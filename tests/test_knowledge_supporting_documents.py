"""Regressions for documents used as supporting knowledge sources.

A knowledge source used to be either the single active primary document or a
supporting website. Documents can now be supporting sources too, which touches
three seams: the repository query that selects them, the service that enables
them and names their role, and the retrieval budget that searches them.

Also covers the upload promotion gate: a PDF that yields no chunks must never
take the primary slot away from a document that still answers questions.
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch


class _Response:
    def __init__(self, data=None):
        self.data = data if data is not None else []


class _Query:
    """Minimal PostgREST-style chain recorder."""

    def __init__(self, response=None):
        self.response = response or _Response()
        self.table_name = None
        self.updated_payload = None
        self.eq_calls = []
        self.neq_calls = []

    def table(self, table_name):
        self.table_name = table_name
        return self

    def select(self, *args, **kwargs):
        return self

    def update(self, payload):
        self.updated_payload = payload
        return self

    def eq(self, field, value):
        self.eq_calls.append((field, value))
        return self

    def neq(self, field, value):
        self.neq_calls.append((field, value))
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return self.response

    @property
    def eq_fields(self):
        return [field for field, _ in self.eq_calls]


class _SupabaseByTable:
    def __init__(self, table_data):
        self.table_data = table_data

    def table(self, table_name):
        return _Query(_Response(self.table_data.get(table_name, []))).table(table_name)


class TestSupportingKnowledgeRepository(unittest.TestCase):
    def test_supporting_files_include_documents_and_exclude_the_primary(self):
        from app.database import knowledge_file_repository

        rows = [
            {"id": 1, "file_type": "pdf", "is_active": True, "is_enabled": True},
            {"id": 2, "file_type": "pdf", "is_active": False, "is_enabled": True},
            {"id": 3, "file_type": "url", "is_active": None, "is_enabled": True},
        ]
        query = _Query(_Response(rows))

        with patch.object(knowledge_file_repository, "supabase", query):
            files = knowledge_file_repository.get_supporting_knowledge_files(7)

        # The enabled non-primary document is supporting knowledge, the website
        # still is, and the active primary is dropped so retrieval cannot count
        # it twice. A NULL is_active means "not primary" and must survive.
        self.assertEqual([f["id"] for f in files], [2, 3])
        self.assertIn(("chatbot_id", 7), query.eq_calls)
        self.assertIn(("is_enabled", True), query.eq_calls)
        self.assertNotIn("file_type", query.eq_fields)
        self.assertEqual(query.neq_calls, [])

    def test_missing_is_enabled_column_still_excludes_the_primary(self):
        from app.database import knowledge_file_repository

        rows = [
            {"id": 1, "file_type": "pdf", "is_active": True},
            {"id": 2, "file_type": "pdf", "is_active": False},
        ]

        class _DegradedQuery(_Query):
            def __init__(self, response):
                super().__init__(response)
                self.attempts = 0

            def execute(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise Exception('column knowledge_files.is_enabled does not exist')
                return self.response

        query = _DegradedQuery(_Response(rows))

        with patch.object(knowledge_file_repository, "supabase", query):
            files = knowledge_file_repository.get_supporting_knowledge_files(7)

        self.assertEqual([f["id"] for f in files], [2])

    def test_update_supporting_enabled_accepts_any_file_type(self):
        from app.database import knowledge_file_repository

        query = _Query(_Response([{"id": 5, "file_type": "pdf", "is_enabled": True}]))

        with patch.object(knowledge_file_repository, "supabase", query):
            updated = knowledge_file_repository.update_supporting_knowledge_enabled(7, 5, True)

        self.assertEqual(updated["id"], 5)
        self.assertEqual(query.updated_payload, {"is_enabled": True})
        self.assertIn(("chatbot_id", 7), query.eq_calls)
        self.assertIn(("id", 5), query.eq_calls)
        self.assertNotIn("file_type", query.eq_fields)


class TestToggleSupportingKnowledge(unittest.TestCase):
    def _knowledge_file(self, **overrides):
        knowledge_file = {
            "id": 5,
            "file_name": "bot_1_handbook.pdf",
            "file_type": "pdf",
            "is_active": False,
            "is_enabled": False,
        }
        knowledge_file.update(overrides)
        return knowledge_file

    def test_document_can_be_enabled_as_supporting(self):
        from app.services import knowledge_service

        updated_row = self._knowledge_file(is_enabled=True)

        with patch.object(
            knowledge_service,
            "get_knowledge_file_by_name_or_id",
            return_value=self._knowledge_file(),
        ), patch.object(
            knowledge_service,
            "update_supporting_knowledge_enabled",
            return_value=updated_row,
        ) as mock_update:
            result = knowledge_service.toggle_supporting_knowledge(
                "bot_1_handbook.pdf", True, chatbot_id=7,
            )

        self.assertTrue(result["is_enabled"])
        self.assertEqual(result["role"], "supporting")
        self.assertEqual(result["message"], "Supporting source enabled.")
        mock_update.assert_called_once_with(chatbot_id=7, file_id=5, is_enabled=True)

    def test_document_can_be_disabled_again(self):
        from app.services import knowledge_service

        with patch.object(
            knowledge_service,
            "get_knowledge_file_by_name_or_id",
            return_value=self._knowledge_file(is_enabled=True),
        ), patch.object(
            knowledge_service,
            "update_supporting_knowledge_enabled",
            return_value=self._knowledge_file(is_enabled=False),
        ):
            result = knowledge_service.toggle_supporting_knowledge(
                "bot_1_handbook.pdf", False, chatbot_id=7,
            )

        self.assertFalse(result["is_enabled"])
        self.assertEqual(result["role"], "inactive")

    def test_primary_source_cannot_be_toggled(self):
        from app.services import knowledge_service

        with patch.object(
            knowledge_service,
            "get_knowledge_file_by_name_or_id",
            return_value=self._knowledge_file(is_active=True, is_enabled=True),
        ), patch.object(
            knowledge_service, "update_supporting_knowledge_enabled",
        ) as mock_update:
            with self.assertRaises(ValueError) as ctx:
                knowledge_service.toggle_supporting_knowledge(
                    "bot_1_handbook.pdf", False, chatbot_id=7,
                )

        self.assertIn("primary source", str(ctx.exception))
        mock_update.assert_not_called()

    def test_is_enabled_must_be_a_boolean(self):
        from app.services import knowledge_service

        with self.assertRaises(ValueError):
            knowledge_service.toggle_supporting_knowledge(
                "bot_1_handbook.pdf", "yes", chatbot_id=7,
            )


class TestKnowledgeRoleProjection(unittest.TestCase):
    def test_list_uploaded_pdfs_names_the_role(self):
        from app.services import knowledge_service

        rows = [
            {"id": 1, "file_name": "primary.pdf", "file_type": "pdf",
             "is_active": True, "is_enabled": True, "processing_status": "completed"},
            {"id": 2, "file_name": "extra.pdf", "file_type": "pdf",
             "is_active": False, "is_enabled": True, "processing_status": "completed"},
            {"id": 3, "file_name": "old.pdf", "file_type": "pdf",
             "is_active": False, "is_enabled": False, "processing_status": "completed"},
            {"id": 4, "file_name": "https://example.com", "file_type": "url",
             "is_active": False, "is_enabled": True, "processing_status": "completed"},
        ]

        with patch.object(knowledge_service, "get_knowledge_files", return_value=rows):
            files = knowledge_service.list_uploaded_pdfs(7)

        self.assertEqual(
            [f["role"] for f in files],
            ["primary", "supporting", "inactive", "supporting"],
        )
        # Existing consumers must keep every key they already read.
        for key in ("id", "file_name", "name", "size", "file_type",
                    "is_enabled", "is_active", "status"):
            self.assertIn(key, files[0])

    def test_failed_ingest_is_reported_to_the_client(self):
        from app.services import knowledge_service

        rows = [{
            "id": 9, "file_name": "scan.pdf", "file_type": "pdf",
            "is_active": False, "is_enabled": True, "processing_status": "failed",
        }]

        with patch.object(knowledge_service, "get_knowledge_files", return_value=rows):
            files = knowledge_service.list_uploaded_pdfs(7)

        self.assertEqual(files[0]["processing_status"], "failed")


class TestRetrievalIncludesSupportingDocuments(unittest.TestCase):
    QUESTION = "What is the refund window?"
    PRIMARY_CHUNK = "Refund window for the standard catalogue is 30 days."
    SUPPORTING_CHUNK = "Refund window for enterprise plans is 60 days."

    def _chunks_by_file(self, _chatbot_id, file_id, include_embedding=True):
        if file_id == 10:
            return [{"content": self.PRIMARY_CHUNK}]
        return [{"content": self.SUPPORTING_CHUNK}]

    def test_enabled_document_chunks_reach_the_context(self):
        from app.services import rag_service

        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 10}), \
            patch.object(
                rag_service,
                "get_supporting_knowledge_files",
                return_value=[{"id": 20, "file_type": "pdf"}],
            ), \
            patch.object(rag_service, "get_chunks_by_file_for_chatbot", side_effect=self._chunks_by_file), \
            patch.object(rag_service, "generate_embedding", return_value=[]), \
            patch.object(rag_service, "_vector_matches_for_file", return_value=[]):
            result = rag_service.retrieve_relevant_chunks(self.QUESTION, chatbot_id=7, top_k=2)

        joined = "\n".join(result)
        self.assertIn(self.SUPPORTING_CHUNK, joined)
        self.assertIn("Supporting document knowledge", joined)
        # A document must not be announced to the model as a website.
        self.assertNotIn("Supporting website knowledge", joined)

    def test_primary_keeps_a_slot_when_supporting_sources_exist(self):
        from app.services import rag_service

        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value={"id": 10}), \
            patch.object(
                rag_service,
                "get_supporting_knowledge_files",
                return_value=[{"id": 20, "file_type": "pdf"}],
            ), \
            patch.object(rag_service, "get_chunks_by_file_for_chatbot", side_effect=self._chunks_by_file), \
            patch.object(rag_service, "generate_embedding", return_value=[]), \
            patch.object(rag_service, "_vector_matches_for_file", return_value=[]):
            result = rag_service.retrieve_relevant_chunks(self.QUESTION, chatbot_id=7, top_k=1)

        joined = "\n".join(result)
        self.assertIn(self.PRIMARY_CHUNK, joined)

    def test_supporting_website_is_still_labelled_as_a_website(self):
        from app.services import rag_service

        with patch.object(rag_service, "get_active_pdf_knowledge_file", return_value=None), \
            patch.object(
                rag_service,
                "get_supporting_knowledge_files",
                return_value=[{"id": 20, "file_type": "url"}],
            ), \
            patch.object(rag_service, "get_chunks_by_file_for_chatbot", side_effect=self._chunks_by_file), \
            patch.object(rag_service, "generate_embedding", return_value=[]), \
            patch.object(rag_service, "_vector_matches_for_file", return_value=[]):
            result = rag_service.retrieve_relevant_chunks(self.QUESTION, chatbot_id=7, top_k=2)

        self.assertIn("Supporting website knowledge", "\n".join(result))


class TestZeroChunkUploadDoesNotStealPrimary(unittest.TestCase):
    """A PDF that produced no searchable chunk must not become the primary."""

    def _patched_upload(self, chunk_count, extraction_error="", extraction=None):
        from app.services import knowledge_service
        from app.services.document_ocr_service import ExtractionResult

        # _index_pdf_chunks now also returns the extraction record: how the
        # document was read, including whether OCR was involved. The upload
        # copy branches on it, so the fake has to supply one.
        record = extraction if extraction is not None else ExtractionResult(
            page_count=1,
            character_count=120 if chunk_count else 0,
            ocr_available=False,
        )

        return (
            patch.object(knowledge_service, "save_knowledge_file", return_value={"id": 77}),
            patch.object(
                knowledge_service,
                "_index_pdf_chunks",
                return_value=(chunk_count, extraction_error, record),
            ),
            patch.object(knowledge_service, "set_active_pdf_knowledge_file"),
            patch.object(knowledge_service, "update_knowledge_file_status"),
            patch.object(knowledge_service, "update_chatbot_runtime"),
            patch.object(knowledge_service, "generate_and_save_knowledge_readme"),
            patch.object(knowledge_service, "log_knowledge_modification"),
        )

    def _upload(self, tmp_path, chunk_count, extraction_error=""):
        from app.services import knowledge_service

        (save_file, index_chunks, set_active, update_status,
         update_runtime, readme, history) = self._patched_upload(chunk_count, extraction_error)

        with save_file, index_chunks as mock_index, set_active as mock_set_active, \
                update_status as mock_status, update_runtime as mock_runtime, readme, history:
            with patch.object(knowledge_service, "DATA_FOLDER", str(tmp_path)):
                result = knowledge_service.save_uploaded_pdf(_FakeUpload("handbook.pdf"), 7)

        return result, mock_index, mock_set_active, mock_status, mock_runtime

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_zero_chunk_upload_leaves_the_existing_primary_alone(self):
        result, _index, mock_set_active, mock_status, mock_runtime = self._upload(
            self._tmp.name, chunk_count=0, extraction_error="no text layer",
        )

        mock_set_active.assert_not_called()
        mock_runtime.assert_not_called()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["processing_status"], "failed")
        self.assertEqual(result["chunk_count"], 0)
        self.assertIn("not set as primary knowledge", result["message"])
        mock_status.assert_called_once_with(77, processing_status="failed")

    def test_upload_is_never_reported_complete_before_parsing(self):
        from app.services import knowledge_service
        from app.services.document_ocr_service import ExtractionResult

        recorded = {}

        def _record(**kwargs):
            recorded.update(kwargs)
            return {"id": 77}

        with patch.object(knowledge_service, "save_knowledge_file", side_effect=_record), \
            patch.object(knowledge_service, "_index_pdf_chunks", return_value=(0, "", ExtractionResult())), \
            patch.object(knowledge_service, "set_active_pdf_knowledge_file"), \
            patch.object(knowledge_service, "update_knowledge_file_status"), \
            patch.object(knowledge_service, "update_chatbot_runtime"), \
            patch.object(knowledge_service, "generate_and_save_knowledge_readme"), \
            patch.object(knowledge_service, "log_knowledge_modification"), \
            patch.object(knowledge_service, "DATA_FOLDER", self._tmp.name):
            knowledge_service.save_uploaded_pdf(_FakeUpload("handbook.pdf"), 7)

        self.assertNotEqual(recorded.get("processing_status"), "completed")

    def test_upload_with_chunks_becomes_the_primary(self):
        result, _index, mock_set_active, mock_status, mock_runtime = self._upload(
            self._tmp.name, chunk_count=4,
        )

        mock_set_active.assert_called_once_with(chatbot_id=7, file_id=77)
        mock_status.assert_called_once_with(77, processing_status="completed")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["chunk_count"], 4)
        self.assertTrue(mock_runtime.called)


class TestKnowledgeReadmeDisplayNames(unittest.TestCase):
    def test_readme_uses_original_file_name_for_visible_document_title(self):
        from app.services import knowledge_service

        internal_name = "bot_7_123e4567_policy.pdf"
        readable_name = "policy.pdf"

        with tempfile.TemporaryDirectory() as tmpdir, \
            patch.object(knowledge_service, "DATA_FOLDER", tmpdir), \
            patch(
                "app.database.db.supabase",
                _SupabaseByTable({
                    "knowledge_files": [{
                        "id": 55,
                        "chatbot_id": 7,
                        "file_name": internal_name,
                        "original_file_name": readable_name,
                    }],
                    "knowledge_graph_nodes": [],
                    "knowledge_graph_edges": [],
                }),
            ), \
            patch(
                "app.database.knowledge_file_repository.get_active_pdf_knowledge_file",
                return_value={"id": 55, "file_name": internal_name, "original_file_name": readable_name},
            ), \
            patch(
                "app.database.knowledge_chunk_repository.get_chunks_by_file_for_chatbot",
                return_value=[{"content": "Refund policy text", "metadata": {"chunk_index": 0}}],
            ):
            knowledge_service.generate_and_save_knowledge_readme(7, 55)

            readme = Path(tmpdir, "bot_7_55_readme.md").read_text(encoding="utf-8")

        self.assertIn(f"# Knowledge Base README: {readable_name}", readme)
        self.assertIn(f"compiled knowledge source for Chatbot #7, extracted from the document `{readable_name}`", readme)
        self.assertNotIn(f"# Knowledge Base README: {internal_name}", readme)
        self.assertNotIn(f"document `{internal_name}`", readme)
        self.assertNotIn("primary document", readme)


class _FakeUpload:
    """Stand-in for the werkzeug FileStorage the upload route passes in."""

    def __init__(self, filename):
        self.filename = filename

    def save(self, path):
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4\n")


if __name__ == "__main__":
    unittest.main()
