"""Regression checks for removal of the tenant System Guide widget."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch


os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("SECRET_KEY", "test-secret-key")


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP = ROOT / "app"
# Astro sources only: web/node_modules and web/dist sit outside these folders.
WEB_SRC = ROOT / "web" / "src"
WEB_PUBLIC = ROOT / "web" / "public"


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def test_system_guide_frontend_assets_are_removed():
    # web/public/assets is served at the same /assets/ URLs, so it must stay free of them too.
    for assets in (FRONTEND / "assets", WEB_PUBLIC / "assets"):
        assert not (assets / "js" / "guide-bot.js").exists()
        assert not (assets / "css" / "guide-bot.css").exists()


def test_system_guide_backend_route_source_is_removed():
    assert not (APP / "routes" / "guide_router.py").exists()
    app_init = read(APP / "__init__.py")

    assert "guide_blueprint" not in app_init
    assert "guide_router" not in app_init


def test_no_live_system_guide_request_path_remains():
    live_files = [
        *APP.rglob("*.py"),
        *FRONTEND.rglob("*.html"),
        *FRONTEND.rglob("*.js"),
        *FRONTEND.rglob("*.css"),
        # Every source file under web/, whatever its type: pages, components, styles and public assets.
        *(path for web in (WEB_SRC, WEB_PUBLIC) for path in web.rglob("*") if path.is_file()),
    ]
    assert any(path.suffix == ".astro" for path in live_files), "migrated Astro pages must be scanned"
    ignored_segments = {
        "frontend_backup_before_ui_overhaul",
    }
    forbidden = [
        "/api/guide/chat",
        "/api/guide/status",
        "guide-bot-trigger",
        "guide-bot-window",
        "guide-bot-js",
        "guide-bot-css",
        "guidance_bot_history",
        "toggleGuidanceBot",
    ]

    offenders = []
    for path in live_files:
        rel = path.relative_to(ROOT)
        if any(segment in rel.parts for segment in ignored_segments):
            continue
        text = read(path)
        for marker in forbidden:
            if marker in text:
                offenders.append(f"{rel}: {marker}")

    assert offenders == []


def test_shared_sidebar_no_longer_injects_system_guide_widget():
    sidebar = read(FRONTEND / "sidebar-component.js")
    removed_markers = [
        "System Guidance Bot",
        "System Guide",
        "guide-bot-trigger",
        "guide-bot-window",
        "guide-bot-css",
        "guide-bot-js",
        "guide-bot.css",
        "guide-bot.js",
        "toggleGuidanceBot",
        "Ask for help...",
    ]

    for marker in removed_markers:
        assert marker not in sidebar


def test_removed_guide_endpoint_is_not_registered():
    with patch("app.database.db.supabase", MagicMock()):
        from app import create_app

        app = create_app()
        app.config["TESTING"] = True
        routes = {str(rule) for rule in app.url_map.iter_rules()}

    assert "/api/guide/chat" not in routes
    assert "/api/guide/status" not in routes
