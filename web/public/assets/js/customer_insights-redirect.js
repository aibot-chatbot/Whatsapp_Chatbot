
        requireLogin();

        (function redirectToCrmAiSignals() {
            if (!sessionStorage.getItem("token")) {
                return;
            }

            let user = null;
            try {
                user = JSON.parse(sessionStorage.getItem("user") || "null");
            } catch (_) {
                user = null;
            }

            const role = String(user && user.role || "").toLowerCase();
            if (role !== "owner" && role !== "admin") {
                sessionStorage.setItem("redirect_message", "You do not have permission to access that page.");
                window.location.replace("bots.html");
                return;
            }

            const urlParams = new URLSearchParams(window.location.search);
            const urlBotId = parsePositiveSafeInteger(String(urlParams.get("bot_id") || ""));
            const storedBotId = parsePositiveSafeInteger(String(sessionStorage.getItem("selectedBotId") || ""));
            const selectedBotId = urlBotId || storedBotId;

            if (!selectedBotId) {
                clearChatbotContext();
                window.location.replace("bots.html");
                return;
            }

            sessionStorage.setItem("selectedBotId", String(selectedBotId));
            const destination = new URL("crm.html", window.location.href);
            destination.search = "";
            destination.searchParams.set("bot_id", String(selectedBotId));
            destination.searchParams.set("tab", "ai-signals");
            window.location.replace(destination.href);
        })();
    