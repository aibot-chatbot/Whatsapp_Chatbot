class ChatbotSidebar extends HTMLElement {
    constructor() {
        super();
    }

    connectedCallback() {
        const currentPath = window.location.pathname.split('/').pop() || 'index.html';
        const urlParams = new URLSearchParams(window.location.search);
        const botId = urlParams.get("bot_id");
        const botQuery = botId ? `?bot_id=${botId}` : "";

        const isBotsPage = currentPath === "bots.html";

        this.innerHTML = `
        <style>
            .sidebar {
                width: 280px;
                background: var(--sidebar-bg);
                backdrop-filter: blur(20px);
                border-right: 1px solid var(--glass-border);
                height: 100vh;
                display: flex;
                flex-direction: column;
                padding: 40px 20px;
                position: sticky;
                top: 0;
                z-index: 100;
            }
            .logo {
                font-size: 1.5rem;
                font-weight: 700;
                margin-bottom: 50px;
                display: flex;
                align-items: center;
                gap: 12px;
                background: linear-gradient(to right, #60a5fa, #10b981);
                -webkit-background-clip: text;
                background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            .nav-list {
                list-style: none;
                flex-grow: 1;
            }
            .nav-item {
                margin-bottom: 8px;
            }
            .nav-link {
                text-decoration: none;
                color: var(--text-dim);
                padding: 12px 16px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                gap: 12px;
                transition: all 0.3s;
                font-weight: 500;
                cursor: pointer;
            }
            .nav-link:hover {
                background: rgba(255, 255, 255, 0.05);
                color: var(--text-main);
            }
            .dropdown-content {
                max-height: 0;
                overflow: hidden;
                transition: all 0.3s ease-in-out;
                padding-left: 20px;
                display: flex;
                flex-direction: column;
                gap: 4px;
            }
            .dropdown-container.open .dropdown-content {
                max-height: 500px;
                margin-top: 8px;
                padding-bottom: 8px;
            }
            .sub-link {
                font-size: 0.9rem;
                padding: 10px 16px;
            }
            .logout-btn {
                margin-top: auto;
                color: #ef4444;
                display: flex;
                align-items: center;
                gap: 12px;
                padding: 12px 16px;
                text-decoration: none;
                font-weight: 600;
                border-radius: 12px;
                transition: background 0.3s;
            }
            .logout-btn:hover {
                background: rgba(239, 68, 68, 0.1);
            }
        </style>
        <aside class="sidebar">
            <div class="logo">
                <span>AI CHATBOT</span>
            </div>
    
            <nav class="nav-list">
                <div class="nav-item">
                    <a href="bots.html" class="nav-link">🤖 Bots</a>
                </div>
    
                ${!isBotsPage && botId ? `
                    <div class="nav-item">
                        <a href="index.html${botQuery}" class="nav-link">📊 Dashboard</a>
                    </div>

    
                    <div class="dropdown-container" id="training-dropdown">
                        <div class="nav-item">
                            <button class="nav-link dropdown-toggle" onclick="window.toggleSidebarDropdown('training-dropdown')" style="width: 100%; justify-content: space-between; background: transparent; border: none; font-family: inherit; font-size: inherit;">
                                <span>📁 Training Data</span>
                                <span class="chevron">⌄</span>
                            </button>
                        </div>
                        <div class="dropdown-content">
                            <a href="new_linkdocs.html${botQuery}" class="nav-link sub-link">🔗 Links / Docs</a>
                            <a href="new_prompt.html${botQuery}" class="nav-link sub-link">📋 Prompt</a>
                            <a href="training.html${botQuery}" class="nav-link sub-link">📚 Help & Documentation</a>
                        </div>
                    </div>
    
                    <div class="dropdown-container" id="behaviour-dropdown">
                        <div class="nav-item">
                            <button class="nav-link dropdown-toggle" onclick="window.toggleSidebarDropdown('behaviour-dropdown')" style="width: 100%; justify-content: space-between; background: transparent; border: none; font-family: inherit; font-size: inherit;">
                                <span>⚙️ Behaviour</span>
                                <span class="chevron">⌄</span>
                            </button>
                        </div>
                        <div class="dropdown-content">
                            <a href="model_settings.html${botQuery}" class="nav-link sub-link">🤖 Tune AI</a>
                            <a href="testbot.html${botQuery}" class="nav-link sub-link">🧪 Test Your Bot</a>
                        </div>
                    </div>
    
                    <div class="nav-item">
                        <a href="integration.html${botQuery}" class="nav-link">🔌 Integration</a>
                    </div>
                ` : ""}

            </nav>

    
            <a href="login.html?logout=1" class="logout-btn">🚪 Logout</a>
        </aside>

        <!-- System Guidance Bot UI - ONLY ON INTERNAL PAGES -->
        ${(!isBotsPage && botId) ? `
            <div id="guide-bot-trigger" class="guide-bot-trigger">
                <span>💬</span>
            </div>

            <div id="guide-bot-window" class="guide-bot-window">
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
            if (link.getAttribute('href') === currentPath) {
                link.classList.add('active');
                link.style.background = 'var(--primary)';
                link.style.color = 'white';
                link.style.boxShadow = '0 4px 20px var(--primary-glow)';
            }
        });

        // Auto-expand dropdowns if child is active
        if (['new_linkdocs.html', 'new_prompt.html', 'training.html'].includes(currentPath)) {
            const drop = this.querySelector('#training-dropdown');
            if (drop) drop.classList.add('open');
        }
        if (['model_settings.html', 'testbot.html'].includes(currentPath)) {
            const drop = this.querySelector('#behaviour-dropdown');
            if (drop) drop.classList.add('open');
        }
    }
}

customElements.define('chatbot-sidebar', ChatbotSidebar);

window.toggleSidebarDropdown = window.toggleSidebarDropdown || function (id) {
    const el = document.getElementById(id);
    if (!el) {
        // If not found in document, look inside the sidebar tag
        const sb = document.querySelector('chatbot-sidebar');
        if (sb) {
            const insideEl = sb.querySelector('#' + id);
            if (insideEl) insideEl.classList.toggle('open');
        }
    } else {
        el.classList.toggle('open');
    }
};
