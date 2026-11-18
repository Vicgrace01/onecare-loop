"""
OneCare Loop — services/patient.py

Patient receipt formatter. Every event type gets a headline.
Auxiliary events (PATIENT_ACKNOWLEDGED, CONFIRMATORY_TEST) render as
thread messages but do NOT enter the 6-node canonical ring.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from models import connect_db
from services.ledger import utc_now, verify_patient_chain


HEADLINES = {
    "SCREEN_POSITIVE": ("Your blood pressure was checked", None),
    "REFERRAL_CREATED": ("You were referred to a clinic", "facility_id"),
    "FACILITY_ACCEPTED": ("The clinic accepted your referral", "facility_id"),
    "APPOINTMENT_BOOKED": ("Your appointment is booked", "slot_start"),
    "CLINICAL_ENCOUNTER_COMPLETED": ("You were seen by a clinician", None),
    "CLINICAL_DISPOSITION_RETURNED": ("Your result and next steps are ready", "outcome"),
    "PATIENT_ACKNOWLEDGED": ("You confirmed you understood", "message"),
    "CONFIRMATORY_TEST": ("A confirmatory reading was recorded", "systolic"),
    "REFERRAL_DECLINED": ("The clinic could not take you", "reason_code"),
    "FACILITY_UNAVAILABLE": ("No clinic was available this time", "reason_code"),
    "APPOINTMENT_MISSED": ("You missed your appointment", "reason_code"),
    "PATIENT_UNREACHABLE": ("We could not reach you", "reason_code"),
    "PATIENT_DECLINED": ("You declined the referral", "reason_code"),
    "PATIENT_REQUESTED_RESCHEDULE": ("You asked to reschedule", "reason_code"),
    "REFERRAL_REDIRECTED": ("Your referral was sent to another clinic", "next_facility_id"),
    "FOLLOWUP_OVERDUE": ("Your follow-up is overdue", "due_date"),
    "FOLLOWUP_DUE": ("Your follow-up is due", "due_date"),
    "REPEAT_ASSESSMENT": ("Your blood pressure was checked again", None),
    "BP_CONTROL_RECORDED": ("Your blood pressure control was recorded", None),
    "CONSENT_REVOKED": ("Your consent was revoked", None),
}


def _log_access(actor_id: str, resource_type: str, resource_id: str, purpose: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO access_logs (id, actor_id, resource_type, resource_id, purpose, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), actor_id, resource_type, resource_id, purpose, utc_now()),
        )
    finally:
        conn.close()


def _to_message(event: dict, chain_ok: bool) -> dict[str, Any]:
    payload = json.loads(event["payload_json"])
    headline, detail_key = HEADLINES.get(
        event["event_type"], ("Update recorded", None)
    )

    detail_parts: list[str] = []
    if event["event_type"] == "SCREEN_POSITIVE":
        detail_parts.append(f"Reading: {payload.get('systolic')}/{payload.get('diastolic')} mmHg")
    elif event["event_type"] == "CONFIRMATORY_TEST":
        sbp = payload.get("systolic")
        dbp = payload.get("diastolic")
        if sbp and dbp:
            detail_parts.append(f"Reading: {sbp}/{dbp} mmHg")
    elif detail_key and detail_key in payload:
        detail_parts.append(f"{detail_key.replace('_', ' ').title()}: {payload[detail_key]}")

    if event["event_type"] == "REFERRAL_CREATED":
        urgency = payload.get("urgency")
        if urgency:
            detail_parts.append(f"Urgency: {urgency}")

    if event["event_type"] == "CLINICAL_DISPOSITION_RETURNED":
        next_step = payload.get("next_step")
        if next_step:
            detail_parts.append(f"Next step: {next_step}")

    return {
        "seq": event["seq"],
        "event_type": event["event_type"],
        "actor_role": event["actor_role"],
        "occurred_at": event["occurred_at"],
        "headline": headline,
        "detail": " · ".join(detail_parts) if detail_parts else "",
        "hash_short": event["hash"][:12],
        "hash": event["hash"],
        "verified": chain_ok,
    }


def get_receipt(patient_id: str, viewer_id: str | None = None) -> dict[str, Any]:
    conn = connect_db()
    try:
        events_rows = conn.execute(
            "SELECT * FROM loop_events WHERE patient_id = ? ORDER BY seq ASC",
            (patient_id,),
        ).fetchall()

        if not events_rows:
            raise LookupError(f"no events for patient {patient_id}")

        events = [dict(r) for r in events_rows]
        verification = verify_patient_chain(conn, patient_id)
    finally:
        conn.close()

    if viewer_id:
        _log_access(viewer_id, "patient_receipt", patient_id, "patient_viewed_own_receipt")

    chain_ok = bool(verification.get("ok"))
    messages = [_to_message(e, chain_ok) for e in events]

    return {
        "patient_id": patient_id,
        "messages": messages,
        "verified": chain_ok,
        "head_hash": verification.get("head_hash"),
        "broken_at": verification.get("broken_at"),
        "verify_url": f"/api/audit/verify/{patient_id}",
        "checked_at": utc_now(),
    }


def confirm_attendance(patient_id: str, note: str = "") -> dict[str, Any]:
    conn = connect_db()
    try:
        exists = conn.execute(
            "SELECT 1 FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        if not exists:
            raise ValueError(f"patient {patient_id} not found")

        conn.execute(
            "INSERT INTO notifications "
            "(id, patient_id, channel, template_id, language, sent_at, reply_class, reply_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), patient_id, "whatsapp", "attendance_confirm", "en",
                utc_now(), "attendance_confirmed", note or "I attended", utc_now(),
            ),
        )
    finally:
        conn.close()

    return {
        "patient_id": patient_id,
        "recorded": True,
        "note": "hospital attestation is still required for canonical state transition",
    }