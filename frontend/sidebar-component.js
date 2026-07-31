class ChatbotSidebar extends HTMLElement {
    constructor() {
        super();
    }

    connectedCallback() {
        const currentPath = window.location.pathname.split('/').pop() || 'index.html';
        const urlParams = new URLSearchParams(window.location.search);
        const rawBotId = urlParams.get("bot_id");
        const botId = (rawBotId && rawBotId !== "null") ? rawBotId : (sessionStorage.getItem("selectedBotId") || null);
        const botQuery = botId ? `?bot_id=${botId}` : "";
        const isMobileViewport = window.matchMedia('(max-width: 768px)').matches;
        const isCollapsed = localStorage.getItem("sidebarCollapsed") === "true" && !isMobileViewport;
        const initialIcon = isMobileViewport ? "☰" : (isCollapsed ? "☰" : "«");

        const isBotsPage = currentPath === "bots.html";
        // Determine user role from sessionStorage
        var storedUser = null;
        try { storedUser = JSON.parse(sessionStorage.getItem("user") || "null"); } catch (_) { }
        var userRole = (storedUser && storedUser.role || "").toLowerCase();
        var isAdmin = userRole === "admin" || userRole === "owner";

        this.innerHTML = `
        <style>
            .sidebar {
                width: 280px;
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
                font-family: 'Outfit', sans-serif;
                transition: width 0.28s ease, padding 0.28s ease;
                overflow-y: auto;
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
                font-family: 'Outfit', sans-serif;
            }
            .sidebar-top {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 10px;
                margin-bottom: 24px;
            }
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
                flex-grow: 1;
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
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
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
                color: var(--primary, #3b82f6);
            }
            .nav-link.active {
                background: linear-gradient(135deg, var(--primary, #3b82f6), #2563eb);
                color: white;
                box-shadow: 0 4px 20px rgba(59, 130, 246, 0.4);
                border-color: transparent;
                transform: none;
            }
            .nav-link.active i, .nav-link.active svg {
                color: white;
            }
            .dropdown-toggle {
                width: 100%;
                justify-content: space-between;
                background: transparent;
                border: none;
                font-family: inherit;
            }
            .dropdown-content {
                max-height: 0;
                overflow: hidden;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                display: flex;
                flex-direction: column;
                gap: 4px;
                padding-left: 8px;
            }
            .dropdown-container.open .dropdown-content {
                max-height: 500px;
                margin-top: 4px;
                padding-bottom: 6px;
            }
            .dropdown-container .chevron {
                transition: transform 0.3s ease;
                width: 16px;
                height: 16px;
            }
            .dropdown-container.open .chevron {
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

            /* ===== Bottom section: tenant navigation only ===== */
            .sidebar-bottom-section {
                margin-top: auto;
                display: flex;
                flex-direction: column;
                gap: 2px;
                padding-top: 6px;
                border-top: 1px solid rgba(255, 255, 255, 0.04);
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
                .sidebar .nav-list,
                .sidebar .sidebar-bottom-section {
                    display: none !important;
                }

                /* Show when mobile-open is active */
                .sidebar.mobile-open .nav-list,
                .sidebar.mobile-open .sidebar-bottom-section {
                    display: flex !important;
                }

                .sidebar.mobile-open {
                    height: 100vh;
                    overflow-y: auto;
                }
            }
        </style>
        <aside class="sidebar ${isCollapsed ? "collapsed" : ""}">
            <div class="sidebar-top">
                <div class="logo">
                    <i data-lucide="bot" style="color: var(--primary, #3b82f6); width: 28px; height: 28px;"></i>
                    <span>AI CHATBOT</span>
                </div>
                <button class="sidebar-toggle" type="button" aria-label="${isCollapsed ? "Expand sidebar" : "Collapse sidebar"}" title="${isCollapsed ? "Expand sidebar" : "Collapse sidebar"}">
                    <span class="sidebar-toggle-icon">${initialIcon}</span>
                </button>
            </div>

            <nav class="nav-list">
                <a href="bots.html" class="nav-link" title="My Bots">
                    <i data-lucide="home"></i>
                    <span>My Bots</span>
                </a>

                ${!isBotsPage && botId ? `
                    <div class="nav-group-header">General Overview</div>
                    <a href="index.html${botQuery}" class="nav-link" title="Dashboard">
                        <i data-lucide="layout-dashboard"></i>
                        <span>Dashboard</span>
                    </a>

                    ${isAdmin ? `
                        <div class="nav-group-header">Build &amp; Configuration</div>
                        <div class="dropdown-container" id="training-dropdown">
                            <button class="nav-link dropdown-toggle" onclick="window.toggleSidebarDropdown('training-dropdown')" title="Training Data">
                                <div class="nav-link-content">
                                    <i data-lucide="folder-open"></i>
                                    <span>Training Data</span>
                                </div>
                                <i data-lucide="chevron-down" class="chevron"></i>
                            </button>
                            <div class="dropdown-content">
                                <a href="new_linkdocs.html${botQuery}" class="nav-link sub-link" title="Documents">
                                    <i data-lucide="file-text"></i>
                                    <span>Documents</span>
                                </a>
                                <a href="new_prompt.html${botQuery}" class="nav-link sub-link" title="Bot Config">
                                    <i data-lucide="terminal-square"></i>
                                    <span>Bot Config</span>
                                </a>
                            </div>
                        </div>

                        <div class="dropdown-container" id="behaviour-dropdown">
                            <button class="nav-link dropdown-toggle" onclick="window.toggleSidebarDropdown('behaviour-dropdown')" title="Behaviour">
                                <div class="nav-link-content">
                                    <i data-lucide="settings"></i>
                                    <span>Behaviour</span>
                                </div>
                                <i data-lucide="chevron-down" class="chevron"></i>
                            </button>
                            <div class="dropdown-content">
                                <a href="model_settings.html${botQuery}" class="nav-link sub-link" title="Tune AI">
                                    <i data-lucide="sliders-horizontal"></i>
                                    <span>Tune AI</span>
                                </a>
                                <a href="testbot.html${botQuery}" class="nav-link sub-link" title="Test Bot">
                                    <i data-lucide="flask-conical"></i>
                                    <span>Test Bot</span>
                                </a>
                            </div>
                        </div>

                        <a href="flows.html${botQuery}" class="nav-link" title="Flow Builder">
                            <i data-lucide="workflow"></i>
                            <span>Flow Builder</span>
                        </a>

                        <a href="integration.html${botQuery}" class="nav-link" title="Integration">
                            <i data-lucide="plug"></i>
                            <span>Integration</span>
                        </a>
                    ` : ""}

                    <div class="nav-group-header">Operate &amp; CRM</div>
                    <a href="conversations.html${botQuery}" class="nav-link" title="Inbox & Conversations">
                        <i data-lucide="message-square"></i>
                        <span>Inbox &amp; Chat</span>
                    </a>

                    ${isAdmin ? `
                        <div class="dropdown-container" id="campaigns-dropdown">
                            <button class="nav-link dropdown-toggle" onclick="window.toggleSidebarDropdown('campaigns-dropdown')" title="Campaigns">
                                <div class="nav-link-content">
                                    <i data-lucide="send"></i>
                                    <span>Campaigns</span>
                                </div>
                                <i data-lucide="chevron-down" class="chevron"></i>
                            </button>
                            <div class="dropdown-content">
                                <a href="broadcast.html${botQuery}" class="nav-link sub-link" title="Broadcast / Campaigns">
                                    <i data-lucide="send"></i>
                                    <span>Broadcast</span>
                                </a>
                                <a href="meta_templates.html${botQuery}" class="nav-link sub-link" title="Meta Templates">
                                    <i data-lucide="file-check"></i>
                                    <span>Templates</span>
                                </a>
                            </div>
                        </div>
                    ` : `
                        <a href="broadcast.html${botQuery}" class="nav-link" title="Broadcast / Campaigns">
                            <i data-lucide="send"></i>
                            <span>Campaigns</span>
                        </a>
                    `}

                    <div class="dropdown-container" id="crm-analytics-dropdown">
                        <button class="nav-link dropdown-toggle" onclick="window.toggleSidebarDropdown('crm-analytics-dropdown')" title="CRM &amp; Analytics">
                            <div class="nav-link-content">
                                <i data-lucide="bar-chart-3"></i>
                                <span>CRM &amp; Analytics</span>
                            </div>
                            <i data-lucide="chevron-down" class="chevron"></i>
                        </button>
                        <div class="dropdown-content">
                            <a href="crm.html${botQuery}" class="nav-link sub-link" title="CRM / Leads">
                                <i data-lucide="users"></i>
                                <span>CRM / Leads</span>
                            </a>
                            <a href="reports.html${botQuery}" class="nav-link sub-link" title="Reports">
                                <i data-lucide="bar-chart-3"></i>
                                <span>Reports</span>
                            </a>
                        </div>
                    </div>
                ` : ""}
            </nav>

            <!-- Bottom section: tenant navigation only. Account actions live in <tenant-account-menu>. -->
            <div class="sidebar-bottom-section">
                ${isAdmin ? `
                <a href="team.html${botQuery}" class="profile-link" title="Team Members">
                    <div class="profile-link-content">
                        <i data-lucide="users"></i>
                        <span>Team Members</span>
                    </div>
                </a>
                ` : ""}
                <a href="pricing.html${botQuery}" class="profile-link" title="Pricing & Billing">
                    <div class="profile-link-content">
                        <i data-lucide="credit-card"></i>
                        <span>Billing</span>
                    </div>
                </a>
            </div>

        </aside>


        <!-- System Guidance Bot UI - ONLY ON INTERNAL PAGES -->
        ${(!isBotsPage && botId) ? `
            <div id="guide-bot-trigger" class="guide-bot-trigger">
                <span>💬</span>
            </div>

            <div id="guide-bot-window" class="guide-bot-window" style="display: none;" aria-hidden="true">
                <div class="bot-header">
                    <h3>System Guide</h3>
                    <button id="close-bot" style="background:none; border:none; color:white; cursor:pointer;">✕</button>
                </div>
                <div id="bot-messages" class="bot-messages"></div>
                <div class="bot-input-area">
                    <input type="text" id="bot-input" placeholder="Ask for help...">
                    <button id="send-bot-msg">➔</button>
                </div>
            </div>
        ` : ""}
        `;

        this.loadAssets();
        this.initSidebar();
        this.initCollapseToggle();

        // Check if lucide is available globally
        if (window.lucide && typeof window.lucide.createIcons === 'function') {
            window.lucide.createIcons({ root: this });
        } else {
            // Load it dynamically if missing
            const script = document.createElement('script');
            script.src = 'https://unpkg.com/lucide@latest';
            script.onload = () => {
                window.lucide.createIcons({ root: this });
            };
            document.head.appendChild(script);
        }
    }

    loadAssets() {
        // Load AI Bot assets ONLY on internal pages
        const urlParams = new URLSearchParams(window.location.search);
        const botId = urlParams.get("bot_id");
        const currentPath = window.location.pathname.split('/').pop() || 'index.html';

        if (currentPath !== 'bots.html' && botId) {
            if (!document.getElementById('guide-bot-css')) {
                const link = document.createElement('link');
                link.id = 'guide-bot-css';
                link.rel = 'stylesheet';
                link.href = '/assets/css/guide-bot.css';
                document.head.appendChild(link);
            }
            if (!document.getElementById('guide-bot-js')) {
                const script = document.createElement('script');
                script.id = 'guide-bot-js';
                script.src = '/assets/js/guide-bot.js';
                document.head.appendChild(script);
            }
        }
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
                if (p === currentPath) { pl.classList.add("active"); }
            }
        });

        navLinks.forEach(link => {
            // Check if the href matches the exact path (removing queries)
            const href = link.getAttribute("href");
            if (href) {
                const linkPath = href.split("?")[0];
                if (linkPath === currentPath && !link.classList.contains("dropdown-toggle")) {
                    link.classList.add("active");
                }
            }
        });

        // Auto-expand dropdowns if child is active
        if (['new_linkdocs.html', 'new_prompt.html', 'training.html'].includes(currentPath)) {
            const drop = this.querySelector('#training-dropdown');
            if (drop) {
                drop.classList.add('open');
            }
        }
        if (['model_settings.html', 'testbot.html'].includes(currentPath)) {
            const drop = this.querySelector('#behaviour-dropdown');
            if (drop) {
                drop.classList.add('open');
            }
        }
        if (['broadcast.html', 'meta_templates.html'].includes(currentPath)) {
            const drop = this.querySelector('#campaigns-dropdown');
            if (drop) {
                drop.classList.add('open');
            }
        }
        if (['crm.html', 'reports.html'].includes(currentPath)) {
            const drop = this.querySelector('#crm-analytics-dropdown');
            if (drop) {
                drop.classList.add('open');
            }
        }

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

            if (isMobileViewport) {
                sidebar.classList.remove('collapsed');
                const isOpen = sidebar.classList.contains('mobile-open');
                icon.textContent = isOpen ? '✕' : '☰';
                toggle.setAttribute('aria-label', isOpen ? 'Close menu' : 'Open menu');
                toggle.setAttribute('title', isOpen ? 'Close menu' : 'Open menu');
            } else {
                sidebar.classList.remove('mobile-open');
                const shouldBeCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
                sidebar.classList.toggle('collapsed', shouldBeCollapsed);
                icon.textContent = shouldBeCollapsed ? '☰' : '«';
                toggle.setAttribute('aria-label', shouldBeCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
                toggle.setAttribute('title', shouldBeCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
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
        if (insideEl) insideEl.classList.toggle('open');
    }
};
