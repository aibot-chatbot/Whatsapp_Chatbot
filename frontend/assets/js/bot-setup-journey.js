/* Navigation only: a visited step is not proof that its setup is complete. */
class BotSetupJourney extends HTMLElement {
    static get observedAttributes() { return ['current', 'bot-id']; }

    connectedCallback() { this.render(); }
    attributeChangedCallback() { if (this.isConnected) this.render(); }

    render() {
        const params = new URLSearchParams(window.location.search);
        const candidate = this.getAttribute('bot-id') || params.get('bot_id') || sessionStorage.getItem('selectedBotId');
        const botId = candidate && candidate !== 'null' ? candidate : '';
        const query = new URLSearchParams();
        if (botId) query.set('bot_id', botId);
        if (params.get('setup') === '1') query.set('setup', '1');

        const nav = document.createElement('nav');
        nav.className = 'setup-journey';
        nav.setAttribute('aria-label', 'Bot setup steps');
        const list = document.createElement('ol');
        const steps = [
            ['knowledge', 'Add knowledge', 'new_linkdocs.html'],
            ['instructions', 'Review instructions', 'new_prompt.html'],
            ['test', 'Test replies', 'testbot.html'],
            ['publish', 'Publish', 'integration.html']
        ];
        steps.forEach(([key, label, page], index) => {
            const item = document.createElement('li');
            const link = document.createElement(botId ? 'a' : 'span');
            link.className = 'setup-journey-link';
            if (botId) link.href = `${page}?${query}`;
            if (this.getAttribute('current') === key) link.setAttribute('aria-current', 'step');
            const number = document.createElement('span');
            number.className = 'setup-journey-number';
            number.setAttribute('aria-hidden', 'true');
            number.textContent = String(index + 1);
            const text = document.createElement('span');
            text.textContent = label;
            link.append(number, text);
            item.append(link);
            list.append(item);
        });
        nav.append(list);
        this.replaceChildren(nav);
    }
}

customElements.define('bot-setup-journey', BotSetupJourney);
