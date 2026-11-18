"""
OneCare Loop — services/screening.py

BP validation, red flag detection, patient/consent/screening creation.
Encrypts patient PII at capture time so crypto-shredding has something to shred.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from models import connect_db
from services.crypto import (
    encrypt as aes_encrypt,
    generate_data_key,
    get_master_key,
    wrap_key,
)
from services.ledger import canonical_json, utc_now
from services.loop import start_loop


SBP_POSITIVE = 140
DBP_POSITIVE = 90
SBP_RED_FLAG = 180
DBP_RED_FLAG = 120
RED_FLAG_SYMPTOMS = {
    "chest_pain", "one_sided_weakness", "vision_loss",
    "severe_headache", "shortness_of_breath",
}


class ScreeningError(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def ensure_org(org_id: str, name: str, org_type: str) -> None:
    conn = connect_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO organisations (id, name, type, created_at) VALUES (?, ?, ?, ?)",
            (org_id, name, org_type, utc_now()),
        )
    finally:
        conn.close()


def validate_bp(systolic: int, diastolic: int) -> None:
    if not isinstance(systolic, int) or not isinstance(diastolic, int):
        raise ScreeningError("invalid_bp", "systolic and diastolic must be integers")
    if systolic < 40 or systolic > 300:
        raise ScreeningError("invalid_bp", f"systolic {systolic} out of range [40, 300]")
    if diastolic < 20 or diastolic > 200:
        raise ScreeningError("invalid_bp", f"diastolic {diastolic} out of range [20, 200]")
    if systolic <= diastolic:
        raise ScreeningError("invalid_bp", f"systolic {systolic} must exceed diastolic {diastolic}")


def classify(systolic: int, diastolic: int, symptoms: list[str]) -> dict[str, Any]:
    red_flag = (
        systolic >= SBP_RED_FLAG
        or diastolic >= DBP_RED_FLAG
        or bool(set(symptoms) & RED_FLAG_SYMPTOMS)
    )
    positive = systolic >= SBP_POSITIVE or diastolic >= DBP_POSITIVE
    result = "positive" if positive else "negative"
    if red_flag:
        urgency = "emergency"
    elif positive and (systolic >= 160 or diastolic >= 100):
        urgency = "urgent"
    elif positive:
        urgency = "routine"
    else:
        urgency = None
    return {"result": result, "red_flag": red_flag, "urgency": urgency}


def _store_encrypted_phone(conn, patient_id: str, phone_hash: str, phone_plaintext: str, lang: str) -> None:
    master = get_master_key()
    data_key = generate_data_key()
    wrapped = wrap_key(master, data_key)
    ciphertext = aes_encrypt(data_key, phone_plaintext)

    conn.execute(
        "INSERT INTO key_store (patient_id, wrapped_key, key_id, created_at) VALUES (?, ?, ?, ?)",
        (patient_id, wrapped, str(uuid.uuid4()), utc_now()),
    )
    conn.execute(
        "INSERT INTO patient_contacts (id, patient_id, phone_hash, phone_encrypted, preferred_language, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), patient_id, phone_hash, ciphertext, lang, utc_now()),
    )


def ensure_patient(payload: dict) -> str:
    phone = payload.get("phone")
    phone_hash = hashlib.sha256(phone.encode()).hexdigest() if phone else None

    conn = connect_db()
    try:
        if payload.get("id"):
            pid = payload["id"]
            row = conn.execute("SELECT id FROM patients WHERE id = ?", (pid,)).fetchone()
            if not row:
                conn.execute(
                    "INSERT INTO patients (id, age_band, insurance_type, nhia_number, created_at) VALUES (?, ?, ?, ?, ?)",
                    (pid, payload.get("age_band"), payload.get("insurance_type"), payload.get("nhia_number"), utc_now()),
                )
            return pid

        if phone_hash:
            row = conn.execute(
                "SELECT patient_id FROM patient_contacts WHERE phone_hash = ?", (phone_hash,)
            ).fetchone()
            if row:
                return row["patient_id"]

        pid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO patients (id, age_band, insurance_type, nhia_number, created_at) VALUES (?, ?, ?, ?, ?)",
            (pid, payload.get("age_band"), payload.get("insurance_type"), payload.get("nhia_number"), utc_now()),
        )
        if phone:
            _store_encrypted_phone(
                conn, pid, phone_hash, phone, payload.get("preferred_language", "en")
            )
        return pid
    finally:
        conn.close()


def create_consent(patient_id: str, version: str, scope: list[str]) -> dict[str, Any]:
    granted_at = utc_now()
    scope_json = canonical_json({"scope": sorted(scope)})
    material = canonical_json({
        "patient_id": patient_id, "version": version,
        "scope_json": scope_json, "granted_at": granted_at,
    })
    consent_hash = hashlib.sha256(material.encode()).hexdigest()
    consent_id = str(uuid.uuid4())

    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO consents (id, patient_id, version, scope_json, granted_at, hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (consent_id, patient_id, version, scope_json, granted_at, consent_hash, granted_at),
        )
    finally:
        conn.close()

    return {"id": consent_id, "version": version, "scope_json": scope_json,
            "granted_at": granted_at, "hash": consent_hash}


def create_screening(
    patient_id: str, pharmacy_id: str,
    systolic: int, diastolic: int,
    symptoms: list[str], protocol_version: str,
) -> dict[str, Any]:
    validate_bp(systolic, diastolic)
    classification = classify(systolic, diastolic, symptoms)
    screening_id = str(uuid.uuid4())

    conn = connect_db()
    try:
        conn.execute(
            "INSERT INTO screenings (id, patient_id, pharmacy_id, systolic, diastolic, symptoms_json, protocol_version, result, red_flag, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                screening_id, patient_id, pharmacy_id, systolic, diastolic,
                canonical_json(symptoms), protocol_version,
                classification["result"], 1 if classification["red_flag"] else 0,
                utc_now(),
            ),
        )
    finally:
        conn.close()

    return {
        "id": screening_id, "systolic": systolic, "diastolic": diastolic,
        "symptoms": symptoms, "protocol_version": protocol_version, **classification,
    }


def run_screening(payload: dict) -> dict[str, Any]:
    screening_input = payload["screening"]
    pharmacy_id = screening_input["pharmacy_id"]

    ensure_org(pharmacy_id, pharmacy_id, "pharmacy")
    patient_id = ensure_patient(payload["patient"])
    consent = create_consent(patient_id, payload["consent"]["version"], payload["consent"]["scope"])
    screening = create_screening(
        patient_id, pharmacy_id,
        screening_input["systolic"], screening_input["diastolic"],
        screening_input.get("symptoms", []),
        screening_input["protocol_version"],
    )

    event_payload = {
        "systolic": screening["systolic"],
        "diastolic": screening["diastolic"],
        "protocol_version": screening["protocol_version"],
        "result": screening["result"],
        "red_flag": screening["red_flag"],
        "urgency": screening["urgency"],
        "consent_version": consent["version"],
        "consent_hash": consent["hash"],
    }

    event = start_loop(
        patient_id=patient_id,
        actor_id=payload.get("actor_id", f"{pharmacy_id}@onecare.demo"),
        actor_role="pharmacy",
        payload=event_payload,
        referral_id=None,
    )

    return {
        "patient_id": patient_id,
        "consent": consent,
        "screening": screening,
        "event": event,
    }