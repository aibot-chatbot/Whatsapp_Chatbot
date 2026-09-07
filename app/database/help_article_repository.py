"""Service-role repository for global help articles and tenant feedback."""

import logging
from datetime import datetime, timezone

from app.database.db import supabase
from app.database.db_errors import is_unique_violation


logger = logging.getLogger(__name__)

# is_published is a filter, never a projected column: publication state is
# staff information and has no business crossing the API boundary.
ARTICLE_FIELDS = "id,category,title,body,slug,sort_order"

# The staff projection. Publication state and timestamps are exactly what the
# tenant projection above withholds, which is why they are two constants and
# not one with a flag.
ADMIN_ARTICLE_FIELDS = (
    "id,category,title,body,slug,is_published,sort_order,created_at,updated_at"
)

# Columns platform admins may write. id, created_at and updated_at are excluded
# on purpose: two are database-owned and updated_at is stamped here.
WRITABLE_ARTICLE_FIELDS = frozenset(
    {"category", "title", "body", "slug", "is_published", "sort_order"}
)

ALLOWED_CATEGORIES = {
    "technical", "account", "chatbot", "integration", "billing_question",
    "ai_credits", "other",
}

# ponytail: the whole published set is fetched once and filtered in the
# browser (02-analysis section 2). This ceiling is the bound on that decision -
# past a few hundred articles, add a server-side search endpoint instead of
# raising it.
MAX_ARTICLE_LIMIT = 500

# ponytail: helpfulness counts are produced by pulling the (article_id,
# was_helpful) pairs for the listed articles in ONE query and tallying them in
# Python, because a count per article would be an N+1 and PostgREST aggregate
# functions are not enabled on this project. This cap is the ceiling on that
# choice: help_article_feedback holds at most one row per (article, company),
# so it bites only once articles x voting tenants exceeds it. Past that, add a
# grouped aggregate view in a new migration and select from it instead of
# raising this number.
MAX_FEEDBACK_ROWS = 50000


class HelpArticleSlugConflict(Exception):
    """The unique index on help_articles.slug rejected a write."""


def _validate_positive_id(value, field_name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _validate_limit(limit):
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if not 1 <= limit <= MAX_ARTICLE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_ARTICLE_LIMIT}")


def list_published_help_articles(*, limit=MAX_ARTICLE_LIMIT, category=None):
    """Published articles only, ordered by sort_order then id.

    Articles are global platform content, so there is no tenant filter here
    (02-analysis section 4). Tenancy lives on help_article_feedback instead.
    """
    _validate_limit(limit)
    if category is not None and category not in ALLOWED_CATEGORIES:
        raise ValueError("Unsupported help article category")
    query = (
        supabase.table("help_articles")
        .select(ARTICLE_FIELDS)
        .eq("is_published", True)
    )
    if category is not None:
        query = query.eq("category", category)
    response = (
        query.order("sort_order", desc=False)
        .order("id", desc=False)
        .limit(limit)
        .execute()
    )
    return response.data or []


def get_published_help_article(article_id):
    """The article if it is published, else None.

    Only the id is selected: the caller is deciding whether a vote is allowed,
    not rendering anything, and an unpublished article must be indistinguishable
    from one that does not exist.
    """
    _validate_positive_id(article_id, "article_id")
    response = (
        supabase.table("help_articles")
        .select("id")
        .eq("id", article_id)
        .eq("is_published", True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def record_help_article_feedback(*, article_id, company_id, was_helpful):
    """One vote per tenant per article. Returns True when the row was new.

    The unique index on (article_id, company_id) is the arbiter, not a prior
    SELECT: two concurrent votes from the same tenant would both pass a
    read-then-write check and one would fail on insert anyway. Catching the
    unique violation and updating is the same code path with none of the race.
    """
    _validate_positive_id(article_id, "article_id")
    _validate_positive_id(company_id, "company_id")
    if not isinstance(was_helpful, bool):
        raise ValueError("was_helpful must be a boolean")

    try:
        supabase.table("help_article_feedback").insert(
            {
                "article_id": article_id,
                "company_id": company_id,
                "was_helpful": was_helpful,
            }
        ).execute()
    except Exception as error:
        if not is_unique_violation(error):
            raise
        (
            supabase.table("help_article_feedback")
            .update({"was_helpful": was_helpful})
            .eq("article_id", article_id)
            .eq("company_id", company_id)
            .execute()
        )
        return False
    return True


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _validate_category(category):
    if category not in ALLOWED_CATEGORIES:
        raise ValueError("Unsupported help article category")


def list_all_help_articles(*, limit=MAX_ARTICLE_LIMIT):
    """Every article, draft or published, ordered by sort_order then id.

    The deliberate difference from list_published_help_articles: staff author
    drafts and have to be able to find them again, so there is no is_published
    filter and the projection carries publication state and timestamps.
    """
    _validate_limit(limit)
    response = (
        supabase.table("help_articles")
        .select(ADMIN_ARTICLE_FIELDS)
        .order("sort_order", desc=False)
        .order("id", desc=False)
        .limit(limit)
        .execute()
    )
    return response.data or []


def count_help_article_feedback(article_ids):
    """{article_id: {"helpful_count": n, "unhelpful_count": n}} in one query.

    One query for the whole page, never one per article - see MAX_FEEDBACK_ROWS
    for the ceiling this trades against. Every requested id is present in the
    result, so an article nobody has voted on reports zeroes rather than going
    missing.
    """
    ids = list(article_ids or [])
    for value in ids:
        _validate_positive_id(value, "article_id")
    counts = {
        article_id: {"helpful_count": 0, "unhelpful_count": 0} for article_id in ids
    }
    if not counts:
        return counts

    response = (
        supabase.table("help_article_feedback")
        .select("article_id,was_helpful")
        .in_("article_id", list(counts))
        .limit(MAX_FEEDBACK_ROWS)
        .execute()
    )
    rows = response.data or []
    if len(rows) >= MAX_FEEDBACK_ROWS:
        # Loud rather than silently wrong: past the cap the tallies below are an
        # under-count, and staff would otherwise read them as the truth.
        logger.error(
            "Help article feedback tally hit the %s row cap; counts are truncated",
            MAX_FEEDBACK_ROWS,
        )
    for row in rows:
        bucket = counts.get(row.get("article_id"))
        if bucket is None:
            continue
        key = "helpful_count" if row.get("was_helpful") else "unhelpful_count"
        bucket[key] += 1
    return counts


def create_help_article(
    *, category, title, body, slug, is_published, sort_order
):
    """Insert one article, or raise HelpArticleSlugConflict if the slug is taken.

    The unique index is the arbiter, not a prior SELECT: a read-then-write check
    would still lose a race with a concurrent create and the insert would fail
    anyway. Lengths and shapes are the service's job; what is validated here is
    what this function itself puts into a query.
    """
    _validate_category(category)
    payload = {
        "category": category,
        "title": title,
        "body": body,
        "slug": slug,
        "is_published": is_published,
        "sort_order": sort_order,
    }
    try:
        response = supabase.table("help_articles").insert(payload).execute()
    except Exception as error:
        if is_unique_violation(error):
            raise HelpArticleSlugConflict(slug) from error
        raise
    rows = response.data or []
    if not rows:
        raise RuntimeError("Help article insert returned no row")
    return rows[0]


def update_help_article(article_id, changes):
    """Apply a partial update. Returns the updated row, or None if it is gone."""
    _validate_positive_id(article_id, "article_id")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a non-empty mapping")
    unknown = set(changes) - WRITABLE_ARTICLE_FIELDS
    if unknown:
        raise ValueError("changes contains unsupported fields")
    if "category" in changes:
        _validate_category(changes["category"])

    payload = dict(changes)
    # help_articles has no updated_at trigger, so the timestamp is stamped here
    # or it never moves.
    payload["updated_at"] = _now_iso()
    try:
        response = (
            supabase.table("help_articles")
            .update(payload)
            .eq("id", article_id)
            .execute()
        )
    except Exception as error:
        if is_unique_violation(error):
            raise HelpArticleSlugConflict(changes.get("slug")) from error
        raise
    rows = response.data or []
    return rows[0] if rows else None


def delete_help_article(article_id):
    """Delete one article. Returns the deleted row, or None if it was not there.

    Feedback rows go with it through the ON DELETE CASCADE that migration 050
    declares on help_article_feedback.article_id, so this function must never
    delete from that table itself: the cascade already prevents orphans, and
    service_role holds no DELETE grant there, so a hand-rolled cleanup would
    fail and take the article delete down with it.
    """
    _validate_positive_id(article_id, "article_id")
    response = (
        supabase.table("help_articles")
        .delete()
        .eq("id", article_id)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None
