
        const destination = new URL("crm.html", window.location.href);
        const current = new URLSearchParams(window.location.search);
        const selectedBotId = current.get("bot_id") || sessionStorage.getItem("selectedBotId");
        if (selectedBotId) destination.searchParams.set("bot_id", selectedBotId);
        destination.searchParams.set("view", "performance");
        window.location.replace(destination.href);
    