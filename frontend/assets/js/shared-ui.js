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

/* ===== Authenticated Tenant Account Menu ===== */
(function () {
    if (window.customElements && window.customElements.get("tenant-account-menu")) {
        return;
    }

    function getStoredUser() {
        try {
            var parsed = JSON.parse(sessionStorage.getItem("user") || "null");
            return parsed && typeof parsed === "object" ? parsed : null;
        } catch (_) {
            return null;
        }
    }

    function getDisplayName(user) {
        var name = user && (user.full_name || user.name || user.email);
        return typeof name === "string" && name.trim() ? name.trim() : "Account";
    }

    function getEmail(user) {
        var email = user && user.email;
        return typeof email === "string" && email.trim() ? email.trim() : "";
    }

    function getInitials(label) {
        var words = String(label || "A").trim().split(/\s+/).filter(Boolean);
        var initials = words.slice(0, 2).map(function (word) {
            return word.charAt(0).toUpperCase();
        }).join("");
        return initials || "A";
    }

    function currentBotQuery() {
        var params = new URLSearchParams(window.location.search);
        var botId = params.get("bot_id") || sessionStorage.getItem("selectedBotId");
        if (!botId || !/^[1-9][0-9]*$/.test(String(botId))) {
            return "";
        }
        var query = new URLSearchParams();
        query.set("bot_id", String(botId));
        return "?" + query.toString();
    }

    function injectAccountMenuHostStyle() {
        if (document.getElementById("tenant-account-menu-host-style")) return;
        var style = document.createElement("style");
        style.id = "tenant-account-menu-host-style";
        style.textContent = [
            ".tenant-account-menu-floating{position:fixed;top:24px;right:32px;z-index:900;}",
            "@media (max-width:768px){.tenant-account-menu-floating{top:14px;right:14px;}}",
            "@media (max-width:420px){.tenant-account-menu-floating{right:10px;}}"
        ].join("");
        document.head.appendChild(style);
    }

    class TenantAccountMenu extends HTMLElement {
        constructor() {
            super();
            this.attachShadow({ mode: "open" });
            this.isOpen = false;
            this.platformState = "unknown";
            this.platformPromise = null;
            this.platformController = null;
            this.boundDocumentClick = this.handleDocumentClick.bind(this);
            this.boundKeydown = this.handleKeydown.bind(this);
            this.boundPageHide = this.abortPlatformCheck.bind(this);
        }

        connectedCallback() {
            this.render();
            document.addEventListener("click", this.boundDocumentClick);
            document.addEventListener("keydown", this.boundKeydown);
            window.addEventListener("pagehide", this.boundPageHide);
        }

        disconnectedCallback() {
            document.removeEventListener("click", this.boundDocumentClick);
            document.removeEventListener("keydown", this.boundKeydown);
            window.removeEventListener("pagehide", this.boundPageHide);
            this.abortPlatformCheck();
        }

        render() {
            var user = getStoredUser();
            var displayName = getDisplayName(user);
            var email = getEmail(user);
            this.shadowRoot.innerHTML = "";

            var style = document.createElement("style");
            style.textContent = `
                :host{display:inline-block;position:relative;font-family:'Outfit',system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:var(--text-main,#f8fafc);}
                .account-button{min-height:42px;border:1px solid var(--glass-border,rgba(255,255,255,.12));border-radius:999px;background:rgba(15,23,42,.72);color:inherit;display:inline-flex;align-items:center;gap:10px;padding:6px 10px 6px 7px;cursor:pointer;box-shadow:0 12px 32px rgba(0,0,0,.22);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);transition:border-color .18s,background .18s,box-shadow .18s;}
                .account-button:hover,.account-button:focus-visible{border-color:var(--primary,#3b82f6);background:rgba(59,130,246,.16);box-shadow:0 0 0 3px rgba(59,130,246,.18),0 12px 32px rgba(0,0,0,.28);outline:none;}
                .avatar{width:30px;height:30px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;background:rgba(59,130,246,.16);color:#bfdbfe;border:1px solid rgba(59,130,246,.28);font-size:.78rem;font-weight:700;letter-spacing:.02em;flex:0 0 auto;}
                .label{display:flex;flex-direction:column;align-items:flex-start;line-height:1.1;min-width:0;}
                .name{font-size:.86rem;font-weight:700;max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
                .email{margin-top:2px;font-size:.72rem;color:var(--text-dim,#94a3b8);max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
                .chevron{width:16px;height:16px;color:var(--text-dim,#94a3b8);transition:transform .18s;flex:0 0 auto;}
                .account-button[aria-expanded="true"] .chevron{transform:rotate(180deg);}
                .menu{position:absolute;top:calc(100% + 10px);right:0;min-width:246px;background:rgba(15,23,42,.97);border:1px solid var(--glass-border,rgba(255,255,255,.12));border-radius:18px;padding:8px;box-shadow:0 20px 60px rgba(0,0,0,.46);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);z-index:1000;}
                .menu[hidden]{display:none;}
                .identity{padding:9px 10px 10px;border-bottom:1px solid var(--glass-border,rgba(255,255,255,.1));margin-bottom:6px;}
                .identity-name{font-size:.9rem;font-weight:700;overflow-wrap:anywhere;}
                .identity-email{font-size:.78rem;color:var(--text-dim,#94a3b8);margin-top:3px;overflow-wrap:anywhere;}
                .item{width:100%;display:flex;align-items:center;gap:10px;border:0;background:transparent;color:var(--text-dim,#94a3b8);text-decoration:none;border-radius:12px;padding:10px 11px;font-size:.9rem;font-weight:600;cursor:pointer;text-align:left;font:inherit;}
                .item[hidden]{display:none;}
                .item:hover,.item:focus-visible{background:rgba(255,255,255,.07);color:var(--text-main,#f8fafc);outline:none;}
                .item svg{width:17px;height:17px;flex:0 0 auto;}
                .platform-item{color:#bfdbfe;}
                .divider{height:1px;background:var(--glass-border,rgba(255,255,255,.1));margin:6px 8px;}
                .logout{color:#f87171;}
                .logout:hover,.logout:focus-visible{background:rgba(239,68,68,.12);color:#fecaca;}
                .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0;}
                @media (max-width:640px){.label{display:none}.account-button{padding:6px}.menu{right:0;min-width:min(246px,calc(100vw - 24px));}.email,.name{max-width:190px;}}
            `;

            var button = document.createElement("button");
            button.type = "button";
            button.className = "account-button";
            button.setAttribute("aria-haspopup", "menu");
            button.setAttribute("aria-expanded", "false");
            button.setAttribute("aria-label", "Open account menu");
            button.addEventListener("click", (event) => {
                event.stopPropagation();
                this.toggleMenu();
            });

            var avatar = document.createElement("span");
            avatar.className = "avatar";
            avatar.textContent = getInitials(displayName);
            var label = document.createElement("span");
            label.className = "label";
            var nameNode = document.createElement("span");
            nameNode.className = "name";
            nameNode.textContent = displayName;
            var emailNode = document.createElement("span");
            emailNode.className = "email";
            emailNode.textContent = email || "Signed in";
            label.append(nameNode, emailNode);
            var chevron = document.createElement("span");
            chevron.className = "chevron";
            chevron.setAttribute("aria-hidden", "true");
            chevron.textContent = "⌄";
            button.append(avatar, label, chevron);

            var menu = document.createElement("div");
            menu.className = "menu";
            menu.hidden = true;
            menu.setAttribute("role", "menu");

            var identity = document.createElement("div");
            identity.className = "identity";
            var identityName = document.createElement("div");
            identityName.className = "identity-name";
            identityName.textContent = displayName;
            var identityEmail = document.createElement("div");
            identityEmail.className = "identity-email";
            identityEmail.textContent = email || "Authenticated tenant user";
            identity.append(identityName, identityEmail);

            var profile = this.linkItem("profile.html" + this.profileQuery(), "Profile", "user-circle");
            this.platformLink = this.linkItem("platform-admin.html", "Platform Administration", "shield", "platform-item");
            this.platformLink.hidden = true;
            var divider = document.createElement("div");
            divider.className = "divider";
            var logoutButton = document.createElement("button");
            logoutButton.type = "button";
            logoutButton.className = "item logout";
            logoutButton.setAttribute("role", "menuitem");
            logoutButton.append(this.icon("log-out"), document.createTextNode("Logout"));
            logoutButton.addEventListener("click", () => {
                this.closeMenu();
                this.abortPlatformCheck();
                window.logout();
            });

            menu.append(identity, profile, this.platformLink, divider, logoutButton);
            this.shadowRoot.append(style, button, menu);
            this.button = button;
            this.menu = menu;
            refreshIcons(this.shadowRoot);
        }

        icon(name) {
            var node = document.createElement("i");
            node.setAttribute("data-lucide", name);
            node.setAttribute("aria-hidden", "true");
            return node;
        }

        profileQuery() {
            return this.hasAttribute("preserve-bot-query") ? currentBotQuery() : "";
        }

        linkItem(href, label, iconName, extraClass) {
            var link = document.createElement("a");
            link.href = href;
            link.className = "item" + (extraClass ? " " + extraClass : "");
            link.setAttribute("role", "menuitem");
            link.append(this.icon(iconName), document.createTextNode(label));
            return link;
        }

        toggleMenu() {
            if (this.isOpen) {
                this.closeMenu();
            } else {
                this.openMenu();
            }
        }

        openMenu() {
            this.isOpen = true;
            this.menu.hidden = false;
            this.button.setAttribute("aria-expanded", "true");
            if (this.platformState === "unknown" || this.platformState === "unavailable") {
                this.checkPlatformAccess();
            }
        }

        closeMenu() {
            if (!this.isOpen) return;
            this.isOpen = false;
            this.menu.hidden = true;
            this.button.setAttribute("aria-expanded", "false");
        }

        handleDocumentClick(event) {
            if (!this.isOpen) return;
            var path = typeof event.composedPath === "function" ? event.composedPath() : [];
            if (path.indexOf(this) === -1) {
                this.closeMenu();
            }
        }

        handleKeydown(event) {
            if (!this.isOpen || event.key !== "Escape") return;
            this.closeMenu();
            this.button.focus();
        }

        abortPlatformCheck() {
            if (this.platformController) {
                this.platformController.abort();
                this.platformController = null;
            }
            this.platformPromise = null;
        }

        checkPlatformAccess() {
            if (this.platformPromise) return this.platformPromise;
            var token = sessionStorage.getItem("token");
            if (!token) {
                this.platformState = "denied";
                this.platformLink.hidden = true;
                return Promise.resolve(false);
            }
            this.platformState = "checking";
            this.platformController = new AbortController();
            this.platformPromise = fetch("/api/platform-admin/me", {
                method: "GET",
                headers: { "Authorization": "Bearer " + token },
                signal: this.platformController.signal
            }).then((response) => {
                if (response.status === 200) {
                    this.platformState = "allowed";
                    this.platformLink.hidden = false;
                    return true;
                }
                this.platformLink.hidden = true;
                if (response.status === 401) {
                    this.platformState = "denied";
                    this.closeMenu();
                    if (typeof window.logout === "function") window.logout();
                    return false;
                }
                this.platformState = response.status === 503 ? "unavailable" : "denied";
                return false;
            }).catch((error) => {
                if (error && error.name === "AbortError") {
                    return false;
                }
                this.platformLink.hidden = true;
                this.platformState = "unavailable";
                return false;
            }).finally(() => {
                this.platformPromise = null;
                this.platformController = null;
            });
            return this.platformPromise;
        }
    }

    window.customElements.define("tenant-account-menu", TenantAccountMenu);

    function installTenantAccountMenu() {
        if (document.querySelector("tenant-account-menu")) return;
        if (!document.querySelector("chatbot-sidebar")) return;
        injectAccountMenuHostStyle();
        var host = document.createElement("div");
        host.className = "tenant-account-menu-floating";
        var menu = document.createElement("tenant-account-menu");
        menu.setAttribute("preserve-bot-query", "");
        host.appendChild(menu);
        document.body.appendChild(host);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", installTenantAccountMenu);
    } else {
        installTenantAccountMenu();
    }
})();
