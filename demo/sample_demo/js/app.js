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
    // Refresh the chat sidebar for the selected agent.
    onChatAgentChanged();
  }

  // Everything the sidebar offers for the current agent, as last loaded.
  const chatState = {
    options: null,        // GET /agents/{file}/chat_options response
    skillDefaults: [],    // names ticked by SKILL.TOOLS.<name>.DEFAULT
    personality: {},      // agent PERSONALITY, to send only what was changed
    sessionId: "",        // session shown in the chat log
    sessionName: "",
    feedbackCfg: {},      // agent_file -> GET /agents/{file}/feedback
    justRan: "",          // session whose turn this page just ran
  };

  async function onChatAgentChanged() {
    const file = $("#chat-agent").value;
    if (!file) return;
    try {
      applyChatOptions(await Api.chatOptions(file));
    } catch (e) {
      // Older backend without chat_options: fall back to the engine list.
      try {
        const r = await Api.listEngines(file);
        applyChatOptions({ LLM: r.LLM, IMAGEGEN: r.IMAGEGEN, skills: [], books: [], orgs: [] });
      } catch (e2) { /* chat can still fire with the default engine */ }
    }
  }
  $("#chat-agent").addEventListener("change", onChatAgentChanged);
  $("#btn-agents-load").addEventListener("click", loadAgents);

  function fillSelect(el, values, def, blankLabel) {
    el.innerHTML = "";
    if (blankLabel != null) {
      const o = document.createElement("option"); o.value = ""; o.textContent = blankLabel; el.appendChild(o);
    }
    for (const v of values || []) {
      const opt = document.createElement("option");
      opt.value = v; opt.textContent = v;
      if (v === def) opt.selected = true;
      el.appendChild(opt);
    }
  }

  function checkItem(name, label, checked, desc, data) {
    const l = document.createElement("label");
    l.innerHTML = `<input type="checkbox" /><span><span class="lbl"></span><span class="desc"></span></span>`;
    const cb = l.querySelector("input");
    cb.value = name; cb.checked = !!checked;
    for (const k of Object.keys(data || {})) cb.dataset[k] = data[k];
    l.querySelector(".lbl").textContent = label;
    l.querySelector(".desc").textContent = desc || "";
    return l;
  }
  const checkedValues = sel => $$(`${sel} input[type=checkbox]`).filter(c => c.checked).map(c => c.value);

  function applyChatOptions(r) {
    chatState.options = r || {};
    const llm = (r && r.LLM) || {}, img = (r && r.IMAGEGEN) || {};
    fillSelect($("#chat-engine"), llm.engines, llm.default);
    fillSelect($("#chat-imagegen-engine"), img.engines, img.default, (img.engines || []).length ? null : "(none)");

    // Skills by phase, ticked by their DEFAULT.
    const skills = (r && r.skills) || [];
    const sk = $("#chat-skills"); sk.innerHTML = "";
    let lastPhase = "";
    for (const s of skills) {
      if (s.phase !== lastPhase) {
        const g = document.createElement("div"); g.className = "group"; g.textContent = s.phase; sk.appendChild(g);
        lastPhase = s.phase;
      }
      sk.appendChild(checkItem(s.name, s.label === s.name ? s.name : `${s.label} (${s.name})`, s.default, s.description));
    }
    chatState.skillDefaults = skills.filter(s => s.default).map(s => s.name);
    $("#chat-skill-box").hidden = skills.length === 0;
    // Agents with SKILL.TOOLS pick web search / citations / diagrams / emphasis there.
    $("#chat-legacy-flags").hidden = skills.length > 0;

    const books = (r && r.books) || [];
    const bk = $("#chat-books"); bk.innerHTML = "";
    for (const b of books) bk.appendChild(checkItem(b.rag_name, b.rag_name, false, b.retriever));
    $("#chat-book-box").hidden = books.length === 0;

    const orgs = (r && r.orgs) || [];
    const orgSel = $("#chat-org"); orgSel.innerHTML = "";
    orgs.forEach((o, i) => {
      const opt = document.createElement("option"); opt.value = String(i); opt.textContent = o.label; orgSel.appendChild(opt);
    });
    renderPersonaChoices();
    $("#chat-persona-box").hidden = orgs.length === 0;

    const t = (r && r.thinking) || {};
    if (t.options) {
      $("#flag-thinking_mode").checked = !!t.mode;
      const tb = $("#chat-thinking-box"); tb.innerHTML = "";
      for (const o of t.options) tb.appendChild(checkItem(o, o, (t.targets || []).includes(o)));
      $("#chat-max-thinking-turns").value = t.max_turns || 1;
    }

    const d = (r && r.execution_defaults) || {};
    const flagOf = { MEMORY_USE: "memory_use", MEMORY_SAVE: "memory_save", SAVE_DIGEST: "save_digest",
                     MAGIC_WORD_USE: "magic_word_use", RAG_QUERY_GENE: "rag_query_gene",
                     META_SEARCH: "meta_search", WEB_SEARCH_GUARDRAIL: "web_search_guardrail",
                     PRIVATE_MODE: "private_mode" };
    for (const k of Object.keys(flagOf)) {
      const el = $("#flag-" + flagOf[k]);
      if (el && k in d) el.checked = !!d[k];
    }
    chatState.personality = (r && r.personality) || {};
    $("#chat-po-language").value = chatState.personality.LANGUAGE || "";
    $("#chat-po-style").value = chatState.personality.SPEAKING_STYLE || "";
  }

  function renderPersonaChoices() {
    const orgs = (chatState.options && chatState.options.orgs) || [];
    const o = orgs[Number($("#chat-org").value || 0)];
    const box = $("#chat-personas"); box.innerHTML = "";
    for (const p of (o && o.personas) || []) box.appendChild(checkItem(p.persona_id, `${p.persona_id}: ${p.name}`, false));
    if (o && !(o.personas || []).length) box.innerHTML = '<p class="hint">No matching personas</p>';
  }
  $("#chat-org").addEventListener("change", renderPersonaChoices);

  // ---------- Chat -------------------------------------------------------
  const chatLog = $("#chat-log");
  // Files staged for the next send. Cleared after a successful send.
  const chatAttachments = [];
  // Store references keyed by DOM element so the click handler can pull
  // them without stashing anything on the element itself (which serializes
  // poorly and can be large).
  const bubbleRefs = new WeakMap();
  const JOB_POLL_MS = 2000;
  const sleep = ms => new Promise(r => setTimeout(r, ms));

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

  function chatIds() {
    return {
      service_info: { SERVICE_ID: $("#chat-service-id").value || cfg.DEFAULT_SERVICE_ID, SERVICE_DATA: {} },
      user_info:    { USER_ID:    $("#chat-user-id").value    || cfg.DEFAULT_USER_ID,    USER_DATA: {} },
    };
  }

  function buildChatBody(text) {
    const opts = chatState.options || {};
    const body = Object.assign(chatIds(), {
      session_id:   $("#chat-session-id").value || null,
      user_input:   text,
      agent_file:   $("#chat-agent").value || null,
      engine:       $("#chat-engine").value || null,
      imagegen_engine: $("#chat-imagegen-engine").value || null,
      memory_use:      $("#flag-memory_use").checked,
      memory_save:     $("#flag-memory_save").checked,
      save_digest:     $("#flag-save_digest").checked,
      magic_word_use:  $("#flag-magic_word_use").checked,
      rag_query_gene:  $("#flag-rag_query_gene").checked,
      meta_search:     $("#flag-meta_search").checked,
      web_search_guardrail: $("#flag-web_search_guardrail").checked,
      thinking_mode:   $("#flag-thinking_mode").checked,
      private_mode:    $("#flag-private_mode").checked,
      insert_citations:$("#flag-insert_citations").checked,
    });
    if ((opts.skills || []).length) {
      // Unchanged from the agent's defaults: leave them as candidates Thinking
      // may decline, exactly as the WebUI does. Changed: send them as orders.
      const picked = checkedValues("#chat-skills");
      const same = picked.length === chatState.skillDefaults.length &&
                   picked.every(n => chatState.skillDefaults.includes(n));
      if (!same) body.skills = picked;
    } else {
      body.web_search    = $("#flag-web_search").checked;
      body.cite_knowledge = $("#flag-cite_knowledge").checked;
      body.diagram_mode  = $("#flag-diagram_mode").checked;
      body.emphasis_mode = $("#flag-emphasis_mode").checked;
    }
    if (body.thinking_mode) {
      body.thinking_targets = checkedValues("#chat-thinking-box");
      body.max_thinking_turns = Number($("#chat-max-thinking-turns").value || 1);
    }
    const books = checkedValues("#chat-books");
    if (books.length) body.books = books;
    const orgs = opts.orgs || [];
    if (orgs.length) {
      body.org = (orgs[Number($("#chat-org").value || 0)] || {}).org || null;
      const pids = checkedValues("#chat-personas");
      if (pids.length) body.personas = pids;
      if ($("#chat-include-query").checked) body.include_query = true;
    }
    const pers = {};
    const lang = $("#chat-po-language").value.trim(), style = $("#chat-po-style").value.trim();
    if (lang && lang !== (chatState.personality.LANGUAGE || "")) pers.LANGUAGE = lang;
    if (style && style !== (chatState.personality.SPEAKING_STYLE || "")) pers.SPEAKING_STYLE = style;
    if (Object.keys(pers).length) body.personality = pers;

    // Session Summary — send both fields only when the operator opted in for
    // this turn. Sending them null-null preserves whatever was saved earlier.
    if ($("#chat-summary-enabled").checked) {
      body.session_summary_enabled = true;
      const _presetName = $("#chat-summary-preset").value;
      if (_presetName) {
        const _tpl = (summaryState.presets || []).find(p => p.name === _presetName);
        if (_tpl) body.session_summary_template = _tpl.template;
      }
    }
    return body;
  }

  async function sendChat() {
    const text = $("#chat-input").value.trim();
    if (!text && chatAttachments.length === 0) return;
    $("#chat-input").value = "";
    appendMsg("user", text || "(files only)");

    const body = buildChatBody(text);
    const files = chatAttachments.slice();
    const useBase64 = $("#chat-attach-base64").checked;
    const background = $("#chat-async").checked;
    if (files.length && useBase64) {
      body.attachments = await Promise.all(files.map(async f => ({
        filename: f.name,
        content_base64: await fileToBase64(f),
        content_type: f.type || null,
      })));
    }
    const multipart = files.length > 0 && !useBase64;

    const placeholder = appendMsg("agent", "…");
    placeholder.classList.add("pending");
    $("#btn-send").disabled = true;
    try {
      let r;
      if (background) {
        const job = multipart ? await Api.runAsyncMultipart(body, files) : await Api.runAsync(body);
        if (job.session_id) $("#chat-session-id").value = job.session_id;
        const done = await pollJob(job.job_id, placeholder);
        if (done.state !== "done") throw new Error(done.error || "Run failed");
        r = done.result || {};
      } else {
        placeholder.querySelector(".body").textContent = "⏳ Waiting for the answer (synchronous /run)…";
        r = multipart ? await Api.runMultipart(body, files) : await Api.run(body);
      }
      if (r.session_id) $("#chat-session-id").value = r.session_id;
      placeholder.classList.remove("pending");
      placeholder.querySelector(".body").textContent = r.response_display || r.response || "(empty response)";
      const attachSummary = Array.isArray(r.attachments_processed) && r.attachments_processed.length
        ? ` · attached=${r.attachments_processed.length}` : "";
      placeholder.querySelector(".meta").textContent =
        `session=${r.session_id || ""}${r.session_name ? " · " + r.session_name : ""}${attachSummary}`;
      attachRefsToBubble(placeholder, r.references, r.session_id, text);
      // Successful send → clear the attachment tray.
      chatAttachments.length = 0;
      renderAttachmentChips();
      // Re-read the turn so it gets its actions (detail, memory, delete, feedback).
      if (r.session_id && r.seq) { chatState.justRan = r.session_id; await openSession(r.session_id); }
      loadChatSessions(true);
    } catch (e) {
      placeholder.classList.remove("pending");
      placeholder.querySelector(".body").textContent = "⚠ " + e.message;
      placeholder.classList.add("error");
    } finally {
      $("#btn-send").disabled = false;
    }
  }

  // Poll GET /jobs/{id} until the run leaves "running", showing the
  // executor's status message and the streamed text the way the WebUI does.
  async function pollJob(jobId, bubble) {
    for (;;) {
      const j = await Api.getJob(jobId);
      showJobProgress(bubble, j);
      if (j.state !== "running") return j;
      await sleep(JOB_POLL_MS);
    }
  }

  function showJobProgress(bubble, j) {
    if (!bubble) return;
    const p = j.progress || {};
    if (j.state === "running") {
      bubble.querySelector(".body").textContent = p.partial_response || "…";
      bubble.querySelector(".meta").textContent =
        `⏳ ${p.message || "Running..."}${j.elapsed_sec != null ? ` · ${j.elapsed_sec}s` : ""}`;
    } else if (j.state === "done") {
      const r = j.result || {};
      bubble.classList.remove("pending");
      bubble.querySelector(".body").textContent = r.response_display || r.response || "(empty response)";
      bubble.querySelector(".meta").textContent =
        `session=${r.session_id || ""}${r.session_name ? " · " + r.session_name : ""} · ${j.elapsed_sec || 0}s`;
      attachRefsToBubble(bubble, r.references, r.session_id, j.user_input);
    } else {
      bubble.classList.remove("pending");
      bubble.classList.add("error");
      bubble.querySelector(".body").textContent = "⚠ " + (j.error || "Run failed");
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

  // ---------- Chat: sessions and turns ------------------------------------
  $("#btn-chat-new").addEventListener("click", () => {
    $("#chat-session-id").value = "";
    chatState.sessionId = ""; chatState.sessionName = "";
    chatLog.innerHTML = "";
    $("#chat-head-name").textContent = "New chat";
    markCurrentSession();
    closeRefs();
  });
  $("#btn-chat-open").addEventListener("click", () => {
    const id = $("#chat-session-id").value.trim();
    if (id) openSession(id);
  });
  $("#btn-chat-reload").addEventListener("click", () => { if (chatState.sessionId) openSession(chatState.sessionId); });
  $("#chat-view").addEventListener("change", () => { if (chatState.sessionId) openSession(chatState.sessionId); });
  $("#btn-chat-sess-reload").addEventListener("click", () => loadChatSessions(false));
  $("#chat-sess-hidden").addEventListener("change", () => loadChatSessions(false));
  $("#btn-chat-rename").addEventListener("click", () => { if (chatState.sessionId) renameSession(chatState.sessionId, chatState.sessionName); });
  $("#btn-chat-export").addEventListener("click", async () => {
    const id = chatState.sessionId;
    if (!id) { setStatus("Open a session first."); return; }
    try {
      const md = await Api.exportSession(id, { view: $("#chat-view").value });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([typeof md === "string" ? md : JSON.stringify(md)], { type: "text/markdown" }));
      a.download = `${id}_chat.md`;
      a.click();
      setStatus(`Exported ${id}_chat.md`);
    } catch (e) { setStatus("Export failed: " + e.message); }
  });

  async function loadChatSessions(silent) {
    const ids = chatIds();
    try {
      const r = await Api.listSessions({
        user_id: ids.user_info.USER_ID, service_id: ids.service_info.SERVICE_ID,
        active: $("#chat-sess-hidden").checked ? "N" : "Y",
      });
      renderChatSessionList(r.sessions || [], $("#chat-sess-hidden").checked);
    } catch (e) { if (!silent) setStatus("Sessions load failed: " + e.message); }
  }

  function renderChatSessionList(sessions, hiddenView) {
    const box = $("#chat-sess-list");
    box.innerHTML = "";
    if (!sessions.length) { box.innerHTML = '<p class="hint">No sessions.</p>'; return; }
    for (const s of sessions) {
      const row = document.createElement("div");
      row.className = "sess-row" + (hiddenView ? " hidden-sess" : "");
      row.dataset.sid = s.id;
      row.innerHTML = `<span class="sess-name"></span>` +
        (hiddenView ? `<button class="act" title="Show again (POST /sessions/{id}/activate)">↺</button>`
                    : `<button class="ren" title="Rename">✎</button><button class="hide" title="Hide (POST /sessions/{id}/hide)">×</button>`);
      const nm = row.querySelector(".sess-name");
      nm.textContent = s.name || s.id;
      nm.title = `${s.id} · ${s.last_update_date || ""}${s.status === "LOCKED" ? " · running" : ""}`;
      if (s.status === "LOCKED") nm.insertAdjacentHTML("beforeend", "<small>⏳</small>");
      nm.addEventListener("click", () => openSession(s.id));
      const on = (cls, fn) => { const b = row.querySelector(cls); if (b) b.addEventListener("click", fn); };
      on(".ren", () => renameSession(s.id, s.name));
      on(".hide", async () => {
        if (!confirm(`Hide "${s.name || s.id}"? (it can be shown again)`)) return;
        try { await Api.hideSession(s.id); setStatus(`Hid ${s.id}`); loadChatSessions(true); }
        catch (e) { setStatus("Hide failed: " + e.message); }
      });
      on(".act", async () => {
        try { await Api.activateSession(s.id); setStatus(`Re-displayed ${s.id}`); loadChatSessions(true); }
        catch (e) { setStatus("Activate failed: " + e.message); }
      });
      box.appendChild(row);
    }
    markCurrentSession();
  }

  function markCurrentSession() {
    $$("#chat-sess-list .sess-row").forEach(r => r.classList.toggle("current", r.dataset.sid === chatState.sessionId));
  }

  async function renameSession(id, current) {
    const name = prompt("New session name", current || "");
    if (!name || name === current) return;
    try {
      await Api.renameSession(id, name);
      if (id === chatState.sessionId) { chatState.sessionName = name; $("#chat-head-name").textContent = name; }
      setStatus(`Renamed ${id}`);
      loadChatSessions(true);
    } catch (e) { setStatus("Rename failed: " + e.message); }
  }

  async function openSession(id) {
    try {
      const r = await Api.getTurns(id, { view: $("#chat-view").value });
      renderTurns(r);
    } catch (e) { setStatus("Open session failed: " + e.message); }
  }

  // Draw a session the way the WebUI chat pane does: per turn, the question,
  // then each answer with its images and actions.
  function renderTurns(r) {
    chatState.sessionId = r.session_id || "";
    chatState.sessionName = r.session_name || "";
    $("#chat-session-id").value = chatState.sessionId;
    $("#chat-head-name").textContent = chatState.sessionName || chatState.sessionId || "New chat";
    if (r.view) $("#chat-view").value = r.view;
    chatLog.innerHTML = "";
    closeRefs();
    for (const t of r.turns || []) {
      const sep = document.createElement("hr"); sep.className = "turn-sep"; chatLog.appendChild(sep);
      (t.entries || []).forEach((e, i) => {
        const u = appendMsg("user", e.user_input || "");
        u.insertAdjacentHTML("afterbegin", `<div class="who"></div>`);
        u.querySelector(".who").textContent = `${t.user_id || e.prompt_role || "user"} · seq ${t.seq}`;
        addLinks(u, e.contents, "📎");
        const a = appendMsg("agent", e.response_display || e.response || "");
        a.insertAdjacentHTML("afterbegin", `<div class="who"></div>`);
        a.querySelector(".who").textContent =
          [e.name, e.persona_name && e.persona_name !== e.name ? e.persona_name : "", e.engine, e.type !== "LLM" ? e.type : ""]
            .filter(Boolean).join(" · ");
        a.querySelector(".meta").textContent = e.response_timestamp || "";
        for (const img of e.images || []) {
          const el = document.createElement("img");
          el.className = "gen"; el.src = Api.contentUrl(img.url); el.alt = img.file_name;
          a.insertBefore(el, a.querySelector(".meta"));
        }
        if (t.memory_flg === "N" || e.memory_flg === "N") a.classList.add("memory-off");
        attachRefsToBubble(a, e.references, r.session_id, e.user_input);
        // Turn-level actions sit under the turn's last answer.
        if (i === (t.entries.length - 1)) addTurnActions(a, r.session_id, t, e);
        else if ((e.feedback_config || {}).active) addTurnActions(a, r.session_id, t, e, true);
      });
    }
    if (!(r.turns || []).length) appendMsg("system", "(no turns yet)");
    markCurrentSession();
    chatLog.scrollTop = chatLog.scrollHeight;
    // Not during playback: the recording already holds what came next.
    if (r.status === "LOCKED" && Recorder.mode !== "playing") {
      watchRunningSession(r.session_id, chatState.justRan === r.session_id);
    }
    chatState.justRan = "";
  }

  function addLinks(bubble, items, icon) {
    if (!(items || []).length) return;
    const div = document.createElement("div"); div.className = "attach-links";
    for (const c of items) {
      const a = document.createElement("a");
      a.href = Api.contentUrl(c.url); a.target = "_blank"; a.rel = "noopener";
      a.textContent = `${icon} ${c.file_name}`;
      a.addEventListener("click", ev => ev.stopPropagation());
      div.appendChild(a);
    }
    bubble.insertBefore(div, bubble.querySelector(".meta"));
  }

  function addTurnActions(bubble, sid, turn, entry, feedbackOnly) {
    const bar = document.createElement("div"); bar.className = "turn-actions";
    const btn = (label, title, fn, cls) => {
      const b = document.createElement("button"); b.textContent = label; b.title = title;
      if (cls) b.className = cls;
      b.addEventListener("click", ev => { ev.stopPropagation(); fn(); });
      bar.appendChild(b);
    };
    if (!feedbackOnly) {
      btn("Detail", "GET /sessions/{id}/turns/{seq}/detail", () => showDetail(sid, turn.seq, entry.detail_sub_seq));
      const off = turn.memory_flg === "N";
      btn(off ? "Memory On" : "Memory Off",
          "POST /sessions/{id}/turns/{seq}/memory — kept on screen, left out of the LLM's memory",
          async () => {
            try { await Api.setTurnMemory(sid, turn.seq, off); await openSession(sid); }
            catch (e) { setStatus("Memory flag failed: " + e.message); }
          });
      btn("Delete", "POST /sessions/{id}/turns/{seq}/delete", async () => {
        if (!confirm(`Delete turn ${turn.seq}?`)) return;
        try { await Api.deleteTurn(sid, turn.seq); await openSession(sid); }
        catch (e) { setStatus("Delete failed: " + e.message); }
      }, "danger");
    }
    if ((entry.feedback_config || {}).active) {
      btn("Feedback", "POST /feedback", () => toggleFeedback(bubble, sid, turn.seq, entry));
    }
    bubble.insertBefore(bar, bubble.querySelector(".meta"));
  }

  async function toggleFeedback(bubble, sid, seq, entry) {
    const open = bubble.querySelector(".fb-form");
    if (open) { open.remove(); return; }
    const agentFile = entry.answer_agent_file || entry.agent_file;
    let cats = [];
    try {
      if (!chatState.feedbackCfg[agentFile]) chatState.feedbackCfg[agentFile] = await Api.feedbackConfig(agentFile);
      cats = chatState.feedbackCfg[agentFile].categories || [];
    } catch (e) { /* categories are optional */ }
    const cfgFb = entry.feedback_config || {};
    const saved = entry.feedback || {};
    const form = document.createElement("div"); form.className = "fb-form";
    form.addEventListener("click", ev => ev.stopPropagation());
    for (const item of cfgFb.items || []) {
      const cur = saved[item] || {};
      const row = document.createElement("div"); row.className = "fb-item"; row.dataset.item = item;
      row.innerHTML = `<label><input type="checkbox" class="on" /> <span></span></label>
                       <textarea class="memo" placeholder="Memo"></textarea>
                       <select class="cat"></select>`;
      row.querySelector("span").textContent = item;
      row.querySelector(".on").checked = !!cur.visible;
      row.querySelector(".memo").value = cur.memo || "";
      const sel = row.querySelector(".cat");
      for (const c of (cats.length ? cats : [cfgFb.default_category || "未設定"])) {
        const o = document.createElement("option"); o.value = c; o.textContent = c; sel.appendChild(o);
      }
      sel.value = cur.category || cfgFb.default_category || sel.value;
      form.appendChild(row);
    }
    const send = document.createElement("button"); send.className = "btn primary"; send.textContent = "Save feedback";
    send.addEventListener("click", async () => {
      // Same record the WebUI writes: per item {visible, flg, memo, category},
      // flg set when the memo is new or changed.
      const fbs = { name: "Feedback" };
      for (const row of $$(".fb-item", form)) {
        const item = row.dataset.item, prev = (saved[item] || {}).memo || "";
        const on = row.querySelector(".on").checked;
        const memo = on ? row.querySelector(".memo").value : "";
        fbs[item] = { visible: on, memo, category: row.querySelector(".cat").value,
                      flg: memo !== "" && memo !== prev };
      }
      try {
        await Api.submitFeedback({ session_id: sid, agent_file: agentFile, seq, sub_seq: entry.sub_seq, feedbacks: fbs });
        setStatus(`Saved feedback (${seq}_${entry.sub_seq})`);
        await openSession(sid);
      } catch (e) { setStatus("Feedback failed: " + e.message); }
    });
    form.appendChild(send);
    bubble.insertBefore(form, bubble.querySelector(".meta"));
  }

  async function showDetail(sid, seq, subSeq) {
    try {
      const r = await Api.turnDetail(sid, seq, subSeq);
      renderDetail(r);
    } catch (e) { setStatus("Detail failed: " + e.message); }
  }

  function renderDetail(r) {
    $("#refs-title").textContent = "Detail Information";
    $("#refs-turn").textContent = `seq ${r.seq || ""}-${r.sub_seq || ""}`;
    const body = $("#refs-body"); body.innerHTML = "";
    const pre = document.createElement("pre"); pre.className = "detail-pre";
    pre.textContent = r.detail || "(empty)";
    body.appendChild(pre);
    openRefs();
  }

  // A session opened while a turn runs (WebUI, another client, a job): show
  // its progress until it unlocks, then redraw it. Right after our own run the
  // answer is already on screen and the lock is the digest being written, so
  // only the status line is shown.
  let watching = "";
  async function watchRunningSession(sid, statusOnly) {
    if (watching === sid) return;
    watching = sid;
    const bubble = statusOnly ? appendMsg("system", "⏳") : appendMsg("agent", "…");
    if (!statusOnly) bubble.classList.add("pending");
    try {
      for (;;) {
        const s = await Api.sessionStatus(sid);
        if (chatState.sessionId !== sid) return;
        if (s.status !== "LOCKED") break;
        if (statusOnly) {
          bubble.querySelector(".body").textContent = `⏳ Finishing: ${s.message || "..."}`;
        } else {
          bubble.querySelector(".body").textContent = s.partial_response || "…";
          bubble.querySelector(".meta").textContent = `⏳ ${s.message || "Running..."}`;
        }
        await sleep(JOB_POLL_MS);
      }
    } catch (e) { /* stop watching on error */ }
    finally { watching = ""; }
    if (chatState.sessionId === sid) openSession(sid);
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
    $("#refs-title").textContent = "References";
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

  // ---------- Session Summary --------------------------------------------
  // Shared state so the Chat sidebar dropdown and the Summary tab dropdown
  // stay in sync from a single GET /session_summary_presets call.
  const summaryState = { presets: [] };

  function populateSummaryPresetDropdowns() {
    for (const sel of ["#chat-summary-preset", "#summary-preset-select"]) {
      const el = $(sel);
      if (!el) continue;
      const prev = el.value;
      // Keep the first empty option to allow "no change" / "none loaded".
      el.innerHTML = el.querySelector('option[value=""]').outerHTML;
      for (const p of summaryState.presets) {
        const opt = document.createElement("option");
        opt.value = p.name;
        opt.textContent = p.description ? `${p.name} — ${p.description}` : p.name;
        el.appendChild(opt);
      }
      if (prev) el.value = prev;
    }
  }

  async function loadSummaryPresets(silent) {
    try {
      const r = await Api.listSummaryPresets();
      summaryState.presets = Array.isArray(r && r.presets) ? r.presets : [];
      populateSummaryPresetDropdowns();
      if (!silent) setStatus(`Loaded ${summaryState.presets.length} summary preset(s).`);
    } catch (e) {
      if (!silent) setStatus("Summary presets load failed: " + e.message);
    }
  }

  $("#btn-summary-presets").addEventListener("click", () => loadSummaryPresets(false));

  $("#btn-summary-load").addEventListener("click", async () => {
    const id = $("#summary-session-id").value.trim();
    if (!id) { setStatus("Enter a session ID first."); return; }
    try {
      const r = await Api.getSessionSummary(id);
      $("#summary-enabled").checked   = !!r.enabled;
      $("#summary-template").value    = r.template || "";
      $("#summary-content").textContent = r.content || "(no summary generated yet)";
      $("#summary-updated").textContent  = r.updated_at || "—";
    } catch (e) {
      $("#summary-content").textContent = "Error: " + e.message;
    }
  });

  $("#btn-summary-apply-preset").addEventListener("click", () => {
    const name = $("#summary-preset-select").value;
    if (!name) { setStatus("Pick a preset first."); return; }
    const p = summaryState.presets.find(x => x.name === name);
    if (!p) return;
    $("#summary-template").value = p.template || "";
  });

  $("#btn-summary-save").addEventListener("click", async () => {
    const id = $("#summary-session-id").value.trim();
    if (!id) { setStatus("Enter a session ID first."); return; }
    try {
      const r = await Api.setSessionSummary(id, {
        enabled:  $("#summary-enabled").checked,
        template: $("#summary-template").value,
      });
      $("#summary-content").textContent = r.content || "(no summary generated yet)";
      $("#summary-updated").textContent  = r.updated_at || "—";
      setStatus("Summary settings saved.");
    } catch (e) { setStatus("Save failed: " + e.message); }
  });

  // Convenience: when the Chat panel picks up a session_id from a /run
  // response, mirror it into the Summary tab's session_id field so operators
  // can jump straight from a live turn to the summary editor.
  const _chatSessionInput = $("#chat-session-id");
  const _mirrorSessionId = () => {
    const v = _chatSessionInput.value.trim();
    if (v && !$("#summary-session-id").value.trim()) {
      $("#summary-session-id").value = v;
    }
  };
  _chatSessionInput.addEventListener("input",  _mirrorSessionId);
  _chatSessionInput.addEventListener("change", _mirrorSessionId);

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
  // Recorded chat-pane traffic: the async run and its polls, the turn view
  // and its actions, the chat session list. Returns true when it handled it.
  let playbackBubble = null;
  function handleChatPlayback(evt) {
    const path = evt.path || "";
    const resp = evt.response || {};
    const req = evt.request || {};
    const bare = path.split("?")[0];
    if (bare === "/run_async" || bare === "/run_async_multipart") {
      if (req.user_input) appendMsg("user", req.user_input);
      playbackBubble = appendMsg("agent", "…");
      playbackBubble.classList.add("pending");
      if (resp.session_id) $("#chat-session-id").value = resp.session_id;
      if (evt.error) showJobProgress(playbackBubble, { state: "error", error: evt.error });
    } else if (bare.startsWith("/jobs/")) {
      showJobProgress(playbackBubble, resp);
      if (resp.state !== "running") playbackBubble = null;
    } else if (/^\/agents\/[^/]+\/chat_options$/.test(bare)) {
      applyChatOptions(resp);
    } else if (/^\/sessions\/[^/]+\/turns$/.test(bare)) {
      renderTurns(resp);
    } else if (/^\/sessions\/[^/]+\/turns\/[^/]+\/detail$/.test(bare)) {
      renderDetail(resp);
    } else if (/^\/sessions\/[^/]+\/(turns\/[^/]+\/(delete|memory)|rename|hide|activate)$/.test(bare)) {
      setStatus(`${evt.method} ${bare} → ${evt.status || ""}`);
    } else if (/^\/sessions\/[^/]+\/(export|status)$/.test(bare)) {
      setStatus(`${evt.method} ${bare} → ${evt.status || ""}`);
    } else if (bare === "/sessions" && /[?&]active=/.test(path)) {
      // The chat sidebar asks with active=…; the Sessions tab does not.
      renderChatSessionList(resp.sessions || [], /[?&]active=N/.test(path));
    } else {
      return false;
    }
    switchTab("chat");
    return true;
  }

  function handlePlaybackEvent(evt) {
    if (evt.type !== "api") return;
    if (handleChatPlayback(evt)) return;
    // Switch to the relevant tab so the operator sees the update.
    const path = evt.path || "";
    if      (path === "/run" || path === "/run_function" ||
             path === "/run_multipart")                   switchTab("chat");
    else if (path === "/session_summary_presets" ||
             (path.startsWith("/sessions/") && path.endsWith("/summary")))
                                                          switchTab("summary");
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
    } else if (path.startsWith("/sessions/") && path.endsWith("/summary")) {
      // Summary sub-path must be checked BEFORE the generic /sessions/{id}
      // renderer below, otherwise the summary payload leaks into #sess-detail.
      const r = evt.response || {};
      $("#summary-enabled").checked   = !!r.enabled;
      $("#summary-template").value    = r.template || "";
      $("#summary-content").textContent = r.content || "(no summary generated yet)";
      $("#summary-updated").textContent  = r.updated_at || "—";
      const _sid = (path.match(/^\/sessions\/([^/]+)\/summary$/) || [])[1] || "";
      if (_sid && !$("#summary-session-id").value.trim()) {
        $("#summary-session-id").value = decodeURIComponent(_sid);
      }
    } else if (path.startsWith("/sessions/")) {
      $("#sess-detail").textContent = JSON.stringify(evt.response, null, 2);
    } else if (path === "/sessions" || path.startsWith("/sessions?")) {
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
    } else if (path === "/session_summary_presets") {
      // Update in-memory registry so both dropdowns refresh in sync.
      summaryState.presets = Array.isArray(evt.response && evt.response.presets)
                              ? evt.response.presets : [];
      populateSummaryPresetDropdowns();
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
  loadAgents();            // best-effort; falls back on network error
  loadChatSessions(true);  // the chat sidebar's session list
  loadSummaryPresets(true); // populate summary preset dropdowns silently
  setStatus(`Ready. Backend: ${Api.getBackendUrl() || "(unset)"}`);
})();
