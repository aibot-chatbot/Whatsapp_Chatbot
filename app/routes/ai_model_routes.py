from flask import Blueprint, jsonify

from app.services.model_catalog import MODEL_CATALOG
from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required

ai_model_blueprint = Blueprint("ai_models", __name__)


@ai_model_blueprint.route("/api/ai-models", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_ai_models():
    try:
        return jsonify({
            "status": "success",
            "data": MODEL_CATALOG
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500