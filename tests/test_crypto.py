"""tests/test_crypto.py"""

import base64
import os
import sys
import uuid

import pytest
from cryptography.exceptions import InvalidTag

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import create_app
from services.crypto import (
    decrypt,
    encrypt,
    generate_data_key,
    get_master_key,
    unwrap_key,
    wrap_key,
)
from services.signing import generate_keypair, sign, verify


@pytest.fixture
def app_ctx(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app({"TESTING": True, "DATABASE": db_path, "DEV_MODE": True})
    with app.app_context():
        yield app


def test_aes_roundtrip():
    key = generate_data_key()
    ct = encrypt(key, "08012345678")
    assert decrypt(key, ct) == "08012345678"


def test_aes_different_ciphertext_per_call():
    key = generate_data_key()
    ct1 = encrypt(key, "08012345678")
    ct2 = encrypt(key, "08012345678")
    assert ct1 != ct2  # nonce randomness
    assert decrypt(key, ct1) == decrypt(key, ct2)


def test_aes_wrong_key_fails():
    key1 = generate_data_key()
    key2 = generate_data_key()
    ct = encrypt(key1, "secret")
    with pytest.raises(InvalidTag):
        decrypt(key2, ct)


def test_wrap_unwrap_key():
    master = get_master_key()
    data = generate_data_key()
    wrapped = wrap_key(master, data)
    unwrapped = unwrap_key(master, wrapped)
    assert unwrapped == data


def test_ed25519_roundtrip():
    priv, pub = generate_keypair()
    msg = b"hello chain"
    sig = sign(priv, msg)
    assert verify(pub, msg, sig) is True


def test_ed25519_wrong_message_fails():
    priv, pub = generate_keypair()
    sig = sign(priv, b"message a")
    assert verify(pub, b"message b", sig) is False


def test_ed25519_wrong_key_fails():
    priv1, _ = generate_keypair()
    _, pub2 = generate_keypair()
    sig = sign(priv1, b"message")
    assert verify(pub2, b"message", sig) is False


def test_ledger_event_is_signed(app_ctx):
    from services.ledger import append_event
    e = append_event(
        patient_id=str(uuid.uuid4()),
        event_type="SCREEN_POSITIVE",
        actor_id="pharmacy@test.demo",
        actor_role="pharmacy",
        payload={"systolic": 160, "diastolic": 100},
    )
    assert e["actor_signature"]
    assert e["actor_public_key"]
    assert verify(e["actor_public_key"], e["hash"].encode(), e["actor_signature"]) is True


def test_signed_event_hash_unchanged_by_sig(app_ctx):
    """Adding signature columns must not change the hash computation."""
    from services.ledger import append_event, compute_event_hash
    pid = str(uuid.uuid4())
    e = append_event(pid, "SCREEN_POSITIVE", "pharmacy@test.demo", "pharmacy", {})
    assert compute_event_hash(e) == e["hash"]


def test_chain_verify_counts_signatures(app_ctx):
    from services.ledger import append_event, connect_db, verify_patient_chain
    pid = str(uuid.uuid4())
    append_event(pid, "SCREEN_POSITIVE", "pharmacy@test.demo", "pharmacy", {})
    append_event(pid, "REFERRAL_CREATED", "pharmacy@test.demo", "pharmacy",
                 {"consent_version": "1.0", "consent_hash": "x"})
    conn = connect_db()
    try:
        r = verify_patient_chain(conn, pid)
    finally:
        conn.close()
    assert r["ok"] is True
    assert r["signed"] == 2
    assert r["unsigned"] == 0
    assert r["invalid_signature"] == 0


def test_crypto_shred_preserves_chain(app_ctx):
    from services.ledger import append_event, connect_db, verify_patient_chain
    from services.screening import ensure_patient

    pid = ensure_patient({
        "phone": "+2348099" + str(uuid.uuid4().int)[:6],
        "insurance_type": "nhia",
        "nhia_number": "NHIA-SHRED",
    })
    append_event(pid, "SCREEN_POSITIVE", "pharmacy@test.demo", "pharmacy", {})

    conn = connect_db()
    try:
        # Confirm phone is encrypted (ciphertext, not plaintext)
        row = conn.execute(
            "SELECT phone_encrypted FROM patient_contacts WHERE patient_id = ?", (pid,)
        ).fetchone()
        assert row is not None
        assert not row["phone_encrypted"].startswith("+")
        assert not row["phone_encrypted"].startswith("0")

        # Confirm key_store row exists
        ks = conn.execute(
            "SELECT shredded_at FROM key_store WHERE patient_id = ?", (pid,)
        ).fetchone()
        assert ks is not None
        assert ks["shredded_at"] is None

        # Simulate shred
        from services.ledger import utc_now
        conn.execute(
            "UPDATE key_store SET shredded_at = ? WHERE patient_id = ?",
            (utc_now(), pid),
        )

        # Chain still verifies
        r = verify_patient_chain(conn, pid)
        assert r["ok"] is True
        assert r["events"] == 1
    finally:
        conn.close()