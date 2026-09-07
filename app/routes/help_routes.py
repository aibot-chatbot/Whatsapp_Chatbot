"""Read-only help article routes for authenticated tenant users."""

from flask import Blueprint, g, jsonify, request

from app.decorators.auth_decorator import token_required
from app.services import help_article_service


help_bp = Blueprint("help", __name__, url_prefix="/api/help")


@help_bp.get("/articles")
@token_required
def list_help_articles():
    """Published articles, global to the platform - no tenant filter.

    The error envelope is {status, message} rather than the {status, code,
    message} used by support_routes.py, because 03-design.md section 5 pins
    this response shape exactly.
    """
    try:
        result = help_article_service.list_published_articles()
        return jsonify({"status": "success", "data": result}), 200
    except help_article_service.HelpArticleServiceError as exc:
        return jsonify({
            "status": "error",
            "message": exc.message,
        }), exc.status_code


@help_bp.post("/articles/<int:article_id>/feedback")
@token_required
def record_help_article_feedback(article_id):
    """One helpfulness vote per tenant per article.

    Unlike the read route above, the error envelope carries a `code`: this
    endpoint has several distinct rejections and the page has to tell them
    apart. The tenant comes from g, never from the body - the support page
    contract forbids the string "company_id" appearing in its JavaScript.
    """
    try:
        result = help_article_service.record_article_feedback(
            article_id,
            request.get_json(silent=True),
            company_id=g.company_id,
        )
        return jsonify({"status": "success", "data": result}), 200
    except help_article_service.HelpArticleServiceError as exc:
        return jsonify({
            "status": "error",
            "code": exc.code,
            "message": exc.message,
        }), exc.status_code
