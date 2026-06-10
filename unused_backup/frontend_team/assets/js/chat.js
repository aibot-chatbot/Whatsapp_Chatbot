// Chat Interaction Logic for Antigravity AI
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('user-input');
    if (input) {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendMessage();
            }
        });
    }
});

function sendMessage() {
    const input = document.getElementById('user-input');
    const chatBox = document.getElementById('chat-box');
    
    if (input && input.value.trim() !== "") {
        const userValue = input.value.trim();
        const timeStr = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        
        // Append user message
        const userBubble = document.createElement('div');
        userBubble.className = 'bubble bubble-user';
        userBubble.innerHTML = `${userValue}<span class="timestamp">${timeStr}</span>`;
        
        chatBox.appendChild(userBubble);
        input.value = "";
        chatBox.scrollTop = chatBox.scrollHeight;

        // Simulate Bot response
        setTimeout(() => {
            const botBubble = document.createElement('div');
            botBubble.className = 'bubble bubble-bot';
            botBubble.innerHTML = `This is a premium response from Antigravity AI! Your input: "${userValue}" has been processed.<span class="timestamp">${timeStr}</span>`;
            chatBox.appendChild(botBubble);
            chatBox.scrollTop = chatBox.scrollHeight;
        }, 1000);
    }
}
