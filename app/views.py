import logging
import json

from flask import Blueprint, request, jsonify, current_app, abort, send_from_directory, g
import os
from werkzeug.utils import secure_filename

from .decorators.security import signature_required
from app.decorators.auth_decorator import token_required
from .utils.whatsapp_utils import (
    process_whatsapp_message,
    is_valid_whatsapp_message,
)
from app.services.knowledge_service import save_uploaded_pdf
from app.services.persona_derivation_service import derive_persona_for_upload
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import can_upload_knowledge_file, can_upload_knowledge_storage, BillingLimitError
from app.services.company_status_service import company_operational_required

webhook_blueprint = Blueprint("webhook", __name__)
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

@webhook_blueprint.route("/", methods=["GET"])
def serve_frontend_root():
    return send_from_directory(FRONTEND_DIR, "landing.html")


def handle_message():
    """
    Handle incoming webhook events from the WhatsApp API.

    This function processes incoming WhatsApp messages and other events,
    such as delivery statuses. If the event is a valid message, it gets
    processed. If the incoming payload is not a recognized WhatsApp event,
    an error is returned.

    Every message send will trigger 4 HTTP requests to your webhook: message, sent, delivered, read.

    Returns:
        response: A tuple containing a JSON response and an HTTP status code.
    """
    body = request.get_json()
    logging.info(f"request body: {body}")

    # Check if it's a WhatsApp status update
    if (
        body.get("entry", [{}])[0]
        .get("changes", [{}])[0]
        .get("value", {})
        .get("statuses")
    ):
        logging.info("Received a WhatsApp status update.")
        return jsonify({"status": "ok"}), 200

    try:
        if is_valid_whatsapp_message(body):
            logging.info("Valid WhatsApp message received.")
            process_whatsapp_message(body)
            return jsonify({"status": "ok"}), 200
        else:
            return (
                jsonify({"status": "error", "message": "Not a WhatsApp API event"}),
                404,
            )
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": "Internal error"}), 500

# Required webhook verifictaion for WhatsApp
def verify():
    # Parse params from the webhook verification request
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    # Check if a token and mode were sent
    if mode and token:
        # Check the mode and token sent are correct
        if mode == "subscribe" and token == current_app.config["VERIFY_TOKEN"]:
            # Respond with 200 OK and challenge token from the request
            logging.info("WEBHOOK_VERIFIED")
            return challenge, 200
        else:
            # Responds with '403 Forbidden' if verify tokens do not match
            logging.info("VERIFICATION_FAILED")
            return jsonify({"status": "error", "message": "Verification failed"}), 403
    else:
        # Responds with '400 Bad Request' if verify tokens do not match
        logging.info("MISSING_PARAMETER")
        return jsonify({"status": "error", "message": "Missing parameters"}), 400

@webhook_blueprint.route("/webhook", methods=["GET"])
def webhook_get():
    return verify()

@webhook_blueprint.route("/webhook", methods=["POST"])
@signature_required
def webhook_post():
    return handle_message()

@webhook_blueprint.route("/upload-pdf", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def upload_pdf():
    chatbot_id = None
    try:
        if "pdf_file" not in request.files:
            return jsonify({"message": "No file part"}), 400

        file = request.files["pdf_file"]

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        # Determine file size before saving (seek to end, then reset)
        file.seek(0, 2)
        incoming_size = file.tell()
        file.seek(0)

        # Check subscription limits before file upload
        can_upload_knowledge_file(g.company_id)
        can_upload_knowledge_storage(g.company_id, incoming_size)
        result = save_uploaded_pdf(file, chatbot_id)

        # Fill company_name / business_description / tone from the document the
        # client just uploaded, so a client who never opened the settings form
        # does not get a bot introducing itself as an assistant for "Your
        # Company". Never overwrites a value the client typed, and never fails
        # the upload -- the outcome is reported instead of raised.
        derivation = derive_persona_for_upload(chatbot_id)

        # The upload itself succeeded even when extraction produced nothing, so
        # the row exists and the caller must be able to see that outcome rather
        # than a blanket "uploaded" claim. The status travels in the body.
        return jsonify({
            "status": result.get("status", "completed"),
            "processing_status": result.get("processing_status", "completed"),
            "chunk_count": result.get("chunk_count", 0),
            # What was read and how, including whether OCR was involved, so the
            # page can tell the operator a scan happened rather than presenting
            # OCR output as if it came from a clean text layer.
            "extraction": result.get("extraction", {}),
            "message": result["message"],
            "persona_derivation": {
                "status": derivation.status,
                "error_code": derivation.error_code,
            },
        }), 200

    except BillingLimitError as e:
        response = {
            "status": "error",
            "code": e.code,
            "message": str(e),
        }
        if getattr(e, "details", None):
            response["details"] = e.details
        return jsonify(response), 403

    except Exception:
        logging.exception("PDF upload failed for chatbot_id=%s", chatbot_id)
        return jsonify({
            "message": "PDF upload failed. Please check the server logs for details."
        }), 500
