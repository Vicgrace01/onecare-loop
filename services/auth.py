"""OneCare Loop — services/auth.py — session-based demo auth + demo cohort seed."""

from __future__ import annotations

import hashlib
import uuid

from models import connect_db
from services.ledger import utc_now


DEMO_USERS = {
    "admin@onecare.demo":    ("Admin User",     "admin",    "System Administrator"),
    "hospital@onecare.demo": ("Dr. Adewale",    "hospital", "Lagos General Hospital"),
    "pharmacy@onecare.demo": ("Pharm. Chioma",  "pharmacy", "GreenLife Pharmacy, Yaba"),
}

DEMO_PASSWORD = "demo1234"

# Demo patient — kept as a module constant for backward compat with /proof route
DEMO_PHONE = "+2348099000001"
DEMO_DISPLAY_NAME = "Adaeze O."


def _hash_password(password: str) -> str:
    return hashlib.sha256(("onecare-salt::" + password).encode()).hexdigest()


def ensure_demo_users() -> None:
    conn = connect_db()
    try:
        for email, (name, role, org) in DEMO_USERS.items():
            existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO users (id, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), email, _hash_password(DEMO_PASSWORD), role, utc_now()),
            )
            conn.execute(
                "INSERT OR IGNORE INTO organisations (id, name, type, created_at) VALUES (?, ?, ?, ?)",
                (org, org, "hospital" if role == "hospital" else "pharmacy" if role == "pharmacy" else "donor", utc_now()),
            )
    finally:
        conn.close()


def ensure_demo_patient() -> str:
    """
    Seeds the full demo cohort (10 patients across all workflow states)
    and returns Adaeze's patient_id. Backward-compatible with the
    /proof route and app startup.

    Idempotent. If the cohort already exists, this is a fast no-op.
    """
    from services.demo_fixtures import DEMO_PHONE as COHORT_PHONE, seed_all
    from services.otp import find_patient_by_phone

    try:
        seed_all()
    except Exception:
        pass

    return find_patient_by_phone(COHORT_PHONE) or ""


def authenticate(email: str, password: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT id, email, role, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    if row["password_hash"] != _hash_password(password):
        return None
    return {"id": row["id"], "email": row["email"], "role": row["role"]}


def create_user(email: str, password: str, name: str, role: str) -> dict:
    conn = connect_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            raise ValueError("An account with this email already exists.")
        user_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, email, _hash_password(password), role, utc_now()),
        )
    finally:
        conn.close()
    return {"id": user_id, "email": email, "role": role, "name": name}


def get_user(user_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT id, email, role, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    name, _, org = DEMO_USERS.get(row["email"], (row["email"].split("@")[0].title(), "", ""))
    return {"id": row["id"], "email": row["email"], "role": row["role"], "name": name, "org": org}


def update_profile(user_id: str, name: str, org: str) -> None:
    pass