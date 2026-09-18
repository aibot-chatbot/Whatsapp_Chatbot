from flask import Flask, request, current_app
import os
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_cors import CORS
from app.rate_limit import init_limiter, limiter
from app.config import load_configurations, configure_logging
from app.observability import init_sentry
from app.storage_paths import MEDIA_FOLDER, LEGACY_MEDIA_FOLDER
from app.services.upload_validation_service import MAX_UPLOAD_BYTES
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
from app.routes.company_routes import company_blueprint
from app.routes.conversation_routes import conversation_blueprint
from app.routes.telegram_routes import telegram_blueprint
from app.routes.whatsapp_routes import whatsapp_blueprint
from app.routes.wasender_routes import wasender_blueprint
from app.routes.ai_model_routes import ai_model_blueprint
from app.routes.crm_routes import crm_blueprint
from app.routes.agent_routes import agent_blueprint
from app.routes.media_attachment_routes import media_attachment_blueprint
from app.routes.meta_template_routes import meta_template_blueprint

from app.routes.user_routes import user_bp, team_bp
from app.routes.invite_routes import invite_bp
from app.routes.billing_routes import billing_bp
from app.routes.chip_routes import chip_bp
from app.routes.broadcast_routes import broadcast_blueprint
from app.routes.admin_billing_routes import admin_billing_bp
from app.routes.dev_billing_routes import dev_billing_bp
from app.routes.platform_admin_routes import platform_admin_bp
from app.routes.support_routes import support_bp
from app.routes.help_routes import help_bp
from app.routes.widget_routes import widget_blueprint
from app.routes.flow_routes import flow_blueprint
from app.routes.automation_routes import automation_blueprint

def create_app():
    # 1. Correctly locate the project root (up one level from 'app' folder)
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

    # 2. Define both the template and the static folder paths
    app = Flask(__name__,
                template_folder=os.path.join(root_dir, 'frontend'),
                static_folder=os.path.join(root_dir, 'frontend'),
                static_url_path='/static')

    # Behind Render's router the socket peer is the proxy, not the visitor.
    # Two things break without this. app/rate_limit.py keys unauthenticated
    # limits on remote_addr, so every visitor across every tenant would share
    # one login/OTP bucket - one bad actor locks out the whole platform. And
    # request.host_url comes back http://, which gets baked into widget embed
    # snippets and media URLs.
    #
    # 1 = trust Render's hop only. Raise it only once ingress is restricted to
    # Cloudflare's ranges; until then anything hitting *.onrender.com directly
    # can forge the extra X-Forwarded-For entries a higher count would trust.
    _hops_raw = os.getenv("TRUSTED_PROXY_HOPS", "1").strip()
    try:
        _proxy_hops = int(_hops_raw)
    except ValueError as exc:
        raise RuntimeError(
            f"TRUSTED_PROXY_HOPS must be an integer, got {_hops_raw!r}."
        ) from exc
    if _proxy_hops < 0:
        # ProxyFix treats a negative count as truthy and indexes values[-n],
        # so it would quietly trust a *less* distant hop rather than fail.
        raise RuntimeError(
            f"TRUSTED_PROXY_HOPS must be zero or positive, got {_proxy_hops}."
        )
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=_proxy_hops, x_proto=_proxy_hops, x_host=_proxy_hops
    )

    # Load configurations and logging settings. This must come before CORS is
    # registered: the allowed origins are read from config, and an earlier
    # CORS(origins="*") call here would win over this one and echo back any
    # Origin the caller sends, silently voiding CORS_ORIGINS entirely.
    load_configurations(app)
    configure_logging()
    init_sentry()

    CORS(app, resources={r"/*": {"origins": app.config["CORS_ORIGINS"]}})
    init_limiter(app)

    @app.before_request
    def _limit_upload_requests():
        if request.endpoint in {
            "webhook.upload_pdf", "knowledge.validate_pdf_candidate",
            "media_attachments.upload_attachment_file",
        }:
            # Bound multipart parsing, including streams without Content-Length.
            request.max_content_length = min(
                request.max_content_length or MAX_UPLOAD_BYTES, MAX_UPLOAD_BYTES
            )

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
        response.headers["Referrer-Policy"] = (
            "no-referrer" if request.path.startswith("/media/")
            else "strict-origin-when-cross-origin"
        )
        if (request.path.startswith(("/api/", "/media/"))
                or request.path == "/upload-pdf"
                or "Authorization" in request.headers):
            # Tenant responses and shared document links must not enter caches.
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["CDN-Cache-Control"] = "no-store"
            response.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
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
    app.register_blueprint(company_blueprint)
    app.register_blueprint(conversation_blueprint)
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
    app.register_blueprint(chip_bp)
    app.register_blueprint(broadcast_blueprint)
    app.register_blueprint(admin_billing_bp)
    app.register_blueprint(platform_admin_bp)
    app.register_blueprint(support_bp)
    app.register_blueprint(help_bp)
    app.register_blueprint(widget_blueprint)
    app.register_blueprint(flow_blueprint)
    app.register_blueprint(automation_blueprint)
    if app.config.get("ENABLE_DEV_BILLING_ROUTES"):
        app.register_blueprint(dev_billing_bp)


    # Serve frontend files as fallback for unmatched GET routes
    FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
    
    # Serve media uploads. MEDIA_FOLDER lives on the mounted disk so uploads
    # survive a deploy; files predating that move are still in the image, so a
    # miss falls back to the legacy directory rather than 404ing a live bot.
    os.makedirs(MEDIA_FOLDER, exist_ok=True)

    # Rate-limited because this route is anonymous by design (messaging
    # providers fetch attachments without a session) and, since documents
    # moved to R2, a miss is no longer a local stat -- it is a blocking
    # GetObject with a retry budget measured in tens of seconds. On
    # --workers 1 --threads 8 a handful of concurrent misses can hold every
    # thread, taking the webhooks, the Wasender retry loop and the billing
    # scheduler down with it. Generous by default so a real provider burst
    # is never dropped.
    @app.route('/media/<path:filename>')
    @limiter.limit(lambda: current_app.config.get("RATELIMIT_MEDIA", "240/minute"))
    def serve_media(filename):
        from flask import abort, send_from_directory
        from werkzeug.exceptions import NotFound
        from werkzeug.security import safe_join
        from app.services.document_storage_service import (
            DocumentStorageError, materialize_file, r2_enabled,
        )
        try:
            remote_storage = r2_enabled()
            if remote_storage:
                path = safe_join(MEDIA_FOLDER, filename)
                if path is None:
                    abort(404)
                materialize_file(path, root=MEDIA_FOLDER, namespace="media")
        except FileNotFoundError:
            abort(404)
        except DocumentStorageError:
            return {"status": "error", "message": "Media storage is temporarily unavailable."}, 503
        try:
            response = send_from_directory(MEDIA_FOLDER, filename)
        except NotFound:
            if remote_storage:
                raise
            response = send_from_directory(LEGACY_MEDIA_FOLDER, filename)

        # Uploads are untrusted on the app's origin, including legacy files.
        # Providers still need anonymous downloads; only passive media is inline.
        inline_media = response.mimetype in {
            "image/jpeg", "image/png", "image/gif", "image/webp", "image/avif",
            "image/bmp", "image/x-icon", "image/vnd.microsoft.icon",
        } or response.mimetype.startswith(("audio/", "video/"))
        # Native audio/video documents fetch their source with CORS enabled.
        response.headers["Content-Security-Policy"] = (
            "sandbox allow-same-origin" if inline_media else "sandbox; default-src 'none'"
        )
        if not inline_media:
            response.headers["Content-Disposition"] = response.headers[
                "Content-Disposition"
            ].replace("inline;", "attachment;", 1)
        return response

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
