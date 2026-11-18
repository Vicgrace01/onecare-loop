# OneCare Loop

**A referral cannot quietly disappear between the pharmacy, hospital, clinician, patient and payer.**

OneCare Loop is a last-mile referral operating system for Nigerian hypertension care. It records every transition in a patient's care journey as an immutable, signed, hash-chained event — so the loop can be proven to have closed, or proven to have broken, at every step.

Built for the **Future Health — Digital Innovation Challenge** (Abu Dhabi, 2026).
Population Health track · Challenge 05: *Closing the Screening-to-Care Loop.*

---

## The problem in numbers

**WHO Global Report on Hypertension, 2025 — Nigeria, adults 30–79:**

| | |
|---|---|
| Living with hypertension | 22 million |
| Diagnosed | 11 million (50%) |
| On treatment | 7 million (32%) |
| **BP controlled** | **2.9 million (13%)** |

The bottleneck is not awareness. It is completion. A patient can be screened at a pharmacy, referred to a clinic, and still disappear between the two. Nobody owns the hand-off. Nobody can prove the outcome.

---

## What OneCare Loop does

1. **Screening** at a licensed pharmacy (or PMV under protocol) records a BP reading as the first event in the chain.
2. **Referral** fires a signed referral, an eligibility check (simulated against real FHIR R4 schema), and an SMS to the patient.
3. **Hospital queue** — accept, book, attest, counter-refer. Each is a signed transition. Every actor is on record.
4. **Patient portal** — the patient sees every event in their own journey, verified, in WhatsApp-style plain language, in 5 Nigerian languages.
5. **Payer dashboard** — closure rate, time-to-care, failure breakdown, value recovered. Not referral tracking. Proof that care happened.

Every event is **Ed25519-signed by the acting party**. Every event is **chained to the previous one with SHA-256**. A single byte changed anywhere in the chain breaks verification at that exact event.

---

## Try it in 30 seconds

Three paths, all one click:

| Path | URL | What you see |
|---|---|---|
| **Instant anonymous proof** | `/proof` | A closed 6-event care loop with green verification — no login needed |
| **Full patient experience** | `/patient/login` → pick a patient card | The companion card, the receipt, the chain |
| **Staff dashboard** | `/login` → `admin@onecare.demo` / `demo1234` | Dashboard, referral queue, analytics, ROI calculator |

The demo database pre-seeds **10 patients** across every workflow state — closed loops, mid-referral, declined, unreachable — so nothing looks empty when you land. The cohort regenerates on every fresh startup.

---

## What's built (the honest ledger)

### Built and tested

- 6-state canonical loop (screen → disposition)
- 8 named failure states (declined, missed, unreachable, etc.)
- Longitudinal follow-up (30-day BP review → BP-control)
- Hash-chained event ledger, per patient
- Ed25519 per-actor signing on every event
- Chain + signature verification endpoints
- Tamper test — mutate one event, watch the chain break visibly
- Crypto-shredding for NDPA erasure (consent revocation)
- Consent version log (append-only, hashed)
- Drop-off risk score (logistic regression on synthetic data)
- FHIR R4 Bundle export (7 resource types)
- Patient receipt (WhatsApp-style, public, verifiable, 5 languages)
- Access logs (who read which patient record)
- Population dashboard (closure rate, time-to-care, failure breakdown)
- Interactive ROI calculator
- Model card, datasheet, DPIA, NDPA checklist, threat model, pilot plan

### Simulated — clearly labeled in product

| Feature | Status | Honest note |
|---|---|---|
| DHIN FHIR eligibility check | Real FHIR schema, mock response | Not wired to a live DHIN endpoint. Response generated locally from NHIA number presence. |
| SMS / WhatsApp delivery | Envelope written to `notifications` table | Twilio-shaped SID returned. **No external call.** Sandbox integration in the roadmap. |
| Reply classification | Groq LLM if key is set, otherwise keyword matching | Both paths tested. Disagreements recorded, never silently resolved. |
| Red flag emergency alert | Alert written to `loop_exceptions` | **No ambulance dispatched.** No emergency coordinator paged. This is a log, not an incident. |
| Money recovered | ₦6,000 per closed loop | Placeholder. The pilot plan requires a real negotiated value from the payer before these numbers go into a pitch deck. |

### Coming soon — documented, not shipped

Live DHIN API · Multi-disease config (hypertension only for pilot) · Ambulance dispatch · Live claims submission · USSD fallback · Voice-note instructions · External timestamp anchoring (OpenTimestamps) · Per-actor device-held keys · Public provider reputation · Care navigator assignment UI · Marketplace / bidding · Rate limiting beyond Render's default · MFA on hospital accounts.

---

## Quick start

Requires **Python 3.11+**.

```bash
git clone <this-repo>
cd onecare-loop
python -m venv .venv
.venv\Scripts\Activate.ps1       # Windows
# source .venv/bin/activate      # macOS / Linux
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. The demo cohort seeds on first startup (~3 seconds).

**Two validation commands:**

```bash
python -m pytest tests/ -q       # unit tests
python smoke_test.py             # 63 end-to-end checks, no login required
```

The smoke test spins up a fresh app with a temporary database and walks the full product: signup → login → every page → screen → refer → accept → book → attest → counter-refer → verify chain → verify signatures → tamper → restore → revoke consent → verify chain still holds → decline with auto-redirect → confirm invalid transitions are rejected → metrics. All in about 3 seconds.

---

## Architecture

Modular monolith. Single Flask app. No microservices.

```
 Pharmacy / PMV        Hospital           Patient           Payer
        │                 │                  │                │
        └─────────────────┴──────────────────┴────────────────┘
                                  │
                          Flask API (app.py)
                    ┌─────────────┴─────────────┐
                    │                           │
              services/ledger.py           services/loop.py
           (hash chain + signing)    (state machine + guards)
                    │                           │
                    └─────────────┬─────────────┘
                                  │
                            SQLite / Postgres
                       (append-only loop_events)
```

A `loop_events` row is append-only. Its hash commits to (a) its own payload, (b) its `prev_hash`, and (c) its identity fields. Its Ed25519 signature commits to that hash. `ledger_head` provides a fast per-patient tip lookup. Verification recomputes every hash and re-verifies every signature.

---

## Design decisions and their tradeoffs

**Hash-chained, not blockchain.** The chain is SHA-256, per patient, local. It is tamper-**evident**, not tamper-**proof**. Anyone with write access to the DB can rewrite the whole chain and its head. The mitigation is external anchoring (Coming Soon). We say so loudly because pretending otherwise is a lie.

**Signatures are server-held today.** Per-actor Ed25519 keys are stored in `actor_keys` on the server. A compromised server can forge signatures. Moving to device-held keys is Coming Soon. The threat model documents this — it is a meaningful improvement over no signatures at all, and not a substitute for the real thing.

**Drop-off model trained on synthetic data.** 2,000 generated journeys, seeded and reproducible. AUC 0.79 on held-out synthetic. **This is not evidence of real-world performance.** The pilot will validate.

**No clinical LLM.** The classifier classifies replies into 4 buckets. It does not compose replies. It does not touch clinical text. The model card excludes clinical content generation with the label `EXCLUDED` — we will not ship a model that hallucinates care instructions to a patient.

**No automated state transitions.** Every transition requires a human actor with a role that matches the guard. The drop-off score, the classifier, the red-flag detection — none of them move a patient through the state machine. They inform a human. The human decides.

---

## Compliance

Live at these routes:

- `/model/card` — what each ML component does, its limits, its training data
- `/model/datasheet` — composition of the synthetic dataset
- `/model/dpia` — Article 35-style assessment under NDPA 2023
- `/model/ndpa` — section-by-section compliance map
- `/model/threat-model` — STRIDE analysis including what we *don't* protect against
- `/model/consent-versions` — append-only consent log

---

## Pilot plan

8-week pilot. 5 pharmacies, 1 hospital, 1 HMO. Lagos. Hypertension only.

| Week | Milestone |
|---|---|
| 1 | Deploy + onboarding at all sites |
| 2 | First 50 referrals |
| 3 | First 10 completed loops |
| 4 | Mid-point review with HMO |
| 5 | First auto-redirect on decline |
| 6 | First longitudinal follow-up |
| 7 | First consent revocation + crypto-shred |
| 8 | Readout to HMO + hospital |

**Pre-pilot blockers** (documented at `/app/pilot-plan`): in-country hosting, external DPO review, native-speaker review of all non-English templates, Twilio live credentials, HMO policy v1.

---

## What this repo will not do

- It will not diagnose hypertension. It records screenings.
- It will not recommend treatment. It records dispositions.
- It will not replace a pharmacist, a PMV under approved protocol, or a clinician.
- It will not page an ambulance.
- It will not claim production-readiness.
- It will not call itself a blockchain.
- It will not pretend the drop-off model is validated on real data.

If you want to know what it actually does, open `/model/card`, `/model/dpia`, and `/model/threat-model`. Those pages are the contract, not this README.

---

## License

MIT. See [LICENSE](LICENSE).