import time
import threading
import logging
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g, current_app

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.database.broadcast_repository import (
    create_campaign,
    get_campaigns,
    get_campaign_by_id,
    update_campaign_status,
    create_broadcast_log,
    get_broadcast_logs_by_campaign,
    update_broadcast_log_status
)

broadcast_blueprint = Blueprint("broadcast", __name__)

def process_broadcast_dispatch(app_ctx_obj, campaign, pending_logs):
    """Background worker function executing the sequential message dispatch loop."""
    with app_ctx_obj.app_context():
        campaign_id = campaign["id"]
        company_id = campaign["company_id"]
        chatbot_id = campaign["chatbot_id"]
        channel_type = campaign["channel_type"]
        message_template = campaign["message_template"]

        if message_template == "__use_bot_welcome_flow__":
            from app.database.bot_repository import get_bot_by_id
            bot = get_bot_by_id(chatbot_id, company_id)
            message_template = bot.get("welcome_message") if bot else ""
            if not message_template:
                message_template = "Hello! Welcome to our service."

        # Resolve channel configuration
        channel_config = None
        if channel_type == "whatsapp":
            from app.database.whatsapp_channel_repository import get_whatsapp_channels_by_chatbot
            channels = get_whatsapp_channels_by_chatbot(chatbot_id)
            active = [c for c in channels if c.get("is_active")]
            if active:
                channel_config = active[0]
        elif channel_type == "wasender":
            from app.database.wasender_channel_repository import get_wasender_channels_by_chatbot
            channels = get_wasender_channels_by_chatbot(chatbot_id)
            active = [c for c in channels if c.get("is_active")]
            if active:
                channel_config = active[0]

        if not channel_config:
            # Mark all as failed if no channel is found
            for log in pending_logs:
                update_broadcast_log_status(
                    log["id"],
                    "failed",
                    error_message="No active connection channel found."
                )
            update_campaign_status(campaign_id, company_id, "failed")
            return

        success_count = 0
        fail_count = 0

        for log in pending_logs:
            log_id = log["id"]
            phone = log["recipient_phone"]

            # Token replacement
            message_text = message_template.replace("{{phone}}", phone)

            # Update recipient status to sending
            update_broadcast_log_status(log_id, "sending")

            sent_ok = False
            err_msg = None

            try:
                if channel_type == "whatsapp":
                    from app.utils.whatsapp_utils import send_message, get_text_message_input, get_interactive_button_message_input
                    import re

                    button_matches = re.findall(r"\[BUTTON:\s*(.*?)\]", message_text, re.IGNORECASE)
                    if button_matches:
                        clean_text = re.sub(r"\[BUTTON:\s*(.*?)\]", "", message_text, flags=re.IGNORECASE).strip()
                        button_labels = [b.strip() for b in button_matches[:3] if b.strip()]
                        data = get_interactive_button_message_input(phone, clean_text, button_labels)
                    else:
                        data = get_text_message_input(phone, message_text)

                    res = send_message(data, channel_config)
                    if isinstance(res, tuple):
                        sent_ok = False
                        try:
                            flask_res = res[0]
                            err_msg = flask_res.get_json().get("message", "Failed to send message")
                        except Exception:
                            err_msg = str(res[0])
                    elif hasattr(res, "status_code") and res.status_code >= 400:
                        sent_ok = False
                        err_msg = f"HTTP {res.status_code}: {res.text}"
                    else:
                        sent_ok = True
                elif channel_type == "wasender":
                    from app.services.wasender_service import send_wasender_text_message
                    api_key = channel_config["api_key"]
                    res = send_wasender_text_message(api_key, phone, message_text)
                    if res and res.get("success"):
                        sent_ok = True
                    else:
                        sent_ok = False
                        err_msg = res.get("error") if res else "WasenderAPI failure"
            except Exception as e:
                sent_ok = False
                err_msg = str(e)

            if sent_ok:
                sent_at = datetime.now(timezone.utc).isoformat()
                update_broadcast_log_status(log_id, "sent", sent_at=sent_at)
                success_count += 1
            else:
                update_broadcast_log_status(log_id, "failed", error_message=err_msg)
                fail_count += 1

            # Inter-message delay (3 seconds) to prevent Meta/Wasender spam-blocking
            time.sleep(3)

        # Update final campaign status
        final_status = "completed" if success_count > 0 else "failed"
        update_campaign_status(campaign_id, company_id, final_status)


@broadcast_blueprint.route("/api/broadcast/campaigns", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_campaigns():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400
        verify_chatbot_access(chatbot_id)

        campaigns = get_campaigns(g.company_id, chatbot_id)
        return jsonify({"status": "success", "campaigns": campaigns})
    except Exception as e:
        logging.error(f"Failed to fetch campaigns: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@broadcast_blueprint.route("/api/broadcast/campaign", methods=["POST"])
@token_required
@role_required("admin", "owner")
def save_campaign():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400
        verify_chatbot_access(chatbot_id)

        data = request.get_json() or {}
        name = data.get("name", "").strip()
        channel_type = data.get("channel_type", "whatsapp").strip()
        message_template = data.get("message_template", "").strip()
        recipients = data.get("recipients", [])

        if not name or not message_template or not recipients:
            return jsonify({"status": "error", "message": "name, message_template, and recipients are required"}), 400

        campaign = create_campaign(g.company_id, chatbot_id, name, channel_type, message_template)
        if not campaign:
            return jsonify({"status": "error", "message": "Failed to create campaign"}), 500

        # Register pending logs for the recipients
        for r in recipients:
            phone = r.get("phone", "").strip()
            # Normalize: remove symbols except leading '+' or digits
            phone = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
            if phone:
                create_broadcast_log(campaign["id"], phone, status="pending")

        return jsonify({"status": "success", "campaign": campaign})
    except Exception as e:
        logging.error(f"Failed to save campaign: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@broadcast_blueprint.route("/api/broadcast/campaign/<int:campaign_id>/logs", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_campaign_logs(campaign_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400
        verify_chatbot_access(chatbot_id)

        campaign = get_campaign_by_id(campaign_id, g.company_id)
        if not campaign:
            return jsonify({"status": "error", "message": "Campaign not found"}), 404

        logs = get_broadcast_logs_by_campaign(campaign_id)
        return jsonify({"status": "success", "logs": logs})
    except Exception as e:
        logging.error(f"Failed to fetch logs: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@broadcast_blueprint.route("/api/broadcast/campaign/<int:campaign_id>/start", methods=["POST"])
@token_required
@role_required("admin", "owner")
def start_campaign(campaign_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400
        verify_chatbot_access(chatbot_id)

        campaign = get_campaign_by_id(campaign_id, g.company_id)
        if not campaign:
            return jsonify({"status": "error", "message": "Campaign not found"}), 404

        if campaign["status"] in ("sending", "completed"):
            return jsonify({"status": "error", "message": f"Campaign already in status: {campaign['status']}"}), 400

        logs = get_broadcast_logs_by_campaign(campaign_id)
        pending_logs = [l for l in logs if l["status"] == "pending"]

        if not pending_logs:
            update_campaign_status(campaign_id, g.company_id, "completed")
            return jsonify({"status": "success", "message": "No pending recipients found."})

        # Update campaign status
        update_campaign_status(campaign_id, g.company_id, "sending")

        # Spawn worker thread with active app context reference
        app_ctx_obj = current_app._get_current_object()
        thread = threading.Thread(
            target=process_broadcast_dispatch,
            args=(app_ctx_obj, campaign, pending_logs)
        )
        thread.start()

        return jsonify({"status": "success", "message": "Campaign broadcast started successfully."})
    except Exception as e:
        logging.error(f"Failed to start campaign: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
