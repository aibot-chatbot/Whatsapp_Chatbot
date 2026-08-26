import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NEW_PROMPT = ROOT / "frontend" / "new_prompt.html"
BEHAVIOUR_JS = ROOT / "frontend" / "assets" / "js" / "behaviour.js"
NEW_LINKDOCS = ROOT / "frontend" / "new_linkdocs.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


class TestKnowledgeUiDisplayConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.new_prompt = _read(NEW_PROMPT)
        cls.behaviour = _read(BEHAVIOUR_JS)
        cls.linkdocs = _read(NEW_LINKDOCS)

    def test_new_prompt_uses_readable_active_knowledge_display_name(self):
        self.assertIn("function sourceDisplayName(item, fallback = \"\")", self.new_prompt)
        self.assertIn("item?.display_name || item?.original_file_name || item?.file_name", self.new_prompt)
        self.assertIn("state.activeKnowledge = active.file_name || \"\";", self.new_prompt)
        self.assertIn(
            "state.activeKnowledgeDisplayName = sourceDisplayName(active, state.activeKnowledge);",
            self.new_prompt,
        )
        self.assertIn(
            "knowledge: done.knowledge ? activeKnowledgeLabel() : \"Add primary knowledge.\"",
            self.new_prompt,
        )
        self.assertIn(
            "\"Active primary knowledge\", activeKnowledgeLabel() || \"Not selected\"",
            self.new_prompt,
        )

    def test_new_prompt_preserves_internal_identifier_for_state_checks(self):
        self.assertIn("activeKnowledge: \"\"", self.new_prompt)
        self.assertIn("if (!state.active || !state.activeKnowledge) return;", self.new_prompt)
        self.assertIn("Boolean(state.activeKnowledge)", self.new_prompt)
        self.assertNotIn("bot_53_a88bed7fee6f4c2f8a1f055318c6a5d0_Speedbot.pdf", self.new_prompt)

    def test_test_lab_loads_canonical_active_primary_source(self):
        self.assertIn("/api/testbot/context?chatbot_id=", self.behaviour)
        self.assertIn("/api/knowledge/active?chatbot_id=", self.behaviour)
        self.assertIn("var activeKnowledge = {};", self.behaviour)
        self.assertIn("Object.assign({ _loaded: true }, body.data || {})", self.behaviour)

    def test_test_lab_serializes_context_before_scenario_rendering(self):
        self.assertRegex(
            self.behaviour,
            re.compile(
                r"if \(tab === \"test\"\) \{\s*"
                r"renderChatEmpty\(\);\s*"
                r"loadTestContext\(\)\.then\(function \(\) \{\s*"
                r"return loadScenarios\(false\);\s*"
                r"\}\);\s*"
                r"\}",
                re.S,
            ),
        )
        self.assertNotIn("loadTestContext();\n            loadScenarios(false);", self.behaviour)

    def test_test_lab_prefers_readable_active_primary_label(self):
        self.assertIn("function sourceDisplayName(item, fallback)", self.behaviour)
        self.assertIn("item.display_name || item.original_file_name || item.file_name", self.behaviour)
        self.assertRegex(
            self.behaviour,
            re.compile(
                r"var knowledge = activeKnowledge\._loaded\s*\?\s*sourceDisplayName\(activeKnowledge, \"\"\)",
                re.S,
            ),
        )
        self.assertIn("setupItem(\"Knowledge\", hasKnowledge ? knowledge : \"None active\"", self.behaviour)

    def test_test_lab_scenario_note_uses_readable_active_primary_display_name(self):
        self.assertIn("loaded.source_document = body.data.source_document || \"\";", self.behaviour)
        self.assertIn("sessionStorage.setItem(SCENARIO_CACHE_KEY, JSON.stringify(loaded))", self.behaviour)
        self.assertIn(
            "var scenarioSourceName = sourceDisplayName(activeKnowledge, scenarios.source_document);",
            self.behaviour,
        )
        self.assertIn("? \"Matched to \" + scenarioSourceName + \".\"", self.behaviour)
        self.assertNotIn("? \"Matched to \" + scenarios.source_document + \".\"", self.behaviour)

    def test_test_lab_rerenders_cached_scenarios_after_active_primary_loads(self):
        self.assertRegex(
            self.behaviour,
            re.compile(
                r"await loadActiveKnowledge\(\);\s*"
                r"if \(scenarios && !scenarios\.loading\) \{\s*"
                r"renderScenarios\(\);\s*"
                r"\}",
                re.S,
            ),
        )

    def test_test_lab_keeps_none_active_for_genuinely_empty_primary(self):
        self.assertRegex(
            self.behaviour,
            re.compile(
                r"var hasKnowledge = activeKnowledge\._loaded\s*\?\s*Boolean\(activeKnowledge\.file_name\)",
                re.S,
            ),
        )
        self.assertIn("knowledge !== \"No active PDF\"", self.behaviour)

    def test_test_lab_does_not_promote_supporting_source_to_primary_label(self):
        self.assertIn("/api/knowledge/active?chatbot_id=", self.behaviour)
        self.assertNotIn(".filter(isWebsite)", self.behaviour)
        self.assertNotIn("is_enabled) ? sourceDisplayName", self.behaviour)

    def test_test_lab_chat_endpoint_remains_unchanged(self):
        self.assertIn("/api/testbot/chat?chatbot_id=", self.behaviour)
        self.assertIn("appendChat(message, \"user\")", self.behaviour)

    def test_knowledge_workspace_display_rule_remains_available(self):
        self.assertIn("const getSourceDisplayName = (item, fallback = \"Untitled source\")", self.linkdocs)
        self.assertIn("item?.display_name || item?.original_file_name || item?.file_name", self.linkdocs)


if __name__ == "__main__":
    unittest.main()
