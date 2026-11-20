/**
 * auth-sentry.js - hardened, credential-aware error reporting for the auth
 * pages (login, register, forgot, verify-email).
 *
 * Mirrors the server policy in app/observability.py: an ALLOWLIST is built from
 * scratch for every event, exception values are always "[redacted]", stack
 * frames keep only code locations, and no breadcrumbs, traces, profiles, PII or
 * session replay are ever collected.
 *
 * FAIL OPEN is the first requirement. A blocked CDN, a missing DSN, or any
 * thrown error must leave the sign-in form fully working. Observability must
 * never be able to break authentication, so every step is wrapped.
 */

(function () {
  'use strict';

  var CONFIG_ENDPOINT = '/api/auth/sentry-config';

  /* Sentry's own browser bundle, pinned with the hash Sentry publishes for this
     exact version (release-registry, checked against the downloaded bytes).
     A wrong hash makes the browser refuse the script, which under fail-open
     looks identical to "Sentry is simply not reporting": when you bump the
     version, take the new published hash - do not guess one. */
  var SENTRY_CDN = 'https://browser.sentry-cdn.com/8.55.0/bundle.min.js';
  var SENTRY_SRI = 'sha384-BlRl+vkcjdIA/AKRb8zWtiqlVVXepUsSv0+vho7ZMUTsNudEyQjGUKo9W86Hc1EC';

  /* Integration allowlist, by Sentry integration name.
     GlobalHandlers is what actually hooks window.onerror / unhandledrejection -
     without it Sentry initialises successfully and then reports nothing at all.
     Everything absent from this list is dropped, including Breadcrumbs,
     BrowserApiErrors, HttpContext (page URL + headers) and Replay. */
  var ALLOWED_INTEGRATIONS = ['GlobalHandlers', 'Dedupe', 'FunctionToString'];

  /* Defence in depth, applied after the allowlist. Every pattern is global:
     without /g only the first match is replaced, so a string carrying two OTPs
     would redact one and transmit the other. */
  var REDACTIONS = [
    [/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g, '[redacted-email]'],
    [/eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*/g, '[redacted-jwt]'],
    [/Bearer\s+[A-Za-z0-9._-]+/gi, 'Bearer [redacted]'],
    [/\b\d{4,8}\b/g, '[redacted-otp]']
  ];

  var ALLOWED_TOP_LEVEL = [
    'event_id', 'timestamp', 'platform', 'level', 'release', 'environment'
  ];

  var ALLOWED_FRAME_KEYS = ['function', 'module', 'lineno', 'in_app'];

  var sentryReady = false;

  function stripUrl(value) {
    if (typeof value !== 'string') return value;
    return value.split('?')[0].split('#')[0];
  }

  function redact(value) {
    if (typeof value !== 'string') return value;
    var out = value;
    for (var i = 0; i < REDACTIONS.length; i++) {
      out = out.replace(REDACTIONS[i][0], REDACTIONS[i][1]);
    }
    return out;
  }

  function safeFrame(frame) {
    var out = {};
    for (var i = 0; i < ALLOWED_FRAME_KEYS.length; i++) {
      var key = ALLOWED_FRAME_KEYS[i];
      if (key in frame) out[key] = redact(frame[key]);
    }
    if ('filename' in frame) {
      // Query strings on a bundle URL can carry cache-busting tokens.
      out.filename = redact(stripUrl(frame.filename));
    }
    return out;
  }

  /**
   * Build a NEW event containing only permitted fields. The incoming event is
   * never mutated and never partially reused - anything not copied here simply
   * does not leave the browser.
   */
  function beforeSend(event) {
    try {
      var safe = {};
      for (var i = 0; i < ALLOWED_TOP_LEVEL.length; i++) {
        var key = ALLOWED_TOP_LEVEL[i];
        if (key in event) safe[key] = redact(event[key]);
      }

      var incoming = (event.exception && event.exception.values) || [];
      var values = [];
      for (var j = 0; j < incoming.length; j++) {
        var exc = incoming[j];
        var item = { type: exc.type || 'Error', value: '[redacted]' };
        if (exc.stacktrace && exc.stacktrace.frames) {
          item.stacktrace = { frames: exc.stacktrace.frames.map(safeFrame) };
        }
        var mechanism = exc.mechanism || {};
        item.mechanism = {};
        if ('type' in mechanism) item.mechanism.type = mechanism.type;
        if ('handled' in mechanism) item.mechanism.handled = mechanism.handled;
        values.push(item);
      }

      if (values.length) {
        safe.exception = { values: values };
      } else {
        safe.message = 'Client error (message redacted)';
      }
      return safe;
    } catch (err) {
      // Any doubt at all and the event is dropped rather than sent unscrubbed.
      return null;
    }
  }

  /* Breadcrumbs on a login page are a credential-leak vector: dom and ui.input
     record what was typed and clicked, fetch/xhr record request URLs. Drop the
     lot. maxBreadcrumbs is 0 as well, so this is belt and braces. */
  function beforeBreadcrumb() {
    return null;
  }

  function pickIntegrations(defaults) {
    try {
      return defaults.filter(function (integration) {
        return ALLOWED_INTEGRATIONS.indexOf(integration.name) !== -1;
      });
    } catch (err) {
      return [];
    }
  }

  function start(config) {
    try {
      if (!window.Sentry || typeof window.Sentry.init !== 'function') return;
      window.Sentry.init({
        dsn: config.dsn,
        environment: config.environment || 'production',
        release: config.release || undefined,
        integrations: pickIntegrations,
        sendDefaultPii: false,
        attachStacktrace: true,
        maxBreadcrumbs: 0,
        tracesSampleRate: 0.0,
        profilesSampleRate: 0.0,
        replaysSessionSampleRate: 0.0,
        replaysOnErrorSampleRate: 0.0,
        autoSessionTracking: false,
        sendClientReports: false,
        beforeSend: beforeSend,
        beforeBreadcrumb: beforeBreadcrumb
      });
      sentryReady = true;
    } catch (err) {
      sentryReady = false;
    }
  }

  function loadSdk(config) {
    try {
      var script = document.createElement('script');
      script.src = SENTRY_CDN;
      script.integrity = SENTRY_SRI;
      script.async = true;
      script.crossOrigin = 'anonymous';
      script.onload = function () { start(config); };
      script.onerror = function () { /* blocked CDN: stay silent, stay working */ };
      document.head.appendChild(script);
    } catch (err) {
      /* fail open */
    }
  }

  function loadConfig() {
    try {
      if (typeof fetch !== 'function') return;
      fetch(CONFIG_ENDPOINT, { credentials: 'same-origin' })
        .then(function (res) { return res.ok ? res.json() : null; })
        .then(function (payload) {
          var data = payload && payload.data;
          if (data && data.dsn) loadSdk(data);
        })
        .catch(function () { /* fail open */ });
    } catch (err) {
      /* fail open */
    }
  }

  window.AuthSentry = {
    isReady: function () { return sentryReady; },
    captureException: function (err) {
      try {
        if (sentryReady && window.Sentry) window.Sentry.captureException(err);
      } catch (e) { /* fail open */ }
    },
    /* Pure, side-effect-free scrubbing functions, exposed so the redaction
       rules can be exercised by a test without a browser. Safe to expose: they
       only ever remove information. */
    _scrub: { redact: redact, stripUrl: stripUrl, beforeSend: beforeSend }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadConfig);
  } else {
    loadConfig();
  }
})();
