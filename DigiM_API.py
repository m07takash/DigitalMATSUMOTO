import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

import DigiM_Session as dms
import DigiM_Agent as dma
import DigiM_Execute as dme

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
api_agent_file = os.getenv("API_AGENT_FILE")
api_port = os.getenv("API_PORT")
api_session_name = os.getenv("API_SESSION_NAME")

app = FastAPI()

# 入力の型定義
class InputData(BaseModel):
    session_id: str
    user_input: str
    user_name: str
    user_info: str
    agent_file: Optional[str] = None

# 実行する関数(session_idにはLINE ID等のユーザーを一意に指定できるキー)
def exec_function(session_id: str, user_input: str, user_name: str, user_info: str, agent_file: str) -> tuple[str, str]:
    # セッションの設定（新規でセッションIDを発番）
    if not session_id: 
        session_id = dms.set_new_session_id()
    session_name = api_session_name +":"+ user_name
    
    # シチュエーション
    in_situation = {}
    in_situation["SITUATION"] = f"話し相手：{user_name}({user_info})"

    # 実行
    response = ""
    for response_chunk in dme.DigiMatsuExecute_Practice(session_id, session_name, agent_file, user_input, in_situation=in_situation, stream_mode=True):
        response += response_chunk 
    
    return session_id, response

@app.post("/run_function")
async def run_function(data: InputData):
    agent_file = data.agent_file or api_agent_file
    session_id, response = exec_function(data.session_id, data.user_input, data.user_name, data.user_info, agent_file)
    return {
        "session_id": session_id,
        "response": response
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=api_port)
