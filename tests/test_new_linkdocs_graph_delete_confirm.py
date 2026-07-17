"""Regressions for knowledge graph delete confirmation UI."""

from pathlib import Path
import re
import unittest


class TestNewLinkdocsGraphDeleteConfirm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = Path("frontend/new_linkdocs.html").read_text(encoding="utf-8")

    def _const_function(self, name):
        match = re.search(
            rf"const {name} = .*?=> \{{(?P<body>.*?)\n            \}};",
            self.html,
            flags=re.S,
        )
        self.assertIsNotNone(match, f"{name} was not found")
        return match.group("body")

    def test_graph_node_delete_no_longer_uses_browser_confirm(self):
        handler = self._const_function("handleDeleteNode")

        self.assertNotIn("window.confirm", handler)
        self.assertIn("setDeleteNodeTarget({", handler)
        self.assertNotIn("authenticatedFetch", handler)
        self.assertNotIn('method: "DELETE"', handler)

    def test_graph_relationship_delete_no_longer_uses_browser_confirm(self):
        handler = self._const_function("handleDeleteRelation")

        self.assertNotIn("window.confirm", handler)
        self.assertIn("setDeleteRelationTarget({", handler)
        self.assertNotIn("authenticatedFetch", handler)
        self.assertNotIn('method: "DELETE"', handler)

    def test_custom_delete_modal_text_exists(self):
        self.assertIn("Delete Node?", self.html)
        self.assertIn(
            "Deleting this node will also remove its connected relationships.",
            self.html,
        )
        self.assertIn("Delete Relationship?", self.html)
        self.assertIn(
            "This relationship will be permanently removed.",
            self.html,
        )
        self.assertIn("Delete Node", self.html)
        self.assertIn("Delete Relationship", self.html)

    def test_node_delete_request_only_runs_after_modal_confirm(self):
        opener = self._const_function("handleDeleteNode")
        confirmer = self._const_function("confirmDeleteNode")

        self.assertIn("setDeleteNodeTarget({", opener)
        self.assertNotIn("authenticatedFetch", opener)
        self.assertIn("if (!deleteNodeTarget || isDeletingGraphItem) return;", confirmer)
        self.assertIn("setIsDeletingGraphItem(true);", confirmer)
        self.assertIn("/api/knowledge/graph/node?chatbot_id=", confirmer)
        self.assertIn('method: "DELETE"', confirmer)
        self.assertIn("setDeleteNodeTarget(null);", confirmer)
        self.assertIn("setIsDeletingGraphItem(false);", confirmer)

    def test_relationship_delete_request_only_runs_after_modal_confirm(self):
        opener = self._const_function("handleDeleteRelation")
        confirmer = self._const_function("confirmDeleteRelation")

        self.assertIn("setDeleteRelationTarget({", opener)
        self.assertNotIn("authenticatedFetch", opener)
        self.assertIn("if (!deleteRelationTarget || isDeletingGraphItem) return;", confirmer)
        self.assertIn("setIsDeletingGraphItem(true);", confirmer)
        self.assertIn("/api/knowledge/graph/edge?chatbot_id=", confirmer)
        self.assertIn('method: "DELETE"', confirmer)
        self.assertIn("setDeleteRelationTarget(null);", confirmer)
        self.assertIn("setIsDeletingGraphItem(false);", confirmer)


if __name__ == "__main__":
    unittest.main()
