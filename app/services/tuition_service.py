"""Explicit tuition trial actions; never registered as a model write tool."""
from datetime import datetime, timezone
import os

from app.database import tuition_repository as repository
from app.database.analysis_repository import AnalysisScopeDenied, AnalysisUnavailable, get_report_context
from app.services.conversation_delivery_lock import conversation_delivery_lock

TuitionError = repository.TuitionError


def _enabled():
    if os.getenv("TUITION_TRIALS_ENABLED", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        raise TuitionError("Trial booking is not enabled.", "tuition_disabled", 503)


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise ValueError("Invalid text length")
    return value.strip()


def require_trial_context(company_id, chatbot_id):
    _enabled()
    repository.positive(company_id)
    repository.positive(chatbot_id)
    try:
        context = get_report_context(company_id, chatbot_id)
    except AnalysisScopeDenied:
        raise TuitionError("This Bot is unavailable.", "tuition_scope_denied", 404) from None
    except AnalysisUnavailable:
        raise TuitionError("Trial booking context is unavailable.") from None
    bot = context.get("bot", {})
    published = bot.get("industry_template_published") or {}
    if (bot.get("company_id") != company_id or bot.get("id") != chatbot_id
        or published.get("template_id") != "tuition_center" or not published.get("confirmed_at")):
        raise TuitionError("This Bot has no confirmed tuition industry.", "tuition_industry_required", 403)
    return context


def _capacities(total_capacity, enrolled_seats, trial_limit):
    if any(type(value) is not int for value in (total_capacity, enrolled_seats, trial_limit)):
        raise ValueError("Capacity values must be integers")
    if not 1 <= total_capacity <= 10000 or not 0 <= enrolled_seats <= total_capacity or not 0 <= trial_limit <= total_capacity:
        raise ValueError("Invalid session capacity")
    return {"total_capacity": total_capacity, "enrolled_seats": enrolled_seats, "trial_limit": trial_limit}


def _date(value):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("Use a real ISO date with a timezone") from None
    if date.tzinfo is None or date.utcoffset() is None:
        raise ValueError("Session dates require a timezone")
    return date.astimezone(timezone.utc)


def create_course(*, company_id, chatbot_id, actor_user_id, name):
    require_trial_context(company_id, chatbot_id)
    repository.positive(actor_user_id)
    return repository.write_catalog(company_id=company_id, chatbot_id=chatbot_id,
        actor_user_id=actor_user_id, operation="course", data={"name": _text(name, 150)})


def create_class(*, company_id, chatbot_id, actor_user_id, course_id, name):
    require_trial_context(company_id, chatbot_id)
    repository.positive(actor_user_id)
    return repository.write_catalog(company_id=company_id, chatbot_id=chatbot_id, actor_user_id=actor_user_id,
        operation="class", data={"course_id": repository.uuid(course_id), "name": _text(name, 150)})


def create_session(*, company_id, chatbot_id, actor_user_id, class_id, starts_at, ends_at,
                   total_capacity, enrolled_seats=0, trial_limit):
    require_trial_context(company_id, chatbot_id)
    repository.positive(actor_user_id)
    start, end = _date(starts_at), _date(ends_at)
    if start <= datetime.now(timezone.utc) or end <= start:
        raise ValueError("Session must start in the future and end after its start")
    return repository.write_catalog(company_id=company_id, chatbot_id=chatbot_id, actor_user_id=actor_user_id,
        operation="session", data={"class_id": repository.uuid(class_id), "starts_at": start.isoformat(), "ends_at": end.isoformat(),
                                  **_capacities(total_capacity, enrolled_seats, trial_limit)})


def update_session_capacity(*, company_id, chatbot_id, actor_user_id, session_id, expected_version,
                            total_capacity, enrolled_seats, trial_limit):
    require_trial_context(company_id, chatbot_id)
    repository.positive(actor_user_id)
    return repository.write_catalog(company_id=company_id, chatbot_id=chatbot_id, actor_user_id=actor_user_id,
        operation="capacity", data={"session_id": repository.uuid(session_id), "expected_version": repository.positive(expected_version),
                                  **_capacities(total_capacity, enrolled_seats, trial_limit)})


def list_courses(*, company_id, chatbot_id):
    require_trial_context(company_id, chatbot_id)
    return repository.list_courses(company_id=company_id, chatbot_id=chatbot_id)


def list_classes(*, company_id, chatbot_id, course_id=None):
    require_trial_context(company_id, chatbot_id)
    return repository.list_classes(company_id=company_id, chatbot_id=chatbot_id, course_id=course_id)


def list_sessions(*, company_id, chatbot_id, class_id=None):
    require_trial_context(company_id, chatbot_id)
    return repository.list_sessions(company_id=company_id, chatbot_id=chatbot_id, class_id=class_id)


def _customer_command(function, *, company_id, chatbot_id, conversation_id, **params):
    require_trial_context(company_id, chatbot_id)
    repository.positive(conversation_id)
    # Same Flask process gate used by persisted handoff writes. The RPC also
    # locks/rechecks the conversation and existing handoff control in Postgres.
    with conversation_delivery_lock(conversation_id):
        return function(company_id=company_id, chatbot_id=chatbot_id, conversation_id=conversation_id, **params)


def create_participant(*, company_id, chatbot_id, conversation_id, client_key, label, actor_user_id=None):
    return _customer_command(repository.create_participant, company_id=company_id, chatbot_id=chatbot_id,
        conversation_id=conversation_id, client_key=_text(client_key, 100), label=_text(label, 80), actor_user_id=actor_user_id)


def update_participant(*, company_id, chatbot_id, conversation_id, participant_id, expected_version, label, actor_user_id):
    repository.positive(actor_user_id)
    return _customer_command(repository.update_participant, company_id=company_id, chatbot_id=chatbot_id,
        conversation_id=conversation_id, participant_id=participant_id, expected_version=expected_version,
        label=_text(label, 80), actor_user_id=actor_user_id)


def list_participants(*, company_id, chatbot_id, conversation_id):
    require_trial_context(company_id, chatbot_id)
    return repository.list_participants(company_id=company_id, chatbot_id=chatbot_id, conversation_id=conversation_id)


def list_bookings(*, company_id, chatbot_id, conversation_id=None):
    require_trial_context(company_id, chatbot_id)
    return repository.list_bookings(company_id=company_id, chatbot_id=chatbot_id, conversation_id=conversation_id)


def prepare_trial(*, company_id, chatbot_id, conversation_id, participant_id, session_id, booking_id=None,
                  reminder_consent=False, evidence_message_id=None, actor_user_id=None):
    if type(reminder_consent) is not bool:
        raise ValueError("Reminder consent must be explicit")
    return _customer_command(repository.prepare_trial, company_id=company_id, chatbot_id=chatbot_id,
        conversation_id=conversation_id, participant_id=participant_id, session_id=session_id, booking_id=booking_id,
        reminder_consent=reminder_consent, evidence_message_id=evidence_message_id, actor_user_id=actor_user_id)


def _public_booking(booking):
    return {key: value for key, value in booking.items() if key not in {"contact_key", "confirmation_id"}}


def confirm_trial(*, company_id, chatbot_id, conversation_id, confirmation_token, actor_user_id=None):
    result = _customer_command(repository.confirm_trial, company_id=company_id, chatbot_id=chatbot_id,
        conversation_id=conversation_id, confirmation_token=_text(confirmation_token, 100), actor_user_id=actor_user_id)
    return {**result, "booking": _public_booking(result["booking"])}


def cancel_trial(*, company_id, chatbot_id, conversation_id, booking_id, client_message_id, expected_version, actor_user_id=None):
    result = _customer_command(repository.cancel_trial, company_id=company_id, chatbot_id=chatbot_id,
        conversation_id=conversation_id, booking_id=booking_id, client_message_id=_text(client_message_id, 100), expected_version=repository.positive(expected_version), actor_user_id=actor_user_id)
    return _public_booking(result)
