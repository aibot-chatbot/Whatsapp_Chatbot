/* ══════════════════════════════════════════════════════════════════════
   RESILIENT LOAD - shared retry/backoff wrapper for page data loading

   Why this exists: every page loaded its data with a single fetch. One
   transient blip - a dropped connection, a 503 while the server restarted,
   a request that never came back - left a dead-end error that the user
   could only escape by reloading. This retries the failures that are worth
   retrying, keeps the loading state on screen while it does, and only
   surfaces an error once recovery has genuinely failed.

   WHAT IS RETRIED, AND WHAT DEALIBERATELY IS NOT:
     retry     network error, timeout, 408, 425, 429, and any 5xx
     no retry  400, 401, 403, 404, 409, 422 and other 4xx

   The 401 exclusion matters. authenticatedFetch already calls logout() on a
   401, so retrying would hammer the server with requests that cannot
   succeed AND delay the redirect the user is owed. A terminal answer is
   information, not a failure to paper over.
   ══════════════════════════════════════════════════════════════════════ */

(function () {
    "use strict";

    var DEFAULTS = {
        attempts: 4,
        baseDelay: 700,
        maxDelay: 8000,
        timeout: 15000
    };

    var RETRYABLE_STATUS = [408, 425, 429, 500, 502, 503, 504];

    function isRetryableStatus(status) {
        return RETRYABLE_STATUS.indexOf(status) !== -1 || (status >= 500 && status < 600);
    }

    /* Exponential backoff with full jitter. Without jitter every open tab
       retries on the same schedule and a recovering server gets a
       synchronised stampede at exactly the wrong moment. */
    function backoffDelay(attempt, options) {
        var exponential = Math.min(options.baseDelay * Math.pow(2, attempt - 1), options.maxDelay);
        return Math.round(exponential * (0.5 + Math.random() * 0.5));
    }

    function wait(ms) {
        return new Promise(function (resolve) { setTimeout(resolve, ms); });
    }

    /* A request that never returns is worse than one that fails: the page
       spins with no way forward. Every attempt gets its own deadline. */
    function withTimeout(makeRequest, ms) {
        if (typeof AbortController === "undefined") return makeRequest();
        var controller = new AbortController();
        var timer = setTimeout(function () { controller.abort(); }, ms);
        return Promise.resolve(makeRequest(controller.signal)).finally(function () {
            clearTimeout(timer);
        });
    }

    /**
     * Run an authenticated GET until it succeeds or fails terminally.
     *
     * @param {string} url
     * @param {object} [options]
     *   attempts, baseDelay, maxDelay, timeout as above
     *   onRetry(info)  called before each wait, so the page can keep a live
     *                  loading state on screen instead of an error
     * @returns {Promise<{ok:boolean, data:*, status:number, message:string, terminal:boolean}>}
     *   Never throws. Callers get a verdict, not an exception to remember to
     *   catch - the old code had five separate try/catch blocks that each
     *   handled failure slightly differently.
     */
    async function loadJson(url, options) {
        var opts = Object.assign({}, DEFAULTS, options || {});
        var lastMessage = "";
        var lastStatus = 0;

        for (var attempt = 1; attempt <= opts.attempts; attempt += 1) {
            var outcome = await attemptOnce(url, opts);

            if (outcome.ok) return outcome;

            lastMessage = outcome.message;
            lastStatus = outcome.status;

            if (outcome.terminal || attempt === opts.attempts) {
                return {
                    ok: false,
                    data: null,
                    status: lastStatus,
                    message: lastMessage,
                    terminal: outcome.terminal,
                    attempts: attempt
                };
            }

            var delay = backoffDelay(attempt, opts);
            if (typeof opts.onRetry === "function") {
                opts.onRetry({
                    attempt: attempt,
                    of: opts.attempts,
                    delay: delay,
                    status: lastStatus,
                    message: lastMessage
                });
            }
            await wait(delay);
        }

        return {
            ok: false, data: null, status: lastStatus,
            message: lastMessage, terminal: false, attempts: opts.attempts
        };
    }

    async function attemptOnce(url, opts) {
        try {
            var response = await withTimeout(function (signal) {
                var init = signal ? { signal: signal } : {};
                return authenticatedFetch(url, init);
            }, opts.timeout);

            /* A 401 has already triggered logout() inside authenticatedFetch.
               Report it as terminal so nothing retries behind the redirect. */
            if (!response.ok) {
                return {
                    ok: false,
                    data: null,
                    status: response.status,
                    message: await readMessage(response),
                    terminal: !isRetryableStatus(response.status)
                };
            }

            var body = await response.json();

            /* The API answers 200 with status:"error" in places, so a healthy
               HTTP code is not on its own a success. */
            if (!body || body.status !== "success") {
                return {
                    ok: false,
                    data: null,
                    status: response.status,
                    message: (body && body.message) || "The server returned an unexpected response.",
                    // A 200 carrying an error is the server's considered
                    // answer, not a blip. Retrying it just repeats it.
                    terminal: true
                };
            }

            return { ok: true, data: body.data, status: response.status, message: "", terminal: false };
        } catch (error) {
            var aborted = error && (error.name === "AbortError" || error.name === "TimeoutError");
            return {
                ok: false,
                data: null,
                status: 0,
                message: aborted
                    ? "The server took too long to respond."
                    : "We could not reach the server.",
                terminal: false
            };
        }
    }

    async function readMessage(response) {
        try {
            var body = await response.clone().json();
            if (body && body.message) return body.message;
        } catch (_) { /* not JSON, fall through */ }
        return "The server responded with status " + response.status + ".";
    }

    window.resilientLoad = { loadJson: loadJson, isRetryableStatus: isRetryableStatus };
})();
