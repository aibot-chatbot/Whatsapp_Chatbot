from app.database.bot_repository import get_bot_by_id
from app.database.knowledge_file_repository import get_active_knowledge_file
from app.database.message_repository import get_message_health_by_chatbot
from app.database.telegram_channel_repository import get_telegram_channels_by_chatbot
from app.database.wasender_channel_repository import get_wasender_channels_by_chatbot
from app.database.whatchimp_channel_repository import get_whatchimp_channels_by_chatbot
from app.database.web_widget_repository import get_widget_by_chatbot_id
from app.database.whatsapp_channel_repository import get_whatsapp_channels_by_chatbot
from app.services.settings_service import get_deployed_settings_summary, get_draft_runtime


def _sanitize_error(error):
    if not error:
        return None

    text = str(error)
    sensitive_markers = [
        "access_token",
        "api_key",
        "bot_token",
        "webhook_secret",
        "authorization",
        "bearer ",
        "secret",
        "token",
        "key=",
    ]

    if any(marker in text.lower() for marker in sensitive_markers):
        return "Channel error occurred. Check server logs for details."

    return text[:180]


def _is_connected(channel):
    return (
        bool(channel.get("is_active"))
        and str(channel.get("connection_status") or "").lower() == "connected"
    )


def _channel_item(channel_type, label, channel):
    return {
        "type": channel_type,
        "connected": _is_connected(channel),
        "label": label or "",
        "status": channel.get("connection_status") or "",
        "last_error": _sanitize_error(channel.get("last_error")),
    }


def _widget_item(widget):
    """The share link as a channel.

    The widget has no connection_status column because there is nothing to
    connect to -- we host it. `is_enabled` is the whole state, so it maps
    straight onto `connected`. Without this the dashboard tells an owner who
    published by link that they have not connected a channel.
    """
    enabled = bool(widget.get("is_enabled"))
    return {
        "type": "widget",
        "connected": enabled,
        "label": widget.get("display_name") or "Share link",
        "status": "connected" if enabled else "disabled",
        "last_error": None,
    }


def _get_channel_health(chatbot_id, company_id=None):
    items = []

    widget = get_widget_by_chatbot_id(chatbot_id, company_id)
    if widget:
        items.append(_widget_item(widget))

    for channel in get_telegram_channels_by_chatbot(chatbot_id) or []:
        label = channel.get("bot_username") or channel.get("telegram_bot_id")
        items.append(_channel_item("telegram", label, channel))

    for channel in get_wasender_channels_by_chatbot(chatbot_id) or []:
        label = (
            channel.get("phone_number")
            or channel.get("session_name")
            or channel.get("session_id")
        )
        items.append(_channel_item("wasender", label, channel))

    for channel in get_whatchimp_channels_by_chatbot(chatbot_id) or []:
        label = channel.get("display_phone_number") or channel.get("business_name") or channel.get("phone_number_id")
        items.append(_channel_item("whatchimp", label, channel))

    for channel in get_whatsapp_channels_by_chatbot(chatbot_id) or []:
        label = (
            channel.get("verified_name")
            or channel.get("display_phone_number")
            or channel.get("phone_number_id")
        )
        items.append(_channel_item("whatsapp", label, channel))

    return {
        "connected_count": sum(1 for item in items if item["connected"]),
        "items": items,
    }


def _format_processing_status(status):
    status = str(status or "").lower()

    if status == "completed":
        return "Processed"
    if status == "processing":
        return "Processing"
    if status == "failed":
        return "Processing failed"
    if status == "pending":
        return "Processing pending"

    return status.replace("_", " ").title() if status else ""


def _format_validation_status(last_match_result, last_match_reason=""):
    if last_match_result is True:
        return "Profile validated"
    if last_match_result is False:
        return "Profile mismatch"

    if last_match_reason:
        return "Validation unavailable"

    return "Validation not checked"


def get_dashboard_health(chatbot_id, company_id):
    bot = get_bot_by_id(chatbot_id, company_id) or {}
    settings = get_deployed_settings_summary(chatbot_id)
    runtime = get_draft_runtime(chatbot_id)
    active_profile_name = settings.get("active_profile") or ""
    has_active_profile = bool(
        active_profile_name and active_profile_name.lower() != "none"
    )

    active_knowledge = get_active_knowledge_file(chatbot_id) or {}
    active_knowledge_name = active_knowledge.get("file_name") or ""
    has_active_knowledge = bool(active_knowledge_name)
    processing_status = active_knowledge.get("processing_status") or ""
    processing_label = _format_processing_status(processing_status)
    validation_label = _format_validation_status(
        runtime.get("last_match_result"),
        runtime.get("last_match_reason"),
    )

    channels = _get_channel_health(chatbot_id, company_id)
    delivery_health = get_message_health_by_chatbot(chatbot_id)

    warnings = []
    if not has_active_profile:
        warnings.append("No active AI profile")
    if not has_active_knowledge:
        warnings.append("No active knowledge file")
    if channels["connected_count"] == 0:
        warnings.append("No connected channel")
    if delivery_health["permanent_failed"] > 0:
        warnings.append("Some messages permanently failed")

    ready = (
        has_active_profile
        and channels["connected_count"] > 0
        and delivery_health["permanent_failed"] == 0
    )

    return {
        "ready": ready,
        "status_label": "Ready" if ready else "Needs setup",
        "profile": {
            "active": has_active_profile,
            "name": active_profile_name,
            "ai_provider": bot.get("ai_provider") or "",
            "model_name": bot.get("model_name") or "",
        },
        "knowledge": {
            "active": has_active_knowledge,
            "file_name": active_knowledge_name,
            "processing_status": processing_status,
            "processing_label": processing_label,
            "match_status": active_knowledge.get("match_status") or "",
            "validation_status": validation_label,
            "match_result": runtime.get("last_match_result"),
            # The stored explanation behind a False result. Already persisted by
            # match_routes and already read by get_draft_runtime; forwarding it
            # lets the UI say why a check failed instead of only that it did.
            "match_reason": runtime.get("last_match_reason") or "",
        },
        "channels": channels,
        "delivery": {
            "failed": delivery_health["failed"],
            "retrying": delivery_health["retrying"],
            "permanent_failed": delivery_health["permanent_failed"],
            "last_error": _sanitize_error(delivery_health["last_error"]),
            "last_success_at": delivery_health["last_success_at"],
        },
        "activity": {
            "last_message_at": delivery_health["last_message_at"],
        },
        "warnings": warnings,
    }
