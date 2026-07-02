// ============================================================================
// Sample Agent Demo :: Recording Editor
// ----------------------------------------------------------------------------
// The Editor tab lets a demo operator inspect, tweak, and export a recording
// without leaving the browser. Two views on the same data stay in sync:
//
//   • Events table    — quick summary + per-row Delete / Duplicate / ↑ / ↓.
//                       Meta fields (id, title, ...) are inline inputs.
//   • Raw JSON pane   — pretty-printed textarea. Advanced edits go here.
//
// Workflow:
//   1. Pick a recording from the Load dropdown, click "Load into editor".
//   2. Edit rows, meta, or the raw JSON textarea. Click "Sync from JSON →"
//      after typing in the textarea to fold changes back into the table.
//   3. Click "Apply (register)" to update the in-memory registry so playback
//      picks up your edits immediately.
//   4. Click ⬇ .js or ⬇ .json to download the modified recording, then drop
//      it into recordings/ and add a <script> tag in index.html to persist.
// ============================================================================

(function () {
  "use strict";

  const $  = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const EMPTY_EVENT_TEMPLATE = () => ({
    t: 0,
    type: "api",
    method: "GET",
    path: "/health",
    status: 200,
    request: null,
    response: { status: "ok" },
  });

  const state = {
    working: null,   // the recording being edited (deep copy of registry entry)
    origId:  null,   // id it was loaded from (to preserve when the id changes)
  };

  // ------------------------------------------------------------------ boot
  function init() {
    refreshSelect();
    Recorder.onChange(refreshSelect);

    $("#btn-ed-load").addEventListener("click", loadSelected);
    $("#btn-ed-new").addEventListener("click", loadEmpty);
    $("#btn-ed-apply").addEventListener("click", apply);
    $("#btn-ed-add").addEventListener("click", addEvent);
    $("#btn-ed-download-js").addEventListener("click", downloadJs);
    $("#btn-ed-download-json").addEventListener("click", downloadJson);
    $("#btn-ed-download-md").addEventListener("click", downloadMd);
    $("#ed-import").addEventListener("change", importJson);

    $("#btn-ed-json-format").addEventListener("click", () => {
      try {
        const parsed = JSON.parse($("#ed-json").value);
        $("#ed-json").value = JSON.stringify(parsed, null, 2);
        setStatus("Formatted.", "ok");
      } catch (e) { setStatus("Format failed: " + e.message, "err"); }
    });
    $("#btn-ed-json-parse").addEventListener("click", syncFromJson);

    // Meta inputs — write straight into state.working on change.
    ["id", "title", "createdAt", "backend"].forEach(key => {
      const el = $("#ed-" + key);
      el.addEventListener("input", () => {
        if (!state.working) return;
        if (key === "id")            state.working.id = el.value.trim();
        else if (key === "title")    state.working.meta.title = el.value;
        else if (key === "createdAt") state.working.meta.createdAt = el.value;
        else if (key === "backend")  state.working.meta.backendUrl = el.value;
        // meta edits do not need to re-render the table; refresh JSON only.
        renderJson();
      });
    });
  }

  // -------------------------------------------------------- select / load
  function refreshSelect() {
    const sel = $("#ed-select");
    if (!sel) return;
    const prev = sel.value;
    sel.innerHTML = '<option value="">— pick a recording —</option>';
    for (const r of Recorder.list()) {
      const opt = document.createElement("option");
      opt.value = r.id;
      opt.textContent = `${r.title} (${r.events} events)`;
      sel.appendChild(opt);
    }
    if (prev) sel.value = prev;
  }

  function loadSelected() {
    const id = $("#ed-select").value;
    if (!id) { setStatus("Pick a recording first.", "err"); return; }
    const rec = Recorder.get(id);
    if (!rec) { setStatus("Recording not found: " + id, "err"); return; }
    // deep clone so we can edit freely without touching the registry until Apply.
    state.working = JSON.parse(JSON.stringify(rec));
    state.origId = id;
    render();
    setStatus(`Loaded "${rec.meta && rec.meta.title || id}" into editor.`, "ok");
  }

  function loadEmpty() {
    state.working = {
      id: "rec_" + Date.now(),
      meta: {
        title: "Untitled recording",
        createdAt: new Date().toISOString(),
        backendUrl: (window.DIGIM_CONFIG || {}).BACKEND_URL || "",
      },
      events: [],
    };
    state.origId = null;
    render();
    setStatus("New empty recording ready.", "ok");
  }

  // -------------------------------------------------------------- render
  function render() {
    if (!state.working) return;
    renderMeta();
    renderTable();
    renderJson();
  }

  function renderMeta() {
    const w = state.working;
    $("#ed-id").value = w.id || "";
    $("#ed-title").value = (w.meta && w.meta.title) || "";
    $("#ed-createdAt").value = (w.meta && w.meta.createdAt) || "";
    $("#ed-backend").value = (w.meta && w.meta.backendUrl) || "";
  }

  function renderTable() {
    const tbody = $("#ed-table tbody");
    tbody.innerHTML = "";
    const events = state.working.events || [];
    $("#ed-count").textContent = String(events.length);

    let prevT = 0;
    events.forEach((evt, i) => {
      const delta = i === 0 ? evt.t : evt.t - prevT;
      prevT = evt.t;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${delta}</td>
        <td>${esc(evt.method || "")}</td>
        <td>${esc(evt.path || "")}</td>
        <td>${esc(evt.status != null ? String(evt.status) : "")}</td>
        <td class="ed-preview">${esc(previewOf(evt.response))}</td>
        <td class="ed-actions">
          <button data-act="up"   title="Move up">↑</button>
          <button data-act="down" title="Move down">↓</button>
          <button data-act="dup"  title="Duplicate">⧉</button>
          <button data-act="del" class="del" title="Delete">✕</button>
        </td>`;
      tr.querySelectorAll("button").forEach(btn => {
        btn.addEventListener("click", () => onRowAction(i, btn.dataset.act));
      });
      tbody.appendChild(tr);
    });
  }

  function renderJson() {
    $("#ed-json").value = Recorder.exportAsJson(state.working);
  }

  // ------------------------------------------------------ row operations
  function onRowAction(index, act) {
    const evts = state.working.events;
    if (act === "del") {
      evts.splice(index, 1);
    } else if (act === "dup") {
      const copy = JSON.parse(JSON.stringify(evts[index]));
      // Nudge the copy 500ms after the source so playback shows it separately.
      copy.t = (evts[index].t | 0) + 500;
      evts.splice(index + 1, 0, copy);
    } else if (act === "up" && index > 0) {
      const [row] = evts.splice(index, 1);
      evts.splice(index - 1, 0, row);
    } else if (act === "down" && index < evts.length - 1) {
      const [row] = evts.splice(index, 1);
      evts.splice(index + 1, 0, row);
    }
    render();
  }

  function addEvent() {
    if (!state.working) loadEmpty();
    const evts = state.working.events;
    const last = evts.length ? evts[evts.length - 1].t | 0 : 0;
    const tmpl = EMPTY_EVENT_TEMPLATE();
    tmpl.t = last + 1000;
    evts.push(tmpl);
    render();
    setStatus("Added an event template. Edit the row or JSON to customize.", "ok");
  }

  // ---------------------------------------------------------- json bridge
  function syncFromJson() {
    let parsed;
    try {
      parsed = JSON.parse($("#ed-json").value);
    } catch (e) { setStatus("JSON parse failed: " + e.message, "err"); return; }
    if (!parsed || typeof parsed !== "object") {
      setStatus("JSON root must be an object.", "err"); return;
    }
    parsed.meta = parsed.meta || {};
    parsed.events = Array.isArray(parsed.events) ? parsed.events : [];
    state.working = parsed;
    renderMeta();
    renderTable();
    setStatus(`Synced from JSON. ${parsed.events.length} event(s).`, "ok");
  }

  // ------------------------------------------------------ apply / export
  function apply() {
    if (!state.working) { setStatus("Nothing to apply.", "err"); return; }
    if (!state.working.id) { setStatus("Recording id is empty.", "err"); return; }
    try {
      Recorder.update(state.origId, JSON.parse(JSON.stringify(state.working)));
      state.origId = state.working.id;
      setStatus(`Applied. Registry now holds "${state.working.id}".`, "ok");
    } catch (e) { setStatus("Apply failed: " + e.message, "err"); }
  }

  function downloadJs() {
    if (!state.working) return;
    const text = Recorder.exportAsScript(state.working);
    download(text, `${state.working.id}.js`, "application/javascript");
  }

  function downloadJson() {
    if (!state.working) return;
    const text = Recorder.exportAsJson(state.working);
    download(text, `${state.working.id}.json`, "application/json");
  }

  function downloadMd() {
    if (!state.working) return;
    const text = Recorder.exportAsMarkdown(state.working);
    download(text, `${state.working.id}.md`, "text/markdown");
  }

  async function importJson(e) {
    const f = e.target.files[0];
    if (!f) return;
    const text = await f.text();
    try {
      let obj;
      if (f.name.endsWith(".md")) {
        // A .md export carries the recording in a fenced ```json block.
        obj = Recorder.parseMarkdown(text);
      } else if (f.name.endsWith(".json")) {
        obj = JSON.parse(text);
      } else {
        // A demo .js recording is a self-registering snippet. Rather than
        // evaluating it (which would side-effect the registry), extract the
        // object literal and parse it as JSON.
        const m = text.match(/register\s*\(\s*(\{[\s\S]*\})\s*\)\s*;?\s*$/);
        if (!m) throw new Error("Could not locate register(...) payload");
        obj = JSON.parse(m[1]);
      }
      state.working = obj;
      state.origId = null;
      render();
      setStatus(`Imported from ${f.name}. Not yet registered — click Apply.`, "ok");
    } catch (err) { setStatus("Import failed: " + err.message, "err"); }
    e.target.value = "";
  }

  // -------------------------------------------------------------- utils
  function download(text, filename, mime) {
    const blob = new Blob([text], { type: mime });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
  }

  function setStatus(msg, kind) {
    const el = $("#ed-status");
    el.textContent = msg;
    el.className = "ed-status" + (kind ? " " + kind : "");
  }

  function previewOf(v) {
    if (v == null) return "";
    if (typeof v === "string") return v.length > 80 ? v.slice(0, 77) + "..." : v;
    try { const s = JSON.stringify(v); return s.length > 80 ? s.slice(0, 77) + "..." : s; }
    catch { return String(v); }
  }

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
