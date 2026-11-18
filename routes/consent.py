"""
OneCare Loop — routes/consent.py

NDPA erasure right (crypto-shredding) and signature verification.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request, session

from models import connect_db
from services.ledger import (
    append_event,
    utc_now,
    verify_all_chains,
)


bp = Blueprint("consent", __name__, url_prefix="/api")


@bp.post("/consent/revoke")
def revoke_consent():
    """
    NDPA §34 erasure. Marks the patient's PII key as shredded.
    The chain is preserved; phone becomes undecryptable.
    """
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    patient_id = data.get("patient_id")
    if not patient_id:
        return jsonify({"ok": False, "error": "missing_field", "field": "patient_id"}), 400

    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT id FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        if not row:
            return jsonify({"ok": False, "error": "not_found"}), 404

        key_row = conn.execute(
            "SELECT shredded_at FROM key_store WHERE patient_id = ?", (patient_id,)
        ).fetchone()

        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE key_store SET shredded_at = ? WHERE patient_id = ? AND shredded_at IS NULL",
            (utc_now(), patient_id),
        )
        conn.execute(
            "UPDATE consents SET revoked_at = ? WHERE patient_id = ? AND revoked_at IS NULL",
            (utc_now(), patient_id),
        )
        conn.execute(
            "UPDATE patients SET consent_at = NULL WHERE id = ?", (patient_id,)
        )
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        conn.close()

    event = append_event(
        patient_id=patient_id,
        event_type="CONSENT_REVOKED",
        actor_id=uid,
        actor_role=session.get("role", "admin"),
        payload={
            "revoked_at": utc_now(),
            "reason": data.get("reason", "patient_request"),
            "pii_shredded": key_row is not None,
        },
        referral_id=None,
    )

    return jsonify({
        "ok": True,
        "patient_id": patient_id,
        "shredded": key_row is not None,
        "event_id": event["id"],
        "event_hash": event["hash"],
        "event_signature": event["actor_signature"],
    })


@bp.get("/audit/verify-signatures")
def verify_signatures():
    conn = connect_db()
    try:
        result = verify_all_chains(conn, verify_signatures=True)
    finally:
        conn.close()

    total_signed = sum(p.get("signed", 0) for p in result["patients"])
    total_unsigned = sum(p.get("unsigned", 0) for p in result["patients"])
    total_invalid = sum(p.get("invalid_signature", 0) for p in result["patients"])

    return jsonify({
        "ok": result["ok"] and total_invalid == 0,
        "patients": result["patients"],
        "summary": {
            "signed": total_signed,
            "unsigned": total_unsigned,
            "invalid": total_invalid,
        },
        "checked_at": result["checked_at"],
    })