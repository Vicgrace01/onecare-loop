"""OneCare Loop — routes/notifications.py"""

from flask import Blueprint, jsonify, request

from services.classifier import CLASSES, classify
from services.sms import patient_thread, send, simulate_reply
from services.templates import LANGUAGES, list_templates


bp = Blueprint("notifications", __name__, url_prefix="/api")


@bp.post("/notifications/send")
def send_endpoint():
    data = request.get_json(silent=True) or {}
    for field in ("patient_id", "template_id"):
        if not data.get(field):
            return jsonify({"ok": False, "error": "missing_field", "field": field}), 400
    result = send(
        patient_id=data["patient_id"],
        template_id=data["template_id"],
        language=data.get("language"),
        channel=data.get("channel", "sms"),
        context=data.get("context", {}),
    )
    return jsonify(result)


@bp.post("/notifications/simulate-reply")
def reply_endpoint():
    data = request.get_json(silent=True) or {}
    if not data.get("notification_id"):
        return jsonify({"ok": False, "error": "missing_field", "field": "notification_id"}), 400
    if not data.get("reply_text"):
        return jsonify({"ok": False, "error": "missing_field", "field": "reply_text"}), 400
    result = simulate_reply(data["notification_id"], data["reply_text"])
    if not result["ok"]:
        return jsonify(result), 404
    return jsonify(result)


@bp.get("/notifications/patient/<patient_id>")
def thread_endpoint(patient_id):
    return jsonify({"ok": True, "patient_id": patient_id, "notifications": patient_thread(patient_id)})


@bp.post("/classify")
def classify_endpoint():
    data = request.get_json(silent=True) or {}
    if not data.get("text"):
        return jsonify({"ok": False, "error": "missing_field", "field": "text"}), 400
    result = classify(data["text"], data.get("language", "en"))
    return jsonify({"ok": True, "input": data["text"], **result})


@bp.get("/templates")
def templates_endpoint():
    return jsonify({
        "ok": True,
        "languages": LANGUAGES,
        "templates": list_templates(),
    })