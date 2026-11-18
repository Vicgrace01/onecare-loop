"""tests/test_dropoff.py"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from services.dropoff import FEATURES, ensure_model, score_referral


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app({"TESTING": True, "DATABASE": db_path, "DEV_MODE": True})
    with app.app_context():
        yield app.test_client()


def _make_referral(client, insurance="nhia", bp=(180, 118), phone="+2348011100001"):
    r1 = client.post("/api/screening", json={
        "patient": {"age_band": "40-49", "insurance_type": insurance,
                    "nhia_number": "NHIA-D" if insurance == "nhia" else None,
                    "phone": phone},
        "consent": {"version": "1.0", "scope": ["screening", "referral"]},
        "screening": {"pharmacy_id": "PHARM-A", "systolic": bp[0], "diastolic": bp[1],
                      "symptoms": [], "protocol_version": "HTN-PROTOCOL-v1"},
        "actor_id": "pharmacy@onecare.demo",
    })
    s = r1.get_json()
    r2 = client.post("/api/referral", json={
        "screening_id": s["screening"]["id"], "facility_id": "HOSP-A",
    })
    return r2.get_json()["referral_id"]


def test_model_trains_on_first_use(client):
    m = ensure_model()
    assert m["trained_on"] == 2000
    assert len(m["features"]) == len(FEATURES)
    assert len(m["weights"]) == len(FEATURES)
    assert isinstance(m["intercept"], float)


def test_model_endpoint(client):
    j = client.get("/api/dropoff/model").get_json()
    assert j["ok"] is True
    assert "weights" in j
    assert "features" in j
    assert len(j["features"]) == 7
    assert "honest_note" in j


def test_score_endpoint(client):
    rid = _make_referral(client)
    j = client.post("/api/dropoff/score", json={"referral_id": rid}).get_json()
    assert j["ok"] is True
    assert 0.0 <= j["probability"] <= 1.0
    assert j["tier"] in ("low", "medium", "high")
    assert "features" in j
    assert set(j["features"].keys()) == set(FEATURES)


def test_self_pay_scores_higher_than_nhia(client):
    rid_nhia = _make_referral(client, insurance="nhia", bp=(180, 118), phone="+2348011100100")
    rid_sp = _make_referral(client, insurance="self_pay", bp=(180, 118), phone="+2348011100200")

    p_nhia = client.post("/api/dropoff/score", json={"referral_id": rid_nhia}).get_json()["probability"]
    p_sp = client.post("/api/dropoff/score", json={"referral_id": rid_sp}).get_json()["probability"]

    assert p_sp > p_nhia, f"self-pay ({p_sp}) should score higher than nhia ({p_nhia})"


def test_unknown_referral_404(client):
    r = client.post("/api/dropoff/score", json={"referral_id": "nope"})
    assert r.status_code == 404


def test_retrain_clears_cache(client):
    j = client.post("/api/dropoff/train").get_json()
    assert j["ok"] is True
    assert j["retrained"] is True
    assert "weights" in j["model"]


def test_queue_includes_dropoff(client):
    _make_referral(client)
    j = client.get("/api/hospital/queue").get_json()
    assert len(j["queue"]) >= 1
    assert j["queue"][0]["dropoff_score"] is not None
    assert j["queue"][0]["dropoff_tier"] in ("low", "medium", "high")