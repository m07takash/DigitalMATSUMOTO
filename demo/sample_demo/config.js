// ============================================================================
// Digital MATSUMOTO — Sample Demo :: config loader
// ----------------------------------------------------------------------------
// The *source of truth* for demo configuration is `config.json` (pure JSON).
// Edit that file to change backend URL, fallback agents, playback speed, etc.
// This tiny loader is intentionally not the place to change values — it exists
// only because the rest of the demo needs `window.DIGIM_CONFIG` synchronously
// before api.js / app.js are parsed.
//
// Fallback behavior
// -----------------
// If config.json cannot be fetched (typically when the page is opened via
// `file://`, or the file is missing), the embedded DEFAULTS below are used and
// a warning is logged to the console. For editable config in production demos
// always serve via a local HTTP server (see MANUAL.md > "3. 起動方法").
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

  let loaded = null;
  try {
    // Synchronous XHR is deprecated on the main thread but the only way to
    // guarantee DIGIM_CONFIG is ready before api.js / app.js parse. For a demo
    // tool loaded once at boot this trade-off is acceptable; the request is
    // to a same-origin static file and completes in single-digit ms.
    const xhr = new XMLHttpRequest();
    xhr.open("GET", "./config.json", false);
    xhr.send();
    if (xhr.status >= 200 && xhr.status < 300) {
      loaded = JSON.parse(xhr.responseText);
    }
  } catch (e) {
    // file:// or missing file — fall through to DEFAULTS.
  }

  window.DIGIM_CONFIG = Object.assign({}, DEFAULTS, loaded || {});

  if (!loaded) {
    console.warn(
      "[digim-demo] config.json was not loaded — using embedded defaults. " +
      "Open the demo via `python3 -m http.server` (or another HTTP server) " +
      "to make config.json editable at runtime. See MANUAL.md."
    );
  }
})();
