"""Deleted document caches must not remain readable or affect other files."""

import json
from unittest.mock import Mock

import pytest

from app.database import knowledge_graph_repository
from app.services import knowledge_service


@pytest.mark.parametrize("reader", ["readme", "history"])
def test_cached_content_requires_a_current_scoped_document(tmp_path, monkeypatch, reader):
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(tmp_path))
    (tmp_path / "bot_7_55_readme.md").write_text("deleted client text", encoding="utf-8")
    (tmp_path / "bot_7_55_history.json").write_text(
        json.dumps([{"action": "deleted client text"}]), encoding="utf-8"
    )
    lookup = Mock(return_value=None)
    generate = Mock()
    monkeypatch.setattr(knowledge_service, "get_knowledge_file_by_name_or_id", lookup)
    monkeypatch.setattr(knowledge_service, "generate_and_save_knowledge_readme", generate)

    result = (
        knowledge_service.get_or_generate_readme(7, 55)
        if reader == "readme"
        else knowledge_service.get_knowledge_history_logs(7, 55)
    )

    assert "deleted client text" not in str(result)
    lookup.assert_called_once_with(7, 55)
    generate.assert_not_called()


def test_owned_document_cache_remains_readable(tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(tmp_path))
    monkeypatch.setattr(
        knowledge_service, "get_knowledge_file_by_name_or_id", Mock(return_value={"id": 55})
    )
    (tmp_path / "bot_7_55_readme.md").write_text("current client text", encoding="utf-8")
    (tmp_path / "bot_7_55_history.json").write_text(
        json.dumps([{"action": "updated graph"}]), encoding="utf-8"
    )

    assert knowledge_service.get_or_generate_readme(7, 55) == "current client text"
    assert knowledge_service.get_knowledge_history_logs(7, 55) == [
        {"action": "updated graph", "category": "Graph Modifications"}
    ]


@pytest.mark.parametrize("is_active", [False, True])
def test_delete_removes_only_the_selected_document_artifacts(tmp_path, monkeypatch, is_active):
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(tmp_path))
    selected = ["bot_7_doc.pdf", "bot_7_55_readme.md", "bot_7_55_history.json"]
    unrelated = ["bot_8_55_readme.md", "bot_8_55_history.json", "bot_7_56_readme.md", "other.pdf"]
    for name in selected + unrelated + ["bot_7_readme.md"]:
        (tmp_path / name).write_text(name, encoding="utf-8")
    record = {"id": 55, "file_name": "bot_7_doc.pdf", "file_path": str(tmp_path / selected[0])}
    monkeypatch.setattr(knowledge_service, "get_knowledge_file_by_name_or_id", Mock(return_value=record))
    monkeypatch.setattr(
        knowledge_service, "get_active_knowledge_file", Mock(return_value={"id": 55 if is_active else 56})
    )
    delete_chunks = Mock()
    delete_file = Mock()
    monkeypatch.setattr(knowledge_service, "delete_chunks_by_file_for_chatbot", delete_chunks)
    monkeypatch.setattr(knowledge_service, "delete_knowledge_file_by_id", delete_file)
    monkeypatch.setattr(knowledge_graph_repository, "delete_graph_by_file_id", Mock())
    monkeypatch.setattr(knowledge_service, "update_chatbot_runtime", Mock())

    knowledge_service.delete_pdf_file("bot_7_doc.pdf", 7)

    assert all(not (tmp_path / name).exists() for name in selected)
    assert all((tmp_path / name).read_text(encoding="utf-8") == name for name in unrelated)
    assert (tmp_path / "bot_7_readme.md").exists() is not is_active
    delete_chunks.assert_called_once_with(7, 55)
    delete_file.assert_called_once_with(7, 55)


def test_delete_does_not_follow_a_stored_path_outside_data_folder(tmp_path, monkeypatch):
    data_folder = tmp_path / "data"
    data_folder.mkdir()
    outside_file = tmp_path / "other-client.pdf"
    outside_file.write_text("keep outside data", encoding="utf-8")
    monkeypatch.setattr(knowledge_service, "DATA_FOLDER", str(data_folder))
    monkeypatch.setattr(
        knowledge_service,
        "get_knowledge_file_by_name_or_id",
        Mock(return_value={"id": 55, "file_name": "doc.pdf", "file_path": str(outside_file)}),
    )
    monkeypatch.setattr(knowledge_service, "get_active_knowledge_file", Mock(return_value=None))
    monkeypatch.setattr(knowledge_service, "delete_chunks_by_file_for_chatbot", Mock())
    monkeypatch.setattr(knowledge_service, "delete_knowledge_file_by_id", Mock())
    monkeypatch.setattr(knowledge_graph_repository, "delete_graph_by_file_id", Mock())

    knowledge_service.delete_pdf_file("doc.pdf", 7)

    assert outside_file.read_text(encoding="utf-8") == "keep outside data"
