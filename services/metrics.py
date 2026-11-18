"""
OneCare Loop — services/metrics.py

Dashboard metrics: closure rate, time-to-care (median), failure breakdown,
money recovered (SIMULATED), provider stats (internal only — public is COMING SOON).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from models import connect_db
from services.loop import FAILURE_STATES


CLOSURE_VALUE_KOBO = 600000  # SIMULATED — ₦6,000 per closed loop


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _hours_between(a: str, b: str) -> float:
    return (_parse(b) - _parse(a)).total_seconds() / 3600.0


def compute_metrics() -> dict[str, Any]:
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT patient_id, event_type, occurred_at FROM loop_events "
            "ORDER BY patient_id, seq"
        ).fetchall()
    finally:
        conn.close()

    by_patient: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_patient[r["patient_id"]].append(dict(r))

    total = len(by_patient)
    closed = 0
    deltas: list[float] = []
    failure_counts: dict[str, int] = defaultdict(int)

    for events in by_patient.values():
        types = [e["event_type"] for e in events]
        screen = next((e["occurred_at"] for e in events if e["event_type"] == "SCREEN_POSITIVE"), None)
        close = next((e["occurred_at"] for e in events if e["event_type"] == "CLINICAL_DISPOSITION_RETURNED"), None)

        if close:
            closed += 1
            if screen:
                deltas.append(_hours_between(screen, close))

        for t in types:
            if t in FAILURE_STATES:
                failure_counts[t] += 1

    closure_rate = (closed / total) if total else 0.0
    time_to_care_median_hours = round(statistics.median(deltas), 2) if deltas else None
    money_recovered_kobo = closed * CLOSURE_VALUE_KOBO

    return {
        "total_patients": total,
        "closed_loops": closed,
        "closure_rate": round(closure_rate, 3),
        "time_to_care_median_hours": time_to_care_median_hours,
        "failure_breakdown": dict(failure_counts),
        "money_recovered_kobo": money_recovered_kobo,
        "money_recovered_naira": money_recovered_kobo // 100,
        "closure_value_kobo": CLOSURE_VALUE_KOBO,
        "simulated": True,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def compute_provider_metrics() -> dict[str, Any]:
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT facility_id,
                   COUNT(*) AS referrals_count,
                   SUM(CASE WHEN status = 'CLINICAL_DISPOSITION_RETURNED' THEN 1 ELSE 0 END) AS closed_count,
                   SUM(CASE WHEN status = 'REFERRAL_DECLINED' THEN 1 ELSE 0 END) AS declined_count
            FROM referrals
            GROUP BY facility_id
            ORDER BY facility_id
            """
        ).fetchall()
    finally:
        conn.close()

    providers = []
    for r in rows:
        total = int(r["referrals_count"] or 0)
        closed = int(r["closed_count"] or 0)
        declined = int(r["declined_count"] or 0)
        providers.append({
            "facility_id": r["facility_id"],
            "referrals_received": total,
            "closed_loops": closed,
            "declined": declined,
            "closure_rate": round(closed / total, 3) if total else 0.0,
            "decline_rate": round(declined / total, 3) if total else 0.0,
            "public_exposure": False,
        })

    return {
        "providers": providers,
        "public_exposure_enabled": False,
        "note": "Provider reputation is BUILD (internal). Public exposure is COMING SOON.",
    }