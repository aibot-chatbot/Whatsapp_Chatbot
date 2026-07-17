"""Generic menu-code retrieval regressions for RAG."""

import unittest
from unittest.mock import patch


class TestRagMenuCodeRetrieval(unittest.TestCase):
    def test_detect_menu_code_accepts_short_codes(self):
        from app.services.rag_service import detect_menu_code

        self.assertEqual(detect_menu_code("A"), "A")
        self.assertEqual(detect_menu_code(" a "), "A")
        self.assertEqual(detect_menu_code("A1"), "A1")
        self.assertEqual(detect_menu_code("b2"), "B2")
        self.assertEqual(detect_menu_code("A1.1"), "A1.1")
        self.assertEqual(detect_menu_code("A2.8.3"), "A2.8.3")

    def test_detect_menu_code_rejects_normal_questions(self):
        from app.services.rag_service import detect_menu_code

        self.assertIsNone(detect_menu_code("Hi"))
        self.assertIsNone(detect_menu_code("What are your services?"))
        self.assertIsNone(detect_menu_code("A 1"))
        self.assertIsNone(detect_menu_code("AA"))

    def test_exact_input_a_prioritizes_trigger_chunk_before_semantic_fallback(self):
        from app.services import rag_service

        chunks = [
            {"content": 'Trigger Keyword: User replies with "A"\nChatbot Response: Show option A details.'},
            {"content": "General company overview and unrelated details."},
        ]

        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 10}), \
            patch.object(rag_service, "get_supporting_knowledge_files", return_value=[]), \
            patch.object(rag_service, "get_chunks_by_file_for_chatbot", return_value=chunks), \
            patch.object(rag_service, "generate_embedding") as mock_embedding, \
            patch.object(rag_service, "_vector_matches_for_file", return_value=[]) as mock_vector:
            result = rag_service.retrieve_relevant_chunks("A", chatbot_id=7, top_k=1)

        self.assertTrue(result)
        self.assertIn('User replies with "A"', result[0])
        mock_embedding.assert_not_called()
        mock_vector.assert_not_called()

    def test_exact_input_a_does_not_match_a1_trigger(self):
        from app.services import rag_service

        chunks = [
            {"content": 'Trigger Keyword: User replies with "A1"\nChatbot Response: Show option A1 details.'},
        ]

        result = rag_service.find_chunks_for_exact_code(
            chatbot_id=7,
            file_id=10,
            code="A",
            chunks=chunks,
        )

        self.assertEqual(result, [])

    def test_exact_input_a1_prioritizes_code_chunk(self):
        from app.services import rag_service

        chunks = [
            {"content": "A1: This is the generic submenu content for code A1."},
            {"content": "Some other neutral knowledge content."},
        ]

        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 11}), \
            patch.object(rag_service, "get_supporting_knowledge_files", return_value=[]), \
            patch.object(rag_service, "get_chunks_by_file_for_chatbot", return_value=chunks), \
            patch.object(rag_service, "generate_embedding", return_value=[]):
            result = rag_service.retrieve_relevant_chunks("A1", chatbot_id=7, top_k=3)

        self.assertTrue(result)
        self.assertIn("A1:", result[0])

    def test_exact_input_a1_1_prioritizes_code_chunk(self):
        from app.services import rag_service

        chunks = [
            {"content": "A1.1. This chunk explains a generic nested menu action."},
            {"content": "Normal unrelated content."},
        ]

        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 12}), \
            patch.object(rag_service, "get_supporting_knowledge_files", return_value=[]), \
            patch.object(rag_service, "get_chunks_by_file_for_chatbot", return_value=chunks), \
            patch.object(rag_service, "generate_embedding", return_value=[]):
            result = rag_service.retrieve_relevant_chunks("A1.1", chatbot_id=7, top_k=3)

        self.assertTrue(result)
        self.assertIn("A1.1.", result[0])

    def test_non_code_question_uses_normal_semantic_rag(self):
        from app.services import rag_service

        chunks = [{"content": "General product and service information."}]

        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 13}), \
            patch.object(rag_service, "get_supporting_knowledge_files", return_value=[]), \
            patch.object(rag_service, "get_chunks_by_file_for_chatbot", return_value=chunks), \
            patch.object(rag_service, "find_chunks_for_exact_code") as mock_exact, \
            patch.object(rag_service, "generate_embedding", return_value=[0.1]), \
            patch.object(rag_service, "_vector_matches_for_file", return_value=[{"content": "Semantic match content."}]):
            result = rag_service.retrieve_relevant_chunks("What services are available?", chatbot_id=7, top_k=3)

        mock_exact.assert_not_called()
        self.assertTrue(result)
        self.assertIn("Semantic match content", result[0])


class TestGreetingStillBypassesRag(unittest.TestCase):
    def test_hi_still_uses_greeting_handler(self):
        from app.services import chat_pipeline_service

        with patch.object(chat_pipeline_service, "get_or_create_conversation", return_value={"id": 1, "company_id": 2}), \
            patch.object(chat_pipeline_service, "get_recent_chat_history", return_value=[]), \
            patch("app.database.agent_action_repository.is_conversation_escalated", return_value=False), \
            patch.object(chat_pipeline_service, "analyze_agent_intent", return_value={"intent": "greeting", "suggested_action": "none", "confidence": 1.0}), \
            patch.object(chat_pipeline_service, "save_agent_action"), \
            patch.object(chat_pipeline_service, "create_crm_lead_from_agent_signal"), \
            patch.object(chat_pipeline_service, "handle_greeting", return_value="Hello menu"), \
            patch.object(chat_pipeline_service, "retrieve_relevant_chunks") as mock_retrieve:
            result = chat_pipeline_service.prepare_chat_prompt("Hi", "customer", 7)

        self.assertEqual(result["direct_reply"], "Hello menu")
        self.assertEqual(result["intent"], "greeting")
        mock_retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
