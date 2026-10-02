"""Tenant-scoped tuition catalogue and transactional trial booking commands."""
from uuid import UUID

from app.database.db import supabase


class TuitionError(ValueError):
    def __init__(self, message, code="tuition_unavailable", status_code=503):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def positive(value):
    if type(value) is not int or value <= 0:
        raise ValueError("A positive integer is required")
    return value


def uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("A valid identifier is required") from None


def _scope(company_id, chatbot_id, conversation_id=None, actor_user_id=None):
    params = {"p_company_id": positive(company_id), "p_chatbot_id": positive(chatbot_id)}
    if conversation_id is not None:
        params["p_conversation_id"] = positive(conversation_id)
        params["p_actor_user_id"] = None if actor_user_id is None else positive(actor_user_id)
    elif actor_user_id is not None:
        params["p_actor_user_id"] = positive(actor_user_id)
    return params


def _rpc(name, params):
    try:
        data = supabase.rpc(name, params).execute().data
    except Exception as error:
        code = getattr(error, "code", "")
        if code == "42501":
            raise TuitionError("This trial resource is unavailable.", "tuition_scope_denied", 404) from None
        if code == "55000":
            raise TuitionError("A staff member must handle this conversation.", "tuition_human_controlled", 409) from None
        if code in {"22023", "23505", "23514", "40001"}:
            raise TuitionError("The booking or available places changed. Please review and confirm again.", "tuition_conflict", 409) from None
        raise TuitionError("Trial booking storage is unavailable.") from None
    if not isinstance(data, dict) or not data:
        raise TuitionError("Trial booking storage did not confirm the operation.")
    return data


def _rows(query):
    try:
        result = query.execute().data
    except Exception:
        raise TuitionError("Trial booking storage is unavailable.") from None
    if not isinstance(result, list):
        raise TuitionError("Trial booking data is unavailable.")
    return result


def write_catalog(*, company_id, chatbot_id, actor_user_id, operation, data):
    return _rpc("tuition_catalog_write", {**_scope(company_id, chatbot_id, actor_user_id=actor_user_id),
        "p_operation": operation, "p_data": data})


def list_courses(*, company_id, chatbot_id):
    _scope(company_id, chatbot_id)
    return _rows(supabase.table("tuition_courses").select("*").eq("company_id", company_id)
        .eq("chatbot_id", chatbot_id).eq("enabled", True).order("name").limit(200))


def list_classes(*, company_id, chatbot_id, course_id=None):
    _scope(company_id, chatbot_id)
    query = supabase.table("tuition_classes").select("*").eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("enabled", True)
    if course_id:
        query = query.eq("course_id", uuid(course_id))
    return _rows(query.order("name").limit(200))


def list_sessions(*, company_id, chatbot_id, class_id=None):
    result = _rpc("tuition_list_sessions", {**_scope(company_id, chatbot_id), "p_class_id": uuid(class_id) if class_id else None})
    if not isinstance(result.get("sessions"), list):
        raise TuitionError("Trial sessions are unavailable.")
    return result["sessions"]


def create_participant(*, company_id, chatbot_id, conversation_id, client_key, label, actor_user_id=None):
    return _rpc("tuition_create_participant", {**_scope(company_id, chatbot_id, conversation_id, actor_user_id),
        "p_client_key": client_key, "p_label": label})


def update_participant(*, company_id, chatbot_id, conversation_id, participant_id, expected_version, label, actor_user_id):
    positive(actor_user_id)
    return _rpc("tuition_update_participant", {**_scope(company_id, chatbot_id, conversation_id, actor_user_id),
        "p_participant_id": uuid(participant_id), "p_expected_version": positive(expected_version), "p_label": label})


def list_participants(*, company_id, chatbot_id, conversation_id):
    _scope(company_id, chatbot_id, conversation_id)
    return _rows(supabase.table("tuition_participants").select("id,label,version,created_at")
        .eq("company_id", company_id).eq("chatbot_id", chatbot_id).eq("conversation_id", conversation_id).order("created_at").limit(100))


def list_bookings(*, company_id, chatbot_id, conversation_id=None):
    _scope(company_id, chatbot_id, conversation_id)
    query = supabase.table("tuition_bookings").select(
        "id,participant_id,session_id,conversation_id,status,version,reminder_consent,reminder_enabled,reminder_unavailable_reason,reminder_at,reminder_status,created_at,updated_at,tuition_participants(label)")
    query = query.eq("company_id", company_id).eq("chatbot_id", chatbot_id)
    if conversation_id is not None:
        query = query.eq("conversation_id", conversation_id)
    rows = _rows(query.order("created_at", desc=True).limit(200))
    for row in rows:
        participant = row.pop("tuition_participants", None)
        row["participant_label"] = participant.get("label", "") if isinstance(participant, dict) else ""
    return rows


def prepare_trial(*, company_id, chatbot_id, conversation_id, participant_id, session_id, booking_id=None,
                  reminder_consent=False, evidence_message_id=None, actor_user_id=None):
    return _rpc("tuition_prepare_trial", {**_scope(company_id, chatbot_id, conversation_id, actor_user_id),
        "p_participant_id": uuid(participant_id), "p_session_id": uuid(session_id),
        "p_booking_id": uuid(booking_id) if booking_id else None,
        "p_reminder_consent": reminder_consent,
        "p_evidence_message_id": positive(evidence_message_id) if evidence_message_id is not None else None})


def confirm_trial(*, company_id, chatbot_id, conversation_id, confirmation_token, actor_user_id=None):
    return _rpc("tuition_confirm_trial", {**_scope(company_id, chatbot_id, conversation_id, actor_user_id),
        "p_confirmation_token": confirmation_token})


def cancel_trial(*, company_id, chatbot_id, conversation_id, booking_id, client_message_id, expected_version, actor_user_id=None):
    return _rpc("tuition_cancel_trial", {**_scope(company_id, chatbot_id, conversation_id, actor_user_id),
        "p_booking_id": uuid(booking_id), "p_client_message_id": client_message_id, "p_expected_version": positive(expected_version)})
