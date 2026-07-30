from flask import Blueprint, jsonify, request, g

from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
from app.services.billing_guard import can_create_chatbot, can_use_plan_feature, BillingLimitError
from app.services.bot_service import (
    list_bots,
    get_bot,
    add_bot,
    edit_bot,
    remove_bot,
)

bot_blueprint = Blueprint("bots", __name__)


def get_current_company_id():
    company_id = getattr(g, "company_id", None)

    if not company_id:
        raise ValueError("Company ID not found in token. Please login again.")

    return company_id


@bot_blueprint.route("/api/bots", methods=["GET"])
@token_required
def fetch_bots():
    try:
        company_id = get_current_company_id()
        bots = list_bots(company_id)

        return jsonify({
            "status": "success",
            "data": bots
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 401

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bot_blueprint.route("/api/bots/<int:bot_id>", methods=["GET"])
@token_required
def fetch_bot(bot_id):
    try:
        company_id = get_current_company_id()
        bot = get_bot(bot_id, company_id)

        return jsonify({
            "status": "success",
            "data": bot
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 404

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bot_blueprint.route("/api/bots", methods=["POST"])
@token_required
@role_required("admin", "owner")
def create_new_bot():
    try:
        data = request.get_json() or {}
        company_id = get_current_company_id()
        # Check subscription limit before creating
        can_create_chatbot(company_id)

        bot = add_bot(data, company_id)

        return jsonify({
            "status": "success",
            "data": bot,
            "message": "Bot created successfully"
        }), 201

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
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bot_blueprint.route("/api/bots/<int:bot_id>", methods=["PUT"])
@token_required
@role_required("admin", "owner")
def update_existing_bot(bot_id):
    try:
        data = request.get_json() or {}
        company_id = get_current_company_id()

        bot = edit_bot(bot_id, data, company_id)

        return jsonify({
            "status": "success",
            "data": bot,
            "message": "Bot updated successfully"
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
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bot_blueprint.route("/api/bots/<int:bot_id>", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def delete_existing_bot(bot_id):
    try:
        company_id = get_current_company_id()

        remove_bot(bot_id, company_id)

        return jsonify({
            "status": "success",
            "message": "Bot deleted successfully"
        }), 200

    except ValueError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 404

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bot_blueprint.route("/api/bots/<int:bot_id>/auto-generate-menu", methods=["POST"])
@token_required
@role_required("admin", "owner")
def auto_generate_menu(bot_id):
    try:
        # Validate company ownership first (security)
        company_id = get_current_company_id()
        bot = get_bot(bot_id, company_id)
        if not bot:
            return jsonify({"status": "error", "message": "Bot not found"}), 404

        # Check subscription feature access for AI-assisted menu generation
        can_use_plan_feature(company_id, "ai_assisted_menu_generation")

        from app.services.flow_builder_service import auto_generate_welcome_menu
        
        result = auto_generate_welcome_menu(bot_id)

        return jsonify({
            "status": "success",
            "data": result,
            "message": "Menu generated successfully"
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
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bot_blueprint.route("/api/bots/<int:bot_id>/extract-data-points", methods=["POST"])
@token_required
@role_required("admin", "owner")
def extract_data_points(bot_id):
    try:
        company_id = get_current_company_id()
        bot = get_bot(bot_id, company_id)
        if not bot:
            return jsonify({"status": "error", "message": "Bot not found"}), 404

        # Reuse same subscription feature gate as auto-generate
        can_use_plan_feature(company_id, "ai_assisted_menu_generation")

        req_json = request.get_json(silent=True) or {}
        force_refresh = bool(req_json.get("force_refresh", False))

        from app.services.flow_builder_service import extract_pdf_data_points

        result = extract_pdf_data_points(bot_id, force_refresh=force_refresh)

        return jsonify({
            "status": "success",
            "data": result,
            "message": "Data points extracted successfully"
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
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500
