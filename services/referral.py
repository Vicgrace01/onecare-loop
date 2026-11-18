"""
OneCare Loop — services/referral.py

Creates a referral: referral row + eligibility check + REFERRAL_CREATED event
+ (SIMULATED) patient SMS + (SIMULATED) red-flag emergency alert.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from models import connect_db
from services.eligibility import mock_check_eligibility
from services.ledger import canonical_json, utc_now
from services.loop import record_transition
from services.screening import ensure_org


SLA_HOURS = {"routine": 72, "urgent": 24, "emergency": 4}


def compute_sla_deadline(urgency: str) -> str:
    hours = SLA_HOURS.get(urgency, 72)
    deadline = datetime.now(timezone.utc) + timedelta(hours=hours)
    return deadline.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _get_screening(screening_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT s.*, p.insurance_type, p.nhia_number FROM screenings s JOIN patients p ON p.id = s.patient_id WHERE s.id = ?",
            (screening_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _get_latest_consent(patient_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT * FROM consents WHERE patient_id = ? AND revoked_at IS NULL ORDER BY granted_at DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _urgency_from_screening(screening: dict, override: str | None) -> str:
    if override:
        return override
    if screening["red_flag"]:
        return "emergency"
    if screening["systolic"] >= 160 or screening["diastolic"] >= 100:
        return "urgent"
    return "routine"


def create_referral(payload: dict) -> dict:
    screening = _get_screening(payload["screening_id"])
    if not screening:
        raise ValueError(f"screening {payload['screening_id']} not found")

    patient_id = screening["patient_id"]
    facility_id = payload["facility_id"]
    urgency = _urgency_from_screening(screening, payload.get("urgency"))

    consent = _get_latest_consent(patient_id)
    if not consent:
        raise ValueError(f"no active consent for patient {patient_id}")

    ensure_org(facility_id, facility_id, "hospital")

    referral_id = str(uuid.uuid4())
    sla_deadline = compute_sla_deadline(urgency)

    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO referrals (id, screening_id, facility_id, urgency, sla_deadline, status, cached_updated_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (referral_id, screening["id"], facility_id, urgency, sla_deadline,
             "REFERRAL_CREATED", utc_now(), utc_now()),
        )
    finally:
        conn.close()

    eligibility = mock_check_eligibility(
        patient_id, facility_id,
        screening.get("insurance_type"), screening.get("nhia_number"),
    )

    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO eligibility_checks (id, referral_id, request_json, response_json, policy_version_id, decision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), referral_id,
                canonical_json(eligibility["request"]),
                canonical_json(eligibility["response"]),
                None, eligibility["decision"], utc_now(),
            ),
        )
    finally:
        conn.close()

    event_payload = {
        "facility_id": facility_id,
        "urgency": urgency,
        "sla_deadline": sla_deadline,
        "consent_version": consent["version"],
        "consent_hash": consent["hash"],
        "eligibility_decision": eligibility["decision"],
        "eligibility_response_id": eligibility["response"]["id"],
    }

    event = record_transition(
        patient_id=patient_id,
        to_state="REFERRAL_CREATED",
        actor_id=payload.get("actor_id", "pharmacy@onecare.demo"),
        actor_role="pharmacy",
        payload=event_payload,
        referral_id=referral_id,
    )

    sms_result = None
    try:
        from services.sms import send as sms_send
        sms_result = sms_send(
            patient_id=patient_id,
            template_id="referral_created",
            channel="sms",
            context={"facility": facility_id, "urgency": urgency},
        )
    except Exception:
        sms_result = {"ok": False, "status": "error"}

    alert_result = None
    if urgency == "emergency":
        try:
            from services.red_flag import detect, log_alert
            import json as _json
            symptoms = _json.loads(screening.get("symptoms_json") or "[]")
            detection = detect(screening["systolic"], screening["diastolic"], symptoms)
            if detection["is_red_flag"]:
                alert_result = log_alert(referral_id, patient_id, detection["triggers"])
        except Exception as e:
            alert_result = {"ok": False, "error": str(e)}

    return {
        "referral_id": referral_id,
        "screening_id": screening["id"],
        "patient_id": patient_id,
        "facility_id": facility_id,
        "urgency": urgency,
        "sla_deadline": sla_deadline,
        "eligibility": eligibility,
        "event": event,
        "notification": sms_result,
        "emergency_alert": alert_result,
    }