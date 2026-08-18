/**
 * Control-room motion runtime.
 *
 * Pairs with assets/css/control-room-motion.css. No dependency: the pages
 * that use it are plain HTML/vanilla JS, so an animation library would be
 * a new dependency for work that IntersectionObserver already does.
 *
 * Contract:
 *  - Elements opt in with `class="cr-reveal"`.
 *  - This file stamps `data-motion-ready` on <html>, which is what arms the
 *    hidden start state in CSS. If this script never runs, nothing is ever
 *    hidden, so the page degrades to static content rather than blank.
 *  - Reveal order is DOM order; `--motion-index` carries the stagger step.
 */
(function () {
    "use strict";

    var STAGGER_CAP = 6;      // beyond ~6 steps a stagger reads as lag
    var ROOT_MARGIN = "0px 0px -8% 0px";

    var prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)");

    function revealNow(el) {
        el.classList.add("is-in");
    }

    function init() {
        var targets = document.querySelectorAll(".cr-reveal");
        if (!targets.length) return;

        // Arm the hidden start state only once we know we can undo it.
        document.documentElement.setAttribute("data-motion-ready", "");

        if (prefersReduced.matches || typeof IntersectionObserver !== "function") {
            Array.prototype.forEach.call(targets, revealNow);
            return;
        }

        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting) return;
                revealNow(entry.target);
                observer.unobserve(entry.target);
            });
        }, { rootMargin: ROOT_MARGIN, threshold: 0.05 });

        Array.prototype.forEach.call(targets, function (el, index) {
            if (!el.style.getPropertyValue("--motion-index")) {
                el.style.setProperty("--motion-index", String(Math.min(index, STAGGER_CAP)));
            }
            observer.observe(el);
        });
    }

    /**
     * Write a polled value into an element, flagging it only when it
     * actually changed. Re-triggering the animation needs the class gone
     * for a frame, hence the reflow read.
     *
     * @param {HTMLElement|null} el
     * @param {string} value
     */
    function setValue(el, value) {
        if (!el) return;
        var next = String(value);
        if (el.textContent === next) return;

        el.textContent = next;
        el.classList.remove("cr-swap");
        void el.offsetWidth;
        el.classList.add("cr-swap");
    }

    window.controlRoomMotion = { setValue: setValue };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
