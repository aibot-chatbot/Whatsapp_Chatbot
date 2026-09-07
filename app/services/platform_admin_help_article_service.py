"""Platform-admin CRUD for the global help article catalogue (FR-6).

This is a platform-admin service, so it deliberately borrows that surface's
conventions wholesale rather than inventing a second set: it raises
PlatformAdminServiceError, which app/routes/platform_admin_routes.py::_execute
already turns into the {status, code, message} envelope every other
platform-admin endpoint returns, and it reuses that surface's existing codes
(invalid_request, invalid_category, invalid_title, no_change,
platform_admin_data_unavailable) wherever one already fits.

It lives beside platform_admin_service.py rather than inside it only because
that module is already 2500 lines; the contract is identical.
"""

import logging
import re

from app.database import help_article_repository
from app.services.platform_admin_service import PlatformAdminServiceError


logger = logging.getLogger(__name__)

# These four bounds mirror migration 050's CHECK constraints exactly. They are
# duplicated here on purpose - the database must not be the only guard, or a
# 200-character overrun reaches the API as an opaque 503 instead of a 400 that
# names the field - and they must never be relaxed independently of the
# migration, or the service starts accepting rows Postgres will reject.
TITLE_MAX_LENGTH = 200
BODY_MAX_LENGTH = 8000
SLUG_MAX_LENGTH = 200
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# sort_order is a Postgres `integer`, so anything outside int4 is a write that
# can only fail at the database.
SORT_ORDER_MIN = -(2 ** 31)
SORT_ORDER_MAX = 2 ** 31 - 1

WRITABLE_FIELDS = frozenset(
    {"category", "title", "body", "slug", "is_published", "sort_order"}
)
REQUIRED_ON_CREATE = ("category", "title", "body")

# The wire contract pinned for the Admin UI. Serialisation is a whitelist, not
# a deletion pass, so a column added to help_articles later cannot start
# leaking just because someone widened the select.
ARTICLE_FIELDS = (
    "id", "category", "title", "body", "slug", "is_published",
    "sort_order", "created_at", "updated_at",
)

SLUG_CONFLICT_MESSAGE = "A help article with that slug already exists."
ARTICLE_NOT_FOUND_MESSAGE = "Help article not found."


def _validation(code, message):
    raise PlatformAdminServiceError(400, code, message)


def _data_unavailable():
    raise PlatformAdminServiceError(
        503, "platform_admin_data_unavailable",
        "Platform data is temporarily unavailable.",
    )


def _slug_conflict():
    raise PlatformAdminServiceError(
        409, "help_article_slug_exists", SLUG_CONFLICT_MESSAGE
    )


def _not_found():
    raise PlatformAdminServiceError(
        404, "help_article_not_found", ARTICLE_NOT_FOUND_MESSAGE
    )


def _strict_body(payload, allowed_keys):
    if not isinstance(payload, dict):
        _validation("invalid_request", "Request body must be a JSON object.")
    if set(payload) - set(allowed_keys):
        _validation("invalid_request", "Request body contains unsupported fields.")
    return payload


def _article_id(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _validation("invalid_article_id", "Article ID must be a positive integer.")
    return value


def _text_field(value, *, name, code, maximum):
    """A stripped, non-blank string within the column's CHECK bound.

    The stripped value is both what is validated and what is stored, so the
    length this accepts is the length Postgres measures.
    """
    if not isinstance(value, str):
        _validation(code, f"{name} must be text.")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        _validation(code, f"{name} must contain 1 to {maximum} characters.")
    return normalized


def _category(value):
    if (
        not isinstance(value, str)
        or value.strip() not in help_article_repository.ALLOWED_CATEGORIES
    ):
        _validation("invalid_category", "category is not supported.")
    return value.strip()


def _slug(value):
    normalized = _text_field(
        value, name="slug", code="invalid_slug", maximum=SLUG_MAX_LENGTH
    )
    if not SLUG_PATTERN.fullmatch(normalized):
        _validation(
            "invalid_slug",
            "slug must be lowercase letters, digits and single hyphens.",
        )
    return normalized


def _derive_slug(title):
    """A slug from the title, or a 400 rather than a value the column rejects."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    slug = slug[:SLUG_MAX_LENGTH].strip("-")
    if not slug or not SLUG_PATTERN.fullmatch(slug):
        _validation(
            "invalid_slug",
            "A slug could not be derived from the title; supply one explicitly.",
        )
    return slug


def _boolean(value, *, name, code):
    if not isinstance(value, bool):
        _validation(code, f"{name} must be true or false.")
    return value


def _sort_order(value):
    if isinstance(value, bool) or not isinstance(value, int):
        _validation("invalid_sort_order", "sort_order must be an integer.")
    if not SORT_ORDER_MIN <= value <= SORT_ORDER_MAX:
        _validation("invalid_sort_order", "sort_order is outside the allowed range.")
    return value


def _safe_article(row, counts):
    if not isinstance(row, dict):
        row = {}
    if not isinstance(counts, dict):
        counts = {}
    article = {field: row.get(field) for field in ARTICLE_FIELDS}
    article["helpful_count"] = counts.get("helpful_count", 0)
    article["unhelpful_count"] = counts.get("unhelpful_count", 0)
    return article


def _counts_for(article_ids):
    try:
        return help_article_repository.count_help_article_feedback(article_ids)
    except Exception:
        # The postgrest message can name tables and columns, so it is logged
        # server side and never returned.
        logger.error("Help article feedback tally failed")
        _data_unavailable()


def list_help_articles():
    """Every article, draft and published, with its helpfulness tallies.

    Two queries total regardless of how many articles come back: one for the
    articles, one for every relevant feedback row.
    """
    try:
        rows = help_article_repository.list_all_help_articles()
    except Exception:
        logger.error("Help article admin listing failed")
        _data_unavailable()

    article_ids = [
        row.get("id")
        for row in rows
        if isinstance(row.get("id"), int) and not isinstance(row.get("id"), bool)
    ]
    counts = _counts_for(article_ids)
    return {
        "articles": [
            _safe_article(row, counts.get(row.get("id"), {})) for row in rows
        ]
    }


def create_help_article(payload):
    payload = _strict_body(payload, WRITABLE_FIELDS)
    for field in REQUIRED_ON_CREATE:
        if field not in payload:
            _validation("invalid_request", f"{field} is required.")

    category = _category(payload["category"])
    title = _text_field(
        payload["title"], name="title", code="invalid_title", maximum=TITLE_MAX_LENGTH
    )
    body = _text_field(
        payload["body"], name="body", code="invalid_body", maximum=BODY_MAX_LENGTH
    )
    slug = _slug(payload["slug"]) if "slug" in payload else _derive_slug(title)
    is_published = _boolean(
        payload.get("is_published", False),
        name="is_published", code="invalid_is_published",
    )
    sort_order = _sort_order(payload.get("sort_order", 0))

    try:
        row = help_article_repository.create_help_article(
            category=category, title=title, body=body, slug=slug,
            is_published=is_published, sort_order=sort_order,
        )
    except help_article_repository.HelpArticleSlugConflict:
        # A 409, never a silent overwrite: the existing article belongs to
        # whoever wrote it and a duplicate slug is a decision for staff.
        _slug_conflict()
    except Exception:
        logger.error("Help article creation failed")
        _data_unavailable()
    return {"article": _safe_article(row, {})}


def _validated_changes(payload):
    changes = {}
    if "category" in payload:
        changes["category"] = _category(payload["category"])
    if "title" in payload:
        changes["title"] = _text_field(
            payload["title"], name="title", code="invalid_title",
            maximum=TITLE_MAX_LENGTH,
        )
    if "body" in payload:
        changes["body"] = _text_field(
            payload["body"], name="body", code="invalid_body",
            maximum=BODY_MAX_LENGTH,
        )
    if "slug" in payload:
        changes["slug"] = _slug(payload["slug"])
    if "is_published" in payload:
        changes["is_published"] = _boolean(
            payload["is_published"], name="is_published", code="invalid_is_published"
        )
    if "sort_order" in payload:
        changes["sort_order"] = _sort_order(payload["sort_order"])
    return changes


def update_help_article(article_id, payload):
    """Partial update. A new title does not re-derive the slug.

    Re-deriving would silently change a published article's identity, so the
    slug only ever moves when staff ask for it by name.
    """
    article_id = _article_id(article_id)
    payload = _strict_body(payload, WRITABLE_FIELDS)
    if not payload:
        _validation("no_change", "At least one field must be provided.")
    changes = _validated_changes(payload)

    try:
        row = help_article_repository.update_help_article(article_id, changes)
    except help_article_repository.HelpArticleSlugConflict:
        _slug_conflict()
    except Exception:
        logger.error("Help article update failed for %s", article_id)
        _data_unavailable()
    if not row:
        _not_found()
    return {"article": _safe_article(row, _counts_for([article_id]).get(article_id, {}))}


def delete_help_article(article_id):
    """Delete one article; its feedback rows cascade with it (migration 050)."""
    article_id = _article_id(article_id)
    try:
        row = help_article_repository.delete_help_article(article_id)
    except Exception:
        logger.error("Help article delete failed for %s", article_id)
        _data_unavailable()
    if not row:
        _not_found()
    return {"article_id": article_id, "deleted": True}
