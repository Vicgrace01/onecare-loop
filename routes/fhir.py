"""OneCare Loop — routes/fhir.py"""

from flask import Blueprint, jsonify, request

from services.fhir import build_bundle, capability_statement


bp = Blueprint("fhir", __name__, url_prefix="/api/fhir")


@bp.get("/metadata")
def metadata():
    return jsonify(capability_statement())


@bp.get("/export")
def export():
    patient_id = request.args.get("patient_id")
    bundle = build_bundle(patient_id=patient_id)
    return jsonify(bundle)


@bp.get("/patient/<patient_id>")
def patient_bundle(patient_id):
    bundle = build_bundle(patient_id=patient_id)
    if bundle["total"] == 0:
        return jsonify({"ok": False, "error": "no_events_for_patient"}), 404
    return jsonify(bundle)