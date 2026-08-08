/*!
 * Website chat widget loader.
 *
 * Install on any website with a single tag:
 *
 *   <script src="https://your-domain/widget.js"
 *           data-chatbot-key="wgt_xxxxxxxx" defer></script>
 *
 * Optional attributes:
 *   data-position="left|right"   override the dashboard setting
 *   data-auto-open="true"        open the panel on page load
 *
 * Everything is injected into a shadow-DOM-free, prefixed namespace so it
 * cannot clash with the host page's styles.
 */
(function () {
  "use strict";

  var NS = "aichat-widget";
  if (window.__aiChatWidgetLoaded) return;
  window.__aiChatWidgetLoaded = true;

  // ── Locate our own <script> tag to read config and the origin ──────
  var script =
    document.currentScript ||
    (function () {
      var all = document.getElementsByTagName("script");
      for (var i = all.length - 1; i >= 0; i--) {
        if (all[i].src && all[i].src.indexOf("widget.js") !== -1) return all[i];
      }
      return null;
    })();

  if (!script) return;

  var publicKey =
    script.getAttribute("data-chatbot-key") ||
    script.getAttribute("data-bot-key");

  if (!publicKey) {
    console.error("[chat-widget] Missing data-chatbot-key attribute.");
    return;
  }

  var baseUrl;
  try {
    baseUrl = new URL(script.src).origin;
  } catch (e) {
    console.error("[chat-widget] Could not resolve widget origin.");
    return;
  }

  var overridePosition = script.getAttribute("data-position");
  var autoOpen = script.getAttribute("data-auto-open") === "true";

  // ── Helpers ───────────────────────────────────────────────────────
  function el(tag, className, styles) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (styles) {
      for (var key in styles) {
        if (Object.prototype.hasOwnProperty.call(styles, key)) {
          node.style[key] = styles[key];
        }
      }
    }
    return node;
  }

  function readableOn(hexColor) {
    var hex = (hexColor || "#4F46E5").replace("#", "");
    if (hex.length === 3) {
      hex = hex[0] + hex[0] + hex[1] + hex[1] + hex[2] + hex[2];
    }
    var r = parseInt(hex.substr(0, 2), 16);
    var g = parseInt(hex.substr(2, 2), 16);
    var b = parseInt(hex.substr(4, 2), 16);
    // Perceived luminance (ITU-R BT.601)
    return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? "#111827" : "#FFFFFF";
  }

  function injectStyles(side) {
    if (document.getElementById(NS + "-styles")) return;

    var css = [
      "." + NS + "-launcher{position:fixed;bottom:20px;" + side + ":20px;",
      "z-index:2147483000;display:flex;align-items:center;gap:8px;",
      "border:0;border-radius:9999px;cursor:pointer;padding:14px;",
      "box-shadow:0 8px 24px rgba(0,0,0,.18);font:600 14px/1 system-ui,",
      "-apple-system,'Segoe UI',Roboto,sans-serif;transition:transform .18s ease,",
      "box-shadow .18s ease;}",
      "." + NS + "-launcher:hover{transform:translateY(-2px);",
      "box-shadow:0 12px 30px rgba(0,0,0,.24);}",
      "." + NS + "-launcher svg{width:24px;height:24px;display:block;}",
      "." + NS + "-launcher-label{padding-right:6px;white-space:nowrap;}",

      "." + NS + "-panel{position:fixed;bottom:92px;" + side + ":20px;",
      "z-index:2147483000;width:400px;height:620px;max-height:calc(100vh - 120px);",
      "border:0;border-radius:16px;overflow:hidden;background:#fff;",
      "box-shadow:0 20px 50px rgba(0,0,0,.25);opacity:0;pointer-events:none;",
      "transform:translateY(12px) scale(.98);",
      "transition:opacity .2s ease,transform .2s ease;}",
      "." + NS + "-panel.is-open{opacity:1;pointer-events:auto;",
      "transform:translateY(0) scale(1);}",
      "." + NS + "-panel iframe{width:100%;height:100%;border:0;display:block;}",

      "@media (max-width:480px){",
      "." + NS + "-panel{width:100%;height:100%;max-height:100%;bottom:0;",
      "left:0;right:0;border-radius:0;}",
      "." + NS + "-panel.is-open ~ ." + NS + "-launcher{display:none;}",
      "}",
    ].join("");

    var style = el("style");
    style.id = NS + "-styles";
    style.appendChild(document.createTextNode(css));
    document.head.appendChild(style);
  }

  var ICON_CHAT =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>' +
    "</svg>";

  var ICON_CLOSE =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round">' +
    '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>' +
    "</svg>";

  // ── Boot ──────────────────────────────────────────────────────────
  function boot(config) {
    var side = overridePosition || config.launcher_position || "right";
    if (side !== "left") side = "right";

    injectStyles(side);

    var accent = config.primary_color || "#4F46E5";
    var onAccent = config.text_color || readableOn(accent);

    var panel = el("div", NS + "-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", config.display_name || "Chat");

    var frame = el("iframe");
    frame.title = config.display_name || "Chat";
    frame.setAttribute("allow", "clipboard-write");
    frame.src = baseUrl + "/widget/" + encodeURIComponent(publicKey) + "?embed=1";
    panel.appendChild(frame);

    var launcher = el("button", NS + "-launcher");
    launcher.type = "button";
    launcher.style.background = accent;
    launcher.style.color = onAccent;
    launcher.setAttribute("aria-label", config.display_name || "Open chat");
    launcher.setAttribute("aria-expanded", "false");

    var label = config.launcher_label || "";
    launcher.innerHTML =
      ICON_CHAT + (label ? '<span class="' + NS + '-launcher-label"></span>' : "");
    if (label) {
      launcher.querySelector("." + NS + "-launcher-label").textContent = label;
    }

    document.body.appendChild(panel);
    document.body.appendChild(launcher);

    var isOpen = false;

    function setOpen(next) {
      isOpen = next;
      panel.classList.toggle("is-open", isOpen);
      launcher.setAttribute("aria-expanded", isOpen ? "true" : "false");
      launcher.innerHTML = isOpen
        ? ICON_CLOSE
        : ICON_CHAT +
          (label ? '<span class="' + NS + '-launcher-label">' + "</span>" : "");
      if (!isOpen && label) {
        launcher.querySelector("." + NS + "-launcher-label").textContent = label;
      }
      if (isOpen) {
        try {
          frame.contentWindow.postMessage({ type: "aichat:focus" }, baseUrl);
        } catch (e) {
          /* cross-origin timing - safe to ignore */
        }
      }
    }

    launcher.addEventListener("click", function () {
      setOpen(!isOpen);
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && isOpen) setOpen(false);
    });

    // The iframe can ask the host page to close the panel.
    window.addEventListener("message", function (event) {
      if (event.origin !== baseUrl) return;
      var data = event.data || {};
      if (data.type === "aichat:close") setOpen(false);
    });

    if (autoOpen) setOpen(true);

    // Small public API for host pages that want programmatic control.
    window.AIChatWidget = {
      open: function () {
        setOpen(true);
      },
      close: function () {
        setOpen(false);
      },
      toggle: function () {
        setOpen(!isOpen);
      },
    };
  }

  function start() {
    fetch(baseUrl + "/api/widget/" + encodeURIComponent(publicKey) + "/config", {
      method: "GET",
      credentials: "omit",
    })
      .then(function (response) {
        if (!response.ok) throw new Error("config " + response.status);
        return response.json();
      })
      .then(function (payload) {
        if (!payload || payload.status !== "success") {
          throw new Error("config unavailable");
        }
        boot(payload.data || {});
      })
      .catch(function (error) {
        console.warn("[chat-widget] Not loaded:", error.message);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
