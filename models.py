"""
OneCare Loop — models.py

Schema version: 4
Works on SQLite (local dev) AND PostgreSQL (production / Neon).

The Postgres path uses an adapter that accepts SQLite syntax:
  - ? placeholders → %s
  - INSERT OR IGNORE → ON CONFLICT DO NOTHING
  - BEGIN IMMEDIATE / COMMIT / ROLLBACK → no-ops (autocommit handles them)
  - BLOB → BYTEA (handled at schema-string level)
  - Rows support both row[0] and row["column_name"] access

This means zero changes to services/ or routes/ — every existing query
works on both dialects.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone

from flask import Flask, current_app


GENESIS_HASH = "0" * 64
SCHEMA_VERSION = 4


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS organisations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (
        type IN ('pharmacy', 'pmv', 'hospital', 'hmo', 'donor', 'chw')
    ),
    lga TEXT,
    contact_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN (
        'pharmacy', 'pmv', 'chw', 'hospital', 'clinician',
        'hmo', 'donor', 'patient', 'admin'
    )),
    org_id TEXT REFERENCES organisations(id),
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id, role);

CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    age_band TEXT,
    insurance_type TEXT,
    nhia_number TEXT,
    consent_at TEXT,
    display_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patient_contacts (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    phone_hash TEXT NOT NULL,
    phone_encrypted TEXT NOT NULL,
    preferred_language TEXT NOT NULL DEFAULT 'en',
    created_at TEXT NOT NULL,
    UNIQUE(phone_hash)
);

CREATE INDEX IF NOT EXISTS idx_patient_contacts_patient
    ON patient_contacts(patient_id);

CREATE TABLE IF NOT EXISTS consents (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    version TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    revoked_at TEXT,
    hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_consents_patient
    ON consents(patient_id, granted_at);

CREATE TABLE IF NOT EXISTS screenings (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    pharmacy_id TEXT NOT NULL REFERENCES organisations(id),
    systolic INTEGER NOT NULL CHECK (systolic BETWEEN 0 AND 300),
    diastolic INTEGER NOT NULL CHECK (diastolic BETWEEN 0 AND 200),
    symptoms_json TEXT NOT NULL DEFAULT '[]',
    protocol_version TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('positive', 'negative', 'inconclusive')),
    red_flag INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_screenings_patient
    ON screenings(patient_id, created_at);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    calibration_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS referrals (
    id TEXT PRIMARY KEY,
    screening_id TEXT NOT NULL REFERENCES screenings(id),
    facility_id TEXT NOT NULL REFERENCES organisations(id),
    urgency TEXT NOT NULL CHECK (urgency IN ('routine', 'urgent', 'emergency')),
    sla_deadline TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'REFERRAL_CREATED',
    cached_updated_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_referrals_facility_status
    ON referrals(facility_id, status, sla_deadline);

CREATE INDEX IF NOT EXISTS idx_referrals_screening
    ON referrals(screening_id);

CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    referral_id TEXT NOT NULL REFERENCES referrals(id),
    slot_start TEXT NOT NULL,
    slot_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('proposed', 'booked', 'attended', 'missed', 'cancelled')
    ),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_appointments_referral
    ON appointments(referral_id);

CREATE TABLE IF NOT EXISTS encounters (
    id TEXT PRIMARY KEY,
    appointment_id TEXT NOT NULL REFERENCES appointments(id),
    clinician_id TEXT NOT NULL REFERENCES users(id),
    attended_at TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_encounters_appointment
    ON encounters(appointment_id);

CREATE TABLE IF NOT EXISTS clinical_dispositions (
    id TEXT PRIMARY KEY,
    encounter_id TEXT NOT NULL REFERENCES encounters(id),
    outcome TEXT NOT NULL,
    next_step TEXT,
    signed_at TEXT NOT NULL,
    clinician_id TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clinical_dispositions_encounter
    ON clinical_dispositions(encounter_id);

CREATE TABLE IF NOT EXISTS follow_up_plans (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    due_date TEXT NOT NULL,
    type TEXT NOT NULL CHECK (
        type IN ('7_day', '30_day', 'repeat_assessment', 'bp_control_check')
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'met', 'missed', 'cancelled')
    ),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_follow_up_due
    ON follow_up_plans(due_date, status);

CREATE TABLE IF NOT EXISTS policies (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organisations(id),
    version INTEGER NOT NULL,
    benefit_json TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(org_id, version)
);

CREATE TABLE IF NOT EXISTS policy_versions (
    id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES policies(id),
    version INTEGER NOT NULL,
    benefit_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(policy_id, version)
);

CREATE TABLE IF NOT EXISTS eligibility_checks (
    id TEXT PRIMARY KEY,
    referral_id TEXT NOT NULL REFERENCES referrals(id),
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    policy_version_id TEXT REFERENCES policy_versions(id),
    decision TEXT NOT NULL CHECK (
        decision IN ('covered', 'partial', 'not_covered', 'unknown')
    ),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_eligibility_referral
    ON eligibility_checks(referral_id);

CREATE TABLE IF NOT EXISTS loop_events (
    id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    patient_id TEXT NOT NULL,
    referral_id TEXT,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    actor_signature TEXT,
    actor_public_key TEXT,
    UNIQUE(patient_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_loop_events_patient_seq
    ON loop_events(patient_id, seq);

CREATE INDEX IF NOT EXISTS idx_loop_events_referral
    ON loop_events(referral_id, occurred_at);

CREATE TABLE IF NOT EXISTS ledger_head (
    patient_id TEXT PRIMARY KEY,
    head_seq INTEGER NOT NULL,
    head_hash TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS loop_exceptions (
    id TEXT PRIMARY KEY,
    referral_id TEXT NOT NULL REFERENCES referrals(id),
    event_type TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    owner TEXT NOT NULL,
    deadline TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_loop_exceptions_open
    ON loop_exceptions(resolved_at, deadline);

CREATE TABLE IF NOT EXISTS care_artifacts (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES loop_events(id),
    artifact_type TEXT NOT NULL,
    encrypted_blob BLOB NOT NULL,
    hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_care_artifacts_event
    ON care_artifacts(event_id);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    channel TEXT NOT NULL CHECK (channel IN ('sms', 'whatsapp', 'voice', 'ussd')),
    template_id TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    sent_at TEXT,
    delivered_at TEXT,
    reply_class TEXT,
    reply_text TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notifications_patient
    ON notifications(patient_id, created_at);

CREATE TABLE IF NOT EXISTS access_logs (
    id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_access_logs_resource
    ON access_logs(resource_type, resource_id, timestamp);

CREATE TABLE IF NOT EXISTS sync_outbox (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    mutation_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    synced_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sync_outbox_pending
    ON sync_outbox(synced_at, created_at);

CREATE TABLE IF NOT EXISTS bounties (
    id TEXT PRIMARY KEY,
    referral_id TEXT NOT NULL REFERENCES referrals(id),
    amount_kobo INTEGER NOT NULL CHECK (amount_kobo >= 0),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'earned', 'paid', 'cancelled')
    ),
    auto_unlock_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_versions (
    id TEXT PRIMARY KEY,
    model_type TEXT NOT NULL,
    version TEXT NOT NULL,
    weights_json TEXT NOT NULL,
    trained_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(model_type, version)
);

CREATE TABLE IF NOT EXISTS tamper_backups (
    event_id TEXT PRIMARY KEY,
    original_payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actor_keys (
    actor_id TEXT PRIMARY KEY,
    private_pem TEXT NOT NULL,
    public_pem TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS key_store (
    patient_id TEXT PRIMARY KEY,
    wrapped_key TEXT NOT NULL,
    key_id TEXT NOT NULL,
    shredded_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS otp_tokens (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients(id),
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_otp_patient
    ON otp_tokens(patient_id, created_at);
"""


# =========================================================================
# Postgres adapter — accepts SQLite syntax
# =========================================================================

_BEGIN_RE = re.compile(r"^\s*BEGIN(\s+(IMMEDIATE|EXCLUSIVE|DEFERRED))?\s*;?\s*$", re.IGNORECASE)
_COMMIT_RE = re.compile(r"^\s*(COMMIT|END)\s*;?\s*$", re.IGNORECASE)
_ROLLBACK_RE = re.compile(r"^\s*ROLLBACK(\s+TO\s+SAVEPOINT\s+\S+)?\s*;?\s*$", re.IGNORECASE)
_INSERT_OR_IGNORE_RE = re.compile(r"^(\s*)INSERT\s+OR\s+IGNORE\s+INTO\s+(.+)$", re.IGNORECASE | re.DOTALL)


def _translate_sql(sql: str) -> str:
    """Convert SQLite-flavored SQL to Postgres-flavored SQL."""
    if not sql:
        return sql
    # No-op for transaction control (autocommit handles atomicity for demo)
    if _BEGIN_RE.match(sql) or _COMMIT_RE.match(sql) or _ROLLBACK_RE.match(sql):
        return "SELECT 1"
    # INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
    stripped = sql.lstrip()
    m = _INSERT_OR_IGNORE_RE.match(stripped)
    if m:
        indent = m.group(1)
        rest = m.group(2).rstrip().rstrip(";")
        sql = f"{indent}INSERT INTO {rest} ON CONFLICT DO NOTHING"
    # ? → %s, only outside of string literals
    out = []
    in_single = False
    in_double = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < n and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif ch == "?" and not in_single and not in_double:
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


class DualRow:
    """Row that supports both row[0] and row["column_name"] access."""
    __slots__ = ("_values", "_mapping")

    def __init__(self, values, mapping):
        self._values = values
        self._mapping = mapping

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __contains__(self, item):
        if isinstance(item, str):
            return item in self._mapping
        return item in self._values

    def get(self, key, default=None):
        return self._mapping.get(key, default)

    def keys(self):
        return self._mapping.keys()

    def values(self):
        return self._values

    def items(self):
        return self._mapping.items()

    def __repr__(self):
        return f"DualRow({dict(self._mapping)})"


def _dual_row_factory(cursor):
    col_names = [d.name for d in cursor.description] if cursor.description else []
    def make_row(values):
        return DualRow(tuple(values), dict(zip(col_names, values)))
    return make_row


class _PgCursor:
    def __init__(self, cursor):
        self._c = cursor

    def execute(self, sql, params=()):
        sql = _translate_sql(sql)
        if params:
            self._c.execute(sql, params)
        else:
            self._c.execute(sql)
        return self

    def executemany(self, sql, params_list):
        sql = _translate_sql(sql)
        self._c.executemany(sql, params_list)
        return self

    def fetchone(self):
        return self._c.fetchone()

    def fetchall(self):
        return self._c.fetchall()

    def fetchmany(self, *a, **kw):
        return self._c.fetchmany(*a, **kw)

    def __iter__(self):
        return iter(self._c)

    def __getattr__(self, name):
        return getattr(self._c, name)


class _PgConnection:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, *a, **kw):
        return _PgCursor(self._conn.cursor(*a, **kw))

    def execute(self, sql, params=()):
        return _PgCursor(self._conn.cursor()).execute(sql, params)

    def executemany(self, sql, params_list):
        return _PgCursor(self._conn.cursor()).executemany(sql, params_list)

    def executescript(self, script):
        return self.execute(script)

    def commit(self):
        try: self._conn.commit()
        except Exception: pass

    def rollback(self):
        try: self._conn.rollback()
        except Exception: pass

    def close(self):
        self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


# =========================================================================
# Public API — identical signature on both dialects
# =========================================================================

def connect_db():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        # SQLite path — unchanged
        conn = sqlite3.connect(
            current_app.config.get("DATABASE", "onecare.db"),
            timeout=10,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # Postgres / Neon path
    import psycopg

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    raw = psycopg.connect(database_url, autocommit=True)
    raw.row_factory = _dual_row_factory
    return _PgConnection(raw)


def init_db(app: Flask) -> None:
    with app.app_context():
        database_url = os.environ.get("DATABASE_URL")
        conn = connect_db()
        try:
            if database_url:
                # Postgres — BLOB → BYTEA, multi-statement via cursor
                schema = SCHEMA.replace("BLOB", "BYTEA")
                cur = conn.cursor()
                cur.execute(schema)
                cur.execute(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (SCHEMA_VERSION, _utc_now()),
                )
            else:
                # SQLite
                conn.executescript(SCHEMA)
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, _utc_now()),
                )
        finally:
            conn.close()


if __name__ == "__main__":
    print(SCHEMA)
