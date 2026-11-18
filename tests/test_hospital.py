"""tests/test_hospital.py"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from services.ledger import get_current_state


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app({"TESTING": True, "DATABASE": db_path, "DEV_MODE": True})
    with app.app_context():
        yield app.test_client()


def _setup_referral(client):
    r1 = client.post("/api/screening", json={
        "patient": {"age_band": "40-49", "insurance_type": "nhia",
                    "nhia_number": "NHIA-001", "phone": "+2348000000001"},
        "consent": {"version": "1.0", "scope": ["screening", "referral", "follow_up"]},
        "screening": {"pharmacy_id": "PHARM-A", "systolic": 168, "diastolic": 104,
                      "symptoms": [], "protocol_version": "HTN-PROTOCOL-v1"},
        "actor_id": "pharm@x",
    })
    assert r1.status_code == 201
    s = r1.get_json()
    r2 = client.post("/api/referral", json={
        "screening_id": s["screening"]["id"],
        "facility_id": "HOSP-A",
        "actor_id": "pharm@x",
    })
    assert r2.status_code == 201
    return s["patient_id"], r2.get_json()["referral_id"]


def test_queue_lists_open_referrals(client):
    patient_id, referral_id = _setup_referral(client)
    r = client.get("/api/hospital/queue")
    assert r.status_code == 200
    q = r.get_json()["queue"]
    assert any(row["id"] == referral_id for row in q)


def test_accept_referral(client):
    patient_id, referral_id = _setup_referral(client)
    r = client.post(f"/api/referrals/{referral_id}/accept", json={"actor_id": "hosp@x"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["event"]["event_type"] == "FACILITY_ACCEPTED"
    assert get_current_state(patient_id) == "FACILITY_ACCEPTED"


def test_full_canonical_loop(client):
    patient_id, referral_id = _setup_referral(client)
    client.post(f"/api/referrals/{referral_id}/accept", json={"actor_id": "hosp@x"})
    r = client.post(f"/api/referrals/{referral_id}/book", json={
        "actor_id": "hosp@x",
        "slot_start": "2026-11-20T09:00:00Z",
        "slot_end": "2026-11-20T09:30:00Z",
    })
    assert r.status_code == 200
    assert get_current_state(patient_id) == "APPOINTMENT_BOOKED"

    r = client.post(f"/api/referrals/{referral_id}/attest", json={
        "actor_id": "hosp@x", "clinician_id": "doc@x", "notes": "seen",
    })
    assert r.status_code == 200
    assert get_current_state(patient_id) == "CLINICAL_ENCOUNTER_COMPLETED"

    r = client.post(f"/api/referrals/{referral_id}/counter-refer", json={
        "actor_id": "doc@x", "clinician_id": "doc@x",
        "outcome": "started_medication", "next_step": "BP review in 30 days",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["event"]["event_type"] == "CLINICAL_DISPOSITION_RETURNED"
    assert get_current_state(patient_id) == "CLINICAL_DISPOSITION_RETURNED"

    v = client.get(f"/api/audit/verify/{patient_id}").get_json()
    assert v["ok"] is True
    assert v["events"] == 6


def test_attest_without_book_is_rejected(client):
    patient_id, referral_id = _setup_referral(client)
    client.post(f"/api/referrals/{referral_id}/accept", json={"actor_id": "hosp@x"})
    r = client.post(f"/api/referrals/{referral_id}/attest", json={
        "actor_id": "hosp@x", "clinician_id": "doc@x",
    })
    assert r.status_code == 400
    assert r.get_json()["error"] == "invalid_transition"
    assert get_current_state(patient_id) == "FACILITY_ACCEPTED"


def test_decline_with_auto_redirect(client):
    patient_id, referral_id = _setup_referral(client)
    r = client.post(f"/api/referrals/{referral_id}/decline", json={
        "actor_id": "hosp@x",
        "reason_code": "no_slots",
        "owner": "care_navigator",
        "next_facility_id": "HOSP-B",
    })
    assert r.status_code == 200
    body = r.get_json()
    assert body["decline_event"]["event_type"] == "REFERRAL_DECLINED"
    assert body["redirected_to"] == "HOSP-B"
    assert body["new_referral_id"]
    assert body["redirect_event"]["event_type"] == "REFERRAL_CREATED"
    assert get_current_state(patient_id) == "REFERRAL_CREATED"


def test_referral_history_shows_events(client):
    patient_id, referral_id = _setup_referral(client)
    client.post(f"/api/referrals/{referral_id}/accept", json={"actor_id": "hosp@x"})
    r = client.get(f"/api/referrals/{referral_id}/history")
    assert r.status_code == 200
    types = [e["event_type"] for e in r.get_json()["events"]]
    assert "REFERRAL_CREATED" in types
    assert "FACILITY_ACCEPTED" in types