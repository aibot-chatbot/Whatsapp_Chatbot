from time import monotonic

from flask import Blueprint, g, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from app.services.ai_router import generate_response, OPERATION_TEST_BOT
from app.services.settings_service import get_deployed_runtime
from app.services.profile_service import get_profile_by_name
from app.services.test_scenario_service import build_test_scenarios
from app.database.conversation_repository import reset_testbot_conversation, get_or_create_conversation
from app.decorators.auth_decorator import token_required
from app.utils.access_control import get_current_role, verify_chatbot_access, role_required
from app.services.billing_guard import BillingLimitError
from app.utils.api_errors import server_error
from app.rate_limit import limiter, user_rate_limit_key
from app.services import ai_gateway, test_scenario_service as publish_test_service

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


@testbot_blueprint.before_request
def _publish_request_deadline():
    if request.endpoint in {"testbot.latest_publish_test", "testbot.start_publish_test",
                            "testbot.answer_publish_test", "testbot.override_publish_test"}:
        g.publish_test_request_deadline = monotonic() + 80
        request.max_content_length = min(request.max_content_length or 20000, 20000)


def _publish_test_request(operation, run_id=None):
    chatbot_id = request.args.get("chatbot_id", type=int)
    if not chatbot_id:
        return jsonify(status="error", message="chatbot_id is required"), 400
    try:
        company_id = verify_chatbot_access(chatbot_id)["company_id"]
        can_override = get_current_role() in {"owner", "admin"}
        if operation == "override" and not can_override:
            return jsonify(status="error", message="Only an owner or admin can publish anyway."), 403
        body = request.get_json(silent=True) if request.data else {}
        fields = {"answer": {"ticket", "key"}, "override": {"acknowledged_keys"}}.get(operation, set())
        if not isinstance(body, dict) or set(body) != fields:
            return jsonify(status="error", message="Invalid publishing test request."), 400
        if operation in ("start", "answer"):
            g.publish_test = True
            ai_gateway.publish_test_timeout()
        if operation == "start":
            data = publish_test_service.start(chatbot_id, company_id)
        elif operation == "answer":
            data = publish_test_service.answer(chatbot_id, company_id, run_id, body["ticket"], body["key"])
        elif operation == "override":
            data = publish_test_service.override(chatbot_id, company_id, run_id, g.user_id, body["acknowledged_keys"])
        else:
            data = publish_test_service.status(chatbot_id, company_id)
        response = jsonify(status="success", data={**data, "can_override": can_override})
        response.headers["Cache-Control"] = "no-store"
        return response
    except PermissionError as error:
        return jsonify(status="error", message=str(error)), 403
    except RequestEntityTooLarge:
        return jsonify(status="error", message="Publishing test request is too large."), 413
    except publish_test_service.PublishTestError as error:
        return jsonify(status="error", message=str(error)), error.status
    except Exception as error:
        return server_error("publish_test", error)


# Same roles as Test Lab chat: runs spend the client's AI credits, and only owners/admins can connect channels.
@testbot_blueprint.get("/api/testbot/publish-test")
@token_required
@role_required("admin", "owner")
def latest_publish_test():
    return _publish_test_request("status")


@testbot_blueprint.post("/api/testbot/publish-test")
@token_required
@role_required("admin", "owner")
@limiter.limit("6 per hour", key_func=user_rate_limit_key)
def start_publish_test():
    return _publish_test_request("start")


@testbot_blueprint.post("/api/testbot/publish-test/<run_id>/answer")
@token_required
@role_required("admin", "owner")
def answer_publish_test(run_id):
    return _publish_test_request("answer", run_id)


@testbot_blueprint.post("/api/testbot/publish-test/<run_id>/override")
@token_required
@role_required("admin", "owner")
def override_publish_test(run_id):
    return _publish_test_request("override", run_id)


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


@testbot_blueprint.route("/api/testbot/reset", methods=["POST"])
@token_required
@role_required("admin", "owner")
def reset_testbot():
    try:
        chatbot_id = request.args.get("chatbot_id", type=int)
        if not chatbot_id:
            return jsonify({"status": "error", "message": "chatbot_id is required"}), 400

        access = verify_chatbot_access(chatbot_id)
        reset_testbot_conversation(chatbot_id, access["company_id"], TESTBOT_SESSION_ID)
        return jsonify({"status": "success"}), 200
    except PermissionError as e:
        return jsonify({"status": "error", "message": str(e)}), 403
    except Exception as e:
        return server_error("reset_testbot", e)


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
        conversation = get_or_create_conversation(chatbot_id, TESTBOT_SESSION_ID, source_channel="web")
        reply = generate_response(
            user_message,
            TESTBOT_SESSION_ID,
            chatbot_id,
            source_channel="web",
            operation_type=OPERATION_TEST_BOT,
            conversation_id=conversation["id"],
        )
        if reply == "<SILENT_BOT_RESPONSE>":
            reply = "This conversation is currently assigned to human staff."

        return jsonify({
            "status": "success",
            "data": {
                "reply": reply,
                "grade": getattr(g, "reply_grade", None) or {"status": "unchecked", "checks": []},
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
