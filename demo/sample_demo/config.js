// ============================================================================
// Digital MATSUMOTO — Sample Demo :: config
// ----------------------------------------------------------------------------
// The single place a demo operator has to touch. Everything here is read once
// on load and reflected into the UI. Persist across reloads is handled by the
// app itself via localStorage overrides (the UI takes precedence at runtime).
// ============================================================================

window.DIGIM_CONFIG = {
  // FastAPI base URL. Trailing slash is stripped by the client.
  //   local dev              : http://localhost:8899
  //   NGINX reverse proxy    : https://your-domain.com/api
  BACKEND_URL: "http://localhost:8899",

  // Default identity used by the Chat panel until the operator overrides it.
  DEFAULT_USER_ID: "DemoUser",
  DEFAULT_SERVICE_ID: "DEMO",

  // If no /agents call has succeeded yet (offline / cold start), populate the
  // agent selector with these files so the demo remains navigable.
  FALLBACK_AGENTS: [
    { file: "agent_10Sample.json", name: "Sample Agent" }
  ],

  // Auto-play speed multiplier during recording playback.
  //   1.0 = wall-clock (default), 2.0 = 2x speed, 0.5 = half speed.
  PLAYBACK_SPEED: 1.0,

  // If true, when the backend is unreachable AND a recording is loaded, the
  // demo silently falls back to recorded responses. If false, network errors
  // surface as UI errors even with a recording loaded.
  AUTO_FALLBACK_TO_RECORDING: true,

  // When true, /health is polled every N ms and the header dot is updated.
  HEALTH_POLL_MS: 0  // 0 = disabled. e.g. 15000 for 15-second heartbeat.
};
