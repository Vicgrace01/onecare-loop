"""
OneCare Loop — services/fhir.py

FHIR R4 Bundle export from loop_events.
Each ledger event maps to one or more standard FHIR resources.
The event hash is attached as a meta.tag so exported resources remain
cryptographically traceable back to the chain.
"""

from __future__ import annotations

import json
import uuid

from models import connect_db
from services.ledger import utc_now


def _year_from_age_band(age_band: str | None) -> str | None:
    """Approximate birth year from a 5-band age bucket. Not precise, not identifying."""
    if not age_band:
        return None
    current = 2025
    table = {"18-29": 23, "30-39": 34, "40-49": 44, "50-59": 54, "60+": 65}
    mid = table.get(age_band)
    return str(current - mid) if mid else None


def _event_to_resources(event: dict, facility_id: str | None) -> list[dict]:
    payload = json.loads(event["payload_json"] or "{}")
    actor = event["actor_id"]
    occurred = event["occurred_at"]
    pid = event["patient_id"]
    et = event["event_type"]
    tag = {"system": "onecare/ledger-event", "code": event["hash"][:16]}

    def meta(**extra):
        base = {"tag": [tag]}
        base.update(extra)
        return base

    if et == "SCREEN_POSITIVE":
        sbp = int(payload.get("systolic", 0))
        dbp = int(payload.get("diastolic", 0))
        return [{
            "resourceType": "Observation",
            "id": f"bp-{event['id']}",
            "meta": meta(),
            "status": "final",
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
            "code": {"coding": [{"system": "http://loinc.org", "code": "85354-9", "display": "Blood pressure panel"}]},
            "subject": {"reference": f"Patient/{pid}"},
            "effectiveDateTime": occurred,
            "performer": [{"reference": f"Practitioner/{actor}"}],
            "component": [
                {"code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                 "valueQuantity": {"value": sbp, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}},
                {"code": {"coding": [{"system": "http://loinc.org", "code": "8462-4"}]},
                 "valueQuantity": {"value": dbp, "unit": "mmHg", "system": "http://unitsofmeasure.org", "code": "mm[Hg]"}},
            ],
        }]

    if et == "REFERRAL_CREATED":
        priority = payload.get("urgency", "routine")
        return [{
            "resourceType": "ServiceRequest",
            "id": f"ref-{event['id']}",
            "meta": meta(),
            "status": "active",
            "intent": "order",
            "priority": priority,
            "code": {"coding": [{"system": "onecare/referral", "code": "hypertension-review", "display": "Hypertension clinical review"}]},
            "subject": {"reference": f"Patient/{pid}"},
            "requester": {"reference": f"Practitioner/{actor}"},
            "performer": [{"reference": f"Organization/{facility_id}"}] if facility_id else [],
            "authoredOn": occurred,
        }]

    if et == "FACILITY_ACCEPTED":
        res = {
            "resourceType": "Task",
            "id": f"task-{event['id']}",
            "meta": meta(),
            "status": "accepted",
            "intent": "order",
            "subject": {"reference": f"Patient/{pid}"},
            "authoredOn": occurred,
        }
        if facility_id:
            res["owner"] = {"reference": f"Organization/{facility_id}"}
        return [res]

    if et == "APPOINTMENT_BOOKED":
        return [{
            "resourceType": "Appointment",
            "id": f"appt-{event['id']}",
            "meta": meta(),
            "status": "booked",
            "start": payload.get("slot_start", occurred),
            "end": payload.get("slot_end", occurred),
            "participant": [
                {"actor": {"reference": f"Patient/{pid}"}, "status": "accepted"},
                {"actor": {"reference": f"Organization/{facility_id}"}, "status": "accepted"},
            ] if facility_id else [{"actor": {"reference": f"Patient/{pid}"}, "status": "accepted"}],
        }]

    if et == "CLINICAL_ENCOUNTER_COMPLETED":
        return [{
            "resourceType": "Encounter",
            "id": f"enc-{event['id']}",
            "meta": meta(),
            "status": "finished",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
            "subject": {"reference": f"Patient/{pid}"},
            "period": {"start": occurred},
            "serviceProvider": {"reference": f"Organization/{facility_id}"} if facility_id else None,
        }]

    if et == "CLINICAL_DISPOSITION_RETURNED":
        return [{
            "resourceType": "ClinicalImpression",
            "id": f"imp-{event['id']}",
            "meta": meta(),
            "status": "completed",
            "subject": {"reference": f"Patient/{pid}"},
            "date": occurred,
            "summary": payload.get("outcome", ""),
            "note": [{"text": payload.get("next_step", "")}],
        }]

    return []


def build_bundle(patient_id: str | None = None) -> dict:
    conn = connect_db()
    try:
        if patient_id:
            events = [dict(r) for r in conn.execute(
                "SELECT * FROM loop_events WHERE patient_id = ? ORDER BY seq",
                (patient_id,),
            ).fetchall()]
        else:
            events = [dict(r) for r in conn.execute(
                "SELECT * FROM loop_events ORDER BY patient_id, seq"
            ).fetchall()]

        patient_ids = sorted({e["patient_id"] for e in events})
        patient_rows = {
            row["id"]: dict(row)
            for row in conn.execute(
                f"SELECT id, age_band, insurance_type FROM patients "
                f"WHERE id IN ({','.join('?' * len(patient_ids)) or 'NULL'})",
                patient_ids,
            ).fetchall()
        } if patient_ids else {}

        referral_ids = sorted({e["referral_id"] for e in events if e["referral_id"]})
        referral_rows = {
            row["id"]: dict(row)
            for row in conn.execute(
                f"SELECT id, facility_id FROM referrals "
                f"WHERE id IN ({','.join('?' * len(referral_ids)) or 'NULL'})",
                referral_ids,
            ).fetchall()
        } if referral_ids else {}
    finally:
        conn.close()

    resources: list[dict] = []

    for pid in patient_ids:
        pdata = patient_rows.get(pid, {})
        patient_resource = {
            "resourceType": "Patient",
            "id": pid,
            "meta": {"profile": ["http://hl7.org/fhir/StructureDefinition/Patient"]},
            "gender": "unknown",
        }
        birth = _year_from_age_band(pdata.get("age_band"))
        if birth:
            patient_resource["birthDate"] = birth
        if pdata.get("insurance_type"):
            patient_resource["extension"] = [{
                "url": "https://onecare.example.ng/fhir/StructureDefinition/insurance-type",
                "valueCode": pdata["insurance_type"],
            }]
        resources.append(patient_resource)

    for event in events:
        fac = None
        if event["referral_id"]:
            fac = referral_rows.get(event["referral_id"], {}).get("facility_id")
        resources.extend(_event_to_resources(event, fac))

    resources = [r for r in resources if r]

    return {
        "resourceType": "Bundle",
        "id": str(uuid.uuid4()),
        "type": "collection",
        "timestamp": utc_now(),
        "total": len(resources),
        "entry": [{"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in resources],
    }


def capability_statement() -> dict:
    return {
        "resourceType": "CapabilityStatement",
        "id": "onecare-loop-fhir",
        "status": "active",
        "date": utc_now(),
        "publisher": "OneCare Loop",
        "kind": "instance",
        "software": {"name": "OneCare Loop", "version": "1.0"},
        "implementation": {"description": "Nigeria hypertension care-loop tracking, read-only FHIR export"},
        "fhirVersion": "4.0.1",
        "format": ["json"],
        "rest": [{
            "mode": "server",
            "interaction": [{"code": "batch"}, {"code": "transaction"}],
            "resource": [
                {"type": "Patient", "interaction": [{"code": "read"}]},
                {"type": "Observation", "interaction": [{"code": "read"}]},
                {"type": "ServiceRequest", "interaction": [{"code": "read"}]},
                {"type": "Task", "interaction": [{"code": "read"}]},
                {"type": "Appointment", "interaction": [{"code": "read"}]},
                {"type": "Encounter", "interaction": [{"code": "read"}]},
                {"type": "ClinicalImpression", "interaction": [{"code": "read"}]},
            ],
        }],
    }