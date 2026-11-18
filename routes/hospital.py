"""OneCare Loop — routes/hospital.py"""

import uuid

from flask import Blueprint, jsonify, request, session

from models import connect_db
from services.ledger import append_event, utc_now
from services.hospital import (
    accept_referral,
    attest_attendance,
    book_appointment,
    counter_refer,
    decline_referral,
    get_queue,
    get_referral_history,
)
from services.loop import TransitionError


bp = Blueprint("hospital", __name__, url_prefix="/api")


def _err(e, code=400):
    return jsonify({"ok": False, "error": e.reason, "message": e.message}), code


@bp.get("/hospital/queue")
def queue():
    facility_id = request.args.get("facility_id")
    return jsonify({"ok": True, "queue": get_queue(facility_id)})


@bp.post("/referrals/<referral_id>/accept")
def accept(referral_id):
    data = request.get_json(silent=True) or {}
    try:
        result = accept_referral(referral_id, data.get("actor_id", "hospital@onecare.demo"))
        return jsonify({"ok": True, **result})
    except TransitionError as e:
        return _err(e)
    except ValueError as e:
        return jsonify({"ok": False, "error": "invalid_request", "message": str(e)}), 400


@bp.post("/referrals/<referral_id>/decline")
def decline(referral_id):
    data = request.get_json(silent=True) or {}
    try:
        result = decline_referral(
            referral_id,
            data.get("actor_id", "hospital@onecare.demo"),
            data["reason_code"],
            data["owner"],
            data.get("next_facility_id"),
        )
        return jsonify({"ok": True, **result})
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return _err(e)
    except ValueError as e:
        return jsonify({"ok": False, "error": "invalid_request", "message": str(e)}), 400


@bp.post("/referrals/<referral_id>/book")
def book(referral_id):
    data = request.get_json(silent=True) or {}
    try:
        result = book_appointment(
            referral_id,
            data.get("actor_id", "hospital@onecare.demo"),
            data["slot_start"],
            data["slot_end"],
        )
        return jsonify({"ok": True, **result})
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return _err(e)
    except ValueError as e:
        return jsonify({"ok": False, "error": "invalid_request", "message": str(e)}), 400


@bp.post("/referrals/<referral_id>/attest")
def attest(referral_id):
    data = request.get_json(silent=True) or {}
    try:
        result = attest_attendance(
            referral_id,
            data.get("actor_id", "hospital@onecare.demo"),
            data["clinician_id"],
            data.get("notes", ""),
        )
        return jsonify({"ok": True, **result})
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return _err(e)
    except ValueError as e:
        return jsonify({"ok": False, "error": "invalid_request", "message": str(e)}), 400


@bp.post("/referrals/<referral_id>/counter-refer")
def counter_refer_route(referral_id):
    data = request.get_json(silent=True) or {}
    try:
        result = counter_refer(
            referral_id,
            data.get("actor_id", "clinician@onecare.demo"),
            data["clinician_id"],
            data["outcome"],
            data["next_step"],
        )
        return jsonify({"ok": True, **result})
    except KeyError as e:
        return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
    except TransitionError as e:
        return _err(e)
    except ValueError as e:
        return jsonify({"ok": False, "error": "invalid_request", "message": str(e)}), 400


@bp.get("/referrals/<referral_id>/history")
def history(referral_id):
    try:
        events = get_referral_history(referral_id)
        return jsonify({"ok": True, "referral_id": referral_id, "events": events})
    except ValueError as e:
        return jsonify({"ok": False, "error": "invalid_request", "message": str(e)}), 404


@bp.post("/referrals/<referral_id>/message")
def post_message(referral_id):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"ok": False, "error": "missing_field", "field": "body"}), 400
    if len(body) > 4000:
        return jsonify({"ok": False, "error": "too_long"}), 400

    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT r.id, s.patient_id FROM referrals r "
            "JOIN screenings s ON s.id = r.screening_id WHERE r.id = ?",
            (referral_id,),
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "not_found"}), 404

        mid = str(uuid.uuid4())
        role = session.get("role", "unknown")
        conn.execute(
            "INSERT INTO case_messages "
            "(id, referral_id, from_user_id, from_role, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (mid, referral_id, uid, role, body, utc_now()),
        )
        patient_id = row["patient_id"]
    finally:
        conn.close()

    event = append_event(
        patient_id=patient_id,
        event_type="CONSULT_MESSAGE",
        actor_id=uid,
        actor_role=role,
        payload={"referral_id": referral_id, "message_id": mid, "body": body},
        referral_id=referral_id,
    )
    return jsonify({"ok": True, "message_id": mid, "event_id": event["id"]})


@bp.get("/referrals/<referral_id>/messages")
def get_messages(referral_id):
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT id, from_user_id, from_role, body, created_at "
            "FROM case_messages WHERE referral_id = ? ORDER BY created_at",
            (referral_id,),
        ).fetchall()
    finally:
        conn.close()
    return jsonify({
        "ok": True,
        "referral_id": referral_id,
        "messages": [dict(r) for r in rows],
    })