"""smoke_test.py — one command, no login, full product coverage."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["ONECARE_DB"] = str(Path(_tmp) / "smoke.db")

from app import create_app  # noqa: E402


PASS, FAIL = "✓", "✗"
results: list[tuple[str, str, str]] = []


def check(name: str, fn):
    try:
        fn()
        results.append((PASS, name, ""))
        print(f"  {PASS} {name}")
    except Exception as e:
        msg = str(e) or type(e).__name__
        results.append((FAIL, name, msg[:200]))
        print(f"  {FAIL} {name}  —  {msg[:200]}")


def section(title: str):
    print(f"\n[{title}]")


def main() -> int:
    app = create_app({"TESTING": True, "DATABASE": os.environ["ONECARE_DB"], "DEV_MODE": True})
    state: dict = {}

    with app.test_client() as c:
        # ---------------- AUTH ----------------
        section("Auth")

        def signup():
            r = c.post("/auth/signup", json={
                "name": "Smoke Tester", "email": "smoke@test.demo",
                "password": "smoketest123", "role": "admin",
            })
            assert r.status_code == 200, r.get_json()
        check("POST /auth/signup creates user", signup)

        def me():
            j = c.get("/auth/me").get_json()
            assert j["user"]["email"] == "smoke@test.demo", j
        check("GET /auth/me returns session user", me)

        def logout():
            c.post("/auth/logout")
            assert c.get("/auth/me").status_code == 401
        check("POST /auth/logout clears session", logout)

        def login():
            j = c.post("/auth/login", json={
                "email": "smoke@test.demo", "password": "smoketest123",
            }).get_json()
            assert j["ok"] is True, j
        check("POST /auth/login re-authenticates", login)

        # ---------------- PAGES ----------------
        section("Pages")
        for p in ["/", "/login", "/signup", "/app", "/app/referrals", "/app/patients",
                  "/app/analytics", "/app/settings", "/app/profile",
                  "/demo/pharmacy", "/demo/hospital"]:
            def check_page(p=p):
                r = c.get(p)
                assert r.status_code in (200, 302), f"{p} → {r.status_code}"
            check(f"GET {p}", check_page)

        # ---------------- COMPLIANCE ----------------
        section("Compliance")
        for p in ["/model/card", "/model/datasheet", "/model/dpia",
                  "/model/ndpa", "/model/threat-model", "/model/consent-versions"]:
            def check_comp(p=p):
                r = c.get(p)
                assert r.status_code == 200, f"{p} → {r.status_code}"
            check(f"GET {p}", check_comp)

        def ndpa_json():
            j = c.get("/api/compliance/ndpa-checklist").get_json()
            assert j["framework"].startswith("Nigeria"), j
            assert len(j["sections"]) >= 5, j
        check("GET /api/compliance/ndpa-checklist", ndpa_json)

        def model_card_excludes_clinical_llm():
            j = c.get("/model/card")
            assert j.status_code == 200
            assert b"Clinical content generator" in j.data
            assert b"EXCLUDED" in j.data
        check("model card excludes clinical content LLM (documented)", model_card_excludes_clinical_llm)

        # ---------------- CANONICAL LOOP ----------------
        section("Canonical loop")

        def screen():
            r = c.post("/api/screening", json={
                "patient": {"age_band": "40-49", "insurance_type": "nhia",
                            "nhia_number": "NHIA-SMOKE", "phone": "+2348099990001"},
                "consent": {"version": "1.0", "scope": ["screening", "referral", "follow_up"]},
                "screening": {"pharmacy_id": "PHARM-A", "systolic": 185, "diastolic": 122,
                              "symptoms": [], "protocol_version": "HTN-PROTOCOL-v1"},
                "actor_id": "pharmacy@onecare.demo",
            })
            assert r.status_code == 201, r.get_json()
            j = r.get_json()
            assert j["screening"]["red_flag"] is True, j["screening"]
            assert j["screening"]["urgency"] == "emergency", j["screening"]
            state["pid"] = j["patient_id"]
            state["sid"] = j["screening"]["id"]
        check("screen 185/122 → red_flag + emergency", screen)

        def refer():
            r = c.post("/api/referral", json={
                "screening_id": state["sid"], "facility_id": "HOSP-A",
                "actor_id": "pharmacy@onecare.demo",
            })
            assert r.status_code == 201, r.get_json()
            j = r.get_json()
            assert j["eligibility"]["decision"] == "covered", j
            assert j["event"]["seq"] == 2, j["event"]
            state["rid"] = j["referral_id"]
            state["nid"] = j["notification"]["notification_id"] if j.get("notification") and j["notification"].get("ok") else None
        check("referral created, covered, seq 2, SMS simulated", refer)

        def accept():
            j = c.post(f"/api/referrals/{state['rid']}/accept",
                       json={"actor_id": "hospital@onecare.demo"}).get_json()
            assert j["event"]["event_type"] == "FACILITY_ACCEPTED", j
        check("hospital accepts", accept)

        def book():
            r = c.post(f"/api/referrals/{state['rid']}/book", json={
                "actor_id": "hospital@onecare.demo",
                "slot_start": "2026-11-20T09:00:00Z", "slot_end": "2026-11-20T09:30:00Z",
            })
            assert r.status_code == 200, r.get_json()
        check("hospital books", book)

        def attest():
            r = c.post(f"/api/referrals/{state['rid']}/attest",
                       json={"actor_id": "hospital@onecare.demo",
                             "clinician_id": "doc@onecare.demo"})
            assert r.status_code == 200, r.get_json()
        check("hospital attests", attest)

        def counter():
            j = c.post(f"/api/referrals/{state['rid']}/counter-refer", json={
                "actor_id": "doc@onecare.demo", "clinician_id": "doc@onecare.demo",
                "outcome": "started_medication", "next_step": "BP review in 30 days",
            }).get_json()
            assert j["event"]["event_type"] == "CLINICAL_DISPOSITION_RETURNED", j
        check("clinician counter-refers → loop closed", counter)

        def verify_chain():
            j = c.get(f"/api/audit/verify/{state['pid']}").get_json()
            assert j["ok"] is True, j
            assert j["events"] == 6, j["events"]
            assert j["signed"] == 6, j["signed"]
            assert j["invalid_signature"] == 0, j
        check("chain verifies with 6 events, all signed", verify_chain)

        def receipt():
            j = c.get(f"/api/patient/{state['pid']}/receipt").get_json()
            assert j["verified"] is True, j
            assert len(j["messages"]) == 6, len(j["messages"])
        check("patient receipt has 6 verified messages", receipt)

        # ---------------- FHIR ----------------
        section("FHIR")

        def fhir_metadata():
            j = c.get("/api/fhir/metadata").get_json()
            assert j["resourceType"] == "CapabilityStatement", j
            assert j["fhirVersion"] == "4.0.1", j
        check("GET /api/fhir/metadata — CapabilityStatement", fhir_metadata)

        def fhir_export():
            j = c.get("/api/fhir/export").get_json()
            assert j["resourceType"] == "Bundle", j
            assert j["type"] == "collection", j
            assert j["total"] > 0, j
            types = {e["resource"]["resourceType"] for e in j["entry"]}
            for t in ["Patient", "Observation", "ServiceRequest", "Task", "Appointment", "Encounter", "ClinicalImpression"]:
                assert t in types, f"missing {t}: {types}"
        check("GET /api/fhir/export — full Bundle with 7 resource types", fhir_export)

        def fhir_patient():
            j = c.get(f"/api/fhir/patient/{state['pid']}").get_json()
            assert j["resourceType"] == "Bundle", j
            assert j["total"] >= 6, j["total"]
        check("GET /api/fhir/patient/<id> — scoped bundle", fhir_patient)

        def fhir_no_pii():
            j = c.get("/api/fhir/export").get_json()
            for entry in j["entry"]:
                if entry["resource"]["resourceType"] == "Patient":
                    r = entry["resource"]
                    assert "name" not in r, "Patient has name"
                    assert "telecom" not in r, "Patient has telecom"
                    assert "address" not in r, "Patient has address"
        check("FHIR Patient resources omit name/telecom/address", fhir_no_pii)

        # ---------------- NOTIFICATIONS ----------------
        section("Notifications (SMS/WhatsApp simulated)")

        def referral_sms_fired():
            j = c.get(f"/api/notifications/patient/{state['pid']}").get_json()
            assert len(j["notifications"]) >= 1, j
            row = j["notifications"][0]
            assert row["template_id"] == "referral_created", row
            assert row["channel"] == "sms", row
        check("referral triggered a simulated SMS notification", referral_sms_fired)

        def whatsapp_send():
            j = c.post("/api/notifications/send", json={
                "patient_id": state["pid"],
                "template_id": "screening_positive",
                "channel": "whatsapp",
                "context": {"systolic": 185, "diastolic": 122, "facility": "HOSP-A"},
            }).get_json()
            assert j["ok"] is True, j
            assert j["channel"] == "whatsapp", j
            assert "SIMULATED" in j["note"], j
        check("POST /api/notifications/send (whatsapp) — simulated envelope", whatsapp_send)

        def reply_yes():
            if not state.get("nid"):
                raise AssertionError("no notification id captured")
            j = c.post("/api/notifications/simulate-reply", json={
                "notification_id": state["nid"], "reply_text": "Yes I will come",
            }).get_json()
            assert j["ok"] is True, j
            assert j["classification"]["class"] == "yes", j["classification"]
        check("POST /api/notifications/simulate-reply (\"yes\") — classified yes", reply_yes)

        def thread_records_reply():
            j = c.get(f"/api/notifications/patient/{state['pid']}").get_json()
            found = [n for n in j["notifications"] if n["reply_text"]]
            assert found, j
            assert found[0]["reply_class"] == "yes", found[0]
        check("reply visible in patient thread with class", thread_records_reply)

        # ---------------- CLASSIFIER ----------------
        section("Classifier")

        def classify_yes():
            j = c.post("/api/classify", json={"text": "Yes I can", "language": "en"}).get_json()
            assert j["class"] == "yes", j
        check("classify(\"Yes I can\") → yes", classify_yes)

        def classify_no():
            j = c.post("/api/classify", json={"text": "No I cannot", "language": "en"}).get_json()
            assert j["class"] == "no", j
        check("classify(\"No I cannot\") → no", classify_no)

        def classify_reschedule():
            j = c.post("/api/classify", json={"text": "can we reschedule", "language": "en"}).get_json()
            assert j["class"] == "reschedule", j
        check("classify(\"can we reschedule\") → reschedule", classify_reschedule)

        def classify_stop():
            j = c.post("/api/classify", json={"text": "STOP", "language": "en"}).get_json()
            assert j["class"] == "stop", j
        check("classify(\"STOP\") → stop", classify_stop)

        def classify_unknown():
            j = c.post("/api/classify", json={"text": "random", "language": "en"}).get_json()
            assert j["class"] == "unknown", j
        check("classify(\"random\") → unknown", classify_unknown)

        # ---------------- MULTILINGUAL ----------------
        section("Multilingual templates")

        def templates_endpoint():
            j = c.get("/api/templates").get_json()
            assert j["ok"] is True, j
            assert set(j["languages"]) == {"en", "pcm", "ig", "ha", "yo"}, j["languages"]
            for tid in ["screening_positive", "referral_created", "appointment_booked",
                        "counter_referral", "consent_request"]:
                assert tid in j["templates"], f"missing {tid}"
        check("GET /api/templates — 5 languages × 5 templates", templates_endpoint)

        def native_review_flagged():
            j = c.get("/api/templates").get_json()
            for tid, meta in j["templates"].items():
                for lang in ["pcm", "ig", "ha", "yo"]:
                    assert lang in meta["needs_native_review"], f"{tid}/{lang} not flagged for native review"
        check("all non-English templates flagged needs_native_review", native_review_flagged)

        # ---------------- DROP-OFF ----------------
        section("Drop-off risk")

        def model_summary():
            j = c.get("/api/dropoff/model").get_json()
            assert j["ok"] is True, j
            assert len(j["features"]) == 7, j["features"]
            assert j["trained_on"] == 2000, j
            assert j["label"] == "P(drop_off)", j
        check("GET /api/dropoff/model — 7 features, P(drop_off)", model_summary)

        def score_endpoint():
            j = c.post("/api/dropoff/score", json={"referral_id": state["rid"]}).get_json()
            assert j["ok"] is True, j
            assert 0.0 <= j["probability"] <= 1.0, j
            assert j["tier"] in ("low", "medium", "high"), j
        check("POST /api/dropoff/score — probability + tier", score_endpoint)

        def self_pay_higher():
            r2 = c.post("/api/screening", json={
                "patient": {"age_band": "40-49", "insurance_type": "self_pay",
                            "nhia_number": None, "phone": "+2348099990010"},
                "consent": {"version": "1.0", "scope": ["screening", "referral"]},
                "screening": {"pharmacy_id": "PHARM-A", "systolic": 185, "diastolic": 122,
                              "symptoms": [], "protocol_version": "HTN-PROTOCOL-v1"},
                "actor_id": "pharmacy@onecare.demo",
            }).get_json()
            r3 = c.post("/api/referral", json={
                "screening_id": r2["screening"]["id"], "facility_id": "HOSP-A",
            }).get_json()
            p_nhia = c.post("/api/dropoff/score", json={"referral_id": state["rid"]}).get_json()["probability"]
            p_sp = c.post("/api/dropoff/score", json={"referral_id": r3["referral_id"]}).get_json()["probability"]
            assert p_sp > p_nhia, f"self-pay {p_sp} not > nhia {p_nhia}"
        check("drop-off: self-pay scores higher than nhia at same BP", self_pay_higher)

        # ---------------- CRYPTO ----------------
        section("Crypto")

        def signatures_endpoint():
            j = c.get("/api/audit/verify-signatures").get_json()
            assert j["ok"] is True, j
            assert j["summary"]["signed"] >= 6, j["summary"]
            assert j["summary"]["invalid"] == 0, j["summary"]
        check("GET /api/audit/verify-signatures — all signed", signatures_endpoint)

        def event_has_signature():
            export = c.get("/api/audit/export").get_data(as_text=True)
            events = [json.loads(l) for l in export.strip().split("\n") if l]
            mine = [e for e in events if e["patient_id"] == state["pid"]]
            for e in mine:
                assert e["actor_signature"], f"seq {e['seq']} unsigned"
                assert e["actor_public_key"], f"seq {e['seq']} missing pubkey"
        check("every event carries signature + public key", event_has_signature)

        # ---------------- TAMPER ----------------
        section("Tamper detection")

        def tamper():
            export = c.get("/api/audit/export").get_data(as_text=True)
            events = [json.loads(l) for l in export.strip().split("\n") if l]
            mine = [e for e in events if e["patient_id"] == state["pid"]]
            target = mine[2]
            j = c.post("/api/audit/tamper", json={"event_id": target["id"]}).get_json()
            assert j["ok"] is True, j
            state["tid"] = target["id"]
            state["tseq"] = target["seq"]
        check("tamper 3rd event of chain", tamper)

        def broken():
            j = c.get(f"/api/audit/verify/{state['pid']}").get_json()
            assert j["ok"] is False, "chain still verified"
            assert j["broken_at"]["seq"] == state["tseq"], j
            assert j["broken_at"]["reason"] == "hash_mismatch", j
        check("verify fails at tampered seq with hash_mismatch", broken)

        def restore():
            j = c.post("/api/audit/restore",
                       json={"event_id": state["tid"]}).get_json()
            assert j["ok"] is True, j
        check("restore tampered event", restore)

        def re_verify():
            j = c.get(f"/api/audit/verify/{state['pid']}").get_json()
            assert j["ok"] is True, j
        check("chain verifies after restore", re_verify)

        # ---------------- CONSENT REVOCATION ----------------
        section("Consent revocation")

        def revoke():
            j = c.post("/api/consent/revoke", json={
                "patient_id": state["pid"], "reason": "patient_request",
            }).get_json()
            assert j["ok"] is True, j
            assert j["shredded"] is True, j
            assert j["event_signature"], j
        check("POST /api/consent/revoke shreds PII key", revoke)

        def revoked_chain_still_verifies():
            j = c.get(f"/api/audit/verify/{state['pid']}").get_json()
            assert j["ok"] is True, j
            assert j["events"] == 7, j["events"]
        check("chain still verifies after revocation (7 events)", revoked_chain_still_verifies)

        def no_send_after_revoke():
            j = c.post("/api/notifications/send", json={
                "patient_id": state["pid"],
                "template_id": "referral_created",
                "context": {"facility": "HOSP-A", "urgency": "urgent"},
            }).get_json()
            assert j["ok"] is False, j
            assert j["status"] == "skipped", j
        check("send skipped after consent revoked", no_send_after_revoke)

        # ---------------- FAILURE HANDLING ----------------
        section("Failure handling")

        def screen2():
            j = c.post("/api/screening", json={
                "patient": {"age_band": "50-59", "insurance_type": "self_pay",
                            "nhia_number": None, "phone": "+2348099990002"},
                "consent": {"version": "1.0", "scope": ["screening", "referral"]},
                "screening": {"pharmacy_id": "PHARM-A", "systolic": 165, "diastolic": 100,
                              "symptoms": [], "protocol_version": "HTN-PROTOCOL-v1"},
                "actor_id": "pharmacy@onecare.demo",
            }).get_json()
            assert "patient_id" in j, j
            state["pid2"] = j["patient_id"]
            state["sid2"] = j["screening"]["id"]
        check("screen self-pay patient", screen2)

        def refer2():
            j = c.post("/api/referral", json={
                "screening_id": state["sid2"], "facility_id": "HOSP-A",
            }).get_json()
            assert j["eligibility"]["decision"] == "not_covered", j
            state["rid2"] = j["referral_id"]
        check("self-pay → not_covered", refer2)

        def decline():
            j = c.post(f"/api/referrals/{state['rid2']}/decline", json={
                "actor_id": "hospital@onecare.demo", "reason_code": "no_slots",
                "owner": "care_navigator", "next_facility_id": "HOSP-B",
            }).get_json()
            assert j["decline_event"]["event_type"] == "REFERRAL_DECLINED", j
            assert j["redirected_to"] == "HOSP-B", j
            assert j["redirect_event"]["event_type"] == "REFERRAL_CREATED", j
        check("decline + auto-redirect to HOSP-B", decline)

        def invalid_transition():
            r = c.post(f"/api/referrals/{state['rid2']}/attest",
                       json={"actor_id": "hospital@onecare.demo",
                             "clinician_id": "doc@onecare.demo"})
            assert r.status_code == 400, r.status_code
            assert r.get_json()["error"] == "invalid_transition", r.get_json()
        check("attest before book → invalid_transition", invalid_transition)

        # ---------------- METRICS ----------------
        section("Metrics")

        def metrics():
            j = c.get("/api/metrics").get_json()
            assert j["total_patients"] >= 2, j
            assert j["closed_loops"] >= 1, j
            assert j["failure_breakdown"].get("REFERRAL_DECLINED", 0) >= 1, j
        check("metrics: patients, closures, failure breakdown", metrics)

    # ---------------- SUMMARY ----------------
    passed = sum(1 for r in results if r[0] == PASS)
    failed = sum(1 for r in results if r[0] == FAIL)
    total = len(results)

    print(f"\n{'='*60}")
    if failed:
        print(f"  {passed}/{total} passed  ·  {failed} FAILED")
    else:
        print(f"  {passed}/{total} passed  ·  ALL GREEN")
    print(f"{'='*60}\n")

    if failed:
        print("Failures:")
        for status, name, err in results:
            if status == FAIL:
                print(f"  {FAIL} {name}\n    {err}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())