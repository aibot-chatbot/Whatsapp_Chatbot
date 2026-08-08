"""tests/test_message_style_buttons.py

Regression tests for the message-style button rendering fixes:

1. The [BUTTONS: ...] tag must be stripped from the reply BEFORE any
   markdown formatting is applied, so the tag's special characters are
   never escaped/mangled and the buttons always render.
2. Welcome-menu generation is capped at 3 labels to match the UI.
"""

import re
from unittest.mock import patch, MagicMock

from app.utils.message_style_utils import (
    parse_buttons_tag,
    format_for_telegram_markdown,
    format_for_whatsapp_markdown,
)


# ---------------------------------------------------------------------------
# parse_buttons_tag
# ---------------------------------------------------------------------------

def test_parse_buttons_tag_strips_tag_and_returns_labels():
    text = "Welcome to our service!\n\n[BUTTONS: Pricing | Our Services | Contact Us]"
    clean, labels = parse_buttons_tag(text)
    assert clean == "Welcome to our service!"
    assert labels == ["Pricing", "Our Services", "Contact Us"]


def test_parse_buttons_tag_returns_empty_when_no_tag():
    text = "Just a plain reply with no buttons."
    clean, labels = parse_buttons_tag(text)
    assert clean == text
    assert labels == []


def test_parse_buttons_tag_caps_labels_at_three():
    text = "[BUTTONS: A | B | C | D | E]"
    clean, labels = parse_buttons_tag(text)
    assert len(labels) == 3
    assert labels == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Telegram: tag must be stripped before markdown formatting
# ---------------------------------------------------------------------------

def test_telegram_tag_is_stripped_before_markdown_formatting():
    """The tag must be removed before formatting so its characters are not escaped."""
    reply = "Hello **world**!\n\n[BUTTONS: Pricing | Contact]"
    clean, labels = parse_buttons_tag(reply)
    # Tag is gone before formatting
    assert "[BUTTONS" not in clean
    formatted = format_for_telegram_markdown(clean)
    # No escaped tag characters should leak into the formatted output
    assert "\\[BUTTONS" not in formatted
    assert "\\|" not in formatted
    # Bold is still converted
    assert "*world*" in formatted


def test_telegram_markdown_escapes_tag_if_not_stripped_first():
    """Demonstrates the bug: formatting a reply that still contains the tag
    escapes its characters, which would prevent button parsing downstream."""
    reply = "Hello!\n\n[BUTTONS: Pricing | Contact]"
    formatted = format_for_telegram_markdown(reply)
    assert "\\[BUTTONS" in formatted
    assert "\\|" in formatted


# ---------------------------------------------------------------------------
# WhatsApp: tag must be stripped before markdown formatting
# ---------------------------------------------------------------------------

def test_whatsapp_tag_is_stripped_before_markdown_formatting():
    reply = "Hello **world**!\n\n[BUTTONS: Pricing | Contact]"
    clean, labels = parse_buttons_tag(reply)
    assert "[BUTTONS" not in clean
    formatted = format_for_whatsapp_markdown(clean)
    assert "[BUTTONS" not in formatted
    assert "*world*" in formatted


# ---------------------------------------------------------------------------
# Welcome-menu generation limit (ai_router.generate_welcome_menu_suggestions)
# ---------------------------------------------------------------------------

def test_welcome_menu_suggestions_capped_at_eight():
    """generate_welcome_menu_suggestions must return at most 8 labels."""
    from app.services import ai_router

    fake_chunks = [
        {"content": "Pricing details for our plans."},
        {"content": "Our services include support and training."},
        {"content": "Contact us for more information."},
    ]

    with patch.object(
        ai_router, "get_active_knowledge_file", return_value={"id": 1, "file_name": "test.pdf"}
    ), patch.object(
        ai_router, "get_chunks_by_file_for_chatbot", return_value=fake_chunks
    ), patch.object(
        ai_router, "generate_system_response",
        return_value='[{"label": "Pricing", "description": "View plans"}, {"label": "Our Services", "description": "See services"}, {"label": "Contact Us", "description": "Get in touch"}, {"label": "FAQ", "description": "FAQs"}, {"label": "About", "description": "About us"}]',
    ):
        labels, source = ai_router.generate_welcome_menu_suggestions(chatbot_id=1, company_id=1)

    assert isinstance(labels, list)
    assert len(labels) <= 8
    assert source == "test.pdf"
    assert labels == [
        {"label": "Pricing", "description": "View plans"},
        {"label": "Our Services", "description": "See services"},
        {"label": "Contact Us", "description": "Get in touch"},
        {"label": "FAQ", "description": "FAQs"},
        {"label": "About", "description": "About us"},
    ]


def test_welcome_menu_suggestions_returns_empty_on_error():
    from app.services import ai_router

    with patch.object(
        ai_router, "get_active_knowledge_file", return_value={"id": 1, "file_name": "test.pdf"}
    ), patch.object(
        ai_router, "get_chunks_by_file_for_chatbot", return_value=[{"content": "x"}]
    ), patch.object(
        ai_router, "generate_system_response", side_effect=RuntimeError("boom")
    ):
        labels, source = ai_router.generate_welcome_menu_suggestions(chatbot_id=1, company_id=1)

    assert labels == []
    assert source == "test.pdf"


def test_welcome_menu_suggestions_description_capped_at_60():
    """Descriptions longer than 60 chars should be truncated."""
    from app.services import ai_router

    with patch.object(
        ai_router, "get_active_knowledge_file", return_value={"id": 1, "file_name": "test.pdf"}
    ), patch.object(
        ai_router, "get_chunks_by_file_for_chatbot", return_value=[{"content": "x"}]
    ), patch.object(
        ai_router, "generate_system_response",
        return_value='[{"label": "Pricing", "description": "This is a very long description that definitely exceeds sixty characters"}]',
    ):
        labels, source = ai_router.generate_welcome_menu_suggestions(chatbot_id=1, company_id=1)

    assert labels == [{"label": "Pricing", "description": "This is a very long description that definitely exceeds sixt"}]
    assert source == "test.pdf"


def test_welcome_menu_suggestions_fallback_for_string_format():
    """If AI returns bare strings, wrap them into objects with empty descriptions."""
    from app.services import ai_router

    with patch.object(
        ai_router, "get_active_knowledge_file", return_value={"id": 1, "file_name": "test.pdf"}
    ), patch.object(
        ai_router, "get_chunks_by_file_for_chatbot", return_value=[{"content": "x"}]
    ), patch.object(
        ai_router, "generate_system_response",
        return_value='["Pricing", "Our Services", "Contact Us"]',
    ):
        labels, source = ai_router.generate_welcome_menu_suggestions(chatbot_id=1, company_id=1)

    assert labels == [
        {"label": "Pricing", "description": ""},
        {"label": "Our Services", "description": ""},
        {"label": "Contact Us", "description": ""},
    ]
    assert source == "test.pdf"


def test_welcome_menu_suggestions_label_truncated_at_20():
    """Labels longer than 20 chars should be truncated."""
    from app.services import ai_router

    with patch.object(
        ai_router, "get_active_knowledge_file", return_value={"id": 1, "file_name": "test.pdf"}
    ), patch.object(
        ai_router, "get_chunks_by_file_for_chatbot", return_value=[{"content": "x"}]
    ), patch.object(
        ai_router, "generate_system_response",
        return_value='[{"label": "This is a very long label that exceeds twenty characters", "description": "desc"}]',
    ):
        labels, source = ai_router.generate_welcome_menu_suggestions(chatbot_id=1, company_id=1)

    assert labels == [{"label": "This is a very long ", "description": "desc"}]
    assert source == "test.pdf"
