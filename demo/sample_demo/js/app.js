// ============================================================================
// Sample Agent Demo :: App
// ----------------------------------------------------------------------------
// UI wiring only. All network access goes through window.Api, all recording
// state lives in window.Recorder. Keep this file the "boring glue" layer so
// designers can edit HTML/CSS/js/pages/* without touching plumbing.
// ============================================================================

(function () {
  "use strict";

  const cfg = window.DIGIM_CONFIG || {};
  const $  = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  // ---------- Header: backend URL & health ------------------------------
  const backendInput = $("#backend-url");
  backendInput.value = Api.getBackendUrl() || cfg.BACKEND_URL || "";
  backendInput.addEventListener("change", () => {
    Api.setBackendUrl(backendInput.value);
    setStatus(`Backend set to ${Api.getBackendUrl()}`);
  });

  $("#btn-health").addEventListener("click", async () => {
    const dot = $("#health-dot");
    dot.className = "dot dot-unknown";
    try {
      const r = await Api.health();
      dot.className = "dot dot-ok";
      dot.title = JSON.stringify(r);
      setStatus("Backend healthy.");
    } catch (e) {
      dot.className = "dot dot-bad";
      dot.title = e.message;
      setStatus("Backend unreachable: " + e.message);
    }
  });

  if (cfg.HEALTH_POLL_MS && cfg.HEALTH_POLL_MS > 0) {
    setInterval(() => $("#btn-health").click(), cfg.HEALTH_POLL_MS);
  }

  // ---------- Tabs -------------------------------------------------------
  $$(".tab").forEach(t => {
    t.addEventListener("click", () => {
      const name = t.dataset.tab;
      $$(".tab").forEach(x => x.classList.toggle("active", x === t));
      $$(".panel").forEach(p => p.classList.toggle("active", p.dataset.panel === name));
    });
  });

  // ---------- Agent selector (shared across panels) --------------------
  async function loadAgents() {
    let agents;
    try {
      const r = await Api.listAgents();
      agents = r.agents || [];
    } catch (e) {
      agents = (cfg.FALLBACK_AGENTS || []).map(a => ({ file: a.file, agent_name: a.name }));
      setStatus("Using fallback agent list (backend unreachable).");
    }
    // FastAPI returns agents keyed by UPPERCASE `FILE`/`AGENT` (DigiM_API.py's
    // `list_agents` builds each row from the on-disk JSON headers). Older /
    // fallback data uses lowercase `file`/`agent_file`/`name`, so accept both
    // shapes when normalising.
    const _fileOf = a => a.FILE || a.file || a.agent_file || "";
    const _nameOf = a => a.AGENT || a.agent_name || a.name || "";
    for (const sel of ["#chat-agent", "#fb-agent"]) {
      const el = $(sel); if (!el) continue;
      el.innerHTML = "";
      for (const a of agents) {
        const opt = document.createElement("option");
        opt.value = _fileOf(a);
        opt.textContent = `${opt.value} — ${_nameOf(a)}`;
        el.appendChild(opt);
      }
    }
    // Render agents table too.
    const tbody = $("#agents-table tbody");
    if (tbody) {
      tbody.innerHTML = "";
      for (const a of agents) {
        const tr = document.createElement("tr");
        tr.dataset.clickable = "1";
        tr.innerHTML = `<td>${esc(_fileOf(a))}</td>` +
                       `<td>${esc(_nameOf(a))}</td>` +
                       `<td>${esc(a.description || a.DESCRIPTION || "")}</td>`;
        tr.addEventListener("click", async () => {
          $$("#agents-table tr").forEach(r => r.classList.remove("selected"));
          tr.classList.add("selected");
          try {
            const eng = await Api.listEngines(_fileOf(a));
            $("#engines-detail").textContent = JSON.stringify(eng, null, 2);
          } catch (e) {
            $("#engines-detail").textContent = "Error: " + e.message;
          }
        });
        tbody.appendChild(tr);
      }
    }
    // Refresh engine selector for the chat panel.
    onChatAgentChanged();
  }
  async function onChatAgentChanged() {
    const file = $("#chat-agent").value;
    if (!file) return;
    try {
      const r = await Api.listEngines(file);
      const engSel = $("#chat-engine");
      engSel.innerHTML = "";
      const engines = (r.LLM && r.LLM.engines) || [];
      const def     = (r.LLM && r.LLM.default)  || "";
      for (const e of engines) {
        const opt = document.createElement("option");
        opt.value = e; opt.textContent = e;
        if (e === def) opt.selected = true;
        engSel.appendChild(opt);
      }
    } catch (e) {
      // silent — chat can still fire with default engine
    }
  }
  $("#chat-agent").addEventListener("change", onChatAgentChanged);
  $("#btn-agents-load").addEventListener("click", loadAgents);

  // ---------- Chat -------------------------------------------------------
  const chatLog = $("#chat-log");
  // Files staged for the next send. Cleared after a successful send.
  const chatAttachments = [];
  // Store references keyed by DOM element so the click handler can pull
  // them without stashing anything on the element itself (which serializes
  // poorly and can be large).
  const bubbleRefs = new WeakMap();

  $("#btn-send").addEventListener("click", sendChat);
  $("#chat-input").addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) sendChat();
  });

  // Attachment picker
  $("#chat-files").addEventListener("change", e => {
    for (const f of Array.from(e.target.files || [])) chatAttachments.push(f);
    e.target.value = "";
    renderAttachmentChips();
  });

  function renderAttachmentChips() {
    const list = $("#chat-files-list");
    list.innerHTML = "";
    chatAttachments.forEach((f, i) => {
      const chip = document.createElement("span");
      chip.className = "chat-file-chip";
      chip.innerHTML = `📄 <span class="fname"></span>
                       <span class="fsize"></span>
                       <button class="rm" title="Remove">×</button>`;
      chip.querySelector(".fname").textContent = f.name;
      chip.querySelector(".fsize").textContent = `(${formatBytes(f.size)})`;
      chip.querySelector(".rm").addEventListener("click", () => {
        chatAttachments.splice(i, 1);
        renderAttachmentChips();
      });
      list.appendChild(chip);
    });
  }

  function formatBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(1) + " MB";
  }

  async function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const s = r.result || "";
        // strip "data:<mime>;base64,"
        const i = s.indexOf(",");
        resolve(i >= 0 ? s.slice(i + 1) : s);
      };
      r.onerror = () => reject(r.error);
      r.readAsDataURL(file);
    });
  }

  async function sendChat() {
    const text = $("#chat-input").value.trim();
    if (!text && chatAttachments.length === 0) return;
    $("#chat-input").value = "";
    appendMsg("user", text || "(files only)");

    const body = {
      service_info: { SERVICE_ID: $("#chat-service-id").value || cfg.DEFAULT_SERVICE_ID, SERVICE_DATA: {} },
      user_info:    { USER_ID:    $("#chat-user-id").value    || cfg.DEFAULT_USER_ID,    USER_DATA: {} },
      session_id:   $("#chat-session-id").value || null,
      user_input:   text,
      agent_file:   $("#chat-agent").value || null,
      engine:       $("#chat-engine").value || null,
      memory_use:      $("#flag-memory_use").checked,
      rag_query_gene:  $("#flag-rag_query_gene").checked,
      meta_search:     $("#flag-meta_search").checked,
      web_search:      $("#flag-web_search").checked,
      thinking_mode:   $("#flag-thinking_mode").checked,
      private_mode:    $("#flag-private_mode").checked,
    };

    const files = chatAttachments.slice();
    const useBase64 = $("#chat-attach-base64").checked;

    const placeholder = appendMsg("agent", "…");
    try {
      let r;
      if (files.length === 0) {
        r = await Api.run(body);
      } else if (useBase64) {
        // /run + inline base64 attachments — good for small text/CSV/images.
        body.attachments = await Promise.all(files.map(async f => ({
          filename: f.name,
          content_base64: await fileToBase64(f),
          content_type: f.type || null,
        })));
        r = await Api.run(body);
      } else {
        // /run_multipart — the FastAPI endpoint that accepts UploadFiles.
        r = await Api.runMultipart(body, files);
      }
      if (r.session_id) $("#chat-session-id").value = r.session_id;
      placeholder.querySelector(".body").textContent = r.response || "(empty response)";
      const attachSummary = Array.isArray(r.attachments_processed) && r.attachments_processed.length
        ? ` · attached=${r.attachments_processed.length}` : "";
      placeholder.querySelector(".meta").textContent =
        `session=${r.session_id || ""}${r.session_name ? " · " + r.session_name : ""}${attachSummary}`;
      // Attach references to this bubble so a click opens the drawer.
      attachRefsToBubble(placeholder, r.references, r.session_id, text);
      // Successful send → clear the attachment tray.
      chatAttachments.length = 0;
      renderAttachmentChips();
    } catch (e) {
      placeholder.querySelector(".body").textContent = "⚠ " + e.message;
      placeholder.classList.add("error");
    }
  }

  function appendMsg(role, text) {
    const el = document.createElement("div");
    el.className = `msg ${role}`;
    el.innerHTML = `<div class="body"></div><div class="meta"></div>`;
    el.querySelector(".body").textContent = text;
    chatLog.appendChild(el);
    chatLog.scrollTop = chatLog.scrollHeight;
    if (role === "agent") el.addEventListener("click", () => onBubbleClick(el));
    return el;
  }

  // ---------- References drawer -----------------------------------------
  // A per-turn drawer that opens when the user clicks an agent bubble.
  // Data lives in `bubbleRefs` (a WeakMap keyed by the bubble DOM node) so
  // it disappears automatically when the bubble is removed.
  const refsDrawer = $("#refs-drawer");
  $("#btn-refs-close").addEventListener("click", () => closeRefs());

  function attachRefsToBubble(bubbleEl, refs, sessionId, userInput) {
    // Normalise into { knowledge, page_index, web, user_memory }. Missing
    // keys become empty arrays / null.
    const norm = {
      knowledge:   Array.isArray(refs && refs.knowledge)   ? refs.knowledge   : [],
      page_index:  Array.isArray(refs && refs.page_index)  ? refs.page_index  : [],
      web:         (refs && refs.web && typeof refs.web === "object") ? refs.web : null,
      user_memory: Array.isArray(refs && refs.user_memory) ? refs.user_memory : [],
      _turn: { session_id: sessionId || "", user_input: userInput || "" },
    };
    const total = norm.knowledge.length + norm.page_index.length
                + (norm.web && (norm.web.urls || []).length || 0)
                + norm.user_memory.length;
    bubbleRefs.set(bubbleEl, norm);
    if (total > 0) bubbleEl.classList.add("has-refs");
  }

  function onBubbleClick(el) {
    const refs = bubbleRefs.get(el);
    // Highlight the active bubble.
    for (const other of $$(".msg.agent.selected")) other.classList.remove("selected");
    el.classList.add("selected");
    renderRefs(refs);
    openRefs();
  }

  function openRefs() { refsDrawer.hidden = false; }
  function closeRefs() {
    refsDrawer.hidden = true;
    for (const other of $$(".msg.agent.selected")) other.classList.remove("selected");
  }

  function renderRefs(refs) {
    const body = $("#refs-body");
    const turn = $("#refs-turn");
    body.innerHTML = "";
    turn.textContent = "";
    if (!refs) {
      body.innerHTML = '<p class="refs-empty">No references captured for this turn.</p>';
      return;
    }
    const s = refs._turn || {};
    turn.textContent = s.session_id ? `session=${s.session_id}` : "";

    let anyRendered = false;
    anyRendered = renderRefSection(body, "Knowledge",  refs.knowledge)  || anyRendered;
    anyRendered = renderRefSection(body, "PageIndex",  refs.page_index) || anyRendered;
    anyRendered = renderWebSection(body,               refs.web)        || anyRendered;
    anyRendered = renderRefSection(body, "User Memory", refs.user_memory) || anyRendered;
    if (!anyRendered) {
      body.innerHTML = '<p class="refs-empty">Nothing was referenced for this turn.</p>';
    }
  }

  // Compute per-item strength (strong / medium / mild) from similarity_response.
  // Rank-based so a turn with only 2 strong hits still gets clear coloring
  // even if their absolute scores are moderate.
  function tagStrengths(items) {
    const scored = items.map((it, i) => ({
      it, i, sim: numOrNull(it.similarity_response) ?? numOrNull(it.similarity_prompt),
    }));
    const ranked = scored.filter(x => x.sim != null)
                         .sort((a, b) => b.sim - a.sim);
    const n = ranked.length;
    const tag = new Array(items.length).fill("mild");
    ranked.forEach((r, rank) => {
      const pos = rank / Math.max(1, n - 1);
      if      (pos <= 0.33) tag[r.i] = "strong";
      else if (pos <= 0.66) tag[r.i] = "medium";
      else                  tag[r.i] = "mild";
    });
    // Items without similarity default to "medium" so they don't look inert.
    scored.forEach((s, i) => { if (s.sim == null) tag[i] = "medium"; });
    return tag;
  }
  function numOrNull(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }

  function renderRefSection(container, label, items) {
    if (!items || !items.length) return false;
    const sect = document.createElement("div");
    sect.className = "refs-section";
    sect.innerHTML = `<h4>${esc(label)} <span class="count">${items.length}</span></h4>`;
    const strengths = tagStrengths(items);
    items.forEach((it, i) => sect.appendChild(refItemEl(it, strengths[i])));
    container.appendChild(sect);
    return true;
  }

  function refItemEl(it, strength) {
    const el = document.createElement("div");
    el.className = `ref-item ${strength}`;
    const title = it.title || it.page_id || it.rag_name || "(no title)";
    const snippet = it.snippet || it.summary || it.value_text || it.log || it.text || "";
    const tags = [];
    if (it.rag_name)    tags.push(esc(it.rag_name));
    if (it.category)    tags.push(esc(it.category));
    if (it.page_id)     tags.push("page:" + esc(it.page_id));
    if (it.chunk_id)    tags.push("chunk:" + esc(it.chunk_id));
    const sim = numOrNull(it.similarity_response);
    if (sim != null) tags.push(`<span class="sim">sim ${sim.toFixed(2)}</span>`);
    el.innerHTML = `
      <div class="ref-strength-bar"></div>
      <div class="ref-item-main">
        <div class="ref-item-title">${esc(title)}</div>
        <div class="ref-item-meta">${tags.join(" ")}</div>
        <div class="ref-item-snippet">${esc(snippet)}</div>
      </div>`;
    return el;
  }

  function renderWebSection(container, web) {
    const urls = (web && web.urls) || [];
    if (!urls.length) return false;
    const sect = document.createElement("div");
    sect.className = "refs-section";
    const eng = web.engine ? `${esc(web.engine)}${web.model ? " / " + esc(web.model) : ""}` : "";
    sect.innerHTML = `<h4>Web <span class="count">${urls.length}</span>${eng ? ` <span style="color:var(--text-dim); font-weight:400; text-transform:none;">${eng}</span>` : ""}</h4>`;
    // Web items have no similarity → all "medium".
    urls.forEach(u => {
      const el = document.createElement("div");
      el.className = "ref-item medium";
      const title = u.title || u.url || "(untitled)";
      const href  = u.url || "#";
      el.innerHTML = `
        <div class="ref-strength-bar"></div>
        <div class="ref-item-main">
          <div class="ref-item-title"><a href="${esc(href)}" target="_blank" rel="noopener">${esc(title)}</a></div>
          <div class="ref-item-meta">${u.date ? `<span class="tag">${esc(u.date)}</span>` : ""}</div>
          <div class="ref-item-snippet">${esc(u.url || "")}</div>
        </div>`;
      sect.appendChild(el);
    });
    container.appendChild(sect);
    return true;
  }

  // ---------- Sessions ---------------------------------------------------
  $("#btn-sess-load").addEventListener("click", async () => {
    try {
      const r = await Api.listSessions({
        user_id:    $("#sess-user-id").value    || undefined,
        service_id: $("#sess-service-id").value || undefined,
      });
      const tbody = $("#sess-table tbody");
      tbody.innerHTML = "";
      for (const s of (r.sessions || [])) {
        const tr = document.createElement("tr");
        tr.dataset.clickable = "1";
        tr.innerHTML = `<td>${esc(s.id)}</td><td>${esc(s.name)}</td>` +
                       `<td>${esc(s.agent)}</td><td>${esc(s.last_update_date)}</td>`;
        tr.addEventListener("click", async () => {
          $$("#sess-table tr").forEach(r => r.classList.remove("selected"));
          tr.classList.add("selected");
          try {
            const detail = await Api.getSession(s.id);
            $("#sess-detail").textContent = JSON.stringify(detail, null, 2);
          } catch (e) {
            $("#sess-detail").textContent = "Error: " + e.message;
          }
        });
        tbody.appendChild(tr);
      }
    } catch (e) { setStatus("Sessions load failed: " + e.message); }
  });

  // ---------- Web search engines ----------------------------------------
  $("#btn-web-load").addEventListener("click", async () => {
    try {
      const r = await Api.listWebEngines();
      $("#web-detail").textContent = JSON.stringify(r, null, 2);
    } catch (e) { $("#web-detail").textContent = "Error: " + e.message; }
  });

  // ---------- Feedback ---------------------------------------------------
  $("#btn-fb-config").addEventListener("click", async () => {
    try {
      const r = await Api.feedbackConfig($("#fb-agent").value);
      $("#fb-config").textContent = JSON.stringify(r, null, 2);
    } catch (e) { $("#fb-config").textContent = "Error: " + e.message; }
  });
  $("#btn-fb-send").addEventListener("click", async () => {
    let feedbacks;
    try { feedbacks = JSON.parse($("#fb-body").value); }
    catch (e) { $("#fb-result").textContent = "Invalid JSON: " + e.message; return; }
    try {
      const r = await Api.submitFeedback({
        session_id: $("#fb-session").value,
        agent_file: $("#fb-agent").value,
        seq:     $("#fb-seq").value,
        sub_seq: $("#fb-subseq").value,
        feedbacks,
      });
      $("#fb-result").textContent = JSON.stringify(r, null, 2);
    } catch (e) { $("#fb-result").textContent = "Error: " + e.message; }
  });

  // ---------- Health / Raw fetch ----------------------------------------
  $("#btn-raw-health").addEventListener("click", async () => {
    try {
      const r = await Api.health();
      $("#raw-response").textContent = JSON.stringify(r, null, 2);
    } catch (e) { $("#raw-response").textContent = "Error: " + e.message; }
  });
  $("#btn-raw-send").addEventListener("click", async () => {
    const method = $("#raw-method").value;
    const path   = $("#raw-path").value;
    let body;
    if (method === "POST") {
      try { body = JSON.parse($("#raw-body").value || "{}"); }
      catch (e) { $("#raw-response").textContent = "Invalid JSON: " + e.message; return; }
    }
    try {
      const r = await Api.call(method, path, body);
      $("#raw-response").textContent = JSON.stringify(r, null, 2);
    } catch (e) { $("#raw-response").textContent = "Error: " + e.message; }
  });

  // ---------- Recording controls ----------------------------------------
  const recSelect = $("#recording-select");

  function refreshRecordingList() {
    const currentSelection = recSelect.value;
    recSelect.innerHTML = '<option value="">— select recording —</option>';
    for (const r of Recorder.list()) {
      const opt = document.createElement("option");
      opt.value = r.id;
      opt.textContent = `${r.title} (${r.events} events)`;
      recSelect.appendChild(opt);
    }
    if (currentSelection && registryHas(currentSelection)) recSelect.value = currentSelection;
  }
  function registryHas(id) { return Recorder.list().some(r => r.id === id); }

  recSelect.addEventListener("change", () => {
    Recorder.activeRecordingId = recSelect.value || null;
    setStatus(recSelect.value ? `Recording selected: ${recSelect.value}` : "No recording selected.");
  });

  $("#btn-play").addEventListener("click", async () => {
    const id = recSelect.value;
    if (!id) { setStatus("Select a recording first."); return; }
    setStatus("Playing " + id + " …");
    await Recorder.play(id, handlePlaybackEvent);
    setStatus("Playback finished.");
  });

  $("#btn-record").addEventListener("click", () => {
    const title = prompt("Recording title?", "Demo " + new Date().toLocaleString());
    if (title === null) return;
    Recorder.startRecording(title);
    setStatus("Recording…");
  });

  $("#btn-stop").addEventListener("click", () => {
    if (Recorder.mode === "playing") { Recorder.stopPlayback(); return; }
    const rec = Recorder.stopRecording();
    if (rec) {
      Recorder.register(rec);
      recSelect.value = rec.id;
      Recorder.activeRecordingId = rec.id;
      refreshRecordingList();
      setStatus(`Captured ${rec.events.length} events. Click ⬇ Save to download.`);
      $("#btn-download").disabled = false;
      $("#btn-download").dataset.recId = rec.id;
    }
  });

  $("#btn-download").addEventListener("click", () => {
    const id = $("#btn-download").dataset.recId;
    if (!id) return;
    const rec = Recorder.get(id);
    if (!rec) return;
    const text = Recorder.exportAsMarkdown(rec);
    const blob = new Blob([text], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${rec.id}.md`;
    a.click();
    setStatus(`Downloaded ${rec.id}.md — reload it any time via ⬆ Load (or the Editor tab).`);
  });

  $("#file-load").addEventListener("change", async e => {
    const f = e.target.files[0];
    if (!f) return;
    const text = await f.text();
    try {
      // A recording exported by this app is a self-registering .js snippet;
      // eval'ing it here calls Recorder.register(...) directly. A .md export
      // carries the recording in a fenced ```json block; .json is raw data.
      if (f.name.endsWith(".md")) {
        Recorder.register(Recorder.parseMarkdown(text));
      } else if (f.name.endsWith(".json")) {
        Recorder.register(JSON.parse(text));
      } else {
        // eslint-disable-next-line no-new-func
        (new Function(text))();
      }
      refreshRecordingList();
      setStatus(`Loaded recording from ${f.name}`);
    } catch (err) {
      setStatus("Load failed: " + err.message);
    }
    e.target.value = "";
  });

  // ---------- Recorder mode indicator -----------------------------------
  Recorder.onChange(state => {
    const modeEl = $("#mode-indicator");
    modeEl.classList.remove("mode-live", "mode-rec", "mode-play");
    if (state.mode === "recording") { modeEl.classList.add("mode-rec"); modeEl.textContent = "REC"; }
    else if (state.mode === "playing") { modeEl.classList.add("mode-play"); modeEl.textContent = "PLAY"; }
    else { modeEl.classList.add("mode-live"); modeEl.textContent = "LIVE"; }
    $("#btn-stop").disabled = state.mode === "idle";
    $("#btn-record").disabled = state.mode !== "idle";
    $("#btn-play").disabled = state.mode !== "idle";
    refreshRecordingList();
  });

  // Called for each event during playback. Route to the panel that owns it.
  function handlePlaybackEvent(evt) {
    if (evt.type !== "api") return;
    // Switch to the relevant tab so the operator sees the update.
    const path = evt.path || "";
    if      (path === "/run" || path === "/run_function") switchTab("chat");
    else if (path.startsWith("/sessions"))                switchTab("sessions");
    else if (path.startsWith("/agents") &&
             path.endsWith("/feedback"))                  switchTab("feedback");
    else if (path.startsWith("/agents"))                  switchTab("agents");
    else if (path === "/web_search_engines")              switchTab("websearch");
    else                                                  switchTab("health");

    // Panel-specific rendering.
    if (path === "/run" || path === "/run_function" || path === "/run_multipart") {
      const req = evt.request || {};
      if (req.user_input) appendMsg("user", req.user_input);
      const resp = evt.response || {};
      const bubble = appendMsg("agent", resp.response || "(no response captured)");
      bubble.querySelector(".meta").textContent =
        `session=${resp.session_id || ""}${resp.session_name ? " · " + resp.session_name : ""}`;
      if (resp.session_id) $("#chat-session-id").value = resp.session_id;
      // Preserve the click-to-open References behavior during playback so
      // recorded reference data (added to sample_chat.js) can be inspected.
      attachRefsToBubble(bubble, resp.references, resp.session_id, req.user_input);
    } else if (path === "/health") {
      $("#raw-response").textContent = JSON.stringify(evt.response, null, 2);
    } else if (path === "/web_search_engines") {
      $("#web-detail").textContent = JSON.stringify(evt.response, null, 2);
    } else if (path === "/agents") {
      // Re-render agents table from recorded response.
      const tbody = $("#agents-table tbody");
      tbody.innerHTML = "";
      for (const a of (evt.response && evt.response.agents) || []) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${esc(a.file || a.agent_file)}</td>` +
                       `<td>${esc(a.agent_name || a.name || "")}</td>` +
                       `<td>${esc(a.description || "")}</td>`;
        tbody.appendChild(tr);
      }
    } else if (path.startsWith("/sessions/")) {
      $("#sess-detail").textContent = JSON.stringify(evt.response, null, 2);
    } else if (path === "/sessions") {
      const tbody = $("#sess-table tbody");
      tbody.innerHTML = "";
      for (const s of (evt.response && evt.response.sessions) || []) {
        const tr = document.createElement("tr");
        tr.innerHTML = `<td>${esc(s.id)}</td><td>${esc(s.name)}</td>` +
                       `<td>${esc(s.agent)}</td><td>${esc(s.last_update_date)}</td>`;
        tbody.appendChild(tr);
      }
    } else if (path.endsWith("/feedback") && evt.method === "GET") {
      $("#fb-config").textContent = JSON.stringify(evt.response, null, 2);
    } else if (path === "/feedback" && evt.method === "POST") {
      $("#fb-result").textContent = JSON.stringify(evt.response, null, 2);
    }
  }

  function switchTab(name) {
    $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === name));
    $$(".panel").forEach(p => p.classList.toggle("active", p.dataset.panel === name));
  }

  // ---------- Utility ----------------------------------------------------
  function setStatus(msg) { $("#status-text").textContent = msg; }
  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ---------- Boot -------------------------------------------------------
  refreshRecordingList();
  loadAgents();   // best-effort; falls back on network error
  setStatus(`Ready. Backend: ${Api.getBackendUrl() || "(unset)"}`);
})();
