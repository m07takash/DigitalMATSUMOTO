// ============================================================================
// Sample Agent Demo :: config loader
// ----------------------------------------------------------------------------
// Loads DIGIM_CONFIG from three sources, later ones winning:
//   1. Embedded DEFAULTS (below)          — always applies
//   2. `config.json` via XHR              — HTTP-served demos only
//   3. `window.DIGIM_CONFIG_USER`         — set in config.local.js
//
// **file:// opening is fully supported.** Browsers block XHR to config.json
// from a `file://` origin, so config.json alone does not work when the user
// double-clicks index.html. `config.local.js` is loaded via a plain <script>
// tag (which works from file://) and takes highest priority.
//
// Config schema
// -------------
//   BACKEND_URL                : string   FastAPI base URL (no trailing slash)
//   DEFAULT_USER_ID            : string   Chat panel default USER_ID
//   DEFAULT_SERVICE_ID         : string   Chat panel default SERVICE_ID
//   FALLBACK_AGENTS            : array    Used when GET /agents fails
//                                          [{ file: "...", name: "..." }, ...]
//   PLAYBACK_SPEED             : number   1.0 = wall-clock; 2.0 = 2x; 0.5 = ½
//   AUTO_FALLBACK_TO_RECORDING : boolean  Reply from recording on network fail
//   HEALTH_POLL_MS             : number   0 = disabled; e.g. 15000 = 15s poll
// ============================================================================

(function () {
  "use strict";

  const DEFAULTS = {
    BACKEND_URL: "http://localhost:8899",
    DEFAULT_USER_ID: "DemoUser",
    DEFAULT_SERVICE_ID: "DEMO",
    FALLBACK_AGENTS: [
      { file: "agent_10Sample.json", name: "Sample Agent" }
    ],
    PLAYBACK_SPEED: 1.0,
    AUTO_FALLBACK_TO_RECORDING: true,
    HEALTH_POLL_MS: 0
  };

  // Layer 2: config.json — only loadable when the page is served over HTTP.
  // From file:// Chrome/Edge/Safari block the XHR (Firefox allows it). We
  // silently fall through in that case; config.local.js is the intended path.
  let loadedJson = null;
  try {
    const xhr = new XMLHttpRequest();
    xhr.open("GET", "./config.json", false);
    xhr.send();
    if (xhr.status >= 200 && xhr.status < 300) {
      loadedJson = JSON.parse(xhr.responseText);
    }
  } catch (e) {
    // file:// or missing file — layered lookup below still resolves via
    // config.local.js / DEFAULTS, so no warning is needed on this path.
  }

  // Layer 3: config.local.js (highest priority). Populated by the user editing
  // `config.local.js`, which is loaded via a normal <script> tag from
  // index.html — that works everywhere including file://.
  const userOverride = (typeof window.DIGIM_CONFIG_USER === "object"
                          && window.DIGIM_CONFIG_USER)
                          ? window.DIGIM_CONFIG_USER : null;

  window.DIGIM_CONFIG = Object.assign(
    {}, DEFAULTS, loadedJson || {}, userOverride || {}
  );

  // Diagnostics — surface the layered lookup in the console so operators can
  // see which source wound up providing each value.
  const sources = [];
  sources.push("DEFAULTS");
  if (loadedJson)   sources.push("config.json");
  if (userOverride) sources.push("config.local.js");
  console.info(
    "[digim-demo] DIGIM_CONFIG resolved from:", sources.join(" → "),
    "\n  BACKEND_URL =", window.DIGIM_CONFIG.BACKEND_URL
  );
  if (!loadedJson && !userOverride) {
    console.warn(
      "[digim-demo] Only embedded DEFAULTS are in effect. If you're opening " +
      "index.html directly from disk, edit config.local.js to set your " +
      "BACKEND_URL. If serving over HTTP, edit config.json."
    );
  }
})();
