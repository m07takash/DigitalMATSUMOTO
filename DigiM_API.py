import os
import uuid
import threading
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn

import DigiM_Session as dms
import DigiM_Execute as dme
import DigiM_Tool as dmt

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
api_agent_file = os.getenv("API_AGENT_FILE")
api_port = os.getenv("API_PORT")
api_default_session_name = os.getenv("API_DEFAULT_SESSION_NAME")

app = FastAPI()

# ジョブ管理（インメモリ）
_jobs: Dict[str, dict] = {}
_jobs_lock = threading.Lock()

class ServiceInfo(BaseModel):
    SERVICE_ID: str
    SERVICE_DATA: Dict[str, Any]

class UserInfo(BaseModel):
    USER_ID: str
    USER_DATA: Dict[str, Any]

class InputData(BaseModel):
    service_info: ServiceInfo
    user_info: UserInfo
    session_id: Optional[str] = None
    session_name: Optional[str] = None
    user_input: str
    situation: Dict[str, Any]
    agent_file: Optional[str] = None
    execution: Dict[str, Any]

# 実行する関数(session_idにはLINE ID等のユーザーを一意に指定できるキー)
def exec_function(service_info: dict, user_info: dict, session_id: str, session_name: str, user_input: str, situation: dict, agent_file: str, execution: dict) -> tuple[dict, dict, str, str, Any]:
    # セッションの設定（新規でセッションIDを発番）
    if not session_id:
        session_id = "API"+ dms.set_new_session_id()

    # 実行の設定
    if not execution or "LAST_ONLY" not in execution:
        execution["LAST_ONLY"] = True

    # 実行
    response_chunks = []
    for response_service_info, response_user_info, response_chunk, output_reference in dme.DigiMatsuExecute_Practice(
        service_info,
        user_info,
        session_id,
        session_name,
        agent_file,
        user_input,
        in_situation=situation,
        in_execution=execution
    ):
        # [STATUS]プレフィックスの中間ログは除外し、実レスポンスのみ収集
        if response_chunk and not str(response_chunk).startswith("[STATUS]"):
            response_chunks.append(response_chunk)

    if len(response_chunks) == 1 and not isinstance(response_chunks[0], str):
        response = response_chunks[0]
    else:
        response = "".join(map(str, response_chunks))

    if not session_name:
        session = dms.DigiMSession(session_id, session_name)
        _, _, new_session_name, _, _, _ = dmt.gene_session_name(service_info, user_info, session.session_id, session.session_name, "", user_input)
        session_name = f"(User:{user_info['USER_ID']}){new_session_name}"
        session.chg_session_name(session_name)

    return response_service_info, response_user_info, session_id, session_name, response, output_reference

# バックグラウンドでジョブを実行してジョブストアに結果を書き込む
def _run_job(job_id: str, service_info: dict, user_info: dict, session_id: str, session_name: str,
             user_input: str, situation: dict, agent_file: str, execution: dict):
    try:
        response_service_info, response_user_info, session_id, session_name, response, output_reference = exec_function(
            service_info, user_info, session_id, session_name, user_input, situation, agent_file, execution
        )
        result = {
            "service_info": response_service_info,
            "user_info": response_user_info,
            "session_id": session_id,
            "session_name": session_name,
            "response": response,
            "output_reference": output_reference
        }
        if response_service_info.get("SERVICE_DATA", {}).get("_temp_response_keywords"):
            result["metadata"] = {"keywords": response_service_info["SERVICE_DATA"].pop("_temp_response_keywords")}
        with _jobs_lock:
            _jobs[job_id] = {"status": "done", "result": result}
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "error": str(e)}

@app.post("/run_function")
async def run_function(data: InputData, background_tasks: BackgroundTasks):
    agent_file = data.agent_file or api_agent_file

    # Pydantic → dict に変換
    service_info = data.service_info.model_dump()
    user_info = data.user_info.model_dump()

    # ジョブIDを発行して即時返却
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "processing", "result": None}

    background_tasks.add_task(
        _run_job, job_id,
        service_info, user_info,
        data.session_id or "", data.session_name or "",
        data.user_input, data.situation, agent_file, data.execution
    )

    return {"job_id": job_id, "status": "processing"}

@app.get("/result/{job_id}")
async def get_result(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_id not found")
    if job["status"] == "processing":
        return {"status": "processing"}
    if job["status"] == "error":
        raise HTTPException(status_code=500, detail=job["error"])
    # 完了済みはジョブストアから削除して返す
    with _jobs_lock:
        _jobs.pop(job_id, None)
    return {"status": "done", **job["result"]}

@app.get("/agents", tags=["Agent"])
async def get_agent_list():
    import glob as _glob
    agent_path = "/work/user/common/agent"
    if not os.path.isdir(agent_path):
        return {"agents": []}
    agent_files = [os.path.basename(f) for f in _glob.glob(f"{agent_path}/*.json")]
    return {"agents": agent_files}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(api_port))
