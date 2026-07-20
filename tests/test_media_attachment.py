import pytest
from unittest.mock import patch, MagicMock
from app.services.media_send_service import (
    find_matching_attachment,
    dispatch_media_after_reply
)

@pytest.fixture
def mock_attachments():
    return [
        {
            "id": 1,
            "label": "Price List",
            "keywords": ["price", "pricing", "cost"],
            "media_url": "https://example.com/price.pdf",
            "media_type": "document"
        },
        {
            "id": 2,
            "label": "Brochure",
            "keywords": ["brochure", "menu"],
            "media_url": "https://example.com/menu.jpg",
            "media_type": "image"
        }
    ]

def test_find_matching_attachment_exact_word(mock_attachments):
    # Should match "price" exactly
    match = find_matching_attachment("What is the price?", mock_attachments)
    assert match is not None
    assert match["id"] == 1

def test_find_matching_attachment_case_insensitive(mock_attachments):
    # Should match "PRICING"
    match = find_matching_attachment("TELL ME THE PRICING", mock_attachments)
    assert match is not None
    assert match["id"] == 1

def test_find_matching_attachment_no_match(mock_attachments):
    # Should not match
    match = find_matching_attachment("Hello there", mock_attachments)
    assert match is None

def test_find_matching_attachment_partial_word_boundary(mock_attachments):
    # "menu" should match
    match = find_matching_attachment("show me the menu please", mock_attachments)
    assert match is not None
    assert match["id"] == 2

    # "menus" shouldn't match if it's alphanumeric and we use \b boundaries
    # Wait, simple \b matches 'menu' but not 'menus'. Let's see:
    match2 = find_matching_attachment("show me the menus", mock_attachments)
    assert match2 is None

@patch("app.services.media_send_service.get_active_attachments")
@patch("app.services.media_send_service.send_wasender_media")
def test_dispatch_media_after_reply_wasender(mock_send, mock_get_attachments, mock_attachments):
    mock_get_attachments.return_value = mock_attachments
    mock_send.return_value = True
    
    channel = {"api_key": "test_key"}
    
    result = dispatch_media_after_reply(
        "What is your cost?", 
        123, 
        "wasender", 
        channel, 
        "1234567890"
    )
    
    assert result is True
    mock_get_attachments.assert_called_once_with(123)
    mock_send.assert_called_once_with("test_key", "1234567890", mock_attachments[0])

@patch("app.services.media_send_service.get_active_attachments")
@patch("app.services.media_send_service.send_telegram_media")
def test_dispatch_media_after_reply_telegram(mock_send, mock_get_attachments, mock_attachments):
    mock_get_attachments.return_value = mock_attachments
    mock_send.return_value = True
    
    channel = {"bot_token": "test_token"}
    
    result = dispatch_media_after_reply(
        "Can I see the brochure?", 
        123, 
        "telegram", 
        channel, 
        "chat_999"
    )
    
    assert result is True
    mock_get_attachments.assert_called_once_with(123)
    mock_send.assert_called_once_with("test_token", "chat_999", mock_attachments[1])

@patch("app.services.media_send_service.get_active_attachments")
def test_dispatch_media_after_reply_no_match(mock_get_attachments, mock_attachments):
    mock_get_attachments.return_value = mock_attachments
    
    result = dispatch_media_after_reply(
        "Hello", 
        123, 
        "wasender", 
        {}, 
        "1234567890"
    )
    
    assert result is False
