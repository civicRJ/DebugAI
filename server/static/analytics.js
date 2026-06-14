/* DebugAI analytics — PostHog (self-hosted or cloud).
   Loaded by every page. Only initialises when POSTHOG_KEY is present
   (injected by the server as window.__DEBUGAI_CONFIG__). */
(function () {
  const cfg = window.__DEBUGAI_CONFIG__ || {};
  if (!cfg.posthogKey) return;  // no key → no tracking

  /* Minimal PostHog snippet (no external script tag needed for event calls
     once the full library loads). Load async so it never blocks rendering. */
  !function(t,e){var o,n,p,r;e.__SV||(window.posthog=e,e._i=[],e.init=function(i,s,a){function g(t,e){var o=e.split(".");2==o.length&&(t=t[o[0]],e=o[1]);t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}}(p=t.createElement("script")).type="text/javascript",p.crossOrigin="anonymous",p.async=!0,p.src=s.api_host+"/static/array.js",(r=t.getElementsByTagName("script")[0]).parentNode.insertBefore(p,r);var u=e;for(a!==void 0?u=e[a]=[]:a="posthog",u.people=u.people||[],u.toString=function(t){var e="posthog";return"posthog"!==a&&(e+="."+a),t||(e+=" (stub)"),e},u.people.toString=function(){return u.toString(1)+" (stub)"},o="capture identify alias people.set people.set_once set_config register register_once unregister opt_out_capturing has_opted_out_capturing opt_in_capturing reset isFeatureEnabled onFeatureFlags getFeatureFlag getFeatureFlagPayload reloadFeatureFlags group updateEarlyAccessFeatureEnrollment getEarlyAccessFeatures getActiveMatchingSurveys getSurveys onSessionId".split(" "),n=0;n<o.length;n++)g(u,o[n]);e._i.push([i,s,a])},e.__SV=1)}(document,window.posthog||(window.posthog=[]));

  posthog.init(cfg.posthogKey, {
    api_host: cfg.posthogHost || "https://app.posthog.com",
    person_profiles: "identified_only",
    autocapture: false,       // manual events only — keep it clean
    capture_pageview: true,
    capture_pageleave: false,
  });

  /* Expose helpers for app code to call. */
  window.debugaiTrack = function (event, props) {
    try { posthog.capture(event, props || {}); } catch (_) {}
  };

  window.debugaiIdentify = function (userId, traits) {
    try { posthog.identify(userId, traits || {}); } catch (_) {}
  };
})();
