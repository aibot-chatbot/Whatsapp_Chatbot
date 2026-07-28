"""Source-contract tests for the shared authenticated tenant account menu."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SHARED_UI = FRONTEND / "assets" / "js" / "shared-ui.js"
SIDEBAR = FRONTEND / "sidebar-component.js"
BOTS = FRONTEND / "bots.html"
PLATFORM_SHELL = FRONTEND / "assets" / "js" / "platform-admin-shell.js"
AUTHENTICATED_SIDEBAR_PAGES = [
    "index.html",
    "crm.html",
    "flows.html",
    "media_attachments.html",
    "meta_templates.html",
    "integration.html",
    "model_settings.html",
    "new_linkdocs.html",
    "broadcast.html",
    "conversations.html",
    "pricing.html",
    "profile.html",
    "reports.html",
    "team.html",
    "testbot.html",
    "new_prompt.html",
]


def read(path):
    return path.read_text(encoding="utf-8", errors="replace")


def test_shared_account_menu_component_exists_and_is_used_by_bots_page():
    shared = read(SHARED_UI)
    bots = read(BOTS)

    assert 'customElements.define("tenant-account-menu"' in shared
    assert "<tenant-account-menu></tenant-account-menu>" in bots
    assert "toggleUserDropdown" not in bots
    assert "userDropdown" not in bots


def test_support_destination_is_not_rendered_until_implemented():
    shared = read(SHARED_UI)
    bots = read(BOTS)

    assert not (FRONTEND / "support.html").exists()
    assert "support.html" not in shared
    assert "Support" not in bots
    assert "userDropdown" not in bots


def test_sidebar_no_longer_renders_profile_logout_or_platform_link():
    sidebar = read(SIDEBAR)

    assert 'href="profile.html${botQuery}"' not in sidebar
    assert 'href="login.html?logout=1"' not in sidebar
    assert "Platform Administration" not in sidebar
    assert "platform-admin.html" not in sidebar
    assert 'href="team.html${botQuery}"' in sidebar
    assert 'href="pricing.html${botQuery}"' in sidebar


def test_sidebar_pages_auto_mount_account_menu_outside_sidebar():
    shared = read(SHARED_UI)

    assert 'document.querySelector("chatbot-sidebar")' in shared
    assert 'document.querySelector("tenant-account-menu")' in shared
    assert "tenant-account-menu-floating" in shared
    assert 'document.body.appendChild(host)' in shared
    assert 'menu.setAttribute("preserve-bot-query", "")' in shared


def test_all_authenticated_sidebar_pages_load_shared_menu_dependencies():
    for page_name in AUTHENTICATED_SIDEBAR_PAGES:
        page = read(FRONTEND / page_name)
        with_subtest = f"{page_name} should load shared-ui.js, auth.js, and sidebar"
        assert 'assets/js/shared-ui.js' in page, with_subtest
        assert 'assets/js/auth.js' in page, with_subtest
        assert (
            "<chatbot-sidebar" in page
            or 'React.createElement("chatbot-sidebar"' in page
            or "React.createElement('chatbot-sidebar'" in page
        ), with_subtest


def test_platform_admin_option_requires_live_backend_check_only_on_open():
    shared = read(SHARED_UI)

    assert 'fetch("/api/platform-admin/me"' in shared
    assert 'method: "GET"' in shared
    assert 'headers: { "Authorization": "Bearer " + token }' in shared
    assert "openMenu()" in shared
    assert 'this.checkPlatformAccess();' in shared
    assert "sessionStorage.setItem" not in shared[shared.index("checkPlatformAccess"):]
    assert "localStorage.setItem" not in shared[shared.index("checkPlatformAccess"):]
    assert "role" not in shared[shared.index("checkPlatformAccess"):shared.index("window.customElements.define")]


def test_logout_uses_existing_auth_module_without_duplicate_token_clearing():
    shared = read(SHARED_UI)
    logout_handler = shared[shared.index('logoutButton.addEventListener("click"'):shared.index("menu.append")]

    assert "window.logout();" in logout_handler
    assert "sessionStorage.removeItem" not in logout_handler
    assert "localStorage.removeItem" not in logout_handler
    assert "login.html" not in logout_handler


def test_menu_supports_keyboard_outside_click_abort_and_safe_rendering():
    shared = read(SHARED_UI)

    assert 'event.key !== "Escape"' in shared
    assert "handleDocumentClick" in shared
    assert "pagehide" in shared
    assert "AbortController" in shared
    assert ".textContent = displayName" in shared
    assert ".textContent = email" in shared
    assert ".innerHTML =" not in shared[shared.index("var identityName"):shared.index("var profile")]


def test_platform_admin_area_keeps_single_return_to_tenant_app_control():
    shell = read(PLATFORM_SHELL)

    assert 'tenantLink.href = "bots.html"' in shell
    assert "Return to Tenant App" in shell
