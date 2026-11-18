"""OneCare Loop — routes/dropoff.py"""

from flask import Blueprint, jsonify, request

from services.dropoff import model_summary, retrain, score_referral


bp = Blueprint("dropoff", __name__, url_prefix="/api/dropoff")


@bp.post("/score")
def score():
    data = request.get_json(silent=True) or {}
    referral_id = data.get("referral_id")
    if not referral_id:
        return jsonify({"ok": False, "error": "missing_field", "field": "referral_id"}), 400
    result = score_referral(referral_id)
    if not result.get("ok"):
        return jsonify(result), 404
    return jsonify(result)


@bp.get("/model")
def model():
    return jsonify({"ok": True, **model_summary()})


@bp.post("/train")
def train_endpoint():
    return jsonify({"ok": True, "retrained": True, "model": retrain()})