import os
import time
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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

# ---------- Request / Response ----------
class ServiceInfo(BaseModel):
    SERVICE_ID: str
    SERVICE_DATA: Dict[str, Any] = {}

class UserInfo(BaseModel):
    USER_ID: str
    USER_DATA: Dict[str, Any] = {}

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
    # Other execution settings (when passing fields not covered above)
    execution: Dict[str, Any] = {}

LOCK_WAIT_MAX = 60   # Maximum seconds to wait for a session lock
LOCK_POLL_INTERVAL = 2  # Polling interval (seconds)

# ---------- Execution function ----------
def exec_function(service_info: dict, user_info: dict, session_id: str, session_name: str,
                  user_input: str, situation: dict, agent_file: str, engine: str, execution: dict) -> dict:
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

    # Execute
    response_chunks = []
    output_reference = {}
    for response_service_info, response_user_info, response_chunk, ref in dme.DigiMatsuExecute_Practice(
        service_info, user_info, session_id, session_name, agent_file, user_input,
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

# Main execution (synchronous - completes in a single request)
@app.post("/run")
async def run(data: InputData):
    agent_file = data.agent_file or api_agent_file
    service_info = data.service_info.model_dump()
    user_info = data.user_info.model_dump()

    # API default settings (overridden by explicitly specified flags)
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
    # Apply values passed in the execution dict
    execution.update(data.execution)
    # Apply values from explicit fields (highest priority)
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

    # User memory enable/disable (Execute side reads execution["USER_MEMORY_LAYERS"] as top priority)
    #   If unset, falls back to users.json / USER_MEMORY_DEFAULT_LAYERS as before
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

    try:
        result = exec_function(
            service_info, user_info,
            data.session_id or "", data.session_name or "",
            data.user_input, data.situation, agent_file,
            data.engine or "", execution
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Backward compatibility (legacy endpoint -> falls back to the same synchronous handler)
@app.post("/run_function")
async def run_function(data: InputData):
    return await run(data)

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
