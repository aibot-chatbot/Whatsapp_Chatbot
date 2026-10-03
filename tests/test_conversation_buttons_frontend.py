"""The Conversations page shows a reply's [BUTTONS: ...] options as chips, not raw text.

Bot replies are stored with the tag (every channel needs it to rebuild its own
buttons), so the staff view must strip it before display. Source-level check,
matching how the other frontend pages are pinned in this suite.
"""

from pathlib import Path

PAGE = (Path(__file__).resolve().parents[1] / "frontend" / "conversations.html").read_text(encoding="utf-8")


def _bubble_source():
    start = PAGE.index("function buildBubble(")
    return PAGE[start:PAGE.index("\n        }\n", start)]


def test_bubble_text_is_rendered_without_the_buttons_tag():
    bubble = _bubble_source()
    assert "splitButtonsTag(message.message_text" in bubble
    assert "escapeHtml(message.message_text || '')}</span>" not in bubble


def test_only_bot_replies_are_read_as_offered_buttons_with_the_channel_limits():
    bubble = _bubble_source()
    assert "message.sender_type === 'bot'" in bubble
    helper = PAGE[PAGE.index("function splitButtonsTag("):PAGE.index("function announce(")]
    assert ".slice(0, 20)" in helper and ".slice(0, 3)" in helper  # same caps as parse_buttons_tag


def test_offered_buttons_render_as_escaped_chips():
    bubble = _bubble_source()
    assert 'data-part="buttons"' in bubble
    assert "escapeHtml(label)" in bubble
