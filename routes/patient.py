"""OneCare Loop — routes/patient.py"""

from flask import Blueprint, jsonify, request, session

from services.ledger import append_event, utc_now
from services.patient import confirm_attendance, get_receipt


bp = Blueprint("patient", __name__, url_prefix="/api")


@bp.get("/patient/<patient_id>/receipt")
def receipt(patient_id):
    viewer_id = request.args.get("viewer_id")
    try:
        data = get_receipt(patient_id, viewer_id)
        return jsonify({"ok": True, **data})
    except LookupError as e:
        return jsonify({"ok": False, "error": "not_found", "message": str(e)}), 404


@bp.post("/patient/<patient_id>/confirm-attendance")
def confirm(patient_id):
    data = request.get_json(silent=True) or {}
    try:
        result = confirm_attendance(patient_id, data.get("note", ""))
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": "invalid_request", "message": str(e)}), 404


@bp.post("/patient/<patient_id>/acknowledge")
def acknowledge(patient_id):
    if session.get("patient_id") != patient_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    try:
        event = append_event(
            patient_id=patient_id,
            event_type="PATIENT_ACKNOWLEDGED",
            actor_id=patient_id,
            actor_role="patient",
            payload={
                "note": data.get("note", ""),
                "acknowledged_at": utc_now(),
            },
            referral_id=None,
        )
        return jsonify({"ok": True, "event_id": event["id"], "seq": event["seq"]})
    except Exception as e:
        return jsonify({"ok": False, "error": "acknowledge_failed", "message": str(e)}), 500
