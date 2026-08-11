from flask import Blueprint, jsonify, request, g

from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required
from app.services.billing_guard import can_create_chatbot, can_use_plan_feature, BillingLimitError
from app.services.bot_service import (
    list_bots,
    list_archived_bots,
    get_bot,
    add_bot,
    edit_bot,
    remove_bot,
    restore_archived_bot,
    permanently_delete_archived_bot,
    PermanentBotDeleteError,
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


@bot_blueprint.route("/api/bots/archived", methods=["GET"])
@token_required
def fetch_archived_bots():
    try:
        company_id = get_current_company_id()
        bots = list_archived_bots(company_id)

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


@bot_blueprint.route("/api/bots/<int:bot_id>/restore", methods=["POST"])
@token_required
@role_required("admin", "owner")
def restore_existing_bot(bot_id):
    try:
        company_id = get_current_company_id()
        bot = restore_archived_bot(bot_id, company_id)

        return jsonify({
            "status": "success",
            "data": bot,
            "message": "Bot restored successfully"
        }), 200

    except BillingLimitError as e:
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
            "details": e.details or {}
        }), 403

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


@bot_blueprint.route("/api/bots/<int:bot_id>/permanent", methods=["DELETE"])
@token_required
@role_required("admin", "owner")
def permanently_delete_existing_bot(bot_id):
    try:
        data = request.get_json(silent=True) or {}
        confirm_bot_name = data.get("confirm_bot_name")
        company_id = get_current_company_id()

        permanently_delete_archived_bot(
            bot_id,
            company_id,
            confirm_bot_name,
        )

        return jsonify({
            "status": "success",
            "message": "Bot permanently deleted"
        }), 200

    except LookupError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 404

    except PermanentBotDeleteError as e:
        status_code = 403 if e.code == "active_bot" else 400
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e)
        }), status_code

    except Exception:
        return jsonify({
            "status": "error",
            "message": "Unable to permanently delete bot. Please try again or contact support."
        }), 500



@bot_blueprint.route("/api/bots/<int:bot_id>/generate-welcome-menu", methods=["POST"])
@token_required
@role_required("admin", "owner")
def generate_bot_welcome_menu(bot_id):
    try:
        company_id = get_current_company_id()
        
        # Verify bot access
        bot = get_bot(bot_id, company_id)
        if not bot:
            return jsonify({"status": "error", "message": "Bot not found"}), 404
            
        from app.services.ai_router import generate_welcome_menu_suggestions
        suggestions, source_document = generate_welcome_menu_suggestions(bot_id, company_id)
        
        if not suggestions:
             return jsonify({
                "status": "error",
                "message": "AI could not generate suggestions. Try adding more context to your document."
            }), 400

        return jsonify({
            "status": "success",
            "data": suggestions,
            "source_document": source_document,
            "message": "Welcome menu suggestions generated successfully"
        }), 200

    except ValueError as ve:
        return jsonify({
            "status": "error",
            "message": str(ve)
        }), 400
    except Exception as e:
        import logging
        logging.error(f"Error generating welcome menu suggestions: {e}")
        return jsonify({
            "status": "error",
            "message": "An unexpected error occurred during generation."
        }), 500
