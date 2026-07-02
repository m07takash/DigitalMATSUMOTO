// ============================================================================
// Sample Agent Demo :: Video Exporter
// ----------------------------------------------------------------------------
// Turns a *saved* recording into a downloadable animation video (MP4). No LLM,
// no backend — this just re-plays the recorded chat turns as a canvas
// animation and captures the canvas with MediaRecorder.
//
//   1. The recording's /run turns are laid out as chat bubbles.
//   2. A virtual clock drives the animation: bubbles appear in order, the agent
//      shows a typing indicator, then its reply reveals character-by-character.
//   3. canvas.captureStream() feeds MediaRecorder, which we prefer to encode as
//      MP4 (video/mp4). Browsers without an MP4 encoder (e.g. Firefox) fall
//      back to WebM automatically — the download extension follows the format.
//
// Speed model
// -----------
//   The "base" pacing (SPEED = 1) is tuned so a human can comfortably read the
//   conversation. A speed multiplier of N compresses the virtual timeline by N,
//   so the rendered video is 1/N as long and plays back N× faster. Because
//   MediaRecorder captures in wall-clock time, generating a 2× video also takes
//   half the wall-clock time.
// ============================================================================

(function () {
  "use strict";

  const $ = (sel) => document.querySelector(sel);

  // --- Base pacing in *seconds at speed 1* (human-comfortable) ----------
  const PACE = {
    intro:          0.6,   // blank hold before the first bubble
    userAppear:     0.45,  // user bubble settle time
    gapAfterUser:   0.55,  // pause before the agent "thinks"
    typingMin:      0.9,   // minimum typing-indicator duration
    typingPerChar:  0.012, // extra typing time scaled by reply length
    typingMax:      2.2,   // cap on typing-indicator duration
    agentCps:       26,    // agent reply reveal speed (chars/sec)
    gapAfterAgent:  0.9,   // pause after a completed reply
    outro:          1.6,   // hold on the final frame
  };

  const RESOLUTIONS = {
    "720p":  { w: 1280, h: 720 },
    "1080p": { w: 1920, h: 1080 },
  };

  const state = {
    running: false,
    abort:   false,
    recorder: null,
  };

  // ------------------------------------------------------------------ boot
  function init() {
    refreshSelect();
    Recorder.onChange(refreshSelect);

    $("#btn-vid-generate").addEventListener("click", generate);
    $("#btn-vid-cancel").addEventListener("click", () => { state.abort = true; });

    // Report the encoding format the browser will actually use.
    const picked = pickMimeType();
    const fmtEl = $("#vid-format");
    if (fmtEl) {
      fmtEl.textContent = picked
        ? `${picked.ext.toUpperCase()} (${picked.mime})`
        : "unsupported — this browser cannot record canvas video";
    }
  }

  function refreshSelect() {
    const sel = $("#vid-select");
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">— select recording —</option>';
    for (const r of Recorder.list()) {
      const opt = document.createElement("option");
      opt.value = r.id;
      opt.textContent = `${r.title} (${r.events} events)`;
      sel.appendChild(opt);
    }
    if (current && Recorder.list().some((r) => r.id === current)) sel.value = current;
  }

  // ---------------------------------------------------- format negotiation
  // Prefer MP4; fall back to WebM. Returns { mime, ext } or null.
  function pickMimeType() {
    const candidates = [
      { mime: 'video/mp4;codecs="avc1.640028"', ext: "mp4" },
      { mime: 'video/mp4;codecs="avc1.42E01E"', ext: "mp4" },
      { mime: "video/mp4",                       ext: "mp4" },
      { mime: 'video/webm;codecs="vp9"',         ext: "webm" },
      { mime: 'video/webm;codecs="vp8"',         ext: "webm" },
      { mime: "video/webm",                      ext: "webm" },
    ];
    if (typeof MediaRecorder === "undefined") return null;
    for (const c of candidates) {
      try { if (MediaRecorder.isTypeSupported(c.mime)) return c; } catch (e) {}
    }
    return null;
  }

  // ------------------------------------------------------------- generate
  async function generate() {
    if (state.running) return;

    const id = $("#vid-select").value;
    if (!id) { setStatus("Select a recording first.", "err"); return; }
    const rec = Recorder.get(id);
    if (!rec) { setStatus("Recording not found: " + id, "err"); return; }

    const speed = clampSpeed(parseFloat($("#vid-speed").value));
    $("#vid-speed").value = speed;
    const fps = clampFps(parseInt($("#vid-fps").value, 10));
    const res = RESOLUTIONS[$("#vid-res").value] || RESOLUTIONS["720p"];

    const codec = pickMimeType();
    if (!codec) {
      setStatus("This browser cannot record canvas video (MediaRecorder unavailable).", "err");
      return;
    }

    const turns = extractTurns(rec);
    if (!turns.length) {
      setStatus("This recording has no chat turns (/run events) to animate.", "err");
      return;
    }

    // --- Set up the canvas --------------------------------------------
    const canvas = $("#vid-canvas");
    canvas.width = res.w;
    canvas.height = res.h;
    const ctx = canvas.getContext("2d");

    const scene = buildScene(ctx, rec, turns, res);

    // --- Set up MediaRecorder ------------------------------------------
    let stream;
    try {
      stream = canvas.captureStream(fps);
    } catch (e) {
      setStatus("captureStream failed: " + e.message, "err");
      return;
    }

    let recorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: codec.mime, videoBitsPerSecond: 6_000_000 });
    } catch (e) {
      setStatus("MediaRecorder init failed: " + e.message, "err");
      return;
    }

    const chunks = [];
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };

    const done = new Promise((resolve) => { recorder.onstop = resolve; });

    // --- UI state -------------------------------------------------------
    state.running = true;
    state.abort = false;
    state.recorder = recorder;
    setBusy(true);

    const totalVirtual = scene.totalVirtual;       // seconds at speed 1
    const realDuration = totalVirtual / speed;      // wall-clock seconds
    setStatus(
      `Recording ${codec.ext.toUpperCase()} @ ${res.w}×${res.h}, ${fps}fps, ×${speed} ` +
      `(≈${realDuration.toFixed(1)}s)…`
    );

    recorder.start();

    // --- Animation loop (wall-clock → virtual clock) --------------------
    let startReal = null;
    let curScroll = 0;

    await new Promise((resolve) => {
      function frame(nowMs) {
        if (startReal === null) startReal = nowMs;
        const realElapsed = (nowMs - startReal) / 1000;   // seconds
        const vt = realElapsed * speed;                    // virtual seconds

        curScroll = drawScene(ctx, scene, vt, curScroll);
        setProgress(Math.min(1, vt / totalVirtual));

        if (state.abort || vt >= totalVirtual) { resolve(); return; }
        requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    });

    // Flush the final frame so the last state is captured, then stop.
    drawScene(ctx, scene, scene.totalVirtual, curScroll);
    try { recorder.requestData(); } catch (e) {}
    recorder.stop();
    await done;
    stream.getTracks().forEach((t) => t.stop());

    state.running = false;
    state.recorder = null;
    setBusy(false);

    if (state.abort) {
      setStatus("Cancelled. (No file downloaded.)", "err");
      setProgress(0);
      return;
    }

    // --- Download -------------------------------------------------------
    const blob = new Blob(chunks, { type: codec.mime });
    const fname = `${rec.id}_x${String(speed).replace(".", "_")}.${codec.ext}`;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = fname;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);

    setProgress(1);
    setStatus(`Saved ${fname} (${(blob.size / 1e6).toFixed(2)} MB).`, "ok");
  }

  // -------------------------------------------------- scene construction
  // Pull chat turns (user_input + response) out of the recording in order.
  function extractTurns(rec) {
    const turns = [];
    for (const evt of rec.events || []) {
      if (evt.type !== "api") continue;
      if (evt.path !== "/run" && evt.path !== "/run_function") continue;
      const q = (evt.request && evt.request.user_input) || "";
      const a = (evt.response && evt.response.response) || "";
      if (!q && !a) continue;
      turns.push({ user: String(q), agent: String(a) });
    }
    return turns;
  }

  // Precompute wrapped layout + a virtual timeline for every bubble. Doing
  // this once (with the export font already set) keeps the per-frame draw cheap
  // and the layout stable while text reveals.
  function buildScene(ctx, rec, turns, res) {
    const H = res.h, W = res.w;
    const scale = H / 720;

    const S = {
      W, H, scale,
      titleH:     Math.round(70 * scale),
      margin:     Math.round(40 * scale),
      font:       `${Math.round(24 * scale)}px -apple-system, "Hiragino Sans", "Noto Sans JP", "Segoe UI", sans-serif`,
      metaFont:   `${Math.round(13 * scale)}px -apple-system, "Hiragino Sans", "Noto Sans JP", "Segoe UI", sans-serif`,
      titleFont:  `600 ${Math.round(22 * scale)}px -apple-system, "Hiragino Sans", "Noto Sans JP", "Segoe UI", sans-serif`,
      lineH:      Math.round(24 * scale * 1.5),
      padX:       Math.round(18 * scale),
      padY:       Math.round(12 * scale),
      gap:        Math.round(16 * scale),
      radius:     Math.round(14 * scale),
      title:      (rec.meta && rec.meta.title) || rec.id,
      bubbles:    [],
      totalVirtual: 0,
    };

    const chatW = W - S.margin * 2;
    const maxBubbleW = Math.round(chatW * 0.72);
    const textMaxW = maxBubbleW - S.padX * 2;

    ctx.font = S.font;

    let cursor = PACE.intro;
    for (const turn of turns) {
      if (turn.user) {
        const b = makeBubble(ctx, S, "user", turn.user, textMaxW);
        b.appearAt = cursor;
        b.revealStart = cursor;
        b.revealDur = PACE.userAppear;         // user text appears quickly
        cursor += PACE.userAppear + PACE.gapAfterUser;
        S.bubbles.push(b);
      }
      if (turn.agent) {
        const b = makeBubble(ctx, S, "agent", turn.agent, textMaxW);
        const typingDur = Math.min(
          PACE.typingMax,
          Math.max(PACE.typingMin, b.charCount * PACE.typingPerChar)
        );
        b.appearAt = cursor;                    // typing indicator shows here
        b.typingUntil = cursor + typingDur;     // then the bubble reveals
        b.revealStart = b.typingUntil;
        b.revealDur = Math.max(0.2, b.charCount / PACE.agentCps);
        cursor = b.revealStart + b.revealDur + PACE.gapAfterAgent;
        S.bubbles.push(b);
      }
    }
    S.totalVirtual = cursor + PACE.outro;
    return S;
  }

  function makeBubble(ctx, S, role, text, textMaxW) {
    const lines = wrapText(ctx, text, textMaxW);
    let width = 0;
    for (const ln of lines) width = Math.max(width, ctx.measureText(ln).width);
    const charCount = lines.reduce((n, ln) => n + ln.length, 0);
    return {
      role, lines, charCount,
      w: Math.round(width) + S.padX * 2,
      h: lines.length * S.lineH + S.padY * 2,
      appearAt: 0, typingUntil: 0, revealStart: 0, revealDur: 0,
    };
  }

  // -------------------------------------------------------- frame drawing
  // Returns the scroll position used for this frame.
  function drawScene(ctx, S, vt, prevScroll) {
    const { W, H, scale } = S;

    // Background.
    ctx.fillStyle = "#f6f7f9";
    ctx.fillRect(0, 0, W, H);

    // Title bar.
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, W, S.titleH);
    ctx.fillStyle = "#e3e6ea";
    ctx.fillRect(0, S.titleH - Math.max(1, Math.round(scale)), W, Math.max(1, Math.round(scale)));

    ctx.textBaseline = "middle";
    ctx.font = `${Math.round(22 * scale)}px sans-serif`;
    ctx.fillStyle = "#2a6df4";
    ctx.fillText("◆", S.margin, S.titleH / 2);
    ctx.font = S.titleFont;
    ctx.fillStyle = "#1f2328";
    ctx.fillText(S.title, S.margin + Math.round(32 * scale), S.titleH / 2);

    // Chat viewport (clipped).
    const viewTop = S.titleH + S.margin;
    const viewH = H - viewTop - S.margin;
    const viewLeft = S.margin;
    const viewW = W - S.margin * 2;

    // Lay out appeared bubbles top-to-bottom. Each bubble's *effective* height
    // grows as its text reveals, so total content height increases gradually
    // (one line at a time) rather than jumping by a whole bubble at once.
    const appeared = S.bubbles.filter((b) => vt >= b.appearAt);
    const effH = appeared.map((b) => effectiveHeight(S, b, vt));

    // Content-space bottom of the newest (last) bubble.
    let bottom = 0;
    for (let i = 0; i < appeared.length; i++) bottom += effH[i] + S.gap;
    bottom = Math.max(0, bottom - S.gap);

    // Pin that bottom to the viewport bottom: the freshest text is always fully
    // in-frame and never clipped. Because effH grows a line at a time, snapping
    // to the target still looks like a smooth scroll.
    const curScroll = Math.max(0, bottom - viewH);

    ctx.save();
    ctx.beginPath();
    ctx.rect(viewLeft, viewTop, viewW, viewH);
    ctx.clip();

    let y = viewTop - curScroll;
    ctx.font = S.font;
    appeared.forEach((b, i) => {
      const isTyping = b.role === "agent" && vt < b.typingUntil;
      // Only draw if within (or near) the viewport.
      if (y + effH[i] >= viewTop - S.gap && y <= viewTop + viewH + S.gap) {
        if (isTyping) drawTyping(ctx, S, b, viewLeft, viewW, y, vt);
        else          drawBubble(ctx, S, b, viewLeft, viewW, y, revealCount(b, vt), effH[i]);
      }
      y += effH[i] + S.gap;
    });
    ctx.restore();

    return curScroll;
  }

  function revealCount(b, vt) {
    if (vt <= b.revealStart) return 0;
    if (b.revealDur <= 0) return b.charCount;
    const frac = Math.min(1, (vt - b.revealStart) / b.revealDur);
    return Math.round(frac * b.charCount);
  }

  // Height a bubble occupies *right now* — grows with the revealed line count so
  // the layout (and scroll) advance smoothly instead of jumping a full bubble.
  function effectiveHeight(S, b, vt) {
    if (b.role === "agent" && vt < b.typingUntil) return Math.round(40 * S.scale);
    const rc = revealCount(b, vt);
    if (rc >= b.charCount) return b.h;
    let revealedLines = 0, seen = 0;
    for (const ln of b.lines) {
      if (rc > seen) revealedLines++; else break;
      seen += ln.length;
    }
    revealedLines = Math.max(1, revealedLines);
    return revealedLines * S.lineH + S.padY * 2;
  }

  function drawBubble(ctx, S, b, viewLeft, viewW, y, reveal, h) {
    const isUser = b.role === "user";
    const x = isUser ? (viewLeft + viewW - b.w) : viewLeft;

    // Bubble background (height grows with the revealed text).
    ctx.fillStyle = isUser ? "#e8effc" : "#f2f3f5";
    roundRect(ctx, x, y, b.w, h, S.radius);
    ctx.fill();

    // Text (revealed prefix only, but wrapped layout stays fixed).
    ctx.fillStyle = "#1f2328";
    ctx.textBaseline = "top";
    ctx.font = S.font;
    let remaining = reveal;
    let ty = y + S.padY;
    for (const ln of b.lines) {
      if (remaining <= 0) break;
      const shown = remaining >= ln.length ? ln : ln.slice(0, remaining);
      ctx.fillText(shown, x + S.padX, ty);
      remaining -= ln.length;
      ty += S.lineH;
    }
  }

  function drawTyping(ctx, S, b, viewLeft, viewW, y, vt) {
    // Small agent-side bubble with three pulsing dots.
    const scale = S.scale;
    const w = Math.round(70 * scale);
    const h = Math.round(40 * scale);
    const x = viewLeft;
    ctx.fillStyle = "#f2f3f5";
    roundRect(ctx, x, y, w, h, S.radius);
    ctx.fill();

    const r = Math.round(5 * scale);
    const cy = y + h / 2;
    const gap = Math.round(16 * scale);
    const cx0 = x + Math.round(20 * scale);
    for (let i = 0; i < 3; i++) {
      // Phase each dot; use vt so it animates independent of frame rate.
      const phase = (vt * 3 + i * 0.4) % 1;
      const alpha = 0.35 + 0.45 * (0.5 + 0.5 * Math.sin(phase * Math.PI * 2));
      ctx.fillStyle = `rgba(101,109,118,${alpha.toFixed(3)})`;
      ctx.beginPath();
      ctx.arc(cx0 + i * gap, cy, r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // ------------------------------------------------------------- helpers
  // Greedy word/CJK-aware wrap. Honors explicit newlines.
  function wrapText(ctx, text, maxWidth) {
    const out = [];
    for (const para of String(text).split("\n")) {
      if (para === "") { out.push(""); continue; }
      const tokens = para.match(/[　-鿿＀-￯]|[^\s　-鿿＀-￯]+|\s+/g) || [];
      let line = "";
      for (const tok of tokens) {
        const trial = line + tok;
        if (ctx.measureText(trial).width > maxWidth && line !== "") {
          out.push(line.replace(/\s+$/, ""));
          line = /^\s+$/.test(tok) ? "" : tok;
        } else {
          line = trial;
        }
      }
      out.push(line.replace(/\s+$/, ""));
    }
    return out.length ? out : [""];
  }

  function roundRect(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y,     x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x,     y + h, r);
    ctx.arcTo(x,     y + h, x,     y,     r);
    ctx.arcTo(x,     y,     x + w, y,     r);
    ctx.closePath();
  }

  function clampSpeed(v) {
    if (!isFinite(v) || v <= 0) return 1;
    return Math.min(16, Math.max(0.25, Math.round(v * 100) / 100));
  }
  function clampFps(v) {
    if (!isFinite(v) || v <= 0) return 30;
    return Math.min(60, Math.max(10, v));
  }

  // ------------------------------------------------------------------ UI
  function setBusy(busy) {
    $("#btn-vid-generate").disabled = busy;
    $("#btn-vid-cancel").disabled = !busy;
    $("#vid-select").disabled = busy;
    $("#vid-speed").disabled = busy;
    $("#vid-fps").disabled = busy;
    $("#vid-res").disabled = busy;
  }
  function setProgress(frac) {
    const bar = $("#vid-progress-bar");
    if (bar) bar.style.width = `${Math.round(frac * 100)}%`;
  }
  function setStatus(msg, cls) {
    const el = $("#vid-status");
    if (!el) return;
    el.textContent = msg;
    el.className = "ed-status" + (cls ? " " + cls : "");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
