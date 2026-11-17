
        (function () {
            var destination = new URL("support.html", window.location.href);
            var current = new URLSearchParams(window.location.search);
            var botId = current.get("bot_id") || sessionStorage.getItem("selectedBotId") || "";
            if (botId) destination.searchParams.set("bot_id", botId);
            document.getElementById("training-fallback").href = destination.href;
            window.location.replace(destination.href);
        }());
    