"""
OneCare Loop — services/ledger.py

Hash-chained append with Ed25519 per-actor signing.
Signatures are over the hash, so they don't affect chain integrity.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from models import GENESIS_HASH, connect_db


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_event_hash(event: dict[str, Any]) -> str:
    """
    The chain hash. Does NOT include actor_signature or actor_public_key —
    signatures are over the resulting hash, not part of it.
    """
    material = {
        "id": event["id"],
        "seq": event["seq"],
        "patient_id": event["patient_id"],
        "referral_id": event.get("referral_id"),
        "event_type": event["event_type"],
        "actor_id": event["actor_id"],
        "actor_role": event["actor_role"],
        "payload_json": event["payload_json"],
        "prev_hash": event["prev_hash"],
        "occurred_at": event["occurred_at"],
        "recorded_at": event["recorded_at"],
    }
    return sha256_hex(canonical_json(material))


def _get_or_create_actor_key(conn: sqlite3.Connection, actor_id: str) -> tuple[str, str]:
    row = conn.execute(
        "SELECT private_pem, public_pem FROM actor_keys WHERE actor_id = ?",
        (actor_id,),
    ).fetchone()
    if row:
        return row["private_pem"], row["public_pem"]

    from services.signing import generate_keypair
    priv, pub = generate_keypair()
    conn.execute(
        "INSERT INTO actor_keys (actor_id, private_pem, public_pem, created_at) VALUES (?, ?, ?, ?)",
        (actor_id, priv, pub, utc_now()),
    )
    return priv, pub


def append_event(
    patient_id: str,
    event_type: str,
    actor_id: str,
    actor_role: str,
    payload: dict[str, Any] | None = None,
    referral_id: str | None = None,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        head = conn.execute(
            "SELECT head_seq, head_hash FROM ledger_head WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()

        seq = 1 if head is None else int(head["head_seq"]) + 1
        prev_hash = GENESIS_HASH if head is None else head["head_hash"]

        event = {
            "id": str(uuid.uuid4()),
            "seq": seq,
            "patient_id": patient_id,
            "referral_id": referral_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "payload_json": canonical_json(payload or {}),
            "prev_hash": prev_hash,
            "occurred_at": occurred_at or utc_now(),
            "recorded_at": utc_now(),
        }
        event["hash"] = compute_event_hash(event)

        priv_pem, pub_pem = _get_or_create_actor_key(conn, actor_id)
        from services.signing import sign
        signature = sign(priv_pem, event["hash"].encode())
        event["actor_signature"] = signature
        event["actor_public_key"] = pub_pem

        conn.execute(
            """
            INSERT INTO loop_events
                (id, seq, patient_id, referral_id, event_type, actor_id,
                 actor_role, payload_json, prev_hash, hash, occurred_at, recorded_at,
                 actor_signature, actor_public_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["id"],
                event["seq"],
                event["patient_id"],
                event["referral_id"],
                event["event_type"],
                event["actor_id"],
                event["actor_role"],
                event["payload_json"],
                event["prev_hash"],
                event["hash"],
                event["occurred_at"],
                event["recorded_at"],
                event["actor_signature"],
                event["actor_public_key"],
            ),
        )

        conn.execute(
            """
            INSERT INTO ledger_head (patient_id, head_seq, head_hash, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(patient_id) DO UPDATE SET
                head_seq = excluded.head_seq,
                head_hash = excluded.head_hash,
                updated_at = excluded.updated_at
            """,
            (patient_id, event["seq"], event["hash"], utc_now()),
        )

        conn.execute("COMMIT")
        return event
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def get_current_state(patient_id: str) -> str | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT event_type FROM loop_events WHERE patient_id = ? ORDER BY seq DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
        return row["event_type"] if row else None
    finally:
        conn.close()


def verify_patient_chain(
    conn: sqlite3.Connection,
    patient_id: str,
    verify_signatures: bool = True,
) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM loop_events WHERE patient_id = ? ORDER BY seq ASC",
        (patient_id,),
    ).fetchall()

    events = [dict(row) for row in rows]

    if not events:
        return {
            "ok": True,
            "patient_id": patient_id,
            "events": 0,
            "head_seq": 0,
            "head_hash": GENESIS_HASH,
            "broken_at": None,
            "signed": 0,
            "unsigned": 0,
            "invalid_signature": 0,
            "message": "no events for patient",
        }

    expected_prev = GENESIS_HASH
    signed = unsigned = invalid_sig = 0
    first_invalid_sig = None

    for index, event in enumerate(events, start=1):
        if event["seq"] != index:
            return {
                "ok": False,
                "patient_id": patient_id,
                "events": len(events),
                "broken_at": {
                    "seq": event["seq"],
                    "event_id": event["id"],
                    "reason": "sequence_gap",
                    "expected_seq": index,
                    "actual_seq": event["seq"],
                },
            }

        if event["prev_hash"] != expected_prev:
            return {
                "ok": False,
                "patient_id": patient_id,
                "events": len(events),
                "broken_at": {
                    "seq": event["seq"],
                    "event_id": event["id"],
                    "reason": "prev_hash_mismatch",
                    "expected_prev_hash": expected_prev,
                    "actual_prev_hash": event["prev_hash"],
                },
            }

        recomputed = compute_event_hash(event)
        if recomputed != event["hash"]:
            return {
                "ok": False,
                "patient_id": patient_id,
                "events": len(events),
                "broken_at": {
                    "seq": event["seq"],
                    "event_id": event["id"],
                    "reason": "hash_mismatch",
                    "expected_hash": event["hash"],
                    "recomputed_hash": recomputed,
                },
            }

        if verify_signatures:
            sig = event.get("actor_signature")
            pub = event.get("actor_public_key")
            if not sig or not pub:
                unsigned += 1
            else:
                from services.signing import verify as verify_sig
                if verify_sig(pub, event["hash"].encode(), sig):
                    signed += 1
                else:
                    invalid_sig += 1
                    if first_invalid_sig is None:
                        first_invalid_sig = {
                            "seq": event["seq"],
                            "event_id": event["id"],
                            "reason": "signature_invalid",
                        }

        expected_prev = event["hash"]

    if invalid_sig > 0:
        return {
            "ok": False,
            "patient_id": patient_id,
            "events": len(events),
            "broken_at": first_invalid_sig,
            "signed": signed,
            "unsigned": unsigned,
            "invalid_signature": invalid_sig,
        }

    head = conn.execute(
        "SELECT head_seq, head_hash FROM ledger_head WHERE patient_id = ?",
        (patient_id,),
    ).fetchone()

    if head is None:
        return {
            "ok": False,
            "patient_id": patient_id,
            "events": len(events),
            "broken_at": {
                "seq": len(events),
                "event_id": events[-1]["id"],
                "reason": "missing_ledger_head",
            },
        }

    if int(head["head_seq"]) != len(events) or head["head_hash"] != expected_prev:
        return {
            "ok": False,
            "patient_id": patient_id,
            "events": len(events),
            "broken_at": {
                "seq": len(events),
                "event_id": events[-1]["id"],
                "reason": "ledger_head_mismatch",
                "head_seq": int(head["head_seq"]),
                "head_hash": head["head_hash"],
                "computed_head_hash": expected_prev,
            },
        }

    return {
        "ok": True,
        "patient_id": patient_id,
        "events": len(events),
        "head_seq": int(head["head_seq"]),
        "head_hash": head["head_hash"],
        "broken_at": None,
        "signed": signed,
        "unsigned": unsigned,
        "invalid_signature": 0,
    }


def verify_all_chains(
    conn: sqlite3.Connection, verify_signatures: bool = True
) -> dict[str, Any]:
    patient_rows = conn.execute(
        "SELECT DISTINCT patient_id FROM loop_events ORDER BY patient_id"
    ).fetchall()

    results = [
        verify_patient_chain(conn, row["patient_id"], verify_signatures=verify_signatures)
        for row in patient_rows
    ]

    return {
        "ok": all(r["ok"] for r in results),
        "patients": results,
        "checked_at": utc_now(),
    }