import os
import time
import base64
import uuid
import traceback
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

import DigiM_Session as dms
import DigiM_Execute as dme
import DigiM_Tool as dmt
import DigiM_Util as dmu
import DigiM_Agent as dma
import DigiM_GeneFeedback as dmgf

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
    private_mode: Optional[bool] = None
    thinking_mode: Optional[bool] = None
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

# ---------- Execution function ----------
def exec_function(service_info: dict, user_info: dict, session_id: str, session_name: str,
                  user_input: str, situation: dict, agent_file: str, engine: str, execution: dict,
                  uploaded_contents: Optional[List[str]] = None) -> dict:
    uploaded_contents = list(uploaded_contents or [])

    # Set up the session (issue a new ID if not specified)
    if not session_id:
        session_id = "API" + dms.set_new_session_id()

    # Wait for the session lock
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
    overwrite_items = {}
    if engine:
        agent_data = dmu.read_json_file(agent_file, dma.agent_folder_path)
        if engine in agent_data.get("ENGINE", {}).get("LLM", {}):
            overwrite_items["ENGINE"] = {"LLM": agent_data["ENGINE"]["LLM"][engine]}

    # Execute — forward attachment paths as `in_contents`, matching the WebUI
    # flow (WebDigiMatsuAgent.py builds `uploaded_contents` the same way).
    response_chunks = []
    output_reference = {}
    for response_service_info, response_user_info, response_chunk, ref in dme.DigiMatsuExecute_Practice(
        service_info, user_info, session_id, session_name, agent_file, user_input,
        in_contents=uploaded_contents,
        in_situation=situation, in_overwrite_items=overwrite_items, in_execution=execution
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

    return {
        "session_id": session_id,
        "session_name": session_name,
        "response": response,
    }

# ---------- Endpoints ----------

def _build_execution_dict(data: InputData) -> dict:
    """Assemble the `execution` dict from API defaults + data.execution +
    explicit flag fields (each layer overrides the previous)."""
    execution = {
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
    execution.update(data.execution or {})
    _flag_map = {
        "STREAM_MODE": data.stream_mode,
        "SAVE_DIGEST": data.save_digest,
        "MEMORY_USE": data.memory_use,
        "MAGIC_WORD_USE": data.magic_word_use,
        "META_SEARCH": data.meta_search,
        "RAG_QUERY_GENE": data.rag_query_gene,
        "WEB_SEARCH": data.web_search,
        "WEB_SEARCH_ENGINE": data.web_search_engine,
        "PRIVATE_MODE": data.private_mode,
        "THINKING_MODE": data.thinking_mode,
    }
    for key, val in _flag_map.items():
        if val is not None:
            execution[key] = val

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

    return execution


async def _execute_shared(
    data: InputData,
    extra_content_paths: Optional[List[str]] = None,
    extra_processed: Optional[List[dict]] = None,
    tmp_dir: Optional[str] = None,
) -> dict:
    """Single execution path for /run, /run_function and /run_multipart.

    `extra_content_paths` are files already staged on disk by the caller
    (e.g. /run_multipart's UploadFiles). They're appended after any inline
    or URL-based attachments from `data` so the ordering seen by the agent
    matches the request payload order.
    """
    agent_file = data.agent_file or api_agent_file
    service_info = data.service_info.model_dump()
    user_info = data.user_info.model_dump()
    execution = _build_execution_dict(data)

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

    try:
        result = exec_function(
            service_info, user_info,
            data.session_id or "", data.session_name or "",
            data.user_input, data.situation, agent_file,
            data.engine or "", execution,
            uploaded_contents=uploaded_contents,
        )
        result["attachments_processed"] = processed
        return result
    except Exception as e:
        # Full traceback + the raw request payload go to stderr (captured in
        # /var/log/digim_api.log when launched by the WebUI Start button).
        # Without these the log only shows `POST /run 500` with no context.
        import sys
        print("=" * 78, file=sys.stderr, flush=True)
        print(f"[/run 500] agent_file={agent_file!r} engine={data.engine!r} "
              f"user_input={data.user_input!r} session_id={data.session_id!r} "
              f"exec_keys={list(execution.keys())} "
              f"attachments={len(uploaded_contents)}",
              file=sys.stderr, flush=True)
        traceback.print_exc()
        print("=" * 78, file=sys.stderr, flush=True)
        raise HTTPException(status_code=500, detail=str(e))


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
@app.post("/run_multipart")
async def run_multipart(
    data: str = Form(..., description="JSON-encoded InputData payload"),
    files: List[UploadFile] = File(default=[], description="Attachment files"),
):
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

    return await _execute_shared(
        parsed,
        extra_content_paths=saved_paths,
        extra_processed=processed,
        tmp_dir=tmp_dir,
    )


# Backward compatibility (legacy endpoint -> falls back to the same synchronous handler)
@app.post("/run_function")
async def run_function(data: InputData):
    return await _execute_shared(data)

# Session list
@app.get("/sessions")
async def get_sessions(user_id: Optional[str] = None, service_id: Optional[str] = None):
    sessions = dms.get_session_list()
    if user_id:
        sessions = [s for s in sessions if s.get("user_id") == user_id]
    if service_id:
        sessions = [s for s in sessions if s.get("service_id") == service_id]
    return {"sessions": [{"id": s.get("id"), "name": s.get("name"), "agent": s.get("agent"),
                          "last_update_date": s.get("last_update_date")} for s in sessions]}

# Session history
@app.get("/sessions/{session_id}")
async def get_session_history(session_id: str):
    data = dms.get_session_data(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "history": data}

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

# Web search engine list
@app.get("/web_search_engines")
async def get_web_search_engines():
    import DigiM_Tool as dmt
    _setting = dmu.read_yaml_file("setting.yaml")
    default_engine = _setting.get("WEB_SEARCH_DEFAULT", "Perplexity")
    engines = []
    for name in dmt.WEB_SEARCH_ENGINES.keys():
        engine_info = {"name": name}
        if name == "Perplexity":
            engine_info["model"] = _setting.get("PERPLEXITY_MODEL", "sonar")
        elif name == "OpenAI":
            engine_info["model"] = _setting.get("OPENAI_SEARCH_MODEL", "gpt-4.1-mini")
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
    mst_folder = dmu.read_yaml_file("setting.yaml").get("MST_FOLDER", "")
    cat_map = dmu.read_json_file("category_map.json", mst_folder)
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
