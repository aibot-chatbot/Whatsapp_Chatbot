"""Tenant-scoped industry drafts and explicitly confirmed template selections."""

from app.database.db import supabase


def get_industry_template_state(chatbot_id, company_id=None):
    query = supabase.table("chatbots").select(
        "id,company_id,draft_pdf_path,industry_template_draft,industry_template_published"
    ).eq("id", chatbot_id)
    if company_id is not None:
        query = query.eq("company_id", company_id)
    rows = query.limit(1).execute().data or []
    return rows[0] if rows else None


def _proposal_guard(query, column, proposal_id):
    field = column + "->>proposal_id"
    return query.eq(field, proposal_id) if proposal_id else query.is_(field, "null")


def save_industry_template_draft(chatbot_id, company_id, source_path, draft, previous_proposal_id=None):
    query = (
        supabase.table("chatbots")
        .update({"industry_template_draft": draft})
        .eq("id", chatbot_id)
        .eq("company_id", company_id)
        .eq("draft_pdf_path", source_path)
    )
    rows = _proposal_guard(query, "industry_template_draft", previous_proposal_id).execute().data or []
    return rows[0] if rows else None


def publish_industry_template(chatbot_id, company_id, proposal_id, source_path, published, previous_proposal_id=None):
    query = (
        supabase.table("chatbots")
        .update({"industry_template_published": published})
        .eq("id", chatbot_id)
        .eq("company_id", company_id)
        .eq("draft_pdf_path", source_path)
        .eq("industry_template_draft->>proposal_id", proposal_id)
    )
    rows = _proposal_guard(query, "industry_template_published", previous_proposal_id).execute().data or []
    return rows[0] if rows else None
