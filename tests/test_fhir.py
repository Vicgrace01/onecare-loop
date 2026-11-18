"""tests/test_fhir.py"""

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


def _full_loop(client):
    r1 = client.post("/api/screening", json={
        "patient": {"age_band": "40-49", "insurance_type": "nhia",
                    "nhia_number": "NHIA-F", "phone": "+2348011100001"},
        "consent": {"version": "1.0", "scope": ["screening", "referral"]},
        "screening": {"pharmacy_id": "PHARM-A", "systolic": 180, "diastolic": 118,
                      "symptoms": [], "protocol_version": "HTN-PROTOCOL-v1"},
        "actor_id": "pharmacy@onecare.demo",
    })
    s = r1.get_json()
    r2 = client.post("/api/referral", json={
        "screening_id": s["screening"]["id"], "facility_id": "HOSP-A",
    })
    rid = r2.get_json()["referral_id"]
    client.post(f"/api/referrals/{rid}/accept", json={"actor_id": "hospital@onecare.demo"})
    client.post(f"/api/referrals/{rid}/book", json={
        "actor_id": "hospital@onecare.demo",
        "slot_start": "2026-11-20T09:00:00Z", "slot_end": "2026-11-20T09:30:00Z",
    })
    client.post(f"/api/referrals/{rid}/attest", json={
        "actor_id": "hospital@onecare.demo", "clinician_id": "doc@onecare.demo",
    })
    client.post(f"/api/referrals/{rid}/counter-refer", json={
        "actor_id": "doc@onecare.demo", "clinician_id": "doc@onecare.demo",
        "outcome": "started_medication", "next_step": "review in 30 days",
    })
    return s["patient_id"]


def test_metadata_returns_capability(client):
    j = client.get("/api/fhir/metadata").get_json()
    assert j["resourceType"] == "CapabilityStatement"
    assert j["fhirVersion"] == "4.0.1"
    assert j["software"]["name"] == "OneCare Loop"


def test_export_full_bundle(client):
    _full_loop(client)
    j = client.get("/api/fhir/export").get_json()
    assert j["resourceType"] == "Bundle"
    assert j["type"] == "collection"
    assert j["total"] > 0
    types = {e["resource"]["resourceType"] for e in j["entry"]}
    for expected in ["Patient", "Observation", "ServiceRequest", "Task", "Appointment", "Encounter", "ClinicalImpression"]:
        assert expected in types, f"missing {expected} in {types}"


def test_patient_bundle_scoped(client):
    pid = _full_loop(client)
    j = client.get(f"/api/fhir/patient/{pid}").get_json()
    assert j["resourceType"] == "Bundle"
    patient_refs = [e["resource"]["id"] for e in j["entry"] if e["resource"]["resourceType"] == "Patient"]
    assert pid in patient_refs


def test_unknown_patient_404(client):
    r = client.get("/api/fhir/patient/nonexistent")
    assert r.status_code == 404


def test_event_hashes_are_tagged(client):
    _full_loop(client)
    j = client.get("/api/fhir/export").get_json()
    for entry in j["entry"]:
        r = entry["resource"]
        if r["resourceType"] == "Patient":
            continue
        assert "tag" in r["meta"], f"{r['resourceType']} has no tag"
        assert r["meta"]["tag"][0]["system"] == "onecare/ledger-event"


def test_patient_resource_omits_pii(client):
    """Model card promises no name, no address, no phone in exports."""
    _full_loop(client)
    j = client.get("/api/fhir/export").get_json()
    for entry in j["entry"]:
        if entry["resource"]["resourceType"] != "Patient":
            continue
        r = entry["resource"]
        assert "name" not in r
        assert "telecom" not in r
        assert "address" not in r
        assert "identifier" not in r