function initGuidanceBot() {
    const botTrigger = document.getElementById('guide-bot-trigger');
    const botWindow = document.getElementById('guide-bot-window');
    const closeBot = document.getElementById('close-bot');
    const botInput = document.getElementById('bot-input');
    const sendBtn = document.getElementById('send-bot-msg');
    const messageArea = document.getElementById('bot-messages');

    if (!botWindow) {
        // If sidebar hasn't rendered yet, try again in 500ms
        setTimeout(initGuidanceBot, 500);
        return;
    }

    // Global Toggle Function
    window.toggleGuidanceBot = () => {
        botWindow.classList.toggle('active');
        if (botWindow.classList.contains('active')) {
            botInput?.focus();
        }
    };

    botTrigger?.addEventListener('click', window.toggleGuidanceBot);
    closeBot?.addEventListener('click', () => botWindow.classList.remove('active'));

    // Real-time synchronization event listener
    window.addEventListener('recheckBotStatus', async () => {
        console.log("Rechecking bot status...");
        if (messageArea) messageArea.classList.add('sync-pulse');

        const urlParams = new URLSearchParams(window.location.search);
        const botId = urlParams.get("bot_id");

        try {
            const response = await fetch(`http://127.0.0.1:8000/api/guide/status?bot_id=${botId}`);
            const data = await response.json();

            if (data.status === 'online') {
                renderMessage("bot", `
<div style="background: rgba(16, 185, 129, 0.1); border-left: 4px solid #10b981; padding: 12px 16px; border-radius: 8px; margin: 5px 0; font-family: 'Outfit', sans-serif;">
    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #10b981; font-size: 0.95rem; margin-bottom: 6px;">
        <span style="font-size: 1.1rem;">✨</span> Configuration Active
    </div>
    <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.4;">
        <strong>${data.active_provider}</strong> configuration verified! I can now help you with your settings.
    </div>
</div>
`, false);
                const warning = document.querySelector('.setup-warning');
                if (warning) warning.style.display = 'none';
            } else if (data.status === 'key_missing') {
                renderMessage("bot", `
<div style="background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 8px; margin: 5px 0; font-family: 'Outfit', sans-serif;">
    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #ef4444; font-size: 0.95rem; margin-bottom: 6px;">
        <span style="font-size: 1.1rem;">⚠️</span> Key Missing
    </div>
    <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.4; margin-bottom: 12px;">
        <strong>${data.active_provider}</strong> is selected, but the API Key is missing in settings.
    </div>
    <a href="model_settings.html?bot_id=${botId}" style="display: inline-flex; align-items: center; justify-content: center; background: #ef4444; color: white; padding: 8px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; text-decoration: none;">
        Fix Setup ⚙️
    </a>
</div>
`, false);
            } else if (data.status === 'setup_required') {
                renderMessage("bot", `
<div style="background: rgba(245, 158, 11, 0.1); border-left: 4px solid #f59e0b; padding: 12px 16px; border-radius: 8px; margin: 5px 0; font-family: 'Outfit', sans-serif;">
    <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; color: #f59e0b; font-size: 0.95rem; margin-bottom: 6px;">
        <span style="font-size: 1.1rem;">⚠️</span> System Setup Required
    </div>
    <div style="color: #e2e8f0; font-size: 0.9rem; line-height: 1.4; margin-bottom: 12px;">
        Please select a valid AI Provider in the Behaviour settings to enable the system guide.
    </div>
    <a href="model_settings.html?bot_id=${botId}" style="display: inline-flex; align-items: center; justify-content: center; background: #f59e0b; color: #0f172a; padding: 8px 14px; border-radius: 6px; font-size: 0.85rem; font-weight: 600; text-decoration: none; transition: background 0.2s ease;">
        Configure Provider ⚙️
    </a>
</div>
`, false);
            }

        } catch (error) {
            console.error("Sync failed:", error);
        } finally {
            if (messageArea) messageArea.classList.remove('sync-pulse');
        }
    });

    // Chat functionality

    async function sendMessage() {
        const text = botInput?.value.trim();
        if (!text) return;

        const urlParams = new URLSearchParams(window.location.search);
        const botId = urlParams.get("bot_id");

        renderMessage("user", text);
        if (botInput) botInput.value = '';

        try {
            const response = await fetch('http://127.0.0.1:8000/api/guide/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text,
                    bot_id: botId
                })
            });
            const data = await response.json();

            renderMessage("bot", data.reply || data.error);
        } catch (error) {
            renderMessage("bot", "Sorry, I'm having trouble connecting right now.");
        }
    }

    // --- CHAT PERSISTENCE LOGIC ---
    const STORAGE_KEY = 'guidance_bot_history';

    function saveMessage(role, text) {
        const history = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        history.push({ role, text, timestamp: new Date().getTime() });
        // Keep only last 20 messages to save space
        if (history.length > 20) history.shift();
        localStorage.setItem(STORAGE_KEY, JSON.stringify(history));
    }

    function loadHistory() {
        if (!messageArea) return;
        const history = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
        if (history.length > 0) {
            // Clear area and render history
            messageArea.innerHTML = '';
            history.forEach(msg => renderMessage(msg.role, msg.text, false)); // false means don't save again
            return true;
        }
        return false;
    }

    function parseMarkdown(text) {
        if (!text) return "";
        const trimmed = text.trim();
        if (trimmed.startsWith('<div')) {
            return text;
        }

        let html = text;

        // Parse bold tags **text** -> <strong>text</strong>
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong style="color: #60a5fa; font-weight: 600;">$1</strong>');

        // Parse bullet points & numbered lists
        const lines = html.split('\n');
        let inList = false;
        let listType = ''; // 'ul' or 'ol'
        const processedLines = lines.map(line => {
            const lineTrim = line.trim();
            if (lineTrim.startsWith('- ') || lineTrim.startsWith('* ')) {
                const content = lineTrim.substring(2);
                let listHtml = '';
                if (!inList) {
                    listHtml += '<ul style="margin: 8px 0; padding-left: 20px; list-style-type: disc;">';
                    inList = true;
                    listType = 'ul';
                } else if (listType !== 'ul') {
                    listHtml += '</ol><ul style="margin: 8px 0; padding-left: 20px; list-style-type: disc;">';
                    listType = 'ul';
                }
                listHtml += `<li style="margin: 6px 0; line-height: 1.5; color: #f8fafc; font-size: 0.92rem;">${content}</li>`;
                return listHtml;
            } else if (lineTrim.match(/^\d+\.\s/)) {
                const content = lineTrim.replace(/^\d+\.\s/, '');
                let listHtml = '';
                if (!inList) {
                    listHtml += '<ol style="margin: 8px 0; padding-left: 20px; list-style-type: decimal;">';
                    inList = true;
                    listType = 'ol';
                } else if (listType !== 'ol') {
                    listHtml += '</ul><ol style="margin: 8px 0; padding-left: 20px; list-style-type: decimal;">';
                    listType = 'ol';
                }
                listHtml += `<li style="margin: 6px 0; line-height: 1.5; color: #f8fafc; font-size: 0.92rem;">${content}</li>`;
                return listHtml;
            } else {
                let suffix = '';
                if (inList) {
                    suffix = listType === 'ul' ? '</ul>' : '</ol>';
                    inList = false;
                    listType = '';
                }
                return suffix + line;
            }
        });

        if (inList) {
            processedLines.push(listType === 'ul' ? '</ul>' : '</ol>');
        }

        html = processedLines.join('\n');

        // Parse paragraphs and double newlines to clean gaps
        html = html.replace(/\n\n/g, '<div style="height: 10px;"></div>');
        html = html.replace(/\n/g, '<br>');

        return html;
    }

    function renderMessage(role, text, shouldSave = true) {
        if (!messageArea) return;
        const div = document.createElement('div');
        div.className = `message ${role}`;
        
        // Apply professional Markdown parser for bot responses to look clean
        const content = role === 'bot' ? parseMarkdown(text) : text;
        
        div.innerHTML = content;
        messageArea.appendChild(div);
        messageArea.scrollTop = messageArea.scrollHeight;

        if (shouldSave) saveMessage(role, text);
    }
    // --- END PERSISTENCE LOGIC ---

    // Initial load
    const hasHistory = loadHistory();

    sendBtn?.addEventListener('click', sendMessage);
    botInput?.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') sendMessage();
    });

    // Initial greeting and proactive status check (ONLY if no history)
    if (!hasHistory && messageArea && messageArea.children.length === 0) {
        setTimeout(() => {
            renderMessage("bot", "Hi! I'm your setup assistant. How can I help you today?");

            // Check status immediately to show verification
            window.dispatchEvent(new CustomEvent('recheckBotStatus'));
        }, 1000);
    } else if (hasHistory) {
        // If we have history, still trigger status check but silently to update UI warnings if needed
        window.dispatchEvent(new CustomEvent('recheckBotStatus'));
    }
}

// Start looking for the bot elements
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initGuidanceBot);
} else {
    initGuidanceBot();
}

