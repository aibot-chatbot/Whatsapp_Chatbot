from flask import Blueprint, jsonify, request
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access

from app.services.knowledge_service import (
    list_uploaded_pdfs,
    delete_pdf_file,
    get_active_pdf,
    set_active_pdf,
    scrape_website_url,
    discover_website_links,
    scrape_website_urls_batch,
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
