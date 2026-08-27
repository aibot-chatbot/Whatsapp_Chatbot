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

    /**
     * Count an element's text from zero up to a target number.
     *
     * The element must ALREADY contain the final formatted string. We read
     * the numeric target from a data attribute and restore that exact
     * string on the last frame, so currency symbols, separators and units
     * stay owned by the page and are never re-implemented here.
     *
     * Under reduced motion, or for a non-finite target, the markup is left
     * exactly as it was.
     *
     * @param {HTMLElement|null} el
     * @param {number} target
     * @param {string} finalText
     */
    function countUp(el, target, finalText) {
        var DURATION = 560;

        if (!el || !isFinite(target)) return;
        if (prefersReduced.matches) {
            el.textContent = finalText;
            return;
        }

        var decimals = (String(finalText).split(".")[1] || "").replace(/[^0-9]/g, "").length;
        var start = null;

        function frame(now) {
            if (start === null) start = now;
            var t = Math.min((now - start) / DURATION, 1);
            /* Cubic ease-out, the same deceleration family as
               --motion-ease-out, so a counting number and the meter beside
               it settle together rather than fighting each other. */
            var eased = 1 - Math.pow(1 - t, 3);

            if (t >= 1) {
                el.textContent = finalText;
                return;
            }
            el.textContent = (target * eased).toFixed(decimals);
            requestAnimationFrame(frame);
        }

        el.textContent = (0).toFixed(decimals);
        requestAnimationFrame(frame);
    }

    /**
     * Run every [data-countup] inside a container once. The attribute holds
     * the numeric target; the element's existing text is the truth we count
     * toward and restore verbatim.
     *
     * @param {ParentNode} [root]
     */
    function countUpAll(root) {
        var nodes = (root || document).querySelectorAll("[data-countup]");
        for (var i = 0; i < nodes.length; i += 1) {
            var el = nodes[i];
            if (el.hasAttribute("data-countup-done")) continue;
            el.setAttribute("data-countup-done", "");
            countUp(el, parseFloat(el.getAttribute("data-countup")), el.textContent);
        }
    }

    window.controlRoomMotion = {
        setValue: setValue,
        countUp: countUp,
        countUpAll: countUpAll
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
