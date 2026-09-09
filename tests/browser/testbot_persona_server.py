"""Live Flask server for the ``frontend/testbot.html`` persona browser e2e.

Why this exists instead of ``platform-admin-static-server.js``
-------------------------------------------------------------
The sibling browser specs serve ``frontend/`` statically and mock ``/api/**``
in the browser.  That convention cannot express this acceptance criterion: if
``POST /api/testbot/chat`` is answered by a canned string in ``page.route``,
the spec proves only that the page renders whatever the server said.  It
proves nothing about whether the *derived persona* reached the reply, which is
the entire feature under test.

So this harness serves the REAL application instead.  ``create_app()`` already
mounts ``frontend/`` at the root origin (``static_url_path=""``), so the page
and the API share an origin and ``authenticatedFetch``'s relative URLs work
untouched.  A request from the browser travels the production path:

    testbot.html -> POST /api/testbot/chat -> ai_router.generate_response
      -> call_provider -> prepare_chat_prompt -> rag_service.build_prompt
      -> provider

Exactly two boundaries are doubled, and they are the same two the pytest suite
doubles, at the same seams: Supabase, and the LLM provider.  Everything between
the HTTP request and the prompt is the real code.

MONEY: no billed call can leave this process.  ``_serving_stack`` replaces
``openrouter_service._request`` with the grounded stub, makes
``deepseek_service._request`` raise so an accidental failover cannot become a
real call, and makes ``ai_router.generate_system_response`` raise.  Running
this harness costs nothing.

Run it directly:

    ./.venv/Scripts/python.exe tests/browser/testbot_persona_server.py

Control surface (test-only, never mounted by ``run.py``):

    GET  /__e2e__/health              -> {"ready": true, "scenario": <name|null>}
    POST /__e2e__/scenario            -> {"name": "ecommerce"|"no_documents"|"client_override"}
    GET  /__e2e__/provider            -> {"called": bool, "calls": int}
    GET  /__e2e__/fixtures            -> the persona constants, so the .spec.js
                                         cannot drift from the Python fixtures
"""

import json
import os
import sys
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Safe test env vars + the Supabase MagicMock, applied before any app module is
# imported.  Reused from the pytest suite rather than restated here.
import tests.conftest  # noqa: F401,E402  (imported for its import-time side effects)

# ``token_required`` evaluates ``get_jwt_secret()`` as an argument to
# ``jwt.decode`` even when ``jwt.decode`` itself is patched, so the variable has
# to exist.  Its value is irrelevant: the decode never really runs.
os.environ.setdefault("JWT_SECRET", "e2e-testbot-persona-jwt-secret")

from app.routes import testbot_routes  # noqa: E402
from app.services import profile_service  # noqa: E402
from app.utils.auth_token import build_password_fingerprint  # noqa: E402

# Every persona fixture is imported, never redefined.
from tests.test_persona_reaches_replies import (  # noqa: E402
    CATALOGUE,
    CHATBOT_ID,
    COMPANY_ID,
    GENERIC_GREETING,
    KNOWLEDGE_CHUNKS,
    MISSING_INFO_REPLY,
    PERSONA_JSON,
    PRODUCT_QUESTION,
    PROFILE_NAME,
    ClientOverrideWinsInTheReplyTests,
    _derived_config_row,
    _serving_stack,
    create_app,
)

DEFAULT_PORT = int(os.getenv("TESTBOT_E2E_PORT", "4174"))

#: Which scenario each browser case runs against.  ``_serving_stack`` keyword
#: arguments, built fresh on every activation so stage A (the real derivation)
#: re-runs and stage B serves the row stage A actually wrote.
SCENARIOS = ("ecommerce", "no_documents", "client_override")


def _client_edited_row():
    """The stored row for CASE 3, via the pytest suite's own fixture method.

    ``_client_edited_row`` is an instance method on the pytest TestCase, so it
    is reached through an instance rather than copied.  The method name passed
    to the constructor just has to exist; the test is never run.
    """
    case = ClientOverrideWinsInTheReplyTests(
        "test_the_override_is_what_the_generated_reply_says"
    )
    return case._client_edited_row()


def _client_override_row():
    """Re-derive over a client edit and return the row the derivation wrote."""
    return _derived_config_row(
        persona_json=ClientOverrideWinsInTheReplyTests.REDERIVED_JSON,
        stored_row=_client_edited_row(),
    )


def _scenario_kwargs(name):
    """Build the ``_serving_stack`` keyword arguments for a scenario."""
    if name == "ecommerce":
        # CASE 1: an e-commerce knowledge set, derived and deployed.
        return {
            "deployed_profile_name": PROFILE_NAME,
            "config_row": _derived_config_row(),
            "knowledge_chunks": KNOWLEDGE_CHUNKS,
        }

    if name == "no_documents":
        # CASE 2: nothing was ever ingested, so nothing is deployed.
        return {
            "deployed_profile_name": "",
            "config_row": None,
            "active_document": None,
        }

    if name == "client_override":
        # CASE 3: a re-derivation proposes a new name over a client edit.
        return {
            "deployed_profile_name": PROFILE_NAME,
            "config_row": _client_override_row(),
            "knowledge_chunks": KNOWLEDGE_CHUNKS,
        }

    raise ValueError(f"unknown scenario: {name!r}")


@contextmanager
def _scenario_stack(name):
    """``_serving_stack`` plus the two dependencies the context route owns.

    ``GET /api/testbot/context`` resolves the deployed profile through
    ``app.routes.testbot_routes``' own module-level imports, which
    ``_serving_stack`` (which patches ``rag_service``) does not cover.  Without
    these the page header would render a backend error while the chat path
    still worked -- true but confusing, and it would hide a real regression in
    the header.
    """
    kwargs = _scenario_kwargs(name)
    deployed_profile_name = kwargs["deployed_profile_name"]
    config_row = kwargs.get("config_row")

    def _profile_lookup(profile_name, _chatbot_id):
        if not profile_name or not config_row:
            return None
        if profile_name != config_row.get("profile_name"):
            return None
        return profile_service._row_to_profile(config_row)

    with ExitStack() as stack:
        provider = stack.enter_context(_serving_stack(**kwargs))
        stack.enter_context(patch.object(
            testbot_routes,
            "get_deployed_runtime",
            return_value={
                "deployed_profile_name": deployed_profile_name,
                "deployed_pdf_file_name": "",
                "deployed_pdf_path": "",
            },
        ))
        stack.enter_context(patch.object(
            testbot_routes, "get_profile_by_name", side_effect=_profile_lookup
        ))
        yield provider


@contextmanager
def _authenticated():
    """The tenant session the page assumes, doubled at the same seams as pytest."""
    user = {
        "id": 1,
        "company_id": COMPANY_ID,
        "email": "owner@example.com",
        "role": "admin",
        "status": "active",
        "password_hash": None,
    }
    with patch(
        "app.decorators.auth_decorator.jwt.decode",
        return_value={
            "company_id": COMPANY_ID,
            "user_id": 1,
            "role": "admin",
            "pwdv": build_password_fingerprint(user),
        },
    ), patch(
        "app.database.user_repository.get_user_by_id",
        return_value=user,
    ), patch(
        "app.routes.testbot_routes.verify_chatbot_access",
        return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID},
    ):
        yield


@contextmanager
def _page_load_doubles():
    """Double the one page-load call that still reaches the Supabase boundary.

    ``testbot.html`` fetches ``/api/bots/<id>`` for the provider badge and the
    welcome bubble.  Left real it returns 500, which the page survives but
    which would leave a backend error on screen and hide a genuine regression.

    ``welcome_message`` is deliberately empty: a non-empty one makes the page
    append a second bot bubble on a 500ms timer, which would race every
    "the last bot message is the reply" assertion in the spec.
    """
    with patch(
        "app.routes.bot_routes.get_bot",
        return_value={
            "id": CHATBOT_ID,
            "bot_name": "Persona E2E Bot",
            # Matches the bot `_serving_stack` routes the reply through.
            "ai_provider": "google",
            "model_name": "stub/model",
            "welcome_message": "",
        },
    ):
        yield


class _ActiveScenario:
    """Holds the one live scenario. Playwright runs ``workers: 1``, so the
    patches ``_serving_stack`` installs are process-global but never contended:
    the spec activates a scenario, then drives it to completion.
    """

    def __init__(self):
        self._stack = None
        self._provider = None
        self._name = None

    @property
    def name(self):
        return self._name

    @property
    def provider(self):
        return self._provider

    def activate(self, name):
        self.clear()
        stack = _scenario_stack(name)
        self._provider = stack.__enter__()
        self._stack = stack
        self._name = name

    def clear(self):
        if self._stack is not None:
            self._stack.__exit__(None, None, None)
        self._stack = None
        self._provider = None
        self._name = None


_active = _ActiveScenario()


def _register_control_routes(app):
    @app.get("/__e2e__/health")
    def _health():
        return {"ready": True, "scenario": _active.name}, 200

    @app.post("/__e2e__/scenario")
    def _scenario():
        from flask import request

        name = (request.get_json(silent=True) or {}).get("name")
        if name not in SCENARIOS:
            return {"error": f"unknown scenario: {name!r}"}, 400

        _active.activate(name)
        return {"scenario": name}, 200

    @app.get("/__e2e__/fixtures")
    def _fixtures():
        # Served rather than restated in JavaScript, so a change to the Python
        # fixtures cannot silently leave the browser spec asserting stale text.
        from app.services.settings_service import DEFAULT_SETTINGS

        knowledge_text = " ".join(KNOWLEDGE_CHUNKS).lower()
        knowledge_only_terms = [
            term for term in CATALOGUE if term.lower() in knowledge_text
        ]

        return {
            "chatbotId": CHATBOT_ID,
            "productQuestion": PRODUCT_QUESTION,
            "genericGreeting": GENERIC_GREETING,
            "missingInfoReply": MISSING_INFO_REPLY,
            # "Your Company" -- what the page shows when nothing is deployed.
            "placeholderCompany": DEFAULT_SETTINGS.get("company_name", ""),
            "derivedCompany": json.loads(PERSONA_JSON)["company_name"],
            "overrideCompany": _client_edited_row()["company_name"],
            # The name the re-derivation proposed and the override must beat.
            "rejectedCompany": json.loads(
                ClientOverrideWinsInTheReplyTests.REDERIVED_JSON
            )["company_name"],
            # Reaches the prompt ONLY through retrieved knowledge, never through
            # the persona description -- so asserting it proves the RAG channel.
            "knowledgeOnlyTerms": knowledge_only_terms,
        }, 200

    @app.get("/__e2e__/provider")
    def _provider():
        provider = _active.provider
        if provider is None:
            return {"error": "no scenario is active"}, 409
        # `called` is the money assertion: the greeting path must not reach a
        # provider at all.
        return {"called": provider.called, "calls": len(provider.prompts)}, 200


def build_app():
    app = create_app()
    app.config["TESTING"] = True
    _register_control_routes(app)
    return app


def main():
    port = DEFAULT_PORT
    app = build_app()

    with ExitStack() as stack:
        stack.enter_context(_authenticated())
        stack.enter_context(_page_load_doubles())
        # `use_reloader=False` keeps this a single process, so the patches above
        # stay installed in the process that actually serves requests.
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
