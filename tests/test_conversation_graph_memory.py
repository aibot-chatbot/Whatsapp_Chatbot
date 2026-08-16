"""Conversation-scoped graph memory: persistence, keyword recall and tenancy.

Scoping model under test
------------------------
A conversation fact is a row in ``public.conversation_graph_nodes`` bound to a
conversation by ``conversation_id`` and to a tenant by ``chatbot_id``. Both
columns are filtered on every *read* and every *delete*, so a conversation id
belonging to another tenant selects zero rows even if the id is guessed
correctly.

The *write* path is not symmetric, and saying otherwise here would be asserting
something untrue. ``upsert_conversation_fact`` resolves on the conflict target
``(conversation_id, label)``; ``chatbot_id`` rides along as a payload column,
not as a predicate. A mismatched pair therefore takes the ``DO UPDATE`` branch
and rewrites the victim row value *and* its owner instead of selecting zero
rows. ``test_upsert_is_not_tenant_filtered_and_can_retenant_a_row``
characterises that, so the gap fails loudly the day it is closed. Row lifetime
is the conversation lifetime (FK ``ON DELETE CASCADE``).

Fake Supabase
-------------
This module defines a filter-evaluating double. The existing doubles
(``tests/test_persona_derivation.py::_FakeSupabase`` and
``tests/test_bot_archive_soft_delete.py``) only *record* ``.eq()`` predicates and
replay a queued response, so they cannot express "row is invisible to another
tenant" as behaviour -- only as an assertion about which calls were made, which
is an implementation-detail test. Isolation is the security property here, so it
is tested as behaviour against rows that are actually filtered.

The double resolves upserts on ``(conversation_id, label)`` alone, matching the
real conflict target -- which is why it reproduces the re-tenanting overwrite
described above rather than hiding it. It models nothing else about Postgres:
no NOT NULL, no foreign keys, no column projection. Keep it that way; a double
that grows into an emulator stops being evidence.

LLM cost
--------
No test in this module reaches a billed provider. ``retrieve_relevant_chunks``
is exercised with ``generate_embedding`` and ``_vector_matches_for_file``
patched, and the fact producer (``agent_decision_service._extract_fields``) is
pure regex with no provider call. ``ai_router.generate_system_response`` is
never imported or invoked here.
"""

import re
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = PROJECT_ROOT / "data" / "041_conversation_graph_nodes.sql"


def _without_comments(sql: str) -> str:
    """Strip SQL comments, mirroring the helper in
    tests/test_crm_agent_actions_orphan_cleanup_migration.py. Assertions about
    what a migration *executes* must not be satisfied or broken by prose.
    """
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", "", sql)


class _Response:
    def __init__(self, data=None):
        self.data = data if data is not None else []


class _InMemoryConversationGraph:
    """PostgREST double that actually evaluates eq/in_ filters over rows.

    Only the operators the conversation-graph repository uses are implemented;
    anything else raises so an untested query shape cannot pass silently.
    """

    def __init__(self, rows=None):
        self.rows = [dict(row) for row in (rows or [])]
        self._table = None
        self._mode = None
        self._payload = None
        self._filters = []
        self._in_filters = []
        self._next_id = 1000

    # -- builder ---------------------------------------------------------
    def table(self, table_name):
        self._table = table_name
        self._mode = None
        self._payload = None
        self._filters = []
        self._in_filters = []
        return self

    def select(self, *_args, **_kwargs):
        self._mode = "select"
        return self

    def upsert(self, payload, on_conflict=None):
        self._mode = "upsert"
        self._payload = dict(payload)
        self.last_on_conflict = on_conflict
        return self

    def delete(self):
        self._mode = "delete"
        return self

    def eq(self, field, value):
        self._filters.append((field, value))
        return self

    def in_(self, field, values):
        self._in_filters.append((field, list(values)))
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    # -- execution -------------------------------------------------------
    def _matches(self, row):
        for field, value in self._filters:
            if row.get(field) != value:
                return False
        for field, values in self._in_filters:
            if row.get(field) not in values:
                return False
        return True

    def execute(self):
        if self._table != "conversation_graph_nodes":
            raise AssertionError(f"unexpected table: {self._table}")

        if self._mode == "select":
            return _Response([dict(r) for r in self.rows if self._matches(r)])

        if self._mode == "delete":
            removed = [r for r in self.rows if self._matches(r)]
            self.rows = [r for r in self.rows if not self._matches(r)]
            return _Response(removed)

        if self._mode == "upsert":
            payload = dict(self._payload)
            # Mirrors UNIQUE (conversation_id, label) in migration 033.
            key = (payload.get("conversation_id"), payload.get("label"))
            for existing in self.rows:
                if (existing.get("conversation_id"), existing.get("label")) == key:
                    existing.update(payload)
                    return _Response([dict(existing)])
            payload.setdefault("id", self._next_id)
            self._next_id += 1
            self.rows.append(payload)
            return _Response([dict(payload)])

        raise AssertionError(f"unexpected mode: {self._mode}")


CHATBOT_A = 7
CHATBOT_B = 99
CONVO_1 = 501
CONVO_2 = 502


class TestConversationFactPersistence(unittest.TestCase):
    """Requirement 1: a fact learned mid-conversation survives and is recalled."""

    def test_fact_persists_and_is_retrievable_later_in_same_conversation(self):
        from app.database import conversation_graph_repository as repo

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(
                chatbot_id=CHATBOT_A,
                conversation_id=CONVO_1,
                label="name",
                value="Alice",
            )
            # Later turn in the same conversation.
            recalled = repo.get_conversation_facts_by_labels(
                chatbot_id=CHATBOT_A,
                conversation_id=CONVO_1,
                labels=["name"],
            )

        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0]["value"], "Alice")

    def test_repeated_fact_updates_in_place_rather_than_duplicating(self):
        from app.database import conversation_graph_repository as repo

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(CHATBOT_A, CONVO_1, "order", "A-1")
            repo.upsert_conversation_fact(CHATBOT_A, CONVO_1, "order", "A-2")
            recalled = repo.get_conversation_facts_by_labels(
                CHATBOT_A, CONVO_1, ["order"]
            )

        self.assertEqual(len(recalled), 1, "upsert must be idempotent per label")
        self.assertEqual(recalled[0]["value"], "A-2", "latest mention wins")

    def test_label_is_normalised_so_recall_is_case_insensitive(self):
        from app.database import conversation_graph_repository as repo

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(CHATBOT_A, CONVO_1, "  Order Number ", "X9")
            recalled = repo.get_conversation_facts_by_labels(
                CHATBOT_A, CONVO_1, ["ORDER NUMBER"]
            )

        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0]["value"], "X9")


class TestConversationFactIsolation(unittest.TestCase):
    """Tenancy: conversation memory holds personal data; leakage is a bug."""

    def _seeded(self):
        fake = _InMemoryConversationGraph()
        from app.database import conversation_graph_repository as repo

        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(CHATBOT_A, CONVO_1, "name", "Alice")
        return fake

    def test_fact_is_not_retrievable_from_a_different_conversation(self):
        from app.database import conversation_graph_repository as repo

        fake = self._seeded()
        with patch.object(repo, "supabase", fake):
            leaked = repo.get_conversation_facts_by_labels(
                chatbot_id=CHATBOT_A,
                conversation_id=CONVO_2,
                labels=["name"],
            )

        self.assertEqual(leaked, [], "conversation 2 must not see conversation 1's fact")

    def test_fact_is_not_retrievable_by_a_different_tenant(self):
        from app.database import conversation_graph_repository as repo

        fake = self._seeded()
        with patch.object(repo, "supabase", fake):
            # Tenant B guesses the correct conversation id.
            leaked = repo.get_conversation_facts_by_labels(
                chatbot_id=CHATBOT_B,
                conversation_id=CONVO_1,
                labels=["name"],
            )

        self.assertEqual(leaked, [], "chatbot_id must gate the row even with a valid conversation_id")

    def test_recall_service_does_not_leak_across_tenants(self):
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = self._seeded()
        with patch.object(repo, "supabase", fake):
            leaked = memory.recall_conversation_facts(
                chatbot_id=CHATBOT_B,
                conversation_id=CONVO_1,
                query="what is my name",
            )

        self.assertEqual(leaked, [])

    def test_upsert_is_not_tenant_filtered_and_can_retenant_a_row(self):
        """Characterises the known write-path gap so it cannot quietly persist.

        ``chatbot_id`` is a payload column on the upsert, not a predicate, so a
        conversation id belonging to another tenant does not select zero rows --
        it overwrites the value and rewrites the owner. Not reachable from
        untrusted input today: the only producer derives ``conversation_id``
        from ``get_or_create_conversation(chatbot_id=...)``. When a composite
        foreign key or an explicit filter closes the gap, this is the test that
        must fail.
        """
        from app.database import conversation_graph_repository as repo

        fake = self._seeded()
        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(CHATBOT_B, CONVO_1, "name", "Mallory")
            victim = repo.get_conversation_facts_by_labels(
                CHATBOT_A, CONVO_1, ["name"]
            )

        self.assertEqual(len(fake.rows), 1, "the row was overwritten, not added to")
        self.assertEqual(fake.rows[0]["value"], "Mallory")
        self.assertEqual(fake.rows[0]["chatbot_id"], CHATBOT_B, "row was re-tenanted")
        self.assertEqual(victim, [], "tenant A can no longer see its own fact")

    def test_delete_is_scoped_and_does_not_remove_another_tenants_rows(self):
        from app.database import conversation_graph_repository as repo

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(CHATBOT_A, CONVO_1, "name", "Alice")
            repo.upsert_conversation_fact(CHATBOT_B, CONVO_2, "name", "Bob")
            repo.delete_conversation_facts(CHATBOT_A, CONVO_1)
            survivor = repo.get_conversation_facts_by_labels(
                CHATBOT_B, CONVO_2, ["name"]
            )

        self.assertEqual(len(survivor), 1)
        self.assertEqual(survivor[0]["value"], "Bob")


class TestIdentifierGuard(unittest.TestCase):
    """``_require_positive_int`` is what keeps a bad id out of a tenant filter.

    PostgREST renders a ``None`` operand as a null predicate rather than
    refusing it, so a scoped filter built from a missing id stops being a scope.
    The rejection has to happen in Python, before the query is built, and on
    every entry point -- including ``True``, which ``isinstance(x, int)`` alone
    would wave through.
    """

    BAD_IDS = [None, 0, -1, "7", "", True, False, 7.0, [], {}]

    def test_every_entry_point_rejects_a_non_positive_int_id(self):
        from app.database import conversation_graph_repository as repo

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            for bad in self.BAD_IDS:
                with self.subTest(bad_id=bad):
                    calls = (
                        lambda: repo.upsert_conversation_fact(bad, CONVO_1, "n", "A"),
                        lambda: repo.upsert_conversation_fact(CHATBOT_A, bad, "n", "A"),
                        lambda: repo.get_conversation_facts_by_labels(bad, CONVO_1, ["n"]),
                        lambda: repo.get_conversation_facts_by_labels(CHATBOT_A, bad, ["n"]),
                        lambda: repo.delete_conversation_facts(bad, CONVO_1),
                        lambda: repo.delete_conversation_facts(CHATBOT_A, bad),
                    )
                    for call in calls:
                        with self.assertRaises(ValueError):
                            call()

        self.assertEqual(fake.rows, [], "a rejected id must not have written a row")
        self.assertEqual(fake._filters, [], "a rejected id must not reach a query")

    def test_a_valid_id_is_returned_unchanged(self):
        from app.database import conversation_graph_repository as repo

        self.assertEqual(repo._require_positive_int(7, "chatbot_id"), 7)


class TestKeywordRecall(unittest.TestCase):
    """Requirement 2: keyword lookup over node labels."""

    def test_recall_matches_query_term_against_label(self):
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(CHATBOT_A, CONVO_1, "name", "Alice")
            facts = memory.recall_conversation_facts(
                chatbot_id=CHATBOT_A,
                conversation_id=CONVO_1,
                query="can you remind me what my name is?",
            )

        self.assertEqual(len(facts), 1)
        self.assertIn("Alice", facts[0])

    def test_recall_returns_nothing_when_no_query_term_matches_a_label(self):
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(CHATBOT_A, CONVO_1, "name", "Alice")
            facts = memory.recall_conversation_facts(
                chatbot_id=CHATBOT_A,
                conversation_id=CONVO_1,
                query="what are your opening hours",
            )

        self.assertEqual(facts, [])

    def test_recall_handles_empty_and_none_query_without_querying(self):
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            self.assertEqual(
                memory.recall_conversation_facts(CHATBOT_A, CONVO_1, ""), []
            )
            self.assertEqual(
                memory.recall_conversation_facts(CHATBOT_A, CONVO_1, None), []
            )

    def test_recall_without_conversation_id_returns_nothing(self):
        from app.services import conversation_memory_service as memory

        self.assertEqual(
            memory.recall_conversation_facts(CHATBOT_A, None, "what is my name"), []
        )

    def test_query_terms_are_capped_so_the_in_clause_stays_bounded(self):
        """A 500-word message must not become a 500-element IN list."""
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = _InMemoryConversationGraph()
        long_query = " ".join(f"term{i}" for i in range(500))
        with patch.object(repo, "supabase", fake):
            memory.recall_conversation_facts(CHATBOT_A, CONVO_1, long_query)

        self.assertTrue(fake._in_filters, "keyword lookup must use an IN filter")
        _field, values = fake._in_filters[-1]
        self.assertLessEqual(
            len(values),
            memory.MAX_KEYWORD_TERMS,
            "unbounded IN list defeats the index",
        )

    def test_producer_labels_survive_the_write_read_normalisation_round_trip(self):
        """Write and read do not share one reduction, so the overlap is pinned.

        Write applies ``normalize_label`` only. Read applies
        ``clean_query_words`` *first* -- lowercase ``[a-z0-9]+`` tokens longer
        than one character, stopwords removed -- and then ``normalize_label``.
        A label is recallable only where the two agree, so every label the
        producer emits is checked against both. Adding ``name`` to
        ``rag_service.STOPWORDS`` would otherwise blind recall with every other
        test in this module still green.
        """
        from app.database.conversation_graph_repository import normalize_label
        from app.services.conversation_memory_service import _label_words

        for label in ("name", "contact", "interest"):
            with self.subTest(label=label):
                self.assertIn(
                    normalize_label(label),
                    _label_words("what is my " + label),
                )

    def test_multi_word_and_non_ascii_labels_store_but_never_recall(self):
        """Documents the asymmetry instead of assuming it away.

        Query tokenisation can never emit a token containing a space, a hyphen
        or an accent, so a label carrying one is written successfully and is
        then permanently unfindable. The producer emits none of these today.
        """
        from app.database.conversation_graph_repository import normalize_label
        from app.services.conversation_memory_service import _label_words

        cases = (
            ("Order Number", "what is my order number"),
            ("order-id", "what is my order id"),
            ("Prénom", "what is my prénom"),
        )
        for label, query in cases:
            with self.subTest(label=label):
                stored = normalize_label(label)
                self.assertTrue(stored, "the write path accepts it")
                self.assertNotIn(stored, _label_words(query))

    def test_empty_label_list_short_circuits_without_a_query(self):
        from app.database import conversation_graph_repository as repo

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            self.assertEqual(
                repo.get_conversation_facts_by_labels(CHATBOT_A, CONVO_1, []), []
            )
        self.assertEqual(fake._filters, [], "no round trip for an empty label list")


class TestRememberFacts(unittest.TestCase):
    """The producer: facts already extracted per-turn become graph nodes."""

    def test_extracted_fields_are_persisted_as_conversation_facts(self):
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            stored = memory.remember_conversation_facts(
                chatbot_id=CHATBOT_A,
                conversation_id=CONVO_1,
                extracted_fields={
                    "name": "Alice",
                    "contact": "alice@example.com",
                    "interest": "",
                },
            )

        labels = sorted(row["label"] for row in stored)
        self.assertEqual(labels, ["contact", "name"], "blank fields must be skipped")

    def test_remember_is_a_noop_without_a_conversation_id(self):
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            stored = memory.remember_conversation_facts(
                CHATBOT_A, None, {"name": "Alice"}
            )

        self.assertEqual(stored, [])
        self.assertEqual(fake.rows, [])

    def test_remember_tolerates_none_and_non_string_values(self):
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            stored = memory.remember_conversation_facts(
                CHATBOT_A, CONVO_1, {"name": None, "contact": 12345, "interest": "  "}
            )

        labels = sorted(row["label"] for row in stored)
        self.assertEqual(labels, ["contact"])

    def test_remember_handles_none_extracted_fields(self):
        from app.services import conversation_memory_service as memory

        self.assertEqual(
            memory.remember_conversation_facts(CHATBOT_A, CONVO_1, None), []
        )

    def test_fact_value_is_length_capped(self):
        from app.database import conversation_graph_repository as repo
        from app.services import conversation_memory_service as memory

        fake = _InMemoryConversationGraph()
        with patch.object(repo, "supabase", fake):
            memory.remember_conversation_facts(
                CHATBOT_A, CONVO_1, {"interest": "x" * 5000}
            )

        self.assertLessEqual(len(fake.rows[0]["value"]), memory.MAX_FACT_VALUE_LEN)


class TestRagIntegration(unittest.TestCase):
    """Keyword recall runs beside vector search, not instead of it."""

    def _patched_rag(self, rag_service, chunks):
        """Patch every path that would cost money or hit the network."""
        from app.services import conversation_memory_service

        return (
            patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 10}),
            patch.object(rag_service, "get_supporting_knowledge_files", return_value=[]),
            patch.object(rag_service, "get_chunks_by_file_for_chatbot", return_value=chunks),
            patch.object(rag_service, "generate_embedding", return_value=None),
            patch.object(rag_service, "_vector_matches_for_file", return_value=[]),
            # Recall is plan-gated (data/034 conversation_memory); this module
            # tests the memory behaviour of an entitled tenant. The gate itself
            # is covered by tests/test_plan_feature_gating.py.
            patch.object(
                conversation_memory_service,
                "conversation_memory_denial",
                return_value=None,
            ),
        )

    def test_keyword_recall_returns_a_match_vector_similarity_misses(self):
        from app.database import conversation_graph_repository as repo
        from app.services import rag_service

        fake = _InMemoryConversationGraph()
        # The document corpus knows nothing about the customer.
        chunks = [{"content": "We are open from 9am to 6pm on weekdays."}]

        with patch.object(repo, "supabase", fake):
            repo.upsert_conversation_fact(CHATBOT_A, CONVO_1, "name", "Alice")

            for patcher in self._patched_rag(rag_service, chunks):
                patcher.start()
                self.addCleanup(patcher.stop)

            # Vector search alone finds nothing for this query.
            without_memory = rag_service.retrieve_relevant_chunks(
                "remind me of my name", chatbot_id=CHATBOT_A, top_k=3
            )
            with_memory = rag_service.retrieve_relevant_chunks(
                "remind me of my name",
                chatbot_id=CHATBOT_A,
                top_k=3,
                conversation_id=CONVO_1,
            )

        joined_without = "\n".join(without_memory)
        joined_with = "\n".join(with_memory)
        self.assertNotIn("Alice", joined_without)
        self.assertIn("Alice", joined_with)

    def test_vector_path_still_works_unchanged_when_no_conversation_id(self):
        from app.services import rag_service

        chunks = [
            {"content": 'Trigger Keyword: User replies with "A"\nChatbot Response: Show option A details.'},
        ]
        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 10}), \
                patch.object(rag_service, "get_supporting_knowledge_files", return_value=[]), \
                patch.object(rag_service, "get_chunks_by_file_for_chatbot", return_value=chunks), \
                patch.object(rag_service, "generate_embedding") as mock_embedding, \
                patch.object(rag_service, "_vector_matches_for_file", return_value=[]) as mock_vector:
            result = rag_service.retrieve_relevant_chunks("A", chatbot_id=CHATBOT_A, top_k=1)

        self.assertTrue(result)
        self.assertIn('User replies with "A"', result[0])
        mock_embedding.assert_not_called()
        mock_vector.assert_not_called()

    def test_conversation_memory_failure_does_not_break_retrieval(self):
        from app.services import rag_service, conversation_memory_service

        chunks = [{"content": "We are open from 9am to 6pm on weekdays."}]
        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 10}), \
                patch.object(rag_service, "get_supporting_knowledge_files", return_value=[]), \
                patch.object(rag_service, "get_chunks_by_file_for_chatbot", return_value=chunks), \
                patch.object(rag_service, "generate_embedding", return_value=None), \
                patch.object(rag_service, "_vector_matches_for_file", return_value=[]), \
                patch.object(
                    conversation_memory_service,
                    "conversation_memory_denial",
                    return_value=None,
                ), \
                patch.object(
                    conversation_memory_service,
                    "recall_conversation_facts",
                    side_effect=RuntimeError("postgrest down"),
                ):
            result = rag_service.retrieve_relevant_chunks(
                "opening hours", chatbot_id=CHATBOT_A, top_k=3, conversation_id=CONVO_1
            )

        self.assertTrue(result, "a memory outage must not empty the document context")


class TestMigration033(unittest.TestCase):
    """Requirement 3: the index that keeps keyword lookup bounded."""

    def setUp(self):
        self.assertTrue(
            MIGRATION_PATH.exists(), f"missing migration: {MIGRATION_PATH}"
        )
        self.sql = MIGRATION_PATH.read_text(encoding="utf-8")
        self.lowered = self.sql.lower()
        # Executable statements only -- a claim in a comment must not count as
        # evidence, in either direction.
        self.executable = _without_comments(self.lowered)

    def test_creates_the_conversation_graph_nodes_table(self):
        self.assertIn("create table if not exists public.conversation_graph_nodes", self.lowered)

    def test_binds_rows_to_a_conversation_and_a_tenant_with_cascade(self):
        self.assertIn("references public.conversations (id) on delete cascade", self.lowered)
        self.assertIn("references public.chatbots (id) on delete cascade", self.lowered)

    def test_keyword_lookup_index_covers_the_query_shape(self):
        """The lookup is chatbot_id = AND conversation_id = AND label IN (...)."""
        self.assertIn("(conversation_id, label)", self.lowered)

    def test_declares_no_extension_dependency(self):
        """pg_trgm is not enabled anywhere in data/; the index must not need it."""
        self.assertNotIn("gin_trgm_ops", self.executable)
        self.assertNotIn("gist_trgm_ops", self.executable)
        self.assertNotIn("create extension", self.executable)

    def test_keyword_predicate_is_equality_so_the_btree_is_usable(self):
        """The repository must not query with LIKE/ILIKE: the btree cannot
        serve those without text_pattern_ops or pg_trgm respectively."""
        repo_source = (
            PROJECT_ROOT / "app" / "database" / "conversation_graph_repository.py"
        ).read_text(encoding="utf-8")
        lookup = repo_source.split("def get_conversation_facts_by_labels", 1)[1]
        lookup = lookup.split("\ndef ", 1)[0]
        self.assertIn(".in_(\"label\"", lookup)
        self.assertNotIn(".like(", lookup)
        self.assertNotIn(".ilike(", lookup)

    def test_enables_row_level_security_like_029_and_030(self):
        self.assertIn(
            "alter table public.conversation_graph_nodes enable row level security",
            self.lowered,
        )

    def test_grants_service_role_dml_and_sequence_usage(self):
        self.assertIn("to service_role", self.lowered)
        self.assertIn("usage, select on sequence", self.lowered)

    def test_migration_does_not_alter_the_unknown_document_graph_tables(self):
        """knowledge_graph_nodes has no CREATE TABLE in data/; 033 must not touch it."""
        self.assertNotIn("knowledge_graph_nodes", self.executable)
        self.assertNotIn("knowledge_graph_edges", self.executable)

    def test_a_rollback_exists(self):
        rollback = PROJECT_ROOT / "data" / "041_conversation_graph_nodes_rollback.sql"
        self.assertTrue(rollback.exists(), f"missing rollback: {rollback}")


if __name__ == "__main__":
    unittest.main()
