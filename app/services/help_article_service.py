"""Validation and tenant-safe serialisation for the help article read path."""

import logging

from app.database import help_article_repository


logger = logging.getLogger(__name__)


class HelpArticleServiceError(Exception):
    def __init__(self, status_code, message, code=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        # The read route's envelope is pinned to {status, message} by
        # 03-design.md section 5, so `code` stays optional. The feedback route
        # is a write with several distinct rejections and needs one.
        self.code = code


ARTICLES_UNAVAILABLE_MESSAGE = "Unable to load help articles."
FEEDBACK_UNAVAILABLE_MESSAGE = "Unable to record article feedback."
ARTICLE_NOT_FOUND_MESSAGE = "Help article not found."

# One field, and it is the only one a browser may send: tenancy comes from the
# JWT (02-analysis.md section 1) and the article comes from the URL.
FEEDBACK_FIELDS = frozenset({"was_helpful"})

# The wire contract from 03-design.md section 5. Serialisation is a whitelist,
# not a deletion pass, so a column added to help_articles later - a draft note,
# an author id - cannot start leaking just because someone widened the select.
ARTICLE_FIELDS = ("id", "category", "title", "body", "slug", "sort_order")


def _safe_article(row):
    if not isinstance(row, dict):
        row = {}
    return {field: row.get(field) for field in ARTICLE_FIELDS}


def list_published_articles():
    try:
        rows = help_article_repository.list_published_help_articles()
    except Exception:
        # The postgrest message can name tables and columns, so it is logged
        # server side and never returned.
        logger.error("Help article lookup failed")
        raise HelpArticleServiceError(500, ARTICLES_UNAVAILABLE_MESSAGE)
    return {"articles": [_safe_article(row) for row in rows]}


def _feedback_error(code, message, status_code=400):
    raise HelpArticleServiceError(status_code, message, code)


def _positive_article_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _feedback_error("invalid_article_id", "Article ID must be a positive integer.")
    return value


def _tenant_context(company_id):
    if isinstance(company_id, bool) or not isinstance(company_id, int) or company_id <= 0:
        _feedback_error(
            "authentication_context_invalid",
            "Authenticated company context is invalid.",
            status_code=500,
        )
    return company_id


def record_article_feedback(article_id, payload, *, company_id):
    """Record one tenant's helpfulness vote on a published article."""
    article_id = _positive_article_id(article_id)
    company_id = _tenant_context(company_id)

    if not isinstance(payload, dict):
        _feedback_error("invalid_request", "Request body must be an object.")
    if set(payload) - FEEDBACK_FIELDS:
        _feedback_error("unsupported_field", "Request contains unsupported fields.")
    was_helpful = payload.get("was_helpful")
    if not isinstance(was_helpful, bool):
        _feedback_error("invalid_was_helpful", "was_helpful must be true or false.")

    try:
        article = help_article_repository.get_published_help_article(article_id)
    except Exception:
        logger.error("Help article lookup failed for feedback on %s", article_id)
        _feedback_error(
            "help_feedback_unavailable", FEEDBACK_UNAVAILABLE_MESSAGE, status_code=503
        )
    if not article:
        # Deliberately the same answer for "no such article" and "not published
        # yet": a distinct response would let any tenant enumerate drafts.
        _feedback_error(
            "help_article_not_found", ARTICLE_NOT_FOUND_MESSAGE, status_code=404
        )

    try:
        help_article_repository.record_help_article_feedback(
            article_id=article_id, company_id=company_id, was_helpful=was_helpful
        )
    except Exception:
        logger.error("Help article feedback write failed for article %s", article_id)
        _feedback_error(
            "help_feedback_unavailable", FEEDBACK_UNAVAILABLE_MESSAGE, status_code=503
        )

    return {"article_id": article_id, "was_helpful": was_helpful}
