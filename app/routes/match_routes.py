from flask import Blueprint, jsonify, request

from app.services.match_service import check_pdf_config_match

match_blueprint = Blueprint("match", __name__)


@match_blueprint.route("/api/match/check", methods=["POST"])
def check_match():
    try:
        data = request.get_json() or {}
        profile_name = data.get("profile_name")

        result = check_pdf_config_match(profile_name=profile_name)

        return jsonify({
            "status": "success",
            "data": result
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