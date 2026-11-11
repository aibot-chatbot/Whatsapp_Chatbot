"""Unified website knowledge ingestion.

Composes the four website-scraping stages that are otherwise exposed as four
separate HTTP calls in ``app/routes/knowledge_routes.py``:

===========  ===============================  ==================================
Stage        Service function                 Equivalent single-stage endpoint
===========  ===============================  ==================================
``analyze``  ``discover_website_links``       ``POST /api/knowledge/scrape-analyze``
``scrape``   ``scrape_pages``                 ``POST /api/knowledge/scrape-batch``
``extract``  ``extract_business_knowledge``   ``POST /api/knowledge/scrape-extract``
``embed``    ``save_refined_knowledge_chunks``  ``POST /api/knowledge/scrape-embed``
===========  ===============================  ==================================

Those four routes keep working unchanged; this module reuses the very same
service functions rather than duplicating them.

Progress vocabulary follows ``.omx/plans/guided-chatbot-creation-architecture.md``
(§2b): ``succeeded`` / ``partial`` / ``failed``, per-phase truthful status, and
**no roll-back of already-ingested sources when a sibling source fails**. The
doc's ``queued`` / ``running`` states are deliberately absent — this runs
synchronously inside the request, so a returned report is always terminal. Its
phase names (``extracting``/``embedding``/``graph``/``finishing``) describe the
PDF job runner, not the website chain, so the four route-derived stage names
above are used instead.

Scope: website sources only. Uploaded documents go through
``POST /upload-pdf`` (``app/views.py:98``), a separate path with a different
request encoding and no per-stage seams.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Iterable, Sequence

from app.services import knowledge_service
from app.services.billing_guard import BillingLimitError

# ── Stage identifiers, in pipeline order ──────────────────────────────────
STAGE_ANALYZE: Final[str] = "analyze"
STAGE_SCRAPE: Final[str] = "scrape"
STAGE_EXTRACT: Final[str] = "extract"
STAGE_EMBED: Final[str] = "embed"
STAGE_ORDER: Final[tuple[str, ...]] = (
    STAGE_ANALYZE,
    STAGE_SCRAPE,
    STAGE_EXTRACT,
    STAGE_EMBED,
)

# ── Progress vocabulary ───────────────────────────────────────────────────
STATUS_PENDING: Final[str] = "pending"
STATUS_SKIPPED: Final[str] = "skipped"
STATUS_SUCCEEDED: Final[str] = "succeeded"
STATUS_PARTIAL: Final[str] = "partial"
STATUS_FAILED: Final[str] = "failed"
PHASE_DONE: Final[str] = "done"

# ── Bounds. This endpoint runs synchronously inside one HTTP request, so the
# work it can be asked to do must be capped or a single call can hold a
# gunicorn worker open indefinitely. ──────────────────────────────────────
MAX_SOURCES_PER_REQUEST: Final[int] = 10
DEFAULT_MAX_PAGES: Final[int] = 5
# discover_website_links already truncates to 20 (knowledge_service.py:541).
MAX_PAGES_CEILING: Final[int] = 20

ALLOWED_URL_SCHEMES: Final[tuple[str, ...]] = ("http://", "https://")

ERROR_SCRAPE_FAILED: Final[str] = "scrape_failed"
ERROR_EXTRACT_FAILED: Final[str] = "extract_failed"
ERROR_EMBED_FAILED: Final[str] = "embed_failed"


# ── Input validation (trust boundary) ─────────────────────────────────────


def _is_http_url(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower().startswith(
        ALLOWED_URL_SCHEMES
    )


def _require_http_url(value: str) -> str:
    if not _is_http_url(value):
        raise ValueError(
            f"Invalid URL '{value}'. URLs must start with http:// or https://"
        )
    return value.strip()


def _dedupe(values: Iterable[str]) -> list[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def _normalize_max_pages(raw: Any) -> int:
    if raw is None:
        return DEFAULT_MAX_PAGES
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ValueError("'max_pages' must be a positive integer.")
    return min(raw, MAX_PAGES_CEILING)


def _normalize_page_urls(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("'urls' must be a list of URLs when provided.")
    cleaned = [_require_http_url(candidate) for candidate in raw]
    unique = _dedupe(cleaned)
    if not unique:
        raise ValueError("'urls' must contain at least one URL when provided.")
    # The analyze stage is skipped for a caller-supplied page list, so
    # max_pages never gets a chance to bound it. Without this the ceiling is
    # bypassed entirely and one source can be asked to fetch arbitrarily many
    # pages synchronously. Rejected rather than truncated, so the caller is
    # never silently given less than it asked for.
    if len(unique) > MAX_PAGES_CEILING:
        raise ValueError(
            f"At most {MAX_PAGES_CEILING} pages can be ingested per source; "
            f"{len(unique)} were supplied in 'urls'."
        )
    return unique


def _normalize_file_name(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("'file_name' must be a non-empty string when provided.")
    return raw.strip()


def _normalize_source(raw: Any) -> dict:
    """Validate one caller-supplied source into a canonical dict.

    Accepts either a bare URL string or an object of the shape::

        {"url": str,
         "urls": [str, ...]      | None,   # skips link discovery when present
         "discover_links": bool  | None,
         "max_pages": int        | None,
         "file_name": str        | None}
    """
    source = {"url": raw} if isinstance(raw, str) else raw
    if not isinstance(source, dict):
        raise ValueError(
            "Each source must be a URL string or an object containing a 'url'."
        )

    url = source.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Each source requires a non-empty 'url'.")

    return {
        "url": _require_http_url(url),
        "urls": _normalize_page_urls(source.get("urls")),
        "discover_links": bool(source.get("discover_links", False)),
        "max_pages": _normalize_max_pages(source.get("max_pages")),
        "file_name": _normalize_file_name(source.get("file_name")),
    }


def _normalize_sources(sources: Any) -> list[dict]:
    if not isinstance(sources, list) or not sources:
        raise ValueError("'sources' must be a non-empty list of website sources.")
    if len(sources) > MAX_SOURCES_PER_REQUEST:
        raise ValueError(
            f"At most {MAX_SOURCES_PER_REQUEST} sources can be ingested per "
            f"request; {len(sources)} were supplied."
        )
    return [_normalize_source(source) for source in sources]


# ── Per-stage progress records ────────────────────────────────────────────


def _stage_entry(name: str, status: str, **detail: Any) -> dict:
    return {"name": name, "status": status, "detail": detail}


def _derive_file_name(primary_url: str, page_count: int) -> str:
    """Mirror scrape_website_urls_batch's naming (knowledge_service.py:566)."""
    if page_count > 1:
        return f"{primary_url} (+{page_count - 1} pages)"
    return primary_url


def _finish(
    url: str,
    stages: Sequence[dict],
    *,
    file_name: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    error_details: dict | None = None,
) -> dict:
    """Build the terminal report for one source.

    Stages the run never reached are reported as ``skipped`` so the caller can
    always see exactly how far the source got.
    """
    completed = list(stages)
    padded = completed + [
        _stage_entry(name, STATUS_SKIPPED) for name in STAGE_ORDER[len(completed) :]
    ]

    statuses = {stage["status"] for stage in padded}
    if error_code or STATUS_FAILED in statuses:
        status = STATUS_FAILED
    elif STATUS_PARTIAL in statuses:
        status = STATUS_PARTIAL
    else:
        status = STATUS_SUCCEEDED

    failed_stage = next(
        (stage["name"] for stage in padded if stage["status"] == STATUS_FAILED), None
    )

    return {
        "url": url,
        "status": status,
        "phase": failed_stage or PHASE_DONE,
        "file_name": file_name,
        "error_code": error_code,
        "error_message": error_message,
        "error_details": error_details,
        "stages": padded,
    }


# ── The four stages ───────────────────────────────────────────────────────


def _run_analyze(source: dict) -> tuple[list[str], dict]:
    """Resolve the set of pages to scrape. Returns (page_urls, stage_entry).

    Link discovery is best-effort: if it fails we still ingest the source URL
    itself rather than losing the whole source.
    """
    url = source["url"]

    if source["urls"] is not None:
        return source["urls"], _stage_entry(
            STAGE_ANALYZE,
            STATUS_SKIPPED,
            reason="page list supplied by caller",
            selected_pages=len(source["urls"]),
        )

    if not source["discover_links"]:
        return [url], _stage_entry(
            STAGE_ANALYZE,
            STATUS_SKIPPED,
            reason="link discovery not requested",
            selected_pages=1,
        )

    try:
        discovered = knowledge_service.discover_website_links(url) or []
    except Exception as exc:
        logging.warning("[Ingest] Link discovery failed for %s: %s", url, exc)
        return [url], _stage_entry(
            STAGE_ANALYZE,
            STATUS_PARTIAL,
            discovered_pages=0,
            selected_pages=1,
            error=str(exc),
        )

    selected = _dedupe(link for link in discovered if _is_http_url(link))
    selected = selected[: source["max_pages"]] or [url]
    return selected, _stage_entry(
        STAGE_ANALYZE,
        STATUS_SUCCEEDED,
        discovered_pages=len(discovered),
        selected_pages=len(selected),
    )


def _run_scrape(page_urls: Sequence[str]) -> tuple[list[dict], dict]:
    """Fetch every page. Returns (pages, stage_entry).

    Each page is ``{"url": str, "content": str}``; pages that failed are
    reported in the stage detail instead of aborting the source.
    """
    pages, failures = knowledge_service.scrape_pages(page_urls)

    if not pages:
        return [], _stage_entry(
            STAGE_SCRAPE, STATUS_FAILED, scraped_pages=0, failed_pages=failures
        )

    return pages, _stage_entry(
        STAGE_SCRAPE,
        STATUS_PARTIAL if failures else STATUS_SUCCEEDED,
        scraped_pages=len(pages),
        failed_pages=failures,
    )


def _run_extract(combined_text: str, chatbot_id: int) -> tuple[str, dict]:
    """Refine the scraped text with the LLM. Returns (text_to_embed, stage_entry).

    A refinement that yields nothing falls back to the raw scraped text: the
    network fetch already succeeded and discarding it would lose real work.
    """
    from app.services.chat_pipeline_service import scan_client_page

    # The upload scan (plan A4) runs before the extraction AI.
    combined_text = scan_client_page(combined_text, chatbot_id, source="website")
    refined = knowledge_service.extract_business_knowledge(
        combined_text, chatbot_id=chatbot_id
    )

    if refined and refined.strip():
        return refined, _stage_entry(
            STAGE_EXTRACT, STATUS_SUCCEEDED, characters=len(refined)
        )

    return combined_text, _stage_entry(
        STAGE_EXTRACT,
        STATUS_PARTIAL,
        characters=len(combined_text),
        fallback="raw_scraped_text",
    )


def _run_source(source: dict, chatbot_id: int, company_id: int | None) -> dict:
    """Run all four stages for one source. Never raises — every failure is
    reported in the returned record so sibling sources still get ingested."""
    url = source["url"]
    stages: list[dict] = []

    page_urls, analyze_stage = _run_analyze(source)
    stages.append(analyze_stage)

    pages, scrape_stage = _run_scrape(page_urls)
    stages.append(scrape_stage)
    if not pages:
        failures = scrape_stage["detail"].get("failed_pages", [])
        return _finish(
            url,
            stages,
            error_code=ERROR_SCRAPE_FAILED,
            error_message=_describe_failures(failures),
            error_details={"failed_pages": failures},
        )

    combined_text = "\n\n".join(page["content"] for page in pages)
    try:
        text_to_embed, extract_stage = _run_extract(combined_text, chatbot_id)
    except Exception as exc:
        logging.error("[Ingest] Knowledge extraction failed for %s: %s", url, exc)
        stages.append(_stage_entry(STAGE_EXTRACT, STATUS_FAILED, error=str(exc)))
        return _finish(
            url, stages, error_code=ERROR_EXTRACT_FAILED, error_message=str(exc)
        )
    stages.append(extract_stage)

    primary_url = pages[0]["url"]
    file_name = source["file_name"] or _derive_file_name(primary_url, len(pages))
    try:
        result = knowledge_service.save_refined_knowledge_chunks(
            text_content=text_to_embed,
            file_name=file_name,
            primary_url=primary_url,
            chatbot_id=chatbot_id,
            # Without company_id the storage quota check inside
            # save_refined_knowledge_chunks (knowledge_service.py:673-674) is
            # silently skipped.
            company_id=company_id,
        )
    except BillingLimitError as exc:
        logging.warning(
            "[Ingest] Billing limit reached while embedding %s: %s", url, exc
        )
        stages.append(_stage_entry(STAGE_EMBED, STATUS_FAILED, error=str(exc)))
        return _finish(
            url,
            stages,
            error_code=exc.code or ERROR_EMBED_FAILED,
            error_message=str(exc),
            error_details=exc.details,
        )
    except Exception as exc:
        logging.error("[Ingest] Failed to embed %s: %s", url, exc)
        stages.append(_stage_entry(STAGE_EMBED, STATUS_FAILED, error=str(exc)))
        return _finish(
            url, stages, error_code=ERROR_EMBED_FAILED, error_message=str(exc)
        )

    saved_name = (result or {}).get("file_name") or file_name
    stages.append(_stage_entry(STAGE_EMBED, STATUS_SUCCEEDED, file_name=saved_name))
    return _finish(url, stages, file_name=saved_name)


def _describe_failures(failures: Sequence[dict]) -> str:
    if not failures:
        return "No page could be scraped."
    return "; ".join(f"{f['url']}: {f['error']}" for f in failures)


# ── Public entry point ────────────────────────────────────────────────────


def ingest_website_sources(
    sources: Any,
    chatbot_id: int,
    company_id: int | None = None,
) -> dict:
    """Ingest every website source end to end and report per-stage progress.

    Args:
        sources: List of URL strings and/or source objects (see _normalize_source).
        chatbot_id: Target chatbot. The caller must already have verified
            access to it via verify_chatbot_access.
        company_id: Owning company, forwarded so the per-write storage quota
            check actually runs.

    Returns:
        A terminal report::

            {"chatbot_id": int,
             "status": "succeeded" | "partial" | "failed",
             "totals": {"requested": int, "succeeded": int,
                        "partial": int, "failed": int},
             "sources": [ …one record per source, each with a "stages" list… ]}

    Raises:
        ValueError: the request body is malformed (validated before any work).
    """
    normalized = _normalize_sources(sources)

    results = [_run_source(source, chatbot_id, company_id) for source in normalized]

    totals = {
        "requested": len(results),
        "succeeded": sum(1 for r in results if r["status"] == STATUS_SUCCEEDED),
        "partial": sum(1 for r in results if r["status"] == STATUS_PARTIAL),
        "failed": sum(1 for r in results if r["status"] == STATUS_FAILED),
    }

    if totals["failed"] == len(results):
        overall = STATUS_FAILED
    elif totals["failed"] or totals["partial"]:
        overall = STATUS_PARTIAL
    else:
        overall = STATUS_SUCCEEDED

    return {
        "chatbot_id": chatbot_id,
        "status": overall,
        "totals": totals,
        "sources": results,
    }


def summarize_report(report: dict) -> str:
    """One-line human summary for the response envelope's `message`."""
    totals = report["totals"]
    if report["status"] == STATUS_SUCCEEDED:
        return f"Ingested {totals['succeeded']} of {totals['requested']} sources."
    if report["status"] == STATUS_FAILED:
        return f"Failed to ingest any of the {totals['requested']} sources."
    return (
        f"Ingested {totals['succeeded'] + totals['partial']} of "
        f"{totals['requested']} sources; {totals['failed']} failed."
    )
