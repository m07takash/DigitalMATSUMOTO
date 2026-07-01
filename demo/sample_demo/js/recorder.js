// ============================================================================
// Digital MATSUMOTO — Sample Demo :: Recorder
// ----------------------------------------------------------------------------
// Captures API calls during a demo session and replays them later, so the demo
// works standalone (no backend) once a recording exists.
//
//   idle       : nothing is being captured. Live network is used.
//   recording  : every apiFetch(...) result is appended to buffer.events.
//   playing    : Recorder drives the UI by iterating a loaded recording's
//                events; apiFetch(...) short-circuits to the recorded response
//                for the current event.
//
// Recordings self-register from recordings/*.js:
//     Recorder.register({ id: "sample_chat", meta: {...}, events: [...] });
// ============================================================================

(function () {
  "use strict";

  const registry = Object.create(null);   // id -> recording
  const listeners = [];                    // change subscribers

  const Recorder = {
    mode: "idle",
    buffer: null,                          // active recording being written to
    activeRecordingId: null,               // id currently selected for playback
    playCursor: 0,                         // next event index during playback
    playAbort: false,

    // --- registration -----------------------------------------------------
    register(rec) {
      if (!rec || !rec.id) {
        console.warn("[recorder] register: missing id", rec);
        return;
      }
      registry[rec.id] = rec;
      this._emit();
    },

    list() {
      return Object.values(registry).map(r => ({
        id: r.id,
        title: r.meta && r.meta.title || r.id,
        events: r.events ? r.events.length : 0,
      }));
    },

    get(id) { return registry[id] || null; },

    // --- recording --------------------------------------------------------
    startRecording(title) {
      this.buffer = {
        id: "rec_" + Date.now(),
        meta: {
          title: title || "Untitled recording",
          createdAt: new Date().toISOString(),
          backendUrl: (window.DIGIM_CONFIG || {}).BACKEND_URL || "",
        },
        events: [],
      };
      this._recordingStart = Date.now();
      this.mode = "recording";
      this._emit();
    },

    stopRecording() {
      if (this.mode !== "recording") return null;
      const rec = this.buffer;
      this.mode = "idle";
      this._emit();
      return rec;
    },

    // Called by api.js after every fetch (success or failure).
    captureCall(entry) {
      if (this.mode !== "recording" || !this.buffer) return;
      const now = Date.now();
      this.buffer.events.push({
        t: now - this._recordingStart,
        type: "api",
        method: entry.method,
        path: entry.path,
        request: entry.request,
        response: entry.response,
        status: entry.status,
        error: entry.error || null,
      });
    },

    // --- playback ---------------------------------------------------------
    // Two playback shapes are supported:
    //
    //   1. Auto-play : Recorder.play(id, handler)
    //      Iterates events sequentially with wall-clock timing (scaled by
    //      config.PLAYBACK_SPEED). The `handler` receives each event and is
    //      responsible for updating the UI. Playback finishes when all events
    //      are dispatched or Recorder.stopPlayback() is called.
    //
    //   2. Passive mock : Recorder.findMatchingResponse(method, path, request)
    //      Called by the API client when auto-fallback fires. Returns the first
    //      unconsumed event whose (method, path) matches, or null.
    //
    async play(id, handler) {
      const rec = registry[id];
      if (!rec) throw new Error(`Recording not found: ${id}`);
      if (this.mode === "playing") return;

      this.activeRecordingId = id;
      this.mode = "playing";
      this.playCursor = 0;
      this.playAbort = false;
      this._emit();

      const speed = (window.DIGIM_CONFIG && window.DIGIM_CONFIG.PLAYBACK_SPEED) || 1.0;
      const events = rec.events || [];
      let prevT = 0;

      for (let i = 0; i < events.length; i++) {
        if (this.playAbort) break;
        const evt = events[i];
        const wait = Math.max(0, (evt.t - prevT) / speed);
        prevT = evt.t;
        if (wait > 0) await sleep(wait);
        this.playCursor = i + 1;
        try { handler && handler(evt, i, events.length); }
        catch (e) { console.error("[recorder] handler failed", e); }
        this._emit();
      }

      this.mode = "idle";
      this._emit();
    },

    stopPlayback() {
      if (this.mode !== "playing") return;
      this.playAbort = true;
    },

    // Passive mock lookup for auto-fallback. First matching (method, path).
    findMatchingResponse(method, path) {
      const rec = registry[this.activeRecordingId];
      if (!rec) return null;
      for (const evt of rec.events || []) {
        if (evt.type === "api" && evt.method === method && evt.path === path) {
          return { response: evt.response, status: evt.status };
        }
      }
      return null;
    },

    // --- export ----------------------------------------------------------
    // Produce a downloadable .js file that self-registers. Preferred format
    // because <script src> works with file:// while fetch() does not.
    exportAsScript(rec) {
      const clean = {
        id: rec.id,
        meta: rec.meta,
        events: rec.events,
      };
      const banner = "// Digital MATSUMOTO demo recording. Load via <script src>.\n";
      return banner +
        "window.Recorder && window.Recorder.register(" +
        JSON.stringify(clean, null, 2) +
        ");\n";
    },

    // --- subscription ----------------------------------------------------
    onChange(fn) { listeners.push(fn); },
    _emit() { for (const fn of listeners) { try { fn(this); } catch (e) { console.error(e); } } },
  };

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  window.Recorder = Recorder;
})();
