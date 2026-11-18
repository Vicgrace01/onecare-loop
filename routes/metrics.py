"""OneCare Loop — routes/metrics.py"""

from flask import Blueprint, jsonify

from services.metrics import compute_metrics, compute_provider_metrics


bp = Blueprint("metrics", __name__, url_prefix="/api")


@bp.get("/metrics")
def metrics():
    return jsonify({"ok": True, **compute_metrics()})


@bp.get("/metrics/providers")
def providers():
    return jsonify({"ok": True, **compute_provider_metrics()})