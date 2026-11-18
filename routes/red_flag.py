"""OneCare Loop — routes/red_flag.py"""

from flask import Blueprint, jsonify, request, session

from models import connect_db
from services.ledger import append_event, utc_now
from services.red_flag import list_open_alerts


bp = Blueprint("red_flag", __name__, url_prefix="/api")


@bp.get("/red-flags")
def open_alerts():
    alerts = list_open_alerts()
    return jsonify({
        "ok": True,
        "count": len(alerts),
        "alerts": alerts,
        "simulated": True,
        "note": "SIMULATED — no ambulance paged. Real paging is Coming Soon.",
    })


@bp.post("/red-flags/<alert_id>/acknowledge")
def acknowledge_alert(alert_id):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    note = (data.get("note") or "").strip()

    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT id, referral_id FROM loop_exceptions "
            "WHERE id = ? AND resolved_at IS NULL",
            (alert_id,),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "not_found_or_resolved"}), 404

        conn.execute(
            "UPDATE loop_exceptions SET owner = ? WHERE id = ?",
            (uid, alert_id),
        )
        conn.execute(
            "INSERT OR REPLACE INTO red_flag_acks "
            "(alert_id, acknowledged_by, acknowledged_at, note) VALUES (?, ?, ?, ?)",
            (alert_id, uid, utc_now(), note),
        )

        pid_row = conn.execute(
            "SELECT s.patient_id FROM referrals r "
            "JOIN screenings s ON s.id = r.screening_id WHERE r.id = ?",
            (row["referral_id"],),
        ).fetchone()
        patient_id = pid_row["patient_id"] if pid_row else None
    finally:
        conn.close()

    if patient_id:
        append_event(
            patient_id=patient_id,
            event_type="RED_FLAG_ACKNOWLEDGED",
            actor_id=uid,
            actor_role=session.get("role", "unknown"),
            payload={"alert_id": alert_id, "referral_id": row["referral_id"], "note": note},
            referral_id=row["referral_id"],
        )

    return jsonify({"ok": True, "alert_id": alert_id, "owner": uid})
