/* kw-a11y.js - keyboard behaviour the kw-* components assume but cannot
 * provide on their own.
 *
 * Two things, both of which are bugs rather than polish when missing:
 *
 *   kwRadioGroup - a .kw-segment uses roving tabindex, so only the selected
 *   button is reachable by Tab. Without arrow keys a keyboard user reaches
 *   that one button and has no way to choose a different option at all
 *   (WCAG 2.2 SC 2.1.1). conversations.html solved this inline; this is the
 *   same behaviour, extracted so the next page does not write a third copy.
 *
 *   kwDialog - .kw-backdrop is a plain div, so an open dialog lets focus
 *   wander into the page behind it and never returns it to whatever opened
 *   the dialog (SC 2.1.2, SC 2.4.3).
 */

(function (global) {
    "use strict";

    var FOCUSABLE = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled]):not([type=hidden])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        '[tabindex]:not([tabindex="-1"])'
    ].join(",");

    function focusableWithin(root) {
        return Array.prototype.filter.call(root.querySelectorAll(FOCUSABLE), function (el) {
            // offsetParent is null for anything display:none, which is how
            // every hidden panel in these pages is hidden.
            return el.offsetParent !== null || el === document.activeElement;
        });
    }

    /* ── Segmented controls ────────────────────────────────────────── */

    /* Arrow keys move focus between the radios and carry the roving tabindex
       with them. Selection still happens on click, which a button fires for
       Enter and Space on its own, so this adds navigation without taking over
       activation. */
    function kwRadioGroup(root) {
        (root || document).addEventListener("keydown", function (event) {
            var radio = event.target.closest('[role="radio"]');
            if (!radio) return;

            var group = Array.prototype.filter.call(radio.parentElement.children, function (el) {
                return el.getAttribute("role") === "radio";
            });
            var index = group.indexOf(radio);
            var next = null;

            if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                next = group[Math.min(index + 1, group.length - 1)];
            } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                next = group[Math.max(index - 1, 0)];
            } else if (event.key === "Home") {
                next = group[0];
            } else if (event.key === "End") {
                next = group[group.length - 1];
            }

            if (!next) return;
            event.preventDefault();
            group.forEach(function (button) { button.tabIndex = -1; });
            next.tabIndex = 0;
            next.focus();
        });
    }

    /* ── Dialogs ───────────────────────────────────────────────────── */

    var openStack = [];

    function trapTab(event) {
        if (event.key !== "Tab" || !openStack.length) return;

        var current = openStack[openStack.length - 1];
        var items = focusableWithin(current.backdrop);
        if (!items.length) return;

        var first = items[0];
        var last = items[items.length - 1];

        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }

    function open(backdrop, initialFocus) {
        if (!backdrop || backdrop.classList.contains("is-open")) return;

        openStack.push({ backdrop: backdrop, opener: document.activeElement });
        backdrop.classList.add("is-open");

        var target = initialFocus || focusableWithin(backdrop)[0];
        if (target) target.focus();
    }

    function close(backdrop) {
        if (!backdrop || !backdrop.classList.contains("is-open")) return;

        backdrop.classList.remove("is-open");

        var index = -1;
        openStack.forEach(function (entry, i) {
            if (entry.backdrop === backdrop) index = i;
        });
        if (index === -1) return;

        var entry = openStack.splice(index, 1)[0];
        // Returning focus to the control that opened the dialog is what makes
        // a keyboard user's place in the page survive the round trip.
        if (entry.opener && document.contains(entry.opener)) entry.opener.focus();
    }

    function isOpen(backdrop) {
        return !!backdrop && backdrop.classList.contains("is-open");
    }

    document.addEventListener("keydown", trapTab, true);

    global.kwRadioGroup = kwRadioGroup;
    global.kwDialog = { open: open, close: close, isOpen: isOpen };
})(window);
