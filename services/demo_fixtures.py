"""
OneCare Loop — services/demo_fixtures.py

Seeds a cohort of demo patients across all workflow states so the app
feels populated when a judge opens it. Every event goes through the
real state machine — nothing is faked.

Idempotent: re-running does not duplicate patients or events.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models import connect_db
from services.ledger import get_current_state
from services.otp import find_patient_by_phone


DEMO_PHONE = "+2348099000001"
DEMO_DISPLAY_NAME = "Adaeze O."


FIXTURES = [
    # CLOSED loops — full 6-event chain
    {"phone": "+2348099000001", "name": "Adaeze O.",   "insurance": "nhia",     "bp": (185, 122), "symptoms": ["severe_headache"], "target": "CLOSED"},
    {"phone": "+2348099000002", "name": "Chinedu A.",  "insurance": "self_pay", "bp": (168, 104), "symptoms": [],                 "target": "CLOSED"},
    {"phone": "+2348099000003", "name": "Fatima B.",   "insurance": "nhia",     "bp": (175, 110), "symptoms": [],                 "target": "CLOSED"},
    {"phone": "+2348099000010", "name": "Kemi A.",     "insurance": "nhia",     "bp": (160, 100), "symptoms": [],                 "target": "CLOSED"},

    # IN-PROGRESS — mid-workflow states
    {"phone": "+2348099000004", "name": "Tunde O.",    "insurance": "nhia",     "bp": (158,  98), "symptoms": [], "target": "APPOINTMENT_BOOKED"},
    {"phone": "+2348099000005", "name": "Ngozi M.",    "insurance": "self_pay", "bp": (162, 100), "symptoms": [], "target": "FACILITY_ACCEPTED"},
    {"phone": "+2348099000006", "name": "Ibrahim S.",  "insurance": "nhia",     "bp": (148,  92), "symptoms": [], "target": "REFERRAL_CREATED"},
    {"phone": "+2348099000008", "name": "Emeka N.",    "insurance": "nhia",     "bp": (145,  95), "symptoms": [], "target": "REFERRAL_CREATED"},

    # FAILED — failure states (reason + owner recorded)
    {"phone": "+2348099000007", "name": "Blessing E.", "insurance": "self_pay", "bp": (172, 108), "symptoms": [], "target": "REFERRAL_DECLINED"},
    {"phone": "+2348099000009", "name": "Aisha Y.",    "insurance": "nhia",     "bp": (155,  96), "symptoms": [], "target": "PATIENT_UNREACHABLE"},
]


def _has_events(patient_id: str) -> bool:
    conn = connect_db()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM loop_events WHERE patient_id = ?", (patient_id,)
        ).fetchone()[0]
        return n > 0
    finally:
        conn.close()


def _set_display_name(patient_id: str, name: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "UPDATE patients SET display_name = ? WHERE id = ? AND (display_name IS NULL OR display_name = '')",
            (name, patient_id),
        )
    finally:
        conn.close()


def _referral_id_for(patient_id: str) -> str | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT referral_id FROM loop_events "
            "WHERE patient_id = ? AND referral_id IS NOT NULL "
            "ORDER BY seq DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _latest_screening_id(patient_id: str) -> str | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT id FROM screenings WHERE patient_id = ? ORDER BY created_at DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _seed_one(fixture: dict) -> dict:
    from services.screening import run_screening
    from services.referral import create_referral
    from services.hospital import (
        accept_referral, book_appointment, decline_referral,
        attest_attendance, counter_refer,
    )
    from services.loop import record_transition

    phone = fixture["phone"]
    name = fixture["name"]
    target = fixture["target"]

    existing_pid = find_patient_by_phone(phone)

    # Idempotent skip — already has events
    if existing_pid and _has_events(existing_pid):
        _set_display_name(existing_pid, name)
        return {"phone": phone, "status": "already_seeded", "state": get_current_state(existing_pid)}

    # Create screening if needed
    if not existing_pid:
        systolic, diastolic = fixture["bp"]
        result = run_screening({
            "patient": {
                "age_band": "40-49",
                "insurance_type": fixture["insurance"],
                "nhia_number": ("NHIA-" + phone[-4:]) if fixture["insurance"] == "nhia" else None,
                "phone": phone,
            },
            "consent": {"version": "1.0", "scope": ["screening", "referral", "follow_up"]},
            "screening": {
                "pharmacy_id": "PHARM-A",
                "systolic": systolic,
                "diastolic": diastolic,
                "symptoms": fixture["symptoms"],
                "protocol_version": "HTN-PROTOCOL-v1",
            },
            "actor_id": "pharmacy@onecare.demo",
        })
        pid = result["patient_id"]
        screening_id = result["screening"]["id"]
    else:
        pid = existing_pid
        screening_id = _latest_screening_id(pid)
        if not screening_id:
            return {"phone": phone, "status": "error", "reason": "no_screening"}

    _set_display_name(pid, name)
    state = get_current_state(pid)

    # Short-circuit if already at target (partial-state fixtures)
    if target == "CLOSED" and state == "CLINICAL_DISPOSITION_RETURNED":
        return {"phone": phone, "status": "already_seeded", "state": state}
    if target in ("REFERRAL_CREATED", "REFERRAL_DECLINED", "PATIENT_UNREACHABLE") and state in (
        "REFERRAL_CREATED", "REFERRAL_DECLINED", "PATIENT_UNREACHABLE"
    ):
        return {"phone": phone, "status": "already_seeded", "state": state}

    # Walk forward from SCREEN_POSITIVE
    if state == "SCREEN_POSITIVE":
        ref = create_referral({
            "screening_id": screening_id,
            "facility_id": "HOSP-A",
            "actor_id": "pharmacy@onecare.demo",
        })
        referral_id = ref["referral_id"]
        state = "REFERRAL_CREATED"
    else:
        referral_id = _referral_id_for(pid)

    if not referral_id:
        return {"phone": phone, "status": "error", "reason": "no_referral"}

    # ---- Partial states ----
    if target == "REFERRAL_CREATED":
        return {"phone": phone, "status": "seeded", "state": "REFERRAL_CREATED"}

    if target == "REFERRAL_DECLINED" and state == "REFERRAL_CREATED":
        decline_referral(referral_id, "hospital@onecare.demo", "no_slots", "care_navigator")
        return {"phone": phone, "status": "seeded", "state": "REFERRAL_DECLINED"}

    if target == "PATIENT_UNREACHABLE" and state == "REFERRAL_CREATED":
        record_transition(
            patient_id=pid,
            to_state="PATIENT_UNREACHABLE",
            actor_id="pharmacy@onecare.demo",
            actor_role="pharmacy",
            payload={
                "referral_id": referral_id,
                "reason_code": "no_answer_after_3_attempts",
                "owner": "care_navigator",
            },
            referral_id=referral_id,
        )
        return {"phone": phone, "status": "seeded", "state": "PATIENT_UNREACHABLE"}

    # ---- Advance through full loop ----
    if state == "REFERRAL_CREATED":
        accept_referral(referral_id, "hospital@onecare.demo")
        state = "FACILITY_ACCEPTED"

    if target == "FACILITY_ACCEPTED":
        return {"phone": phone, "status": "seeded", "state": "FACILITY_ACCEPTED"}

    if state == "FACILITY_ACCEPTED":
        now = datetime.now(timezone.utc)
        start = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        end = (now + timedelta(minutes=30)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        book_appointment(referral_id, "hospital@onecare.demo", slot_start=start, slot_end=end)
        state = "APPOINTMENT_BOOKED"

    if target == "APPOINTMENT_BOOKED":
        return {"phone": phone, "status": "seeded", "state": "APPOINTMENT_BOOKED"}

    if state == "APPOINTMENT_BOOKED":
        attest_attendance(referral_id, "hospital@onecare.demo", "clinician@onecare.demo", notes="seen")
        state = "CLINICAL_ENCOUNTER_COMPLETED"

    if state == "CLINICAL_ENCOUNTER_COMPLETED":
        counter_refer(
            referral_id,
            "clinician@onecare.demo",
            "clinician@onecare.demo",
            outcome="started_medication",
            next_step="BP review in 30 days",
        )
        state = "CLINICAL_DISPOSITION_RETURNED"

    return {"phone": phone, "status": "seeded", "state": state}


def seed_all() -> dict:
    """Seed the full cohort. Idempotent. Returns a summary."""
    results = []
    for fixture in FIXTURES:
        try:
            results.append(_seed_one(fixture))
        except Exception as e:
            results.append({"phone": fixture["phone"], "status": "error", "reason": str(e)})

    return {
        "total": len(FIXTURES),
        "seeded": sum(1 for r in results if r["status"] == "seeded"),
        "already_seeded": sum(1 for r in results if r["status"] == "already_seeded"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
    }