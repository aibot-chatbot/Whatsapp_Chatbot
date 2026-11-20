
        (function () {
            var params = new URLSearchParams(window.location.search);
            var botId = params.get("bot_id") || sessionStorage.getItem("selectedBotId") || "";
            var target = "behaviour.html?tab=test" + (botId ? "&bot_id=" + encodeURIComponent(botId) : "");
            if (params.get("setup") === "1") target += "&setup=1";
            document.getElementById("go").href = target;
            window.location.replace(target);
        })();
    