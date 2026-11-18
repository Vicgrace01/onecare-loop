"""OneCare Loop — routes/longitudinal.py"""

from flask import Blueprint, jsonify, request

from services.longitudinal import (
    get_status,
    record_bp_control,
    record_repeat_assessment,
    schedule_first_followup,
    schedule_next_followup,
)
from services.loop import TransitionError


bp = Blueprint("longitudinal", __name__, url_prefix="/api/followup")


def _err(e: TransitionError):
    return jsonify({"ok": False, "error": e.reason, "message": e.message}), 400


@bp.get("/<patient_id>")
def status(patient_id):
    return jsonify(get_status(patient_id))


@bp.post("/schedule")
def schedule_endpoint():
    data = request.get_json(silent=True) or {}
    try:
        result = schedule_first_followup(
            data["patient_id"], data.get("actor_id", "clinician@onecare.demo"),
            int(data.get("days", 30)),
        )
        return jsonify(result)
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return _err(e)


@bp.post("/assess")
def assess_endpoint():
    data = request.get_json(silent=True) or {}
    try:
        result = record_repeat_assessment(
            data["patient_id"], data.get("actor_id", "pharmacy@onecare.demo"),
            int(data["systolic"]), int(data["diastolic"]),
            data.get("notes", ""),
        )
        return jsonify(result)
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return _err(e)


@bp.post("/bp-control")
def bp_control_endpoint():
    data = request.get_json(silent=True) or {}
    try:
        result = record_bp_control(
            data["patient_id"], data.get("actor_id", "pharmacy@onecare.demo"),
            int(data["systolic"]), int(data["diastolic"]),
            bool(data.get("bp_controlled", False)),
        )
        return jsonify(result)
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return _err(e)


@bp.post("/loop")
def loop_endpoint():
    data = request.get_json(silent=True) or {}
    try:
        result = schedule_next_followup(
            data["patient_id"], data.get("actor_id", "clinician@onecare.demo"),
            int(data.get("days", 7)),
        )
        return jsonify(result)
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return _err(e)