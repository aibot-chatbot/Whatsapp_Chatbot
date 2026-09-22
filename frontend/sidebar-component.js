class ChatbotSidebar extends HTMLElement {
    constructor() {
        super();
    }

    connectedCallback() {
        const currentPath = window.location.pathname.split('/').pop() || 'index.html';
        const urlParams = new URLSearchParams(window.location.search);
        const rawBotId = urlParams.get("bot_id");
        const botId = (rawBotId && rawBotId !== "null") ? rawBotId : (sessionStorage.getItem("selectedBotId") || null);
        const botParams = new URLSearchParams();
        if (botId) botParams.set('bot_id', botId);
        if (botId && urlParams.get('setup') === '1') botParams.set('setup', '1');
        const botQuery = botId ? `?${botParams}` : "";
        const isMobileViewport = window.matchMedia('(max-width: 768px)').matches;
        const isCollapsed = localStorage.getItem("sidebarCollapsed") === "true" && !isMobileViewport;
        const initialIcon = isMobileViewport ? "☰" : (isCollapsed ? "☰" : "«");

        const isBotsPage = currentPath === "bots.html";
        // Determine user role from sessionStorage
        var storedUser = null;
        try { storedUser = JSON.parse(sessionStorage.getItem("user") || "null"); } catch (_) { }
        var userRole = (storedUser && storedUser.role || "").toLowerCase();
        var isAdmin = userRole === "admin" || userRole === "owner";
        const existingAccountMenu = document.querySelector('chatbot-sidebar tenant-account-menu');
        const shouldRenderAccountMenu = !existingAccountMenu || this.contains(existingAccountMenu);

        this.innerHTML = `
        <style>
            .sidebar {
                width: 260px;
                background: var(--sidebar-bg, rgba(15, 23, 42, 0.85));
                backdrop-filter: blur(20px);
                -webkit-backdrop-filter: blur(20px);
                border-right: 1px solid var(--glass-border, rgba(255,255,255,0.1));
                height: 100vh;
                display: flex;
                flex-direction: column;
                padding: 24px 18px;
                position: sticky;
                top: 0;
                z-index: 100;
                font-family: "Geist", "Outfit", sans-serif;
                transition: width 0.28s ease, padding 0.28s ease;
                overflow-y: hidden;
                overflow-x: hidden;
            }
            .sidebar::-webkit-scrollbar {
                width: 4px;
            }
            .sidebar::-webkit-scrollbar-track {
                background: transparent;
            }
            .sidebar::-webkit-scrollbar-thumb {
                background: rgba(255, 255, 255, 0.15);
                border-radius: 4px;
            }
            .sidebar::-webkit-scrollbar-thumb:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            .sidebar, .sidebar * {
                font-family: "Geist", "Outfit", sans-serif;
                /* Owned here rather than inherited from each host page's
                   global reset: at <=768px the sidebar is width:100% with
                   horizontal padding, so content-box sizing pushes it wider
                   than the viewport and the whole page scrolls sideways. */
                box-sizing: border-box;
            }
            .sidebar-top {
                flex-shrink: 0;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 10px;
                margin-bottom: 24px;
            }
            .sidebar-context { flex-shrink: 0; padding: 12px; margin-bottom: 12px; border: 1px solid var(--control-border, #2b2f34); border-left: 3px solid var(--control-accent, #3e9c89); border-radius: 8px; }
            .sidebar-context-label { display: block; color: var(--control-text-secondary, #8a9096); font-size: 11px; margin-bottom: 5px; }
            .sidebar-context-name { display: block; color: var(--control-text, #f2f3f4); font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
            .sidebar.collapsed .sidebar-context { display: none; }
            .sidebar :focus-visible { outline: 2px solid var(--control-accent-hover, #4ab09b); outline-offset: 2px; }
            .logo {
                font-size: 1.6rem;
                font-weight: 700;
                display: flex;
                align-items: center;
                gap: 12px;
                background: linear-gradient(to right, #ffffff, #94a3b8);
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
                padding: 0 10px;
                min-width: 0;
                white-space: nowrap;
            }
            .sidebar-toggle {
                width: 38px;
                height: 38px;
                border-radius: 12px;
                border: 1px solid rgba(255,255,255,0.12);
                background: rgba(255,255,255,0.06);
                color: var(--text-main, #f8fafc);
                display: inline-flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                font-size: 1.05rem;
                font-weight: 700;
                transition: all 0.25s ease;
                flex-shrink: 0;
            }
            .sidebar-toggle:hover {
                background: rgba(255,255,255,0.1);
                border-color: rgba(255,255,255,0.2);
            }
            .nav-list {
                list-style: none;
                flex: 1 1 auto;
                min-height: 0;
                overflow-y: auto;
                overflow-x: hidden;
                margin: 0;
                padding: 0;
                display: flex;
                flex-direction: column;
                gap: 4px;
            }
            .nav-group-header {
                font-size: 0.68rem;
                font-weight: 700;
                color: var(--text-dim, #94a3b8);
                opacity: 0.55;
                text-transform: uppercase;
                letter-spacing: 0.8px;
                margin: 14px 0 4px 10px;
                white-space: nowrap;
                transition: opacity 0.28s ease, margin 0.28s ease, height 0.28s ease;
            }
            .nav-link {
                text-decoration: none;
                color: var(--text-dim, #94a3b8);
                padding: 9px 12px;
                border-radius: 14px;
                display: flex;
                align-items: center;
                gap: 10px;
                transition: color 0.3s cubic-bezier(0.4, 0, 0.2, 1),
                            background-color 0.3s cubic-bezier(0.4, 0, 0.2, 1),
                            border-color 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                font-weight: 500;
                font-size: 0.92rem;
                cursor: pointer;
                border: 1px solid transparent;
                white-space: nowrap;
            }
            .nav-link i, .nav-link svg {
                width: 18px;
                height: 18px;
                color: var(--text-dim, #94a3b8);
                transition: color 0.3s;
            }
            .nav-link:hover {
                background: rgba(255, 255, 255, 0.04);
                color: var(--text-main, #f8fafc);
                border-color: rgba(255, 255, 255, 0.05);
                transform: translateX(4px);
            }
            .nav-link:hover i, .nav-link:hover svg {
                color: var(--accent, #3e9c89);
            }
            .nav-link.active {
                background: rgba(62, 156, 137, .12);
                color: var(--primary-hover, #4ab09b);
                box-shadow: none;
                border-color: rgba(62, 156, 137, .28);
                transform: none;
            }
            .nav-link.active i, .nav-link.active svg {
                color: var(--primary-hover, #4ab09b);
            }
            .dropdown-toggle {
                width: 100%;
                justify-content: space-between;
                background: transparent;
                border: none;
                font-family: inherit;
                list-style: none;
            }
            .dropdown-toggle::-webkit-details-marker { display: none; }
            .dropdown-content {
                max-height: 0;
                overflow: hidden;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                flex-direction: column;
                gap: 4px;
                padding-left: 8px;
            }
            .dropdown-container[open] .dropdown-content {
                max-height: 500px;
                margin-top: 4px;
                padding-bottom: 6px;
            }
            .dropdown-container .chevron {
                transition: transform 0.3s ease;
                width: 16px;
                height: 16px;
            }
            .dropdown-container[open] .chevron {
                transform: rotate(180deg);
                color: var(--text-main, #f8fafc);
            }
            .sub-link {
                font-size: 0.86rem;
                padding: 8px 12px;
                gap: 10px;
            }
            .sub-link i, .sub-link svg {
                width: 16px;
                height: 16px;
            }

            /* ===== Bottom section: tenant navigation plus account actions ===== */
            .sidebar-bottom-section {
                flex-shrink: 0;
                margin-top: auto;
                display: flex;
                flex-direction: column;
                gap: 2px;
                padding-top: 6px;
                border-top: 1px solid rgba(255, 255, 255, 0.04);
                position: sticky;
                bottom: 0;
                background: var(--sidebar-bg, rgba(15, 23, 42, 0.96));
                z-index: 2;
            }

            .profile-link {
                text-decoration: none;
                color: var(--text-dim, #94a3b8);
                padding: 8px 12px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                gap: 10px;
                transition: all 0.25s ease;
                font-weight: 500;
                font-size: 0.92rem;
                white-space: nowrap;
                cursor: pointer;
            }
            .profile-link i, .profile-link svg {
                width: 18px;
                height: 18px;
                color: var(--text-dim, #94a3b8);
                flex-shrink: 0;
                transition: color 0.25s;
            }
            .profile-link:hover {
                color: var(--text-main, #f8fafc);
                background: rgba(255, 255, 255, 0.04);
            }
            .profile-link:hover i, .profile-link:hover svg {
                color: var(--primary, #3b82f6);
            }
            .profile-link.active {
                background: linear-gradient(135deg, var(--primary, #3b82f6), #2563eb);
                color: white;
                box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4);
            }
            .profile-link.active i, .profile-link.active svg {
                color: white;
            }

            .profile-link-content {
                display: flex;
                align-items: center;
                gap: 10px;
            }

            .logout-link {
                text-decoration: none;
                color: #ef4444;
                padding: 8px 12px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                gap: 10px;
                transition: all 0.25s ease;
                font-weight: 600;
                font-size: 0.92rem;
                white-space: nowrap;
            }
            .logout-link i, .logout-link svg {
                width: 18px;
                height: 18px;
                color: #ef4444;
                flex-shrink: 0;
            }
            .logout-link:hover {
                background: rgba(239, 68, 68, 0.08);
                color: #f87171;
            }
            .logout-link:hover i, .logout-link:hover svg {
                color: #f87171;
            }

            .sidebar.collapsed .sidebar-bottom-section {
                align-items: center;
            }
            .sidebar-account {
                width: 100%;
                margin-top: 2px;
            }
            .sidebar-account tenant-account-menu {
                display: block;
                width: 100%;
            }
            .sidebar.collapsed .sidebar-account {
                width: 44px;
            }
            .sidebar.collapsed .profile-link {
                justify-content: center;
                padding: 10px 12px;
            }
            .sidebar.collapsed .profile-link span,
            .sidebar.collapsed .logout-link span {
                display: none;
            }

            .nav-link-content {
                display: flex;
                align-items: center;
                gap: 14px;
            }
            .sidebar.collapsed .nav-group-header {
                opacity: 0;
                margin: 12px 0 6px;
                height: 1px;
                background: rgba(255, 255, 255, 0.05);
                overflow: hidden;
            }
            .sidebar.collapsed {
                width: 80px;
                padding: 32px 12px;
            }
            .sidebar.collapsed .sidebar-top {
                justify-content: center;
                margin-bottom: 34px;
            }
            .sidebar.collapsed .logo {
                display: none;
            }
            .sidebar.collapsed .sidebar-toggle {
                width: 44px;
                height: 44px;
            }
            .sidebar.collapsed .nav-link,
            .sidebar.collapsed .logout-link {
                justify-content: center;
                padding: 12px;
                gap: 0;
            }
            .sidebar.collapsed .nav-link span,
            .sidebar.collapsed .logout-link span {
                display: none;
            }
            .sidebar.collapsed .nav-link-content {
                gap: 0;
                justify-content: center;
            }
            .sidebar.collapsed .dropdown-content {
                display: none;
            }
            .sidebar.collapsed .chevron {
                display: none;
            }
            .sidebar.collapsed .dropdown-container.open .dropdown-content {
                display: none;
            }
            .sidebar.collapsed .nav-link:hover,
            .sidebar.collapsed .profile-link:hover,
            .sidebar.collapsed .logout-link:hover {
                transform: none;
            }
            .sidebar.collapsed .profile-link-content {
                gap: 0;
                justify-content: center;
            }
            @media (max-width: 768px) {
                .sidebar,
                .sidebar.collapsed {
                    width: 100%;
                    height: auto;
                    min-height: auto;
                    position: sticky;
                    top: 0;
                    z-index: 1000;
                    padding: 16px 20px;
                }

                .sidebar .sidebar-top {
                    margin-bottom: 0;
                }

                .sidebar.mobile-open .sidebar-top {
                    margin-bottom: 24px;
                }

                /* Hide menu contents by default on small viewports */
                .sidebar .sidebar-context,
                .sidebar .nav-list,
                .sidebar .sidebar-bottom-section {
                    display: none !important;
                }

                /* Show when mobile-open is active */
                .sidebar.mobile-open .sidebar-context,
                .sidebar.mobile-open .nav-list,
                .sidebar.mobile-open .sidebar-bottom-section {
                    display: flex !important;
                }

                .sidebar.mobile-open .sidebar-bottom-section {
                    position: relative;
                    bottom: 0;
                    width: auto;
                    background: var(--sidebar-bg, rgba(15, 23, 42, 0.98));
                    border-radius: 14px;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    padding: 6px;
                    z-index: 1002;
                }

                .sidebar.mobile-open {
                    height: 100dvh;
                    overflow-y: hidden;
                    position: fixed;
                    left: 0;
                    right: 0;
                }
                .sidebar.mobile-open .sidebar-context { display: block !important; }
            }
        </style>
        <aside class="sidebar ${isCollapsed ? "collapsed" : ""}" aria-label="${botId ? 'Selected bot navigation' : 'Workspace navigation'}">
            <div class="sidebar-top">
                <div class="logo">
                    <i data-lucide="bot" style="color: var(--accent, #3e9c89); width: 28px; height: 28px;"></i>
                    <span>${botId ? 'This bot' : 'Omnexa'}</span>
                </div>
                <button class="sidebar-toggle" type="button" aria-controls="bot-sidebar-navigation" aria-label="${isCollapsed ? "Expand sidebar" : "Collapse sidebar"}" title="${isCollapsed ? "Expand sidebar" : "Collapse sidebar"}">
                    <span class="sidebar-toggle-icon">${initialIcon}</span>
                </button>
            </div>

            ${!isBotsPage && botId ? '<div class="sidebar-context"><span class="sidebar-context-label">Selected bot</span><span class="sidebar-context-name"></span></div>' : ''}
            <nav class="nav-list" id="bot-sidebar-navigation" aria-label="${botId ? 'This bot' : 'Workspace'}">
                <a href="bots.html" class="nav-link" title="Back to My bots">
                    <i data-lucide="arrow-left" aria-hidden="true"></i>
                    <span>My bots</span>
                </a>

                ${!isBotsPage && botId ? `
                    <a href="index.html${botQuery}" class="nav-link" title="Bot overview">
                        <i data-lucide="layout-dashboard"></i>
                        <span>Overview</span>
                    </a>

                    ${isAdmin ? `
                        <div class="nav-group-header">Set up your bot</div>
                        <a href="new_linkdocs.html${botQuery}" class="nav-link" title="Add knowledge">
                            <i data-lucide="file-text"></i><span>Add knowledge</span>
                        </a>
                        <a href="new_prompt.html${botQuery}" class="nav-link" title="Bot instructions">
                            <i data-lucide="notebook-pen"></i><span>Bot instructions</span>
                        </a>
                        <a href="testbot.html${botQuery}" class="nav-link" title="Test replies">
                            <i data-lucide="flask-conical"></i><span>Test replies</span>
                        </a>
                        <a href="integration.html${botQuery}" class="nav-link" title="Publish">
                            <i data-lucide="plug"></i>
                            <span>Publish</span>
                        </a>
                    ` : ""}

                    <div class="nav-group-header">Customer activity</div>
                    <a href="conversations.html${botQuery}" class="nav-link" title="Inbox & Conversations">
                        <i data-lucide="message-square"></i>
                        <span>Conversations</span>
                    </a>
                    ${isAdmin ? `
                        <a href="analysis.html${botQuery}" class="nav-link" title="Analysis and reports">
                            <i data-lucide="chart-no-axes-combined"></i><span>Analysis</span>
                        </a>
                    ` : ''}

                    <details class="dropdown-container" id="bot-tools-dropdown">
                        <summary class="nav-link dropdown-toggle" title="More tools">
                            <div class="nav-link-content">
                                <i data-lucide="settings"></i>
                                <span>More tools</span>
                            </div>
                            <i data-lucide="chevron-down" class="chevron"></i>
                        </summary>
                        <div class="dropdown-content">
                            ${isAdmin ? `
                                <a href="behaviour.html?tab=model${botQuery ? "&" + botQuery.slice(1) : ""}" class="nav-link sub-link" title="AI settings">
                                    <i data-lucide="sliders-horizontal"></i><span>AI settings</span>
                                </a>
                                <a href="behaviour.html?tab=message${botQuery ? "&" + botQuery.slice(1) : ""}" class="nav-link sub-link" title="Message style">
                                    <i data-lucide="message-circle"></i><span>Message style</span>
                                </a>
                            ` : ''}
                            <a href="broadcast.html${botQuery}" class="nav-link sub-link" title="Campaigns">
                                <i data-lucide="send"></i><span>Campaigns</span>
                            </a>
                            ${isAdmin ? `
                                <a href="meta_templates.html${botQuery}" class="nav-link sub-link" title="Message templates">
                                    <i data-lucide="file-check"></i><span>Message templates</span>
                                </a>
                            ` : ''}
                            <a href="crm.html${botQuery}" class="nav-link sub-link" title="Today and leads">
                                <i data-lucide="users"></i>
                                <span>Today &amp; leads</span>
                            </a>
                            <a href="reports.html${botQuery}" class="nav-link sub-link" title="Performance">
                                <i data-lucide="bar-chart-3"></i>
                                <span>Performance</span>
                            </a>
                        </div>
                    </details>
                ` : ""}
            </nav>

            <!-- Bottom section: tenant navigation plus account actions. -->
            <div class="sidebar-bottom-section">
                ${isAdmin ? `
                <a href="team.html${botQuery}" class="profile-link" title="Team Members">
                    <div class="profile-link-content">
                        <i data-lucide="users"></i>
                        <span>Team Members</span>
                    </div>
                </a>
                ` : ""}
                <a href="billing.html${botQuery}" class="profile-link" title="Billing & Credits">
                    <div class="profile-link-content">
                        <i data-lucide="credit-card"></i>
                        <span>Billing</span>
                    </div>
                </a>
                <a href="pricing.html${botQuery}" class="profile-link" title="Plans & Usage">
                    <div class="profile-link-content">
                        <i data-lucide="layers"></i>
                        <span>Plans</span>
                    </div>
                </a>
                ${shouldRenderAccountMenu ? `
                <div class="sidebar-account">
                    <tenant-account-menu placement="sidebar" preserve-bot-query></tenant-account-menu>
                </div>
                ` : ""}
            </div>

        </aside>


        `;

        this.setBotName(botId ? `Bot #${botId}` : '');
        this.querySelectorAll('[data-lucide]').forEach(icon => icon.setAttribute('aria-hidden', 'true'));
        this.initSidebar();
        this.initCollapseToggle();

        const refreshAccountMenuIcons = () => {
            const accountMenu = this.querySelector('tenant-account-menu');
            if (accountMenu && typeof accountMenu.refreshMenuIcons === 'function') {
                accountMenu.refreshMenuIcons();
            }
        };

        // Check if lucide is available globally
        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons({ root: this });
            refreshAccountMenuIcons();
        } else {
            // Load it dynamically if missing
            const script = document.createElement('script');
            script.src = 'https://unpkg.com/lucide@1.31.0';
            script.onload = () => {
                window.lucide.createIcons({ root: this });
                refreshAccountMenuIcons();
            };
            document.head.appendChild(script);
        }
    }

    setBotName(name) {
        const label = this.querySelector('.sidebar-context-name');
        if (label && name) label.textContent = name;
    }

    initSidebar() {
        const currentPath = window.location.pathname.split("/").pop() || "index.html";
        const navLinks = this.querySelectorAll(".nav-link");
        var profileLinks = this.querySelectorAll(".profile-link");

        // Mark profile/team links active based on current page
        profileLinks.forEach(function (pl) {
            var h = pl.getAttribute("href");
            if (h) {
                var p = h.split("?")[0];
                if (p === currentPath) {
                    pl.classList.add("active");
                    pl.setAttribute('aria-current', 'page');
                }
            }
        });

        navLinks.forEach(link => {
            // Check if the href matches the exact path (removing queries)
            const href = link.getAttribute("href");
            if (href) {
                const linkPath = href.split("?")[0];
                var linkTab = new URLSearchParams((link.getAttribute("href") || "").split("?")[1] || "").get("tab");
                var pageTab = new URLSearchParams(window.location.search).get("tab") || "model";
                var tabMatches = !linkTab || linkTab === pageTab;
                const legacyTest = currentPath === 'behaviour.html' && pageTab === 'test' && linkPath === 'testbot.html';
                const legacySettings = (currentPath === 'model_settings.html' && linkTab === 'model')
                    || (currentPath === 'message_style.html' && linkTab === 'message');
                if ((linkPath === currentPath && tabMatches) || legacyTest || legacySettings) {
                    link.classList.add("active");
                    link.setAttribute('aria-current', 'page');
                }
            }
        });

        this.querySelectorAll('details.dropdown-container').forEach(group => {
            const summary = group.querySelector('summary');
            group.open = Boolean(group.querySelector('a.active'));
            const sync = () => summary.setAttribute('aria-expanded', String(group.open));
            group.addEventListener('toggle', sync);
            sync();
        });

    }

    initCollapseToggle() {
        const sidebar = this.querySelector('.sidebar');
        const toggle = this.querySelector('.sidebar-toggle');
        const icon = this.querySelector('.sidebar-toggle-icon');

        if (!sidebar || !toggle || !icon) {
            return;
        }

        const syncToggleState = () => {
            const isMobileViewport = window.matchMedia('(max-width: 768px)').matches;
            const accountMenu = this.querySelector('tenant-account-menu');

            if (isMobileViewport) {
                sidebar.classList.remove('collapsed');
                if (accountMenu) accountMenu.removeAttribute('compact');
                const isOpen = sidebar.classList.contains('mobile-open');
                icon.textContent = isOpen ? '✕' : '☰';
                toggle.setAttribute('aria-label', isOpen ? 'Close menu' : 'Open menu');
                toggle.setAttribute('title', isOpen ? 'Close menu' : 'Open menu');
                toggle.setAttribute('aria-expanded', String(isOpen));
            } else {
                sidebar.classList.remove('mobile-open');
                const shouldBeCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
                sidebar.classList.toggle('collapsed', shouldBeCollapsed);
                if (accountMenu) accountMenu.toggleAttribute('compact', shouldBeCollapsed);
                icon.textContent = shouldBeCollapsed ? '☰' : '«';
                toggle.setAttribute('aria-label', shouldBeCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
                toggle.setAttribute('title', shouldBeCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
                toggle.setAttribute('aria-expanded', String(!shouldBeCollapsed));
            }
        };

        toggle.addEventListener('click', () => {
            const isMobileViewport = window.matchMedia('(max-width: 768px)').matches;

            if (isMobileViewport) {
                const isOpen = sidebar.classList.contains('mobile-open');
                sidebar.classList.toggle('mobile-open', !isOpen);
                syncToggleState();
                return;
            }

            const shouldCollapse = !sidebar.classList.contains('collapsed');
            sidebar.classList.toggle('collapsed', shouldCollapse);
            localStorage.setItem('sidebarCollapsed', String(shouldCollapse));
            syncToggleState();
        });

        this.querySelectorAll('summary.dropdown-toggle').forEach(summary => {
            summary.addEventListener('click', () => {
                if (sidebar.classList.contains('collapsed')) {
                    localStorage.setItem('sidebarCollapsed', 'false');
                    syncToggleState();
                }
            });
        });

        window.addEventListener('resize', syncToggleState);
        syncToggleState();
    }
}

customElements.define('chatbot-sidebar', ChatbotSidebar);

window.toggleSidebarDropdown = window.toggleSidebarDropdown || function (id) {
    // We must find the dropdown inside the chatbot-sidebar shadow DOM or element
    const sb = document.querySelector('chatbot-sidebar');
    if (sb) {
        const insideEl = sb.querySelector('#' + id);
        if (insideEl instanceof HTMLDetailsElement) insideEl.open = !insideEl.open;
    }
};
