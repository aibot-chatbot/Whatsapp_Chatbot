from flask import Blueprint, jsonify, request, g

from app.decorators.auth_decorator import token_required
from app.utils.access_control import role_required, verify_chatbot_access
from app.services.billing_guard import can_use_plan_feature, BillingLimitError
from app.database.analytics_repository import (
    get_total_users,
    get_total_user_messages,
    get_recent_history,
    get_message_chart_last_7_days,
)
from app.database.agent_action_repository import get_agent_insights_by_chatbot
from app.utils.api_errors import server_error

analytics_blueprint = Blueprint("analytics", __name__)

INSIGHT_SUMMARY_KEYS = {
    "lead_interest": "follow_up_opportunities",
    "handoff_request": "needs_staff_attention",
    "complaint": "negative_feedback",
    "knowledge_gap": "missing_answers",
}

INSIGHT_LABELS = {
    "lead_interest": "Follow-up opportunity detected",
    "handoff_request": "Customer may need staff attention",
    "complaint": "Negative feedback detected",
    "knowledge_gap": "Missing answer detected",
}

ACTION_NEXT_STEPS = {
    "answer": "Review if further assistance is needed",
    "ask_follow_up": "Ask one helpful follow-up question",
    "create_lead": "Review for business follow-up",
    "request_handoff": "Team member should follow up",
    "log_knowledge_gap": "Update PDF or website knowledge",
    "none": "Review when convenient",
}


def _format_agent_insight_row(row):
    intent = row.get("intent") or "unknown"
    action_type = row.get("action_type") or "none"

    return {
        "label": INSIGHT_LABELS.get(intent, "Follow-up signal detected"),
        "suggested_next_step": ACTION_NEXT_STEPS.get(action_type, ACTION_NEXT_STEPS["none"]),
        "confidence": row.get("confidence"),
        "created_at": row.get("created_at"),
    }


@analytics_blueprint.route("/api/analytics", methods=["GET"])
@token_required
def get_analytics():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

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
        return server_error("get_analytics", e)


@analytics_blueprint.route("/api/analytics/report", methods=["GET"])
@token_required
@role_required("owner", "admin")
def get_ai_report():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        days = request.args.get("days", 7, type=int)
        if not 1 <= days <= 366:
            raise ValueError("days must be between 1 and 366")

        # Subscription feature guard
        can_use_plan_feature(g.company_id, "ai_generated_reports")

        verify_chatbot_access(chatbot_id)

        from app.services.report_service import generate_weekly_report
        report = generate_weekly_report(chatbot_id=chatbot_id, days=days)

        return jsonify({
            "status": "success",
            "data": {
                "report": report
            }
        }), 200

    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403

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
        }), 400

    except Exception as e:
        return server_error("get_ai_report", e)


@analytics_blueprint.route("/api/dashboard/live-workflow", methods=["GET"])
@token_required
def get_live_workflow():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        from app.services.workflow_tracker import get_workflow_state
        state = get_workflow_state(chatbot_id)

        return jsonify({
            "status": "success",
            "data": state
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
        return server_error("get_live_workflow", e)


@analytics_blueprint.route("/api/dashboard/health", methods=["GET"])
@token_required
def get_dashboard_health_summary():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        access = verify_chatbot_access(chatbot_id)

        from app.services.dashboard_health_service import get_dashboard_health
        health = get_dashboard_health(chatbot_id, access["company_id"])

        return jsonify({
            "status": "success",
            "data": health
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
        return server_error("get_dashboard_health_summary", e)


@analytics_blueprint.route("/api/agent/insights", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_agent_insights():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)

        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)

        insights = get_agent_insights_by_chatbot(chatbot_id, limit=10)
        raw_summary = insights.get("summary") or {}

        summary = {
            frontend_key: raw_summary.get(intent, 0)
            for intent, frontend_key in INSIGHT_SUMMARY_KEYS.items()
        }

        recent = [
            _format_agent_insight_row(row)
            for row in insights.get("recent") or []
        ]

        return jsonify({
            "status": "success",
            "data": {
                "summary": summary,
                "recent": recent,
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
        return server_error("get_agent_insights", e)
