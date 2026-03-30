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
import DigiM_GeneCommunication as dmgc

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
api_agent_file = os.getenv("API_AGENT_FILE")
api_port = os.getenv("API_PORT")
api_default_session_name = os.getenv("API_DEFAULT_SESSION_NAME")

app = FastAPI()

# ---------- リクエスト / レスポンス ----------
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
    execution: Dict[str, Any] = {}

LOCK_WAIT_MAX = 60   # ロック待機の最大秒数
LOCK_POLL_INTERVAL = 2  # ポーリング間隔（秒）

# ---------- 実行関数 ----------
def exec_function(service_info: dict, user_info: dict, session_id: str, session_name: str,
                  user_input: str, situation: dict, agent_file: str, engine: str, execution: dict) -> dict:
    # セッションの設定（未指定なら新規発番）
    if not session_id:
        session_id = "API" + dms.set_new_session_id()

    # セッションのロック待機
    waited = 0
    while waited < LOCK_WAIT_MAX:
        status = dms.get_status_data(session_id).get("status", "")
        if status != "LOCKED":
            break
        time.sleep(LOCK_POLL_INTERVAL)
        waited += LOCK_POLL_INTERVAL
    else:
        raise HTTPException(status_code=429, detail=f"Session {session_id} is locked. Retry after a moment.")

    # 実行の設定
    if not execution or "LAST_ONLY" not in execution:
        execution["LAST_ONLY"] = True

    # エンジン切り替え
    overwrite_items = {}
    if engine:
        agent_data = dmu.read_json_file(agent_file, dma.agent_folder_path)
        if engine in agent_data.get("ENGINE", {}).get("LLM", {}):
            overwrite_items["ENGINE"] = {"LLM": agent_data["ENGINE"]["LLM"][engine]}

    # 実行
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

    # セッション名の自動生成
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

# ---------- エンドポイント ----------

# メイン実行（同期 - 1回のリクエストで完結）
@app.post("/run")
async def run(data: InputData):
    agent_file = data.agent_file or api_agent_file
    service_info = data.service_info.model_dump()
    user_info = data.user_info.model_dump()

    try:
        result = exec_function(
            service_info, user_info,
            data.session_id or "", data.session_name or "",
            data.user_input, data.situation, agent_file,
            data.engine or "", data.execution
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 後方互換（旧エンドポイント → 同じ同期処理にフォールバック）
@app.post("/run_function")
async def run_function(data: InputData):
    return await run(data)

# セッション一覧
@app.get("/sessions")
async def get_sessions(user_id: Optional[str] = None, service_id: Optional[str] = None):
    sessions = dms.get_session_list()
    if user_id:
        sessions = [s for s in sessions if s.get("user_id") == user_id]
    if service_id:
        sessions = [s for s in sessions if s.get("service_id") == service_id]
    return {"sessions": [{"id": s.get("id"), "name": s.get("name"), "agent": s.get("agent"),
                          "last_update_date": s.get("last_update_date")} for s in sessions]}

# セッション履歴
@app.get("/sessions/{session_id}")
async def get_session_history(session_id: str):
    data = dms.get_session_data(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "history": data}

# エージェント一覧
@app.get("/agents")
async def get_agent_list():
    agents = dma.get_display_agents()
    return {"agents": agents}

# エージェントのフィードバック設定を取得
@app.get("/agents/{agent_file}/feedback")
async def get_feedback_config(agent_file: str):
    try:
        agent = dma.DigiM_Agent(agent_file)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent file not found: {agent_file}")
    comm = agent.communication
    if comm.get("ACTIVE") != "Y":
        return {"active": False, "message": "Feedback is disabled for this agent"}
    # カテゴリ選択肢を取得
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

# フィードバック送信
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

    # セッション存在確認
    session_data = dms.get_session_data(session_id)
    if not session_data:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    if data.seq not in session_data or data.sub_seq not in session_data.get(data.seq, {}):
        raise HTTPException(status_code=404, detail=f"seq={data.seq}/sub_seq={data.sub_seq} not found")

    # 該当seq/sub_seqのエージェントと一致するか確認
    sub_data = session_data[data.seq][data.sub_seq]
    actual_agent = sub_data.get("setting", {}).get("agent_file", "")
    if actual_agent and actual_agent != agent_file:
        raise HTTPException(status_code=400,
            detail=f"Agent mismatch: seq={data.seq}/sub_seq={data.sub_seq} was executed with '{actual_agent}', not '{agent_file}'")

    # エージェントのフィードバック項目と一致するか確認
    try:
        agent = dma.DigiM_Agent(agent_file)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent file not found: {agent_file}")
    comm = agent.communication
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
        dmgc.create_communication_data(session_id, agent_file)
        return {"status": "ok", "session_id": session_id, "seq": data.seq, "sub_seq": data.sub_seq}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ヘルスチェック
@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(api_port))
