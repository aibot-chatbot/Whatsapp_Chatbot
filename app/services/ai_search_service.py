"""Optional Cloudflare AI Search retrieval over the tenant documents in R2.

This module is an *additive* retrieval source for chatbot knowledge. It never
replaces the local path in ``app/services/rag_service.py``: heading-aware
chunking, per-file keyword and vector matching, conversation memory, graph
facts and -- above all -- the exact menu-code lookup
(``find_chunks_for_exact_code``) all still run first and still win. A customer
typing a menu code must get that exact item, and a generic semantic search
cannot reproduce that.

WHY ``/search`` AND NEVER ``/ai-search``. AI Search exposes two query
endpoints. ``/search`` retrieves chunks; ``/ai-search`` retrieves *and
generates* on Workers AI. Generation there would happen outside this
application's AI provider path, so no row would land in ``ai_usage_logs`` and
the tenant would never be charged for those tokens. This repo already caught
the identical bug once: Cloudflare's OpenAI-compatible ``/compat`` endpoint was
rejected for AI Gateway because it would have changed the model string that
AI-credit billing prices from (see ``app/services/ai_gateway.py``). Generation
stays on the existing metered provider path; this module only fetches text.

THE TENANT BOUNDARY IS TWO CONTROLS, NOT ONE. The remote filter
(``ai_search_options.retrieval.filters.chatbot_id``) is a single, remote,
fail-open control whose every failure mode is silent and favours disclosure: a
code path that omits ``filters``, an attribute Cloudflare normalised
differently, an object indexed before metadata filtering existed and therefore
carrying no attributes at all, an integer sent where a string is stored, or a
future change to the filter shape. None of those raise; each just returns more
rows. So this module ships the filter *and* an application-side ownership
re-check: every returned chunk is attributed to a row in this tenant's own
``knowledge_files``, and a chunk that cannot be attributed is discarded rather
than returned. ``folder`` filtering -- Cloudflare's documented multi-tenant
pattern -- cannot isolate tenants here, because every knowledge key sits
directly under ``knowledge/``.

The unfiltered call is unreachable by construction: ``_post_search`` is the
only function that builds a URL or a body, it takes an already-validated tenant
value as its first argument, and it always writes that value into the filter.
There is no code path that can post without one.

THE SAME RE-CHECK IS ALSO THE WITHDRAWAL CONTROL. Cloudflare re-indexes the
bucket on a timer (``sync_interval``, six hours as configured), so a document's
vectors outlive its R2 object by up to that interval. Nothing in this
application can make Cloudflare forget sooner, and a metadata tombstone would
not help either: AI Search fingerprints content, so rewriting an object's
metadata without changing its body skips re-extraction entirely. What closes
that window is the re-check above. ``knowledge_service.delete_pdf_file``
hard-deletes the ``knowledge_files`` row in the same request that deletes the
object, so from that moment the stale chunk has no row to attribute it to and
is discarded here rather than returned. The set is therefore built from what
retrieval may *currently* use, not from what merely exists: a supporting source
the operator disabled is withdrawn here too, because the local path already
ignores it and this path must not be the one door it still answers through.

THE SWITCH IS OFF AND IS RE-READ PER CALL. Same reasoning as
``ai_gateway.py`` and ``cf_queue.py``: an operator must be able to stop
querying by changing a Fly secret, not by shipping a deploy. ``enabled()``
therefore touches the environment on every call and is never cached. It also
refuses to turn on halfway -- without the account id, the instance id and the
API token, every query would travel to an address that cannot authenticate.

NOTHING RAISES AND NOTHING SENSITIVE IS LOGGED. These calls sit in the live
customer-reply path, so a Cloudflare outage, a revoked token or a typo in an
instance id degrades this source to ``[]`` and is logged as a failure *type*
and HTTP status. The query carries customer message text and the results carry
tenant document content, so neither is ever logged, and neither is the token.

THE RESPONSE SHAPE IS NOT FULLY PINNED DOWN, SO AN EMPTY ANSWER IS LOUD.
Cloudflare documents a ``chunks`` array (``chunk.text`` with the source object
at ``chunk.item.key``) for the Workers binding, while the REST endpoint used
here is described only as "OpenAI compatible" and its literal body could not be
confirmed. ``_documents`` therefore accepts ``chunks`` or ``data``, nested
under ``result`` or bare, and ``_document_file_name`` reads ``item.key`` before
``filename``. This matters more than it looks: if the source key were only ever
at ``item.key`` and this code only read ``filename``, every chunk would be
unattributable, the ownership check would discard all of them, and the feature
would return ``[]`` forever while every health check stayed green. That failure
is now audible -- a 2xx response yielding no usable chunk logs the response's
key NAMES and an entry count, which is what separates "this parser does not
match the payload" from "this tenant has no matching documents".

RETRIEVAL OPTIONS. ``max_num_results`` is the caller's ``top_k`` (clamped to
the documented 1..50) so nothing is over-fetched, and ``match_threshold`` is
pinned to the local path's 0.45. ``retrieval_type`` is left at its "hybrid"
default and reranking is left off: reranking is a second model call, which this
four-second budget cannot afford, but it is the lever to reach for if recall
quality disappoints.

The account id is ``R2_ACCOUNT_ID``: the AI Search instance indexes the same
Cloudflare account's document bucket, and a second account-id variable would
only be one more thing to set wrong.
"""

import logging
import os
import re
from functools import lru_cache

import requests

from app.database.knowledge_file_repository import get_knowledge_files

logger = logging.getLogger(__name__)

_API_ROOT = "https://api.cloudflare.com/client/v4/accounts"

#: AI Search instances live under a namespace; "default" is the one the
#: dashboard creates and the only one this application uses.
_NAMESPACE = "default"

#: The label these chunks wear inside the prompt. It is deliberately one of the
#: labels ``build_prompt`` already explains to the model rather than a new one:
#: these really are the tenant's supporting documents, just fetched remotely,
#: and an unexplained label would be context the safety rules never mention.
SOURCE_LABEL = "Supporting document knowledge"

#: Four seconds. This sits inside a live customer reply that already costs
#: about seven, and it is consulted only when local retrieval found nothing --
#: so the reply is going out either way and a longer wait buys the customer
#: nothing they would notice. Four still leaves room for one slow round trip
#: rather than clipping a merely sluggish one.
DEFAULT_TIMEOUT_SECONDS = 4.0

#: Minimum vector similarity for a chunk to be retrieved at all (Cloudflare
#: defaults to 0.4). Pinned to the same 0.45 that ``_vector_matches_for_file``
#: passes to ``search_similar_chunks`` in rag_service, so remote and local
#: recall are comparable rather than accidentally different -- a tenant must
#: not get looser matches merely because the answer came from the remote path.
#: Note this filters on vector similarity, not on the fused hybrid score.
MATCH_THRESHOLD = 0.45

#: Cloudflare accepts 1..50 results per query and defaults to 10. Asking for
#: exactly what the caller will use beats over-fetching and trimming.
MAX_NUM_RESULTS_LIMIT = 50

#: Cloudflare account and instance ids are opaque identifiers. Anything else is
#: refused rather than interpolated into an authenticated API URL.
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

#: A tenant marker reaches R2 as an ``x-amz-meta-*`` header and is indexed as a
#: string, of which only the first 64 UTF-8 bytes are matched by a filter. The
#: same shape ``document_storage_service._TENANT_ID`` writes, so what is stored
#: and what is queried cannot drift apart.
_TENANT_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

_TRUTHY = ("1", "true", "yes", "on")


def _account_id() -> str:
    return os.getenv("R2_ACCOUNT_ID", "").strip()


def _instance_id() -> str:
    return os.getenv("AI_SEARCH_INSTANCE_ID", "").strip()


def _api_token() -> str:
    """Never logged, never returned to a caller."""
    return os.getenv("AI_SEARCH_API_TOKEN", "").strip()


def _timeout_seconds() -> float:
    """Seconds to wait for Cloudflare, falling back when the value is nonsense.

    A mistyped secret must not mean "wait forever" or "time out instantly".
    """
    raw = os.getenv("AI_SEARCH_TIMEOUT_SECONDS", "").strip()
    try:
        timeout = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_TIMEOUT_SECONDS


@lru_cache(maxsize=None)
def _warn_once(message: str) -> None:
    """Log a configuration problem once per process instead of per reply."""
    logger.warning(message)


def enabled() -> bool:
    """Whether AI Search should be consulted at all.

    Read from the environment on every call, never cached: an operator must be
    able to switch this off without waiting for a deploy.
    """
    if os.getenv("AI_SEARCH_ENABLED", "").strip().lower() not in _TRUTHY:
        return False
    if _account_id() and _instance_id() and _api_token():
        return True
    _warn_once(
        "AI_SEARCH_ENABLED is set but R2_ACCOUNT_ID, AI_SEARCH_INSTANCE_ID or "
        "AI_SEARCH_API_TOKEN is missing; Cloudflare AI Search stays off."
    )
    return False


def search_chunks(query, chatbot_id, top_k: int = 3) -> list[str]:
    """Chunks for one tenant, formatted exactly like local retrieval's.

    Returns ``[]`` for every failure -- disabled, unconfigured, unattributable,
    HTTP error, timeout, malformed response -- and never raises.
    """
    if not enabled():
        return []

    text = str(query or "").strip()
    if not text or top_k <= 0:
        return []

    tenant_value = _tenant_filter_value(chatbot_id)
    if tenant_value is None:
        # No filter can be built, so no query may be sent. Refusing here is
        # what makes the unfiltered call unreachable rather than merely
        # discouraged.
        logger.warning("Cloudflare AI Search skipped: no usable tenant filter value")
        return []

    owned_file_names = _owned_file_names(chatbot_id)
    if not owned_file_names:
        # Either the ownership lookup failed or this tenant owns no documents.
        # Both mean nothing coming back could be attributed, so there is no
        # point asking -- and no safe way to use an answer.
        return []

    envelope = _post_search(tenant_value, text, _max_num_results(top_k))
    if envelope is None:
        return []

    entries = _documents(envelope)
    chunks = []
    discarded = 0
    for document in entries:
        file_name = _document_file_name(document)
        if file_name is None or file_name not in owned_file_names:
            discarded += 1
            continue
        content = _document_text(document)
        if content:
            chunks.append(f"{SOURCE_LABEL}:\n{content}")

    if discarded:
        # Counts only. The chunk itself is another tenant's document text.
        logger.warning(
            "Cloudflare AI Search returned %d chunk(s) this chatbot does not own; discarded",
            discarded,
        )

    if not chunks:
        _warn_unusable_response(envelope, len(entries))
    logger.info("Cloudflare AI Search kept %d chunk(s)", min(len(chunks), top_k))

    # Cloudflare was asked for exactly this many, but the cap is re-applied
    # rather than trusted: a remote that ignored max_num_results must not be
    # able to widen the prompt.
    return chunks[:top_k]


def _max_num_results(top_k: int) -> int:
    """``top_k`` as a value the API will accept."""
    return max(1, min(int(top_k), MAX_NUM_RESULTS_LIMIT))


def _warn_unusable_response(envelope: dict, entry_count: int) -> None:
    """Say, once, that a 2xx response yielded nothing this code could use.

    "The parser does not match this payload" and "this tenant has no matching
    documents" both return [] and both look healthy, but only one is a bug.
    The response's key names are what tells them apart, and ``entries``
    separates "nothing parsed" (0, so a shape mismatch) from "parsed but all
    discarded" (>0, so the ownership check did its job).

    Key NAMES only, never values: a value is tenant document text.
    """
    shape = _key_names(envelope)
    result = envelope.get("result")
    if isinstance(result, dict):
        shape += " result:" + _key_names(result)
    _warn_once(
        f"Cloudflare AI Search returned no usable chunk(s) [{shape} entries={entry_count}]. "
        "If entries=0 on a healthy instance, this response shape is not one this "
        "parser recognises."
    )


def _key_names(container: dict) -> str:
    """The container's key names, sanitized for a log line.

    Bounded and character-restricted because a response key is still remote
    input: an unbounded one could pad a log line or smuggle a newline into it.
    """
    names = sorted(
        name for name in container
        if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", name)
    )
    return ",".join(names[:10]) or "no-usable-keys"


def _tenant_filter_value(chatbot_id) -> str | None:
    """The filter value for one tenant, or None when it cannot be expressed.

    Built only from the chatbot id the caller already resolved and authorized,
    never from anything carried in the customer's message.
    """
    if chatbot_id is None:
        return None
    value = str(chatbot_id).strip()
    return value if _TENANT_ID_PATTERN.fullmatch(value) else None


def _retrievable(row) -> bool:
    """Whether local retrieval would still search this ``knowledge_files`` row.

    Remote attribution has to mirror local eligibility, or this path becomes
    the one door a withdrawn document still answers through. Local retrieval
    loads the active primary on its own path -- ``is_active``, which
    ``toggle_supporting_knowledge`` refuses to disable -- plus the supporting
    sources the operator left enabled.

    Only an explicit ``False`` withdraws a row. A missing or null flag predates
    the column rather than meaning "switched off", which is the same reading
    ``resolve_knowledge_role`` and the knowledge routes already use.
    """
    return bool(row.get("is_active")) or row.get("is_enabled") is not False


def _owned_file_names(chatbot_id) -> set[str] | None:
    """Names this tenant can currently be answered from, or None if unknown.

    The rows come from ``knowledge_files`` scoped to this chatbot id, which is
    the same scoping the rest of retrieval uses. None means the check could not
    run -- and a chunk that cannot be checked is discarded, never returned.

    A document the tenant deleted has no row at all, and a supporting source
    they disabled is filtered out by ``_retrievable``; either way its chunks
    stop being attributable the moment the tenant acts, rather than whenever
    Cloudflare next syncs the bucket.
    """
    try:
        rows = get_knowledge_files(chatbot_id)
    except Exception as exc:  # noqa: BLE001 - an unavailable check must close, not raise
        logger.warning(
            "Cloudflare AI Search ownership check unavailable: %s", type(exc).__name__
        )
        return None

    return {
        str(row.get("file_name")).strip()
        for row in rows or []
        if isinstance(row, dict) and row.get("file_name") and _retrievable(row)
    }


def _post_search(tenant_value: str, query: str, max_num_results: int) -> dict | None:
    """POST the one retrieval request. Returns the envelope, or None.

    The only place in this module that builds a URL or a body, and it always
    writes ``tenant_value`` into ``ai_search_options.retrieval.filters``. A
    caller cannot ask for an unfiltered search because there is no argument
    that would express one.
    """
    account = _account_id()
    instance = _instance_id()
    if not _ID_PATTERN.fullmatch(account) or not _ID_PATTERN.fullmatch(instance):
        _warn_once(
            "R2_ACCOUNT_ID or AI_SEARCH_INSTANCE_ID is not a usable Cloudflare "
            "identifier; Cloudflare AI Search stays off."
        )
        return None

    # Two endpoint forms appear in current Cloudflare docs: this namespaced one
    # (from the AI Search get-started API guide) and a shorter
    # ".../ai-search/instances/{instance}/search" (from a later changelog). If
    # the first live query 404s, the shorter form is the thing to try -- it is
    # a one-line change here rather than a setting, because only one of the two
    # is ever correct and an operator should not have to guess which.
    url = (
        f"{_API_ROOT}/{account}/ai-search/namespaces/{_NAMESPACE}"
        f"/instances/{instance}/search"
    )
    payload = {
        "messages": [{"role": "user", "content": query}],
        "ai_search_options": {
            "retrieval": {
                # The value is a string on purpose: R2 custom metadata is
                # stored as strings, and an integer here would quietly match
                # nothing.
                "filters": {"chatbot_id": tenant_value},
                "max_num_results": max_num_results,
                "match_threshold": MATCH_THRESHOLD,
                # retrieval_type is left unset: it defaults to "hybrid"
                # (vector + keyword), which is the closest match to the local
                # path, where keyword and vector scoring also run side by side.
                # Reranking is likewise left off -- it is a second model call
                # and this budget is four seconds -- but it is the lever to
                # reach for if recall quality proves poor.
            }
        },
    }

    try:
        response = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {_api_token()}",
                "Content-Type": "application/json",
            },
            timeout=_timeout_seconds(),
        )
        status = response.status_code
        if not 200 <= status < 300:
            logger.warning("Cloudflare AI Search returned HTTP %s", status)
            return None
        envelope = response.json()
    except Exception as exc:  # noqa: BLE001 - a transport failure must not escape
        logger.warning("Cloudflare AI Search failed: %s", type(exc).__name__)
        return None

    if not isinstance(envelope, dict):
        logger.warning("Cloudflare AI Search returned an unexpected envelope")
        return None
    if envelope.get("success") is False:
        # Cloudflare's error codes name the failure kind; they carry neither
        # the query nor the token.
        codes = [
            error.get("code")
            for error in envelope.get("errors") or []
            if isinstance(error, dict)
        ]
        logger.warning("Cloudflare AI Search rejected the query: %s", codes or "unspecified")
        return None
    return envelope


def _documents(envelope: dict) -> list:
    """The retrieved-chunk array out of a search response.

    Deliberately permissive about where that array lives. Cloudflare documents
    a ``chunks`` array for the Workers binding, while the REST endpoint is
    described only as "OpenAI compatible", whose pages are ``data`` arrays --
    and the REST body could not be confirmed literally. Reading both (nested
    under ``result`` or bare) costs four lines; guessing wrong costs a feature
    that returns nothing forever while every health check stays green.
    """
    result = envelope.get("result")
    if isinstance(result, list):
        return result
    for container in (result, envelope):
        if not isinstance(container, dict):
            continue
        for key in ("chunks", "data"):
            entries = container.get(key)
            if isinstance(entries, list):
                return entries
    return []


def _document_file_name(document) -> str | None:
    """The owning document's name, or None when it carries no attribution.

    ``item.key`` comes first because that is what the documented chunk shape
    uses for the source object, and it is the authoritative one -- a sibling
    ``filename`` never overrides it. The value is the R2 object key
    (``knowledge/bot_<id>_<uuid>_<name>``) while ``knowledge_files`` stores
    only the final segment, so the folder prefix is dropped before comparing.

    An object indexed before tenant metadata existed carries no key at all;
    that is the fail-open case this returns None for, and a None is discarded
    by the caller rather than trusted.
    """
    if not isinstance(document, dict):
        return None

    item = document.get("item")
    candidates = [
        item.get("key") if isinstance(item, dict) else None,
        document.get("filename"),
    ]
    for key in ("attributes", "metadata"):
        container = document.get(key)
        candidates.append(container.get("filename") if isinstance(container, dict) else None)

    for raw in candidates:
        if not isinstance(raw, str):
            continue
        name = raw.rsplit("/", 1)[-1].strip()
        if name:
            return name
    return None


def _document_text(document) -> str:
    """The retrieved text of one chunk, whichever shape it arrived in.

    ``text`` is the documented chunk field; ``content`` is the OpenAI-style
    alternative, which may be a string, one part, or a list of parts.
    """
    if not isinstance(document, dict):
        return ""

    text = document.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    content = document.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return ""

    parts = []
    for part in content:
        if isinstance(part, str):
            parts.append(part)
        elif isinstance(part, dict) and isinstance(part.get("text"), str):
            parts.append(part["text"])
    return "\n".join(part for part in parts if part).strip()
