"""
OneCare Loop — services/otp.py

Phone-based OTP for patient portal login.
6-digit code, 5-minute expiry, 5 attempt max.
Codes are hashed before storage — never plaintext in the DB.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from datetime import datetime, timedelta, timezone

from models import connect_db
from services.ledger import utc_now


OTP_TTL_MINUTES = 5
OTP_MAX_ATTEMPTS = 5


def _hash_code(code: str) -> str:
    return hashlib.sha256(("onecare-otp::" + code).encode()).hexdigest()


def _phone_hash(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()


def find_patient_by_phone(phone: str) -> str | None:
    phone_hash = _phone_hash(phone)
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT patient_id FROM patient_contacts WHERE phone_hash = ?",
            (phone_hash,),
        ).fetchone()
        return row["patient_id"] if row else None
    finally:
        conn.close()


def generate_otp(patient_id: str) -> dict:
    code = f"{random.randint(0, 999999):06d}"
    expires = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
    expires_iso = expires.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    otp_id = str(uuid.uuid4())
    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO otp_tokens (id, patient_id, code_hash, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (otp_id, patient_id, _hash_code(code), expires_iso, utc_now()),
        )
    finally:
        conn.close()
    return {"otp_id": otp_id, "code": code, "expires_at": expires_iso}


def verify_otp(patient_id: str, code: str) -> dict:
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM otp_tokens WHERE patient_id = ? AND used_at IS NULL "
            "ORDER BY created_at DESC",
            (patient_id,),
        ).fetchall()
        if not rows:
            return {"ok": False, "reason": "no_code"}

        code_hash = _hash_code(code)
        now = utc_now()
        for row in rows:
            if row["expires_at"] < now:
                continue
            if row["attempts"] >= OTP_MAX_ATTEMPTS:
                return {"ok": False, "reason": "too_many_attempts"}
            if row["code_hash"] == code_hash:
                conn.execute(
                    "UPDATE otp_tokens SET used_at = ? WHERE id = ?",
                    (utc_now(), row["id"]),
                )
                return {"ok": True}
            else:
                conn.execute(
                    "UPDATE otp_tokens SET attempts = attempts + 1 WHERE id = ?",
                    (row["id"],),
                )
        return {"ok": False, "reason": "invalid_code"}
    finally:
        conn.close()