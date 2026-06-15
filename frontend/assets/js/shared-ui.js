/**
 * shared-ui.js
 * Reusable UI helpers for the AI Chatbot frontend.
 */

/* ===== Bot ID Selector ===== */
function resolveBotId() {
    var urlParams = new URLSearchParams(window.location.search);
    var fromUrl = urlParams.get("bot_id");
    var fromStorage = sessionStorage.getItem("selectedBotId");
    var botId = fromUrl || fromStorage;
    if (botId) {
        sessionStorage.setItem("selectedBotId", botId);
    }
    return botId;
}

/* ===== Lucide Icon Refresh ===== */
function refreshIcons(root) {
    if (window.lucide && typeof window.lucide.createIcons === "function") {
        try {
            window.lucide.createIcons(root ? { root: root } : undefined);
        } catch (_) {}
    }
}

/* ===== Chat Message Renderer ===== */
function renderChatMessages(container, messages, options) {
    if (!messages || messages.length === 0) {
        container.innerHTML = '<div class="empty-state" style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--text-dim,#94a3b8);text-align:center;"><p>No messages found.</p></div>';
        return;
    }

    var opts = Object.assign({
        showTime: false,
        showSender: false,
        showDeliveryStatus: false,
        searchQuery: "",
        parseButtons: false,
        onButtonClick: null
    }, options || {});

    var html = messages.map(function(msg) {
        var rowClass = "bot";
        var senderName = "AI Bot";

        if (msg.role === "user") {
            rowClass = "user";
            senderName = "Customer";
        }
        if (msg.role === "assistant" && msg.metadata && msg.metadata.sent_by === "human_agent") {
            rowClass = "agent";
            senderName = "You (Agent)";
        }

        var content = (msg.content || msg.message_text || "");

        // Parse [BUTTON: ...] markers
        if (opts.parseButtons && rowClass === "bot") {
            var buttonRegex = /\[BUTTON:\s*(.*?)\]/g;
            var buttons = [];
            var m;
            while ((m = buttonRegex.exec(content)) !== null) {
                buttons.push(m[1].trim());
            }
            content = content.replace(buttonRegex, "").trim();
            content = content.replace(/\n/g, "<br>");

            if (buttons.length > 0) {
                var btnsHtml = buttons.map(function(btn) {
                    return '<button class="sim-button" data-btn-text="' + btn.replace(/"/g, "&quot;") + '">' + btn + '</button>';
                }).join("");
                content += '<div class="sim-button-group" style="display:flex;flex-direction:column;gap:8px;margin-top:12px;">' + btnsHtml + '</div>';
            }
        } else {
            content = content.replace(/\n/g, "<br>");
        }

        // Highlight search matches
        if (opts.searchQuery) {
            var escapedQ = opts.searchQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
            var searchRe = new RegExp("(" + escapedQ + ")", "gi");
            content = content.replace(searchRe, '<mark style="background:rgba(245,158,11,0.4);color:inherit;border-radius:2px;padding:0 2px;">$1</mark>');
        }

        // Format time
        var timeHtml = "";
        if (opts.showTime && msg.created_at) {
            timeHtml = '<span class="message-time">' + formatTimeSimple(msg.created_at) + '</span>';
        }

        // Sender label
        var senderHtml = "";
        if (opts.showSender) {
            senderHtml = '<span class="message-sender">' + senderName + '</span>';
        }

        // Delivery status
        var deliveryHtml = "";
        if (opts.showDeliveryStatus && msg.delivery_status) {
            var ds = msg.delivery_status;
            var rc = msg.retry_count || 0;
            var statusClass = "";
            var statusText = "";
            if (ds === "failed" || ds === "permanent_failed") {
                statusClass = "failed";
                statusText = ds === "permanent_failed" ? "Failed permanently" : "Failed to send - Auto retrying";
            } else if (ds === "retrying") {
                statusClass = "retrying";
                statusText = "Retrying now...";
            } else if (ds === "sent" && rc > 0) {
                statusClass = "retried";
                statusText = "Sent after retry";
            }
            if (statusClass) {
                deliveryHtml = '<div class="message-delivery-status ' + statusClass + '">' + statusText + '</div>';
            }
        }

        return '<div class="message-row ' + rowClass + '"><div class="message-bubble">' + senderHtml + content + timeHtml + deliveryHtml + '</div></div>';
    }).join("");

    container.innerHTML = html;

    // Attach button click handlers
    if (opts.parseButtons && opts.onButtonClick) {
        container.querySelectorAll(".sim-button").forEach(function(btn) {
            btn.addEventListener("click", function() {
                var text = btn.getAttribute("data-btn-text") || btn.textContent;
                opts.onButtonClick(text);
            });
        });
    }

    container.scrollTop = container.scrollHeight;
}

function formatTimeSimple(dateStr) {
    if (!dateStr) return "";
    try {
        var d = new Date(dateStr);
        if (isNaN(d.getTime())) return "";
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch (_) {
        return "";
    }
}
