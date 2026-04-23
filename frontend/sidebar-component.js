class ChatbotSidebar extends HTMLElement {
    constructor() {
        super();
    }

    connectedCallback() {
        this.innerHTML = `
        <aside class="sidebar" style="width: 280px; background: var(--sidebar-bg); backdrop-filter: blur(20px); border-right: 1px solid var(--glass-border); height: 100vh; display: flex; flex-direction: column; padding: 40px 20px; position: sticky; top: 0; z-index: 100;">
            <div class="logo" style="font-size: 1.5rem; font-weight: 700; margin-bottom: 50px; display: flex; align-items: center; gap: 12px; background: linear-gradient(to right, #60a5fa, #10b981); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"></path><path d="M12 6v6l4 2"></path></svg>
                <span>AI CHATBOT</span>
            </div>
            <nav class="nav-list" style="list-style: none; flex-grow: 1;">
                <div class="nav-item" style="margin-bottom: 8px;">
                    <a href="index.html" class="nav-link">📊 Dashboard</a>
                </div>
                
                <div class="dropdown-container" id="training-dropdown" style="margin-bottom: 8px;">
                    <div class="nav-item">
                        <button class="nav-link dropdown-toggle" onclick="window.toggleSidebarDropdown('training-dropdown')" style="width: 100%; justify-content: space-between; background: transparent; border: none; cursor: pointer; text-align: left; color: var(--text-dim); padding: 12px 16px; border-radius: 12px; display: flex; align-items: center; gap: 12px; font-weight: 500; font-family: 'Outfit', sans-serif; font-size: 1rem;">
                            <span>📁 Training Data</span>
                            <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        </button>
                    </div>
                    <div class="dropdown-content">
                        <a href="new_linkdocs.html" class="nav-link sub-link">🔗 Links / Docs</a>
                        <a href="new_prompt.html" class="nav-link sub-link">📋 Prompt</a>
                        <a href="training.html" class="nav-link sub-link">📚 Help & Documentation</a>
                    </div>
                </div>
                
                <div class="dropdown-container" id="behaviour-dropdown" style="margin-bottom: 8px;">
                    <div class="nav-item">
                        <button class="nav-link dropdown-toggle" onclick="window.toggleSidebarDropdown('behaviour-dropdown')" style="width: 100%; justify-content: space-between; background: transparent; border: none; cursor: pointer; text-align: left; color: var(--text-dim); padding: 12px 16px; border-radius: 12px; display: flex; align-items: center; gap: 12px; font-weight: 500; font-family: 'Outfit', sans-serif; font-size: 1rem;">
                            <span>⚙️ Behaviour</span>
                            <svg class="chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
                        </button>
                    </div>
                    <div class="dropdown-content">
                        <a href="behaviour.html" class="nav-link sub-link">🤖 Tune AI</a>
                        <a href="testbot.html" class="nav-link sub-link">🧪 Test Your Bot</a>
                    </div>
                </div>
                
                <div class="nav-item" style="margin-bottom: 8px;">
                    <a href="integration.html" class="nav-link">🔌 Integration</a>
                </div>
            </nav>
            <a href="login.html?logout=1" class="logout-btn">🚪 Logout</a>
        </aside>
        `;

        this.initSidebar();
    }

    initSidebar() {
        const currentPath = window.location.pathname.split('/').pop() || 'index.html';
        const navLinks = this.querySelectorAll('.nav-link');
        
        navLinks.forEach(link => {
            if (link.getAttribute('href') === currentPath) {
                link.classList.add('active');
            }
        });

        // Auto-expand dropdowns if child is active
        if (['new_linkdocs.html', 'new_prompt.html', 'training.html'].includes(currentPath)) {
            const drop = this.querySelector('#training-dropdown');
            if (drop) drop.classList.add('open');
        }
        if (['behaviour.html', 'testbot.html'].includes(currentPath)) {
            const drop = this.querySelector('#behaviour-dropdown');
            if (drop) drop.classList.add('open');
        }
    }
}

customElements.define('chatbot-sidebar', ChatbotSidebar);

window.toggleSidebarDropdown = window.toggleSidebarDropdown || function(id) {
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
