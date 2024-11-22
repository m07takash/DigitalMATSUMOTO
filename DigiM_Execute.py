import os
import json
from datetime import datetime
import DigiM_Util as dmu
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Session as dms

# 単体実行用の関数
def DigiMatsuExecute(session_id, session_name, agent_file, sub_seq=1, user_input="", time_setting="", contents=[], overwrite_items={}, prompt_temp_cd="", memory_use="Y", seq_limit="", sub_seq_limit=""):
    # 会話履歴データの定義
    setting_chat_dict = {}
    prompt_chat_dict = {}
    response_chat_dict = {}
    digest_chat_dict = {}
   
    # セッションの宣言
    session = dms.DigiMSession(session_id, session_name)

    # シーケンスの設定(sub_seq=1ならば発番)
    if sub_seq == 1:
        seq = session.get_seq_history() + 1
    else:
        seq = session.get_seq_history()

    # エージェントの宣言
    agent = dma.DigiM_Agent(agent_file)
    
    # オーバーライト（エージェントデータの個別項目を更新）して、エージェントを再度宣言
    if overwrite_items:
        dmu.update_dict(agent.agent, overwrite_items)
        agent.set_property(agent.agent)

    # コンテンツコンテキストを取得
    contents_context, contents_records, image_files = agent.set_contents_context(seq, sub_seq, contents)

    # 入力するクエリに纏めて、トークン数を取得
    query = user_input + contents_context
    query_tokens = dmu.count_token(agent.agent["ENGINE"]["TOKENIZER"], agent.agent["ENGINE"]["MODEL"], query)
    system_tokens = dmu.count_token(agent.agent["ENGINE"]["TOKENIZER"], agent.agent["ENGINE"]["MODEL"], agent.system_prompt)
    
    # RAGコンテキストを取得
    knowledge_context, knowledge_selected, query_vec = agent.set_knowledge_context(query)
    
    # プロンプトテンプレートを取得
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # 時間帯の設定
    if not time_setting:
        time_setting = str(datetime.now())
    time_prompt = f"\n現在の日時は「{time_setting}」とします。"

    # プロンプトを設定
    prompt = f'{knowledge_context}{prompt_template}{query}{time_prompt}'

    # 会話メモリの取得
    model_name = agent.agent["ENGINE"]["MODEL"]
    tokenizer = agent.agent["ENGINE"]["TOKENIZER"]
    if agent.agent["ENGINE"]["TYPE"] == "LLM":
        memory_limit_tokens = agent.agent["ENGINE"]["MEMORY"]["limit"]
    else:
        memory_limit_tokens = agent.agent["ENGINE"]["MEMORY"]["limit"] - (system_tokens + query_tokens)
    memory_role = agent.agent["ENGINE"]["MEMORY"]["role"]
    memory_priority = agent.agent["ENGINE"]["MEMORY"]["priority"]
    memory_similarity_logic = agent.agent["ENGINE"]["MEMORY"]["similarity_logic"]
    memory_digest = agent.agent["ENGINE"]["MEMORY"]["digest"]
    memories_selected = []
    if memory_use == "Y":
        memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
    
    # LLMの実行
    timestamp_begin = str(datetime.now())
    response, completion, prompt_tokens, response_tokens = agent.generate_response(prompt, memories_selected, image_files)
    timestamp_end = str(datetime.now())

    # レスポンスとメモリ・コンテキストの類似度
    response_vec = dmu.embed_text(response.replace("\n", ""))
    memory_ref = dmc.get_memory_similarity_response(response_vec, memories_selected)
    knowledge_ref = dmc.get_rag_similarity_response(response_vec, knowledge_selected)
    
    # 入力されたコンテンツの保存
    contents_record_to = []
    for contents_record in contents_records:
        session.save_contents_file(contents_record["from"], contents_record["to"]["file_name"])
        contents_record_to.append(contents_record["to"])

    # ログデータの保存(setting) ※Overwriteやメモリ保存・使用の設定も追加する
    setting_chat_dict = {
        "session_name": session.session_name, 
        "agent_file": agent_file,
        "name": agent.name,
        "act": agent.act,
        "personality": agent.personality,
        "system_prompt": agent.system_prompt,
        "engine": agent.agent["ENGINE"],
        "knowledge": agent.agent["KNOWLEDGE"],
        "skill": agent.agent["SKILL"]
    }
    session.save_history(str(seq), "setting", setting_chat_dict, str(sub_seq))
    
    # ログデータの保存(prompt) ※ツールの設定も追加する
    prompt_chat_dict = {
        "role": "user",
        "timestamp": timestamp_begin,
        "token": prompt_tokens,
        "text": prompt,
        "query": {
            "input": user_input,
            "token": query_tokens,
            "text": query,
            "contents": contents_record_to,
            "tools": [],
            "vec_text": query_vec
        },
        "prompt_template":{
            "setting": prompt_temp_cd,
            "text": prompt_template
        },
        "knowledge_rag":{
            "setting": agent.agent["KNOWLEDGE"],
            "context": knowledge_context
        }
    }
    session.save_history(str(seq), "prompt", prompt_chat_dict, str(sub_seq))

    # ログデータの保存（生成した画像）
    if agent.agent["ENGINE"]["TYPE"]=="IMAGE":
        img_dict = {}
        i=0
        for img_completion_path in completion:
            img_file_name = os.path.basename(img_completion_path)
            session.save_contents_file(img_completion_path, img_file_name)
            # メモリの保存(response)
            img_dict[i] = {
                "role": "image",
                "timestamp": timestamp_end,
                "file_name": img_file_name,
                "file_type": "image/jpeg"
            }
            i = i + 1
        session.save_history(str(seq), "image", img_dict, str(sub_seq))
    
    # ログデータの保存(response)
    response_chat_dict = {
        "role": "assistant",
        "timestamp": timestamp_end,
        "token": response_tokens,
        "text": response,
        "vec_text": response_vec,
        "reference": {
            "memory": memory_ref,
            "knowledge_rag": knowledge_ref
        }
    }
    session.save_history(str(seq), "response", response_chat_dict, str(sub_seq))

    # メモリダイジェストの作成【作成するエージェントを通常のLLMに変更】
    digest_memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
    digest_memories_selected_text = [{"role": item["role"], "text": item["text"]} for item in digest_memories_selected]
    digest_response, digest_prompt_tokens, digest_response_tokens = dmt.dialog_digest(agent_file, "", digest_memories_selected_text)
    timestamp_digest = str(datetime.now())
    digest_response_vec = dmu.embed_text(digest_response.replace("\n", ""))
    
    # ログデータの保存(digest)
    digest_chat_dict = {
        "role": "assistant",
        "timestamp": timestamp_digest,
        "token": digest_response_tokens,
        "text": digest_response,
        "vec_text": digest_response_vec
    }
    session.save_history(str(seq), "digest", digest_chat_dict, str(sub_seq))

    return response


# プロンプトチェーンで実行
# chains = [{"USER_INPUT": "", "CONTENTS": [], "OVERWRITE_ITEMS": {}},{},...]
def DigiMatsuExecute_Chain(session_id, session_name, agent_file, chains=[], memory_use="Y", magic_word_use="Y"):
    responses = []
    sub_sec = 1
    time_setting = ""
#    # クエリに含まれているコマンド(Magic Word)でタスクを変更
#    if magic_word_use == "Y":        
    prompt_temp_cd="No Template" #いったんデフォルトでプロンプトテンプレを設定

    for chain in chains:
        user_input = chain["USER_INPUT"]
        contents = chain["CONTENTS"]
        overwrite_items = chain["OVERWRITE_ITEMS"]
        seq_limit = chain["PreSEQ"]
        sub_seq_limit = chain["PreSubSEQ"]
        response = DigiMatsuExecute(session_id, session_name, agent_file, sub_sec, user_input, time_setting, contents, overwrite_items, prompt_temp_cd, memory_use, seq_limit, sub_seq_limit)
        responses.append(response)
        sub_sec = sub_sec + 1
    return responses