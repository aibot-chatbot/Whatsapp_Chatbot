"""Prove, against the live Cloudflare instance, that AI Search keeps tenants apart.

``app/services/ai_search_service.py`` has a full unit-test suite, but every one
of those tests answers a mock. That module's parser was originally written for a
response shape Cloudflare does not send, and a mock built from the same belief
agreed with it perfectly. ``search_chunks`` -- its filter construction, its
application-side ownership re-check and its timeout -- has never once executed
against the real instance. This script is the thing that can.

It calls the application's own code rather than a hand-rolled HTTP request,
because a re-implementation here would be free to share the very wrong belief
the unit tests could not catch.

READ-ONLY. Search queries only: no writes, no index changes, no deletes, no R2.

THE ONE RULE IT ASSERTS. A tenant may not keep more chunks than Cloudflare
returned chunks that tenant owns. That single rule is the whole boundary: it
covers the orphan chatbots (present in the index, no ``knowledge_files`` rows,
so anything kept is a leak) and the nonexistent id 999999 (nothing to own, so
anything kept is a leak) exactly as it covers a normal tenant.

WHY IT ALSO CALLS PRIVATE HELPERS. ``search_chunks`` returns formatted text
carrying no attribution, so the only way to report *which* object each chunk
came from -- without re-implementing the request -- is to ask the module's own
``_post_search`` / ``_documents`` / ``_document_file_name``. Same URL, same
body, same parser, which is the entire point. Each tenant therefore costs two
read-only searches: the real entry point, and one diagnostic look at what
Cloudflare handed it.

WHY IT PRINTS KEYS AND NEVER TEXT. Chunk text is tenant document content. The
object key and the counts answer the boundary question on their own, and the
API token is never printed either.

Usage:

    python scripts/smoke_test_ai_search.py
    python scripts/smoke_test_ai_search.py --query "opening hours" --top-k 5

Needs the project's ``.env``: importing the real service pulls in the ``app``
package, so the usual application variables must be present as well as the six
this script names for itself.

Exit codes: 0 clean, 1 a tenant received a chunk it does not own, 2 a boundary
anomaly the application contained -- or a query that exercised nothing.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: Ground truth measured against the live index. Chatbots that appear in the
#: index *and* hold ``knowledge_files`` rows: retrieval should work for these.
OWNING_CHATBOT_IDS = (11, 20, 52, 53, 55)

#: Chatbots whose documents are in the index but which hold no
#: ``knowledge_files`` rows. Cloudflare answers for them; the application must
#: discard every chunk, because nothing can be attributed. A non-zero result
#: here is a genuine finding, not a pass.
ORPHAN_CHATBOT_IDS = (1, 2, 25, 29, 46, 50)

#: Negative control: no such chatbot, so Cloudflare must return nothing.
ABSENT_CHATBOT_ID = 999999

#: Without any one of these the service silently answers ``[]`` for every
#: tenant, and a silent ``[]`` reads as a clean pass. Named individually so the
#: operator is told which one to set rather than that "something" is missing.
REQUIRED_ENV = (
    "AI_SEARCH_ENABLED",
    "AI_SEARCH_INSTANCE_ID",
    "AI_SEARCH_API_TOKEN",
    "R2_ACCOUNT_ID",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
)

#: Deliberately broad: this test cares whether the pipe works, not whether one
#: phrase is well chosen. If it matches nothing anywhere the run reports that it
#: proved nothing and asks for a different --query rather than passing.
DEFAULT_QUERY = "what services, prices and opening hours are offered"

#: Ten is what the live call was confirmed with. ``search_chunks`` defaults to
#: three; more results give the ownership check more to discard.
DEFAULT_TOP_K = 10


def missing_env(environ) -> list[str]:
    """The required variables that are unset or blank, in declared order."""
    return [name for name in REQUIRED_ENV if not str(environ.get(name, "")).strip()]


def probe_tenant(service, chatbot_id: int, query: str, top_k: int) -> dict:
    """One tenant's boundary evidence. Two read-only searches, no writes."""
    kept = service.search_chunks(query, chatbot_id, top_k=top_k)

    owned = service._owned_file_names(chatbot_id)
    owned_names = owned or set()

    tenant_value = service._tenant_filter_value(chatbot_id)
    envelope = (
        service._post_search(tenant_value, query, service._max_num_results(top_k))
        if tenant_value is not None
        else None
    )
    # `_post_search` answers None for a transport failure exactly as it does for
    # an unbuildable filter, and conflating the two reports a leak that is not
    # one: on a ReadTimeout the real search keeps its chunks while the
    # diagnostic call returns nothing to compare them against, so the
    # kept-vs-remote arithmetic accuses the application of leaking its own
    # tenant's data. Observed live 2026-09-21 against chatbot 11.
    diagnostic_ran = envelope is not None

    entries = service._documents(envelope) if envelope is not None else []
    keys = [service._document_file_name(entry) for entry in entries]
    foreign = [key for key in keys if key is None or key not in owned_names]

    return {
        "chatbot_id": chatbot_id,
        "ownership_check_ran": owned is not None,
        "diagnostic_ran": diagnostic_ran,
        "owned_files": len(owned_names),
        "remote_chunks": len(entries),
        "kept_chunks": len(kept),
        "discarded": len(foreign),
        "keys": keys,
    }


def leak_reason(result: dict) -> str | None:
    """Why this result is a cross-tenant leak, or None when it is not.

    ponytail: this compares two separate searches, so it assumes the index
    answers the same filter the same way twice -- true for a vector-only index
    with caching off, but a re-index between the two calls could report a leak
    that is really drift. Re-run before believing a lone failure; the fix, if it
    ever bites, is for ``search_chunks`` to return attribution instead of bare
    text so one call can answer both questions.
    """
    if not result.get("diagnostic_ran", True):
        # No second opinion to compare against, so there is nothing to conclude.
        # anomaly_reasons reports this instead, which exits 2 -- "could not
        # verify" -- rather than 1. A boundary harness that calls a timeout a
        # leak is a harness people stop believing.
        return None

    owned_chunks = result["remote_chunks"] - result["discarded"]
    if result["kept_chunks"] > owned_chunks:
        return (
            f"kept {result['kept_chunks']} chunk(s) but only {owned_chunks} of the "
            f"{result['remote_chunks']} Cloudflare returned belong to this chatbot"
        )
    return None


def anomaly_reasons(result: dict, expect_owner: bool) -> list[str]:
    """Findings the application contained, plus the ways a pass proves nothing."""
    notes = []
    if not result.get("diagnostic_ran", True):
        notes.append(
            "the diagnostic search failed (see the warning above), so the chunks "
            "this tenant kept could not be compared against what Cloudflare "
            "returned; re-run before drawing any conclusion"
        )
    if not result["ownership_check_ran"]:
        notes.append(
            "the ownership check could not run, so every chunk would be discarded "
            "and a pass here proves nothing"
        )
    if expect_owner and result["owned_files"] == 0:
        notes.append(
            "expected knowledge_files rows but found none; ground truth has drifted"
        )
    if expect_owner and result["discarded"]:
        notes.append(
            f"Cloudflare returned {result['discarded']} chunk(s) this chatbot does "
            "not own; the application discarded them"
        )
    if result["chatbot_id"] == ABSENT_CHATBOT_ID and result["remote_chunks"]:
        notes.append(
            f"Cloudflare returned {result['remote_chunks']} chunk(s) for a chatbot id "
            "that does not exist; the remote filter is not filtering"
        )
    if (
        not expect_owner
        and result["chatbot_id"] != ABSENT_CHATBOT_ID
        and not result["remote_chunks"]
    ):
        notes.append(
            "Cloudflare returned nothing, so the ownership check was not exercised"
        )
    return notes


def run(service, query: str, top_k: int) -> tuple[int, list[str]]:
    """Probe every chatbot id and return ``(exit code, report lines)``."""
    lines = []
    leaked = False
    flagged = False
    owner_remote_chunks = 0

    for chatbot_id in OWNING_CHATBOT_IDS + ORPHAN_CHATBOT_IDS + (ABSENT_CHATBOT_ID,):
        expect_owner = chatbot_id in OWNING_CHATBOT_IDS
        result = probe_tenant(service, chatbot_id, query, top_k)
        if expect_owner:
            owner_remote_chunks += result["remote_chunks"]

        leak = leak_reason(result)
        notes = anomaly_reasons(result, expect_owner)
        leaked = leaked or leak is not None
        flagged = flagged or bool(notes)

        label = "LEAK" if leak else ("anomaly" if notes else "clean")
        lines.append(
            f"  [{label:>7}] chatbot {result['chatbot_id']:<6} "
            f"owns {result['owned_files']:>2} file(s) "
            f"| cloudflare {result['remote_chunks']:>2} "
            f"| kept {result['kept_chunks']:>2} "
            f"| discarded {result['discarded']:>2}"
        )
        if result["keys"]:
            names = ", ".join(key if key else "<no key>" for key in result["keys"])
            lines.append(f"            keys: {names}")
        for note in ([leak] if leak else []) + notes:
            lines.append(f"            -> {note}")

    if not owner_remote_chunks:
        flagged = True
        lines.append(
            "  [anomaly] no owning chatbot matched this query, so nothing was "
            "exercised; re-run with a different --query"
        )

    if leaked:
        return 1, lines
    return (2, lines) if flagged else (0, lines)


VERDICTS = {
    0: "PASS: no chatbot received a chunk it does not own.",
    1: "FAIL: a chatbot received a chunk it does not own.",
    2: "FAIL: boundary anomalies above; the tenant boundary is not proven.",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only tenant-boundary check of ai_search_service against the live "
            "Cloudflare AI Search instance."
        )
    )
    parser.add_argument("--query", default=DEFAULT_QUERY, help="the search text to send")
    parser.add_argument(
        "--top-k", type=int, default=DEFAULT_TOP_K, help="results to request per tenant"
    )
    args = parser.parse_args()

    if args.top_k < 1:
        print(f"--top-k must be at least 1, got {args.top_k}")
        return 1

    from dotenv import load_dotenv

    load_dotenv()

    absent = missing_env(os.environ)
    if absent:
        print(
            "Cannot run: the service would answer [] for every tenant, "
            "which reads as a pass."
        )
        for name in absent:
            print(f"  missing: {name}")
        return 1

    try:
        from app.services import ai_search_service as service
    except Exception as exc:  # noqa: BLE001 - name the cause, do not dump a traceback
        print(f"Could not import app.services.ai_search_service: {type(exc).__name__}: {exc}")
        print("This script runs the real service, which loads the app package. Run it")
        print("from a checkout with the project's .env present.")
        return 1

    if not service.enabled():
        print(
            "ai_search_service.enabled() is False with "
            f"AI_SEARCH_ENABLED={os.getenv('AI_SEARCH_ENABLED', '')!r}. "
            "Set it to one of 1/true/yes/on."
        )
        return 1

    print("Cloudflare AI Search tenant-boundary smoke test (read-only)")
    print(f"Instance : {os.getenv('AI_SEARCH_INSTANCE_ID', '').strip()}")
    print(f"Query    : {args.query!r}")
    print(f"Top-k    : {args.top_k}")
    print("-" * 72)

    code, lines = run(service, args.query, args.top_k)
    for line in lines:
        print(line)

    print("-" * 72)
    print(VERDICTS[code])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
