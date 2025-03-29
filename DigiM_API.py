from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

import DigiM_Session as dms
import DigiM_Agent as dma
import DigiM_Execute as dme

app = FastAPI()

# 入力の型定義
class InputData(BaseModel):
    session_id: str
    user_input: str

# 実行する関数
def exec_function(session_id: str, user_input: str) -> tuple[str, str]:
    # セッションの設定（新規でセッションIDを発番）
    print(session_id)
    if not session_id:
        session_id = dms.set_new_session_id()
    session_name = "API実行"
    
    # エージェント設定
    agent_file = "agent_01DigitalMATSUMOTO_GPT.json"
    agent = dma.DigiM_Agent(agent_file)
    practice = agent.habit

    # 実行
    response = ""
    for response_chunk in dme.DigiMatsuExecute_Practice(session_id, session_name, agent_file, user_input, practice=practice, stream_mode=True):
        response += response_chunk 
    
    return session_id, response

@app.post("/run_function")
async def run_function(data: InputData):
    session_id, response = exec_function(data.session_id, data.user_input)
    return {
        "session_id": session_id,
        "response": response
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8900)
