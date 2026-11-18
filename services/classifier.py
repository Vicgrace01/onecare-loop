"""
OneCare Loop — services/classifier.py

Patient reply classifier.
Path 1: Groq LLM (if GROQ_API_KEY is set) — constrained to 4 classes + unknown.
Path 2: deterministic keyword matching per language — always available.

Classes: yes, no, reschedule, stop, unknown.
The classifier never sends anything; it only classifies.
"""

from __future__ import annotations

import json
import os
import re


CLASSES = ["yes", "no", "reschedule", "stop", "unknown"]

KEYWORDS = {
    "en": {
        "yes": ["yes", "yeah", "yep", "ok", "okay", "sure", "fine", "will", "i can", "i will"],
        "no": ["no", "nope", "cannot", "can't", "wont", "won't", "not going", "decline"],
        "reschedule": ["reschedule", "another time", "later", "different day", "change time", "postpone"],
        "stop": ["stop", "unsubscribe", "opt out", "quit", "do not message"],
    },
    "pcm": {
        "yes": ["yes", "i go", "i go come", "ok", "okay", "na fine"],
        "no": ["no", "i no go", "i no fit", "no be"],
        "reschedule": ["reschedule", "anoda time", "shift am", "anoda day"],
        "stop": ["stop", "no send me message", "comot"],
    },
    "ig": {
        "yes": ["ee", "yes", "ọ dị mma", "m ga-abịa", "m na-ekweta"],
        "no": ["mba", "no", "agaghị m", "enweghị m ike"],
        "reschedule": ["reschedule", "oge ọzọ", "ụbọchị ọzọ"],
        "stop": ["kwụsị", "stop", "ezipụla"],
    },
    "ha": {
        "yes": ["eh", "yes", "zan zo", "na yarda"],
        "no": ["a'a", "no", "ba zan zo ba", "ba zan iya ba"],
        "reschedule": ["sake tsarawa", "wani lokaci", "wata rana"],
        "stop": ["tsaya", "stop", "kada ka aika"],
    },
    "yo": {
        "yes": ["bẹ́ẹ̀ ni", "yes", "mo gbà", "èmi yóò wá"],
        "no": ["rárá", "no", "mi ò ní wá", "mi ò lè"],
        "reschedule": ["àtúnṣe àkókò", "àkókò mìíràn", "ọjọ́ mìíràn"],
        "stop": ["dúró", "stop", "má ṣe fi ránṣẹ́"],
    },
}


def _keyword_classify(text: str, language: str) -> dict:
    lang = language if language in KEYWORDS else "en"
    low = text.lower()
    scores = {c: 0 for c in CLASSES if c != "unknown"}
    for cls, kws in KEYWORDS[lang].items():
        for kw in kws:
            if re.search(r"\b" + re.escape(kw) + r"\b", low):
                scores[cls] += 1
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return {"class": "unknown", "confidence": 0.0, "method": "keyword", "language": lang}
    total = sum(scores.values()) or 1
    return {
        "class": best,
        "confidence": round(scores[best] / total, 3),
        "method": "keyword",
        "language": lang,
    }


def _groq_classify(text: str, language: str) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    import requests as _requests

    prompt = (
        f"Classify this patient reply into exactly one of: yes, no, reschedule, stop. "
        f"The reply is in {language}. If none fit, respond 'unknown'. "
        f"Reply with only the class word, lowercase.\n\nReply: {text}"
    )
    resp = _requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "llama-3.1-8b-instant",
            "messages": [
                {"role": "system", "content": "You output single lowercase class labels only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 8,
        },
        timeout=6,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip().lower()
    cls = content if content in CLASSES else "unknown"
    return {"class": cls, "confidence": 1.0 if cls != "unknown" else 0.0,
            "method": "groq", "language": language}


def classify(text: str, language: str = "en") -> dict:
    """Primary: Groq. Fallback: keyword. Always returns a valid class."""
    groq_result = None
    try:
        groq_result = _groq_classify(text, language)
    except Exception:
        groq_result = None

    kw_result = _keyword_classify(text, language)

    if groq_result is None:
        return kw_result

    if groq_result["class"] == kw_result["class"]:
        return {**groq_result, "agreement": True}

    # Disagreement: prefer keyword (deterministic) and record the divergence
    return {
        **kw_result,
        "method": "keyword_override",
        "groq_disagreement": groq_result["class"],
        "agreement": False,
    }