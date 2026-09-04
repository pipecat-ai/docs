/**
 * Tracking and consent for the docs site.
 *
 * Mintlify includes every .js file at the root of the docs repo on every page
 * (the same mechanism that loads kapa-widget.js).
 *
 * This file does two things:
 *
 *   1. Loads Google Tag Manager, which loads HubSpot, which paints the cookie
 *      banner. Every tag in the container is gated on the consent that banner
 *      reports, so this is the single entry point for tracking here.
 *
 *   2. Mirrors that consent into local storage, because Mintlify's own telemetry
 *      is not a GTM tag and cannot be gated by the container. Mintlify reads the
 *      key named by `integrations.cookies` in docs.json and disables telemetry
 *      when it is missing, so HubSpot's banner ends up governing Mintlify's
 *      analytics too and visitors only ever see one banner.
 *
 * Leave the "Consent banner" toggle in the Mintlify dashboard OFF. It gates only
 * Mintlify's telemetry, not GTM, so turning it on would show a second banner
 * governing a different subset of the tracking on the page.
 *
 * The production-hostname guard is deliberate: preview deployments stay out of
 * the container, so the container's triggers never need hostname filters.
 */
(function () {
  var GTM_ID = "GTM-NXC7QWT";
  var PRODUCTION_HOSTS = ["docs.pipecat.ai"];

  // Must match integrations.cookies in docs.json.
  var CONSENT_KEY = "daily_analytics_consent";
  var CONSENT_VALUE = "granted";

  if (PRODUCTION_HOSTS.indexOf(window.location.hostname) === -1) return;

  // Mintlify is a single-page app and re-runs custom scripts on navigation.
  if (window.__dailyGtmLoaded) return;
  window.__dailyGtmLoaded = true;

  // HubSpot calls this listener once on load with the stored consent and again
  // on every change, so the mirrored value tracks the banner without polling.
  var _hsp = (window._hsp = window._hsp || []);
  _hsp.push([
    "addPrivacyConsentListener",
    function (consent) {
      var analytics = !!(consent && consent.categories && consent.categories.analytics);
      try {
        if (analytics) {
          window.localStorage.setItem(CONSENT_KEY, CONSENT_VALUE);
        } else {
          window.localStorage.removeItem(CONSENT_KEY);
        }
      } catch (e) {
        // Private mode or blocked storage. Mintlify treats a missing key as
        // "no consent", which is the safe outcome.
      }
    },
  ]);

  window.dataLayer = window.dataLayer || [];
  window.dataLayer.push({ "gtm.start": new Date().getTime(), event: "gtm.js" });

  var script = document.createElement("script");
  script.async = true;
  script.src = "https://www.googletagmanager.com/gtm.js?id=" + GTM_ID;
  document.head.appendChild(script);
})();
