// ============================================================================
// Sample Agent Demo :: Recorder
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

    // --- editing / update -------------------------------------------------
    // Replace an existing recording in the registry (used by the Editor tab
    // after Apply). If the new recording changes its id, both entries end up
    // registered — the caller is responsible for pruning if needed.
    update(id, rec) {
      if (!rec || !rec.id) throw new Error("update: recording must have an id");
      if (id && id !== rec.id) delete registry[id];
      registry[rec.id] = rec;
      this._emit();
    },

    remove(id) {
      if (registry[id]) { delete registry[id]; this._emit(); }
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
      const banner = "// Sample Agent Demo recording. Load via <script src>.\n";
      return banner +
        "window.Recorder && window.Recorder.register(" +
        JSON.stringify(clean, null, 2) +
        ");\n";
    },

    // Pretty JSON serialization for the Editor tab (and for hand-editable
    // recordings that the operator prefers to store as .json rather than .js).
    exportAsJson(rec) {
      return JSON.stringify({ id: rec.id, meta: rec.meta, events: rec.events }, null, 2);
    },

    // Markdown export — a human-readable transcript plus a fenced ```json block
    // that is the source of truth for re-import. Unlike .js, a .md file can't be
    // loaded via <script src>, so it is re-imported through the ⬆ Load button or
    // the Editor's Import (both call parseMarkdown below).
    exportAsMarkdown(rec) {
      const meta = rec.meta || {};
      const events = rec.events || [];
      const lines = [];
      lines.push("<!-- Sample Agent Demo recording (Markdown export).");
      lines.push("     The ```json block at the bottom is the source of truth for re-import");
      lines.push("     via the ⬆ Load button or the Recording Editor's Import. -->");
      lines.push("");
      lines.push(`# ${meta.title || rec.id}`);
      lines.push("");
      lines.push(`- **id**: \`${rec.id}\``);
      if (meta.createdAt)  lines.push(`- **createdAt**: ${meta.createdAt}`);
      if (meta.backendUrl) lines.push(`- **backendUrl**: \`${meta.backendUrl}\``);
      lines.push(`- **events**: ${events.length}`);
      lines.push("");
      lines.push("## Transcript");
      lines.push("");
      lines.push("> Chat turns only. Other API events (health / agents / sessions …) are");
      lines.push("> omitted here for readability but preserved in the data block below.");
      lines.push("");
      let turnNo = 0;
      for (const evt of events) {
        if (evt.type !== "api") continue;
        if (evt.path !== "/run" && evt.path !== "/run_function") continue;
        const q = (evt.request && evt.request.user_input) || "";
        const a = (evt.response && evt.response.response) || "";
        if (!q && !a) continue;
        turnNo++;
        lines.push(`### ${turnNo}.`);
        if (q) { lines.push(`**🧑 User:** ${mdInline(q)}`); lines.push(""); }
        if (a) { lines.push(`**🤖 Agent:** ${mdInline(a)}`); lines.push(""); }
      }
      if (!turnNo) { lines.push("_(No chat turns in this recording.)_"); lines.push(""); }
      lines.push("## Recording data");
      lines.push("");
      lines.push("```json");
      lines.push(this.exportAsJson(rec));
      lines.push("```");
      lines.push("");
      return lines.join("\n");
    },

    // Parse a recording back out of a Markdown export. Returns { id, meta,
    // events }. Reads the first fenced ```json block; if none is present it
    // falls back to treating the whole text as JSON. Throws on failure.
    parseMarkdown(text) {
      const m = String(text).match(/```json\s*([\s\S]*?)```/);
      const payload = m ? m[1] : text;
      const obj = JSON.parse(payload);
      if (!obj || typeof obj !== "object") throw new Error("Markdown has no recording object");
      obj.meta = obj.meta || {};
      obj.events = Array.isArray(obj.events) ? obj.events : [];
      return obj;
    },

    // --- subscription ----------------------------------------------------
    onChange(fn) { listeners.push(fn); },
    _emit() { for (const fn of listeners) { try { fn(this); } catch (e) { console.error(e); } } },
  };

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // Collapse newlines so a multi-line reply stays on one Markdown line in the
  // human-readable transcript (the JSON data block keeps the original text).
  function mdInline(s) { return String(s).replace(/\r?\n+/g, " ").trim(); }

  window.Recorder = Recorder;
})();
