import logging
from unittest.mock import Mock

import pytest

from app.database import chat_history_repository, conversation_repository
from app.services import ai_router


@pytest.fixture
def storage(monkeypatch):
    state = {"history_summary": "Prefers delivery.", "history_summary_through_id": 20}
    monkeypatch.setattr(conversation_repository, "get_conversation_by_id_and_chatbot",
                        lambda conversation_id, chatbot_id: state)
    candidates = Mock()
    save = Mock(return_value=True)
    ai = Mock(return_value="Asked about delivery.")
    monkeypatch.setattr(chat_history_repository, "get_summary_candidates", candidates, raising=False)
    monkeypatch.setattr(conversation_repository, "save_history_summary", save, raising=False)
    monkeypatch.setattr(ai_router, "generate_system_response", ai)
    return candidates, save, ai


def test_only_fold_an_eligible_batch_and_bill_once(storage):
    from app.services.conversation_summary_service import compact_if_due

    candidates, save, ai = storage
    rows = [
        {"id": 21, "sender_type": "customer", "content": "My IC is 991231-14-4321."},
        {"id": 22, "sender_type": "bot", "content": "We deliver."},
        {"id": 23, "sender_type": "human", "content": "We can check Tuesday."},
        {"id": 24, "sender_type": "customer", "content": "online casino"},
        {"id": 25, "sender_type": "customer", "content": "Thanks."},
        {"id": 26, "sender_type": "customer", "content": "excluded by moderation", "blocked": True},
    ]
    candidates.return_value = rows[:5]
    compact_if_due(7, 9)
    ai.assert_not_called()
    save.assert_not_called()

    candidates.return_value = rows
    compact_if_due(7, 9)
    candidates.assert_called_with(7, 9, 20, keep_recent=6, limit=40)
    ai.assert_called_once()
    request = ai.call_args.kwargs
    assert request["chatbot_id"] == 9
    assert request["operation_type"] == "conversation_summary"
    for expected in ("Prefers delivery.", "Customer", "Bot", "Staff", "We deliver.",
                     "We can check Tuesday.", "[IC number hidden]", "untrusted"):
        assert expected in request["prompt"]
    for excluded in ("991231-14-4321", "online casino", "excluded by moderation"):
        assert excluded not in request["prompt"]
    save.assert_called_once_with(7, 9, "Asked about delivery.", 26, expected_through_id=20)


def test_an_unknown_sender_type_still_folds_so_the_conversation_never_stalls(storage):
    from app.services.conversation_summary_service import compact_if_due

    candidates, save, ai = storage
    candidates.return_value = [
        {"id": i, "sender_type": "customer" if i < 26 else "system", "content": f"Message {i}."}
        for i in range(21, 27)
    ]
    compact_if_due(7, 9)
    assert "Message 26." in ai.call_args.kwargs["prompt"]
    save.assert_called_once_with(7, 9, "Asked about delivery.", 26, expected_through_id=20)


def test_all_flagged_advances_watermark_without_rewriting_summary_or_billing(storage):
    from app.services.conversation_summary_service import compact_if_due

    candidates, save, ai = storage
    candidates.return_value = [
        {"id": i, "sender_type": "customer", "content": "online casino"} for i in range(21, 27)
    ]
    compact_if_due(7, 9)
    ai.assert_not_called()
    save.assert_called_once_with(7, 9, "Prefers delivery.", 26, expected_through_id=20)


@pytest.mark.parametrize("fence", ["```text", "~~~ plain text"])
def test_saved_summary_strips_control_markers_and_redacts_before_character_cap(storage, fence):
    from app.services.conversation_summary_service import compact_if_due

    candidates, save, ai = storage
    candidates.return_value = [{"id": i, "sender_type": "bot", "content": "Hello."} for i in range(21, 27)]
    ai.return_value = (
        f'{fence}\n' '<<NEEDS {"goal":"hidden"}>> <<BOOKING {"name":"secret"}>> '
        '<SILENT_BOT_RESPONSE> IC 991231-14-4321, card 4111 1111 1111 1111.\n'
        + "A" * 1400 + "\n" + fence[:3]
    )
    compact_if_due(7, 9)
    saved = save.call_args.args[2]
    assert saved.startswith("IC [IC number hidden], card [card number hidden].")
    assert len(saved) == 1200
    assert all(token not in saved for token in ("```", "<<", "<SILENT", "hidden\"", "secret"))


@pytest.mark.parametrize("result", [
    RuntimeError("private fixture text"), "  ", "<SILENT_BOT_RESPONSE>",
    "Sorry, an error occurred generating the response.",
])
def test_failure_keeps_summary_and_logs_only_exception_class(storage, result, caplog):
    from app.services.conversation_summary_service import compact_if_due

    candidates, save, ai = storage
    candidates.return_value = [
        {"id": i, "sender_type": "customer", "content": "private fixture text"} for i in range(21, 27)
    ]
    if isinstance(result, Exception):
        ai.side_effect = result
    else:
        ai.return_value = result
    with caplog.at_level(logging.WARNING):
        compact_if_due(7, 9)
    save.assert_not_called()
    assert caplog.records and all(record.exc_info is None for record in caplog.records)
    assert "RuntimeError" in caplog.text or "ValueError" in caplog.text
    assert "private fixture text" not in caplog.text
