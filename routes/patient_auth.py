"""
OneCare Loop — routes/patient_auth.py

Patient demo works like staff demo: pick a patient, enter the app as them.

  GET  /patient              → if logged in: patient home. If not: splash.
  GET  /patient/login        → patient picker (choose who to sign in as)
  GET  /patient/demo-login/<patient_id> → log in as that specific patient
  GET  /patient/demo-login   → redirect to picker (backward compat)
"""

from __future__ import annotations

import os

from flask import Blueprint, redirect, render_template, request, session, jsonify

from models import connect_db
from services.companion import build_patient_home
from services.crypto import decrypt, get_master_key, unwrap_key
from services.ledger import get_current_state
from services.otp import find_patient_by_phone, generate_otp, verify_otp


bp = Blueprint("patient_auth", __name__, url_prefix="/patient")


def _dev_mode() -> bool:
    return os.environ.get("ONECARE_DEV_MODE", "1") == "1"


def _require_patient():
    return session.get("patient_id")


@bp.get("/demo-login")
def demo_login_legacy():
    """Backward compat — old link goes to picker."""
    return redirect("/patient/login")


@bp.get("/demo-login/<patient_id>")
def demo_login(patient_id):
    """Log in as a specific patient. Used by the patient picker."""
    if not _dev_mode():
        return redirect("/patient/login")

    conn = connect_db()
    try:
        exists = conn.execute("SELECT 1 FROM patients WHERE id = ?", (patient_id,)).fetchone()
    finally:
        conn.close()
    if not exists:
        return redirect("/patient/login")

    session["patient_id"] = patient_id
    session["patient_role"] = "patient"
    return redirect("/patient")


@bp.get("")
@bp.get("/")
def home():
    pid = _require_patient()
    if not pid:
        return redirect("/")
    return render_template("patient/home.html", patient_id=pid)


@bp.get("/login")
def login_page():
    if session.get("patient_id"):
        return redirect("/patient")
    return render_template("patient/login.html")


@bp.get("/login/demo-phones")
def demo_phones():
    if not _dev_mode():
        return jsonify({"ok": False, "error": "dev_mode_disabled"}), 403

    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT pc.patient_id, pc.phone_encrypted, ks.wrapped_key, ks.shredded_at, "
            "       p.display_name, p.age_band, p.insurance_type "
            "FROM patient_contacts pc "
            "LEFT JOIN key_store ks ON ks.patient_id = pc.patient_id "
            "LEFT JOIN patients p ON p.id = pc.patient_id "
            "ORDER BY pc.created_at DESC LIMIT 12"
        ).fetchall()
        patients = []
        for row in rows:
            if row["shredded_at"] is not None:
                continue
            if not row["wrapped_key"] or not row["phone_encrypted"]:
                continue
            try:
                master = get_master_key()
                key = unwrap_key(master, row["wrapped_key"])
                phone = decrypt(key, row["phone_encrypted"])
            except Exception:
                continue
            event_count = conn.execute(
                "SELECT COUNT(*) FROM loop_events WHERE patient_id = ?",
                (row["patient_id"],)
            ).fetchone()[0]
            state = get_current_state(row["patient_id"]) or "NONE"
            patients.append({
                "patient_id": row["patient_id"],
                "phone": phone,
                "display_name": row["display_name"] or "Unnamed patient",
                "age_band": row["age_band"],
                "insurance_type": row["insurance_type"],
                "event_count": event_count,
                "state": state,
            })
    finally:
        conn.close()

    return jsonify({"ok": True, "patients": patients, "phones": patients})


@bp.post("/login/request-otp")
def request_otp():
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    if not phone:
        return jsonify({"ok": False, "error": "missing_phone"}), 400

    patient_id = find_patient_by_phone(phone)
    if not patient_id:
        return jsonify({"ok": True, "known": False,
                        "message": "If that number is on file, a code has been sent."})

    otp = generate_otp(patient_id)
    try:
        from services.sms import send as sms_send
        sms_send(patient_id=patient_id, template_id="screening_positive", channel="sms",
                 context={"systolic": "—", "diastolic": "—", "facility": "OneCare Loop (OTP)"})
    except Exception:
        pass

    resp = {"ok": True, "known": True, "patient_id": patient_id}
    if _dev_mode():
        resp["dev_code"] = otp["code"]
    return jsonify(resp)


@bp.post("/login/verify-otp")
def verify_otp_route():
    data = request.get_json(silent=True) or {}
    patient_id = data.get("patient_id")
    code = (data.get("code") or "").strip()
    if not patient_id or not code:
        return jsonify({"ok": False, "error": "missing_field"}), 400

    result = verify_otp(patient_id, code)
    if not result["ok"]:
        return jsonify({"ok": False, "error": result["reason"]}), 400

    session["patient_id"] = patient_id
    session["patient_role"] = "patient"
    return jsonify({"ok": True, "redirect": "/patient"})


@bp.post("/logout")
def logout():
    session.pop("patient_id", None)
    session.pop("patient_role", None)
    return jsonify({"ok": True, "redirect": "/"})


@bp.get("/me")
def me():
    pid = session.get("patient_id")
    if not pid:
        return jsonify({"ok": False}), 401
    return jsonify({"ok": True, "patient_id": pid})


@bp.get("/companion")
def companion():
    pid = _require_patient()
    if not pid:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return jsonify(build_patient_home(pid))


@bp.get("/receipt")
def receipt_own():
    pid = session.get("patient_id")
    if not pid:
        return redirect("/patient/login")
    return render_template("patient/receipt.html", patient_id=pid)


@bp.get("/receipt/<patient_id>")
def receipt_public(patient_id):
    return render_template("patient/receipt.html", patient_id=patient_id)


@bp.post("/seed")
def seed_endpoint():
    data = request.get_json(silent=True) or {}
    patient_id = data.get("patient_id") or session.get("patient_id")
    if not patient_id:
        return jsonify({"ok": False, "error": "missing_patient_id"}), 400
    if not _dev_mode() and not session.get("user_id"):
        if session.get("patient_id") != patient_id:
            return jsonify({"ok": False, "error": "unauthorized"}), 401

    from services.demo_seed import seed_full_journey
    try:
        result = seed_full_journey(patient_id)
    except Exception as e:
        return jsonify({"ok": False, "error": "seed_failed", "message": str(e)}), 500
    return jsonify(result)