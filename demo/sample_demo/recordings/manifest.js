// ============================================================================
// Sample Agent Demo :: Recording manifest
// ----------------------------------------------------------------------------
// This file is loaded before any recording so it can set defaults, and to give
// operators a single, obvious place to enumerate the recordings that ship with
// this mockup. Each recording file self-registers, so listing here is optional
// but strongly recommended for discoverability.
//
// To add a new recording:
//   1. Save the exported .js file into this folder.
//   2. Append a new <script src="recordings/your_file.js"></script> to
//      index.html (search for "sample_chat.js").
//   3. Optionally document it below.
//
//   Bundled recordings
//   ------------------
//   sample_chat.js   — 3-turn chat with the Sample Agent, plus a session list
//                      and health check. Good for smoke-testing the UI.
// ============================================================================

window.DIGIM_RECORDING_INDEX = {
  bundled: [
    "sample_chat"
  ]
};
