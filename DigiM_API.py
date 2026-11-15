import os
import re
import json
import time
import base64
import uuid
import threading
import traceback
from datetime import datetime
from urllib.parse import quote
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, File, UploadFile, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
import uvicorn

import DigiM_Session as dms
import DigiM_Execute as dme
import DigiM_Tool as dmt
import DigiM_Util as dmu
import DigiM_MstStore as dmms
import DigiM_Agent as dma
import DigiM_GeneFeedback as dmgf
import DigiM_AgentPersona as dap

# Load the system.env file and set environment variables
load_dotenv("system.env")
api_agent_file = os.getenv("API_AGENT_FILE")
api_port = os.getenv("API_PORT")
api_default_session_name = os.getenv("API_DEFAULT_SESSION_NAME")

app = FastAPI()

# CORS — the demo frontend (demo/sample_demo/*.html) is a static page served
# from a different origin (e.g. `python3 -m http.server` or the Azure host on
# a different port), so cross-origin fetch() requires an explicit allow-list
# from the API side. Without this middleware the browser fails preflight
# (OPTIONS /run → 405) and reports "Failed to fetch".
#
# `allow_origins=["*"]` is intentionally permissive for demo use. If this API
# ever exposes authenticated endpoints, tighten to the exact demo origin(s)
# and set `allow_credentials=False` (which is required whenever origins="*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Request / Response ----------
class ServiceInfo(BaseModel):
    SERVICE_ID: str
    SERVICE_DATA: Dict[str, Any] = {}

class UserInfo(BaseModel):
    USER_ID: str
    USER_DATA: Dict[str, Any] = {}

class Attachment(BaseModel):
    """A single file attachment carried inline as base64.

    - `filename` is the display / on-disk name. The basename is used and
      path separators are stripped so callers can't traverse outside the
      per-request temp folder.
    - `content_base64` is the raw file bytes, standard base64-encoded.
    - `content_type` is informational; downstream consumers infer file
      type from the filename extension the same way the WebUI does.
    """
    filename: str
    content_base64: str
    content_type: Optional[str] = None

class InputData(BaseModel):
    service_info: ServiceInfo
    user_info: UserInfo
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    user_input: str
    situation: Dict[str, Any] = {"TIME": "", "SITUATION": ""}
    agent_file: Optional[str] = None
    engine: Optional[str] = None
    # Exec Setting (API defaults)
    stream_mode: Optional[bool] = None
    save_digest: Optional[bool] = None
    memory_use: Optional[bool] = None
    magic_word_use: Optional[bool] = None
    meta_search: Optional[bool] = None
    rag_query_gene: Optional[bool] = None
    web_search: Optional[bool] = None
    web_search_engine: Optional[str] = None
    # When ON (default in DigiM_Execute), web-search results are wrapped in
    # an instruction telling the LLM to treat them as reference material
    # only. Turn OFF to pass the raw snippet through unwrapped.
    web_search_guardrail: Optional[bool] = None
    private_mode: Optional[bool] = None
    thinking_mode: Optional[bool] = None
    # Multi-turn Thinking upper bound (1-5). Only relevant when
    # thinking_mode is on. 1 = legacy single-pass behaviour.
    max_thinking_turns: Optional[int] = None
    # Output-side toggles added in the recent WebUI refresh — each maps to a
    # corresponding execution dict key consumed by DigiM_Execute.
    #   insert_citations   → INSERT_CITATIONS (Reference Info section with
    #                         [N] markers for Web / Book sources)
    #   cite_knowledge     → CITE_KNOWLEDGE  (Reference Knowledge section
    #                         built by the second-pass selector agent)
    #   diagram_mode       → DIAGRAM_MODE    (asks LLM to use tables +
    #                         Mermaid diagrams where they clarify)
    #   emphasis_mode      → EMPHASIS_MODE   (asks LLM to bold key points
    #                         and use headings on long answers)
    insert_citations: Optional[bool] = None
    cite_knowledge: Optional[bool] = None
    diagram_mode: Optional[bool] = None
    emphasis_mode: Optional[bool] = None
    # SKILL selection. Omit `skills` and the turn starts with whatever the
    # agent declares `SKILL.TOOLS.<name>.DEFAULT: true` for — the same set the
    # WebUI picker opens with. Pass it to replace that set for this turn
    # (`[]` runs none); unknown names come back in `skills_ignored`.
    #   skills : names to run, replacing the agent defaults
    #   skill  : one name to run on top, the API form of the WebUI's `/<name>`
    # A default-only BEFORE skill stays a candidate Thinking may decline; a
    # name passed here always runs. Unlike the four flag skills below, a
    # function skill (refine_expression, mood_score, …) has no execution flag
    # and can only be reached this way.
    skills: Optional[List[str]] = None
    skill: Optional[str] = None
    # Thinking Mode. All three fall back to the agent JSON's top-level
    # `THINKING` block (MODE / TARGETS / MAX_TURNS) when unset, so an agent
    # that asks for Thinking gets it without the caller restating it.
    #   thinking_targets takes the UI labels: Habit, Web Search, RAG Query,
    #   Books, Skills, Personas.
    thinking_targets: Optional[List[str]] = None
    # Cap for PersonaSelector when the practice uses PERSONAS="THINKING".
    max_personas: Optional[int] = None
    # Reply in the language the user wrote in, overriding PERSONALITY.LANGUAGE.
    match_input_language: Optional[bool] = None
    # User memory (information about the dialogue partner)
    #   user_memory_layers takes top priority when set (subset of ["persona","nowaday","history"] / [] turns all off)
    #   If unset and user_memory=True, all layers are ON; False turns all off
    #   If neither is set, falls back to users.json / USER_MEMORY_DEFAULT_LAYERS (legacy behavior)
    user_memory: Optional[bool] = None
    user_memory_layers: Optional[List[str]] = None
    # Attachments — pass files that the agent should see as context. Same
    # semantics as the WebUI's file uploader: files are saved to a temp
    # folder and their local paths are forwarded to DigiMatsuExecute as
    # `in_contents`. Three intake channels are supported and can be mixed:
    #   attachments           : list of {filename, content_base64} objects
    #   attachment_urls       : list of URLs that the server fetches
    #                           (uses DigiM_UrlFetch under the hood)
    #   fetch_urls_from_input : when true, URLs found inside `user_input`
    #                           are auto-fetched (WebUI parity behavior)
    # For larger files or when base64 overhead is unwelcome, use the
    # sibling endpoint POST /run_multipart which accepts multipart/form-data.
    attachments: List[Attachment] = []
    attachment_urls: List[str] = []
    fetch_urls_from_input: Optional[bool] = None
    # Session Summary — optional per-session dossier maintained across turns.
    # When either field is set, the API writes it to `status.yaml` BEFORE
    # dispatching the run, so the injection + background-update paths in
    # DigiMatsuExecute_Practice pick it up on the very same turn. Leave both
    # None to inherit whatever is already saved for this session (WebUI or
    # a prior API call). See:
    #   GET  /sessions/{id}/summary          → read enabled/template/content
    #   POST /sessions/{id}/summary          → change enabled/template
    #   GET  /session_summary_presets        → list shipped preset templates
    session_summary_enabled: Optional[bool] = None
    session_summary_template: Optional[str] = None
    # WebUI chat-sidebar parity. Choices come from GET /agents/{file}/chat_options.
    #   imagegen_engine : IMAGEGEN engine name (like `engine` for the LLM)
    #   memory_save / memory_similarity : the Conversation Settings toggles
    #   personas  : persona_id list. Two or more run in parallel as one turn,
    #               exactly as picking several in the WebUI does.
    #   org       : the ORG dict the personas belong to. Omitted, the agent's
    #               ORG list is searched; the first ORG is still passed so
    #               Thinking's "Personas" target has one to choose from.
    #   books     : BOOK RAG_NAMEs added to this turn (ignored ones are reported)
    #   include_query : prefix the previous multi-persona turn's answers
    #   personality   : PERSONALITY fields to override (LANGUAGE, SPEAKING_STYLE,
    #                   CHARACTER, BIG5, ...), deep-merged onto the agent JSON
    #   overwrite_items : raw overwrite dict for anything else (HABIT/KNOWLEDGE ...)
    imagegen_engine: Optional[str] = None
    memory_save: Optional[bool] = None
    memory_similarity: Optional[bool] = None
    personas: Optional[List[str]] = None
    org: Optional[Dict[str, Any]] = None
    books: Optional[List[str]] = None
    include_query: Optional[bool] = None
    personality: Optional[Dict[str, Any]] = None
    overwrite_items: Dict[str, Any] = {}
    # Other execution settings (when passing fields not covered above)
    execution: Dict[str, Any] = {}

LOCK_WAIT_MAX = 60   # Maximum seconds to wait for a session lock
LOCK_POLL_INTERVAL = 2  # Polling interval (seconds)

# Upper bound on per-file bytes for base64 attachments. Multipart is not
# capped here; front the API with an NGINX `client_max_body_size` for that.
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024   # 25 MB per file
MAX_ATTACHMENTS = 20                       # count per request

def _api_temp_folder() -> str:
    """Create a fresh subfolder under TEMP_FOLDER for one API request.

    Each request gets its own uuid-suffixed directory so concurrent uploads
    with duplicate filenames don't collide. The WebUI writes to the same
    TEMP_FOLDER root; we scope under `.../api/<uuid>/` to keep the two
    origins separate at a glance.
    """
    _setting = dmu.read_yaml_file("setting.yaml") or {}
    base = _setting.get("TEMP_FOLDER", "user/common/temp/")
    subdir = os.path.join(base.rstrip("/\\"), "api", uuid.uuid4().hex[:16])
    os.makedirs(subdir, exist_ok=True)
    return subdir + os.sep

def _sanitize_filename(name: str, default: str = "attachment.bin") -> str:
    base = os.path.basename(name or "").replace(os.sep, "_")
    if os.altsep:
        base = base.replace(os.altsep, "_")
    return base or default

def _prepare_attachments(
    tmp_dir: str,
    attachments: List[Attachment],
    attachment_urls: List[str],
    user_input: str,
    fetch_urls_from_input: Optional[bool],
) -> (List[str], List[Dict[str, Any]]):
    """Materialize every attachment channel into local files and return
    (list of paths, list of per-file metadata for the API response).
    """
    if attachments and len(attachments) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=413,
            detail=f"Too many attachments: {len(attachments)} > {MAX_ATTACHMENTS}")

    paths: List[str] = []
    processed: List[Dict[str, Any]] = []

    # 1) base64-inlined attachments
    for att in (attachments or []):
        try:
            raw = base64.b64decode(att.content_base64 or "", validate=True)
        except Exception as e:
            raise HTTPException(status_code=400,
                detail=f"Invalid base64 for {att.filename!r}: {e}")
        if len(raw) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413,
                detail=f"Attachment {att.filename!r} exceeds {MAX_ATTACHMENT_BYTES} bytes")
        safe = _sanitize_filename(att.filename)
        # Prevent same-request name collisions between multiple attachments.
        p = _unique_path(tmp_dir, safe)
        with open(p, "wb") as f:
            f.write(raw)
        paths.append(p)
        processed.append({
            "filename": os.path.basename(p),
            "size_bytes": len(raw),
            "content_type": att.content_type,
            "source": "base64",
        })

    # 2) attachment_urls — server fetches
    if attachment_urls:
        try:
            import DigiM_UrlFetch as dmuf
            _res = dmuf.fetch_urls_from_text(
                "\n".join(attachment_urls), tmp_dir, include_subpages=False,
            )
        except Exception as e:
            raise HTTPException(status_code=502,
                detail=f"Failed to fetch attachment_urls: {e}")
        for _p in _res.get("saved_paths", []):
            paths.append(_p)
            processed.append({
                "filename": os.path.basename(_p),
                "size_bytes": os.path.getsize(_p) if os.path.exists(_p) else None,
                "source": "url",
            })
        for _b in _res.get("blocked", []):
            processed.append({"filename": None, "url": _b.get("url"),
                              "source": "url", "blocked": _b.get("reason")})

    # 3) fetch URLs found inside user_input (opt-in)
    if fetch_urls_from_input and user_input:
        try:
            import DigiM_UrlFetch as dmuf
            _res2 = dmuf.fetch_urls_from_text(user_input, tmp_dir, include_subpages=False)
            for _p in _res2.get("saved_paths", []):
                paths.append(_p)
                processed.append({
                    "filename": os.path.basename(_p),
                    "size_bytes": os.path.getsize(_p) if os.path.exists(_p) else None,
                    "source": "user_input_url",
                })
        except Exception:
            # Best-effort — mirrors WebUI: URL fetch errors don't fail the turn.
            pass

    return paths, processed

def _unique_path(folder: str, filename: str) -> str:
    """Return a path in `folder` that doesn't clash with an existing sibling.

    Two attachments in the same request with the same original name become
    e.g. `report.pdf` and `report (1).pdf`.
    """
    p = os.path.join(folder, filename)
    if not os.path.exists(p):
        return p
    stem, ext = os.path.splitext(filename)
    for i in range(1, 1000):
        cand = os.path.join(folder, f"{stem} ({i}){ext}")
        if not os.path.exists(cand):
            return cand
    return os.path.join(folder, f"{stem}_{uuid.uuid4().hex[:6]}{ext}")

# ---------- References ----------
# Each turn yields an `output_reference` dict from DigiMatsuExecute_Practice that
# mixes structured data (Web_search) with log-format strings (knowledge_ref /
# memory_ref). The demo UI wants uniformly structured JSON so it can render a
# reference sidebar with per-item similarity strength. `_shape_references()`
# is the single place that flattens the internal format into that shape.
def _shape_references(output_reference: dict) -> Dict[str, Any]:
    """Return a UI-friendly view of the execution's references.

    Output shape:
      {
        "knowledge":  [ {title, snippet, similarity_prompt, similarity_response,
                         rag_name, chunk_id, category, ...}, ... ],
        "page_index": [ {page_id, title, category, summary, ...}, ... ],
        "web":        { "engine": str, "model": str, "search_text": str,
                        "duration_sec": float,
                        "urls": [ {title, url, date, ...}, ... ] },
        "user_memory": [ {log|text, ...}, ... ],
      }
    """
    out: Dict[str, Any] = {
        "knowledge": [],
        "page_index": [],
        "web": {},
        "user_memory": [],
    }
    if not isinstance(output_reference, dict):
        return out

    # ---- Knowledge / PageIndex -----------------------------------------
    # `knowledge_ref` is a list of LOG_TEMPLATE strings. We parse each into
    # a dict, split out entries carrying `page_id` as page_index items, and
    # keep the rest as generic knowledge items. Similarity fields survive
    # the parse and drive the client-side strength coloring.
    for raw in (output_reference.get("knowledge_ref") or []):
        if not isinstance(raw, str):
            continue
        try:
            d = dmu.parse_log_template(raw)
        except Exception:
            d = {"_raw": raw}
        # keep the raw string too so operators can debug the original entry
        d.setdefault("_raw", raw)
        # normalise a UI-friendly snippet
        for src in ("value_text_short", "value_text", "summary", "title"):
            if d.get(src):
                d.setdefault("snippet", str(d[src])[:140])
                break
        if "page_id" in d:
            out["page_index"].append(d)
        else:
            out["knowledge"].append(d)

    # ---- Web search ----------------------------------------------------
    ws = output_reference.get("Web_search") or {}
    if isinstance(ws, dict) and ws:
        out["web"] = {
            "engine":       ws.get("engine") or "",
            "model":        ws.get("model") or "",
            "search_text":  ws.get("search_text") or "",
            "duration_sec": ws.get("duration_sec"),
            "urls":         [
                {"title": u.get("title") or "",
                 "url":   u.get("url") or "",
                 "date":  u.get("date") or ""}
                for u in (ws.get("urls") or []) if isinstance(u, dict)
            ],
        }

    # ---- User memory ---------------------------------------------------
    # memory_ref entries look like [{"log": "..."}], we forward them as-is.
    for m in (output_reference.get("memory_ref") or []):
        if isinstance(m, dict):
            out["user_memory"].append(m)
        elif isinstance(m, str):
            out["user_memory"].append({"log": m})

    return out

# ---------- Execution function ----------
def _agent_data(agent_file: str) -> dict:
    try:
        return dmu.read_json_file(agent_file, dma.agent_folder_path) or {}
    except Exception:
        return {}


def _agent_orgs(agent_data: dict) -> list:
    return [o for o in (agent_data.get("ORG") or []) if isinstance(o, dict) and o]


def _resolve_personas(agent_file: str, agent_data: dict, persona_ids, org):
    """(persona dicts, org, ignored ids). The WebUI resolves ids inside the ORG
    picked in its selectbox; a caller that names no ORG gets the first of the
    agent's ORGs that knows the ids."""
    if not persona_ids:
        return [], org, []
    orgs = [org] if isinstance(org, dict) and org else _agent_orgs(agent_data)
    for o in orgs:
        try:
            cands = dap.find_personas_by_org(
                o, template_agent=agent_file,
                persona_files=agent_data.get("PERSONA_FILES") or None,
                source=agent_data.get("PERSONA_SOURCE"))
        except Exception:
            continue
        by_id = {p.get("persona_id"): p for p in cands}
        picked = [by_id[pid] for pid in persona_ids if pid in by_id]
        if picked:
            return picked, o, [pid for pid in persona_ids if pid not in by_id]
    return [], org, list(persona_ids)


def _resolve_books(agent_data: dict, names):
    if not names:
        return [], []
    books = [b for b in (agent_data.get("BOOK") or [])
             if isinstance(b, dict) and dma.is_entry_active(b, True)]
    picked = [b for b in books if b.get("RAG_NAME") in names]
    known = {b.get("RAG_NAME") for b in picked}
    return picked, [n for n in names if n not in known]


def _include_query_input(session_id: str, user_input: str):
    """(input, rag_query_text) the WebUI's Include Query builds: when the last
    turn ran several personas, their answers lead the input while RAG still
    searches with the bare question. Parallel personas mark the turn
    MEMORY_FLG=N; a practice with chain PERSONAS marks each answer instead."""
    if not session_id or not dms.get_session_data(session_id):
        return user_input, ""
    hist = dms.DigiMSession(session_id).chat_history_active_dict or {}
    if not hist:
        return user_input, ""
    block = hist.get(max(hist.keys(), key=int), {})
    _personas = sum(1 for k, v in block.items()
                    if k != "SETTING" and ((v or {}).get("setting") or {}).get("persona_id"))
    if (block.get("SETTING") or {}).get("MEMORY_FLG", "Y") != "N" and _personas < 2:
        return user_input, ""
    blobs = []
    for k in sorted([k for k in block if k != "SETTING"], key=int):
        sub = block[k]
        text = (sub.get("response") or {}).get("text") or ""
        name = (sub.get("setting") or {}).get("persona_name") or (sub.get("setting") or {}).get("name") or ""
        if text:
            blobs.append(f"- {name}:\n{text}")
    if not blobs:
        return user_input, ""
    return ("[Each persona's previous response]\n" + "\n\n".join(blobs)
            + "\n\n[Current question]\n" + user_input), user_input


def _saved_references(entry: dict) -> dict:
    """The saved turn keeps the same three sources the live run hands back as
    `output_reference`, under different keys."""
    ref = (entry.get("response") or {}).get("reference") or {}
    return {
        "knowledge_ref": ref.get("knowledge_rag") or [],
        "memory_ref": ref.get("memory") or [],
        "Web_search": (entry.get("prompt") or {}).get("web_search") or {},
    }


def _turn_answers(session_id: str, seq) -> list:
    """Every answer of one turn (one per persona / chain agent), display-ready."""
    turn = (dms.get_session_data(session_id) or {}).get(str(seq)) or {}
    out = []
    for k in sorted([k for k in turn if str(k).isdigit()], key=int):
        e = turn[k] if isinstance(turn[k], dict) else {}
        s = e.get("setting") or {}
        if s.get("type") not in ("LLM", "IMAGEGEN"):
            continue
        r = e.get("response") or {}
        out.append({
            "sub_seq": k,
            "type": s.get("type"),
            "name": s.get("name", ""),
            "persona_id": s.get("persona_id", ""),
            "persona_name": s.get("persona_name", ""),
            "response": r.get("text") or "",
            "response_display": (r.get("text") or "") + dmt.render_response_tail(e),
            "images": [_content_ref(session_id, i) for i in (e.get("image") or {}).values()
                       if isinstance(i, dict)],
        })
    return out


def exec_function(service_info: dict, user_info: dict, session_id: str, session_name: str,
                  user_input: str, situation: dict, agent_file: str, engine: str, execution: dict,
                  uploaded_contents: Optional[List[str]] = None,
                  session_summary_enabled: Optional[bool] = None,
                  session_summary_template: Optional[str] = None,
                  imagegen_engine: str = "",
                  overwrite_items: Optional[dict] = None,
                  add_knowledge: Optional[list] = None,
                  personas: Optional[list] = None,
                  org: Optional[dict] = None,
                  rag_query_text: str = "",
                  wait_for_lock: bool = True) -> dict:
    uploaded_contents = list(uploaded_contents or [])

    # Set up the session (issue a new ID if not specified)
    if not session_id:
        session_id = "API" + dms.set_new_session_id()
    # Loading a history reads the whole session, so it is done once here.
    _hist_before = dms.get_session_data(session_id) or {}
    seq_before = max((int(k) for k in _hist_before if str(k).isdigit()), default=0)
    # A continued session keeps the name it already has; only a session that
    # never got one is named after this turn.
    if not session_name and _hist_before:
        session_name = dms.get_session_name(session_id)

    # Session Summary inline configuration. When either field is set, persist
    # it to status.yaml BEFORE dispatch so the same turn benefits from
    # injection + background auto-update. Missing values (None) keep the
    # existing session-scoped state untouched.
    if session_summary_enabled is not None or session_summary_template is not None:
        try:
            _sess_cfg = dms.DigiMSession(session_id, session_name)
            _cur_enabled, _cur_template, _, _ = _sess_cfg.get_session_summary()
            _new_enabled = (_cur_enabled if session_summary_enabled is None
                              else bool(session_summary_enabled))
            _new_template = (_cur_template if session_summary_template is None
                              else str(session_summary_template))
            _sess_cfg.save_session_summary_settings(_new_enabled, _new_template)
        except Exception:
            pass  # Non-fatal — the run still proceeds without the summary.

    # Wait for the session lock (run_async locks before it hands off)
    if wait_for_lock:
        waited = 0
        while waited < LOCK_WAIT_MAX:
            status = dms.get_status_data(session_id).get("status", "")
            if status != "LOCKED":
                break
            time.sleep(LOCK_POLL_INTERVAL)
            waited += LOCK_POLL_INTERVAL
        else:
            raise HTTPException(status_code=429, detail=f"Session {session_id} is locked. Retry after a moment.")

    # Execution settings
    if not execution or "LAST_ONLY" not in execution:
        execution["LAST_ONLY"] = True

    # Engine override
    overwrite_items = dict(overwrite_items or {})
    if engine or imagegen_engine:
        agent_data = _agent_data(agent_file)
        _eng = dict(overwrite_items.get("ENGINE") or {})
        if engine and engine in agent_data.get("ENGINE", {}).get("LLM", {}):
            _eng["LLM"] = agent_data["ENGINE"]["LLM"][engine]
        if imagegen_engine and imagegen_engine in agent_data.get("ENGINE", {}).get("IMAGEGEN", {}):
            _eng["IMAGEGEN"] = agent_data["ENGINE"]["IMAGEGEN"][imagegen_engine]
        if _eng:
            overwrite_items["ENGINE"] = _eng

    # Execute through the same entry point as the WebUI chat: with 0/1 persona
    # it is DigiMatsuExecute_Practice, with more it runs them in parallel.
    response_chunks = []
    output_reference = {}
    for response_service_info, response_user_info, response_chunk, ref in dme.DigiMatsuExecute_MultiPersona(
        service_info, user_info, session_id, session_name, agent_file, user_input,
        in_contents=uploaded_contents,
        in_situation=situation, in_overwrite_items=overwrite_items,
        in_add_knowledge=list(add_knowledge or []), in_execution=execution,
        in_personas=list(personas or []), in_rag_query_text=rag_query_text or "",
        in_org=org,
    ):
        if response_chunk and not str(response_chunk).startswith("[STATUS]"):
            response_chunks.append(response_chunk)
        if ref:
            output_reference = ref

    if len(response_chunks) == 1 and not isinstance(response_chunks[0], str):
        response = response_chunks[0]
    else:
        response = "".join(map(str, response_chunks))

    # Auto-generate the session name
    if not session_name:
        session = dms.DigiMSession(session_id, session_name)
        _, _, new_session_name, _, _, _ = dmt.gene_session_name(
            service_info, user_info, session.session_id, session.session_name, "", user_input)
        session_name = f"(User:{user_info['USER_ID']}){new_session_name}"
        session.chg_session_name(session_name)

    # The AFTER phase runs after the stream is already drained and writes only
    # to the store: a MERGE="REPLACE" skill rewrote the answer and
    # MERGE="APPEND" output never passed through here at all. Reading the saved
    # turn back is what makes `response` the answer of record rather than the
    # draft that happened to be streamed.
    skills_out = {}
    ref_sections = ""
    response_display = response
    seq = None
    sub_seq = None
    answers = []
    try:
        _sess = dms.DigiMSession(session_id, session_name)
        _seq = _sess.get_seq_history()
        if _seq > seq_before:
            seq = str(_seq)
            _sub, _stored = dme._saved_answer(_sess, _seq)
            if _stored:
                response = _stored
            sub_seq = _sub
            _entry = ((_sess.get_history() or {}).get(str(_seq)) or {}).get(_sub) or {}
            _resp = _entry.get("response") or {}
            if isinstance(_resp.get("skills"), dict):
                skills_out = _resp["skills"]
            if isinstance(_resp.get("ref_sections"), str):
                ref_sections = _resp["ref_sections"]
            response_display = response + dmt.render_response_tail(_entry)
            answers = _turn_answers(session_id, _seq)
            if not output_reference and _entry:
                output_reference = _saved_references(_entry)
    except Exception:
        # MEMORY_SAVE=False saves no turn to read back; the streamed text is
        # then all there is.
        response_display = response

    return {
        "session_id": session_id,
        "session_name": session_name,
        # Where the answer of record was saved (None when MEMORY_SAVE=False).
        # Use them with /feedback and /sessions/{id}/turns/{seq}/... .
        "seq": seq,
        "sub_seq": sub_seq,
        "response": response,
        # The answer with its reference sections and then MERGE="APPEND"
        # skill output underneath, in SKILL.ORDER — what the WebUI shows in
        # the chat bubble.
        "response_display": response_display,
        # The `## Reference Info` / `## Reference Knowledge` sections, kept
        # out of `response`. Empty when neither was produced.
        "ref_sections": ref_sections,
        # {name: {phase, merge, header, order, text, model, tokens, error}} for
        # every SKILL that ran after the answer. Empty when none did.
        "skills": skills_out,
        # One row per answer of the turn — several when personas ran in
        # parallel or a chain has more than one agent.
        "answers": answers,
        # Structured references so the client can render a per-turn reference
        # panel without re-fetching /sessions/{id}. Empty when the agent didn't
        # touch any RAG / web / user-memory sources for this turn.
        "references": _shape_references(output_reference),
    }

# ---------- Endpoints ----------

def _agent_thinking_block(agent_file: str) -> dict:
    try:
        data = dmu.read_json_file(agent_file, dma.agent_folder_path)
    except Exception:
        return {}
    t = data.get("THINKING")
    return t if isinstance(t, dict) else {}


_API_EXECUTION_DEFAULTS = {
    "STREAM_MODE": True,
    "SAVE_DIGEST": True,
    "MEMORY_USE": True,
    "MEMORY_SAVE": True,
    "MEMORY_SIMILARITY": False,
    "MAGIC_WORD_USE": False,
    "META_SEARCH": True,
    "RAG_QUERY_GENE": True,
    "WEB_SEARCH": False,
    "WEB_SEARCH_ENGINE": "OpenAI",
    "PRIVATE_MODE": False,
}

_EXECUTION_DEFAULT_KEYS = ("STREAM_MODE", "MEMORY_USE", "MEMORY_SAVE", "SAVE_DIGEST",
                           "PRIVATE_MODE", "MAGIC_WORD_USE", "RAG_QUERY_GENE",
                           "META_SEARCH", "WEB_SEARCH_GUARDRAIL")


def _agent_execution_defaults(agent_file: str) -> dict:
    e = _agent_data(agent_file).get("EXECUTION_DEFAULTS")
    if not isinstance(e, dict):
        return {}
    out = {k: bool(e[k]) for k in _EXECUTION_DEFAULT_KEYS if k in e}
    if "MAX_PERSONAS" in e:
        try:
            out["MAX_PERSONAS"] = max(1, min(int(e["MAX_PERSONAS"]), 20))
        except (TypeError, ValueError):
            pass
    if isinstance(e.get("WEB_SEARCH_ENGINE"), str) and e["WEB_SEARCH_ENGINE"]:
        out["WEB_SEARCH_ENGINE"] = e["WEB_SEARCH_ENGINE"]
    return out


def _agent_skill_tools(agent_file: str) -> dict:
    try:
        data = dmu.read_json_file(agent_file, dma.agent_folder_path)
    except Exception:
        return {}
    try:
        return dma.normalize_skill_tools(data.get("SKILL") or {})
    except Exception:
        return {}


def _build_execution_dict(data: InputData, agent_file: str = "") -> tuple:
    """Assemble the `execution` dict from API defaults + the agent JSON +
    data.execution + explicit flag fields (each layer overrides the previous).

    Returns `(execution, skills_ignored)`.
    """
    execution = dict(_API_EXECUTION_DEFAULTS)
    # agent.EXECUTION_DEFAULTS sits over the API defaults, as it sits over the
    # user's Defaults in the WebUI.
    execution.update(_agent_execution_defaults(agent_file))
    # The agent's own THINKING block sits under data.execution and the
    # explicit fields, matching the WebUI precedence
    # (agent.THINKING > user default > hardcoded).
    _thinking = _agent_thinking_block(agent_file)
    if "MODE" in _thinking:
        execution["THINKING_MODE"] = bool(_thinking["MODE"])
    if isinstance(_thinking.get("TARGETS"), list):
        execution["_THINKING_TARGET_LABELS"] = list(_thinking["TARGETS"])
    if "MAX_TURNS" in _thinking:
        try:
            execution["MAX_THINKING_TURNS"] = max(1, min(int(_thinking["MAX_TURNS"]), 5))
        except (TypeError, ValueError):
            pass

    execution.update(data.execution or {})
    _flag_map = {
        "STREAM_MODE": data.stream_mode,
        "SAVE_DIGEST": data.save_digest,
        "MEMORY_USE": data.memory_use,
        "MEMORY_SAVE": data.memory_save,
        "MEMORY_SIMILARITY": data.memory_similarity,
        "MAGIC_WORD_USE": data.magic_word_use,
        "META_SEARCH": data.meta_search,
        "RAG_QUERY_GENE": data.rag_query_gene,
        "WEB_SEARCH": data.web_search,
        "WEB_SEARCH_ENGINE": data.web_search_engine,
        "WEB_SEARCH_GUARDRAIL": data.web_search_guardrail,
        "PRIVATE_MODE": data.private_mode,
        "THINKING_MODE": data.thinking_mode,
        "INSERT_CITATIONS": data.insert_citations,
        "CITE_KNOWLEDGE": data.cite_knowledge,
        "DIAGRAM_MODE": data.diagram_mode,
        "EMPHASIS_MODE": data.emphasis_mode,
        "MATCH_INPUT_LANGUAGE": data.match_input_language,
        "MAX_PERSONAS": data.max_personas,
    }
    for key, val in _flag_map.items():
        if val is not None:
            execution[key] = val
    # Multi-turn Thinking cap: mirror the WebUI clamp so a stray large
    # value from an API caller can't blow up cost / latency.
    if data.max_thinking_turns is not None:
        try:
            _mt = int(data.max_thinking_turns)
        except (TypeError, ValueError):
            _mt = 1
        execution["MAX_THINKING_TURNS"] = max(1, min(_mt, 5))

    # User memory enable/disable (Execute reads execution["USER_MEMORY_LAYERS"]
    # as top priority; if unset, falls back to users.json / USER_MEMORY_DEFAULT_LAYERS)
    _valid_layers = ("persona", "nowaday", "history")
    if data.user_memory_layers is not None:
        execution["USER_MEMORY_LAYERS"] = [
            l.strip().lower() for l in data.user_memory_layers
            if isinstance(l, str) and l.strip().lower() in _valid_layers
        ]
    elif data.user_memory is True:
        execution["USER_MEMORY_LAYERS"] = list(_valid_layers)
    elif data.user_memory is False:
        execution["USER_MEMORY_LAYERS"] = []

    # Thinking targets: request labels win, else the agent's, else every
    # target on (the executor's own fallback). Mirrors the WebUI in zeroing
    # them out when Thinking is off.
    _labels = (data.thinking_targets
               if data.thinking_targets is not None
               else execution.pop("_THINKING_TARGET_LABELS", None))
    execution.pop("_THINKING_TARGET_LABELS", None)
    if _labels is not None and "THINKING_TARGETS" not in execution:
        execution["THINKING_TARGETS"] = dma.thinking_targets_to_flags(
            _labels if execution.get("THINKING_MODE") else [])

    # SKILL selection. Agent defaults are candidates, exactly as the WebUI
    # picker leaves them after login; names the caller passed are orders.
    skills_ignored = []
    skill_tools = _agent_skill_tools(agent_file)
    if "_MANUAL_SKILL_PICKS" not in execution:
        if data.skills is None:
            _defaults = dma.default_skill_names(skill_tools)
            execution["_MANUAL_SKILL_PICKS"] = _defaults
            execution["_CANDIDATE_SKILL_PICKS"] = list(_defaults)
        else:
            execution["_MANUAL_SKILL_PICKS"] = [
                n for n in data.skills if n in skill_tools]
            execution["_CANDIDATE_SKILL_PICKS"] = []
            skills_ignored = [n for n in data.skills if n not in skill_tools]
    if data.skill:
        if data.skill in skill_tools:
            execution["_SLASH_SKILL_PICK"] = data.skill
        else:
            skills_ignored.append(data.skill)

    # In the WebUI a flag skill's selection IS its execution flag, and picking
    # a WebSearch skill turns web search on. An explicit flag field or
    # data.execution entry still wins.
    _picks = set(execution.get("_MANUAL_SKILL_PICKS") or [])
    if data.skill:
        _picks.add(data.skill)
    _explicit = {k for k, v in _flag_map.items() if v is not None} | set((data.execution or {}).keys())
    for _name, _flag in dma.FLAG_SKILLS.items():
        if _name not in skill_tools or _flag["EXEC_KEY"] in _explicit:
            continue
        # No pick list and no DEFAULT: the WebUI would fall back to the user's
        # Defaults, which the API does not have, so the executor's own default
        # stands.
        if data.skills is None and not data.skill and (skill_tools[_name] or {}).get("DEFAULT") is None:
            continue
        execution[_flag["EXEC_KEY"]] = _name in _picks
    if data.skills is not None and "WEB_SEARCH" not in _explicit:
        execution["WEB_SEARCH"] = any(n == "WebSearch" or n.startswith("WebSearch_") for n in _picks)

    return execution, skills_ignored


def _prepare_run(
    data: InputData,
    extra_content_paths: Optional[List[str]] = None,
    extra_processed: Optional[List[dict]] = None,
    tmp_dir: Optional[str] = None,
):
    """(exec_function kwargs, notes for the response) for one request.

    `extra_content_paths` are files already staged on disk by the caller
    (e.g. /run_multipart's UploadFiles). They're appended after any inline
    or URL-based attachments from `data` so the ordering seen by the agent
    matches the request payload order.
    """
    agent_file = data.agent_file or api_agent_file
    service_info = data.service_info.model_dump()
    user_info = data.user_info.model_dump()
    execution, skills_ignored = _build_execution_dict(data, agent_file)

    if tmp_dir is None:
        tmp_dir = _api_temp_folder()

    try:
        inline_paths, processed = _prepare_attachments(
            tmp_dir,
            data.attachments,
            data.attachment_urls,
            data.user_input,
            data.fetch_urls_from_input,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Attachment prep failed: {e}")

    uploaded_contents = list(inline_paths)
    if extra_content_paths:
        uploaded_contents.extend(extra_content_paths)
    if extra_processed:
        processed = list(processed) + list(extra_processed)

    agent_data = _agent_data(agent_file)
    personas, org, personas_ignored = _resolve_personas(agent_file, agent_data, data.personas, data.org)
    if org is None and _agent_orgs(agent_data):
        org = _agent_orgs(agent_data)[0]
    books, books_ignored = _resolve_books(agent_data, data.books)

    user_input, rag_query_text = data.user_input, ""
    if data.include_query:
        try:
            user_input, rag_query_text = _include_query_input(data.session_id or "", data.user_input)
        except Exception:
            user_input, rag_query_text = data.user_input, ""

    overwrite_items = dict(data.overwrite_items or {})
    if data.personality:
        _pers = dict(overwrite_items.get("PERSONALITY") or {})
        _pers.update(data.personality)
        overwrite_items["PERSONALITY"] = _pers

    kwargs = dict(
        service_info=service_info, user_info=user_info,
        session_id=data.session_id or "", session_name=data.session_name or "",
        user_input=user_input, situation=data.situation, agent_file=agent_file,
        engine=data.engine or "", execution=execution,
        uploaded_contents=uploaded_contents,
        session_summary_enabled=data.session_summary_enabled,
        session_summary_template=data.session_summary_template,
        imagegen_engine=data.imagegen_engine or "",
        overwrite_items=overwrite_items,
        add_knowledge=books, personas=personas, org=org,
        rag_query_text=rag_query_text,
    )
    notes = {"attachments_processed": processed}
    # Silently dropping an unknown name is how a typo turns into "it just
    # never ran", so each one is reported back.
    if skills_ignored:
        notes["skills_ignored"] = skills_ignored
    if personas_ignored:
        notes["personas_ignored"] = personas_ignored
    if books_ignored:
        notes["books_ignored"] = books_ignored
    return kwargs, notes


def _log_run_error(where: str, kwargs: dict):
    # Full traceback + the request context go to stderr (captured in
    # /var/log/digim_api.log when launched by the WebUI Start button).
    # Without these the log only shows `POST /run 500` with no context.
    import sys
    print("=" * 78, file=sys.stderr, flush=True)
    print(f"[{where} 500] agent_file={kwargs.get('agent_file')!r} engine={kwargs.get('engine')!r} "
          f"user_input={kwargs.get('user_input')!r} session_id={kwargs.get('session_id')!r} "
          f"exec_keys={list((kwargs.get('execution') or {}).keys())} "
          f"attachments={len(kwargs.get('uploaded_contents') or [])}",
          file=sys.stderr, flush=True)
    traceback.print_exc()
    print("=" * 78, file=sys.stderr, flush=True)


async def _execute_shared(
    data: InputData,
    extra_content_paths: Optional[List[str]] = None,
    extra_processed: Optional[List[dict]] = None,
    tmp_dir: Optional[str] = None,
) -> dict:
    """Single execution path for /run, /run_function and /run_multipart."""
    kwargs, notes = await run_in_threadpool(
        _prepare_run, data, extra_content_paths, extra_processed, tmp_dir)
    try:
        # A turn takes minutes; run on the thread pool so the worker keeps
        # answering /health and /jobs meanwhile.
        result = await run_in_threadpool(lambda: exec_function(**kwargs))
        result.update(notes)
        return result
    except HTTPException:
        raise
    except Exception as e:
        _log_run_error("/run", kwargs)
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Background runs (/run_async + /jobs) ----------
# A job is a JSON file, not process memory: gunicorn runs several workers and
# the poll may land on a different one than the run. Progress itself is read
# from the session's status.yaml, which the executor writes as it goes (the
# same source the WebUI's chat monitor polls).
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _jobs_folder() -> str:
    _setting = dmu.read_yaml_file("setting.yaml") or {}
    base = _setting.get("TEMP_FOLDER", "user/common/temp/")
    folder = os.path.join(base.rstrip("/\\"), "api", "jobs")
    os.makedirs(folder, exist_ok=True)
    return folder


def _job_path(job_id: str) -> str:
    if not _JOB_ID_RE.match(job_id or ""):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return os.path.join(_jobs_folder(), job_id + ".json")


def _write_job(job: dict):
    path = _job_path(job["job_id"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_job(job_id: str) -> dict:
    path = _job_path(job_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _run_job(job: dict, kwargs: dict, notes: dict):
    try:
        result = exec_function(**kwargs)
        result.update(notes)
        job.update(state="done", result=result, session_name=result.get("session_name", ""))
    except Exception as e:
        _log_run_error("/run_async", kwargs)
        job.update(state="error", error=str(e))
        # Practice records its own failures; this covers one raised before it
        # started, which would otherwise leave the session locked for good.
        # The digest thread may still hold the lock, so give it time first.
        try:
            _sess = dms.DigiMSession(job["session_id"])
            for _ in range(30):
                if _sess.get_status() != "LOCKED":
                    break
                time.sleep(1)
            if _sess.get_status() == "LOCKED" or not _sess.get_status_error():
                _sess.save_status("UNLOCKED", error=str(e))
        except Exception:
            pass
    job["finished_at"] = _now()
    _write_job(job)


async def _start_job(kwargs: dict, notes: dict) -> dict:
    session_id = kwargs.get("session_id") or ("API" + dms.set_new_session_id())
    kwargs["session_id"] = session_id
    if dms.get_status_data(session_id).get("status") == "LOCKED":
        raise HTTPException(status_code=429, detail=f"Session {session_id} is locked. Retry after a moment.")
    # Lock before answering, so a client that polls at once never sees the
    # session idle and a second request cannot slip in.
    dms.DigiMSession(session_id, kwargs.get("session_name") or "").save_status("LOCKED")
    kwargs["execution"]["_PRE_LOCKED"] = True
    kwargs["wait_for_lock"] = False
    job = {
        "job_id": uuid.uuid4().hex,
        "session_id": session_id,
        "session_name": kwargs.get("session_name") or "",
        "agent_file": kwargs.get("agent_file"),
        "user_input": kwargs.get("user_input"),
        "state": "running",
        "started_at": _now(),
        "finished_at": None,
        "error": None,
        "result": None,
    }
    _write_job(job)
    threading.Thread(target=_run_job, args=(dict(job), kwargs, notes), daemon=True).start()
    return job


def _session_progress(session_id: str) -> dict:
    st = dms.get_status_data(session_id) or {}
    return {
        "status": st.get("status") or "UNLOCKED",
        "message": st.get("message") or "",
        # Streamed text so far; cleared when the run unlocks the session.
        "partial_response": st.get("response") or "",
        "error": st.get("error") or "",
    }


# Main execution (synchronous - completes in a single request)
@app.post("/run")
async def run(data: InputData):
    return await _execute_shared(data)


# Multipart variant — accepts one or more UploadFile parts alongside a JSON
# metadata field. Use this when the caller cannot base64-encode attachments
# (e.g. large PDFs / videos, or a form-based UI where multipart is easier).
#
# curl -X POST http://localhost:8899/run_multipart \
#   -F 'data={"service_info":{"SERVICE_ID":"DEMO"},"user_info":{"USER_ID":"U"},"user_input":"要約して"};type=application/json' \
#   -F 'files=@report.pdf' -F 'files=@notes.txt'
async def _stage_multipart(data: str, files: List[UploadFile]):
    try:
        parsed = InputData.model_validate_json(data)
    except Exception as e:
        raise HTTPException(status_code=400,
            detail=f"Invalid JSON in the `data` form field: {e}")

    if len(files) > MAX_ATTACHMENTS:
        raise HTTPException(status_code=413,
            detail=f"Too many multipart files: {len(files)} > {MAX_ATTACHMENTS}")

    tmp_dir = _api_temp_folder()
    saved_paths: List[str] = []
    processed: List[dict] = []
    for uf in files:
        content = await uf.read()
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413,
                detail=f"File {uf.filename!r} exceeds {MAX_ATTACHMENT_BYTES} bytes")
        safe = _sanitize_filename(uf.filename or "upload.bin", default="upload.bin")
        p = _unique_path(tmp_dir, safe)
        with open(p, "wb") as f:
            f.write(content)
        saved_paths.append(p)
        processed.append({
            "filename": os.path.basename(p),
            "size_bytes": len(content),
            "content_type": uf.content_type,
            "source": "multipart",
        })
    return parsed, saved_paths, processed, tmp_dir


@app.post("/run_multipart")
async def run_multipart(
    data: str = Form(..., description="JSON-encoded InputData payload"),
    files: List[UploadFile] = File(default=[], description="Attachment files"),
):
    parsed, saved_paths, processed, tmp_dir = await _stage_multipart(data, files)
    return await _execute_shared(
        parsed,
        extra_content_paths=saved_paths,
        extra_processed=processed,
        tmp_dir=tmp_dir,
    )


# Background variant of /run — what the WebUI chat does. Returns at once with
# a job_id; poll GET /jobs/{job_id} for progress and the final result. Use it
# when a turn can outlast a proxy's request timeout (Azure App Service cuts
# requests at 230 s) or when the client wants to show progress.
@app.post("/run_async")
async def run_async(data: InputData):
    kwargs, notes = await run_in_threadpool(_prepare_run, data)
    return await _start_job(kwargs, notes)


@app.post("/run_async_multipart")
async def run_async_multipart(
    data: str = Form(..., description="JSON-encoded InputData payload"),
    files: List[UploadFile] = File(default=[], description="Attachment files"),
):
    parsed, saved_paths, processed, tmp_dir = await _stage_multipart(data, files)
    kwargs, notes = await run_in_threadpool(_prepare_run, parsed, saved_paths, processed, tmp_dir)
    return await _start_job(kwargs, notes)


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """state: running → done (with `result`, the /run response) or error.
    While running, `progress` carries the executor's status message and the
    streamed text so far."""
    job = _read_job(job_id)
    job["progress"] = _session_progress(job["session_id"])
    try:
        _t0 = datetime.strptime(job["started_at"], "%Y-%m-%d %H:%M:%S")
        _t1 = (datetime.strptime(job["finished_at"], "%Y-%m-%d %H:%M:%S")
               if job.get("finished_at") else datetime.now())
        job["elapsed_sec"] = int((_t1 - _t0).total_seconds())
    except Exception:
        pass
    return job


# Backward compatibility (legacy endpoint -> falls back to the same synchronous handler)
@app.post("/run_function")
async def run_function(data: InputData):
    return await _execute_shared(data)

# Session list
# ---------- History retention (DigiM_HistoryArchive) ----------
# The API has no authentication of its own, and these endpoints delete
# history. They answer only when HISTORY_ARCHIVE_API_TOKEN is set in
# system.env and the request carries it as X-Admin-Token.
class HistoryArchiveRequest(BaseModel):
    days: Optional[float] = None
    session_ids: Optional[List[str]] = None
    dry_run: bool = False
    keep_turns: Optional[int] = None


class HistoryRestoreRequest(BaseModel):
    session_id: str
    zip_name: Optional[str] = None
    overwrite: bool = False


def _require_history_token(token: Optional[str]):
    import hmac
    expect = os.getenv("HISTORY_ARCHIVE_API_TOKEN") or ""
    if not expect:
        raise HTTPException(status_code=403,
                            detail="History archive endpoints are disabled: set HISTORY_ARCHIVE_API_TOKEN")
    if not token or not hmac.compare_digest(token, expect):
        raise HTTPException(status_code=401, detail="Invalid X-Admin-Token")


@app.get("/admin/history/sessions")
async def history_sessions(days: Optional[float] = None,
                           x_admin_token: Optional[str] = Header(default=None)):
    _require_history_token(x_admin_token)
    import DigiM_HistoryArchive as ha
    return {"sessions": ha.scan(days=days)}


@app.get("/admin/history/turns")
async def history_turns(days: Optional[float] = None, keep_turns: Optional[int] = None,
                        x_admin_token: Optional[str] = Header(default=None)):
    _require_history_token(x_admin_token)
    import DigiM_HistoryArchive as ha
    return {"sessions": ha.scan_turns(days=days, keep=keep_turns)}


@app.get("/admin/history/archives")
async def history_archives(x_admin_token: Optional[str] = Header(default=None)):
    _require_history_token(x_admin_token)
    import DigiM_HistoryArchive as ha
    return {"archives": ha.list_archives()}


@app.post("/admin/history/backup")
async def history_backup(data: HistoryArchiveRequest,
                         x_admin_token: Optional[str] = Header(default=None)):
    _require_history_token(x_admin_token)
    import DigiM_HistoryArchive as ha
    try:
        return ha.backup(days=data.days, session_ids=data.session_ids, dry_run=data.dry_run)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/admin/history/purge")
async def history_purge(data: HistoryArchiveRequest,
                        x_admin_token: Optional[str] = Header(default=None)):
    _require_history_token(x_admin_token)
    if data.days is None:
        raise HTTPException(status_code=400, detail="days is required (how long a session must be idle)")
    import DigiM_HistoryArchive as ha
    try:
        return ha.purge(days=data.days, session_ids=data.session_ids, dry_run=data.dry_run)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/admin/history/prune")
async def history_prune(data: HistoryArchiveRequest,
                        x_admin_token: Optional[str] = Header(default=None)):
    """Delete turns older than `days` (default ARCHIVE_TURN_DAYS) inside
    sessions, keeping each session's newest `keep_turns` (ARCHIVE_KEEP_TURNS)."""
    _require_history_token(x_admin_token)
    import DigiM_HistoryArchive as ha
    try:
        return ha.prune_turns(days=data.days, keep=data.keep_turns, session_ids=data.session_ids,
                              dry_run=data.dry_run)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/admin/history/restore")
async def history_restore(data: HistoryRestoreRequest,
                          x_admin_token: Optional[str] = Header(default=None)):
    _require_history_token(x_admin_token)
    import DigiM_HistoryArchive as ha
    try:
        return ha.restore(data.session_id, zip_name=data.zip_name, overwrite=data.overwrite)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/sessions")
async def get_sessions(user_id: Optional[str] = None, service_id: Optional[str] = None,
                       active: Optional[str] = None):
    """Newest first, like the WebUI sidebar. `active=Y` lists what the sidebar
    shows, `active=N` the hidden sessions it can re-display."""
    sessions = await run_in_threadpool(dms.get_session_list)
    if user_id:
        sessions = [s for s in sessions if s.get("user_id") == user_id]
    if service_id:
        sessions = [s for s in sessions if s.get("service_id") == service_id]
    if active in ("Y", "N"):
        sessions = [s for s in sessions if (s.get("active") or "Y") == active]
    sessions = sorted(sessions, key=lambda s: str(s.get("last_update_date") or ""), reverse=True)
    return {"sessions": [{"id": s.get("id"), "name": s.get("name"), "agent": s.get("agent"),
                          "last_update_date": s.get("last_update_date"),
                          "active": s.get("active") or "Y",
                          "status": s.get("status") or "UNLOCKED",
                          "user_id": s.get("user_id"), "service_id": s.get("service_id")}
                         for s in sessions]}

# Session history
@app.get("/sessions/{session_id}")
async def get_session_history(session_id: str):
    data = dms.get_session_data(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "history": data}


# ---------- Chat view of a session (what the WebUI chat pane shows) ----------
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-.]+$")


def _session_or_404(session_id: str) -> "dms.DigiMSession":
    if not _SESSION_ID_RE.match(session_id or ""):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    folder = os.path.join(dms.user_folder_path, dms.session_folder_prefix + session_id)
    if not os.path.isdir(folder) and not dms.get_session_data(session_id):
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return dms.DigiMSession(session_id)


def _content_ref(session_id: str, item: dict) -> dict:
    name = item.get("file_name") or ""
    return {"file_name": name, "file_type": item.get("file_type") or "",
            "url": f"/sessions/{quote(session_id)}/contents/{quote(name)}"}


def _shape_entry(session_id: str, seq: str, sub: str, entry: dict, include_refs: bool,
                 raw_turn: Optional[dict] = None) -> dict:
    s = entry.get("setting") or {}
    p = entry.get("prompt") or {}
    q = p.get("query") or {}
    r = entry.get("response") or {}
    # A collapsed (SUMMARY) entry is keyed "1" but reads and writes belong to
    # real coordinates: the chain's first entry for detail, its last for the
    # answer and feedback.
    write_sub = entry.get("_src_sub_seq_last", sub)
    # POST /feedback checks the agent of the entry it writes to, which in a
    # chain is not the one the collapsed entry is named after.
    ws = (((raw_turn or {}).get(write_sub) or {}).get("setting") or {}) or s
    fb = ws.get("feedback") or {}
    out = {
        "sub_seq": write_sub,
        "detail_sub_seq": entry.get("_src_sub_seq", sub),
        "type": s.get("type", ""),
        "name": s.get("name", ""),
        "agent_file": s.get("agent_file", ""),
        "answer_agent_file": ws.get("agent_file", ""),
        "persona_id": s.get("persona_id", ""),
        "persona_name": s.get("persona_name", ""),
        # PUSH / SKILL / TOOL entries carry no engine.
        "engine": (s.get("engine") or {}).get("NAME", "") if isinstance(s.get("engine"), dict) else "",
        "memory_flg": s.get("memory_flg", "Y"),
        "prompt_role": p.get("role", ""),
        "prompt_timestamp": p.get("timestamp", ""),
        "user_input": dmt.strip_skill_wraps(q.get("input") or ""),
        "contents": [_content_ref(session_id, c) for c in (q.get("contents") or []) if isinstance(c, dict)],
        "response_timestamp": r.get("timestamp", ""),
        "response": r.get("text") or "",
        "response_display": (r.get("text") or "") + dmt.render_response_tail(entry),
        "ref_sections": r.get("ref_sections") or "",
        "skills": r.get("skills") if isinstance(r.get("skills"), dict) else {},
        "images": [_content_ref(session_id, i) for i in (entry.get("image") or {}).values() if isinstance(i, dict)],
        "feedback": entry.get("feedback") or {},
        "feedback_config": {
            "active": fb.get("ACTIVE") == "Y",
            "items": fb.get("FEEDBACK_ITEM_LIST") or [],
            "default_category": fb.get("DEFAULT_CATEGORY") or "",
        },
    }
    if include_refs:
        refs = _shape_references(_saved_references(entry))
        # The raw log strings double the payload and the parsed fields hold
        # everything a viewer shows.
        for _k in ("knowledge", "page_index"):
            for _it in refs.get(_k) or []:
                _it.pop("_raw", None)
        out["references"] = refs
    return out


@app.get("/sessions/{session_id}/status")
async def get_session_status(session_id: str):
    """LOCKED while a turn runs (WebUI, API or a job), with its progress."""
    _session_or_404(session_id)
    out = {"session_id": session_id, "name": dms.get_session_name(session_id),
           "active": dms.get_active_session(session_id)}
    out.update(_session_progress(session_id))
    return out


@app.get("/sessions/{session_id}/turns")
async def get_session_turns(session_id: str, view: str = "summary", last: int = 0,
                            include_refs: bool = True):
    """Deleted turns are left out, as in the WebUI.

    view=summary : one entry per turn, its question and final answer (the
                   WebUI's History Detail Visible = SUMMARY)
    view=all     : every entry of the chain (= ALL)
    last         : only the newest N turns (0 = all)
    """
    sess = await run_in_threadpool(_session_or_404, session_id)
    hist = sess.chat_history_active_omit_dict if view != "all" else sess.chat_history_active_dict
    seqs = sorted(hist.keys(), key=int)
    if last and last > 0:
        seqs = seqs[-last:]
    raw = sess.chat_history_active_dict or {}
    turns = []
    for k in seqs:
        block = hist[k] or {}
        setting = (raw.get(k) or {}).get("SETTING") or {}
        turns.append({
            "seq": k,
            "memory_flg": setting.get("MEMORY_FLG", "Y"),
            "user_id": (setting.get("user_info") or {}).get("USER_ID", ""),
            "entries": [_shape_entry(session_id, k, k2, v2, include_refs, raw.get(k))
                        for k2, v2 in sorted(((a, b) for a, b in block.items() if a != "SETTING"),
                                             key=lambda x: int(x[0]))
                        if isinstance(v2, dict)],
        })
    st = dms.get_status_data(session_id) or {}
    return {
        "session_id": session_id,
        "session_name": sess.session_name,
        "agent": st.get("agent") or "",
        "active": st.get("active") or "Y",
        "status": st.get("status") or "UNLOCKED",
        "view": "all" if view == "all" else "summary",
        "turn_count": len(hist),
        "turns": turns,
    }


def _require_seq(sess, seq: str) -> dict:
    turn = (sess.chat_history_dict or {}).get(str(seq))
    if not isinstance(turn, dict) or "SETTING" not in turn:
        raise HTTPException(status_code=404, detail=f"seq={seq} not found")
    return turn


def _require_unlocked(sess):
    # The running turn saves its own copy of the history; a change made under
    # it can be written over.
    if sess.get_status() == "LOCKED":
        raise HTTPException(status_code=409, detail=f"Session {sess.session_id} is running a turn. Retry after it finishes.")


@app.get("/sessions/{session_id}/turns/{seq}/detail")
async def get_turn_detail(session_id: str, seq: str, sub_seq: str = "1"):
    """The WebUI's Detail Information text (LLM input, tokens, references, ...).
    For a SUMMARY entry pass its `detail_sub_seq`."""
    sess = await run_in_threadpool(_session_or_404, session_id)
    turn = _require_seq(sess, seq)
    if sub_seq not in turn:
        raise HTTPException(status_code=404, detail=f"seq={seq}/sub_seq={sub_seq} not found")
    text = await run_in_threadpool(sess.get_detail_info, seq, sub_seq)
    return {"session_id": session_id, "seq": seq, "sub_seq": sub_seq, "detail": text}


@app.post("/sessions/{session_id}/turns/{seq}/delete")
async def delete_turn(session_id: str, seq: str):
    """Hide a turn (FLG=N), as the WebUI's delete does. It stays in storage."""
    sess = await run_in_threadpool(_session_or_404, session_id)
    _require_seq(sess, seq)
    _require_unlocked(sess)
    await run_in_threadpool(sess.chg_seq_history, seq, "N")
    return {"status": "ok", "session_id": session_id, "seq": seq}


class TurnMemorySetting(BaseModel):
    enabled: bool


@app.post("/sessions/{session_id}/turns/{seq}/memory")
async def set_turn_memory(session_id: str, seq: str, data: TurnMemorySetting):
    """enabled=false is the WebUI's Memory Off: the turn stays visible but is
    left out of the conversation memory sent to the LLM."""
    sess = await run_in_threadpool(_session_or_404, session_id)
    _require_seq(sess, seq)
    _require_unlocked(sess)
    await run_in_threadpool(sess.chg_seq_memory_flg, seq, "Y" if data.enabled else "N")
    return {"status": "ok", "session_id": session_id, "seq": seq,
            "memory_flg": "Y" if data.enabled else "N"}


class SessionRename(BaseModel):
    name: str


@app.post("/sessions/{session_id}/rename")
async def rename_session(session_id: str, data: SessionRename):
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is empty")
    sess = await run_in_threadpool(_session_or_404, session_id)
    _require_unlocked(sess)
    await run_in_threadpool(sess.chg_session_name, name)
    return {"status": "ok", "session_id": session_id, "name": name}


@app.post("/sessions/{session_id}/hide")
async def hide_session(session_id: str):
    """The WebUI sidebar's Del: hidden from the list, nothing is deleted."""
    sess = await run_in_threadpool(_session_or_404, session_id)
    sess.save_active_session("N")
    sess.save_user_dialog_session("DISCARD")
    return {"status": "ok", "session_id": session_id, "active": "N"}


@app.post("/sessions/{session_id}/activate")
async def activate_session(session_id: str):
    """The WebUI's Activate Sessions: show a hidden session again."""
    sess = await run_in_threadpool(_session_or_404, session_id)
    sess.save_active_session("Y")
    sess.save_user_dialog_session("UNSAVED")
    return {"status": "ok", "session_id": session_id, "active": "Y"}


@app.get("/sessions/{session_id}/contents/{file_name}")
async def get_session_content(session_id: str, file_name: str):
    """An attachment or generated image of the session (the `url` in turns)."""
    if not _SESSION_ID_RE.match(session_id or "") or os.path.basename(file_name) != file_name \
            or file_name in ("", ".", ".."):
        raise HTTPException(status_code=404, detail="File not found")
    folder = os.path.join(dms.user_folder_path, dms.session_folder_prefix + session_id,
                          dms.session_contents_folder)
    path = os.path.join(folder, file_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path)


@app.get("/sessions/{session_id}/export")
async def export_session(session_id: str, view: str = "summary", images: bool = False):
    """The chat as Markdown, like the WebUI's Chats Only download. images=true
    embeds attachments and generated images as base64 (can be several MB)."""
    sess = await run_in_threadpool(_session_or_404, session_id)
    hist = sess.chat_history_active_omit_dict if view != "all" else sess.chat_history_active_dict
    folder = sess.session_contents_folder_path

    def _img(name):
        if not images or not name:
            return []
        path = folder + name
        if not os.path.isfile(path) or not re.search(r"\.(png|jpe?g|gif|webp)$", name, re.I):
            return []
        b64 = dmu.encode_image_file(path).replace("\n", "").replace("\r", "")
        return [f"![{name}](data:image/png;base64,{b64})", "---"]

    lines = []
    for k in sorted(hist.keys(), key=int):
        block = hist[k] or {}
        role = ((sess.chat_history_dict.get(k) or {}).get("SETTING") or {}).get("user_info", {}).get("USER_ID")
        for k2 in sorted([x for x in block if x != "SETTING"], key=int):
            v2 = block[k2]
            p = v2.get("prompt") or {}
            user = role or p.get("role", "user")
            lines += [f"**User**\n **{user}:**\n\n" + dmt.strip_skill_wraps((p.get("query") or {}).get("input") or ""), "---"]
            for c in (p.get("query") or {}).get("contents") or []:
                lines += _img((c or {}).get("file_name"))
            text = ((v2.get("response") or {}).get("text") or "") + dmt.render_response_tail(v2)
            lines += [f"**Assistant**\n **{(v2.get('setting') or {}).get('name', '')}:**\n\n" + text, "---"]
            for i in (v2.get("image") or {}).values():
                lines += _img((i or {}).get("file_name"))
    md = "\n\n".join(lines)
    fname = f"{session_id}_chat.md"
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- Session Summary endpoints ----------
# Read the current session summary (settings + generated content) for a session.
# Returns the same tuple DigiMSession.get_session_summary() produces, plus
# session_id echoed for client convenience.
@app.get("/sessions/{session_id}/summary")
async def get_session_summary(session_id: str):
    try:
        _sess = dms.DigiMSession(session_id, "")
        _enabled, _template, _content, _updated_at = _sess.get_session_summary()
    except Exception as e:
        raise HTTPException(status_code=404,
                             detail=f"Session not found or unreadable: {e}")
    return {
        "session_id": session_id,
        "enabled":    _enabled,
        "template":   _template,
        "content":    _content,
        "updated_at": _updated_at,
    }


class SessionSummarySettings(BaseModel):
    """Payload for `POST /sessions/{id}/summary`. Fields are optional so
    callers can flip the toggle without resupplying the template (and
    vice-versa)."""
    enabled:  Optional[bool] = None
    template: Optional[str]  = None


# Update the session summary settings (toggle + template). The generated
# `content` is NOT settable here — it's owned by the background updater in
# DigiMatsuExecute_Practice. To clear the content, POST with a new template
# (which resets on the next turn) or just leave it alone.
@app.post("/sessions/{session_id}/summary")
async def set_session_summary(session_id: str, data: SessionSummarySettings):
    try:
        _sess = dms.DigiMSession(session_id, "")
        _cur_enabled, _cur_template, _content, _updated_at = _sess.get_session_summary()
        _new_enabled  = _cur_enabled  if data.enabled  is None else bool(data.enabled)
        _new_template = _cur_template if data.template is None else str(data.template)
        _sess.save_session_summary_settings(_new_enabled, _new_template)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "session_id": session_id,
        "enabled":    _new_enabled,
        "template":   _new_template,
        "content":    _content,
        "updated_at": _updated_at,
    }


# Return the shipped preset templates (same file the WebUI reads).
@app.get("/session_summary_presets")
async def get_session_summary_presets():
    """List shipped preset templates that clients can use as starting points.

    Backed by `user/common/mst/session_summary_presets.json`. Operators can
    edit that file to add/remove presets; both the WebUI and any API client
    pick up changes on the next call.
    """
    try:
        import DigiM_MstStore as dmms
        _presets = dmms.load("session_summary_presets") or {}
    except Exception:
        _presets = {}
    return {
        "presets": [
            {"name": _name,
             "description": (_meta or {}).get("description", ""),
             "template":    (_meta or {}).get("template", "")}
            for _name, _meta in _presets.items()
        ]
    }


# Agent list
@app.get("/agents")
async def get_agent_list():
    agents = dma.get_display_agents()
    return {"agents": agents}

# List of engines selectable for the agent
@app.get("/agents/{agent_file}/engines")
async def get_engine_list(agent_file: str):
    try:
        agent_data = dmu.read_json_file(agent_file, dma.agent_folder_path)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent file not found: {agent_file}")
    llm_engines = dma.get_engine_list(agent_data, "LLM")
    imagegen_engines = dma.get_engine_list(agent_data, "IMAGEGEN")
    default_llm = agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
    default_imagegen = agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")
    return {
        "agent_file": agent_file,
        "LLM": {"default": default_llm, "engines": llm_engines},
        "IMAGEGEN": {"default": default_imagegen, "engines": imagegen_engines},
    }

# Everything the WebUI chat sidebar offers for this agent, in one call:
# engines, SKILLs by phase, BOOKs, ORG → personas, Thinking, personality and
# the execution toggles a turn starts from. Values feed straight into /run.
@app.get("/agents/{agent_file}/chat_options")
async def get_chat_options(agent_file: str):
    agent_data = _agent_data(agent_file)
    if not agent_data:
        raise HTTPException(status_code=404, detail=f"Agent file not found: {agent_file}")

    def _engines(kind):
        return {"default": agent_data.get("ENGINE", {}).get(kind, {}).get("DEFAULT", ""),
                "engines": dma.get_engine_list(agent_data, kind)}

    try:
        import DigiM_ToolRegistry as dmtr
    except Exception:
        dmtr = None
    skill_tools = _agent_skill_tools(agent_file)
    skills = []
    for phase in ("BEFORE", "AFTER"):
        names = dma.sort_skill_names(
            [n for n, c in skill_tools.items() if dma.normalize_skill_phase((c or {}).get("PHASE")) == phase],
            skill_tools)
        for n in names:
            c = skill_tools.get(n) or {}
            flag = dma.FLAG_SKILLS.get(n) or {}
            desc = flag.get("DESCRIPTION", "")
            if not desc and dmtr is not None:
                try:
                    desc = ((dmtr.get_tool(n) or {}).get("description") or "").strip()
                except Exception:
                    desc = ""
            skills.append({"name": n, "phase": phase, "label": flag.get("LABEL") or n,
                           "default": bool(c.get("DEFAULT")), "flag": n in dma.FLAG_SKILLS,
                           "merge": c.get("MERGE", ""), "description": desc})

    books = [{"rag_name": b.get("RAG_NAME"), "retriever": b.get("RETRIEVER", "")}
             for b in (agent_data.get("BOOK") or [])
             if isinstance(b, dict) and b.get("RAG_NAME") and dma.is_entry_active(b, True)]

    orgs = []
    for o in _agent_orgs(agent_data):
        try:
            cands = await run_in_threadpool(
                dap.find_personas_by_org, o, agent_file,
                agent_data.get("PERSONA_FILES") or None, agent_data.get("PERSONA_SOURCE"))
        except Exception:
            cands = []
        orgs.append({"org": o, "label": ", ".join(f"{k}={v}" for k, v in o.items()),
                     "personas": [{"persona_id": p.get("persona_id"), "name": p.get("name", "")}
                                  for p in cands]})

    thinking_options = ["Habit", "Web Search", "RAG Query"]
    if books:
        thinking_options.append("Books")
    if skill_tools:
        thinking_options.append("Skills")
    if orgs:
        thinking_options.append("Personas")
    t = _agent_thinking_block(agent_file)
    try:
        _setting = dmu.read_yaml_file("setting.yaml") or {}
        max_personas = int(_setting.get("MAX_PERSONAS", 3))
    except Exception:
        max_personas = 3
    defaults = dict(_API_EXECUTION_DEFAULTS)
    defaults.update(_agent_execution_defaults(agent_file))
    pers = agent_data.get("PERSONALITY") or {}
    return {
        "agent_file": agent_file,
        "agent_name": (agent_data.get("DISPLAY_NAME") or agent_data.get("NAME") or ""),
        "LLM": _engines("LLM"),
        "IMAGEGEN": _engines("IMAGEGEN"),
        "skills": skills,
        "books": books,
        "orgs": orgs,
        "thinking": {
            "mode": bool(t.get("MODE", False)),
            "targets": [("Skills" if x == "Tools" else x) for x in (t.get("TARGETS") or [])
                        if ("Skills" if x == "Tools" else x) in thinking_options],
            "max_turns": max(1, min(int(t.get("MAX_TURNS", 1) or 1), 5)),
            "options": thinking_options,
            "max_personas": int(defaults.get("MAX_PERSONAS", max_personas)),
        },
        "execution_defaults": defaults,
        "personality": {k: v for k, v in pers.items() if isinstance(v, (str, int, float, bool)) or k == "BIG5"},
        "feedback_active": (agent_data.get("FEEDBACK") or {}).get("ACTIVE") == "Y",
    }


# Web search engine list
@app.get("/web_search_engines")
async def get_web_search_engines():
    import DigiM_Tool as dmt
    _setting = dmu.read_yaml_file("setting.yaml")
    default_engine = _setting.get("WEB_SEARCH_DEFAULT", "Perplexity")
    engines = []
    try:
        _engine_names = list(dmt.WEB_SEARCH_ENGINES.keys())
    except AttributeError:
        _engine_names = ["Perplexity", "OpenAI", "AzureOpenAI", "Bedrock", "Google", "Claude"]
    for name in _engine_names:
        engine_info = {"name": name}
        if name == "Perplexity":
            engine_info["model"] = _setting.get("PERPLEXITY_MODEL", "sonar")
        elif name == "OpenAI":
            engine_info["model"] = _setting.get("OPENAI_SEARCH_MODEL", "gpt-4.1-mini")
        elif name == "Bedrock":
            engine_info["model"] = _setting.get("BEDROCK_SEARCH_MODEL", "openai.gpt-5.6-terra")
        elif name == "Google":
            engine_info["model"] = _setting.get("GOOGLE_SEARCH_MODEL", "gemini-2.5-flash")
        engines.append(engine_info)
    return {
        "default": default_engine,
        "engines": engines,
    }

# Get the agent's feedback configuration
@app.get("/agents/{agent_file}/feedback")
async def get_feedback_config(agent_file: str):
    try:
        agent = dma.DigiM_Agent(agent_file)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent file not found: {agent_file}")
    comm = agent.feedback
    if comm.get("ACTIVE") != "Y":
        return {"active": False, "message": "Feedback is disabled for this agent"}
    # Fetch category choices
    cat_map = dmms.load("category_map")
    categories = list(cat_map.get("Category", {}).keys()) if cat_map else []
    return {
        "active": True,
        "feedback_items": comm.get("FEEDBACK_ITEM_LIST", []),
        "default_category": comm.get("DEFAULT_CATEGORY", ""),
        "categories": categories,
        "save_mode": comm.get("SAVE_MODE", "CSV"),
    }

# Submit feedback
class FeedbackData(BaseModel):
    session_id: str
    agent_file: Optional[str] = None
    seq: str
    sub_seq: str = "1"
    feedbacks: Dict[str, Any]

@app.post("/feedback")
async def post_feedback(data: FeedbackData):
    agent_file = data.agent_file or api_agent_file
    session_id = data.session_id

    # Check that the session exists
    session_data = dms.get_session_data(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    if data.seq not in session_data or data.sub_seq not in session_data.get(data.seq, {}):
        raise HTTPException(status_code=404, detail=f"seq={data.seq}/sub_seq={data.sub_seq} not found")

    # Verify that the agent matches the seq/sub_seq target
    sub_data = session_data[data.seq][data.sub_seq]
    actual_agent = sub_data.get("setting", {}).get("agent_file", "")
    if actual_agent and actual_agent != agent_file:
        raise HTTPException(status_code=400,
            detail=f"Agent mismatch: seq={data.seq}/sub_seq={data.sub_seq} was executed with '{actual_agent}', not '{agent_file}'")

    # Verify the items match the agent's feedback configuration
    try:
        agent = dma.DigiM_Agent(agent_file)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent file not found: {agent_file}")
    comm = agent.feedback
    if comm.get("ACTIVE") != "Y":
        raise HTTPException(status_code=400, detail=f"Feedback is disabled for agent: {agent_file}")
    allowed_items = set(comm.get("FEEDBACK_ITEM_LIST", []))
    submitted_items = {k for k in data.feedbacks if k != "name"}
    invalid_items = submitted_items - allowed_items
    if invalid_items:
        raise HTTPException(status_code=400,
            detail=f"Invalid feedback items: {list(invalid_items)}. Allowed: {list(allowed_items)}")

    try:
        session = dms.DigiMSession(session_id)
        session.set_feedback_history(data.seq, data.sub_seq, data.feedbacks)
        dmgf.create_feedback_data(session_id, agent_file)
        return {"status": "ok", "session_id": session_id, "seq": data.seq, "sub_seq": data.sub_seq}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Health check
@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(api_port))
