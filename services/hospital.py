"""
OneCare Loop — services/hospital.py

Hospital-side flow: accept, decline (with auto-redirect), book appointment,
attest attendance, counter-refer (clinical disposition).

State machine is the gatekeeper: state is validated first via
services.loop.record_transition. Domain lookups (appointment, encounter)
only run after state validation passes.
"""

from __future__ import annotations

import uuid
from typing import Any

from models import connect_db
from services.dropoff import score_referral
from services.eligibility import mock_check_eligibility
from services.ledger import canonical_json, get_current_state, utc_now
from services.loop import TransitionError, record_transition
from services.referral import compute_sla_deadline
from services.screening import ensure_org


def ensure_user(user_id: str, role: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, f"{user_id}@onecare.demo", "demo-not-real-hash", role, utc_now()),
        )
    finally:
        conn.close()


def _get_referral(referral_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            """
            SELECT r.*, s.patient_id, s.systolic, s.diastolic, s.result, s.red_flag,
                   p.insurance_type, p.nhia_number
            FROM referrals r
            JOIN screenings s ON s.id = r.screening_id
            JOIN patients p ON p.id = s.patient_id
            WHERE r.id = ?
            """,
            (referral_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_latest_consent(patient_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM consents WHERE patient_id = ? AND revoked_at IS NULL "
            "ORDER BY granted_at DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _update_referral_status(referral_id: str, status: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "UPDATE referrals SET status = ?, cached_updated_at = ? WHERE id = ?",
            (status, utc_now(), referral_id),
        )
    finally:
        conn.close()


def _require_state(patient_id: str, expected: str, action: str) -> None:
    current = get_current_state(patient_id)
    if current != expected:
        raise TransitionError(
            "invalid_transition",
            f"Cannot {action} from state {current!r}; expected {expected!r}",
        )


def get_queue(facility_id: str | None = None) -> list[dict[str, Any]]:
    conn = connect_db()
    try:
        if facility_id:
            rows = conn.execute(
                """
                SELECT r.*, s.patient_id, s.systolic, s.diastolic, s.result, s.red_flag
                FROM referrals r JOIN screenings s ON s.id = r.screening_id
                WHERE r.status IN ('REFERRAL_CREATED', 'FACILITY_ACCEPTED')
                  AND r.facility_id = ?
                ORDER BY
                    CASE r.urgency
                        WHEN 'emergency' THEN 0
                        WHEN 'urgent' THEN 1
                        WHEN 'routine' THEN 2
                        ELSE 3
                    END,
                    r.sla_deadline ASC
                """,
                (facility_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT r.*, s.patient_id, s.systolic, s.diastolic, s.result, s.red_flag
                FROM referrals r JOIN screenings s ON s.id = r.screening_id
                WHERE r.status IN ('REFERRAL_CREATED', 'FACILITY_ACCEPTED')
                ORDER BY
                    CASE r.urgency
                        WHEN 'emergency' THEN 0
                        WHEN 'urgent' THEN 1
                        WHEN 'routine' THEN 2
                        ELSE 3
                    END,
                    r.sla_deadline ASC
                """
            ).fetchall()
    finally:
        conn.close()

    now_iso = utc_now()
    out = []
    for r in rows:
        d = dict(r)
        d["sla_breached"] = d["sla_deadline"] < now_iso
        try:
            score = score_referral(d["id"])
            if score.get("ok"):
                d["dropoff_score"] = score["probability"]
                d["dropoff_tier"] = score["tier"]
        except Exception:
            d["dropoff_score"] = None
            d["dropoff_tier"] = None
        out.append(d)
    return out


def accept_referral(referral_id: str, actor_id: str) -> dict:
    referral = _get_referral(referral_id)
    if not referral:
        raise ValueError(f"referral {referral_id} not found")

    _require_state(referral["patient_id"], "REFERRAL_CREATED", "accept referral")
    ensure_user(actor_id, "hospital")

    event = record_transition(
        patient_id=referral["patient_id"],
        to_state="FACILITY_ACCEPTED",
        actor_id=actor_id,
        actor_role="hospital",
        payload={
            "actor_authenticated": True,
            "facility_id": referral["facility_id"],
            "accepted_at": utc_now(),
        },
        referral_id=referral_id,
    )
    _update_referral_status(referral_id, "FACILITY_ACCEPTED")
    return {"referral_id": referral_id, "patient_id": referral["patient_id"], "event": event}


def decline_referral(
    referral_id: str,
    actor_id: str,
    reason_code: str,
    owner: str,
    next_facility_id: str | None = None,
) -> dict:
    referral = _get_referral(referral_id)
    if not referral:
        raise ValueError(f"referral {referral_id} not found")

    _require_state(referral["patient_id"], "REFERRAL_CREATED", "decline referral")
    ensure_user(actor_id, "hospital")

    decline_event = record_transition(
        patient_id=referral["patient_id"],
        to_state="REFERRAL_DECLINED",
        actor_id=actor_id,
        actor_role="hospital",
        payload={
            "referral_id": referral_id,
            "reason_code": reason_code,
            "owner": owner,
            "facility_id": referral["facility_id"],
        },
        referral_id=referral_id,
    )
    _update_referral_status(referral_id, "REFERRAL_DECLINED")

    result: dict[str, Any] = {
        "referral_id": referral_id,
        "patient_id": referral["patient_id"],
        "decline_event": decline_event,
        "redirected_to": None,
        "new_referral_id": None,
        "redirect_event": None,
    }

    if not next_facility_id:
        return result

    ensure_org(next_facility_id, next_facility_id, "hospital")
    consent = _get_latest_consent(referral["patient_id"])
    if not consent:
        raise TransitionError("missing_consent", "Cannot redirect without active consent")

    new_referral_id = str(uuid.uuid4())
    sla_deadline = compute_sla_deadline(referral["urgency"])

    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO referrals (id, screening_id, facility_id, urgency, sla_deadline, status, cached_updated_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_referral_id, referral["screening_id"], next_facility_id,
             referral["urgency"], sla_deadline, "REFERRAL_CREATED", utc_now(), utc_now()),
        )
    finally:
        conn.close()

    eligibility = mock_check_eligibility(
        referral["patient_id"], next_facility_id,
        referral.get("insurance_type"), referral.get("nhia_number"),
    )
    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO eligibility_checks (id, referral_id, request_json, response_json, policy_version_id, decision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), new_referral_id,
             canonical_json(eligibility["request"]),
             canonical_json(eligibility["response"]),
             None, eligibility["decision"], utc_now()),
        )
    finally:
        conn.close()

    redirect_event = record_transition(
        patient_id=referral["patient_id"],
        to_state="REFERRAL_CREATED",
        actor_id="system@onecare.demo",
        actor_role="hospital",
        payload={
            "facility_id": next_facility_id,
            "previous_facility_id": referral["facility_id"],
            "redirected_from_decline": True,
            "original_referral_id": referral_id,
            "consent_version": consent["version"],
            "consent_hash": consent["hash"],
            "urgency": referral["urgency"],
            "sla_deadline": sla_deadline,
            "eligibility_decision": eligibility["decision"],
            "eligibility_response_id": eligibility["response"]["id"],
        },
        referral_id=new_referral_id,
    )

    result["redirected_to"] = next_facility_id
    result["new_referral_id"] = new_referral_id
    result["redirect_event"] = redirect_event
    return result


def book_appointment(
    referral_id: str,
    actor_id: str,
    slot_start: str,
    slot_end: str,
) -> dict:
    referral = _get_referral(referral_id)
    if not referral:
        raise ValueError(f"referral {referral_id} not found")

    _require_state(referral["patient_id"], "FACILITY_ACCEPTED", "book appointment")
    ensure_user(actor_id, "hospital")

    appointment_id = str(uuid.uuid4())
    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO appointments (id, referral_id, slot_start, slot_end, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (appointment_id, referral_id, slot_start, slot_end, "booked", utc_now()),
        )
    finally:
        conn.close()

    event = record_transition(
        patient_id=referral["patient_id"],
        to_state="APPOINTMENT_BOOKED",
        actor_id=actor_id,
        actor_role="hospital",
        payload={
            "facility_id": referral["facility_id"],
            "slot_start": slot_start,
            "slot_end": slot_end,
            "appointment_id": appointment_id,
        },
        referral_id=referral_id,
    )
    _update_referral_status(referral_id, "APPOINTMENT_BOOKED")
    return {
        "referral_id": referral_id,
        "appointment_id": appointment_id,
        "patient_id": referral["patient_id"],
        "event": event,
    }


def attest_attendance(
    referral_id: str,
    actor_id: str,
    clinician_id: str,
    notes: str = "",
) -> dict:
    referral = _get_referral(referral_id)
    if not referral:
        raise ValueError(f"referral {referral_id} not found")

    _require_state(referral["patient_id"], "APPOINTMENT_BOOKED", "attest attendance")
    ensure_user(actor_id, "hospital")
    ensure_user(clinician_id, "clinician")

    conn = connect_db()
    try:
        appointment = conn.execute(
            "SELECT * FROM appointments WHERE referral_id = ? ORDER BY created_at DESC LIMIT 1",
            (referral_id,),
        ).fetchone()
    finally:
        conn.close()
    if not appointment:
        raise TransitionError("missing_appointment", "State says APPOINTMENT_BOOKED but no appointment row exists")

    encounter_id = str(uuid.uuid4())
    attended_at = utc_now()

    event = record_transition(
        patient_id=referral["patient_id"],
        to_state="CLINICAL_ENCOUNTER_COMPLETED",
        actor_id=actor_id,
        actor_role="hospital",
        payload={
            "attended": True,
            "encounter_id": encounter_id,
            "appointment_id": appointment["id"],
            "clinician_id": clinician_id,
            "attended_at": attended_at,
        },
        referral_id=referral_id,
    )

    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO encounters (id, appointment_id, clinician_id, attended_at, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (encounter_id, appointment["id"], clinician_id, attended_at, notes, attended_at),
        )
        conn.execute(
            "UPDATE appointments SET status = 'attended' WHERE id = ?",
            (appointment["id"],),
        )
    finally:
        conn.close()

    _update_referral_status(referral_id, "CLINICAL_ENCOUNTER_COMPLETED")
    return {
        "referral_id": referral_id,
        "encounter_id": encounter_id,
        "appointment_id": appointment["id"],
        "patient_id": referral["patient_id"],
        "event": event,
    }


def counter_refer(
    referral_id: str,
    actor_id: str,
    clinician_id: str,
    outcome: str,
    next_step: str,
) -> dict:
    referral = _get_referral(referral_id)
    if not referral:
        raise ValueError(f"referral {referral_id} not found")

    _require_state(referral["patient_id"], "CLINICAL_ENCOUNTER_COMPLETED", "counter-refer")
    ensure_user(actor_id, "clinician")
    ensure_user(clinician_id, "clinician")

    conn = connect_db()
    try:
        appointment = conn.execute(
            "SELECT * FROM appointments WHERE referral_id = ? ORDER BY created_at DESC LIMIT 1",
            (referral_id,),
        ).fetchone()
        if not appointment:
            raise TransitionError("missing_appointment", "No appointment for this referral")
        encounter = conn.execute(
            "SELECT * FROM encounters WHERE appointment_id = ? ORDER BY created_at DESC LIMIT 1",
            (appointment["id"],),
        ).fetchone()
        if not encounter:
            raise TransitionError("missing_encounter", "No encounter for this appointment")
    finally:
        conn.close()

    disposition_id = str(uuid.uuid4())
    signed_at = utc_now()

    event = record_transition(
        patient_id=referral["patient_id"],
        to_state="CLINICAL_DISPOSITION_RETURNED",
        actor_id=actor_id,
        actor_role="clinician",
        payload={
            "clinician_id": clinician_id,
            "outcome": outcome,
            "next_step": next_step,
            "disposition_id": disposition_id,
            "encounter_id": encounter["id"],
            "signed_at": signed_at,
            "referral_id": referral_id,
        },
        referral_id=referral_id,
    )

    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO clinical_dispositions (id, encounter_id, outcome, next_step, signed_at, clinician_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (disposition_id, encounter["id"], outcome, next_step, signed_at, clinician_id, signed_at),
        )
    finally:
        conn.close()

    _update_referral_status(referral_id, "CLINICAL_DISPOSITION_RETURNED")
    return {
        "referral_id": referral_id,
        "disposition_id": disposition_id,
        "outcome": outcome,
        "next_step": next_step,
        "patient_id": referral["patient_id"],
        "event": event,
    }


def get_referral_history(referral_id: str) -> list[dict[str, Any]]:
    referral = _get_referral(referral_id)
    if not referral:
        raise ValueError(f"referral {referral_id} not found")
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM loop_events WHERE patient_id = ? AND referral_id = ? ORDER BY seq ASC",
            (referral["patient_id"], referral_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()