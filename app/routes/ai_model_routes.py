from flask import Blueprint, jsonify

from app.services.model_catalog import get_models_for_plan, plan_code_for_policy
from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
from app.utils.access_control import get_current_company_id
from app.utils.api_errors import server_error

ai_model_blueprint = Blueprint("ai_models", __name__)


@ai_model_blueprint.route("/api/ai-models", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_ai_models():
    try:
        from app.services.ai_access_policy import resolve_ai_access

        policy = resolve_ai_access(get_current_company_id())
        response = {
            "status": "success",
            "data": get_models_for_plan(plan_code_for_policy(policy)),
            "read_only": not policy.allowed or not policy.model_editable,
            "access_allowed": policy.allowed,
            "access_state": policy.access_state,
        }
        if policy.denial_reason:
            response["denial_reason"] = policy.denial_reason
        return jsonify(response), 200

    except Exception as e:
        return server_error("get_ai_models", e)
