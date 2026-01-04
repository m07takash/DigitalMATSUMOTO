import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from fastapi import FastAPI
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
def exec_function(service_info: dict, user_info: dict, session_id: str, session_name: str, user_input: str, situation: dict, agent_file: str, execution: dict) -> tuple[dict, dict, str, str, str]:
    # セッションの設定（新規でセッションIDを発番）
    if not session_id: 
        session_id = "API"+ dms.set_new_session_id()
#    if not session_name:
#        session_name = f"(User:{user_info['USER_ID']}){api_default_session_name}"
    
    # 実行の設定
    if not execution or "LAST_ONLY" not in execution:
        execution["LAST_ONLY"] = True

    # 実行
    response = ""
    for response_service_info, response_user_info, response_chunk in dme.DigiMatsuExecute_Practice(
        service_info,
        user_info,
        session_id,
        session_name,
        agent_file,
        user_input,
        in_situation=situation,
        in_execution=execution
    ):
        response += response_chunk

    if not session_name:
        session = dms.DigiMSession(session_id, session_name)
        _, _, new_session_name, _, _, _ = dmt.gene_session_name(service_info, user_info, session.session_id, session.session_name, "", user_input)
        session_name = f"(User:{user_info['USER_ID']}){new_session_name}"
        session.chg_session_name(session_name)

    return response_service_info, response_user_info, session_id, session_name, response

@app.post("/run_function")
async def run_function(data: InputData):
    agent_file = data.agent_file or api_agent_file

    # Pydantic → dict に変換
    service_info = data.service_info.model_dump()
    user_info = data.user_info.model_dump()

    # exec_function 呼び出し
    service_info, user_info, session_id, session_name, response = exec_function(
        service_info,
        user_info,
        data.session_id,
        data.session_name,
        data.user_input,
        data.situation,
        agent_file,
        data.execution
    )

    return {
        "service_info": service_info,
        "user_info": user_info,
        "session_id": session_id,
        "session_name": session_name,
        "response": response
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=api_port)
