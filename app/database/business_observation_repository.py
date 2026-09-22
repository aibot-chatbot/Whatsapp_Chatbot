"""Scoped opt-in settings and worker-only durable observation transitions."""

from uuid import UUID

from app.database.db import supabase
from app.database.analysis_repository import AnalysisConflict, AnalysisScopeDenied, AnalysisUnavailable


def _scope(company_id, chatbot_id):
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (company_id, chatbot_id)):
        raise AnalysisScopeDenied("Valid company and Bot are required")


def _row(query):
    try:
        rows = query.execute().data
    except Exception:
        raise AnalysisUnavailable("Business observation storage is unavailable") from None
    if not isinstance(rows, list):
        raise AnalysisUnavailable("Business observation storage returned no result")
    if not rows:
        raise AnalysisScopeDenied("Bot is unavailable")
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise AnalysisUnavailable("Business observation storage returned an invalid result")
    return rows[0]


def get_recording_enabled(company_id, chatbot_id):
    _scope(company_id, chatbot_id)
    row = _row(supabase.table("chatbots").select("id,company_id,analysis_recording_enabled")
        .eq("id", chatbot_id).eq("company_id", company_id).is_("deleted_at", "null").neq("status", "archived").limit(1))
    if row.get("id") != chatbot_id or row.get("company_id") != company_id or not isinstance(row.get("analysis_recording_enabled"), bool):
        raise AnalysisUnavailable("Recording setting could not be verified")
    return row.get("analysis_recording_enabled") is True


def set_recording_enabled(company_id, chatbot_id, enabled):
    _scope(company_id, chatbot_id)
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be a boolean")
    # PostgREST update returns the matched representation; do not silently claim
    # success if a foreign/deleted Bot matched no row.
    row = _row(supabase.table("chatbots").update({"analysis_recording_enabled": enabled})
        .eq("id", chatbot_id).eq("company_id", company_id).is_("deleted_at", "null").neq("status", "archived"))
    if row.get("id") != chatbot_id or row.get("company_id") != company_id or row.get("analysis_recording_enabled") is not enabled:
        raise AnalysisUnavailable("Recording setting could not be confirmed")
    return enabled


def apply_observation(*, event_id, lease_token, operation, output=None):
    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        raise ValueError("Invalid event ID")
    if operation not in {"inspect", "start", "finish", "skip", "uncertain"}:
        raise ValueError("Invalid observation operation")
    token = str(UUID(str(lease_token)))
    try:
        data = supabase.rpc("analysis_apply_business_observation", {
            "p_event_id": event_id, "p_lease_token": token, "p_operation": operation, "p_output": output or {},
        }).execute().data
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code == "40001":
            raise AnalysisConflict("Observation lease changed") from None
        if code == "42501":
            raise AnalysisScopeDenied("Observation source is unavailable") from None
        raise AnalysisUnavailable("Observation storage is unavailable") from None
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict) or not data:
        raise AnalysisUnavailable("Observation storage did not confirm the operation")
    return data
