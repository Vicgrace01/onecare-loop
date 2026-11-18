"""OneCare Loop — routes/screening.py"""

from flask import Blueprint, jsonify, request

from services.loop import TransitionError
from services.screening import ScreeningError, run_screening


bp = Blueprint("screening", __name__, url_prefix="/api")


@bp.post("/screening")
def post_screening():
    data = request.get_json(silent=True) or {}
    try:
        result = run_screening(data)
        return jsonify({"ok": True, **result}), 201
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except ScreeningError as e:
        return jsonify({"ok": False, "error": e.reason, "message": e.message}), 400
    except TransitionError as e:
        return jsonify({"ok": False, "error": e.reason, "message": e.message}), 400