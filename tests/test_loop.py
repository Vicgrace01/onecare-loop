"""tests/test_loop.py — state machine tests."""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from services.ledger import get_current_state
from services.loop import (
    CANONICAL_STATES,
    FAILURE_STATES,
    TransitionError,
    VALID_TRANSITIONS,
    record_transition,
    start_loop,
)


@pytest.fixture
def app_ctx(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app({"TESTING": True, "DATABASE": db_path, "DEV_MODE": True})
    with app.app_context():
        yield app


def _start(patient_id="T-001"):
    start_loop(patient_id, "pharm@x", "pharmacy", {"systolic": 160, "diastolic": 100})
    assert get_current_state(patient_id) == "SCREEN_POSITIVE"
    return patient_id


def _advance_to_referral(patient_id):
    record_transition(
        patient_id, "REFERRAL_CREATED", "pharm@x", "pharmacy",
        {"consent_version": "1.0", "consent_hash": "abc", "facility_id": "HOSP-A"},
    )
    assert get_current_state(patient_id) == "REFERRAL_CREATED"


def _advance_to_accepted(patient_id):
    _advance_to_referral(patient_id)
    record_transition(
        patient_id, "FACILITY_ACCEPTED", "hosp@x", "hospital",
        {"actor_authenticated": True, "facility_id": "HOSP-A"},
    )
    assert get_current_state(patient_id) == "FACILITY_ACCEPTED"


def _advance_to_booked(patient_id):
    _advance_to_accepted(patient_id)
    record_transition(
        patient_id, "APPOINTMENT_BOOKED", "hosp@x", "hospital",
        {"slot_start": "2026-11-20T09:00:00Z", "facility_id": "HOSP-A"},
    )
    assert get_current_state(patient_id) == "APPOINTMENT_BOOKED"


def test_canonical_happy_path(app_ctx):
    p = _start("T-HAPPY")
    _advance_to_booked(p)
    record_transition(
        p, "CLINICAL_ENCOUNTER_COMPLETED", "hosp@x", "hospital",
        {"attended": True, "encounter_id": "E-1"},
    )
    assert get_current_state(p) == "CLINICAL_ENCOUNTER_COMPLETED"
    record_transition(
        p, "CLINICAL_DISPOSITION_RETURNED", "clin@x", "clinician",
        {"clinician_id": "clin@x", "outcome": "referred_for_treatment", "next_step": "start meds"},
    )
    assert get_current_state(p) == "CLINICAL_DISPOSITION_RETURNED"


def test_shortcut_screen_to_facility_is_impossible(app_ctx):
    p = _start("T-SHORTCUT")
    with pytest.raises(TransitionError) as exc:
        record_transition(
            p, "FACILITY_ACCEPTED", "hosp@x", "hospital",
            {"actor_authenticated": True, "facility_id": "HOSP-A"},
        )
    assert exc.value.reason == "invalid_transition"


def test_missing_consent_blocks_referral(app_ctx):
    p = _start("T-NOCONSENT")
    with pytest.raises(TransitionError) as exc:
        record_transition(
            p, "REFERRAL_CREATED", "pharm@x", "pharmacy",
            {"facility_id": "HOSP-A"},
        )
    assert exc.value.reason == "missing_consent"


def test_wrong_actor_cannot_accept_referral(app_ctx):
    p = _start("T-WRONGACTOR")
    _advance_to_referral(p)
    with pytest.raises(TransitionError) as exc:
        record_transition(
            p, "FACILITY_ACCEPTED", "pharm@x", "pharmacy",
            {"actor_authenticated": True, "facility_id": "HOSP-A"},
        )
    assert exc.value.reason == "wrong_actor"


def test_failure_requires_reason_and_owner(app_ctx):
    p = _start("T-NOREASON")
    _advance_to_referral(p)
    with pytest.raises(TransitionError) as exc:
        record_transition(
            p, "REFERRAL_DECLINED", "hosp@x", "hospital",
            {"facility_id": "HOSP-A"},
        )
    assert exc.value.reason == "missing_referral_id"


def test_failure_with_full_payload_succeeds(app_ctx):
    p = _start("T-FAILURE")
    _advance_to_referral(p)
    record_transition(
        p, "REFERRAL_DECLINED", "hosp@x", "hospital",
        {
            "referral_id": "REF-1",
            "reason_code": "no_slots",
            "owner": "care_navigator",
            "facility_id": "HOSP-A",
        },
    )
    assert get_current_state(p) == "REFERRAL_DECLINED"


def test_decline_then_new_facility(app_ctx):
    p = _start("T-REDIRECT")
    _advance_to_referral(p)
    record_transition(
        p, "REFERRAL_DECLINED", "hosp@x", "hospital",
        {"referral_id": "REF-1", "reason_code": "no_slots", "owner": "navigator"},
    )
    record_transition(
        p, "REFERRAL_CREATED", "pharm@x", "pharmacy",
        {"consent_version": "1.0", "consent_hash": "abc",
         "facility_id": "HOSP-B", "previous_facility_id": "HOSP-A"},
    )
    assert get_current_state(p) == "REFERRAL_CREATED"


def test_cannot_restart_started_loop(app_ctx):
    p = _start("T-RESTART")
    with pytest.raises(TransitionError) as exc:
        start_loop(p, "pharm@x", "pharmacy", {"systolic": 150, "diastolic": 95})
    assert exc.value.reason == "loop_already_started"


def test_all_failure_states_have_entry_path(app_ctx):
    reached = {to_state for (_, to_state) in VALID_TRANSITIONS if to_state in FAILURE_STATES}
    assert reached == FAILURE_STATES


def test_all_canonical_states_have_entry(app_ctx):
    entered = {to_state for (_, to_state) in VALID_TRANSITIONS}
    for state in CANONICAL_STATES - {"SCREEN_POSITIVE"}:
        assert state in entered, f"No transition enters {state}"