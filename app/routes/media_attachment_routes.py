from flask import Blueprint, request, jsonify, g
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
import logging

from app.database.bot_media_attachment_repository import (
    get_all_attachments,
    get_attachment_by_id,
    create_attachment,
    update_attachment,
    delete_attachment
)

media_attachment_blueprint = Blueprint("media_attachments", __name__)

@media_attachment_blueprint.route("/api/media-attachments", methods=["GET"])
@token_required
@role_required("admin", "owner")
def list_attachments():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)
        
        attachments = get_all_attachments(chatbot_id)
        
        return jsonify({
            "status": "success",
            "data": attachments
        }), 200

    except Exception as e:
        logging.error(f"List media attachments error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@media_attachment_blueprint.route("/api/media-attachments/upload", methods=["POST"])
@token_required
@role_required("admin", "owner")
def upload_attachment_file():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)
        
        if "media_file" not in request.files:
            return jsonify({"status": "error", "message": "No file part"}), 400
            
        file = request.files["media_file"]
        if file.filename == "":
            return jsonify({"status": "error", "message": "No selected file"}), 400
            
        import os
        from werkzeug.utils import secure_filename
        
        # Save into MEDIA_FOLDER, which sits on the mounted disk. Writing to
        # the old repo-relative media_uploads/ put uploads outside the volume,
        # so every file a tenant uploaded was deleted on the next deploy while
        # the rows and campaigns referencing its URL survived.
        from app.storage_paths import MEDIA_FOLDER

        os.makedirs(MEDIA_FOLDER, exist_ok=True)
        
        original_name = secure_filename(file.filename)
        safe_name = f"bot_{chatbot_id}_{original_name}"
        
        filepath = os.path.join(MEDIA_FOLDER, safe_name)
        file.save(filepath)
        
        public_url = request.host_url.rstrip("/") + f"/media/{safe_name}"
        
        return jsonify({
            "status": "success",
            "message": "File uploaded successfully",
            "data": {
                "public_url": public_url
            }
        }), 201

    except Exception as e:
        logging.error(f"Upload media attachment error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@media_attachment_blueprint.route("/api/media-attachments", methods=["POST"])
@token_required
@role_required("admin", "owner")
def add_attachment():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        access = verify_chatbot_access(chatbot_id)
        company_id = access["company_id"]
        
        data = request.get_json() or {}
        
        # Validation
        if not data.get("label"):
            return jsonify({"status": "error", "message": "label is required"}), 400
        if not data.get("media_url"):
            return jsonify({"status": "error", "message": "media_url is required"}), 400
            
        attachment = create_attachment(chatbot_id, company_id, data)
        
        if not attachment:
            return jsonify({"status": "error", "message": "Failed to create attachment"}), 500
            
        return jsonify({
            "status": "success",
            "message": "Media attachment created successfully",
            "data": attachment
        }), 201

    except Exception as e:
        logging.error(f"Create media attachment error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@media_attachment_blueprint.route("/api/media-attachments/<int:attachment_id>", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def edit_attachment(attachment_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)
        
        existing = get_attachment_by_id(attachment_id, chatbot_id)
        if not existing:
            return jsonify({"status": "error", "message": "Attachment not found"}), 404
            
        data = request.get_json() or {}
        
        # Validation
        if "label" in data and not data["label"]:
            return jsonify({"status": "error", "message": "label cannot be empty"}), 400
        if "media_url" in data and not data["media_url"]:
            return jsonify({"status": "error", "message": "media_url cannot be empty"}), 400
            
        attachment = update_attachment(attachment_id, chatbot_id, data)
        
        if not attachment:
            return jsonify({"status": "error", "message": "Failed to update attachment"}), 500
            
        return jsonify({
            "status": "success",
            "message": "Media attachment updated successfully",
            "data": attachment
        }), 200

    except Exception as e:
        logging.error(f"Update media attachment error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@media_attachment_blueprint.route("/api/media-attachments/<int:attachment_id>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def remove_attachment(attachment_id):
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        verify_chatbot_access(chatbot_id)
        
        existing = get_attachment_by_id(attachment_id, chatbot_id)
        if not existing:
            return jsonify({"status": "error", "message": "Attachment not found"}), 404
            
        delete_attachment(attachment_id, chatbot_id)
        
        return jsonify({
            "status": "success",
            "message": "Media attachment deleted successfully"
        }), 200

    except Exception as e:
        logging.error(f"Delete media attachment error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
