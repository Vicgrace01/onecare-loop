"""
OneCare Loop — services\red_flag.py

Deterministic red-flag detection + alert logging.

SIMULATE: the alert is written to loop_exceptions and returned to the caller.
It is NOT paged to an ambulance dispatcher. That integration is Coming Soon.
"""

from __future__ import annotations

import uuid

from models import connect_db
from services.ledger import utc_now


SBP_THRESHOLD = 180
DBP_THRESHOLD = 120
RED_FLAG_SYMPTOMS = {
    "chest_pain",
    "one_sided_weakness",
    "vision_loss",
    "severe_headache",
    "shortness_of_breath",
}


def detect(systolic: int, diastolic: int, symptoms: list[str]) -> dict:
    triggers: list[str] = []
    if systolic >= SBP_THRESHOLD:
        triggers.append(f"systolic_{SBP_THRESHOLD}_plus")
    if diastolic >= DBP_THRESHOLD:
        triggers.append(f"diastolic_{DBP_THRESHOLD}_plus")
    for symptom in symptoms:
        if symptom in RED_FLAG_SYMPTOMS:
            triggers.append(f"symptom_{symptom}")
    return {"is_red_flag": bool(triggers), "triggers": triggers}


def log_alert(referral_id: str, patient_id: str, triggers: list[str]) -> dict:
    """
    SIMULATE — writes to loop_exceptions with event_type=RED_FLAG_EMERGENCY.
    No external paging. Returns a record explaining what WOULD have been paged.
    """
    alert_id = str(uuid.uuid4())
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM referrals WHERE id = ?", (referral_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "referral_not_found", "referral_id": referral_id}

        conn.execute(
            "INSERT INTO loop_exceptions "
            "(id, referral_id, event_type, reason_code, owner, deadline, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                alert_id,
                referral_id,
                "RED_FLAG_EMERGENCY",
                "red_flag",
                "emergency_coordinator",
                None,
                utc_now(),
            ),
        )
    finally:
        conn.close()

    return {
        "ok": True,
        "alert_id": alert_id,
        "referral_id": referral_id,
        "patient_id": patient_id,
        "triggers": triggers,
        "status": "simulated",
        "paged_to": None,
        "note": (
            "SIMULATED — no ambulance dispatched. In production this would page the "
            "nearest emergency coordinator and open a tracked incident. Flagged in README."
        ),
        "created_at": utc_now(),
    }


def list_open_alerts() -> list[dict]:
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT id, referral_id, reason_code, owner, created_at "
            "FROM loop_exceptions "
            "WHERE event_type = 'RED_FLAG_EMERGENCY' AND resolved_at IS NULL "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()