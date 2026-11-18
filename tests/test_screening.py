"""tests/test_screening.py"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from services.ledger import get_current_state
from services.screening import ScreeningError, classify, validate_bp


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app({"TESTING": True, "DATABASE": db_path, "DEV_MODE": True})
    with app.app_context():
        yield app.test_client()


def _screening_payload(nhia="NHIA-001", systolic=168, diastolic=104, symptoms=None,
                       phone="+2348000000001"):
    return {
        "patient": {
            "age_band": "40-49",
            "insurance_type": "nhia" if nhia else "self_pay",
            "nhia_number": nhia,
            "phone": phone,
        },
        "consent": {"version": "1.0", "scope": ["screening", "referral", "follow_up"]},
        "screening": {
            "pharmacy_id": "PHARM-A",
            "systolic": systolic,
            "diastolic": diastolic,
            "symptoms": symptoms or [],
            "protocol_version": "HTN-PROTOCOL-v1",
        },
        "actor_id": "pharm@x",
    }


def test_classify_normal_is_negative():
    c = classify(120, 80, [])
    assert c["result"] == "negative"
    assert c["red_flag"] is False
    assert c["urgency"] is None


def test_classify_positive_routine():
    c = classify(145, 95, [])
    assert c["result"] == "positive"
    assert c["urgency"] == "routine"


def test_classify_positive_urgent():
    c = classify(165, 102, [])
    assert c["urgency"] == "urgent"


def test_classify_red_flag_bp():
    c = classify(185, 122, [])
    assert c["red_flag"] is True
    assert c["urgency"] == "emergency"


def test_classify_red_flag_symptom():
    c = classify(145, 95, ["chest_pain"])
    assert c["red_flag"] is True
    assert c["urgency"] == "emergency"


def test_validate_bp_rejects_systolic_le_diastolic():
    with pytest.raises(ScreeningError) as exc:
        validate_bp(80, 120)
    assert exc.value.reason == "invalid_bp"


def test_screening_creates_loop(client):
    resp = client.post("/api/screening", json=_screening_payload())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["ok"] is True
    assert body["screening"]["result"] == "positive"
    assert body["event"]["event_type"] == "SCREEN_POSITIVE"
    assert body["consent"]["hash"]


def test_full_screening_to_referral(client):
    r1 = client.post("/api/screening", json=_screening_payload())
    assert r1.status_code == 201
    s = r1.get_json()
    patient_id = s["patient_id"]
    screening_id = s["screening"]["id"]

    r2 = client.post("/api/referral", json={
        "screening_id": screening_id,
        "facility_id": "HOSP-A",
        "urgency": "urgent",
        "actor_id": "pharm@x",
    })
    assert r2.status_code == 201
    body = r2.get_json()
    assert body["ok"] is True
    assert body["urgency"] == "urgent"
    assert body["eligibility"]["decision"] == "covered"
    assert get_current_state(patient_id) == "REFERRAL_CREATED"


def test_referral_without_nhia_is_not_covered(client):
    payload = _screening_payload(nhia=None)
    r1 = client.post("/api/screening", json=payload)
    s = r1.get_json()
    r2 = client.post("/api/referral", json={
        "screening_id": s["screening"]["id"],
        "facility_id": "HOSP-A",
    })
    assert r2.status_code == 201
    assert r2.get_json()["eligibility"]["decision"] == "not_covered"