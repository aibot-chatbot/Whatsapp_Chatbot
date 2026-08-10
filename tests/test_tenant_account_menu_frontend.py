"""Source-contract tests for the shared authenticated tenant account menu."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SHARED_UI = FRONTEND / "assets" / "js" / "shared-ui.js"
SIDEBAR = FRONTEND / "sidebar-component.js"
BOTS = FRONTEND / "bots.html"
SUPPORT = FRONTEND / "support.html"
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
    "support.html",
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


def test_support_destination_exists_and_is_rendered_in_shared_menu():
    shared = read(SHARED_UI)
    bots = read(BOTS)

    assert SUPPORT.exists()
    assert 'this.linkItem("support.html", "Support"' in shared
    assert 'this.linkItem("profile.html" + this.profileQuery(), "Profile"' in shared
    assert "userDropdown" not in bots


def test_sidebar_no_longer_renders_profile_logout_or_platform_link():
    sidebar = read(SIDEBAR)

    assert 'href="profile.html${botQuery}"' not in sidebar
    assert 'href="login.html?logout=1"' not in sidebar
    assert "Platform Administration" not in sidebar
    assert "platform-admin.html" not in sidebar
    assert "support.html" not in sidebar
    assert "Support" not in sidebar
    assert 'href="team.html${botQuery}"' in sidebar
    assert 'href="pricing.html${botQuery}"' in sidebar


def test_sidebar_pages_auto_mount_account_menu_outside_sidebar():
    shared = read(SHARED_UI)

    assert 'document.querySelector("chatbot-sidebar")' in shared
    assert 'document.querySelector("tenant-account-menu")' in shared
    assert "tenant-account-menu-floating" in shared
    assert 'document.body.appendChild(host)' in shared
    assert 'menu.setAttribute("preserve-bot-query", "")' in shared
    assert "MutationObserver" in shared
    assert "watchForSidebarAccountMenuMount" in shared
    assert "stopTenantAccountMenuObserver" in shared


def test_floating_account_menu_layers_above_mobile_sidebar_toggle():
    shared = read(SHARED_UI)
    sidebar = read(SIDEBAR)

    assert ".tenant-account-menu-floating{position:fixed;top:24px;right:32px;z-index:1001;width:max-content;" in shared
    assert "z-index: 1000;" in sidebar


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


def test_support_menu_item_is_static_and_role_independent():
    shared = read(SHARED_UI)
    render_section = shared[shared.index("var profile ="):shared.index("var logoutButton")]

    assert 'this.linkItem("support.html", "Support", "circle-help")' in render_section
    assert "role" not in render_section
    assert "userRole" not in render_section
    assert "isAdmin" not in render_section
    assert "profileQuery()" not in render_section[render_section.index("var support"):]


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


def test_support_page_is_authenticated_static_and_uses_safe_account_rendering():
    page = read(SUPPORT)

    assert 'assets/css/shared-glass.css' in page
    assert 'assets/js/shared-ui.js' in page
    assert 'assets/js/auth.js' in page
    assert 'sidebar-component.js' in page
    assert "requireLogin();" in page
    assert "<chatbot-sidebar></chatbot-sidebar>" in page
    assert 'id="support-request-form"' in page
    assert 'id="support-history-list"' in page
    assert 'id="support-history-detail"' in page
    assert 'authenticatedFetch("/api/support/requests?limit=25&offset=0"' in page
    assert 'authenticatedFetch("/api/support/requests/" + String(requestId)' in page
    assert "XMLHttpRequest" not in page
    assert "mailto:" not in page.lower()
    assert "tel:" not in page.lower()
    assert "support@" not in page.lower()
    assert "http://" not in page.lower()
    assert "<script src=\"https://" not in page.lower()
    assert "console." not in page
    assert ".innerHTML" not in page
    assert ".textContent = displayName" in page
    assert ".textContent = email" in page
    assert "user_id" not in page
    assert "company_id" not in page
    assert "jwt" not in page.lower()
    assert "platform-admin" not in page
    assert "Tenant-visible replies" in page
    assert "internal notes are not exposed" in page


def test_support_quick_links_point_only_to_existing_local_frontend_files():
    page = read(SUPPORT)
    links = re.findall(r'<a class="quick-link" href="([^"]+)" data-support-link>', page)

    assert links
    assert len(links) == len(set(links))
    for href in links:
        assert re.fullmatch(r"[a-z_]+\.html", href), href
        assert (FRONTEND / href).exists(), href


def test_platform_admin_area_keeps_single_return_to_tenant_app_control():
    shell = read(PLATFORM_SHELL)

    assert 'tenantLink.href = "bots.html"' in shell
    assert "Return to Tenant App" in shell
