from flask import Blueprint, jsonify, request

from app.services.ai_router import generate_response, OPERATION_TEST_BOT
from app.services.settings_service import get_deployed_runtime
from app.services.profile_service import get_profile_by_name
from app.services.test_scenario_service import build_test_scenarios
from app.decorators.auth_decorator import token_required
from app.utils.access_control import verify_chatbot_access, role_required
from app.services.billing_guard import BillingLimitError
from app.utils.api_errors import server_error

testbot_blueprint = Blueprint("testbot", __name__)
TESTBOT_SESSION_ID = "web_testbot_session"

#: "Let me talk to a person" is the same test for a shop, a clinic and a
#: school, so it is never derived from the document and never billed.  It is
#: appended last so it is on screen even when the business could not be read at
#: all -- including when the company has run out of AI credit, which is exactly
#: when an operator most wants to check the escape hatch still works.
HANDOFF_SCENARIO = {
    "key": "handoff",
    "name": "Ask for a human",
    "goal": "Hand the conversation to your team",
    "message": "I would rather speak to a real person please.",
}

@testbot_blueprint.route("/api/testbot/context", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_testbot_context():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        deployed = get_deployed_runtime(chatbot_id)
        profile_name = deployed.get("deployed_profile_name", "")
        profile = get_profile_by_name(profile_name, chatbot_id) if profile_name else {}

        return jsonify({
            "status": "success",
            "data": {
                "active_profile": profile_name,
                "bot_name": (profile or {}).get("bot_name", ""),
                "company_name": (profile or {}).get("company_name", ""),
                "active_pdf": deployed.get("deployed_pdf_file_name", "")
            }
        }), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return server_error("get_testbot_context", e)

@testbot_blueprint.route("/api/testbot/scenarios", methods=["GET"])
@token_required
@role_required("admin", "owner")
def get_testbot_scenarios():
    """The questions worth asking this particular business's bot.

    Derived from the bot's own active document, because a shop, a clinic and a
    school do not share a single useful test. Always returns a usable set --
    ``matched`` says whether it came from the document, and ``note`` says why
    not in words the operator can act on.
    """
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        result = build_test_scenarios(chatbot_id)
        result["scenarios"] = list(result["scenarios"]) + [dict(HANDOFF_SCENARIO)]

        return jsonify({"status": "success", "data": result}), 200

    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@testbot_blueprint.route("/api/testbot/chat", methods=["POST"])
@token_required
@role_required("admin", "owner")
def chat_with_testbot():
    try:
        data = request.get_json() or {}
        user_message = (data.get("message") or "").strip()

        if not user_message:
            return jsonify({
                "status": "error",
                "message": "Message is required."
            }), 400

        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({
                "status": "error",
                "message": "chatbot_id is required"
            }), 400

        verify_chatbot_access(chatbot_id)
        reply = generate_response(
            user_message,
            TESTBOT_SESSION_ID,
            chatbot_id,
            source_channel="web",
            operation_type=OPERATION_TEST_BOT,
        )
        if reply == "<SILENT_BOT_RESPONSE>":
            reply = "This conversation is currently assigned to human staff."

        return jsonify({
            "status": "success",
            "data": {
                "reply": reply
            }
        }), 200
    except PermissionError as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 403
    except BillingLimitError as e:
        if e.code == "ai_credit_insufficient":
            return jsonify({
                "status": "error",
                "code": "ai_credit_insufficient",
                "message": str(e)
            }), 402
        return jsonify({
            "status": "error",
            "code": e.code,
            "message": str(e),
            "details": e.details or {}
        }), 403
    except Exception as e:
        return server_error("chat_with_testbot", e)
