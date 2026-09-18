from flask import Blueprint, current_app, jsonify, request, g
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import (
    can_upload_knowledge_file,
    can_upload_knowledge_storage,
    can_use_plan_feature,
    BillingLimitError,
)
from app.services.company_status_service import (
    CompanyOperationalStatusError,
    company_operational_required,
    ensure_company_operational,
)
import logging
from werkzeug.exceptions import RequestEntityTooLarge

from app.services.knowledge_service import (
    list_uploaded_pdfs,
    delete_pdf_file,
    get_active_pdf,
    set_active_pdf,
    toggle_supporting_knowledge,
    scrape_website_url,
    discover_website_links,
    scrape_website_urls_batch,
    extract_business_knowledge,
    save_refined_knowledge_chunks,
    scrape_pages,
)
from app.services.knowledge_ingestion_service import (
    ingest_website_sources,
    summarize_report,
)
from app.services.knowledge_ingest_job_service import get_ingest_status
from app.database.knowledge_file_repository import get_active_knowledge_file
from app.services.pdf_relevance_validation_service import (
    CandidateStateError,
    cancel_pdf_candidate,
    confirm_supporting_pdf_candidate,
    validate_supporting_pdf_candidate,
)
from app.utils.api_errors import server_error
from app.services.document_storage_service import DocumentStorageError, materialize_file, r2_enabled

knowledge_blueprint = Blueprint("knowledge", __name__)


@knowledge_blueprint.errorhandler(DocumentStorageError)
def handle_document_storage_error(_error):
    return jsonify({
        "status": "error",
        "message": "Document storage is temporarily unavailable. Please try again.",
    }), 503


def _incoming_upload_size(file):
    file.seek(0, 2)
    incoming_size = file.tell()
    file.seek(0)
    return incoming_size


PRIMARY_PDF_REQUIRED_CODE = "primary_pdf_required"
PRIMARY_PDF_REQUIRED_MESSAGE = "Upload a Primary PDF before adding website knowledge."


def _is_active_primary_pdf(knowledge_file):
    if not knowledge_file:
        return False
    if not knowledge_file.get("is_active"):
        return False
    if knowledge_file.get("is_enabled", True) is False:
        return False

    file_type = str(knowledge_file.get("file_type") or "").strip().lower()
    if file_type == "pdf":
        return True
    if file_type in {"url", "website"}:
        return False

    # Legacy rows may not have file_type. Only accept them when the stored or
    # original name still gives credible PDF evidence.
    for key in ("original_file_name", "file_name", "file_path", "name"):
        value = str(knowledge_file.get(key) or "").strip().lower()
        if value.endswith(".pdf"):
            return True
    return False


def _has_active_primary_pdf(chatbot_id):
    return _is_active_primary_pdf(get_active_knowledge_file(chatbot_id))


def _primary_pdf_required_response():
    return jsonify({
        "status": "error",
        "code": PRIMARY_PDF_REQUIRED_CODE,
        "message": PRIMARY_PDF_REQUIRED_MESSAGE,
    }), 409


def _reject_without_active_primary_pdf(chatbot_id):
    if not _has_active_primary_pdf(chatbot_id):
        return _primary_pdf_required_response()
    return None

@knowledge_blueprint.route("/api/knowledge/files", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_uploaded_pdfs():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        files = list_uploaded_pdfs(chatbot_id)
        return jsonify({
            "status": "success",
            "data": files
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return server_error("get_uploaded_pdfs", e)

@knowledge_blueprint.route("/api/knowledge/upload-status", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_upload_status():
    """How far the deferred ingest of one uploaded document has got.

    ``POST /upload-pdf`` returns as soon as the file is safe, so this is where
    the page learns that the document is readable, that nothing could be read
    out of it, or that its persona was filled in. Cheap enough to poll: it
    answers from process memory, and only falls back to one row read.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        file_id = request.args.get("file_id", type=int)

        if not chatbot_id or not file_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id and file_id are required"
            }), 400

        verify_chatbot_access(chatbot_id)
        job = get_ingest_status(chatbot_id, file_id)

        if not job:
            return jsonify({
                "status": "error",
                "message": "That document was not found."
            }), 404

        return jsonify({
            "status": "success",
            "data": job
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return server_error("get_upload_status", e)


@knowledge_blueprint.route("/api/knowledge/active", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_current_active_pdf():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        active_pdf = get_active_pdf(chatbot_id)
        return jsonify({
            "status": "success",
            "data": active_pdf
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return server_error("get_current_active_pdf", e)


@knowledge_blueprint.route("/api/knowledge/pdf-candidates/validate", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def validate_pdf_candidate():
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
        primary_file = get_active_knowledge_file(chatbot_id)
        if not primary_file:
            return jsonify({
                "status": "success",
                "data": {
                    "validation_status": "no_primary_source",
                    "passed": False,
                    "can_confirm": False,
                    "reason": "No Primary source exists for this chatbot yet.",
                },
            }), 200

        if "pdf_file" not in request.files:
            return jsonify({
                "status": "error",
                "message": "No file part"
            }), 400

        file = request.files["pdf_file"]
        if not file or not file.filename:
            return jsonify({
                "status": "error",
                "message": "No selected file"
            }), 400
        if not file.filename.lower().endswith(".pdf"):
            return jsonify({
                "status": "error",
                "message": "Invalid file type"
            }), 400

        incoming_size = _incoming_upload_size(file)
        can_upload_knowledge_file(g.company_id)
        can_upload_knowledge_storage(g.company_id, incoming_size)

        threshold = float(current_app.config.get("PDF_SUPPORTING_RELEVANCE_THRESHOLD", 0.65))
        result = validate_supporting_pdf_candidate(
            file=file,
            chatbot_id=chatbot_id,
            company_id=g.company_id,
            created_by_user_id=getattr(g, "user_id", None),
            threshold=threshold,
            primary_file=primary_file,
        )

        return jsonify({
            "status": "success",
            "data": result,
        }), 200

    except RequestEntityTooLarge:
        return jsonify({"status": "error", "message": "Upload exceeds the request size limit (maximum 32 MiB)."}), 413
    except BillingLimitError as e:
        response = {
            "status": "error",
            "code": e.code,
            "message": str(e),
        }
        if getattr(e, "details", None):
            response["details"] = e.details
        return jsonify(response), 403
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception:
        logging.exception("Supporting PDF candidate validation failed")
        return jsonify({
            "status": "error",
            "message": "PDF validation failed. Please check the server logs for details."
        }), 500


@knowledge_blueprint.route("/api/knowledge/pdf-candidates/<candidate_id>/confirm", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def confirm_pdf_candidate(candidate_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        result = confirm_supporting_pdf_candidate(
            candidate_id=candidate_id,
            chatbot_id=chatbot_id,
            company_id=g.company_id,
        )

        return jsonify({
            "status": "success",
            "data": result,
        }), 200

    except CandidateStateError as e:
        status_code = 404 if e.code == "candidate_not_found" else 409
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
        }), status_code
    except BillingLimitError as e:
        response = {
            "status": "error",
            "code": e.code,
            "message": str(e),
        }
        if getattr(e, "details", None):
            response["details"] = e.details
        return jsonify(response), 403
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except Exception:
        logging.exception("Supporting PDF candidate confirmation failed")
        return jsonify({
            "status": "error",
            "message": "PDF candidate confirmation failed. Please check the server logs for details."
        }), 500


@knowledge_blueprint.route("/api/knowledge/pdf-candidates/<candidate_id>/cancel", methods=["POST", "DELETE"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def cancel_pdf_candidate_route(candidate_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        result = cancel_pdf_candidate(candidate_id, chatbot_id, g.company_id)

        return jsonify({
            "status": "success",
            "data": result,
        }), 200

    except CandidateStateError as e:
        status_code = 404 if e.code == "candidate_not_found" else 409
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
        }), status_code
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except Exception:
        logging.exception("Supporting PDF candidate cancellation failed")
        return jsonify({
            "status": "error",
            "message": "PDF candidate cancellation failed. Please check the server logs for details."
        }), 500


@knowledge_blueprint.route("/api/knowledge/set-active", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def set_current_active_pdf():
    try:
        data = request.get_json()

        if not data or "file_name" not in data:
            return jsonify({
                "status": "error",
                "message": "file_name is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        result = set_active_pdf(data["file_name"], chatbot_id)

        return jsonify({
            "status": "success",
            "data": result
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except DocumentStorageError:
        raise
    except Exception as e:
        return server_error("set_current_active_pdf", e)


@knowledge_blueprint.route("/api/knowledge/toggle-support", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def toggle_supporting_knowledge_source():
    try:
        data = request.get_json() or {}

        if "file_name" not in data:
            return jsonify({
                "status": "error",
                "message": "file_name is required"
            }), 400

        if "is_enabled" not in data:
            return jsonify({
                "status": "error",
                "message": "is_enabled is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        result = toggle_supporting_knowledge(
            file_name=data["file_name"],
            is_enabled=data["is_enabled"],
            chatbot_id=chatbot_id,
        )

        return jsonify({
            "status": "success",
            "data": result
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except Exception as e:
        return server_error("toggle_supporting_knowledge_source", e)


@knowledge_blueprint.route("/api/knowledge/files/<path:file_name>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def delete_uploaded_pdf(file_name):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        # Normalize double slashes if Werkzeug collapsed them
        if file_name.startswith("http:/") and not file_name.startswith("http://"):
            file_name = file_name.replace("http:/", "http://", 1)
        elif file_name.startswith("https:/") and not file_name.startswith("https://"):
            file_name = file_name.replace("https:/", "https://", 1)

        result = delete_pdf_file(file_name, chatbot_id)
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except DocumentStorageError:
        raise
    except Exception as e:
        return server_error("delete_uploaded_pdf", e)


@knowledge_blueprint.route("/api/knowledge/scrape", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def scrape_website_knowledge():
    try:
        data = request.get_json()
        if not data or "url" not in data:
            return jsonify({
                "status": "error",
                "message": "URL is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        primary_guard = _reject_without_active_primary_pdf(chatbot_id)
        if primary_guard:
            return primary_guard
        # Plan gate: Free and Essential have single_website_scraping = false
        # (data/004_add_subscription_plan_feature_flags.sql). Without this the
        # flag is defined on every plan but enforced nowhere.
        can_use_plan_feature(g.company_id, "single_website_scraping")
        # Check subscription limit before knowledge file creation
        can_upload_knowledge_file(g.company_id)
        # company_id is required for the storage quota check inside
        # scrape_website_url (knowledge_service.py:443-444); omitting it
        # silently skips the check.
        result = scrape_website_url(data["url"], chatbot_id, company_id=g.company_id)
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except Exception as e:
        return server_error("scrape_website_knowledge", e)


@knowledge_blueprint.route("/api/knowledge/scrape-analyze", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def scrape_analyze_website():
    try:
        data = request.get_json()
        if not data or "url" not in data:
            return jsonify({
                "status": "error",
                "message": "URL is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        primary_guard = _reject_without_active_primary_pdf(chatbot_id)
        if primary_guard:
            return primary_guard
        can_use_plan_feature(g.company_id, "single_website_scraping")
        links = discover_website_links(data["url"])
        return jsonify({
            "status": "success",
            "data": {
                "url": data["url"],
                "links": links
            }
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
            "details": e.details or {}
        }), 403
    except Exception as e:
        return server_error("scrape_analyze_website", e)


@knowledge_blueprint.route("/api/knowledge/scrape-batch", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def scrape_batch_website():
    try:
        data = request.get_json()
        if not data or "urls" not in data or not isinstance(data["urls"], list):
            return jsonify({
                "status": "error",
                "message": "List of URLs ('urls') is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        primary_guard = _reject_without_active_primary_pdf(chatbot_id)
        if primary_guard:
            return primary_guard
        # Check subscription feature access for batch scraping
        urls = data["urls"]
        if len(urls) > 1:
            can_use_plan_feature(g.company_id, "batch_website_scraping")
        else:
            can_use_plan_feature(g.company_id, "single_website_scraping")
        # Check subscription limit before knowledge file creation
        can_upload_knowledge_file(g.company_id)
        result = scrape_website_urls_batch(
            data["urls"],
            chatbot_id,
            company_id=g.company_id,
        )
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except Exception as e:
        return server_error("scrape_batch_website", e)


@knowledge_blueprint.route("/api/knowledge/scrape-extract", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def scrape_extract_website():
    try:
        data = request.get_json()
        if not data or "urls" not in data or not isinstance(data["urls"], list):
            return jsonify({
                "status": "error",
                "message": "List of URLs ('urls') is required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        primary_guard = _reject_without_active_primary_pdf(chatbot_id)
        if primary_guard:
            return primary_guard
        # Check subscription feature access: single or batch website scraping depending on URL count
        urls = data["urls"]
        if len(urls) > 1:
            can_use_plan_feature(g.company_id, "batch_website_scraping")
        else:
            can_use_plan_feature(g.company_id, "single_website_scraping")
        # Fail before the billed LLM call below. scrape-embed re-checks this at
        # write time, but a client already at their knowledge-file limit would
        # otherwise pay for an extraction that can never be saved.
        can_upload_knowledge_file(g.company_id)

        urls = data["urls"]
        if not urls:
            return jsonify({
                "status": "error",
                "message": "At least one URL must be selected."
            }), 400

        primary_url = urls[0]
        pages, failures = scrape_pages(urls)
        failed_urls = [failure["url"] for failure in failures]

        if not pages:
            return jsonify({
                "status": "error",
                "message": f"Failed to scrape any of the selected URLs. Errors: {failed_urls}"
            }), 400

        combined_text = "\n\n".join(page["content"] for page in pages)

        # Call the LLM refiner
        refined_text = extract_business_knowledge(combined_text, chatbot_id=chatbot_id)

        return jsonify({
            "status": "success",
            "data": {
                "extracted_text": refined_text,
                "primary_url": primary_url,
                "failed_urls": failed_urls
            }
        }), 200
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
            "details": e.details or {}
        }), 403
    except Exception as e:
        return server_error("scrape_extract_website", e)


@knowledge_blueprint.route("/api/knowledge/scrape-embed", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def scrape_embed_website():
    try:
        data = request.get_json()
        if not data or "text_content" not in data or "primary_url" not in data:
            return jsonify({
                "status": "error",
                "message": "text_content and primary_url are required"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        primary_guard = _reject_without_active_primary_pdf(chatbot_id)
        if primary_guard:
            return primary_guard

        # Check subscription limit before knowledge file creation
        can_upload_knowledge_file(g.company_id)

        text_content = data["text_content"]
        primary_url = data["primary_url"]

        # Default file name is the primary URL or custom override
        file_name = data.get("file_name", primary_url)

        result = save_refined_knowledge_chunks(
            text_content=text_content,
            file_name=file_name,
            primary_url=primary_url,
            chatbot_id=chatbot_id,
            # company_id is required for the storage quota check inside
            # save_refined_knowledge_chunks (knowledge_service.py:673-674);
            # omitting it silently skips the check.
            company_id=g.company_id
        )

        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    except Exception as e:
        return server_error("scrape_embed_website", e)


@knowledge_blueprint.route("/api/knowledge/ingest", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def ingest_knowledge_sources():
    """Run the whole website ingestion pipeline in a single call.

    Composes the four stages that /api/knowledge/scrape-analyze,
    -scrape-batch, -scrape-extract and -scrape-embed expose individually.
    Those endpoints are unchanged and still work; this is a composition over
    them, not a replacement.

    Body:
        {"sources": [ "https://example.com"
                    | {"url": str, "urls": [str], "discover_links": bool,
                       "max_pages": int, "file_name": str} , ... ]}

    Returns 200 when at least one source was ingested — including the partial
    case, where already-ingested sources are kept and the failures are named
    per source in data.sources[].error_code / .error_message. Returns 400 only
    when every source failed, mirroring scrape-extract's existing behaviour.
    """
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({
                "status": "error",
                "message": "Request body must be a JSON object"
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        primary_guard = _reject_without_active_primary_pdf(chatbot_id)
        if primary_guard:
            return primary_guard
        # Plan gate for this endpoint's own capability (data/042). Checked
        # first so a plan without single-call ingestion is told exactly that.
        can_use_plan_feature(g.company_id, "unified_knowledge_ingestion")
        # Same gates, in the same order, as the staged chain this composes:
        # the plan feature the chain actually enforces (scrape-extract), then
        # the file quota, checked before the billed LLM extraction below.
        # Kept as well as the gate above: this endpoint scrapes many pages per
        # source, so dropping it would hand batch scraping to a plan that pays
        # for single-page scraping only.
        can_use_plan_feature(g.company_id, "batch_website_scraping")
        can_upload_knowledge_file(g.company_id)

        report = ingest_website_sources(
            sources=data.get("sources"),
            chatbot_id=chatbot_id,
            company_id=g.company_id,
        )
        message = summarize_report(report)

        if report["status"] == "failed":
            return jsonify({
                "status": "error",
                "message": message,
                "data": report
            }), 400

        return jsonify({
            "status": "success",
            "message": message,
            "data": report
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
            "details": e.details or {}
        }), 403
    except Exception as e:
        logging.error(f"[Ingest] Unified ingestion failed: {e}")
        return server_error("ingest_knowledge_sources", e)


@knowledge_blueprint.route("/api/knowledge/graph", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_knowledge_graph_data():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        from app.database.db import supabase
        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        from app.database.knowledge_chunk_repository import get_chunks_by_file_for_chatbot
        from app.services.knowledge_service import extract_and_store_graph_supabase

        # 1. Identify the current active PDF knowledge file
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        if not active_file:
            return jsonify({
                "status": "success",
                "data": {
                    "nodes": [],
                    "edges": []
                }
            }), 200

        file_id = active_file["id"]

        # 2. Check if we have nodes for this active PDF
        nodes_check = (
            supabase.table("knowledge_graph_nodes")
            .select("id")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .limit(1)
            .execute()
        )

        # 3. If no nodes exist, auto-trigger extraction synchronously
        if not nodes_check.data:
            ensure_company_operational(g.company_id)
            logging.info(f"[GraphRAG] No nodes found for active file_id={file_id}. Running auto-extraction...")
            chunks_data = get_chunks_by_file_for_chatbot(chatbot_id, file_id)
            chunks = [c["content"] for c in chunks_data]

            # Self-healing: if 0 chunks exist, attempt to parse the local PDF file from the disk
            if not chunks:
                logging.info(f"[GraphRAG] Chunks count is 0 in DB. Attempting to parse physical PDF file...")
                from app.services.knowledge_service import DATA_FOLDER
                import os
                import fitz
                from app.services.rag_service import split_text_into_sections, generate_embedding
                from app.database.knowledge_chunk_repository import save_knowledge_chunk

                file_name = active_file.get("file_name", "")
                stored_path = (active_file.get("file_path") or "").replace("\\", "/")
                from werkzeug.utils import secure_filename

                # Robust path candidates lookup
                candidates = []
                if stored_path:
                    if os.path.isabs(stored_path):
                        candidates.append(stored_path)
                    else:
                        candidates.append(os.path.join(DATA_FOLDER, os.path.basename(stored_path)))

                candidates.extend([
                    os.path.join(DATA_FOLDER, file_name),
                    os.path.join(DATA_FOLDER, f"bot_{chatbot_id}_{file_name}"),
                    os.path.join(DATA_FOLDER, secure_filename(file_name)),
                    os.path.join(DATA_FOLDER, secure_filename(f"bot_{chatbot_id}_{file_name}")),
                ])
                if r2_enabled():
                    candidates = candidates[:1] if stored_path else [
                        os.path.join(DATA_FOLDER, secure_filename(file_name))
                    ]

                target_path = None
                for path in candidates:
                    try:
                        target_path = materialize_file(path, root=DATA_FOLDER, namespace="knowledge")
                        break
                    except FileNotFoundError:
                        continue

                logging.info("[GraphRAG] Original document available for file_id=%s: %s", file_id, bool(target_path))

                if target_path:
                    try:
                        doc = fitz.open(target_path)
                        lines = []
                        for page in doc:
                            blocks = page.get_text("blocks")
                            blocks = sorted(blocks, key=lambda b: (b[1], b[0]))
                            for block in blocks:
                                text = block[4].strip()
                                if text:
                                    for line in text.splitlines():
                                        clean_line = " ".join(line.split())
                                        if clean_line:
                                            lines.append(clean_line)
                        pdf_text = "\n".join(lines)
                        chunks = split_text_into_sections(pdf_text)

                        logging.info(f"[GraphRAG] Extracted {len(chunks)} chunks from local PDF. Saving to database...")
                        for idx, chunk in enumerate(chunks):
                            embedding = generate_embedding(chunk)
                            if embedding:
                                save_knowledge_chunk(
                                    chatbot_id=chatbot_id,
                                    file_id=file_id,
                                    content=chunk,
                                    embedding=embedding,
                                    metadata={"chunk_index": idx}
                                )
                    except Exception as parse_err:
                        logging.error("[GraphRAG] Original document parsing failed for file_id=%s (%s)", file_id, type(parse_err).__name__)
                else:
                    logging.error("[GraphRAG] Original document is missing for file_id=%s", file_id)

            if chunks:
                try:
                    extract_and_store_graph_supabase(chunks, chatbot_id, file_id)
                except Exception as ext_err:
                    logging.error(f"[GraphRAG] Auto-extraction failed for file_id={file_id}: {ext_err}")
                    err_msg = str(ext_err)
                    is_billing = "402" in err_msg or "billing" in err_msg.lower() or "payment" in err_msg.lower() or "credit" in err_msg.lower()
                    return jsonify({
                        "status": "error",
                        "message": f"Auto-extraction of Knowledge Graph failed: {err_msg}"
                    }), 402 if is_billing else 500

        # 4. Fetch graph elements ONLY for this active PDF file
        nodes_result = (
            supabase.table("knowledge_graph_nodes")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )

        edges_result = (
            supabase.table("knowledge_graph_edges")
            .select("*")
            .eq("chatbot_id", chatbot_id)
            .eq("file_id", file_id)
            .execute()
        )

        # Format nodes and edges for frontend graphing libraries (like vis.js)
        formatted_nodes = []
        for node in (nodes_result.data or []):
            formatted_nodes.append({
                "id": node["name"],
                "label": node["name"].title(),
                "title": f"Type: {node['label']}\n{node.get('properties', {}).get('description', '')}".strip(),
                "group": node["label"]
            })

        formatted_edges = []
        for edge in (edges_result.data or []):
            formatted_edges.append({
                "from": edge["source_name"],
                "to": edge["target_name"],
                "label": edge["rel_type"].replace("_", " "),
                "title": edge["rel_type"]
            })

        return jsonify({
            "status": "success",
            "data": {
                "nodes": formatted_nodes,
                "edges": formatted_edges
            }
        }), 200
    except CompanyOperationalStatusError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": e.message
        }), e.status_code
    except DocumentStorageError:
        raise
    except Exception as e:
        return server_error("get_knowledge_graph_data", e)


@knowledge_blueprint.route("/api/knowledge/refinement/questions", methods=["GET"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def get_refinement_questions():
    chatbot_id = request.args.get("chatbot_id", type=int)
    if not chatbot_id:
        return jsonify({
            "status": "error",
            "message": "chatbot_id is required"
        }), 400

    verify_chatbot_access(chatbot_id)
    try:
        can_use_plan_feature(g.company_id, "knowledge_refinement")
    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403

    from flask import Response, stream_with_context
    import json

    def generate():
        try:
            yield "data: " + json.dumps({"type": "log", "message": "Connecting to database..."}) + "\n\n"

            from app.database.db import supabase
            from app.database.knowledge_file_repository import get_active_pdf_knowledge_file

            # 1. Get active PDF
            active_file = get_active_pdf_knowledge_file(chatbot_id)
            if not active_file:
                yield "data: " + json.dumps({"type": "error", "message": "No active primary PDF found. Please set a primary PDF before scanning for clarifications."}) + "\n\n"
                return

            file_id = active_file["id"]
            file_name = active_file["file_name"]

            yield "data: " + json.dumps({"type": "log", "message": f"Active PDF detected: {file_name}"}) + "\n\n"
            yield "data: " + json.dumps({"type": "log", "message": "Loading Knowledge Graph nodes and edges..."}) + "\n\n"

            # 2. Get graph elements for this PDF
            nodes_res = (
                supabase.table("knowledge_graph_nodes")
                .select("*")
                .eq("chatbot_id", chatbot_id)
                .eq("file_id", file_id)
                .execute()
            )

            edges_res = (
                supabase.table("knowledge_graph_edges")
                .select("*")
                .eq("chatbot_id", chatbot_id)
                .eq("file_id", file_id)
                .execute()
            )

            nodes = nodes_res.data or []
            edges = edges_res.data or []

            if not nodes:
                yield "data: " + json.dumps({"type": "error", "message": "No knowledge graph elements found for this PDF. The graph must be populated first."}) + "\n\n"
                return

            yield "data: " + json.dumps({"type": "log", "message": f"Graph loaded: {len(nodes)} nodes, {len(edges)} edges."}) + "\n\n"
            yield "data: " + json.dumps({"type": "log", "message": "Scanning Knowledge Graph for structural gaps using AI..."}) + "\n\n"

            # 3. Format the graph elements into a summary prompt
            graph_text = f"Here is the knowledge graph extracted from active file '{file_name}':\n\n"
            graph_text += "Entities (Nodes):\n"
            for n in nodes:
                graph_text += f"- {n['name']} (Category: {n['label']})"
                if n.get("properties") and isinstance(n["properties"], dict):
                    props_str = ", ".join(f"{k}: {v}" for k, v in n["properties"].items())
                    if props_str:
                        graph_text += f" | Details: {props_str}"
                graph_text += "\n"

            graph_text += "\nConnections (Edges):\n"
            for e in edges:
                graph_text += f"- {e['source_name']} [{e['rel_type']}] -> {e['target_name']}\n"

            system_prompt = (
                "You are a knowledge graph refinement assistant for a customer support AI chatbot.\n"
                "Your task is to analyze the extracted business knowledge graph and identify 3 to 5 critical clarifying questions "
                "that a customer might ask but are ambiguous, incomplete, or lack specific details in the current nodes/relationships "
                "(e.g., missing prices, undefined warranties, service limitations, shipping times, or package details).\n"
                "You must return the result as a raw JSON array of objects with the fields: 'question' and 'context'.\n"
                "Example output format:\n"
                "[\n"
                "  {\"question\": \"What is the warranty period for Titan Laptop?\", \"context\": \"Titan Laptop is connected to Warranty, but details/duration are not specified.\"},\n"
                "  {\"question\": \"How much does the Platinum Package cost?\", \"context\": \"Platinum Package is a Service, but has no HAS_PRICE relation.\"}\n"
                "]\n"
                "Return ONLY the raw JSON block without markdown formatting."
            )

            import os
            from app.services.ai_router import (
                OPERATION_KNOWLEDGE_REFINEMENT_QUESTIONS,
                OPERATION_KNOWLEDGE_REFINEMENT_VERIFICATION,
                generate_system_response,
            )
            full_prompt = system_prompt + "\n\nKnowledge Graph:\n" + graph_text
            content = generate_system_response(
                prompt=full_prompt,
                chatbot_id=chatbot_id,
                temperature=0.3,
                json_response=True,
                operation_type=OPERATION_KNOWLEDGE_REFINEMENT_QUESTIONS,
            )
            if not content:
                content = "[]"

            content = content.strip()
            if content.startswith("```"):
                lines = content.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].startswith("```"):
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            try:
                draft_questions = json.loads(content)
            except Exception:
                draft_questions = []

            yield "data: " + json.dumps({"type": "log", "message": f"Found {len(draft_questions)} candidate questions. Commencing Layer 2 Semantic checks against PDF chunks..."}) + "\n\n"


            from app.services.rag_service import generate_embedding
            from app.database.knowledge_chunk_repository import search_similar_chunks

            retained_questions = []

            # 4. Run Second Layer Semantic Check for each question
            for q_idx, item in enumerate(draft_questions):
                question = item.get("question", "")
                context = item.get("context", "")
                if not question:
                    continue

                yield "data: " + json.dumps({"type": "log", "message": f"[{q_idx+1}/{len(draft_questions)}] Auditing text chunks: \"{question}\"..."}) + "\n\n"

                # Fetch relevant chunks
                emb = generate_embedding(question)
                chunks = []
                if emb:
                    chunks = search_similar_chunks(
                        chatbot_id=chatbot_id,
                        query_embedding=emb,
                        match_threshold=0.3,
                        match_count=3,
                        file_id=file_id
                    )

                chunk_contents = "\n".join(c["content"] for c in chunks) if chunks else ""

                if not chunk_contents:
                    retained_questions.append(item)
                    yield "data: " + json.dumps({"type": "log", "message": " -> Genuinely missing (No PDF context found). Retained."}) + "\n\n"
                    continue

                # Call LLM to verify if it is answerable in the text
                verify_prompt = (
                    "You are a knowledge auditing assistant.\n"
                    "Your task is to determine if the question below is already answered clearly and completely by the provided context snippet.\n"
                    "If yes, reply with the prefix 'RESOLVED: ' followed by the answer found in the context.\n"
                    "If no (or if the context is ambiguous, incomplete, or doesn't mention the answer), reply ONLY with 'AMBIGUOUS'.\n\n"
                    f"Question: {question}\n\n"
                    f"Context Snippet:\n{chunk_contents}"
                )

                verify_res = generate_system_response(
                    prompt=verify_prompt,
                    chatbot_id=chatbot_id,
                    temperature=0.1,
                    operation_type=OPERATION_KNOWLEDGE_REFINEMENT_VERIFICATION,
                )
                if not verify_res:
                    verify_reply = "AMBIGUOUS"
                else:
                    verify_reply = verify_res.strip()

                if verify_reply.upper().startswith("RESOLVED"):
                    ans_part = verify_reply[len("RESOLVED:"):].strip()
                    yield "data: " + json.dumps({"type": "log", "message": f" -> Auto-resolved: \"{ans_part}\" (Filtered out)"}) + "\n\n"
                else:
                    retained_questions.append(item)
                    yield "data: " + json.dumps({"type": "log", "message": " -> Ambiguous/unspecified in text. Retained."}) + "\n\n"

            yield "data: " + json.dumps({"type": "log", "message": f"Audits completed. Retained {len(retained_questions)} unresolved clarifications."}) + "\n\n"
            yield "data: " + json.dumps({"type": "complete", "questions": retained_questions}) + "\n\n"

        except Exception as e:
            logging.error(f"[Refinement Generator] Error: {e}")
            yield "data: " + json.dumps({"type": "error", "message": str(e)}) + "\n\n"

    return Response(stream_with_context(generate()), content_type="text/event-stream")


@knowledge_blueprint.route("/api/knowledge/refinement/submit", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def submit_refinement_answers():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        can_use_plan_feature(g.company_id, "knowledge_refinement")

        data = request.get_json()
        answers = data.get("answers", [])
        if not answers:
            return jsonify({
                "status": "error",
                "message": "No answers provided"
            }), 400

        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        from app.services.rag_service import generate_embedding
        from app.database.knowledge_chunk_repository import save_knowledge_chunk

        # 1. Get active PDF
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        if not active_file:
            return jsonify({
                "status": "error",
                "message": "No active primary PDF found."
            }), 400

        file_id = active_file["id"]

        # 2. Save each answer as a new chunk with embeddings
        saved_count = 0
        saved_qa_pairs = []
        for item in answers:
            question = item.get("question", "").strip()
            answer = item.get("answer", "").strip()
            if not question or not answer:
                continue

            chunk_content = f"Question: {question}\nAnswer: {answer}"
            embedding = generate_embedding(chunk_content)
            if embedding:
                save_knowledge_chunk(
                    chatbot_id=chatbot_id,
                    file_id=file_id,
                    content=chunk_content,
                    embedding=embedding,
                    metadata={
                        "source_type": "refinement",
                        "question": question,
                        "refined_at": "2026-06-29"
                    }
                )
                saved_count += 1
                saved_qa_pairs.append({"question": question, "answer": answer})

        if saved_count > 0:
            from app.services.knowledge_service import generate_and_save_knowledge_readme, log_knowledge_modification
            try:
                generate_and_save_knowledge_readme(chatbot_id, file_id)
            except DocumentStorageError:
                raise
            except Exception as readme_err:
                logging.error(f"Failed to generate README inside submit_refinement_answers: {readme_err}")
            try:
                log_knowledge_modification(
                    chatbot_id, file_id,
                    f"Submitted {saved_count} refined knowledge Q&A clarifications.",
                    "Q&A Submissions",
                    details=saved_qa_pairs
                )
            except DocumentStorageError:
                raise
            except Exception as log_err:
                logging.error(f"Failed to log history inside submit_refinement_answers: {log_err}")

        return jsonify({
            "status": "success",
            "message": f"Successfully saved {saved_count} refined knowledge clarifications."
        }), 200

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), 403
    except DocumentStorageError:
        raise
    except Exception as e:
        logging.error(f"[Refinement] Failed to submit answers: {e}")
        return server_error("submit_refinement_answers", e)


@knowledge_blueprint.route("/api/knowledge/graph/node", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def save_graph_node():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        data = request.get_json() or {}
        name = data.get("name", "").strip()
        label = data.get("label", "").strip()
        properties = data.get("properties", {})
        old_name = data.get("old_name", "").strip()

        if not name or not label:
            return jsonify({
                "status": "error",
                "message": "Node name and category (label) are required"
            }), 400

        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        from app.database.knowledge_graph_repository import upsert_node, delete_node, update_edge_node_references

        active_file = get_active_pdf_knowledge_file(chatbot_id)
        file_id = active_file["id"] if active_file else 0

        # Handle renaming
        if old_name and old_name.lower() != name.lower():
            # 1. Upsert node with new name
            new_node = upsert_node(chatbot_id, file_id, name, label, properties)
            # 2. Update edge source/target references
            update_edge_node_references(chatbot_id, old_name, name)
            # 3. Delete old node
            delete_node(chatbot_id, old_name)
            node_data = new_node
        else:
            node_data = upsert_node(chatbot_id, file_id, name, label, properties)

        from app.services.knowledge_service import generate_and_save_knowledge_readme, log_knowledge_modification
        try:
            generate_and_save_knowledge_readme(chatbot_id, file_id)
        except DocumentStorageError:
            raise
        except Exception as readme_err:
            logging.error(f"Failed to generate README inside save_graph_node: {readme_err}")
        try:
            if old_name and old_name.lower() != name.lower():
                log_knowledge_modification(chatbot_id, file_id, f"Updated entity from '{old_name}' to '{name}' (Category: '{label}').", "Graph Modifications")
            else:
                log_knowledge_modification(chatbot_id, file_id, f"Saved entity '{name}' (Category: '{label}').", "Graph Modifications")
        except DocumentStorageError:
            raise
        except Exception as log_err:
            logging.error(f"Failed to log history inside save_graph_node: {log_err}")

        return jsonify({
            "status": "success",
            "data": node_data
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except DocumentStorageError:
        raise
    except Exception as e:
        logging.error(f"Error saving graph node: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_blueprint.route("/api/knowledge/graph/node", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def delete_graph_node_route():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        name = request.args.get("name", "").strip()
        if not name:
            return jsonify({
                "status": "error",
                "message": "Node name is required"
            }), 400

        from app.database.knowledge_graph_repository import delete_node, delete_edges_by_node

        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        file_id = active_file["id"] if active_file else 0

        # Delete edges first
        delete_edges_by_node(chatbot_id, name)
        # Delete node
        delete_node(chatbot_id, name)

        from app.services.knowledge_service import generate_and_save_knowledge_readme, log_knowledge_modification
        try:
            generate_and_save_knowledge_readme(chatbot_id, file_id)
        except DocumentStorageError:
            raise
        except Exception as readme_err:
            logging.error(f"Failed to generate README inside delete_graph_node_route: {readme_err}")
        try:
            log_knowledge_modification(chatbot_id, file_id, f"Deleted entity '{name}' and all its adjacent connections.", "Graph Modifications")
        except DocumentStorageError:
            raise
        except Exception as log_err:
            logging.error(f"Failed to log history inside delete_graph_node_route: {log_err}")

        return jsonify({
            "status": "success",
            "message": f"Successfully deleted node '{name}' and all its adjacent connections."
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except DocumentStorageError:
        raise
    except Exception as e:
        logging.error(f"Error deleting graph node: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_blueprint.route("/api/knowledge/graph/edge", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def save_graph_edge():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        data = request.get_json() or {}
        source_name = data.get("source_name", "").strip()
        target_name = data.get("target_name", "").strip()
        rel_type = data.get("rel_type", "").strip()
        properties = data.get("properties", {})

        if not source_name or not target_name or not rel_type:
            return jsonify({
                "status": "error",
                "message": "source_name, target_name, and rel_type are required"
            }), 400

        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        from app.database.knowledge_graph_repository import upsert_edge

        active_file = get_active_pdf_knowledge_file(chatbot_id)
        file_id = active_file["id"] if active_file else 0

        edge_data = upsert_edge(
            chatbot_id=chatbot_id,
            file_id=file_id,
            source_name=source_name,
            target_name=target_name,
            rel_type=rel_type,
            properties=properties
        )

        if not edge_data:
            return jsonify({
                "status": "error",
                "message": "Failed to create relation. Self-referencing relationships are not allowed."
            }), 400

        from app.services.knowledge_service import generate_and_save_knowledge_readme, log_knowledge_modification
        try:
            generate_and_save_knowledge_readme(chatbot_id, file_id)
        except DocumentStorageError:
            raise
        except Exception as readme_err:
            logging.error(f"Failed to generate README inside save_graph_edge: {readme_err}")
        try:
            log_knowledge_modification(chatbot_id, file_id, f"Created connection: '{source_name}' [{rel_type}] -> '{target_name}'.", "Graph Modifications")
        except DocumentStorageError:
            raise
        except Exception as log_err:
            logging.error(f"Failed to log history inside save_graph_edge: {log_err}")

        return jsonify({
            "status": "success",
            "data": edge_data
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except DocumentStorageError:
        raise
    except Exception as e:
        logging.error(f"Error saving graph edge: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_blueprint.route("/api/knowledge/graph/edge", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def delete_graph_edge_route():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        data = request.get_json() or {}
        source_name = data.get("source_name", "").strip()
        target_name = data.get("target_name", "").strip()
        rel_type = data.get("rel_type", "").strip()

        if not source_name or not target_name or not rel_type:
            return jsonify({
                "status": "error",
                "message": "source_name, target_name, and rel_type are required"
            }), 400

        from app.database.knowledge_file_repository import get_active_pdf_knowledge_file
        active_file = get_active_pdf_knowledge_file(chatbot_id)
        file_id = active_file["id"] if active_file else 0

        from app.database.knowledge_graph_repository import delete_edge
        delete_edge(chatbot_id, source_name, target_name, rel_type)

        from app.services.knowledge_service import generate_and_save_knowledge_readme, log_knowledge_modification
        try:
            generate_and_save_knowledge_readme(chatbot_id, file_id)
        except DocumentStorageError:
            raise
        except Exception as readme_err:
            logging.error(f"Failed to generate README inside delete_graph_edge_route: {readme_err}")
        try:
            log_knowledge_modification(chatbot_id, file_id, f"Deleted connection: '{source_name}' [{rel_type}] -> '{target_name}'.", "Graph Modifications")
        except DocumentStorageError:
            raise
        except Exception as log_err:
            logging.error(f"Failed to log history inside delete_graph_edge_route: {log_err}")

        return jsonify({
            "status": "success",
            "message": "Successfully deleted relationship."
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except DocumentStorageError:
        raise
    except Exception as e:
        logging.error(f"Error deleting graph edge: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_blueprint.route("/api/knowledge/readme", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_knowledge_readme():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        file_id = request.args.get("file_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        from app.services.knowledge_service import get_or_generate_readme
        readme_content = get_or_generate_readme(chatbot_id, file_id, company_id=g.company_id)

        return jsonify({
            "status": "success",
            "data": {
                "content": readme_content
            }
        }), 200
    except CompanyOperationalStatusError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": e.message
        }), e.status_code
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except DocumentStorageError:
        raise
    except Exception as e:
        logging.error(f"Error fetching knowledge readme: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@knowledge_blueprint.route("/api/knowledge/history", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_knowledge_history():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        file_id = request.args.get("file_id", type=int)

        if not chatbot_id or not file_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id and file_id are required"
            }), 400

        verify_chatbot_access(chatbot_id)

        from app.services.knowledge_service import get_knowledge_history_logs
        logs = get_knowledge_history_logs(chatbot_id, file_id)

        return jsonify({
            "status": "success",
            "data": {
                "logs": logs
            }
        }), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except DocumentStorageError:
        raise
    except Exception as e:
        logging.error(f"Error fetching knowledge history: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
