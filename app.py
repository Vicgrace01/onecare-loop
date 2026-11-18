"""OneCare Loop — app.py"""

from __future__ import annotations

import json
import os

from flask import Flask, Response, current_app, jsonify, redirect, render_template, request, session

from models import connect_db, init_db
from routes.auth import bp as auth_bp
from routes.consent import bp as consent_bp
from routes.dropoff import bp as dropoff_bp
from routes.fhir import bp as fhir_bp
from routes.hospital import bp as hospital_bp
from routes.longitudinal import bp as longitudinal_bp
from routes.metrics import bp as metrics_bp
from routes.notifications import bp as notifications_bp
from routes.patient import bp as patient_bp
from routes.patient_auth import bp as patient_auth_bp
from routes.red_flag import bp as red_flag_bp
from routes.referral import bp as referral_bp
from routes.screening import bp as screening_bp
from services.auth import DEMO_PHONE, ensure_demo_patient, ensure_demo_users
from services.ledger import append_event, canonical_json, utc_now, verify_all_chains, verify_patient_chain
from services.loop import (
    CANONICAL_STATES, FAILURE_STATES,
    TransitionError, get_current_state, record_transition, start_loop,
)
from services.otp import find_patient_by_phone


def _require_admin():
    if not session.get("user_id"):
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if session.get("role") != "admin":
        return jsonify({"ok": False, "error": "forbidden"}), 403
    return None


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "onecare-loop-dev-only-change-me"),
        DATABASE=os.environ.get("ONECARE_DB", os.path.join(os.getcwd(), "onecare.db")),
        DEV_MODE=os.environ.get("ONECARE_DEV_MODE", "1") == "1",
        SEED_DEMO_PATIENT=os.environ.get("ONECARE_SEED_DEMO", "1") == "1",
    )

    if test_config:
        app.config.update(test_config)

    # Tests default to no demo patient unless they explicitly opt in.
    if app.config.get("TESTING") and "SEED_DEMO_PATIENT" not in (test_config or {}):
        app.config["SEED_DEMO_PATIENT"] = False

    init_db(app)

    with app.app_context():
        ensure_demo_users()
        if app.config["SEED_DEMO_PATIENT"]:
            try:
                ensure_demo_patient()
            except Exception:
                pass  # never fail app startup because of demo seed

    app.register_blueprint(auth_bp)
    app.register_blueprint(consent_bp)
    app.register_blueprint(dropoff_bp)
    app.register_blueprint(fhir_bp)
    app.register_blueprint(longitudinal_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(patient_auth_bp)
    app.register_blueprint(red_flag_bp)
    app.register_blueprint(screening_bp)
    app.register_blueprint(referral_bp)
    app.register_blueprint(hospital_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(metrics_bp)

    def require_login():
        if not session.get("user_id"):
            return redirect("/login")
        return None

    @app.get("/")
    def splash():
        return render_template("splash.html")

    @app.get("/proof")
    def proof():
        """Public redirect to the demo patient's closed-loop receipt.
        One click from splash to the wow. Seeded at startup."""
        pid = find_patient_by_phone(DEMO_PHONE)
        if not pid:
            try:
                pid = ensure_demo_patient()
            except Exception:
                pid = ""
        if pid:
            return redirect(f"/patient/receipt/{pid}")
        return redirect("/patient/login")

    @app.get("/login")
    def login_page():
        return redirect("/auth/login")

    @app.get("/signup")
    def signup_page():
        return redirect("/auth/signup")

    @app.get("/verify")
    def public_verify():
        return render_template("patient/verify.html")

    @app.get("/app")
    def dashboard():
        r = require_login()
        if r: return r
        return render_template("app/dashboard.html", active="dashboard")

    @app.get("/app/referrals")
    def referrals_page():
        r = require_login()
        if r: return r
        return render_template("app/referrals.html", active="referrals")

    @app.get("/app/patients")
    def patients_page():
        r = require_login()
        if r: return r
        return render_template("app/patients.html", active="patients")

    @app.get("/app/analytics")
    def analytics_page():
        r = require_login()
        if r: return r
        if session.get("role") != "admin":
            return redirect("/app")
        return render_template("app/analytics.html", active="analytics")

    @app.get("/app/alerts")
    def alerts_page():
        r = require_login()
        if r: return r
        return render_template("app/alerts.html", active="alerts")

    @app.get("/app/roi")
    def roi_page():
        r = require_login()
        if r: return r
        return render_template("app/roi.html", active="roi")

    @app.get("/app/pilot-plan")
    def pilot_plan_page():
        r = require_login()
        if r: return r
        return render_template("app/pilot_plan.html", active="pilot_plan")

    @app.get("/app/settings")
    def settings_page():
        r = require_login()
        if r: return r
        return render_template("app/settings.html", active="settings")

    @app.get("/app/profile")
    def profile_page():
        r = require_login()
        if r: return r
        return render_template("app/profile.html", active="profile")

    @app.get("/demo/pharmacy")
    def demo_pharmacy():
        r = require_login()
        if r: return r
        return render_template("app/pharmacy.html", active="demo_pharmacy")

    @app.get("/demo/hospital")
    def demo_hospital():
        r = require_login()
        if r: return r
        return render_template("app/hospital.html", active="demo_hospital")

    @app.get("/demo/patient")
    def demo_patient():
        return redirect("/patient/login")

    @app.get("/model/card")
    def model_card():
        r = require_login()
        if r: return r
        return render_template("app/model_card.html", active="model_card")

    @app.get("/model/datasheet")
    def datasheet():
        r = require_login()
        if r: return r
        return render_template("app/datasheet.html", active="datasheet")

    @app.get("/model/dpia")
    def dpia():
        r = require_login()
        if r: return r
        return render_template("app/dpia.html", active="dpia")

    @app.get("/model/ndpa")
    def ndpa_page():
        r = require_login()
        if r: return r
        return render_template("app/ndpa.html", active="ndpa")

    @app.get("/model/threat-model")
    def threat_model_page():
        r = require_login()
        if r: return r
        return render_template("app/threat_model.html", active="threat_model")

    @app.get("/model/consent-versions")
    def consent_versions_page():
        r = require_login()
        if r: return r
        return render_template("app/consent_versions.html", active="consent_versions")

    @app.get("/api/compliance/ndpa-checklist")
    def ndpa_checklist():
        return jsonify({
            "framework": "Nigeria Data Protection Act 2023",
            "generated_at": utc_now(),
            "sections": [
                {"section": "§24", "title": "Lawful basis", "items": [
                    {"basis": "consent", "scope": "all patient processing", "status": "BUILD"},
                    {"basis": "legal_obligation", "scope": "7-year retention of care events", "status": "BUILD"},
                    {"basis": "vital_interests", "scope": "emergency red-flag routing", "status": "SIMULATE"},
                ]},
                {"section": "§34-38", "title": "Data subject rights", "items": [
                    {"right": "access", "implementation": "patient receipt via OTP", "status": "BUILD"},
                    {"right": "rectification", "implementation": "corrective event append", "status": "BUILD"},
                    {"right": "erasure", "implementation": "crypto-shred PII, chain preserved", "status": "BUILD"},
                    {"right": "portability", "implementation": "JSONL export", "status": "BUILD"},
                    {"right": "objection", "implementation": "PATIENT_DECLINED event", "status": "BUILD"},
                ]},
                {"section": "§39", "title": "Security measures", "items": [
                    {"requirement": "encryption_in_transit", "status": "DEPLOY-CONFIG"},
                    {"requirement": "encryption_at_rest_pii", "status": "BUILD"},
                    {"requirement": "tamper_evidence", "status": "BUILD"},
                    {"requirement": "access_control", "status": "BUILD"},
                    {"requirement": "pseudonymisation", "status": "BUILD"},
                ]},
                {"section": "§40", "title": "Breach notification", "items": [
                    {"requirement": "72h_notification_ndpc", "status": "DOCUMENTED"},
                    {"requirement": "data_subject_notification", "status": "DOCUMENTED"},
                    {"requirement": "breach_detection", "status": "BUILD"},
                ]},
                {"section": "§41-43", "title": "Cross-border transfer", "items": [
                    {"requirement": "in_country_hosting", "status": "PHASED", "note": "pre-pilot blocker"},
                ]},
            ],
        })

    @app.get("/healthz")
    def healthz():
        try:
            conn = connect_db()
            conn.execute("SELECT 1").fetchone()
            conn.close()
            return jsonify({"ok": True, "service": "onecare-loop", "time": utc_now()})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.get("/api/audit/verify")
    def audit_verify_all():
        conn = connect_db()
        try:
            return jsonify(verify_all_chains(conn))
        finally:
            conn.close()

    @app.get("/api/audit/verify/<patient_id>")
    def audit_verify_patient(patient_id):
        conn = connect_db()
        try:
            return jsonify(verify_patient_chain(conn, patient_id))
        finally:
            conn.close()

    @app.get("/api/audit/export")
    def audit_export():
        r = _require_admin()
        if r: return r
        conn = connect_db()
        try:
            rows = conn.execute("SELECT * FROM loop_events ORDER BY patient_id, seq").fetchall()
            lines = [json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")) for row in rows]
            payload = "\n".join(lines) + ("\n" if lines else "")
            return Response(payload, mimetype="application/x-ndjson",
                            headers={"Content-Disposition": "attachment; filename=onecare-events.jsonl"})
        finally:
            conn.close()

    @app.post("/api/audit/tamper")
    def audit_tamper():
        if not current_app.config["DEV_MODE"]:
            return jsonify({"ok": False, "error": "dev_mode_only"}), 403
        r = _require_admin()
        if r: return r
        data = request.get_json(silent=True) or {}
        conn = connect_db()
        try:
            row = conn.execute("SELECT * FROM loop_events WHERE id = ?", (data.get("event_id"),)).fetchone()
            if not row:
                return jsonify({"ok": False, "error": "not_found"}), 404
            if conn.execute("SELECT 1 FROM tamper_backups WHERE event_id=?", (row["id"],)).fetchone():
                return jsonify({"ok": False, "error": "already_tampered"}), 409
            original = row["payload_json"]
            obj = json.loads(original)
            if not isinstance(obj, dict): obj = {"original": obj}
            obj["_tampered"] = True
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO tamper_backups (event_id, original_payload_json, created_at) VALUES (?,?,?)",
                         (row["id"], original, utc_now()))
            conn.execute("UPDATE loop_events SET payload_json=? WHERE id=?", (canonical_json(obj), row["id"]))
            conn.execute("COMMIT")
            return jsonify({"ok": True, "event_id": row["id"], "seq": row["seq"]})
        finally:
            conn.close()

    @app.post("/api/audit/restore")
    def audit_restore():
        if not current_app.config["DEV_MODE"]:
            return jsonify({"ok": False, "error": "dev_mode_only"}), 403
        r = _require_admin()
        if r: return r
        data = request.get_json(silent=True) or {}
        conn = connect_db()
        try:
            rows = conn.execute("SELECT event_id, original_payload_json FROM tamper_backups WHERE event_id=?",
                                (data.get("event_id"),)).fetchall()
            conn.execute("BEGIN IMMEDIATE")
            for r in rows:
                conn.execute("UPDATE loop_events SET payload_json=? WHERE id=?", (r["original_payload_json"], r["event_id"]))
                conn.execute("DELETE FROM tamper_backups WHERE event_id=?", (r["event_id"],))
            conn.execute("COMMIT")
            return jsonify({"ok": True, "restored": len(rows)})
        finally:
            conn.close()

    @app.post("/api/audit/dev/seed")
    def dev_seed():
        if not current_app.config["DEV_MODE"]:
            return jsonify({"ok": False}), 403
        pid = "DEMO-001"
        conn = connect_db()
        try:
            n = conn.execute("SELECT COUNT(*) AS n FROM loop_events WHERE patient_id=?", (pid,)).fetchone()["n"]
            if n:
                return jsonify({"ok": True, "seeded": False, "events": n})
        finally:
            conn.close()
        append_event(pid, "SCREEN_POSITIVE", "pharmacy@onecare.demo", "pharmacy", {"systolic": 168, "diastolic": 104})
        append_event(pid, "REFERRAL_CREATED", "pharmacy@onecare.demo", "pharmacy",
                     {"facility_id": "HOSP-A", "urgency": "urgent"}, referral_id="REF-DEMO-001")
        append_event(pid, "FACILITY_ACCEPTED", "hospital@onecare.demo", "hospital",
                     {"facility_id": "HOSP-A"}, referral_id="REF-DEMO-001")
        return jsonify({"ok": True, "seeded": True, "events": 3})

    @app.post("/api/loop/start")
    def loop_start():
        d = request.get_json(silent=True) or {}
        try:
            e = start_loop(d["patient_id"], d["actor_id"], d["actor_role"], d.get("payload", {}), d.get("referral_id"))
            return jsonify({"ok": True, "event": e})
        except KeyError as e:
            return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
        except TransitionError as e:
            return jsonify({"ok": False, "error": e.reason, "message": e.message}), 400

    @app.post("/api/loop/transition")
    def loop_transition():
        d = request.get_json(silent=True) or {}
        try:
            e = record_transition(d["patient_id"], d["to_state"], d["actor_id"], d["actor_role"], d.get("payload", {}), d.get("referral_id"))
            return jsonify({"ok": True, "event": e})
        except KeyError as e:
            return jsonify({"ok": False, "error": "missing_field", "field": str(e)}), 400
        except TransitionError as e:
            return jsonify({"ok": False, "error": e.reason, "message": e.message}), 400

    @app.get("/api/loop/state/<patient_id>")
    def loop_state(patient_id):
        s = get_current_state(patient_id)
        return jsonify({"ok": True, "patient_id": patient_id, "current_state": s,
                        "is_canonical": s in CANONICAL_STATES if s else False,
                        "is_failure": s in FAILURE_STATES if s else False})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5000")),
            debug=app.config["DEV_MODE"])