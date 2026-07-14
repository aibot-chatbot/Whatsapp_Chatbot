from flask import Blueprint, jsonify

from app.services.model_catalog import get_models_with_tiers
from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
from app.utils.access_control import get_current_company_id

ai_model_blueprint = Blueprint("ai_models", __name__)


@ai_model_blueprint.route("/api/ai-models", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_ai_models():
    try:
        all_models = get_models_with_tiers()

        company_id = get_current_company_id()
        if company_id:
            from app.services.ai_access_policy import (
                resolve_ai_access,
                TRIAL_MODEL,
                STATE_ACTIVE_TRIAL,
                STATE_EXPIRED_TRIAL,
                STATE_FREE_NO_TRIAL,
            )
            from app.services.ai_access_policy import PLAN_CODE_FREE
            policy = resolve_ai_access(company_id)

            # All Free-plan states (valid trial, expired trial, active
            # without trial_ends_at) get the DeepSeek-only read-only
            # catalogue.  Paid users get the full catalogue unchanged.
            free_trial_states = {STATE_ACTIVE_TRIAL, STATE_EXPIRED_TRIAL, STATE_FREE_NO_TRIAL}
            if policy.access_state in free_trial_states:
                filtered = {}
                for key, entry in all_models.items():
                    if key == "deepseek":
                        filtered["deepseek"] = {
                            "label": entry["label"],
                            "models": [
                                m for m in entry.get("models", [])
                                if m.get("value") == TRIAL_MODEL
                            ],
                        }
                response = {
                    "status": "success",
                    "data": filtered,
                    "read_only": True,
                    "access_allowed": policy.allowed,
                    "access_state": policy.access_state,
                }
                if not policy.allowed and policy.denial_reason:
                    response["denial_reason"] = policy.denial_reason
                return jsonify(response), 200

        return jsonify({
            "status": "success",
            "data": all_models
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
