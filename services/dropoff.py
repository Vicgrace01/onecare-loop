"""
OneCare Loop — services/dropoff.py

Logistic regression for referral drop-off risk.
Trained at first use on 2,000 synthetic journeys. Coefficients cached in
model_versions. Retraining is a POST to /api/dropoff/train.

Deliberately interpretable: 7 features, no hidden layers, no embeddings.

The output is P(drop-off): the probability the referral will FAIL to close.
Higher = more likely to drop off. This matches the field name `dropoff_score`
and the model card's stated purpose.
"""

from __future__ import annotations

import json
import math
import random
import uuid
from datetime import datetime

from models import connect_db
from services.ledger import utc_now


FEATURES = [
    "is_self_pay",
    "urgency_emergency",
    "urgency_urgent",
    "severity_systolic",
    "severity_diastolic",
    "is_weekend",
    "is_repeat_pharmacy",
]

MODEL_TYPE = "dropoff_lr"
MODEL_VERSION = "1.1"  # bumped when label flipped from closure → drop-off
TRAIN_SEED = 20251115
TRAIN_SAMPLES = 2000
TRAIN_EPOCHS = 40
TRAIN_LR = 0.3
TRAIN_L2 = 0.001

_MODEL_CACHE: dict = {}


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _generate_synthetic(n: int = TRAIN_SAMPLES, seed: int = TRAIN_SEED):
    rng = random.Random(seed)
    samples = []
    for _ in range(n):
        systolic = rng.choice([135, 145, 155, 165, 175, 185, 195, 205])
        diastolic = rng.choice([85, 95, 100, 105, 110, 115, 120, 125])
        insurance = rng.choices(["nhia", "self_pay", "donor"], weights=[38, 52, 10])[0]
        urgency = rng.choices(["routine", "urgent", "emergency"], weights=[60, 30, 10])[0]
        weekday = rng.randint(0, 6)
        is_repeat = rng.random() < 0.25

        risk = 0.0
        if insurance == "self_pay":
            risk += 0.9
        if urgency == "emergency":
            risk += 0.4
        elif urgency == "urgent":
            risk += 0.15
        risk += max(0.0, (systolic - 140) / 60.0) * 0.5
        risk += max(0.0, (diastolic - 90) / 30.0) * 0.3
        if weekday >= 5:
            risk += 0.3
        if is_repeat:
            risk -= 0.4
        risk += rng.gauss(0, 0.5)

        dropped = 1 if risk >= 1.5 else 0
        features = [
            1.0 if insurance == "self_pay" else 0.0,
            1.0 if urgency == "emergency" else 0.0,
            1.0 if urgency == "urgent" else 0.0,
            max(0.0, (systolic - 140) / 60.0),
            max(0.0, (diastolic - 90) / 30.0),
            1.0 if weekday >= 5 else 0.0,
            1.0 if is_repeat else 0.0,
        ]
        samples.append((features, dropped))
    return samples


def _train_lr(samples, epochs=TRAIN_EPOCHS, lr=TRAIN_LR, l2=TRAIN_L2):
    n_features = len(samples[0][0]) + 1
    weights = [0.0] * n_features
    n = len(samples)
    for _ in range(epochs):
        grads = [0.0] * n_features
        for features, label in samples:
            x = features + [1.0]
            z = sum(w * xi for w, xi in zip(weights, x))
            p = _sigmoid(z)
            err = p - label
            for i in range(n_features):
                grads[i] += err * x[i]
        for i in range(n_features):
            weights[i] -= lr * (grads[i] / n + l2 * weights[i])
    return weights


def ensure_model() -> dict:
    if "model" in _MODEL_CACHE:
        return _MODEL_CACHE["model"]

    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT weights_json FROM model_versions "
            "WHERE model_type = ? AND version = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (MODEL_TYPE, MODEL_VERSION),
        ).fetchone()
        if row:
            model = json.loads(row["weights_json"])
            _MODEL_CACHE["model"] = model
            return model

        samples = _generate_synthetic()
        weights = _train_lr(samples)
        model = {
            "weights": weights[:-1],
            "intercept": weights[-1],
            "features": FEATURES,
            "trained_on": len(samples),
            "seed": TRAIN_SEED,
            "epochs": TRAIN_EPOCHS,
            "label": "P(drop_off)",
            "version": MODEL_VERSION,
            "trained_at": utc_now(),
        }
        conn.execute(
            "INSERT OR IGNORE INTO model_versions "
            "(id, model_type, version, weights_json, trained_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), MODEL_TYPE, MODEL_VERSION,
                json.dumps(model), model["trained_at"], utc_now(),
            ),
        )
        row = conn.execute(
            "SELECT weights_json FROM model_versions "
            "WHERE model_type = ? AND version = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (MODEL_TYPE, MODEL_VERSION),
        ).fetchone()
        model = json.loads(row["weights_json"])
        _MODEL_CACHE["model"] = model
        return model
    finally:
        conn.close()


def _score_raw(features: list[float]) -> dict:
    model = ensure_model()
    x = features + [1.0]
    w = model["weights"] + [model["intercept"]]
    z = sum(wi * xi for wi, xi in zip(w, x))
    p = _sigmoid(z)
    # p = P(drop_off)
    if p > 0.6:
        tier = "high"
    elif p > 0.3:
        tier = "medium"
    else:
        tier = "low"
    return {"probability": round(p, 4), "tier": tier, "raw_z": round(z, 4)}


def _gather_features(referral_id: str) -> list[float] | None:
    conn = connect_db()
    try:
        row = conn.execute(
            """
            SELECT r.urgency, r.created_at, s.patient_id, s.pharmacy_id,
                   s.systolic, s.diastolic, p.insurance_type
            FROM referrals r
            JOIN screenings s ON s.id = r.screening_id
            JOIN patients p ON p.id = s.patient_id
            WHERE r.id = ?
            """,
            (referral_id,),
        ).fetchone()
        if not row:
            return None
        prior = conn.execute(
            "SELECT COUNT(*) AS n FROM screenings WHERE patient_id = ? AND pharmacy_id = ? AND created_at < ?",
            (row["patient_id"], row["pharmacy_id"], row["created_at"]),
        ).fetchone()["n"]
    finally:
        conn.close()

    weekday = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")).weekday()
    return [
        1.0 if row["insurance_type"] == "self_pay" else 0.0,
        1.0 if row["urgency"] == "emergency" else 0.0,
        1.0 if row["urgency"] == "urgent" else 0.0,
        max(0.0, (row["systolic"] - 140) / 60.0),
        max(0.0, (row["diastolic"] - 90) / 30.0),
        1.0 if weekday >= 5 else 0.0,
        1.0 if prior > 0 else 0.0,
    ]


def score_referral(referral_id: str) -> dict:
    features = _gather_features(referral_id)
    if features is None:
        return {"ok": False, "error": "not_found", "referral_id": referral_id}
    result = _score_raw(features)
    result["ok"] = True
    result["referral_id"] = referral_id
    result["features"] = dict(zip(FEATURES, features))
    return result


def model_summary() -> dict:
    model = ensure_model()
    return {
        "model_type": MODEL_TYPE,
        "version": MODEL_VERSION,
        "label": "P(drop_off)",
        "features": model["features"],
        "weights": dict(zip(model["features"], model["weights"])),
        "intercept": model["intercept"],
        "trained_on": model["trained_on"],
        "seed": model["seed"],
        "epochs": model["epochs"],
        "trained_at": model["trained_at"],
        "tier_thresholds": {"low": 0.0, "medium": 0.3, "high": 0.6},
        "honest_note": (
            "Trained on 2,000 synthetically generated journeys. Not trained on real patient data. "
            "Output is P(drop-off): the probability a referral will fail to close. "
            "This score is a prioritisation hint for a care navigator; it never gates a state transition."
        ),
    }


def retrain() -> dict:
    _MODEL_CACHE.pop("model", None)
    conn = connect_db()
    try:
        conn.execute("DELETE FROM model_versions WHERE model_type = ?", (MODEL_TYPE,))
    finally:
        conn.close()
    return model_summary()