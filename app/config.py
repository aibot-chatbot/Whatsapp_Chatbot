import sys
import os
from dotenv import load_dotenv
import logging


def _is_production():
    """Heuristic: treat as production when FLASK_DEBUG is not set to a truthy value."""
    val = os.getenv("FLASK_DEBUG", "0").strip().lower()
    return val not in ("1", "true", "yes", "on")


def load_configurations(app):
    load_dotenv()

    # ── CORS ───────────────────────────────────────────────────────────
    cors_raw = os.getenv("CORS_ORIGINS", "").strip()
    if cors_raw:
        origins = [o.strip() for o in cors_raw.split(",") if o.strip()]
        for origin in origins:
            if "*" in origin and origin != "*":
                continue  # allow explicit wildcard-only for dev
        if "*" in origins and _is_production():
            raise RuntimeError(
                "CORS_ORIGINS contains wildcard '*' which is not allowed in production. "
                "Set explicit allowed origins."
            )
        app.config["CORS_ORIGINS"] = origins
    else:
        if _is_production():
            raise RuntimeError(
                "CORS_ORIGINS is not configured. Set it to a comma-separated list "
                "of allowed origins for production."
            )
        app.config["CORS_ORIGINS"] = [
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]

    # ── Frontend URL (for invite links etc.) ───────────────────────────
    frontend_url = os.getenv("FRONTEND_URL", "").strip()
    if not frontend_url:
        if _is_production():
            raise RuntimeError(
                "FRONTEND_URL is not configured. Set it to the production frontend base URL."
            )
        frontend_url = "http://localhost:3000"
    app.config["FRONTEND_URL"] = frontend_url.rstrip("/")

    # ── Dev billing routes ─────────────────────────────────────────────
    enable_dev = os.getenv("ENABLE_DEV_BILLING_ROUTES", "").strip().lower()
    if enable_dev and _is_production():
        raise RuntimeError(
            "ENABLE_DEV_BILLING_ROUTES is set but this is not allowed in production."
        )
    app.config["ENABLE_DEV_BILLING_ROUTES"] = enable_dev in ("1", "true", "yes", "on")

    # ── Rate limiting ──────────────────────────────────────────────────
    app.config["RATELIMIT_ENABLED"] = os.getenv(
        "RATELIMIT_ENABLED", "true" if _is_production() else "false"
    ).strip().lower() in ("1", "true", "yes", "on")

    app.config["RATELIMIT_STORAGE_URI"] = os.getenv(
        "RATELIMIT_STORAGE_URI", "memory://"
    )

    # Rate-limit defaults (can be overridden per endpoint)
    app.config.setdefault("RATELIMIT_LOGIN", os.getenv("RATELIMIT_LOGIN", "10/minute"))
    app.config.setdefault("RATELIMIT_OTP", os.getenv("RATELIMIT_OTP", "5/hour"))
    app.config.setdefault("RATELIMIT_CHECKOUT", os.getenv("RATELIMIT_CHECKOUT", "5/minute"))
    app.config.setdefault("RATELIMIT_RETRY", os.getenv("RATELIMIT_RETRY", "5/minute"))
    app.config.setdefault("RATELIMIT_RECEIPT", os.getenv("RATELIMIT_RECEIPT", "30/minute"))
    app.config.setdefault("RATELIMIT_EXPORT", os.getenv("RATELIMIT_EXPORT", "20/minute"))

    # ── Legacy config values ───────────────────────────────────────────
    app.config["ACCESS_TOKEN"] = os.getenv("ACCESS_TOKEN")
    app.config["YOUR_PHONE_NUMBER"] = os.getenv("YOUR_PHONE_NUMBER")
    app.config["APP_ID"] = os.getenv("APP_ID")
    app.config["APP_SECRET"] = os.getenv("APP_SECRET")
    app.config["RECIPIENT_WAID"] = os.getenv("RECIPIENT_WAID")
    app.config["VERSION"] = os.getenv("VERSION")
    app.config["PHONE_NUMBER_ID"] = os.getenv("PHONE_NUMBER_ID")
    app.config["VERIFY_TOKEN"] = os.getenv("VERIFY_TOKEN")

    # ── Production secret validation (fail-fast) ──
    if _is_production():
        jwt_secret = os.getenv("JWT_SECRET", "").strip()
        weak_secrets = {"", "your-secret-key", "change-me", "dev-secret",
                       "secret", "test", "default"}
        if not jwt_secret or jwt_secret.lower() in weak_secrets:
            raise RuntimeError(
                "JWT_SECRET is unset or uses a weak/default value. "
                "Generate a strong random secret for production."
            )

        flask_secret = os.getenv("SECRET_KEY", "").strip()
        if not flask_secret or flask_secret.lower() in weak_secrets:
            raise RuntimeError(
                "SECRET_KEY is unset or uses a weak/default value. "
                "Session security depends on a strong secret."
            )


def configure_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
        force=True,
    )
