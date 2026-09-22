"""Suggest an industry from a primary document; apply only explicit staff confirmation."""

from datetime import datetime, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL

from app.database import industry_template_repository as repository
from app.database.knowledge_file_repository import get_knowledge_file_by_name_or_id
from app.services.industry_template_catalog import get_template, list_templates


class IndustryTemplateError(ValueError):
    def __init__(self, message, code, status_code):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now():
    return datetime.now(timezone.utc).isoformat()


def _state(chatbot_id, company_id=None):
    try:
        state = repository.get_industry_template_state(chatbot_id, company_id)
    except Exception:
        raise IndustryTemplateError(
            "Industry templates are temporarily unavailable. Your current bot behavior is unchanged.",
            "industry_template_unavailable", 503,
        ) from None
    if not state:
        raise IndustryTemplateError("Chatbot not found.", "chatbot_not_found", 404)
    return state


def _object(value):
    return value if isinstance(value, dict) else {}


def _draft_is_current(state, draft):
    return bool(draft.get("proposal_id") and draft.get("source_path")
                and draft["source_path"] == state.get("draft_pdf_path"))


def _require_company(company_id):
    if not isinstance(company_id, int) or isinstance(company_id, bool) or company_id <= 0:
        raise IndustryTemplateError("A verified company is required.", "company_required", 403)


def _source_is_current(chatbot_id, draft):
    try:
        source = get_knowledge_file_by_name_or_id(chatbot_id, draft.get("source_file_id"))
    except Exception:
        raise IndustryTemplateError("Could not verify the source document.", "industry_template_unavailable", 503) from None
    return bool(source and source.get("is_active") is True
                and source.get("processing_status") == "completed"
                and source.get("file_path") == draft.get("source_path"))


def get_industry_settings(chatbot_id, company_id):
    _require_company(company_id)
    state = _state(chatbot_id, company_id)
    draft = _object(state.get("industry_template_draft"))
    return {
        "draft": draft,
        "published": _object(state.get("industry_template_published")),
        "templates": list_templates(),
        "can_confirm": (_draft_is_current(state, draft)
                        and _object(state.get("industry_template_published")).get("proposal_id") != draft.get("proposal_id")
                        and _source_is_current(chatbot_id, draft)),
    }


def save_industry_suggestion(chatbot_id, source_file_id, suggestion):
    """Internal ingest entry: never publish, and reject a superseded primary source."""
    source = get_knowledge_file_by_name_or_id(chatbot_id, source_file_id)
    if not source or source.get("is_active") is not True or source.get("processing_status") != "completed":
        return None
    source_path = source.get("file_path")
    state = _state(chatbot_id)
    if not source_path or state.get("draft_pdf_path") != source_path:
        return None
    previous = _object(state.get("industry_template_draft"))
    if previous.get("source_file_id") == source_file_id and previous.get("source_path") == source_path:
        # A repeated queue delivery must not reopen a previously reviewed proposal.
        return state
    template = get_template(suggestion.get("template_id")) if suggestion.get("template_id") else None
    draft = {
        "proposal_id": str(uuid5(NAMESPACE_URL, f"industry-template:{chatbot_id}:{source_file_id}:{source_path}")),
        "source_file_id": source_file_id,
        "source_path": source_path,
        "template_id": suggestion.get("template_id"),
        "template_version": template["version"] if template else None,
        "candidate_ids": suggestion.get("candidate_ids", []),
        "evidence": suggestion.get("evidence", []),
        "status": suggestion.get("status", "uncertain"),
        "created_at": _now(),
    }
    try:
        return repository.save_industry_template_draft(chatbot_id, state["company_id"], source_path, draft, previous.get("proposal_id"))
    except Exception:
        raise IndustryTemplateError("Could not save the industry suggestion.", "industry_template_unavailable", 503) from None


def confirm_industry_template(chatbot_id, company_id, actor_user_id, proposal_id, template_id):
    _require_company(company_id)
    if not isinstance(proposal_id, str) or not proposal_id.strip() or len(proposal_id) > 100:
        raise IndustryTemplateError("A valid proposal_id is required.", "invalid_proposal", 400)
    if not isinstance(template_id, str):
        raise IndustryTemplateError("Select an industry template.", "invalid_template", 400)
    try:
        template = get_template(template_id)
    except ValueError:
        template = None
    if not template:
        raise IndustryTemplateError("Select a supported industry template.", "invalid_template", 400)
    if not isinstance(actor_user_id, int) or isinstance(actor_user_id, bool) or actor_user_id <= 0:
        raise IndustryTemplateError("A signed-in staff member is required.", "unauthenticated", 401)
    state = _state(chatbot_id, company_id)
    draft = _object(state.get("industry_template_draft"))
    if (draft.get("proposal_id") != proposal_id or not _draft_is_current(state, draft)
            or not _source_is_current(chatbot_id, draft)):
        raise IndustryTemplateError("The source document or suggestion changed. Refresh and review it again.", "stale_proposal", 409)
    previous = _object(state.get("industry_template_published"))
    if previous.get("proposal_id") == proposal_id:
        if previous.get("template_id") == template_id:
            return get_industry_settings(chatbot_id, company_id)
        raise IndustryTemplateError("This suggestion was already confirmed with another industry. Refresh to see the current selection.", "proposal_already_confirmed", 409)
    published = {
        "template_id": template_id,
        "template_version": template["version"],
        "proposal_id": proposal_id,
        "source_file_id": draft.get("source_file_id"),
        "confirmed_at": _now(),
        "confirmed_by": actor_user_id,
    }
    try:
        saved = repository.publish_industry_template(chatbot_id, company_id, proposal_id, draft["source_path"], published, previous.get("proposal_id"))
    except Exception:
        raise IndustryTemplateError("Could not apply the industry template. Please try again.", "industry_template_unavailable", 503) from None
    if not saved:
        current = get_industry_settings(chatbot_id, company_id)
        current_published = current["published"]
        if (current_published.get("proposal_id") == proposal_id
                and current_published.get("template_id") == template_id):
            return current
        raise IndustryTemplateError("The source document or suggestion changed. Refresh and review it again.", "stale_proposal", 409)
    return {"draft": _object(saved.get("industry_template_draft")),
            "published": _object(saved.get("industry_template_published")),
            "templates": list_templates(), "can_confirm": False}


def review_industry_template(chatbot_id, company_id, proposal_id):
    """Explicitly reopen a confirmed choice without changing the live template."""
    _require_company(company_id)
    if not isinstance(proposal_id, str) or not proposal_id.strip() or len(proposal_id) > 100:
        raise IndustryTemplateError("A valid proposal_id is required.", "invalid_proposal", 400)
    state = _state(chatbot_id, company_id)
    draft = _object(state.get("industry_template_draft"))
    published = _object(state.get("industry_template_published"))
    if (draft.get("proposal_id") != proposal_id or published.get("proposal_id") != proposal_id
            or not _draft_is_current(state, draft) or not _source_is_current(chatbot_id, draft)):
        raise IndustryTemplateError("The industry selection or source changed. Refresh before reviewing it.", "stale_proposal", 409)
    revised = {**draft, "proposal_id": str(uuid4()), "created_at": _now()}
    try:
        saved = repository.save_industry_template_draft(chatbot_id, company_id, draft["source_path"], revised, proposal_id)
    except Exception:
        raise IndustryTemplateError("Could not reopen the industry selection.", "industry_template_unavailable", 503) from None
    if not saved:
        raise IndustryTemplateError("The industry selection changed. Refresh before reviewing it.", "stale_proposal", 409)
    return get_industry_settings(chatbot_id, company_id)
