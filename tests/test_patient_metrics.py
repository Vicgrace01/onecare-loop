"""tests/test_patient_metrics.py"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app({"TESTING": True, "DATABASE": db_path, "DEV_MODE": True})
    with app.app_context():
        yield app.test_client()


def _full_loop(client, phone="+2348011110001", nhia="NHIA-P1"):
    r1 = client.post("/api/screening", json={
        "patient": {"age_band": "40-49", "insurance_type": "nhia",
                    "nhia_number": nhia, "phone": phone},
        "consent": {"version": "1.0", "scope": ["screening", "referral", "follow_up"]},
        "screening": {"pharmacy_id": "PHARM-A", "systolic": 170, "diastolic": 105,
                      "symptoms": [], "protocol_version": "HTN-PROTOCOL-v1"},
        "actor_id": "pharm@x",
    })
    s = r1.get_json()
    patient_id = s["patient_id"]

    r2 = client.post("/api/referral", json={
        "screening_id": s["screening"]["id"],
        "facility_id": "HOSP-A",
        "actor_id": "pharm@x",
    })
    referral_id = r2.get_json()["referral_id"]

    client.post(f"/api/referrals/{referral_id}/accept", json={"actor_id": "hosp@x"})
    client.post(f"/api/referrals/{referral_id}/book", json={
        "actor_id": "hosp@x",
        "slot_start": "2026-11-20T09:00:00Z",
        "slot_end": "2026-11-20T09:30:00Z",
    })
    client.post(f"/api/referrals/{referral_id}/attest", json={
        "actor_id": "hosp@x", "clinician_id": "doc@x",
    })
    client.post(f"/api/referrals/{referral_id}/counter-refer", json={
        "actor_id": "doc@x", "clinician_id": "doc@x",
        "outcome": "started_medication", "next_step": "BP review in 30 days",
    })
    return patient_id


def test_patient_receipt_after_full_loop(client):
    patient_id = _full_loop(client)
    r = client.get(f"/api/patient/{patient_id}/receipt")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["verified"] is True
    assert len(body["messages"]) == 6
    seqs = [m["seq"] for m in body["messages"]]
    assert seqs == [1, 2, 3, 4, 5, 6]
    assert body["messages"][0]["headline"] == "Your blood pressure was checked"
    assert body["messages"][5]["headline"] == "Your result and next steps are ready"
    assert all(m["verified"] for m in body["messages"])


def test_patient_receipt_logs_access_when_viewer_provided(client):
    patient_id = _full_loop(client, phone="+2348011110002")
    client.get(f"/api/patient/{patient_id}/receipt?viewer_id=patient-self")
    from models import connect_db
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT actor_id, purpose FROM access_logs WHERE resource_type='patient_receipt' AND resource_id=?",
            (patient_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["actor_id"] == "patient-self"
    assert row["purpose"] == "patient_viewed_own_receipt"


def test_patient_receipt_404_for_unknown_patient(client):
    r = client.get("/api/patient/does-not-exist/receipt")
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_found"


def test_confirm_attendance_does_not_move_state(client):
    patient_id = _full_loop(client, phone="+2348011110003")
    from services.ledger import get_current_state
    before = get_current_state(patient_id)

    r = client.post(f"/api/patient/{patient_id}/confirm-attendance",
                    json={"note": "I was there"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["recorded"] is True
    assert "hospital attestation" in body["note"]

    after = get_current_state(patient_id)
    assert after == before  # patient confirmation did not change canonical state


def test_metrics_empty_db(client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    assert body["total_patients"] == 0
    assert body["closure_rate"] == 0.0
    assert body["closed_loops"] == 0
    assert body["time_to_care_median_hours"] is None


def test_metrics_closure_rate_after_one_loop(client):
    _full_loop(client, phone="+2348011110004")
    body = client.get("/api/metrics").get_json()
    assert body["total_patients"] == 1
    assert body["closed_loops"] == 1
    assert body["closure_rate"] == 1.0
    assert body["time_to_care_median_hours"] is not None
    assert body["money_recovered_kobo"] == 600000
    assert body["money_recovered_naira"] == 6000
    assert body["simulated"] is True


def test_metrics_failure_breakdown(client):
    # one full loop + one declined referral
    _full_loop(client, phone="+2348011110005")
    r1 = client.post("/api/screening", json={
        "patient": {"age_band": "40-49", "insurance_type": "nhia",
                    "nhia_number": "NHIA-P2", "phone": "+2348011110006"},
        "consent": {"version": "1.0", "scope": ["screening", "referral"]},
        "screening": {"pharmacy_id": "PHARM-A", "systolic": 165, "diastolic": 100,
                      "symptoms": [], "protocol_version": "HTN-PROTOCOL-v1"},
        "actor_id": "pharm@x",
    })
    s = r1.get_json()
    r2 = client.post("/api/referral", json={
        "screening_id": s["screening"]["id"],
        "facility_id": "HOSP-B",
        "actor_id": "pharm@x",
    })
    rid = r2.get_json()["referral_id"]
    client.post(f"/api/referrals/{rid}/decline", json={
        "actor_id": "hosp@x",
        "reason_code": "no_slots",
        "owner": "care_navigator",
    })

    body = client.get("/api/metrics").get_json()
    assert body["total_patients"] == 2
    assert body["closed_loops"] == 1
    assert body["closure_rate"] == 0.5
    assert body["failure_breakdown"].get("REFERRAL_DECLINED") == 1


def test_provider_metrics_internal_only(client):
    _full_loop(client, phone="+2348011110007")
    body = client.get("/api/metrics/providers").get_json()
    assert body["ok"] is True
    assert body["public_exposure_enabled"] is False
    assert any(p["facility_id"] == "HOSP-A" for p in body["providers"])