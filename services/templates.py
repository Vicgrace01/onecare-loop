"""
OneCare Loop — services/templates.py

Multilingual patient message templates.

Honest flag: every non-English template carries needs_native_review=True.
We wrote these ourselves as best-effort approximations. Before any pilot, a
native speaker of each language must review every template. This is documented
in the model card and in the pilot plan.
"""

from __future__ import annotations


LANGUAGES = ["en", "pcm", "ig", "ha", "yo"]

LANGUAGE_NAMES = {
    "en": "English",
    "pcm": "Nigerian Pidgin",
    "ig": "Igbo",
    "ha": "Hausa",
    "yo": "Yorùbá",
}


TEMPLATES: dict[str, dict] = {
    "screening_positive": {
        "en": {
            "text": "Hello. Your blood pressure reading is high ({systolic}/{diastolic} mmHg). OneCare Loop has referred you to {facility} for a clinical review. Reply YES to confirm, NO to decline.",
            "needs_native_review": False,
        },
        "pcm": {
            "text": "How you dey. Your BP high ({systolic}/{diastolic} mmHg). We don send your file go {facility} so doctor go see you. Reply YES if you wan go, NO if you no wan go.",
            "needs_native_review": True,
        },
        "ig": {
            "text": "Ndewo. Ọbara gị dị elu ({systolic}/{diastolic} mmHg). Anyị zigara gị na {facility} ka dọkịta hụ gị. Zaa YES ma ị chọrọ ịga, NO ma ị chọghị.",
            "needs_native_review": True,
        },
        "ha": {
            "text": "Sannu. Hawan jininsa ya yi tsanani ({systolic}/{diastolic} mmHg). Mun tura ka zuwa {facility} domin likita ya gan ka. Amsa YES idan kana so ka je, NO idan ba ka so.",
            "needs_native_review": True,
        },
        "yo": {
            "text": "Ẹ káàsán. Ẹ̀jẹ̀ rẹ ga ({systolic}/{diastolic} mmHg). A ti fi ọ́ ránṣẹ́ sí {facility} kí dókítà lè wò ó. Dáhùn YES bí o bá fẹ́ lọ, NO bí o kò fẹ́.",
            "needs_native_review": True,
        },
    },
    "referral_created": {
        "en": {
            "text": "Your referral to {facility} has been created. Urgency: {urgency}. Reply YES if you can attend, or RESCHEDULE if the timing does not work.",
            "needs_native_review": False,
        },
        "pcm": {
            "text": "We don create your referral go {facility}. Urgency na {urgency}. Reply YES if you fit go, or RESCHEDULE if time no work for you.",
            "needs_native_review": True,
        },
        "ig": {
            "text": "E mepụtala referral gị gaa {facility}. Ngwa ngwa: {urgency}. Zaa YES ma ị nwere ike ịga, ma ọ bụ RESCHEDULE ma oge adịghị mma.",
            "needs_native_review": True,
        },
        "ha": {
            "text": "An ƙirƙiri tura ka zuwa {facility}. Gaggawa: {urgency}. Amsa YES idan za ka iya zuwa, ko RESCHEDULE idan lokacin bai dace ba.",
            "needs_native_review": True,
        },
        "yo": {
            "text": "A ti ṣẹ̀dá ìránṣẹ́ rẹ sí {facility}. Kánjú: {urgency}. Dáhùn YES bí o lè wá, tàbí RESCHEDULE bí àkókò kò bá yá.",
            "needs_native_review": True,
        },
    },
    "appointment_booked": {
        "en": {
            "text": "Your appointment at {facility} is booked for {slot_start}. Please arrive 15 minutes early. Reply STOP to opt out of reminders.",
            "needs_native_review": False,
        },
        "pcm": {
            "text": "Your appointment for {facility} don book for {slot_start}. Come 15 minutes before. Reply STOP if you no wan reminder again.",
            "needs_native_review": True,
        },
        "ig": {
            "text": "E debanyere oge ọmụmụ gị na {facility} maka {slot_start}. Bịa nkeji iri na ise tupu oge. Zaa STOP ma ị chọghị ncheta ọzọ.",
            "needs_native_review": True,
        },
        "ha": {
            "text": "An tsara alƙawarinka a {facility} don {slot_start}. Zo minti 15 kafin lokaci. Amsa STOP idan ba ka son ƙarin tunatarwa.",
            "needs_native_review": True,
        },
        "yo": {
            "text": "A ti ṣètò ìpàdé rẹ ní {facility} fún {slot_start}. Wá ní ìṣẹ́jú mẹ́ẹ̀ẹ́dógún ṣáájú àkókò. Dáhùn STOP bí o kò fẹ́ ìránnilétí mìíràn.",
            "needs_native_review": True,
        },
    },
    "counter_referral": {
        "en": {
            "text": "Your care loop is closed. Outcome: {outcome}. Next step: {next_step}. Reply YES if you understand.",
            "needs_native_review": False,
        },
        "pcm": {
            "text": "Your care loop don close. Result: {outcome}. Next thing: {next_step}. Reply YES if you understand.",
            "needs_native_review": True,
        },
        "ig": {
            "text": "Emechiela usoro nlekọta gị. Nsonaazụ: {outcome}. Nzọụkwụ ọzọ: {next_step}. Zaa YES ma ị ghọtara.",
            "needs_native_review": True,
        },
        "ha": {
            "text": "An rufe tsarin kulawarka. Sakamako: {outcome}. Mataki na gaba: {next_step}. Amsa YES idan ka fahimta.",
            "needs_native_review": True,
        },
        "yo": {
            "text": "A ti pa ìgbésẹ̀ ìtọ́jú rẹ dé. Èsì: {outcome}. Ìgbésẹ̀ tó kàn: {next_step}. Dáhùn YES bí o bá yé ọ.",
            "needs_native_review": True,
        },
    },
    "consent_request": {
        "en": {
            "text": "OneCare Loop would like to record your screening, referral, and treatment. Reply YES to consent, NO to decline. You can withdraw consent at any time.",
            "needs_native_review": False,
        },
        "pcm": {
            "text": "OneCare Loop wan record your screening, referral, and treatment. Reply YES if you agree, NO if you no agree. You fit change your mind anytime.",
            "needs_native_review": True,
        },
        "ig": {
            "text": "OneCare Loop chọrọ idekọ nyocha, referral na ọgwụgwọ gị. Zaa YES ma ị kwekọrọ, NO ma ị kwekọghị. Ị nwere ike ịgbanwe uche gị oge ọ bụla.",
            "needs_native_review": True,
        },
        "ha": {
            "text": "OneCare Loop na son yin rikodin bincikenka, turawa, da jiyyarka. Amsa YES idan ka yarda, NO idan ba ka yarda ba. Kana iya canza ra'ayinka kowane lokaci.",
            "needs_native_review": True,
        },
        "yo": {
            "text": "OneCare Loop fẹ́ kọ àkọsílẹ̀ àyẹ̀wò, ìránṣẹ́, àti ìtọ́jú rẹ. Dáhùn YES bí o bá gbà, NO bí o kò gbà. O lè yí èrò rẹ padà ní àkókòkókò.",
            "needs_native_review": True,
        },
    },
}


class TemplateNotFound(Exception):
    pass


def render(template_id: str, language: str, context: dict) -> dict:
    if template_id not in TEMPLATES:
        raise TemplateNotFound(f"template {template_id} not found")
    lang = language if language in LANGUAGES else "en"
    entry = TEMPLATES[template_id][lang]
    text = entry["text"]
    try:
        body = text.format(**context)
    except KeyError as e:
        body = text  # leave placeholders intact rather than fail the send
    return {
        "template_id": template_id,
        "language": lang,
        "text": body,
        "needs_native_review": entry["needs_native_review"],
    }


def list_templates() -> dict:
    out = {}
    for tid, langs in TEMPLATES.items():
        out[tid] = {
            "languages": list(langs.keys()),
            "needs_native_review": [l for l, v in langs.items() if v.get("needs_native_review")],
        }
    return out