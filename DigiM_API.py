from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

import DigiM_Session as dms
import DigiM_Agent as dma
import DigiM_Execute as dme

app = FastAPI()

# 入力の型定義
class InputData(BaseModel):
    input: str

# 実行する関数
def exec_function(user_input: str) -> str:
    # セッションの設定（新規でセッションIDを発番）
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
    
    return f"Received: {response}"

@app.post("/run_function")
async def run_function(data: InputData):
    result = exec_function(data.input)
    #result = "結果"+data.input
    return {"result": result}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8900)
