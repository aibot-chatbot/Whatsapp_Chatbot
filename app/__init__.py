from flask import Flask, request
import os
from flask_cors import CORS
from app.rate_limit import init_limiter
from app.config import load_configurations, configure_logging
from .views import webhook_blueprint
from app.routes.chat_routes import chat_blueprint
from app.routes.settings_routes import settings_blueprint
from app.routes.knowledge_routes import knowledge_blueprint
from app.routes.profile_routes import profile_blueprint
from app.routes.match_routes import match_blueprint
from app.routes.testbot_routes import testbot_blueprint
from app.routes.analytics_routes import analytics_blueprint
from app.routes.auth_routes import auth_bp
from app.routes.bot_routes import bot_blueprint
from app.routes.conversation_routes import conversation_blueprint
from app.routes.guide_router import guide_blueprint
from app.routes.telegram_routes import telegram_blueprint
from app.routes.whatsapp_routes import whatsapp_blueprint
from app.routes.wasender_routes import wasender_blueprint
from app.routes.ai_model_routes import ai_model_blueprint
from app.routes.crm_routes import crm_blueprint
from app.routes.agent_routes import agent_blueprint
from app.routes.media_attachment_routes import media_attachment_blueprint
from app.routes.meta_template_routes import meta_template_blueprint
from app.routes.flow_routes import flow_blueprint
from app.routes.user_routes import user_bp, team_bp
from app.routes.invite_routes import invite_bp
from app.routes.billing_routes import billing_bp
from app.routes.toyyibpay_routes import toyyibpay_bp
from app.routes.broadcast_routes import broadcast_blueprint
from app.routes.admin_billing_routes import admin_billing_bp
from app.routes.dev_billing_routes import dev_billing_bp
from app.routes.platform_admin_routes import platform_admin_bp
from app.routes.widget_routes import widget_blueprint

def create_app():
    # 1. Correctly locate the project root (up one level from 'app' folder)
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    # 2. Define both the template and the static folder paths
    app = Flask(__name__,
                template_folder=os.path.join(root_dir, 'frontend'),
                static_folder=os.path.join(root_dir, 'frontend'),
                static_url_path='')

    CORS(app, resources={r"/*": {"origins": "*"}})

    # Load configurations and logging settings
    load_configurations(app)
    configure_logging()

    CORS(app, resources={r"/*": {"origins": app.config["CORS_ORIGINS"]}})
    init_limiter(app)

    # ── Security response headers ──────────────────────────────────
    # The website chat widget is designed to be framed by customer sites,
    # so those routes opt out of X-Frame-Options: DENY. Their own
    # frame-ancestors CSP and per-widget domain allowlist apply instead.
    WIDGET_FRAMEABLE_PREFIXES = ("/widget/", "/chat/", "/api/widget/")

    def _is_frameable_widget_path(path):
        return path == "/widget.js" or path.startswith(WIDGET_FRAMEABLE_PREFIXES)

    @app.after_request
    def _add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not _is_frameable_widget_path(request.path):
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CSP omitted intentionally: the frontend uses many inline
        # scripts and styles that a strict CSP would break. A
        # nonce-based or hash-based CSP requires frontend build
        # tooling and is deferred to a later phase.
        return response

    # Register blueprints
    app.register_blueprint(webhook_blueprint)
    app.register_blueprint(chat_blueprint)
    app.register_blueprint(settings_blueprint)
    app.register_blueprint(knowledge_blueprint)
    app.register_blueprint(profile_blueprint)
    app.register_blueprint(match_blueprint)
    app.register_blueprint(testbot_blueprint)
    app.register_blueprint(analytics_blueprint)
    app.register_blueprint(auth_bp)
    app.register_blueprint(bot_blueprint)
    app.register_blueprint(conversation_blueprint)
    app.register_blueprint(guide_blueprint)
    app.register_blueprint(telegram_blueprint)
    app.register_blueprint(whatsapp_blueprint)
    app.register_blueprint(wasender_blueprint)
    app.register_blueprint(ai_model_blueprint)
    app.register_blueprint(crm_blueprint)
    app.register_blueprint(agent_blueprint)
    app.register_blueprint(media_attachment_blueprint)
    app.register_blueprint(meta_template_blueprint)
    app.register_blueprint(user_bp)
    app.register_blueprint(team_bp)
    app.register_blueprint(invite_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(toyyibpay_bp)
    app.register_blueprint(broadcast_blueprint)
    app.register_blueprint(admin_billing_bp)
    app.register_blueprint(platform_admin_bp)
    app.register_blueprint(widget_blueprint)
    if app.config.get("ENABLE_DEV_BILLING_ROUTES"):
        app.register_blueprint(dev_billing_bp)
    app.register_blueprint(flow_blueprint)

    # Serve frontend files as fallback for unmatched GET routes
    FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    
    # Serve media uploads
    MEDIA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "media_uploads"))
    os.makedirs(MEDIA_DIR, exist_ok=True)
    
    @app.route('/media/<path:filename>')
    def serve_media(filename):
        from flask import send_from_directory
        return send_from_directory(MEDIA_DIR, filename)

    @app.errorhandler(404)
    def serve_frontend_fallback(error):
        path = request.path.lstrip("/")
        if not path:
            path = "landing.html"
        if path.startswith("api/"):
            return {"status": "error", "message": "Not found"}, 404
        try:
            from flask import send_from_directory
            return send_from_directory(FRONTEND_DIR, path), 200
        except Exception:
            return {"status": "error", "message": "Not found"}, 404

    return app

