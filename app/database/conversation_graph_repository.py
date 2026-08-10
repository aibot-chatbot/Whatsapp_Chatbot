"""Data access for conversation-scoped graph nodes.

Scoping model
-------------
A conversation fact is a node bound to exactly one conversation. Binding is by
``conversation_id``; tenancy is by ``chatbot_id``. Both are applied as filters on
every *read* and *delete* in this module, so a caller holding a valid
``conversation_id`` from another tenant selects zero rows there.

The write path is the exception, and it is a real gap. ``upsert_conversation_fact``
resolves on the conflict target ``(conversation_id, label)``; ``chatbot_id`` is a
payload column, not a predicate. An upsert carrying a ``conversation_id`` owned by
another tenant therefore does not select zero rows -- it takes the ``DO UPDATE``
branch and rewrites that row's ``chatbot_id`` and value. Nothing in the schema
prevents it either: see the "TENANCY IS NOT ENFORCED BY THIS SCHEMA" section of
``data/033_conversation_graph_nodes.sql`` for the composite foreign key that
would. It is not reachable from untrusted input today because the only producer
derives ``conversation_id`` from ``get_or_create_conversation(chatbot_id=...)``;
do not add a caller that accepts a conversation id from a request before that
constraint exists.

Lifetime is the conversation's lifetime: both foreign keys are
``ON DELETE CASCADE`` (see ``data/033_conversation_graph_nodes.sql``), so
deleting a conversation or a chatbot removes its facts with it. There is no
independent expiry -- a fact is as durable as the conversation that produced it.

This is deliberately a separate relation from ``knowledge_graph_nodes``. That
table is uniquely keyed on ``(chatbot_id, name)`` (see
``knowledge_graph_repository.upsert_node``), so two concurrent conversations
that both learn a customer name would collide on one row and overwrite each
other -- a cross-conversation data leak. Its DDL also does not exist anywhere in
``data/``, so widening that key is not a safely specifiable migration.

Errors propagate. Callers in the reply path decide whether degradation is
acceptable and log accordingly; this module does not silently swallow failures.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.database.db import supabase

TABLE_NAME = "conversation_graph_nodes"

MAX_LABEL_LEN = 120
MAX_VALUE_LEN = 500

# Caps the ``IN`` list in :func:`get_conversation_facts_by_labels`. The lookup's
# cost bound is structural -- ``UNIQUE (conversation_id, label)`` permits one row
# per label, so rows fetched equals the length of this list -- and the cap is
# what makes it a *constant*. It is enforced here, at the layer that emits the
# query, rather than trusted to whichever caller happens to cap upstream.
MAX_LOOKUP_LABELS = 24

# Mirrors the UNIQUE constraint in migration 033.
ON_CONFLICT = "conversation_id,label"

_SELECT_COLUMNS = "id,chatbot_id,conversation_id,label,value,fact_type,properties,updated_at"


def normalize_label(label: str) -> str:
    """Normalise a label to its lookup form.

    Labels are stored lowercase and whitespace-trimmed so that keyword lookup
    is a plain equality match. That is what lets the composite btree index
    serve the query without ``pg_trgm`` or ``text_pattern_ops`` -- equality and
    ``IN`` on a btree are collation-independent.

    This is the *storage* normal form, not the recall normal form. It keeps
    spaces, hyphens and non-ASCII, none of which the reader can ever produce:
    ``conversation_memory_service`` reduces a query through
    ``rag_service.clean_query_words`` first, so only a single ASCII
    alphanumeric non-stopword token round-trips. A label outside that set is
    stored successfully and is then unfindable by keyword recall -- see the
    "Label form is a constraint" note in that module before adding one.
    """
    if not isinstance(label, str):
        return ""
    return " ".join(label.strip().lower().split())[:MAX_LABEL_LEN]


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer, got {value!r}")
    return value


def upsert_conversation_fact(
    chatbot_id: int,
    conversation_id: int,
    label: str,
    value: str,
    fact_type: str = "attribute",
    properties: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Insert or update one fact for a conversation.

    Idempotent per ``(conversation_id, label)``: re-stating a fact updates the
    existing row rather than appending, mirroring ``upsert_node``. The most
    recent mention wins.
    """
    _require_positive_int(chatbot_id, "chatbot_id")
    _require_positive_int(conversation_id, "conversation_id")

    normalized_label = normalize_label(label)
    if not normalized_label:
        raise ValueError("label must be a non-empty string")

    if value is None:
        raise ValueError("value must not be None")

    payload = {
        "chatbot_id": chatbot_id,
        "conversation_id": conversation_id,
        "label": normalized_label,
        "value": str(value).strip()[:MAX_VALUE_LEN],
        "fact_type": str(fact_type or "attribute").strip().lower() or "attribute",
        "properties": properties or {},
    }

    result = (
        supabase.table(TABLE_NAME)
        .upsert(payload, on_conflict=ON_CONFLICT)
        .execute()
    )
    return result.data[0] if result.data else None


def get_conversation_facts_by_labels(
    chatbot_id: int,
    conversation_id: int,
    labels: Iterable[str],
) -> list[dict[str, Any]]:
    """Keyword lookup: fetch this conversation's facts whose label matches.

    Emits ``chatbot_id = $1 AND conversation_id = $2 AND label IN ($3...)``.
    The ``UNIQUE (conversation_id, label)`` btree from migration 033 serves the
    last two as index conditions (leading equality, then a ScalarArrayOp).
    ``chatbot_id`` is not in that index and is applied as a heap filter; the
    UNIQUE constraint caps matches at one row per label and this function caps
    the label list at ``MAX_LOOKUP_LABELS``, so that filter examines at most
    that many rows regardless of how many facts the conversation holds.

    Labels beyond the cap are dropped, not rejected: the caller is reducing a
    free-text message to candidate terms, and the terms it kept first are the
    ones worth spending the lookup on.
    """
    _require_positive_int(chatbot_id, "chatbot_id")
    _require_positive_int(conversation_id, "conversation_id")

    normalized = sorted({
        normalized_label
        for normalized_label in (normalize_label(label) for label in labels or [])
        if normalized_label
    })[:MAX_LOOKUP_LABELS]
    if not normalized:
        return []

    result = (
        supabase.table(TABLE_NAME)
        .select(_SELECT_COLUMNS)
        .eq("chatbot_id", chatbot_id)
        .eq("conversation_id", conversation_id)
        .in_("label", normalized)
        .execute()
    )
    return list(result.data or [])


def delete_conversation_facts(chatbot_id: int, conversation_id: int) -> int:
    """Drop every fact for one conversation. Returns the number removed.

    Routine cleanup happens by cascade when the conversation is deleted; this
    exists for an explicit "forget this conversation" action.
    """
    _require_positive_int(chatbot_id, "chatbot_id")
    _require_positive_int(conversation_id, "conversation_id")

    result = (
        supabase.table(TABLE_NAME)
        .delete()
        .eq("chatbot_id", chatbot_id)
        .eq("conversation_id", conversation_id)
        .execute()
    )
    return len(result.data or [])
