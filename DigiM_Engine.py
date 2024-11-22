import os
import json
from datetime import datetime
import DigiM_Util as dmu
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Session as dms

# 単体実行用の関数
def DigiMatsuEngine(session_id, session_name, agent_file, sub_seq=1, agent_mode="DEFAULT", user_input="", contents=[], overwrite_items={}, memory_use="Y", magic_word_use="Y", seq_limit="", sub_seq_limit=""):
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
    agent_data = dmu.read_json_file(agent_file)
    agent = dma.DigiM_Agent(agent_data, agent_mode)
    
    # クエリに含まれているコマンド(Magic Word)でエージェントモードを変更して、エージェントを再度宣言
    if magic_word_use == "Y":
        agent_mode = agent.set_agent_mode_by_command(user_input)
        agent = dma.DigiM_Agent(agent_data, agent_mode)
    
    # オーバーライト（エージェントデータの個別項目を更新）して、エージェントを再度宣言
    if overwrite_items:
        dmu.update_dict(agent_data["MODE"][agent_mode], overwrite_items)
        agent = dma.DigiM_Agent(agent_data, agent_mode)

    # ログデータの保存(setting) ※Overwriteやメモリ保存・使用の設定も追加する
    setting_chat_dict = {
        "session_name": session.session_name, 
        "agent_file": agent_file,
        "mode": agent_mode,
        "name": agent.name,
        "act": agent.act,
        "charactor": agent.charactor,
        "system_prompt": agent.system_prompt,
        "model": agent.agent["MODEL"],
        "tool_list": agent.agent["TOOL"]
    }

    # コンテンツコンテキストを取得
    contents_context, contents_records, image_files = agent.set_contents_context(seq, sub_seq, contents)

    # 入力するクエリに纏めて、トークン数を取得
    query = user_input + contents_context
    query_tokens = dmu.count_token(agent.agent["MODEL"]["TOKENIZER"], agent.agent["MODEL"]["MODEL"], query)
    system_tokens = dmu.count_token(agent.agent["MODEL"]["TOKENIZER"], agent.agent["MODEL"]["MODEL"], agent.system_prompt)
    
    # RAGコンテキストを取得
    rag_context, rag_selected, query_vec = agent.set_rag_context(query)
    
    # プロンプトテンプレートを取得
    prompt_template = agent.set_prompt_template()

    # 時間帯の設定
    time_setting = str(datetime.now())
    time_prompt = f"\n現在の日時は「{time_setting}」とします。"
    
    # プロンプトを設定
    prompt = f'{rag_context}{prompt_template}{query}{time_prompt}'

    # 会話メモリの取得
    model_name = agent.agent["MODEL"]["MODEL"]
    tokenizer = agent.agent["MODEL"]["TOKENIZER"]
    if agent.agent["MODEL"]["TYPE"] == "LLM":
        memory_limit_tokens = agent.agent["MODEL"]["MEMORY"]["limit"]
    else:
        memory_limit_tokens = agent.agent["MODEL"]["MEMORY"]["limit"] - (system_tokens + query_tokens)
    memory_role = agent.agent["MODEL"]["MEMORY"]["role"]
    memory_priority = agent.agent["MODEL"]["MEMORY"]["priority"]
    memory_similarity_logic = agent.agent["MODEL"]["MEMORY"]["similarity_logic"]
    memory_digest = agent.agent["MODEL"]["MEMORY"]["digest"]
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
    rag_ref = dmc.get_rag_similarity_response(response_vec, rag_selected)

    # メモリの保存(設定)
    session.save_history(str(seq), "setting", setting_chat_dict, str(sub_seq))
    
    # 入力されたコンテンツの保存
    contents_record_to = []
    for contents_record in contents_records:
        session.save_contents_file(contents_record["from"], contents_record["to"]["file_name"])
        contents_record_to.append(contents_record["to"])
    
    # メモリの保存(prompt) ※ツールの設定も追加する
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
            "setting": agent.agent["PROMPT_TEMPLATE"],
            "text": prompt_template
        },
        "rag":{
            "setting": agent.agent["RAG"],
            "context": rag_context
        }
    }
    session.save_history(str(seq), "prompt", prompt_chat_dict, str(sub_seq))

    # 画像生成モデルの場合
    if agent.agent["MODEL"]["TYPE"]=="IMAGE":
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
    
    # メモリの保存(response)
    response_chat_dict = {
        "role": "assistant",
        "timestamp": timestamp_end,
        "token": response_tokens,
        "text": response,
        "vec_text": response_vec,
        "reference": {
            "memory": memory_ref,
            "rag": rag_ref
        }
    }
    session.save_history(str(seq), "response", response_chat_dict, str(sub_seq))

    # メモリダイジェストの作成
    digest_memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
    digest_memories_selected_text = [{"role": item["role"], "text": item["text"]} for item in digest_memories_selected]
    digest_response, digest_prompt_tokens, digest_response_tokens = dmt.dialog_digest(agent_data, "", digest_memories_selected_text)
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
    
    # メモリの保存（Digest）
    session.save_history(str(seq), "digest", digest_chat_dict, str(sub_seq))

    return response


# プロンプトチェーンで実行
# chains = [{"AGENT_MODE": "", "USER_INPUT": "", "CONTENTS": [], "OVERWRITE_ITEMS": {}},{},...]
def DigiMatsuEngine_Chain(session_id, session_name, agent_file, chains=[], memory_use="Y", magic_word_use="Y"):
    responses = []
    sub_sec = 1
    for chain in chains:
        agent_mode = chain["AGENT_MODE"]
        user_input = chain["USER_INPUT"]
        contents = chain["CONTENTS"]
        overwrite_items = chain["OVERWRITE_ITEMS"]
        seq_limit = chain["PreSEQ"]
        sub_seq_limit = chain["PreSubSEQ"]
        response = DigiMatsuEngine(session_id, session_name, agent_file, sub_sec, agent_mode, user_input, contents, overwrite_items, memory_use, magic_word_use, seq_limit, sub_seq_limit)
        responses.append(response)
        sub_sec = sub_sec + 1
    return responses