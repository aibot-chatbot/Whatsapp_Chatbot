
        (function () {
            var params = new URLSearchParams(window.location.search);
            var botId = params.get("bot_id") || sessionStorage.getItem("selectedBotId") || "";
            var target = "behaviour.html?tab=model" + (botId ? "&bot_id=" + encodeURIComponent(botId) : "");
            document.getElementById("go").href = target;
            window.location.replace(target);
        })();
    