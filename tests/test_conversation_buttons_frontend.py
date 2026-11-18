"""The Conversations page shows a reply's [BUTTONS: ...] options as chips, not raw text.

Bot replies are stored with the tag (every channel needs it to rebuild its own
buttons), so the staff view must strip it before display. Source-level check,
matching how the other frontend pages are pinned in this suite.
"""

import pytest

from tests.frontend_pages import WEB_PUBLIC_JS, page_source_path


@pytest.fixture(scope="module")
def page():
    markup = page_source_path("conversations.html").read_text(encoding="utf-8")
    return markup + (WEB_PUBLIC_JS / "conversations.js").read_text(encoding="utf-8")


def _bubble_source(page):
    start = page.index("function buildBubble(")
    return page[start:page.index("\n        }\n", start)]


def test_bubble_text_is_rendered_without_the_buttons_tag(page):
    bubble = _bubble_source(page)
    assert "splitButtonsTag(message.message_text" in bubble
    assert "escapeHtml(message.message_text || '')}</span>" not in bubble


def test_only_bot_replies_are_read_as_offered_buttons_with_the_channel_limits(page):
    bubble = _bubble_source(page)
    assert "message.sender_type === 'bot'" in bubble
    helper = page[page.index("function splitButtonsTag("):page.index("function announce(")]
    assert ".slice(0, 20)" in helper and ".slice(0, 3)" in helper  # same caps as parse_buttons_tag


def test_offered_buttons_render_as_escaped_chips(page):
    bubble = _bubble_source(page)
    assert 'data-part="buttons"' in bubble
    assert "escapeHtml(label)" in bubble
