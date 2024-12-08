import os
import json
from datetime import datetime
import pytz
import DigiM_Util as dmu
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Session as dms

agent_folder_path = os.getenv("AGENT_FOLDER")
practice_folder_path = os.getenv("PRACTICE_FOLDER")
timezone_setting = os.getenv("TIMEZONE")

# 単体実行用の関数
def DigiMatsuExecute(session_id, session_name, agent_file, sub_seq=1, user_input="", contents=[], situation={}, overwrite_items={}, add_knowledge=[], prompt_temp_cd="", memory_use=True, seq_limit="", sub_seq_limit=""):
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
    agent = dma.DigiM_Agent(agent_folder_path+agent_file)
    
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

    # 会話のダイジェストを取得(ダイジェストはRAGとMemoryの類似度検索にのみ用い、プロンプトには含めない)
    query_digest = query
    if session.chat_history_active_dict:
        max_seq, max_sub_seq, chat_history_max_digest_dict = session.get_history_max_digest(session.chat_history_active_dict)
        if chat_history_max_digest_dict:
            digest_text = "会話履歴のダイジェスト:\n"+chat_history_max_digest_dict["text"]+"\n---\n"
            query_digest = digest_text + query_digest

    # RAGコンテキストを取得(追加ナレッジを反映)
    if add_knowledge:
        agent.knowledge += add_knowledge
    knowledge_context, knowledge_selected, query_vec = agent.set_knowledge_context(query_digest)
    
    # プロンプトテンプレートを取得
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

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
    if memory_use:
        memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)

    # シチュエーションの設定
    situation_setting = "\n"
    time_setting = str(datetime.now(pytz.timezone(timezone_setting)).strftime('%Y/%m/%d %H:%M:%S'))
    if situation:
        if "SITUATION" in situation:
            situation_setting = situation["SITUATION"]+"\n"
        if "TIME" in situation:
            time_setting = situation["TIME"]
    situation_prompt = f"\n【状況】\n{situation_setting}現在は「{time_setting}」です。"

    # プロンプトを設定
    prompt = f'{knowledge_context}{prompt_template}{query}{situation_prompt}'
    
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
    
    # ログデータの保存(SubSeq:setting) ※Overwriteやメモリ保存・使用の設定も追加する
    setting_chat_dict = {
        "session_name": session.session_name, 
        "situation": situation,
        "agent_file": agent_file,
        "name": agent.name,
        "act": agent.act,
        "personality": agent.personality,
        "system_prompt": agent.system_prompt,
        "engine": agent.agent["ENGINE"],
        "knowledge": agent.agent["KNOWLEDGE"],
        "skill": agent.agent["SKILL"]
    }
    session.save_history(str(seq), "setting", setting_chat_dict, "SUB_SEQ", str(sub_seq))
    
    # ログデータの保存(SubSeq:prompt) ※ツールの設定も追加する
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
            "situation": situation,
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
    session.save_history(str(seq), "prompt", prompt_chat_dict, "SUB_SEQ", str(sub_seq))

    # ログデータの保存(SubSeq:image)
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
        session.save_history(str(seq), "image", img_dict, "SUB_SEQ", str(sub_seq))
    
    # ログデータの保存(SubSeq:response)
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
    session.save_history(str(seq), "response", response_chat_dict, "SUB_SEQ", str(sub_seq))

    # メモリダイジェストの作成
    session.set_history()
    digest_memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
    digest_response, digest_prompt_tokens, digest_response_tokens = dmt.dialog_digest("", digest_memories_selected)
    timestamp_digest = str(datetime.now())
    digest_response_vec = dmu.embed_text(digest_response.replace("\n", ""))
    
    # ログデータの保存(SubSeq:digest)
    digest_chat_dict = {
        "role": "assistant",
        "timestamp": timestamp_digest,
        "token": digest_response_tokens,
        "text": digest_response,
        "vec_text": digest_response_vec
    }
    session.save_history(str(seq), "digest", digest_chat_dict, "SUB_SEQ", str(sub_seq))

    return response


# プラクティスで実行
def DigiMatsuExecute_Practice(session_id, session_name, in_agent_file, query, in_contents, in_situation={}, in_overwrite_items={}, practice={}, in_memory_use=True, magic_word_use="Y"):
    sub_seq = 1
    results = []

    # プラクティスの選択
    habit = "DEFAULT"
    if magic_word_use == "Y":
        agent = dma.DigiM_Agent(agent_folder_path+in_agent_file)
        habit = agent.set_practice_by_command(query)
    practice_file = practice[habit]["PRACTICE"]
    practice = dmu.read_json_file(practice_folder_path+practice_file)

    # プラクティス(チェイン)の実行
    for chain in practice["CHAINS"]:
        result = {}
        input = ""
        output = ""

        # TYPE「LLM」の場合
        if chain["TYPE"]=="LLM":
            setting = chain["SETTING"]
            # "USER":ユーザー入力(引数)、他:プラクティスファイルの設定
            agent_file = setting["AGENT_FILE"] if setting["AGENT_FILE"] != "USER" else in_agent_file
            overwrite_items = setting["OVERWRITE_ITEMS"] if setting["OVERWRITE_ITEMS"] != "USER" else in_overwrite_items
            add_knowledge = setting["ADD_KNOWLEDGE"]
            prompt_temp_cd = setting["PROMPT_TEMPLATE"]
            
            # "USER":ユーザー入力(引数)、"INPUT{SubSeqNo}":サブSEQの入力結果、"RESULT{SubSeqNo}":サブSEQの出力結果
            user_input = ""
            if setting["USER_INPUT"] == "USER":
                user_input = query
            elif setting["USER_INPUT"].startswith("INPUT"):
                ref_subseq = int(setting["USER_INPUT"].replace("INPUT", "").strip())
                user_input = next((item["INPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
            elif setting["USER_INPUT"].startswith("OUTPUT"):
                ref_subseq = int(setting["USER_INPUT"].replace("OUTPUT", "").strip())
                user_input = next((item["OUTPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
            else:
                setting["USER_INPUT"]

            # コンテンツの設定
            contents = setting["CONTENTS"] if setting["CONTENTS"] != "USER" else in_contents

            # シチュエーションの設定
            situation = {}
            if setting["SITUATION"] == "USER":
                situation = in_situation
            else:
                situation["TIME"] = in_situation["TIME"] if setting["SITUATION"]["TIME"] == "USER" else setting["SITUATION"]["TIME"]
                situation["SITUATION"] = in_situation["SITUATION"] if setting["SITUATION"]["SITUATION"] == "USER" else setting["SITUATION"]["SITUATION"]

            # メモリ利用可否
            memory_use = in_memory_use and setting["MEMORY_USE"]
    #        seq_limit = chain["PreSEQ"] #メモリ参照範囲のSeq
    #        sub_seq_limit = chain["PreSubSEQ"] #メモリ参照範囲のsubSeq

            # LLM実行
            response = DigiMatsuExecute(session_id, session_name, agent_file, sub_seq, user_input, contents, situation, overwrite_items, add_knowledge, prompt_temp_cd, memory_use) #, seq_limit, sub_seq_limit)    
            input = user_input
            output = response

        elif chain["TYPE"]=="TOOL":
            break
        
        # 結果のリストへの格納
        result["SubSEQ"]=sub_seq
        result["TYPE"]=chain["TYPE"]
        result["INPUT"]=input
        result["OUTPUT"]=output
        results.append(result)

        # サブSEQ更新
        sub_seq = sub_seq + 1

    # ログデータの保存(Seq)
    session = dms.DigiMSession(session_id, session_name)
    seq = session.get_seq_history()
    session.save_history(str(seq), "practice", practice, "SEQ")
 
    return results