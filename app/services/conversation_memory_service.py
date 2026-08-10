"""Conversation-scoped memory: remember facts mid-chat, recall them by keyword.

This is the graph's contribution to *answers*, not just to the visualisation.

Producer
--------
``remember_conversation_facts`` persists the fields the pipeline has already
extracted for the current turn. The extractor
(``agent_decision_service._extract_fields``) is pure regex and runs on every
turn regardless, so recording its output adds **no** LLM call and no billing
change. Nothing here touches ``ai_router.generate_system_response``.

Consumer
--------
``recall_conversation_facts`` matches the query's own words against stored node
labels by equality. It runs *beside* vector similarity in
``rag_service.retrieve_relevant_chunks``, never instead of it: an exact term the
embedding misses ("remind me of my name") still hits.

Plan gate
---------
Memory is a paid capability (``conversation_memory``, data/034). The check is
:func:`conversation_memory_denial`. Both seams call it from *inside* the
try/except that swallows their failures -- the producer in
``chat_pipeline_service``, the consumer in ``rag_service`` -- so it returns a
code instead of raising. That, not its placement, is what stops a plan denial
from being logged as a broken write. The two
functions below are the ungated primitives; a new caller must gate itself, and
``tests/test_plan_feature_gating.py::NoUngatedMemoryCallerTests`` fails the day
one appears.

Label form is a constraint, not a convention
--------------------------------------------
Write and read do **not** share one normalisation. Write applies
``normalize_label`` only, which lowercases and collapses whitespace but keeps
spaces, hyphens and non-ASCII. Read first reduces the query with
``rag_service.clean_query_words`` -- lowercase ``[a-z0-9]+`` tokens, longer than
one character, stopwords removed -- and only then applies ``normalize_label``.

A label is therefore recallable only if it survives *both*: a single ASCII
alphanumeric token that is not a stopword. A fact written under ``order
number``, ``order-id`` or ``prenom`` stores fine and is then permanently
unfindable, because no query token can ever contain a space, a hyphen or an
accent. The three labels the producer emits (``name``, ``contact``,
``interest``) round-trip; ``tests/test_conversation_graph_memory.py`` pins that,
so a later change to ``STOPWORDS`` or to the tokenizer fails loudly instead of
silently blinding recall.
"""

from __future__ import annotations

import logging
from typing import Any

from app.database.conversation_graph_repository import (
    MAX_LOOKUP_LABELS,
    MAX_VALUE_LEN,
    get_conversation_facts_by_labels,
    normalize_label,
    upsert_conversation_fact,
)
from app.services.billing_guard import (
    BillingLimitError,
    can_use_plan_feature_for_chatbot,
)

#: Plan feature gating both halves of this module
#: (data/034_gate_new_capability_feature_flags.sql; Free is denied).  Memory
#: adds no LLM call, so it is priced as an Essential-and-up convenience rather
#: than as a cost recovery.
CONVERSATION_MEMORY_FEATURE = "conversation_memory"

#: Returned by :func:`conversation_memory_denial` when the entitlement itself
#: could not be established.  Distinct from a plan saying "no".
DENIAL_UNVERIFIED = "entitlement_unverified"

# An unbounded IN list turns an index lookup into a scan, so cap the terms taken
# from one message. Long messages are rare and the first terms carry the intent.
# Aliased to the repository's own cap rather than restated, so the two layers
# cannot drift into disagreeing about the bound the index argument rests on.
MAX_KEYWORD_TERMS = MAX_LOOKUP_LABELS

MAX_FACT_VALUE_LEN = MAX_VALUE_LEN

# Human-readable prefix for each label, used when rendering facts into context.
_LABEL_PHRASING = {
    "name": "The customer's name is",
    "contact": "The customer's contact detail is",
    "interest": "The customer is interested in",
}


def conversation_memory_denial(chatbot_id: int) -> str | None:
    """Denial code when the owning plan excludes memory, else ``None``.

    Called by both seams -- the producer (``chat_pipeline_service``) and the
    consumer (``rag_service``) -- from *inside* the try/except that
    deliberately swallows storage and recall failures.  Returning is therefore
    load-bearing, not a style choice: a raised denial would be caught there and
    logged as "memory just doesn't work".  Do not make this raise.

    Returns rather than raises, deliberately.  This runs on the live reply
    path: the WhatsApp customer is not the paying tenant, cannot act on a
    billing error and must still get their answer.  Fail-closed here means the
    capability is skipped and named, not that the reply fails.

    Cost ceiling: each call is one chatbot lookup plus the subscription and
    plan lookups inside ``can_use_plan_feature``, and both seams call it, so an
    entitlement costs ~6 reads per turn.  Neither seam short-circuits first --
    the producer gates before testing whether this turn extracted anything, and
    the consumer before testing whether the query yields a usable term -- so an
    ordinary turn with nothing to remember pays it too, and
    ``prepare_chat_prompt`` has already resolved the same owner into
    ``authoritative_company_id`` by that point.  If it shows up in reply
    latency: gate after those cheap tests, or memoise the entitlement per turn
    (resolve once in ``prepare_chat_prompt`` and pass it down) -- never across
    turns, which would keep a downgraded tenant entitled.

    Args:
        chatbot_id: The chatbot whose owning company is checked.

    Returns:
        The denial code (``"feature_not_available"``, ``"no_subscription"``,
        ``"company_unresolved"`` or :data:`DENIAL_UNVERIFIED`), or None when
        the plan allows conversation memory.
    """
    try:
        can_use_plan_feature_for_chatbot(chatbot_id, CONVERSATION_MEMORY_FEATURE)
        return None
    except BillingLimitError as exc:
        return exc.code or DENIAL_UNVERIFIED
    except Exception as exc:
        # Cannot establish the entitlement -> treat as denied, never as
        # allowed: an outage must not become a free feature.
        logging.warning(
            "[ConversationMemory] entitlement check failed for chatbot_id=%s: %s",
            chatbot_id,
            exc,
        )
        return DENIAL_UNVERIFIED


def _label_words(query: str) -> list[str]:
    """Reduce a query to candidate label terms, in the stored normal form."""
    # Imported locally: a module-level import would pull the whole RAG stack
    # (and its provider client construction) into every importer of this
    # module, and rag_service imports back into here just as lazily.
    from app.services.rag_service import clean_query_words

    seen: list[str] = []
    for word in clean_query_words(query):
        normalized = normalize_label(word)
        if normalized and normalized not in seen:
            seen.append(normalized)
        if len(seen) >= MAX_KEYWORD_TERMS:
            break
    return seen


def remember_conversation_facts(
    chatbot_id: int,
    conversation_id: int | None,
    extracted_fields: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Persist this turn's extracted fields as conversation-scoped nodes.

    Blank, whitespace-only and ``None`` values are skipped -- an empty regex
    capture must not overwrite a good fact learned on an earlier turn.
    Returns the rows written (empty when there was nothing worth storing).
    """
    if not conversation_id or not extracted_fields:
        return []

    if not isinstance(extracted_fields, dict):
        # Producer contract break, not a customer input problem: log it rather
        # than let ``.items()`` raise into the reply path.
        logging.warning(
            "[ConversationMemory] extracted_fields must be a dict, got %s",
            type(extracted_fields).__name__,
        )
        return []

    stored: list[dict[str, Any]] = []
    for label, raw_value in extracted_fields.items():
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if not value or not normalize_label(label):
            continue
        try:
            row = upsert_conversation_fact(
                chatbot_id=chatbot_id,
                conversation_id=conversation_id,
                label=label,
                value=value[:MAX_FACT_VALUE_LEN],
            )
        except Exception as exc:
            # A memory write must never cost the customer their reply.
            logging.warning(
                "[ConversationMemory] failed to store %r for chatbot_id=%s "
                "conversation_id=%s: %s",
                label, chatbot_id, conversation_id, exc,
            )
            continue
        if row:
            stored.append(row)

    return stored


def _render_fact(row: dict[str, Any]) -> str:
    label = (row.get("label") or "").strip()
    value = (row.get("value") or "").strip()
    prefix = _LABEL_PHRASING.get(label)
    if prefix:
        return f"- {prefix} {value}."
    return f"- {label.capitalize()}: {value}"


def recall_conversation_facts(
    chatbot_id: int,
    conversation_id: int | None,
    query: str | None,
) -> list[str]:
    """Keyword lookup over this conversation's node labels.

    Returns rendered fact lines, or ``[]`` when there is no conversation, no
    usable query term, or no label match. Raises on a data-layer failure so the
    caller can decide -- ``retrieve_relevant_chunks`` degrades and logs.
    """
    if not conversation_id or not query:
        return []

    labels = _label_words(query)
    if not labels:
        return []

    rows = get_conversation_facts_by_labels(
        chatbot_id=chatbot_id,
        conversation_id=conversation_id,
        labels=labels,
    )
    return [_render_fact(row) for row in rows if row.get("value")]
