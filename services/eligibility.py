"""
OneCare Loop — services/eligibility.py

SIMULATED: DHIN FHIR R4 CoverageEligibilityRequest/Response mock.
Real FHIR schema. Mock decision based on NHIA number presence.
Not wired to live DHIN. See README "What's simulated".
"""

from __future__ import annotations

import uuid
from typing import Any

from services.ledger import utc_now


FHIR_BASE = "https://dhin.example.ng/fhir/R4"


def _request_id() -> str:
    return str(uuid.uuid4())


def build_request(patient_id: str, facility_id: str, nhia_number: str | None) -> dict[str, Any]:
    insurance = [{"coverage": {"reference": f"Coverage/{nhia_number}"}}] if nhia_number else []
    return {
        "resourceType": "CoverageEligibilityRequest",
        "id": _request_id(),
        "status": "active",
        "priority": {"coding": [{"system": "http://hl7.org/fhir/request-priority", "code": "normal"}]},
        "purpose": ["benefits"],
        "patient": {"reference": f"Patient/{patient_id}"},
        "created": utc_now()[:10],
        "provider": {"reference": f"Organization/{facility_id}"},
        "insurance": insurance,
    }


def build_response(request: dict, nhia_number: str | None) -> dict[str, Any]:
    patient_ref = request["patient"]["reference"]
    if not nhia_number:
        return {
            "resourceType": "CoverageEligibilityResponse",
            "id": _request_id(),
            "status": "active",
            "purpose": ["benefits"],
            "patient": {"reference": patient_ref},
            "created": request["created"],
            "request": {"reference": f"CoverageEligibilityRequest/{request['id']}"},
            "outcome": "complete",
            "disposition": "No coverage on file. Refer to donor-subsidized pathway.",
            "insurance": [],
        }
    return {
        "resourceType": "CoverageEligibilityResponse",
        "id": _request_id(),
        "status": "active",
        "purpose": ["benefits"],
        "patient": {"reference": patient_ref},
        "created": request["created"],
        "request": {"reference": f"CoverageEligibilityRequest/{request['id']}"},
        "outcome": "complete",
        "disposition": "Covered: consultation and BP review. Co-pay 0 NGN.",
        "insurance": [{
            "coverage": {"reference": f"Coverage/{nhia_number}"},
            "inforce": True,
            "item": [
                {
                    "category": {"coding": [{"system": FHIR_BASE + "/benefit-category", "code": "consultation"}]},
                    "benefit": [{"type": {"coding": [{"code": "copay"}]}, "allowedMoney": {"value": 0, "currency": "NGN"}}],
                },
                {
                    "category": {"coding": [{"system": FHIR_BASE + "/benefit-category", "code": "bp-review"}]},
                    "benefit": [{"type": {"coding": [{"code": "copay"}]}, "allowedMoney": {"value": 0, "currency": "NGN"}}],
                },
            ],
        }],
    }


def decide(response: dict) -> str:
    return "covered" if response.get("insurance") else "not_covered"


def mock_check_eligibility(
    patient_id: str,
    facility_id: str,
    insurance_type: str | None,
    nhia_number: str | None,
) -> dict[str, Any]:
    """SIMULATED. Returns FHIR request/response pair + decision."""
    request = build_request(patient_id, facility_id, nhia_number)
    response = build_response(request, nhia_number)
    return {"request": request, "response": response, "decision": decide(response)}