class ChatbotSidebar extends HTMLElement {
    constructor() {
        super();
    }

    connectedCallback() {
        const currentPath = window.location.pathname.split('/').pop() || 'index.html';
        const urlParams = new URLSearchParams(window.location.search);
        const botId = urlParams.get("bot_id");
        const botQuery = botId ? `?bot_id=${botId}` : "";
        const isMobileViewport = window.matchMedia('(max-width: 768px)').matches;
        const isCollapsed = localStorage.getItem("sidebarCollapsed") === "true" && !isMobileViewport;

        const isBotsPage = currentPath === "bots.html";

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
                padding: 40px 24px;
                position: sticky;
                top: 0;
                z-index: 100;
                font-family: 'Outfit', sans-serif;
                transition: width 0.28s ease, padding 0.28s ease;
            }
            .sidebar-top {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 10px;
                margin-bottom: 40px;
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
                gap: 6px;
            }
            .nav-link {
                text-decoration: none;
                color: var(--text-dim, #94a3b8);
                padding: 12px 16px;
                border-radius: 14px;
                display: flex;
                align-items: center;
                gap: 14px;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                font-weight: 500;
                font-size: 1rem;
                cursor: pointer;
                border: 1px solid transparent;
                white-space: nowrap;
            }
            .nav-link i, .nav-link svg {
                width: 20px;
                height: 20px;
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
                padding-left: 10px;
            }
            .dropdown-container.open .dropdown-content {
                max-height: 500px;
                margin-top: 6px;
                padding-bottom: 8px;
            }
            .dropdown-container .chevron {
                transition: transform 0.3s ease;
                width: 18px;
                height: 18px;
            }
            .dropdown-container.open .chevron {
                transform: rotate(180deg);
                color: var(--text-main, #f8fafc);
            }
            .sub-link {
                font-size: 0.95rem;
                padding: 10px 16px;
                gap: 12px;
            }
            .sub-link i, .sub-link svg {
                width: 18px;
                height: 18px;
            }
            .logout-btn {
                margin-top: auto;
                color: #ef4444;
                display: flex;
                align-items: center;
                gap: 14px;
                padding: 14px 16px;
                text-decoration: none;
                font-weight: 600;
                border-radius: 14px;
                transition: all 0.3s;
                border: 1px solid transparent;
                white-space: nowrap;
            }
            .logout-btn i, .logout-btn svg {
                width: 20px;
                height: 20px;
            }
            .logout-btn:hover {
                background: rgba(239, 68, 68, 0.08);
                border-color: rgba(239, 68, 68, 0.2);
                transform: translateX(4px);
            }
            
            .nav-link-content {
                display: flex;
                align-items: center;
                gap: 14px;
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
            .sidebar.collapsed .logout-btn {
                justify-content: center;
                padding: 12px;
                gap: 0;
            }
            .sidebar.collapsed .nav-link-content {
                justify-content: center;
                gap: 0;
            }
            .sidebar.collapsed .nav-link span,
            .sidebar.collapsed .logout-btn span,
            .sidebar.collapsed .chevron {
                display: none;
            }
            .sidebar.collapsed .dropdown-content {
                padding-left: 0;
            }
            .sidebar.collapsed .dropdown-container.open .dropdown-content {
                margin-top: 6px;
            }
            .sidebar.collapsed .nav-link:hover,
            .sidebar.collapsed .logout-btn:hover {
                transform: none;
            }
            @media (max-width: 768px) {
                .sidebar,
                .sidebar.collapsed {
                    width: 100%;
                    height: auto;
                    min-height: auto;
                    position: relative;
                    padding: 24px 20px;
                }
                .sidebar.collapsed .sidebar-top {
                    justify-content: space-between;
                    margin-bottom: 28px;
                }
                .sidebar.collapsed .logo {
                    display: flex;
                }
                .sidebar.collapsed .nav-link,
                .sidebar.collapsed .logout-btn {
                    justify-content: flex-start;
                    padding: 12px 16px;
                    gap: 14px;
                }
                .sidebar.collapsed .nav-link-content {
                    justify-content: flex-start;
                    gap: 14px;
                }
                .sidebar.collapsed .nav-link span,
                .sidebar.collapsed .logout-btn span,
                .sidebar.collapsed .chevron {
                    display: inline;
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
                    <span class="sidebar-toggle-icon">${isCollapsed ? "☰" : "«"}</span>
                </button>
            </div>
    
            <nav class="nav-list">
                <a href="bots.html" class="nav-link" title="My Bots">
                    <i data-lucide="home"></i>
                    <span>My Bots</span>
                </a>
    
                ${!isBotsPage && botId ? `
                    <div style="height: 1px; background: rgba(255,255,255,0.05); margin: 12px 0;"></div>
                    
                    <a href="index.html${botQuery}" class="nav-link" title="Dashboard">
                        <i data-lucide="layout-dashboard"></i>
                        <span>Dashboard</span>
                    </a>
                    
                    <a href="conversations.html${botQuery}" class="nav-link" title="Conversations">
                        <i data-lucide="message-square"></i>
                        <span>Conversations</span>
                    </a>

                    <a href="customer_insights.html${botQuery}" class="nav-link" title="Customer Insights">
                        <i data-lucide="target"></i>
                        <span>Customer Insights</span>
                    </a>

                    <a href="crm.html${botQuery}" class="nav-link" title="CRM / Leads">
                        <i data-lucide="users"></i>
                        <span>CRM / Leads</span>
                    </a>

                    <a href="reports.html${botQuery}" class="nav-link" title="Reports">
                        <i data-lucide="bar-chart-3"></i>
                        <span>Reports</span>
                    </a>
                    
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
    
                    <a href="integration.html${botQuery}" class="nav-link" title="Integration">
                        <i data-lucide="plug"></i>
                        <span>Integration</span>
                    </a>
                ` : ""}
            </nav>

            <a href="login.html?logout=1" class="logout-btn" title="Logout">
                <i data-lucide="log-out"></i>
                <span>Logout</span>
            </a>
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
        const currentPath = window.location.pathname.split('/').pop() || 'index.html';
        const navLinks = this.querySelectorAll('.nav-link');

        navLinks.forEach(link => {
            // Check if the href matches the exact path (removing queries)
            const href = link.getAttribute('href');
            if (href) {
                const linkPath = href.split('?')[0];
                if (linkPath === currentPath && !link.classList.contains('dropdown-toggle')) {
                    link.classList.add('active');
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
            const shouldBeCollapsed = localStorage.getItem('sidebarCollapsed') === 'true' && !isMobileViewport;
            sidebar.classList.toggle('collapsed', shouldBeCollapsed);

            icon.textContent = shouldBeCollapsed ? '☰' : '«';
            toggle.setAttribute('aria-label', shouldBeCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
            toggle.setAttribute('title', shouldBeCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
        };

        toggle.addEventListener('click', () => {
            const isMobileViewport = window.matchMedia('(max-width: 768px)').matches;

            if (isMobileViewport) {
                localStorage.setItem('sidebarCollapsed', 'false');
                sidebar.classList.remove('collapsed');
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
