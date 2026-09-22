from unittest.mock import patch

from app.services import knowledge_service
from app.services.document_ocr_service import ExtractionResult


class Upload:
    filename = "policy.pdf"

    def save(self, path):
        with open(path, "wb") as handle:
            handle.write(b"%PDF-1.4\n")


def test_completed_document_ingest_enqueues_follow_up(tmp_path):
    with patch.object(knowledge_service, "DATA_FOLDER", str(tmp_path)), \
        patch.object(knowledge_service, "save_knowledge_file", return_value={"id": 77}), \
        patch.object(knowledge_service, "_index_pdf_chunks", return_value=(4, "", ExtractionResult(page_count=1, character_count=100))), \
        patch.object(knowledge_service, "update_knowledge_file_status"), \
        patch.object(knowledge_service, "set_active_pdf_knowledge_file"), \
        patch.object(knowledge_service, "update_chatbot_runtime"), \
        patch.object(knowledge_service, "generate_and_save_knowledge_readme"), \
        patch.object(knowledge_service, "log_knowledge_modification"), \
        patch("app.database.bot_repository.get_bot_by_id", return_value={"id": 7, "company_id": 42}), \
        patch("app.services.automation_service.schedule_knowledge_document_follow_up") as schedule:
        result = knowledge_service.save_uploaded_pdf(Upload(), 7)

    assert result["status"] == "completed"
    schedule.assert_called_once_with(
        company_id=42,
        chatbot_id=7,
        file_id=77,
        display_name="policy.pdf",
        chunk_count=4,
        target_role="primary",
    )
