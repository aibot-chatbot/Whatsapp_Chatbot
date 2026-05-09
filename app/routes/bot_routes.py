from flask import Blueprint, jsonify, request, g

from app.decorators.auth_decorator import token_required
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
def create_new_bot():
    try:
        data = request.get_json() or {}
        company_id = get_current_company_id()

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

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bot_blueprint.route("/api/bots/<int:bot_id>", methods=["PUT"])
@token_required
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

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@bot_blueprint.route("/api/bots/<int:bot_id>", methods=["DELETE"])
@token_required
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