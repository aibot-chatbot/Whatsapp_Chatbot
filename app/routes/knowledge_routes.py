from flask import Blueprint, jsonify, request

from app.services.knowledge_service import (
    list_uploaded_pdfs,
    delete_pdf_file,
    get_active_pdf,
    set_active_pdf,
)

knowledge_blueprint = Blueprint("knowledge", __name__)


@knowledge_blueprint.route("/api/knowledge/files", methods=["GET"])
def get_uploaded_pdfs():
    try:
        files = list_uploaded_pdfs()
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
def get_current_active_pdf():
    try:
        active_pdf = get_active_pdf()
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
def set_current_active_pdf():
    try:
        data = request.get_json()

        if not data or "file_name" not in data:
            return jsonify({
                "status": "error",
                "message": "file_name is required"
            }), 400

        result = set_active_pdf(data["file_name"])

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


@knowledge_blueprint.route("/api/knowledge/files/<file_name>", methods=["DELETE"])
def delete_uploaded_pdf(file_name):
    try:
        result = delete_pdf_file(file_name)
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