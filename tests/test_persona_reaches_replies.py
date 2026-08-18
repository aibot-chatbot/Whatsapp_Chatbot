"""Does the derived persona actually reach the reply the customer reads?

``tests/test_persona_derivation.py`` proves the derived persona lands in the
``bot_configs`` row.  That is *storage*.  This file proves the other half: the
stored persona is what the **serving** path actually uses -- ``build_prompt``,
the local greeting branch, and the provider call behind
``ai_router.generate_response`` (the same function ``/api/testbot/chat`` calls).

Why a new file rather than more of ``test_persona_derivation.py``: that file is
organised around the write side (provenance primitives, the two writers, the
migration) and already runs 1191 lines.  Everything here needs a different mock
surface -- the chat pipeline's repositories and a provider double -- and asserts
on replies, not on payloads.  The Supabase fake is *imported* from it rather
than re-declared, so there is still exactly one fake in the suite.

THE PRECONDITION, STATED ONCE
-----------------------------
Derivation writes the **active** ``bot_configs`` row.
``rag_service.get_deployed_settings`` (``rag_service.py:26-43``) resolves the row
named by ``chatbots.deployed_profile_name`` and returns ``DEFAULT_SETTINGS``
when that field is blank.  A derived persona therefore only reaches a reply on a
bot whose ``deployed_profile_name`` names the row the derivation wrote.

Every test below sets that up explicitly and visibly -- see the
``deployed_profile_name=`` argument of :func:`_serving_stack` -- and
:meth:`EcommercePersonaReachesTheReplyTests.test_the_same_derived_row_undeployed_cannot_name_the_store`
is the negative control that proves the precondition is load-bearing rather than
decorative.  Closing the gap is create-RPC/promotion work and is deliberately
NOT done here; ``test_persona_derivation.py`` pins the gap itself in
``test_an_undeployed_bot_still_falls_back_to_the_placeholders``.

MONEY
-----
No test in this file may reach a provider.  Three seams are stubbed:

* ``ai_router.generate_system_response`` -- the billed derivation call (stage A);
* ``openrouter_service._request``        -- the billed reply call (stage B);
* ``deepseek_service._request``          -- raises if the failover path is ever
  entered, so a stub reply that accidentally looks like an error cannot turn
  into a second, real provider call.

The stage-B double is :class:`_GroundedProviderStub`, which is deliberately not
a canned string.  It answers using only what it can find in the prompt it was
handed, exactly as a real model does, and otherwise returns the
missing-information line.  That is what makes "the reply references what the
store sells" a real assertion: if the persona or the retrieved knowledge never
reaches the prompt, the stub cannot name them and the test fails.
"""

from contextlib import ExitStack, contextmanager
import json
import re
import unittest
from unittest.mock import MagicMock, patch

# One Supabase fake for the whole suite: reused, never re-declared.
from tests.test_persona_derivation import _FakeSupabase, _config_row

with patch("app.database.db.supabase", MagicMock()):
    from app import create_app


CHATBOT_ID = 7
COMPANY_ID = 42
PROFILE_NAME = "Default Profile"
CUSTOMER_ID = "web_testbot_session"

# The e-commerce document the client ingested.
ECOMMERCE_DOCUMENT = (
    "GreenLeaf Grocers is an online grocery store serving the Klang Valley. "
    "We sell cold-pressed juice, organic pantry staples and sourdough starter "
    "kits. Orders placed before 11am are delivered the same day."
)

# What the (stubbed) derivation LLM returns for that document.  Note the
# description names two product lines but NOT the third: "sourdough starter
# kits" only ever reaches the prompt through retrieved knowledge, which is what
# lets the assertions tell the two channels apart.
PERSONA_JSON = json.dumps({
    "company_name": "GreenLeaf Grocers",
    "business_description": (
        "An online grocery store selling cold-pressed juice and organic pantry "
        "staples to households in the Klang Valley."
    ),
    "tone": "Friendly",
})

KNOWLEDGE_CHUNKS = [
    "Product range: sourdough starter kits, shipped chilled within 24 hours.",
]

#: What the stub provider is able to talk about, if -- and only if -- it finds
#: the term in the prompt.
CATALOGUE = (
    "cold-pressed juice",
    "organic pantry staples",
    "sourdough starter kits",
)

#: Deliberately contains no catalogue term and no company name, so a passing
#: assertion cannot be satisfied by the question echoing back through the prompt.
PRODUCT_QUESTION = "What do you sell?"

MISSING_INFO_REPLY = (
    "I do not have that information in the provided company materials."
)

GENERIC_GREETING = "Hello! Welcome to Your Company. How can I help you today?"

#: ``build_prompt`` renders this line first: "You are {bot_name}, an AI
#: assistant for {company_name}."
_COMPANY_LINE = re.compile(
    r"^You are .+?, an AI assistant for (?P<company>.+?)\.\s*$", re.MULTILINE
)


class _GroundedProviderStub:
    """A provider double that can only answer from the prompt it was given.

    Stands in for ``openrouter_service._request``.  Returns the company name it
    finds in the system prompt plus every catalogue term present in that prompt;
    if it can find neither, it returns the missing-information line.  A canned
    reply would make every assertion below a tautology -- this does not.
    """

    def __init__(self, catalogue=CATALOGUE):
        self.catalogue = tuple(catalogue)
        self.prompts = []

    def __call__(self, prompt, model=None, temperature=0.7, max_tokens=1500):
        self.prompts.append(prompt)
        return True, {
            "choices": [{"message": {"content": self._reply_for(prompt)}}],
            "model": model,
            "id": "stub-generation",
        }

    @property
    def called(self):
        return bool(self.prompts)

    @property
    def last_prompt(self):
        if not self.prompts:
            raise AssertionError("the provider was never called")
        return self.prompts[-1]

    def _reply_for(self, prompt):
        match = _COMPANY_LINE.search(prompt)
        company = match.group("company").strip() if match else ""
        lowered = prompt.lower()
        found = [item for item in self.catalogue if item.lower() in lowered]

        if not company or not found:
            return MISSING_INFO_REPLY

        return f"Yes. {company} stocks {', '.join(found)}."


def _no_provider_call(*_args, **_kwargs):
    raise AssertionError("a test tried to make a real provider call")


# =====================================================================
# Stage A: run the real derivation, keep the row it wrote
# =====================================================================

def _derived_config_row(persona_json=PERSONA_JSON, stored_row=None):
    """Run the real derivation with the LLM and ``bot_configs`` doubled.

    Returns the exact row payload the derivation wrote, so stage B serves what
    stage A stored rather than a hand-written stand-in.
    """
    from app.services import ai_router, persona_derivation_service, settings_service

    select_responses = (
        [[stored_row], [{"id": stored_row["id"]}]] if stored_row else [[], []]
    )
    fake = _FakeSupabase(select_responses=select_responses)

    with patch.object(settings_service, "supabase", fake), patch.object(
        ai_router, "generate_system_response", lambda **_kwargs: persona_json
    ):
        persona_derivation_service.derive_persona_from_documents(
            CHATBOT_ID, source_text=ECOMMERCE_DOCUMENT
        )

    return fake.last_write_payload


# =====================================================================
# Stage B: serve a reply with every external dependency doubled
# =====================================================================

@contextmanager
def _serving_stack(
    *,
    deployed_profile_name,
    config_row=None,
    knowledge_chunks=(),
    active_document=None,
    document_chunks=(),
    welcome_message="",
):
    """Stand the reply path up on doubles and yield the provider stub.

    ``deployed_profile_name`` is the precondition this whole file turns on: only
    a profile whose name matches it resolves, exactly as ``get_profile_by_name``
    behaves against a real ``bot_configs`` table.
    """
    from app.database import agent_action_repository, bot_repository
    from app.services import (
        ai_router,
        chat_logic_service,
        chat_pipeline_service,
        deepseek_service,
        flow_executor_service,
        openrouter_service,
        profile_service,
        rag_service,
    )

    provider = _GroundedProviderStub()

    def _profile_lookup(profile_name, _chatbot_id):
        if not profile_name or not config_row:
            return None
        if profile_name != config_row.get("profile_name"):
            return None
        return profile_service._row_to_profile(config_row)

    with ExitStack() as stack:
        enter = stack.enter_context

        # -- the deployment precondition ------------------------------------
        enter(patch.object(
            rag_service,
            "get_deployed_runtime",
            return_value={
                "deployed_profile_name": deployed_profile_name,
                "deployed_pdf_file_name": "",
                "deployed_pdf_path": "",
            },
        ))
        enter(patch.object(
            rag_service, "get_profile_by_name", side_effect=_profile_lookup
        ))

        # -- money: no provider call may leave the process -------------------
        enter(patch.object(openrouter_service, "_request", provider))
        enter(patch.object(deepseek_service, "_request", _no_provider_call))
        enter(patch.object(ai_router, "generate_system_response", _no_provider_call))
        enter(patch.object(ai_router, "_check_ai_credit_before_provider", lambda _c: None))

        # -- routing is out of scope: identity in, identity out --------------
        enter(patch.object(
            ai_router, "normalize_model_selection", lambda provider_, model: (provider_, model)
        ))
        enter(patch.object(
            ai_router,
            "_route_for_enforcement",
            lambda provider_, model, company_id=None: (provider_, model),
        ))
        enter(patch.object(
            ai_router,
            "get_bot_by_id",
            return_value={
                "id": CHATBOT_ID,
                # "google" is an OPENROUTER_PROVIDER_KEYS member, so this takes
                # the OpenRouter branch of call_provider -- the branch that
                # builds the RAG prompt.
                "ai_provider": "google",
                "model_name": "stub/model",
                "temperature": 0.0,
                # None on purpose: usage logging needs a company_id, and this
                # file is not testing billing.
                "company_id": None,
            },
        ))
        enter(patch.object(flow_executor_service, "process_flow_message", return_value=None))

        # -- chat pipeline repositories --------------------------------------
        enter(patch.object(
            chat_pipeline_service, "get_or_create_conversation", return_value={"id": 100}
        ))
        enter(patch.object(chat_pipeline_service, "get_recent_chat_history", return_value=[]))
        enter(patch.object(
            agent_action_repository, "is_conversation_escalated", return_value=False
        ))
        enter(patch.object(chat_pipeline_service, "save_agent_action", return_value=None))
        enter(patch.object(
            chat_pipeline_service, "create_crm_lead_from_agent_signal", return_value=None
        ))
        enter(patch.object(
            chat_pipeline_service,
            "get_bot_by_id",
            return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID},
        ))
        enter(patch.object(chat_pipeline_service, "update_workflow_state", return_value=None))
        enter(patch.object(
            chat_pipeline_service,
            "retrieve_relevant_chunks",
            return_value=list(knowledge_chunks),
        ))

        # -- greeting branch dependencies ------------------------------------
        # `get_active_knowledge_file` is the name chat_logic_service binds
        # (:5, used at :160). The old `get_active_pdf_knowledge_file` survives
        # as an alias on knowledge_file_repository and rag_service, but never
        # existed here, so patch.object raised AttributeError before the stack
        # was even built.
        #
        # KNOWN: fixing this uncovers a second, older break in the same stack --
        # ensure_company_operational rejects the resolved company id
        # ("Unable to validate company access.", company_context_invalid), so
        # this module and tests/browser/testbot-persona.spec.js are both still
        # red. That one is not diagnosed yet; it is unrelated to the patch
        # target and predates it.
        enter(patch.object(
            chat_logic_service, "get_active_knowledge_file", return_value=active_document
        ))
        enter(patch.object(
            chat_logic_service,
            "get_chunks_by_file_for_chatbot",
            return_value=list(document_chunks),
        ))
        enter(patch.object(
            bot_repository,
            "get_bot_by_id",
            return_value={"id": CHATBOT_ID, "welcome_message": welcome_message},
        ))

        yield provider


def _reply(message):
    """The reply a customer would read, through the real router."""
    from app.services.ai_router import OPERATION_TEST_BOT, generate_response

    return generate_response(
        message,
        CUSTOMER_ID,
        CHATBOT_ID,
        source_channel="web",
        operation_type=OPERATION_TEST_BOT,
    )


# =====================================================================
# CASE 1: an e-commerce knowledge set yields replies about that store
# =====================================================================

class EcommercePersonaReachesTheReplyTests(unittest.TestCase):
    def test_the_derivation_writes_the_row_the_deployed_profile_resolves(self):
        # The precondition, made explicit rather than assumed: derivation writes
        # the row named PROFILE_NAME, and that is the name a deployed bot must
        # carry in chatbots.deployed_profile_name for any of this to work.
        row = _derived_config_row()

        self.assertEqual(row["profile_name"], PROFILE_NAME)
        self.assertEqual(row["company_name"], "GreenLeaf Grocers")

    def test_a_deployed_derived_persona_names_the_store_and_its_products(self):
        row = _derived_config_row()

        with _serving_stack(
            deployed_profile_name=PROFILE_NAME,   # <-- the precondition
            config_row=row,
            knowledge_chunks=KNOWLEDGE_CHUNKS,
        ) as provider:
            reply = _reply(PRODUCT_QUESTION)

        self.assertNotEqual(reply, MISSING_INFO_REPLY)
        # From the derived persona:
        self.assertIn("GreenLeaf Grocers", reply)
        self.assertIn("cold-pressed juice", reply)
        # From the retrieved e-commerce knowledge, which the persona never names:
        self.assertIn("sourdough starter kits", reply)
        self.assertNotIn("Your Company", reply)

    def test_the_prompt_behind_that_reply_carries_no_placeholder(self):
        row = _derived_config_row()

        with _serving_stack(
            deployed_profile_name=PROFILE_NAME,
            config_row=row,
            knowledge_chunks=KNOWLEDGE_CHUNKS,
        ) as provider:
            _reply(PRODUCT_QUESTION)

        prompt = provider.last_prompt

        self.assertIn("GreenLeaf Grocers", prompt)
        self.assertNotIn("Your Company", prompt)
        self.assertNotIn("No business description provided.", prompt)

    def test_the_same_derived_row_undeployed_cannot_name_the_store(self):
        # NEGATIVE CONTROL for the precondition above.  Same derived row, same
        # knowledge, only deployed_profile_name differs -- and the persona is
        # gone from the reply.  If someone ever closes the deployed_profile_name
        # gap, this test fails and should be deleted together with
        # test_persona_derivation.py's
        # test_an_undeployed_bot_still_falls_back_to_the_placeholders.
        row = _derived_config_row()

        with _serving_stack(
            deployed_profile_name="",             # <-- never had a profile applied
            config_row=row,
            knowledge_chunks=KNOWLEDGE_CHUNKS,
        ):
            reply = _reply(PRODUCT_QUESTION)

        self.assertIn("Your Company", reply)
        self.assertNotIn("GreenLeaf Grocers", reply)
        self.assertNotIn("cold-pressed juice", reply)

    def test_no_knowledge_and_no_persona_yields_the_missing_information_reply(self):
        # The stub is not free-associating: strip both channels and it has
        # nothing to say.  This is what makes the two tests above meaningful.
        with _serving_stack(deployed_profile_name="", knowledge_chunks=[]) as provider:
            reply = _reply(PRODUCT_QUESTION)

        self.assertEqual(reply, MISSING_INFO_REPLY)
        self.assertTrue(provider.called)


# =====================================================================
# CASE 2: no ingested documents -> the generic greeting
# =====================================================================

class NoDocumentsGreetingTests(unittest.TestCase):
    """``generate_greeting`` lives at ``settings_service.py:242``."""

    def test_generate_greeting_renders_the_placeholder_for_default_settings(self):
        from app.services.settings_service import DEFAULT_SETTINGS, generate_greeting

        self.assertEqual(generate_greeting(DEFAULT_SETTINGS), GENERIC_GREETING)

    def test_a_bot_with_no_documents_falls_back_to_the_generic_greeting(self):
        # No ingest ever ran: nothing was derived, no profile is deployed, and
        # there is no active document to lift a menu from.
        with _serving_stack(
            deployed_profile_name="",
            config_row=None,
            active_document=None,
        ) as provider:
            reply = _reply("hi")

        self.assertEqual(reply, GENERIC_GREETING)
        # ...and greeting is a local intent, so it costs nothing.
        self.assertFalse(provider.called)

    def test_a_deployed_derived_persona_greets_as_the_store_instead(self):
        # The counterpart that proves the greeting above is a fallback and not a
        # hardcoded string.
        row = _derived_config_row()

        with _serving_stack(
            deployed_profile_name=PROFILE_NAME,
            config_row=row,
            active_document=None,
        ) as provider:
            reply = _reply("hi")

        self.assertEqual(
            reply, "Hello! Welcome to GreenLeaf Grocers. How can I help you today?"
        )
        self.assertFalse(provider.called)

    def test_a_bot_with_no_documents_still_answers_a_product_question_safely(self):
        # The other half of "no documents": a real question gets the
        # missing-information reply rather than an invented one.
        with _serving_stack(deployed_profile_name="", knowledge_chunks=[]) as provider:
            reply = _reply(PRODUCT_QUESTION)

        self.assertEqual(reply, MISSING_INFO_REPLY)


# =====================================================================
# CASE 3: a client override wins in the REPLY, not just in storage
# =====================================================================

class ClientOverrideWinsInTheReplyTests(unittest.TestCase):
    #: The LLM's proposal for a bot whose client already renamed the company.
    REDERIVED_JSON = json.dumps({
        "company_name": "Green Leaf Store",
        "business_description": (
            "An online grocery store selling cold-pressed juice and organic "
            "pantry staples to households in the Klang Valley."
        ),
        "tone": "Friendly",
    })

    def _client_edited_row(self):
        from app.services.bot_config_fields import (
            PROVENANCE_CLIENT,
            PROVENANCE_COLUMN,
            PROVENANCE_DERIVED,
        )

        return _config_row(
            company_name="GreenLeaf Grocers Sdn Bhd",
            business_description="An online grocery store.",
            tone="Friendly",
            **{
                PROVENANCE_COLUMN: {
                    "company_name": PROVENANCE_CLIENT,
                    "business_description": PROVENANCE_DERIVED,
                    "tone": PROVENANCE_DERIVED,
                }
            },
        )

    def test_the_override_survives_the_re_derivation_in_storage(self):
        row = _derived_config_row(
            persona_json=self.REDERIVED_JSON, stored_row=self._client_edited_row()
        )

        self.assertEqual(row["company_name"], "GreenLeaf Grocers Sdn Bhd")
        # The derived-provenance sibling field did refresh, so this is not just
        # "the write was skipped wholesale".
        self.assertIn("cold-pressed juice", row["business_description"])

    def test_the_override_is_what_the_generated_reply_says(self):
        row = _derived_config_row(
            persona_json=self.REDERIVED_JSON, stored_row=self._client_edited_row()
        )

        with _serving_stack(
            deployed_profile_name=PROFILE_NAME,
            config_row=row,
            knowledge_chunks=KNOWLEDGE_CHUNKS,
        ) as provider:
            reply = _reply(PRODUCT_QUESTION)

        self.assertIn("GreenLeaf Grocers Sdn Bhd", reply)
        self.assertNotIn("Green Leaf Store", reply)
        self.assertNotIn("Green Leaf Store", provider.last_prompt)

    def test_the_override_is_what_the_generated_greeting_says(self):
        row = _derived_config_row(
            persona_json=self.REDERIVED_JSON, stored_row=self._client_edited_row()
        )

        with _serving_stack(deployed_profile_name=PROFILE_NAME, config_row=row):
            reply = _reply("hi")

        self.assertIn("GreenLeaf Grocers Sdn Bhd", reply)
        self.assertNotIn("Green Leaf Store", reply)


# =====================================================================
# The seam the browser test drives: POST /api/testbot/chat
# =====================================================================

class TestbotChatRouteTests(unittest.TestCase):
    """``frontend/testbot.html`` reaches ``generate_response`` through here."""

    def setUp(self):
        app = create_app()
        app.config["TESTING"] = True
        self.client = app.test_client()

    @contextmanager
    def _authenticated(self):
        with patch(
            "app.decorators.auth_decorator.jwt.decode",
            return_value={"company_id": COMPANY_ID, "user_id": 1, "role": "admin"},
        ), patch(
            "app.database.user_repository.get_user_by_id",
            return_value={
                "id": 1,
                "company_id": COMPANY_ID,
                "email": "owner@example.com",
                "role": "admin",
                "status": "active",
            },
        ), patch(
            "app.routes.testbot_routes.verify_chatbot_access",
            return_value={"id": CHATBOT_ID, "company_id": COMPANY_ID},
        ):
            yield

    def _post(self, message):
        return self.client.post(
            f"/api/testbot/chat?chatbot_id={CHATBOT_ID}",
            json={"message": message},
            headers={"Authorization": "Bearer test-token"},
        )

    def test_the_route_returns_a_reply_grounded_in_the_derived_persona(self):
        row = _derived_config_row()

        with self._authenticated(), _serving_stack(
            deployed_profile_name=PROFILE_NAME,
            config_row=row,
            knowledge_chunks=KNOWLEDGE_CHUNKS,
        ):
            response = self._post(PRODUCT_QUESTION)

        self.assertEqual(response.status_code, 200)
        reply = response.get_json()["data"]["reply"]

        self.assertIn("GreenLeaf Grocers", reply)
        self.assertIn("sourdough starter kits", reply)

    def test_the_route_returns_the_generic_greeting_for_a_bot_with_no_documents(self):
        with self._authenticated(), _serving_stack(
            deployed_profile_name="", active_document=None
        ) as provider:
            response = self._post("hi")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["reply"], GENERIC_GREETING)
        self.assertFalse(provider.called)


if __name__ == "__main__":
    unittest.main()
