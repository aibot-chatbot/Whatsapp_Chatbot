from flask import Blueprint, jsonify, request
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access

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
)

knowledge_blueprint = Blueprint("knowledge", __name__)


@knowledge_blueprint.route("/api/knowledge/files", methods=["GET"])
@token_required
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
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/active", methods=["GET"])
@token_required
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
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/set-active", methods=["POST"])
@token_required
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
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/toggle-support", methods=["POST"])
@token_required
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
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/files/<path:file_name>", methods=["DELETE"])
@token_required
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
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape", methods=["POST"])
@token_required
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
        result = scrape_website_url(data["url"], chatbot_id)
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape-analyze", methods=["POST"])
@token_required
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
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape-batch", methods=["POST"])
@token_required
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
        result = scrape_website_urls_batch(data["urls"], chatbot_id)
        return jsonify({
            "status": "success",
            "data": result
        }), 200
    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape-extract", methods=["POST"])
@token_required
def scrape_extract_website():
    try:
        from app.services.knowledge_service import fetch_and_parse_url
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

        urls = data["urls"]
        if not urls:
            return jsonify({
                "status": "error",
                "message": "At least one URL must be selected."
            }), 400

        combined_content_list = []
        failed_urls = []
        primary_url = urls[0]

        for url in urls:
            try:
                content = fetch_and_parse_url(url)
                combined_content_list.append(content)
            except Exception as e:
                import logging
                logging.error(f"Failed to scrape URL {url} for extraction: {e}")
                failed_urls.append(url)

        if not combined_content_list:
            return jsonify({
                "status": "error",
                "message": f"Failed to scrape any of the selected URLs. Errors: {failed_urls}"
            }), 400

        combined_text = "\n\n".join(combined_content_list)
        
        # Call the LLM refiner
        refined_text = extract_business_knowledge(combined_text)

        return jsonify({
            "status": "success",
            "data": {
                "extracted_text": refined_text,
                "primary_url": primary_url,
                "failed_urls": failed_urls
            }
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@knowledge_blueprint.route("/api/knowledge/scrape-embed", methods=["POST"])
@token_required
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

        text_content = data["text_content"]
        primary_url = data["primary_url"]
        
        # Default file name is the primary URL or custom override
        file_name = data.get("file_name", primary_url)

        result = save_refined_knowledge_chunks(
            text_content=text_content,
            file_name=file_name,
            primary_url=primary_url,
            chatbot_id=chatbot_id
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
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
