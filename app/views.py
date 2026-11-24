import logging
import re

from flask import Blueprint, request, jsonify, current_app, abort, g
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

from .decorators.security import signature_required
from app.decorators.auth_decorator import token_required
from .utils.whatsapp_utils import process_whatsapp_message
from app.services import meta_webhook_service
from app.services.knowledge_service import save_uploaded_pdf
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import can_upload_knowledge_file, can_upload_knowledge_storage, BillingLimitError
from app.services.client_job_limits import ClientJobLimitError
from app.services.company_status_service import company_operational_required
from app.frontend_files import send_frontend_file

webhook_blueprint = Blueprint("webhook", __name__)

@webhook_blueprint.route("/", methods=["GET"])
def serve_frontend_root():
    return send_frontend_file("landing.html")


def handle_message():
    """Dispatch signed changes independently. Meta retries transient failures."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("object") != "whatsapp_business_account":
        return jsonify({"status": "ok"}), 200
    failed = False
    for entry in meta_webhook_service.objects(body.get("entry")):
        for change in meta_webhook_service.objects(entry.get("changes")):
            field, value = change.get("field"), change.get("value")
            if not isinstance(value, dict):
                continue
            try:
                if field == "messages":
                    for part in meta_webhook_service.inbound_messages(value):
                        process_whatsapp_message({"object": body["object"], "entry": [
                            {"id": entry.get("id"), "changes": [{"field": field, "value": part}]}]})
                    meta_webhook_service.record_statuses(entry.get("id"), value)
                elif field == "message_template_status_update":
                    meta_webhook_service.record_template_status(entry.get("id"), value, entry.get("time"))
                elif field == "smb_message_echoes":
                    meta_webhook_service.record_echoes(entry.get("id"), value)
                elif field == "account_update" and value.get("event") == "PARTNER_REMOVED":
                    meta_webhook_service.partner_removed(entry.get("id"), value, entry.get("time"))
                else:
                    safe_field = field if isinstance(field, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,100}", field) else "unknown"
                    logging.info("Ignored WhatsApp webhook field %s", safe_field)
            except Exception as error:
                logging.error("WhatsApp webhook processing failed (%s)", type(error).__name__)
                failed = True
    if failed:
        return jsonify({"status": "error", "message": "Internal error"}), 500
    return jsonify({"status": "ok"}), 200

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
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        try:
            verify_chatbot_access(chatbot_id)
        except PermissionError:
            return jsonify({"status": "error", "message": "Access denied."}), 403

        if "pdf_file" not in request.files:
            return jsonify({"message": "No file part"}), 400

        file = request.files["pdf_file"]

        # Determine file size before saving (seek to end, then reset)
        file.seek(0, 2)
        incoming_size = file.tell()
        file.seek(0)

        # Check subscription limits before file upload
        can_upload_knowledge_file(g.company_id)
        can_upload_knowledge_storage(g.company_id, incoming_size)
        # Accept and persist here; read, embed and derive off the request
        # thread. Reading a scanned PDF is one to three seconds per page and
        # the knowledge graph is one billed LLM call per section, which is why
        # this used to answer after minutes. The billing gates above still run
        # first and still block a denied upload -- only the work that follows
        # an accepted one is deferred. knowledge_ingest_job_service runs it.
        result = save_uploaded_pdf(file, chatbot_id, defer_processing=True, company_id=g.company_id)

        # The upload itself succeeded even when extraction produced nothing, so
        # the row exists and the caller must be able to see that outcome rather
        # than a blanket "uploaded" claim. The status travels in the body:
        # "processing" until GET /api/knowledge/upload-status says otherwise.
        return jsonify({
            "status": result.get("status", "completed"),
            "processing_status": result.get("processing_status", "completed"),
            "file_id": result.get("file_id"),
            "chunk_count": result.get("chunk_count", 0),
            # What was read and how, including whether OCR was involved, so the
            # page can tell the operator a scan happened rather than presenting
            # OCR output as if it came from a clean text layer.
            "extraction": result.get("extraction", {}),
            "message": result["message"],
            # Filling company_name / business_description / tone from the
            # document is part of the deferred ingest now, so its outcome
            # arrives with the rest of it on the status endpoint rather than
            # here. Reported as pending rather than omitted: a caller that
            # reads this key must not read a missing one as "not derived".
            "persona_derivation": {
                "status": "pending",
                "error_code": None,
            },
        }), 200

    except RequestEntityTooLarge:
        return jsonify({"status": "error", "message": "Upload exceeds the request size limit (maximum 32 MiB)."}), 413
    except ClientJobLimitError as e:
        return jsonify({"status": "error", "code": e.code, "message": str(e)}), 429
    except BillingLimitError as e:
        response = {
            "status": "error",
            "code": e.code,
            "message": str(e),
        }
        if getattr(e, "details", None):
            response["details"] = e.details
        return jsonify(response), 403

    except ValueError:
        return jsonify({"status": "error", "message": "Invalid PDF upload. Please check the file and try again."}), 400
    except Exception:
        logging.exception("PDF upload failed for chatbot_id=%s", chatbot_id)
        return jsonify({
            "message": "PDF upload failed. Please check the server logs for details."
        }), 500
