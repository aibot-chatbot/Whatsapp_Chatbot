from flask import Blueprint, jsonify, request

from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access
from app.database.analytics_repository import (
    get_total_users,
    get_total_user_messages,
    get_recent_history,
    get_message_chart_last_7_days,
)

analytics_blueprint = Blueprint("analytics", __name__)


@analytics_blueprint.route("/api/analytics", methods=["GET"])
@token_required
def get_analytics():
    try:
        chatbot_id = request.args.get("chatbot_id", 1, type=int)

        verify_chatbot_access(chatbot_id)

        total_users = get_total_users(chatbot_id)
        total_messages = get_total_user_messages(chatbot_id)
        recent_history = get_recent_history(chatbot_id, limit=4)
        chart = get_message_chart_last_7_days(chatbot_id)

        return jsonify({
            "status": "success",
            "data": {
                "total_users": total_users,
                "total_messages": total_messages,
                "recent_history": recent_history,
                "chart": chart
            }
        }), 200

    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403

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