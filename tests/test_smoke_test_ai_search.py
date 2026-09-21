"""Tests for scripts/smoke_test_ai_search.py.

The script's whole value is its verdict: run against live Cloudflare it must say
"leak" when a chatbot receives a chunk it does not own, and must not say "pass"
when it in fact proved nothing. That verdict logic is what is pinned here.

No test performs network or database I/O. The stand-in service keeps the *real*
module's parsing helpers (``_documents``, ``_document_file_name``) and fakes only
the two seams that leave the process -- so these cases are fed the payload shape
Cloudflare actually sends, parsed by the code that will actually parse it.
"""

import importlib.util
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path

from app.services import ai_search_service

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_test_ai_search.py"


def load_script():
    spec = importlib.util.spec_from_file_location("smoke_test_ai_search", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SECRET_TEXT = "tenant-document-body-that-must-never-be-printed"


def envelope(*file_names):
    """A response in the shape the live instance was confirmed to send."""
    return {
        "query_kind": "text",
        "search_query": "anything",
        "chunks": [
            {
                "id": name,
                "type": "text",
                "score": 0.59,
                "text": SECRET_TEXT,
                "item": {"key": f"knowledge/{name}", "timestamp": 1789393920000},
                "scoring_details": {"vector_score": 0.59},
            }
            for name in file_names
        ],
    }


def doc(chatbot_id):
    return f"bot_{chatbot_id}_49_readme.md"


def fake_service(responses, owned, kept):
    """Real parsing, faked I/O.

    ``responses`` and ``owned`` are keyed by chatbot id; anything absent behaves
    as "Cloudflare answered nothing" and "this chatbot owns nothing".
    """
    return types.SimpleNamespace(
        _documents=ai_search_service._documents,
        _document_file_name=ai_search_service._document_file_name,
        _max_num_results=ai_search_service._max_num_results,
        _tenant_filter_value=ai_search_service._tenant_filter_value,
        _owned_file_names=lambda cid: owned.get(int(cid), set()),
        _post_search=lambda tenant, query, count: responses.get(int(tenant)),
        search_chunks=lambda query, cid, top_k=3: list(kept.get(int(cid), [])),
    )


class SmokeTestAiSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script()

    def healthy(self):
        """Every chatbot behaving exactly as the live ground truth says it should."""
        mod = self.mod
        responses, owned, kept = {}, {}, {}
        for cid in mod.OWNING_CHATBOT_IDS:
            owned[cid] = {doc(cid)}
            responses[cid] = envelope(doc(cid))
            kept[cid] = [f"Supporting document knowledge:\n{SECRET_TEXT}"]
        for cid in mod.ORPHAN_CHATBOT_IDS:
            # In the index, but no knowledge_files rows: Cloudflare answers and
            # the application must discard every chunk.
            owned[cid] = set()
            responses[cid] = envelope(doc(cid))
            kept[cid] = []
        owned[mod.ABSENT_CHATBOT_ID] = set()
        responses[mod.ABSENT_CHATBOT_ID] = envelope()
        return responses, owned, kept

    def run_with(self, responses, owned, kept):
        return self.mod.run(fake_service(responses, owned, kept), "a query", 10)

    # -- the clean run ----------------------------------------------------

    def test_a_healthy_instance_passes(self):
        code, lines = self.run_with(*self.healthy())

        self.assertEqual(code, 0, "\n".join(lines))
        self.assertNotIn("LEAK", "\n".join(lines))

    def test_a_clean_run_never_prints_chunk_text(self):
        _, lines = self.run_with(*self.healthy())

        self.assertNotIn(SECRET_TEXT, "\n".join(lines))
        self.assertIn(doc(53), "\n".join(lines))

    def test_every_chatbot_in_the_ground_truth_is_probed(self):
        _, lines = self.run_with(*self.healthy())
        report = "\n".join(lines)

        for cid in self.mod.OWNING_CHATBOT_IDS + self.mod.ORPHAN_CHATBOT_IDS:
            self.assertIn(f"chatbot {cid}", report)
        self.assertIn(f"chatbot {self.mod.ABSENT_CHATBOT_ID}", report)

    # -- the leaks --------------------------------------------------------

    def test_an_orphan_chatbot_that_keeps_a_chunk_fails(self):
        responses, owned, kept = self.healthy()
        orphan = self.mod.ORPHAN_CHATBOT_IDS[3]
        kept[orphan] = [f"Supporting document knowledge:\n{SECRET_TEXT}"]

        code, lines = self.run_with(responses, owned, kept)

        self.assertEqual(code, 1)
        self.assertNotEqual(code, 0)
        self.assertIn("LEAK", "\n".join(lines))

    def test_an_owning_chatbot_that_keeps_a_foreign_chunk_fails(self):
        responses, owned, kept = self.healthy()
        victim = self.mod.OWNING_CHATBOT_IDS[3]
        # Cloudflare hands back one owned chunk and one belonging to chatbot 99,
        # and the service keeps both.
        responses[victim] = envelope(doc(victim), doc(99))
        kept[victim] = [
            f"Supporting document knowledge:\n{SECRET_TEXT}",
            f"Supporting document knowledge:\n{SECRET_TEXT}",
        ]

        code, lines = self.run_with(responses, owned, kept)

        self.assertEqual(code, 1)
        self.assertIn("LEAK", "\n".join(lines))

    def test_the_nonexistent_chatbot_returning_a_chunk_fails(self):
        responses, owned, kept = self.healthy()
        absent = self.mod.ABSENT_CHATBOT_ID
        responses[absent] = envelope(doc(53))
        kept[absent] = [f"Supporting document knowledge:\n{SECRET_TEXT}"]

        code, _ = self.run_with(responses, owned, kept)

        self.assertEqual(code, 1)

    # -- the ways a pass would prove nothing ------------------------------

    def test_a_contained_remote_leak_is_still_a_failure(self):
        """The remote filter leaks, the application discards it: not a pass."""
        responses, owned, kept = self.healthy()
        victim = self.mod.OWNING_CHATBOT_IDS[0]
        responses[victim] = envelope(doc(victim), doc(99))

        code, lines = self.run_with(responses, owned, kept)

        self.assertEqual(code, 2)
        self.assertIn("discarded them", "\n".join(lines))

    def test_an_unavailable_ownership_check_is_not_a_pass(self):
        responses, owned, kept = self.healthy()
        owned[self.mod.OWNING_CHATBOT_IDS[0]] = None
        kept[self.mod.OWNING_CHATBOT_IDS[0]] = []

        code, lines = self.run_with(responses, owned, kept)

        self.assertEqual(code, 2)
        self.assertIn("ownership check could not run", "\n".join(lines))

    def test_a_query_that_matches_nothing_is_not_a_pass(self):
        responses, owned, kept = self.healthy()
        for cid in self.mod.OWNING_CHATBOT_IDS:
            responses[cid] = envelope()
            kept[cid] = []

        code, lines = self.run_with(responses, owned, kept)

        self.assertEqual(code, 2)
        self.assertIn("--query", "\n".join(lines))

    def test_an_owning_chatbot_with_no_rows_is_not_a_pass(self):
        responses, owned, kept = self.healthy()
        drifted = self.mod.OWNING_CHATBOT_IDS[2]
        owned[drifted] = set()
        kept[drifted] = []

        code, lines = self.run_with(responses, owned, kept)

        self.assertEqual(code, 2)
        self.assertIn("ground truth has drifted", "\n".join(lines))

    def test_a_leak_outranks_an_anomaly(self):
        responses, owned, kept = self.healthy()
        responses[self.mod.ABSENT_CHATBOT_ID] = envelope(doc(53))
        orphan = self.mod.ORPHAN_CHATBOT_IDS[0]
        kept[orphan] = [f"Supporting document knowledge:\n{SECRET_TEXT}"]

        code, _ = self.run_with(responses, owned, kept)

        self.assertEqual(code, 1)

    # -- configuration ----------------------------------------------------

    def test_missing_configuration_names_the_variable(self):
        absent = self.mod.missing_env({"AI_SEARCH_ENABLED": "1", "R2_ACCOUNT_ID": "  "})

        self.assertIn("R2_ACCOUNT_ID", absent)
        self.assertIn("AI_SEARCH_API_TOKEN", absent)
        self.assertNotIn("AI_SEARCH_ENABLED", absent)

    def test_full_configuration_reports_nothing_missing(self):
        environ = {name: "set" for name in self.mod.REQUIRED_ENV}

        self.assertEqual(self.mod.missing_env(environ), [])

    def test_help_runs_with_no_credentials(self):
        """--help must not need the app import chain, let alone credentials."""
        env = {
            "SystemRoot": os.environ.get("SystemRoot", ""),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--query", result.stdout)
        self.assertIn("--top-k", result.stdout)


if __name__ == "__main__":
    unittest.main()
