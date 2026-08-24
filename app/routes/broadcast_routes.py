import time
import threading
import logging
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request, g, current_app

from app.decorators.auth_decorator import token_required
from app.services.company_status_service import company_operational_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.database.broadcast_repository import (
    create_campaign,
    get_campaigns,
    get_campaign_by_id,
    update_campaign_status,
    create_broadcast_log,
    get_broadcast_logs_by_campaign,
    update_broadcast_log_status,
    update_campaign,
    delete_campaign,
    count_broadcast_logs_by_status,
    cancel_pending_broadcast_logs,
    delete_broadcast_logs_by_campaign
)

# Recipient statuses that mean "this recipient is finished with".
TERMINAL_LOG_STATUSES = ("sent", "failed", "cancelled")

# Campaign statuses an operator may still edit or remove.
EDITABLE_CAMPAIGN_STATUSES = ("draft",)
DELETABLE_CAMPAIGN_STATUSES = ("draft", "completed", "failed", "cancelled")

broadcast_blueprint = Blueprint("broadcast", __name__)

def process_broadcast_dispatch(app_ctx_obj, campaign, pending_logs):
    """Background worker function executing the sequential message dispatch loop."""
    with app_ctx_obj.app_context():
        campaign_id = campaign["id"]
        company_id = campaign["company_id"]
        chatbot_id = campaign["chatbot_id"]
        channel_type = campaign["channel_type"]
        message_template = campaign["message_template"]
        try:
            from app.services.company_status_service import ensure_company_operational
            ensure_company_operational(company_id)
        except Exception:
            for log in pending_logs:
                update_broadcast_log_status(
                    log["id"],
                    "failed",
                    error_message="Company is suspended."
                )
            update_campaign_status(campaign_id, company_id, "failed")
            return

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

        for index, log in enumerate(pending_logs):
            log_id = log["id"]
            phone = log["recipient_phone"]

            # Token replacement
            message_text = message_template.replace("{{phone}}", phone)

            try:
                ensure_company_operational(company_id)
            except Exception:
                for remaining_log in pending_logs[index:]:
                    update_broadcast_log_status(
                        remaining_log["id"],
                        "failed",
                        error_message="Company is suspended."
                    )
                update_campaign_status(campaign_id, company_id, "failed")
                return

            # Stop signal. The operator sets the campaign to 'cancelling' from
            # the dispatch console; this loop is the only thing that can act on
            # it, because it owns the pacing sleep between messages.
            #
            # ponytail: one extra SELECT per message, at a 3s cadence. A
            # threading.Event would avoid the read but only works when the
            # canceller and the worker share a process -- under gunicorn they
            # usually do not, so the flag has to live in the database.
            try:
                current = get_campaign_by_id(campaign_id, company_id)
            except Exception as read_error:
                # A transient read failure must not abandon a send that is
                # already half delivered. The stop button still works on the
                # next message, and the operator sees no change until it does.
                logging.warning(
                    f"Broadcast campaign {campaign_id}: could not read cancel "
                    f"flag, continuing. {read_error}"
                )
                current = None

            if current and current.get("status") == "cancelling":
                cancel_pending_broadcast_logs(campaign_id)
                update_campaign_status(campaign_id, company_id, "cancelled")
                logging.info(
                    f"Broadcast campaign {campaign_id} cancelled after "
                    f"{success_count} sent, {fail_count} failed."
                )
                return

            # Update recipient status to sending
            update_broadcast_log_status(log_id, "sending")

            sent_ok = False
            err_msg = None

            try:
                media_attachment_id = campaign.get("media_attachment_id")
                
                # Fetch media attachment if provided
                attachment = None
                if media_attachment_id:
                    from app.database.bot_media_attachment_repository import get_attachment_by_id
                    attachment = get_attachment_by_id(media_attachment_id, chatbot_id)

                if channel_type == "whatsapp":
                    from app.utils.whatsapp_utils import send_message, get_text_message_input, get_interactive_button_message_input
                    import re

                    meta_template_name = campaign.get("meta_template_name")
                    meta_language_code = campaign.get("meta_language_code", "en_US")

                    if attachment and meta_template_name:
                        from app.services.media_send_service import send_meta_media_template
                        sent_ok = send_meta_media_template(channel_config, attachment, phone)
                        if not sent_ok:
                            err_msg = "Failed to send meta media template"
                    elif meta_template_name:
                        # Construct a Meta API Template JSON payload
                        import json
                        data = json.dumps({
                            "messaging_product": "whatsapp",
                            "to": phone,
                            "type": "template",
                            "template": {
                                "name": meta_template_name,
                                "language": { "code": meta_language_code }
                            }
                        })
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
                    else:
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
                    
                    if attachment:
                        from app.services.media_send_service import send_wasender_media
                        # Override caption with the broadcast message text
                        attachment_copy = attachment.copy()
                        attachment_copy["caption"] = message_text
                        sent_ok = send_wasender_media(api_key, phone, attachment_copy)
                        if not sent_ok:
                            err_msg = "Wasender API media failure"
                    else:
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
@company_operational_required
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
        meta_template_name = data.get("meta_template_name", "").strip()
        meta_language_code = data.get("meta_language_code", "en_US").strip()
        media_attachment_id = data.get("media_attachment_id")
        recipients = data.get("recipients", [])

        if not name or not message_template or not recipients:
            return jsonify({"status": "error", "message": "name, message_template, and recipients are required"}), 400

        try:
            if media_attachment_id:
                media_attachment_id = int(media_attachment_id)
        except (ValueError, TypeError):
            media_attachment_id = None

        campaign = create_campaign(g.company_id, chatbot_id, name, channel_type, message_template, meta_template_name, meta_language_code, media_attachment_id)
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
@company_operational_required
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

        if campaign["status"] in ("cancelling", "cancelled"):
            return jsonify({
                "status": "error",
                "message": "This campaign was cancelled. Duplicate it to send to the remaining recipients."
            }), 400

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


def _normalize_phone(raw):
    """E.164-ish normalisation: keep digits and a single leading '+'."""
    return "".join(ch for ch in (raw or "").strip() if ch.isdigit() or ch == "+")


@broadcast_blueprint.route("/api/broadcast/campaign/<int:campaign_id>", methods=["PATCH"])
@token_required
@company_operational_required
@role_required("admin", "owner")
def edit_campaign(campaign_id):
    """Corrects a draft in place, so a typo does not cost a rebuild.

    Draft-only on purpose: once a campaign is sending, its recipient rows are
    the worker's live queue, and rewriting them underneath it would send the
    wrong message to the wrong people.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400
        verify_chatbot_access(chatbot_id)

        campaign = get_campaign_by_id(campaign_id, g.company_id)
        if not campaign:
            return jsonify({"status": "error", "message": "Campaign not found"}), 404

        if campaign["status"] not in EDITABLE_CAMPAIGN_STATUSES:
            return jsonify({
                "status": "error",
                "message": "Only a draft can be edited. This campaign has already been dispatched."
            }), 400

        data = request.get_json() or {}
        fields = {}

        if "name" in data:
            name = (data.get("name") or "").strip()
            if not name:
                return jsonify({"status": "error", "message": "Campaign name cannot be empty"}), 400
            fields["name"] = name

        if "message_template" in data:
            message_template = (data.get("message_template") or "").strip()
            if not message_template:
                return jsonify({"status": "error", "message": "Message cannot be empty"}), 400
            fields["message_template"] = message_template

        if "channel_type" in data:
            fields["channel_type"] = (data.get("channel_type") or "whatsapp").strip()
        if "meta_template_name" in data:
            fields["meta_template_name"] = (data.get("meta_template_name") or "").strip()
        if "meta_language_code" in data:
            fields["meta_language_code"] = (data.get("meta_language_code") or "en_US").strip()
        if "media_attachment_id" in data:
            try:
                media_attachment_id = data.get("media_attachment_id")
                fields["media_attachment_id"] = int(media_attachment_id) if media_attachment_id else None
            except (ValueError, TypeError):
                fields["media_attachment_id"] = None

        recipients = data.get("recipients")
        if recipients is not None:
            phones = []
            seen = set()
            for r in recipients:
                phone = _normalize_phone(r.get("phone") if isinstance(r, dict) else r)
                if phone and phone not in seen:
                    seen.add(phone)
                    phones.append(phone)
            if not phones:
                return jsonify({"status": "error", "message": "At least one valid recipient is required"}), 400

            # Replace wholesale rather than diff: a draft's rows are all
            # pending, so there is no per-recipient state worth preserving.
            delete_broadcast_logs_by_campaign(campaign_id)
            for phone in phones:
                create_broadcast_log(campaign_id, phone, status="pending")

        updated = update_campaign(campaign_id, g.company_id, fields) if fields else campaign
        return jsonify({"status": "success", "campaign": updated or campaign})
    except Exception as e:
        logging.error(f"Failed to edit campaign: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@broadcast_blueprint.route("/api/broadcast/campaign/<int:campaign_id>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def remove_campaign(campaign_id):
    """Removes a campaign and its recipient rows.

    Blocked while a send is in flight: the worker holds those rows and would
    keep writing to them after the delete, resurrecting orphans.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400
        verify_chatbot_access(chatbot_id)

        campaign = get_campaign_by_id(campaign_id, g.company_id)
        if not campaign:
            return jsonify({"status": "error", "message": "Campaign not found"}), 404

        if campaign["status"] not in DELETABLE_CAMPAIGN_STATUSES:
            return jsonify({
                "status": "error",
                "message": "This campaign is still sending. Stop it first, then delete it."
            }), 400

        delete_campaign(campaign_id, g.company_id)
        return jsonify({"status": "success", "message": "Campaign deleted."})
    except Exception as e:
        logging.error(f"Failed to delete campaign: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@broadcast_blueprint.route("/api/broadcast/campaign/<int:campaign_id>/progress", methods=["GET"])
@token_required
@role_required("admin", "owner")
def campaign_progress(campaign_id):
    """Recipient tallies for the dispatch console, polled during a send."""
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400
        verify_chatbot_access(chatbot_id)

        campaign = get_campaign_by_id(campaign_id, g.company_id)
        if not campaign:
            return jsonify({"status": "error", "message": "Campaign not found"}), 404

        counts = count_broadcast_logs_by_status(campaign_id)
        total = sum(counts.values())
        done = sum(counts.get(status, 0) for status in TERMINAL_LOG_STATUSES)

        return jsonify({
            "status": "success",
            "campaign_status": campaign["status"],
            "total": total,
            "done": done,
            "sent": counts.get("sent", 0),
            "failed": counts.get("failed", 0),
            "pending": counts.get("pending", 0),
            "sending": counts.get("sending", 0),
            "cancelled": counts.get("cancelled", 0),
        })
    except Exception as e:
        logging.error(f"Failed to fetch campaign progress: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@broadcast_blueprint.route("/api/broadcast/campaign/<int:campaign_id>/cancel", methods=["POST"])
@token_required
@role_required("admin", "owner")
def cancel_campaign(campaign_id):
    """Asks the dispatch worker to stop after the message it is on.

    This does not unsend anything. Messages already delivered stay delivered;
    the endpoint only stops the queue, so the response says how many recipients
    were spared rather than claiming the campaign was undone.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400
        verify_chatbot_access(chatbot_id)

        campaign = get_campaign_by_id(campaign_id, g.company_id)
        if not campaign:
            return jsonify({"status": "error", "message": "Campaign not found"}), 404

        campaign_status = campaign["status"]

        if campaign_status == "sending":
            # The worker polls this status between messages and does the
            # cleanup itself, so it never writes to a row after we clear it.
            update_campaign_status(campaign_id, g.company_id, "cancelling")
            remaining = count_broadcast_logs_by_status(campaign_id).get("pending", 0)
            return jsonify({
                "status": "success",
                "message": f"Stopping. {remaining} recipient(s) will not be messaged.",
                "campaign_status": "cancelling",
            })

        if campaign_status == "draft":
            cancelled = cancel_pending_broadcast_logs(campaign_id)
            update_campaign_status(campaign_id, g.company_id, "cancelled")
            return jsonify({
                "status": "success",
                "message": f"Cancelled. {cancelled} recipient(s) will not be messaged.",
                "campaign_status": "cancelled",
            })

        return jsonify({
            "status": "error",
            "message": f"Nothing to stop. This campaign is {campaign_status}."
        }), 400
    except Exception as e:
        logging.error(f"Failed to cancel campaign: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
