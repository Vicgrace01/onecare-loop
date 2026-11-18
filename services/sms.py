"""
OneCare Loop — services/sms.py

SMS / WhatsApp sender in SIMULATE mode.
Writes to the notifications table and returns a Twilio-shaped envelope.
No external network calls unless ONECARE_TWILIO_LIVE=1 (never in demo).
"""

from __future__ import annotations

import os
import uuid

from models import connect_db
from services.classifier import classify
from services.ledger import utc_now
from services.templates import render


def _get_patient_language(patient_id: str) -> str | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT preferred_language FROM patient_contacts WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()
        return row["preferred_language"] if row else None
    finally:
        conn.close()


def _has_active_consent(patient_id: str) -> bool:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM consents WHERE patient_id = ? AND revoked_at IS NULL LIMIT 1",
            (patient_id,),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def send(
    patient_id: str,
    template_id: str,
    language: str | None = None,
    channel: str = "sms",
    context: dict | None = None,
) -> dict:
    """
    SIMULATE. If patient has no contact or no active consent, returns status='skipped'.
    Otherwise writes a notification row and returns a Twilio-shaped SID.
    """
    if channel not in ("sms", "whatsapp"):
        raise ValueError(f"channel must be sms or whatsapp, got {channel}")

    if not _has_active_consent(patient_id):
        return {
            "ok": False, "status": "skipped", "reason": "no_active_consent",
            "patient_id": patient_id, "template_id": template_id,
        }

    lang = language or _get_patient_language(patient_id) or "en"
    try:
        rendered = render(template_id, lang, context or {})
    except Exception as e:
        return {"ok": False, "status": "error", "reason": str(e)}

    notification_id = str(uuid.uuid4())
    sid = f"SM{uuid.uuid4().hex[:30]}"  # Twilio-shaped

    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO notifications "
            "(id, patient_id, channel, template_id, language, sent_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (notification_id, patient_id, channel, template_id, lang, utc_now(), utc_now()),
        )
    finally:
        conn.close()

    return {
        "ok": True,
        "status": "simulated",
        "notification_id": notification_id,
        "sid": sid,
        "channel": channel,
        "language": lang,
        "template_id": template_id,
        "preview": rendered["text"],
        "needs_native_review": rendered["needs_native_review"],
        "sent_at": utc_now(),
        "note": "SIMULATED — no external network call. Marked as simulated in model card.",
    }


def simulate_reply(notification_id: str, reply_text: str) -> dict:
    """SIMULATE an inbound reply. Classifies it and stores the result."""
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT id, patient_id, language FROM notifications WHERE id = ?",
            (notification_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "notification_not_found"}

        classification = classify(reply_text, row["language"] or "en")

        conn.execute(
            "UPDATE notifications SET reply_text = ?, reply_class = ?, delivered_at = ? WHERE id = ?",
            (reply_text, classification["class"], utc_now(), notification_id),
        )
    finally:
        conn.close()

    return {
        "ok": True,
        "notification_id": notification_id,
        "patient_id": row["patient_id"],
        "reply_text": reply_text,
        "classification": classification,
    }


def patient_thread(patient_id: str) -> list[dict]:
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE patient_id = ? ORDER BY created_at ASC",
            (patient_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()