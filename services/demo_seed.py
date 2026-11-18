"""
OneCare Loop — services/demo_seed.py

Walk a patient through the full 6-event canonical loop using the real
state machine and real services. Nothing is faked — every event goes
through record_transition with a guard, gets signed, and lands in the
chain.

Used by the patient receipt page's "Run a full demo journey" button so
the demo can be exercised without needing the admin surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from models import connect_db
from services.ledger import get_current_state, utc_now


def _get_patient(patient_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _decrypt_phone(patient_id: str) -> str | None:
    from services.crypto import decrypt, get_master_key, unwrap_key
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT pc.phone_encrypted, ks.wrapped_key, ks.shredded_at "
            "FROM patient_contacts pc "
            "LEFT JOIN key_store ks ON ks.patient_id = pc.patient_id "
            "WHERE pc.patient_id = ? LIMIT 1",
            (patient_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row or row["shredded_at"] or not row["wrapped_key"] or not row["phone_encrypted"]:
        return None
    try:
        master = get_master_key()
        key = unwrap_key(master, row["wrapped_key"])
        return decrypt(key, row["phone_encrypted"])
    except Exception:
        return None


def _latest_screening(patient_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM screenings WHERE patient_id = ? ORDER BY created_at DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _referral_from_events(patient_id: str) -> str | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT referral_id FROM loop_events "
            "WHERE patient_id = ? AND referral_id IS NOT NULL "
            "ORDER BY seq DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        return row["referral_id"] if row else None
    finally:
        conn.close()


def _event_count(patient_id: str) -> int:
    conn = connect_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM loop_events WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()["n"]
    finally:
        conn.close()


def seed_full_journey(patient_id: str) -> dict:
    """
    Walk forward from whatever state the patient is in to
    CLINICAL_DISPOSITION_RETURNED. Idempotent — if already closed, returns
    already_complete=True.
    """
    state = get_current_state(patient_id)

    if state == "CLINICAL_DISPOSITION_RETURNED":
        return {
            "ok": True,
            "already_complete": True,
            "created": [],
            "final_state": state,
            "events": _event_count(patient_id),
        }

    created: list[str] = []
    referral_id: str | None = None

    # ---- Ensure SCREEN_POSITIVE ----------------------------------------
    if state is None:
        screening = _latest_screening(patient_id)
        if screening:
            from services.loop import start_loop
            start_loop(
                patient_id,
                "pharmacy@onecare.demo",
                "pharmacy",
                {
                    "systolic": screening["systolic"],
                    "diastolic": screening["diastolic"],
                    "protocol_version": screening["protocol_version"],
                    "result": screening["result"],
                    "red_flag": bool(screening["red_flag"]),
                },
            )
        else:
            phone = _decrypt_phone(patient_id)
            if not phone:
                return {
                    "ok": False,
                    "error": "no_phone_to_screen",
                    "message": (
                        "This patient has no phone on file (or the key was shredded), "
                        "so no new screening can be created."
                    ),
                }
            patient = _get_patient(patient_id) or {}
            from services.screening import run_screening
            run_screening({
                "patient": {
                    "id": patient_id,
                    "age_band": patient.get("age_band") or "40-49",
                    "insurance_type": patient.get("insurance_type") or "nhia",
                    "nhia_number": patient.get("nhia_number") or "NHIA-DEMO",
                    "phone": phone,
                },
                "consent": {
                    "version": "1.0",
                    "scope": ["screening", "referral", "follow_up"],
                },
                "screening": {
                    "pharmacy_id": "PHARM-A",
                    "systolic": 185,
                    "diastolic": 122,
                    "symptoms": ["severe_headache"],
                    "protocol_version": "HTN-PROTOCOL-v1",
                },
                "actor_id": "pharmacy@onecare.demo",
            })
        created.append("SCREEN_POSITIVE")
        state = "SCREEN_POSITIVE"

    # ---- Ensure REFERRAL_CREATED ---------------------------------------
    if state == "SCREEN_POSITIVE":
        screening = _latest_screening(patient_id)
        if not screening:
            return {"ok": False, "error": "no_screening_for_referral", "created": created}
        from services.referral import create_referral
        ref = create_referral({
            "screening_id": screening["id"],
            "facility_id": "HOSP-A",
            "actor_id": "pharmacy@onecare.demo",
        })
        referral_id = ref["referral_id"]
        created.append("REFERRAL_CREATED")
        state = "REFERRAL_CREATED"

    if referral_id is None:
        referral_id = _referral_from_events(patient_id)

    if not referral_id:
        return {"ok": False, "error": "no_referral_found", "created": created}

    # ---- Walk forward --------------------------------------------------
    from services.hospital import (
        accept_referral,
        attest_attendance,
        book_appointment,
        counter_refer,
    )

    if state == "REFERRAL_CREATED":
        accept_referral(referral_id, "hospital@onecare.demo")
        created.append("FACILITY_ACCEPTED")
        state = "FACILITY_ACCEPTED"

    if state == "FACILITY_ACCEPTED":
        now = datetime.now(timezone.utc)
        start = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        end = (now + timedelta(minutes=30)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        book_appointment(referral_id, "hospital@onecare.demo", slot_start=start, slot_end=end)
        created.append("APPOINTMENT_BOOKED")
        state = "APPOINTMENT_BOOKED"

    if state == "APPOINTMENT_BOOKED":
        attest_attendance(referral_id, "hospital@onecare.demo", "clinician@onecare.demo", notes="seen")
        created.append("CLINICAL_ENCOUNTER_COMPLETED")
        state = "CLINICAL_ENCOUNTER_COMPLETED"

    if state == "CLINICAL_ENCOUNTER_COMPLETED":
        counter_refer(
            referral_id,
            "clinician@onecare.demo",
            "clinician@onecare.demo",
            outcome="started_medication",
            next_step="BP review in 30 days",
        )
        created.append("CLINICAL_DISPOSITION_RETURNED")
        state = "CLINICAL_DISPOSITION_RETURNED"

    return {
        "ok": True,
        "created": created,
        "final_state": state,
        "events": _event_count(patient_id),
    }