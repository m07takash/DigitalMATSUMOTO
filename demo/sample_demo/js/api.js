// ============================================================================
// Sample Agent Demo :: API client
// ----------------------------------------------------------------------------
// Thin wrapper around fetch() that:
//   1. Prepends config.BACKEND_URL (with a UI override via localStorage).
//   2. Emits every call to Recorder.captureCall(...) when recording.
//   3. Falls back to Recorder.findMatchingResponse(...) when the network is
//      unreachable AND config.AUTO_FALLBACK_TO_RECORDING is true, so the demo
//      keeps working from a recording when the backend is down.
// ============================================================================

(function () {
  "use strict";

  const cfg = window.DIGIM_CONFIG || {};
  const LS_KEY = "digim_demo_backend_url";

  const Api = {
    // --- URL management -------------------------------------------------
    getBackendUrl() {
      const stored = localStorage.getItem(LS_KEY);
      return (stored || cfg.BACKEND_URL || "").replace(/\/+$/, "");
    },
    setBackendUrl(url) {
      localStorage.setItem(LS_KEY, (url || "").replace(/\/+$/, ""));
    },

    // --- Low-level fetch ------------------------------------------------
    async call(method, path, body) {
      const base = this.getBackendUrl();
      const url = base + path;
      const opts = {
        method,
        headers: { "Content-Type": "application/json" },
      };
      if (body !== undefined && method !== "GET") {
        opts.body = JSON.stringify(body);
      }

      let response = null, status = 0, error = null;
      try {
        const res = await fetch(url, opts);
        status = res.status;
        const text = await res.text();
        try { response = text ? JSON.parse(text) : null; }
        catch { response = text; }
        if (!res.ok) {
          // FastAPI convention: {"detail": "…root cause…"}. Fall back to raw
          // text (or status alone) when the server responded without a body.
          const detail = (response && typeof response === "object" && response.detail)
                            ? response.detail
                            : (typeof response === "string" && response) ? response : "";
          error = detail ? `HTTP ${status}: ${detail}` : `HTTP ${status}`;
        }
      } catch (e) {
        error = e.message || String(e);
      }

      // Auto-fallback: if the network failed AND a recording is loaded AND the
      // operator has opted into it in config, return the recorded response.
      if (error && cfg.AUTO_FALLBACK_TO_RECORDING && window.Recorder) {
        const hit = window.Recorder.findMatchingResponse(method, path);
        if (hit) {
          response = hit.response;
          status = hit.status || 200;
          error = null;
        }
      }

      // Notify recorder (only records when in 'recording' mode).
      if (window.Recorder) {
        window.Recorder.captureCall({
          method, path,
          request: body === undefined ? null : body,
          response, status, error,
        });
      }

      if (error) throw new Error(`${method} ${path}: ${error}`);
      return response;
    },

    // --- multipart: only for /run_multipart when Files are attached. All
    //     other endpoints go through call(). Recorder still captures both.
    async callMultipart(path, jsonData, files) {
      const base = this.getBackendUrl();
      const url = base + path;
      const fd = new FormData();
      fd.append("data", JSON.stringify(jsonData || {}));
      for (const f of (files || [])) fd.append("files", f, f.name);

      let response = null, status = 0, error = null;
      try {
        const res = await fetch(url, { method: "POST", body: fd });
        status = res.status;
        const text = await res.text();
        try { response = text ? JSON.parse(text) : null; } catch { response = text; }
        if (!res.ok) {
          const detail = (response && typeof response === "object" && response.detail)
                          ? response.detail
                          : (typeof response === "string" && response) ? response : "";
          error = detail ? `HTTP ${status}: ${detail}` : `HTTP ${status}`;
        }
      } catch (e) { error = e.message || String(e); }

      // Record & fall-back use the same primitives as the JSON path but with
      // a redacted request body (raw file bytes would bloat the recording).
      const redactedRequest = Object.assign(
        {}, jsonData,
        { _multipart_files: (files || []).map(f => ({ name: f.name, size: f.size, type: f.type })) }
      );
      if (error && cfg.AUTO_FALLBACK_TO_RECORDING && window.Recorder) {
        const hit = window.Recorder.findMatchingResponse("POST", path);
        if (hit) { response = hit.response; status = hit.status || 200; error = null; }
      }
      if (window.Recorder) {
        window.Recorder.captureCall({
          method: "POST", path, request: redactedRequest, response, status, error,
        });
      }
      if (error) throw new Error(`POST ${path}: ${error}`);
      return response;
    },

    // --- Typed helpers matching DigiM_API.py endpoints ------------------
    health()               { return this.call("GET",  "/health"); },
    listSessions(params)   { return this.call("GET",  "/sessions" + qs(params)); },
    getSession(id)         { return this.call("GET",  `/sessions/${encodeURIComponent(id)}`); },
    listAgents()           { return this.call("GET",  "/agents"); },
    listEngines(file)      { return this.call("GET",  `/agents/${encodeURIComponent(file)}/engines`); },
    listWebEngines()       { return this.call("GET",  "/web_search_engines"); },
    feedbackConfig(file)   { return this.call("GET",  `/agents/${encodeURIComponent(file)}/feedback`); },
    submitFeedback(body)   { return this.call("POST", "/feedback", body); },
    run(body)              { return this.call("POST", "/run", body); },
    runMultipart(body, files) { return this.callMultipart("/run_multipart", body, files); },
    // Session Summary — the per-session dossier maintained by the background
    // updater in DigiMatsuExecute_Practice. Read/write settings here; the
    // generated `content` is read-only from the client's perspective.
    listSummaryPresets()   { return this.call("GET",  "/session_summary_presets"); },
    getSessionSummary(id)  { return this.call("GET",  `/sessions/${encodeURIComponent(id)}/summary`); },
    setSessionSummary(id, body) {
      return this.call("POST", `/sessions/${encodeURIComponent(id)}/summary`, body);
    },
    // Legacy alias kept intentionally so demos targeting older backends work.
    runLegacy(body)        { return this.call("POST", "/run_function", body); },
  };

  function qs(params) {
    if (!params) return "";
    const p = new URLSearchParams();
    for (const k of Object.keys(params)) {
      if (params[k] != null && params[k] !== "") p.set(k, params[k]);
    }
    const s = p.toString();
    return s ? "?" + s : "";
  }

  window.Api = Api;
})();
