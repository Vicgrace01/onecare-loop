"""
OneCare Loop — services/longitudinal.py

Longitudinal loop after a closed referral:
CLINICAL_DISPOSITION_RETURNED → FOLLOWUP_DUE → REPEAT_ASSESSMENT → BP_CONTROL_RECORDED → ...

State machine wiring: BUILD.
Auto-triggers on a schedule: SIMULATE — nothing fires on a timer yet. Transitions
happen only when a human POSTs the endpoint. Documented in the README.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from models import connect_db
from services.ledger import get_current_state, utc_now
from services.loop import TransitionError, record_transition


def _schedule_due_date(days: int) -> str:
    deadline = datetime.now(timezone.utc) + timedelta(days=days)
    return deadline.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _create_plan(patient_id: str, days: int, plan_type: str) -> str:
    plan_id = str(uuid.uuid4())
    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO follow_up_plans (id, patient_id, due_date, type, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (plan_id, patient_id, _schedule_due_date(days), plan_type, utc_now()),
        )
    finally:
        conn.close()
    return plan_id


def _close_plan(plan_id: str, status: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "UPDATE follow_up_plans SET status = ? WHERE id = ?",
            (status, plan_id),
        )
    finally:
        conn.close()


def schedule_first_followup(patient_id: str, actor_id: str, days: int = 30) -> dict:
    """CLINICAL_DISPOSITION_RETURNED → FOLLOWUP_DUE."""
    current = get_current_state(patient_id)
    if current != "CLINICAL_DISPOSITION_RETURNED":
        raise TransitionError(
            "invalid_transition",
            f"Cannot schedule follow-up from state {current!r}; "
            f"expected 'CLINICAL_DISPOSITION_RETURNED'",
        )

    plan_id = _create_plan(patient_id, days, "30_day")
    event = record_transition(
        patient_id=patient_id,
        to_state="FOLLOWUP_DUE",
        actor_id=actor_id,
        actor_role="clinician",
        payload={
            "due_date": _schedule_due_date(days),
            "followup_type": "30_day",
            "plan_id": plan_id,
        },
    )
    return {
        "ok": True,
        "patient_id": patient_id,
        "plan_id": plan_id,
        "due_in_days": days,
        "event_type": event["event_type"],
    }


def record_repeat_assessment(
    patient_id: str, actor_id: str, systolic: int, diastolic: int, notes: str = ""
) -> dict:
    """FOLLOWUP_DUE → REPEAT_ASSESSMENT."""
    current = get_current_state(patient_id)
    if current != "FOLLOWUP_DUE":
        raise TransitionError(
            "invalid_transition",
            f"Cannot record assessment from state {current!r}; expected 'FOLLOWUP_DUE'",
        )

    event = record_transition(
        patient_id=patient_id,
        to_state="REPEAT_ASSESSMENT",
        actor_id=actor_id,
        actor_role="pharmacy",
        payload={
            "systolic": systolic,
            "diastolic": diastolic,
            "notes": notes,
        },
    )
    return {
        "ok": True,
        "patient_id": patient_id,
        "systolic": systolic,
        "diastolic": diastolic,
        "event_type": event["event_type"],
    }


def record_bp_control(
    patient_id: str, actor_id: str, systolic: int, diastolic: int, controlled: bool
) -> dict:
    """REPEAT_ASSESSMENT → BP_CONTROL_RECORDED."""
    current = get_current_state(patient_id)
    if current != "REPEAT_ASSESSMENT":
        raise TransitionError(
            "invalid_transition",
            f"Cannot record BP control from state {current!r}; expected 'REPEAT_ASSESSMENT'",
        )

    event = record_transition(
        patient_id=patient_id,
        to_state="BP_CONTROL_RECORDED",
        actor_id=actor_id,
        actor_role="pharmacy",
        payload={
            "systolic": systolic,
            "diastolic": diastolic,
            "bp_controlled": controlled,
        },
    )
    return {
        "ok": True,
        "patient_id": patient_id,
        "bp_controlled": controlled,
        "systolic": systolic,
        "diastolic": diastolic,
        "event_type": event["event_type"],
    }


def schedule_next_followup(patient_id: str, actor_id: str, days: int = 7) -> dict:
    """BP_CONTROL_RECORDED → FOLLOWUP_DUE (loop continues, or exit if patient stable)."""
    current = get_current_state(patient_id)
    if current != "BP_CONTROL_RECORDED":
        raise TransitionError(
            "invalid_transition",
            f"Cannot schedule next follow-up from state {current!r}; expected 'BP_CONTROL_RECORDED'",
        )

    plan_id = _create_plan(patient_id, days, "7_day" if days <= 7 else "30_day")
    event = record_transition(
        patient_id=patient_id,
        to_state="FOLLOWUP_DUE",
        actor_id=actor_id,
        actor_role="clinician",
        payload={
            "due_date": _schedule_due_date(days),
            "followup_type": "7_day" if days <= 7 else "30_day",
            "plan_id": plan_id,
        },
    )
    return {
        "ok": True,
        "patient_id": patient_id,
        "plan_id": plan_id,
        "due_in_days": days,
        "event_type": event["event_type"],
    }


def get_status(patient_id: str) -> dict:
    conn = connect_db()
    try:
        plans = [
            dict(r) for r in conn.execute(
                "SELECT * FROM follow_up_plans WHERE patient_id = ? ORDER BY created_at DESC",
                (patient_id,),
            ).fetchall()
        ]
    finally:
        conn.close()

    state = get_current_state(patient_id)
    return {
        "ok": True,
        "patient_id": patient_id,
        "current_state": state,
        "is_longitudinal": state in ("FOLLOWUP_DUE", "REPEAT_ASSESSMENT", "BP_CONTROL_RECORDED"),
        "plans": plans,
    }