import logging

from flask import Blueprint, abort, g, jsonify, request
from werkzeug.exceptions import BadRequest, Forbidden

from app.database.whatsapp_channel_repository import get_whatsapp_channels_by_chatbot
from app.decorators.auth_decorator import token_required
from app.services.company_status_service import company_operational_required
from app.services.meta_template_service import create_meta_template, delete_meta_template, get_meta_templates
from app.utils.access_control import role_required, verify_chatbot_access

meta_template_blueprint = Blueprint("meta_templates", __name__)


def _connected_channel():
    chatbot_id = request.args.get("chatbot_id", type=int)
    if not chatbot_id:
        abort(400, description="chatbot_id is required")
    try:
        verify_chatbot_access(chatbot_id)
    except PermissionError:
        abort(403, description="Access denied.")
    for channel in get_whatsapp_channels_by_chatbot(chatbot_id):
        if (channel.get("company_id") == g.company_id and channel.get("chatbot_id") == chatbot_id
                and channel.get("is_active") and channel.get("connection_status") == "connected"
                and (channel.get("whatsapp_business_account_id") or channel.get("waba_id"))
                and channel.get("access_token")):
            return channel
    abort(400, description="No active Meta WhatsApp integration found for this bot.")


@meta_template_blueprint.errorhandler(BadRequest)
@meta_template_blueprint.errorhandler(Forbidden)
def _invalid_request(error):
    return jsonify(status="error", message=error.description), error.code


@meta_template_blueprint.errorhandler(Exception)
def _template_error(error):
    logging.error("Meta template request failed (%s)", type(error).__name__)
    return jsonify(status="error", message="The template request could not be completed."), 500


@meta_template_blueprint.route("/api/meta-templates", methods=["GET"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def list_meta_templates():
    channel = _connected_channel()
    waba_id = channel.get("whatsapp_business_account_id") or channel["waba_id"]
    return jsonify(status="success", data=get_meta_templates(waba_id, channel["access_token"])), 200


@meta_template_blueprint.route("/api/meta-templates", methods=["POST"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def add_meta_template():
    channel = _connected_channel()
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip():
        abort(400, description="Template name is required")
    result = create_meta_template(channel, data["name"], data.get("language", "en_US"),
                                  data.get("category", "MARKETING"), data.get("components", []))
    return jsonify(status="success", message="Template submitted to Meta successfully", data=result), 201


@meta_template_blueprint.route("/api/meta-templates/<template_name>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
@company_operational_required
def remove_meta_template(template_name):
    channel = _connected_channel()
    delete_meta_template(channel, template_name)
    return jsonify(status="success", message="Template deleted successfully from Meta"), 200
