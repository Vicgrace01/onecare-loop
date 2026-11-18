"""
OneCare Loop — services/loop.py

The state machine.
6 canonical states, 8 failure states, 3 longitudinal states.
Every transition is guarded. Every invalid transition raises TransitionError.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from models import connect_db
from services.ledger import append_event, get_current_state, utc_now


CANONICAL_STATES = frozenset({
    "SCREEN_POSITIVE",
    "REFERRAL_CREATED",
    "FACILITY_ACCEPTED",
    "APPOINTMENT_BOOKED",
    "CLINICAL_ENCOUNTER_COMPLETED",
    "CLINICAL_DISPOSITION_RETURNED",
})

FAILURE_STATES = frozenset({
    "REFERRAL_DECLINED",
    "FACILITY_UNAVAILABLE",
    "APPOINTMENT_MISSED",
    "PATIENT_UNREACHABLE",
    "PATIENT_DECLINED",
    "PATIENT_REQUESTED_RESCHEDULE",
    "REFERRAL_REDIRECTED",
    "FOLLOWUP_OVERDUE",
})

LONGITUDINAL_STATES = frozenset({
    "FOLLOWUP_DUE",
    "REPEAT_ASSESSMENT",
    "BP_CONTROL_RECORDED",
})

ALL_STATES = CANONICAL_STATES | FAILURE_STATES | LONGITUDINAL_STATES


class TransitionError(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def _require(payload: dict, key: str, reason: str) -> Any:
    value = payload.get(key)
    if value is None or value == "" or value is False:
        raise TransitionError(reason, f"Missing required field: {key}")
    return value


def guard_valid_consent(payload, actor_role):
    _require(payload, "consent_version", "missing_consent")
    _require(payload, "consent_hash", "missing_consent")


def guard_hospital_actor(payload, actor_role):
    if actor_role != "hospital":
        raise TransitionError("wrong_actor", f"Transition requires hospital actor, got {actor_role}")
    if not payload.get("actor_authenticated"):
        raise TransitionError("unauthenticated", "Actor must be authenticated")


def guard_date_and_facility(payload, actor_role):
    _require(payload, "slot_start", "missing_slot")
    _require(payload, "facility_id", "missing_facility")


def guard_attendance_attested(payload, actor_role):
    if not payload.get("attended"):
        raise TransitionError("not_attended", "attended must be true")


def guard_clinician_signed(payload, actor_role):
    if actor_role not in ("clinician", "hospital"):
        raise TransitionError("wrong_actor", f"Requires clinician/hospital, got {actor_role}")
    _require(payload, "clinician_id", "missing_clinician")
    _require(payload, "outcome", "missing_outcome")


def guard_reason_and_owner(payload, actor_role):
    _require(payload, "referral_id", "missing_referral_id")
    _require(payload, "reason_code", "missing_reason_code")
    _require(payload, "owner", "missing_owner")


def guard_new_facility(payload, actor_role):
    _require(payload, "facility_id", "missing_facility")
    prev = payload.get("previous_facility_id")
    if prev and prev == payload["facility_id"]:
        raise TransitionError("same_facility", "New facility must differ from previous")


def guard_redirect(payload, actor_role):
    guard_reason_and_owner(payload, actor_role)
    _require(payload, "next_facility_id", "missing_next_facility")


def guard_reschedule(payload, actor_role):
    _require(payload, "slot_start", "missing_slot")
    _require(payload, "facility_id", "missing_facility")


def guard_followup_scheduled(payload, actor_role):
    _require(payload, "due_date", "missing_due_date")
    _require(payload, "followup_type", "missing_followup_type")


def guard_measurement_recorded(payload, actor_role):
    _require(payload, "systolic", "missing_measurement")
    _require(payload, "diastolic", "missing_measurement")


def guard_bp_reading_recorded(payload, actor_role):
    _require(payload, "bp_controlled", "missing_bp_control")
    _require(payload, "systolic", "missing_measurement")
    _require(payload, "diastolic", "missing_measurement")


GUARDS: dict[str, Callable[[dict, str], None]] = {
    "valid_consent": guard_valid_consent,
    "hospital_actor": guard_hospital_actor,
    "date_and_facility": guard_date_and_facility,
    "attendance_attested": guard_attendance_attested,
    "clinician_signed": guard_clinician_signed,
    "reason_and_owner": guard_reason_and_owner,
    "new_facility": guard_new_facility,
    "redirect": guard_redirect,
    "reschedule": guard_reschedule,
    "followup_scheduled": guard_followup_scheduled,
    "measurement_recorded": guard_measurement_recorded,
    "bp_reading_recorded": guard_bp_reading_recorded,
}


VALID_TRANSITIONS: dict[tuple[str, str], str] = {
    # Canonical forward
    ("SCREEN_POSITIVE", "REFERRAL_CREATED"): "valid_consent",
    ("REFERRAL_CREATED", "FACILITY_ACCEPTED"): "hospital_actor",
    ("FACILITY_ACCEPTED", "APPOINTMENT_BOOKED"): "date_and_facility",
    ("APPOINTMENT_BOOKED", "CLINICAL_ENCOUNTER_COMPLETED"): "attendance_attested",
    ("CLINICAL_ENCOUNTER_COMPLETED", "CLINICAL_DISPOSITION_RETURNED"): "clinician_signed",

    # Failure entries
    ("REFERRAL_CREATED", "REFERRAL_DECLINED"): "reason_and_owner",
    ("REFERRAL_CREATED", "FACILITY_UNAVAILABLE"): "reason_and_owner",
    ("REFERRAL_CREATED", "PATIENT_UNREACHABLE"): "reason_and_owner",
    ("REFERRAL_CREATED", "PATIENT_DECLINED"): "reason_and_owner",
    ("FACILITY_ACCEPTED", "PATIENT_UNREACHABLE"): "reason_and_owner",
    ("FACILITY_ACCEPTED", "PATIENT_DECLINED"): "reason_and_owner",
    ("APPOINTMENT_BOOKED", "APPOINTMENT_MISSED"): "reason_and_owner",
    ("APPOINTMENT_BOOKED", "PATIENT_UNREACHABLE"): "reason_and_owner",
    ("APPOINTMENT_BOOKED", "PATIENT_DECLINED"): "reason_and_owner",
    ("APPOINTMENT_BOOKED", "PATIENT_REQUESTED_RESCHEDULE"): "reason_and_owner",
    ("CLINICAL_DISPOSITION_RETURNED", "FOLLOWUP_OVERDUE"): "reason_and_owner",

    # Failure recovery
    ("REFERRAL_DECLINED", "REFERRAL_CREATED"): "new_facility",
    ("FACILITY_UNAVAILABLE", "REFERRAL_CREATED"): "new_facility",
    ("REFERRAL_DECLINED", "REFERRAL_REDIRECTED"): "redirect",
    ("FACILITY_UNAVAILABLE", "REFERRAL_REDIRECTED"): "redirect",
    ("APPOINTMENT_MISSED", "APPOINTMENT_BOOKED"): "reschedule",
    ("PATIENT_REQUESTED_RESCHEDULE", "APPOINTMENT_BOOKED"): "reschedule",
    ("PATIENT_UNREACHABLE", "REFERRAL_CREATED"): "valid_consent",
    ("PATIENT_DECLINED", "REFERRAL_CREATED"): "valid_consent",

    # Longitudinal
    ("CLINICAL_DISPOSITION_RETURNED", "FOLLOWUP_DUE"): "followup_scheduled",
    ("FOLLOWUP_DUE", "REPEAT_ASSESSMENT"): "measurement_recorded",
    ("REPEAT_ASSESSMENT", "BP_CONTROL_RECORDED"): "bp_reading_recorded",
    ("BP_CONTROL_RECORDED", "FOLLOWUP_DUE"): "followup_scheduled",
}


def validate_transition(from_state: str, to_state: str, payload: dict, actor_role: str) -> None:
    if to_state not in ALL_STATES:
        raise TransitionError("unknown_state", f"Unknown target state: {to_state}")
    key = (from_state, to_state)
    if key not in VALID_TRANSITIONS:
        raise TransitionError(
            "invalid_transition",
            f"Cannot transition from {from_state!r} to {to_state!r}",
        )
    guard_name = VALID_TRANSITIONS[key]
    GUARDS[guard_name](payload, actor_role)


def start_loop(
    patient_id: str,
    actor_id: str,
    actor_role: str,
    payload: dict[str, Any],
    referral_id: str | None = None,
) -> dict[str, Any]:
    existing = get_current_state(patient_id)
    if existing is not None:
        raise TransitionError(
            "loop_already_started",
            f"Patient already has events (current: {existing}). Use record_transition.",
        )
    return append_event(patient_id, "SCREEN_POSITIVE", actor_id, actor_role, payload, referral_id)


def record_transition(
    patient_id: str,
    to_state: str,
    actor_id: str,
    actor_role: str,
    payload: dict[str, Any] | None = None,
    referral_id: str | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    current_state = get_current_state(patient_id)
    if current_state is None:
        raise TransitionError(
            "no_active_loop",
            "No events for patient. Call start_loop first.",
        )
    validate_transition(current_state, to_state, payload, actor_role)
    event = append_event(patient_id, to_state, actor_id, actor_role, payload, referral_id)

    if to_state in FAILURE_STATES:
        _write_exception(payload, event, to_state)

    return event


def _write_exception(payload: dict, event: dict, event_type: str) -> None:
    """
    Write to loop_exceptions if a matching referral row exists.
    If no referral row exists (early demo, unit tests), skip silently —
    the reason_code and owner are still validated by the guard.
    """
    referral_id = payload.get("referral_id")
    if not referral_id:
        return

    conn = connect_db()
    try:
        exists = conn.execute(
            "SELECT 1 FROM referrals WHERE id = ?", (referral_id,)
        ).fetchone()
        if not exists:
            return
        conn.execute(
            """
            INSERT INTO loop_exceptions
                (id, referral_id, event_type, reason_code, owner, deadline, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                referral_id,
                event_type,
                payload.get("reason_code"),
                payload.get("owner"),
                payload.get("deadline"),
                utc_now(),
            ),
        )
    finally:
        conn.close()