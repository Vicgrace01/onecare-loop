"""OneCare Loop — routes/referral.py"""

from flask import Blueprint, jsonify, request

from models import connect_db
from services.ledger import get_current_state
from services.loop import TransitionError
from services.referral import create_referral


bp = Blueprint("referral", __name__, url_prefix="/api")


@bp.post("/referral")
def post_referral():
    data = request.get_json(silent=True) or {}
    try:
        result = create_referral(data)
        return jsonify({"ok": True, **result}), 201
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return jsonify({"ok": False, "error": e.reason, "message": e.message}), 400
    except ValueError as e:
        return jsonify({"ok": False, "error": "invalid_request", "message": str(e)}), 400


@bp.get("/referrals/<referral_id>")
def get_referral(referral_id):
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT r.*, s.patient_id FROM referrals r JOIN screenings s ON s.id = r.screening_id WHERE r.id = ?",
            (referral_id,),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "not_found"}), 404
        data = dict(row)
    finally:
        conn.close()

    patient_id = data.pop("patient_id")
    return jsonify({
        "ok": True,
        "referral": data,
        "patient_id": patient_id,
        "current_state": get_current_state(patient_id),
    })