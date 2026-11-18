"""
OneCare Loop — services/companion.py

The patient's plain-language companion.

Grounds every message in the actual ledger state of that patient — no
hallucination, no invented facts. Reads chain, reads referral, reads
appointment, and produces:
  - what just happened (in the patient's words)
  - what is happening now
  - exactly one suggested next action
  - who to call if the loop stalls

Rule-based today. LLM-assisted phrasing is on the roadmap; when it lands
it will still be constrained to these states and these actors. The
companion will never invent a clinical fact.
"""

from __future__ import annotations

from datetime import datetime

from models import connect_db
from services.ledger import get_current_state


STATE_GUIDES: dict[str, dict] = {
    "NONE": {
        "headline": "Your care journey starts at a pharmacy",
        "story": "You haven't been screened yet. A pharmacist can check your blood pressure in about 60 seconds — no appointment needed.",
        "action": "Find a partner pharmacy near you",
        "action_type": "find_pharmacy",
        "help": "If you already gave your phone to a pharmacy and don't see any events, ask them to enter it again.",
    },
    "SCREEN_POSITIVE": {
        "headline": "Your blood pressure was checked",
        "story": "A pharmacist recorded your blood pressure. Based on that reading, they've begun a referral to a clinic where a clinician can review you.",
        "action": "Nothing yet — we're creating your referral",
        "action_type": "wait",
        "help": "If you don't hear back today, contact the pharmacy where you were screened.",
    },
    "REFERRAL_CREATED": {
        "headline": "We've sent your referral to a clinic",
        "story": "A clinic has been notified. They will respond within 24 hours. You'll receive an SMS the moment they accept.",
        "action": "Wait for the clinic to respond",
        "action_type": "wait",
        "help": "If no response after 24 hours, we auto-redirect you to another clinic. No action needed from you.",
    },
    "FACILITY_ACCEPTED": {
        "headline": "A clinic accepted your referral",
        "story": "The clinic has agreed to see you. They are now assigning a date and time for your appointment.",
        "action": "Wait for your appointment slot",
        "action_type": "wait",
        "help": "Your appointment details will arrive by SMS shortly.",
    },
    "APPOINTMENT_BOOKED": {
        "headline": "Your appointment is booked",
        "story": "Your visit is scheduled. Please arrive 15 minutes early with any existing medications or BP records you have.",
        "action": "Note the date and location",
        "action_type": "view_appointment",
        "help": "If you can't make it, reply RESCHEDULE to the SMS or contact us here.",
    },
    "CLINICAL_ENCOUNTER_COMPLETED": {
        "headline": "You were seen by a clinician",
        "story": "The clinician has recorded your visit. They are now preparing your outcome and next steps — this usually takes minutes.",
        "action": "Wait for your result",
        "action_type": "wait",
        "help": "Your outcome will appear here as soon as the clinician submits it.",
    },
    "CLINICAL_DISPOSITION_RETURNED": {
        "headline": "Your loop has closed",
        "story": "Your full care journey is complete — from screening through treatment. Your receipt below is now a permanently verifiable record.",
        "action": "Check your next follow-up date",
        "action_type": "view_followup",
        "help": "Need a copy for your own records? Tap 'Copy receipt link' below.",
    },
    "REFERRAL_DECLINED": {
        "headline": "The clinic couldn't take this referral",
        "story": "The clinic declined for a specific reason. Your referral is being re-routed to another clinic automatically.",
        "action": "Nothing yet — we're re-routing you",
        "action_type": "wait",
        "help": "If this happens more than once, call our team — we'll find you a clinic directly.",
    },
    "FACILITY_UNAVAILABLE": {
        "headline": "The clinic is temporarily unavailable",
        "story": "This clinic has no slots available right now. We're searching for an alternative.",
        "action": "Wait for us to find another clinic",
        "action_type": "wait",
        "help": "This is on our side — you don't need to do anything.",
    },
    "APPOINTMENT_MISSED": {
        "headline": "An appointment was missed",
        "story": "The appointment did not happen. The clinic is ready to re-book you — just let us know.",
        "action": "Reply YES to re-book",
        "action_type": "reschedule",
        "help": "Reply to your SMS with a new date that works, or tap here to contact us.",
    },
    "PATIENT_UNREACHABLE": {
        "headline": "We couldn't reach you",
        "story": "We tried calling or messaging and couldn't get through. Please confirm your phone number is correct.",
        "action": "Confirm your contact details",
        "action_type": "contact",
        "help": "If your number changed, tell the pharmacy on your next visit.",
    },
    "PATIENT_DECLINED": {
        "headline": "You chose not to continue",
        "story": "You've opted out of the referral or treatment. We respect that. You can restart at any pharmacy whenever you're ready.",
        "action": "Restart when you're ready",
        "action_type": "find_pharmacy",
        "help": "Your care journey is yours. No one will pressure you.",
    },
    "PATIENT_REQUESTED_RESCHEDULE": {
        "headline": "You asked to reschedule",
        "story": "We've noted the request. The clinic will propose a new slot shortly.",
        "action": "Wait for the new slot",
        "action_type": "wait",
        "help": "If you don't hear back within a day, reply to any of our messages.",
    },
    "REFERRAL_REDIRECTED": {
        "headline": "Your referral moved to another clinic",
        "story": "The first clinic couldn't take you, so your referral has automatically moved to a second one. You don't need to re-do anything.",
        "action": "Wait for the new clinic to accept",
        "action_type": "wait",
        "help": "This is usually faster than starting over. You'll get a new SMS.",
    },
    "FOLLOWUP_OVERDUE": {
        "headline": "Your follow-up is overdue",
        "story": "You were due for a follow-up visit. Please let us know how you're doing.",
        "action": "Reply YES to book a follow-up",
        "action_type": "reschedule",
        "help": "Staying on top of follow-ups is how BP stays controlled. We'll make it easy.",
    },
    "FOLLOWUP_DUE": {
        "headline": "A follow-up is due",
        "story": "Time for your next blood pressure check. It's short — usually under 5 minutes.",
        "action": "Book your follow-up",
        "action_type": "reschedule",
        "help": "Any partner pharmacy can do a follow-up check.",
    },
    "REPEAT_ASSESSMENT": {
        "headline": "Your BP was checked again",
        "story": "Good job coming back. Your numbers have been recorded and are being reviewed against your earlier reading.",
        "action": "Nothing yet",
        "action_type": "wait",
        "help": "Keep taking your medication as prescribed.",
    },
    "BP_CONTROL_RECORDED": {
        "headline": "Your BP control was recorded",
        "story": "Your latest reading shows how well your BP is controlled. Your clinician will adjust the plan if needed.",
        "action": "Wait for your next step",
        "action_type": "wait",
        "help": "If your numbers haven't improved, don't skip the next follow-up.",
    },
    "CONSENT_REVOKED": {
        "headline": "Your consent was revoked",
        "story": "Your personal details have been removed. The chain of events remains, but without any information that can identify you.",
        "action": "Contact us to restart",
        "action_type": "contact",
        "help": "You can consent again at any pharmacy.",
    },
}


def _get_display_name(patient_id: str) -> str | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT display_name FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
    finally:
        conn.close()
    return row["display_name"] if row and row["display_name"] else None


def _get_facility(patient_id: str) -> str | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT facility_id FROM referrals WHERE screening_id IN "
            "(SELECT id FROM screenings WHERE patient_id = ?) "
            "ORDER BY created_at DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["facility_id"] if row else None


def _get_appointment(patient_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT a.slot_start, a.slot_end FROM appointments a "
            "JOIN referrals r ON r.id = a.referral_id "
            "JOIN screenings s ON s.id = r.screening_id "
            "WHERE s.patient_id = ? "
            "ORDER BY a.created_at DESC LIMIT 1",
            (patient_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _get_next_followup(patient_id: str) -> dict | None:
    conn = connect_db()
    try:
        row = conn.execute(
            "SELECT due_date, type FROM follow_up_plans "
            "WHERE patient_id = ? AND status = 'pending' "
            "ORDER BY due_date ASC LIMIT 1",
            (patient_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def _friendly_date(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%a %d %b · %H:%M")
    except Exception:
        return iso


def build_patient_home(patient_id: str) -> dict:
    """Everything the patient home page needs, in one call."""
    state = get_current_state(patient_id) or "NONE"
    guide = dict(STATE_GUIDES.get(state, STATE_GUIDES["NONE"]))
    guide["state"] = state

    name = _get_display_name(patient_id)
    facility = _get_facility(patient_id)
    appointment = _get_appointment(patient_id)
    followup = _get_next_followup(patient_id)

    story = guide["story"]
    if facility:
        story = story.replace("{facility}", facility)
    else:
        story = story.replace("{facility}", "your clinic")
    guide["story"] = story

    action_extra = None
    if state == "APPOINTMENT_BOOKED" and appointment:
        action_extra = f"{_friendly_date(appointment['slot_start'])} · {facility or 'the clinic'}"
    elif state == "CLINICAL_DISPOSITION_RETURNED" and followup:
        action_extra = f"Next follow-up: {_friendly_date(followup['due_date'])}"

    return {
        "ok": True,
        "patient_id": patient_id,
        "display_name": name,
        "greeting": f"Welcome, {name}" if name else "Welcome back",
        "current_state": state,
        "headline": guide["headline"],
        "story": guide["story"],
        "action": guide["action"],
        "action_type": guide["action_type"],
        "action_extra": action_extra,
        "help": guide["help"],
        "facility": facility,
        "appointment": appointment,
        "next_followup": followup,
        "source": "rule-based companion · grounded in ledger state",
        "honest_note": (
            "This guide reads only the recorded events of this patient's care journey. "
            "It never diagnoses, never prescribes, and never invents a step that isn't "
            "already in the chain."
        ),
    }