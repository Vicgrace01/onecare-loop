"""
OneCare Loop — services/crypto.py

AES-256-GCM encryption for PII + crypto-shredding primitive.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MASTER_KEY_ENV = "ONECARE_MASTER_KEY"
NONCE_BYTES = 12


def get_master_key() -> bytes:
    """
    Master key from env. Must be base64-encoded 32 bytes.
    Fallback derives deterministically from SECRET_KEY for local dev — NOT for production.
    """
    val = os.environ.get(MASTER_KEY_ENV)
    if val:
        try:
            key = base64.b64decode(val)
        except Exception as e:
            raise RuntimeError(f"Invalid {MASTER_KEY_ENV}: {e}") from e
        if len(key) != 32:
            raise RuntimeError(f"{MASTER_KEY_ENV} must be 32 bytes; got {len(key)}")
        return key
    secret = os.environ.get("SECRET_KEY", "onecare-loop-dev-only-change-me")
    return hashlib.sha256(("onecare-master::" + secret).encode()).digest()


def generate_data_key() -> bytes:
    return os.urandom(32)


def encrypt(key: bytes, plaintext: str) -> str:
    """AES-GCM. Returns base64(nonce || ciphertext || tag)."""
    aes = AESGCM(key)
    nonce = os.urandom(NONCE_BYTES)
    ct = aes.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt(key: bytes, payload: str) -> str:
    """Raises cryptography.exceptions.InvalidTag if the key is wrong or data is corrupt."""
    raw = base64.b64decode(payload)
    nonce, ct = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
    aes = AESGCM(key)
    return aes.decrypt(nonce, ct, None).decode()


def wrap_key(master_key: bytes, data_key: bytes) -> str:
    return encrypt(master_key, base64.b64encode(data_key).decode())


def unwrap_key(master_key: bytes, wrapped: str) -> bytes:
    return base64.b64decode(decrypt(master_key, wrapped))


def can_shred(patient_id: str) -> bool:
    """Informational — actual shredding happens by UPDATE on key_store."""
    from models import connect_db
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT shredded_at FROM key_store WHERE patient_id = ?", (patient_id,)
        ).fetchone()
        return row is not None and row["shredded_at"] is None
    finally:
        conn.close()