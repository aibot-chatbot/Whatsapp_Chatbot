/**
 * turnstile-guard.js - renders the Cloudflare Turnstile widget on the four
 * public auth forms and attaches its token to the requests they send.
 *
 * Why this lives outside the pages' inline <script> blocks: the auth pages are
 * pinned by tests that match their script region as source text, so the token
 * is attached here by wrapping window.fetch instead of by editing four submit
 * handlers. The pages contribute one empty <div class="cf-turnstile"> slot and
 * one <script src> line; nothing else about them changes.
 *
 * FAIL OPEN IN THE BROWSER, FAIL CLOSED ON THE SERVER. Nothing here decides
 * whether a request is allowed - app/services/turnstile_service.py does. If
 * /api/auth/turnstile-config says Turnstile is off, or Cloudflare's script is
 * blocked, or any step throws, this file does nothing at all and window.fetch
 * is left untouched, so the sign-in form keeps working exactly as before.
 *
 * The site key is public and arrives at runtime from the config endpoint, the
 * same shape the Google client id uses. No key is ever written into the page.
 */

(function () {
  'use strict';

  var CONFIG_ENDPOINT = '/api/auth/turnstile-config';

  /* Cloudflare's widget API. render=explicit because the site key is not known
     until the config call returns, so auto-render on a data-sitekey attribute
     is not available to us. */
  var WIDGET_API = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';

  /* Must equal TOKEN_FIELD in app/services/turnstile_service.py. */
  var TOKEN_FIELD = 'cf-turnstile-response';

  /* Only these four endpoints are guarded server side. Anything else - the OTP
     steps, the Google exchange, the invite lookup - is left alone, because
     spending a single-use token on them would burn the one the real submit
     needs. */
  var GUARDED_PATHS = [
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/forgot-password',
    '/api/invites/accept'
  ];

  var widgetIds = [];
  var currentToken = '';

  function isGuardedRequest(input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var method = ((init && init.method) || (input && input.method) || 'GET').toUpperCase();
    if (method !== 'POST') return false;
    var path = url.split('?')[0].split('#')[0];
    for (var i = 0; i < GUARDED_PATHS.length; i++) {
      var offset = path.length - GUARDED_PATHS[i].length;
      if (offset >= 0 && path.slice(offset) === GUARDED_PATHS[i]) return true;
    }
    return false;
  }

  /** Return a copy of init whose JSON body also carries the token. */
  function withToken(init) {
    if (!currentToken) return init;
    if (!init || typeof init.body !== 'string') return init;
    var body;
    try {
      body = JSON.parse(init.body);
    } catch (err) {
      return init;
    }
    if (!body || typeof body !== 'object' || Object.prototype.toString.call(body) === '[object Array]') {
      return init;
    }
    body[TOKEN_FIELD] = currentToken;
    var copy = {};
    for (var key in init) {
      if (Object.prototype.hasOwnProperty.call(init, key)) copy[key] = init[key];
    }
    copy.body = JSON.stringify(body);
    return copy;
  }

  /* A solved token is single use: Cloudflare answers "timeout-or-duplicate" the
     second time. After every guarded attempt the widget is reset so a retry -
     a wrong password, a taken email - has a fresh one to send. */
  function resetWidgets() {
    currentToken = '';
    try {
      for (var i = 0; i < widgetIds.length; i++) {
        window.turnstile.reset(widgetIds[i]);
      }
    } catch (err) {
      /* nothing to reset */
    }
  }

  function installFetchWrapper() {
    if (typeof window.fetch !== 'function') return;
    var nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      var guarded = false;
      var options = init;
      try {
        guarded = isGuardedRequest(input, init);
        if (guarded) options = withToken(init);
      } catch (err) {
        return nativeFetch(input, init);
      }
      if (!guarded) return nativeFetch(input, options);
      return nativeFetch(input, options).then(function (response) {
        resetWidgets();
        return response;
      }, function (error) {
        resetWidgets();
        throw error;
      });
    };
  }

  function renderWidget(element, siteKey) {
    try {
      if (!window.turnstile || typeof window.turnstile.render !== 'function') return;
      var id = window.turnstile.render(element, {
        sitekey: siteKey,
        callback: function (token) { currentToken = token; },
        'expired-callback': function () { currentToken = ''; },
        'error-callback': function () { currentToken = ''; }
      });
      if (id !== undefined && id !== null) {
        widgetIds.push(id);
        /* Only spend layout on a slot that actually holds a widget; while
           Turnstile is off the empty div must take no room at all. */
        element.style.marginBottom = '16px';
      }
    } catch (err) {
      /* An unrendered widget means no token, which the server refuses with a
         clear message. Never let this throw into the page. */
    }
  }

  /* accept-invite.html keeps its form hidden until the invite validates, and a
     widget rendered inside a display:none container can fail to run its
     challenge. Rendering on first visibility covers that without the page
     having to tell us anything. */
  function mountWhenVisible(element, siteKey) {
    try {
      if (typeof IntersectionObserver !== 'function') {
        renderWidget(element, siteKey);
        return;
      }
      var observer = new IntersectionObserver(function (entries) {
        for (var i = 0; i < entries.length; i++) {
          if (entries[i].isIntersecting) {
            observer.disconnect();
            renderWidget(element, siteKey);
            return;
          }
        }
      });
      observer.observe(element);
    } catch (err) {
      renderWidget(element, siteKey);
    }
  }

  function start(siteKey) {
    try {
      var slots = document.querySelectorAll('.cf-turnstile');
      if (!slots.length) return;
      installFetchWrapper();
      for (var i = 0; i < slots.length; i++) {
        mountWhenVisible(slots[i], siteKey);
      }
    } catch (err) {
      /* fail open */
    }
  }

  function loadWidgetApi(siteKey) {
    try {
      var script = document.createElement('script');
      script.src = WIDGET_API;
      script.async = true;
      script.defer = true;
      script.onload = function () { start(siteKey); };
      script.onerror = function () { /* blocked CDN: no widget, no wrapper */ };
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
          if (data && data.site_key) loadWidgetApi(data.site_key);
        })
        .catch(function () { /* Turnstile off or unreachable: change nothing */ });
    } catch (err) {
      /* fail open */
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadConfig);
  } else {
    loadConfig();
  }
})();
