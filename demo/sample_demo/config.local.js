// ============================================================================
// Sample Agent Demo :: user overrides (loaded via <script> tag)
// ----------------------------------------------------------------------------
// This file is loaded synchronously BEFORE `config.js`, so anything assigned
// to `window.DIGIM_CONFIG_USER` here overrides the JSON / DEFAULTS fallback.
//
// **This is the file to edit when you open index.html directly from disk**
// (i.e. `file://…/index.html`) — browsers block XHR to `config.json` from
// `file://` origin, so config.json alone cannot deliver values there.
//
// Editing is safe: it's plain JS, no build step. Just change the values on
// the right-hand side and refresh the page. Any keys you omit fall through
// to config.json (if HTTP-served) or to the embedded DEFAULTS in config.js.
// ============================================================================

window.DIGIM_CONFIG_USER = {
  // FastAPI base URL — no trailing slash. Must be reachable from the browser.
  // Replace with your own backend URL, e.g.:
  //   "http://localhost:8899"                        (uvicorn on same machine)
  //   "http://YOUR_HOST:8899"                        (LAN / VM, HTTP-only)
  //   "https://YOUR_HOST.example.com/api"            (HTTPS reverse proxy)
  BACKEND_URL: "http://localhost:8899",

  // Default identifiers used in the Chat panel form.
  DEFAULT_USER_ID:    "DemoUser",
  DEFAULT_SERVICE_ID: "DEMO",

  // Shown in the Agents dropdown when GET /agents fails or before it returns.
  FALLBACK_AGENTS: [
    { file: "agent_10Sample.json", name: "Sample Agent" }
  ],

  // 1.0 = play recordings at wall-clock speed; 2.0 = 2×; 0.5 = ½.
  PLAYBACK_SPEED: 1.0,

  // If a live API call fails AND a recording is loaded, use the recorded
  // response instead of surfacing the network error to the operator.
  AUTO_FALLBACK_TO_RECORDING: true,

  // Milliseconds between automatic /health polls. 0 = disabled.
  HEALTH_POLL_MS: 0
};
