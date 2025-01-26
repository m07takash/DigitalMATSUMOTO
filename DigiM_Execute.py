import os
import json
from datetime import datetime

import pytz
import DigiM_Util as dmu
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Session as dms

user_folder_path = os.getenv("USER_FOLDER")
session_folder_prefix = os.getenv("SESSION_FOLDER_PREFIX")
temp_folder_path = os.getenv("TEMP_FOLDER")
practice_folder_path = os.getenv("PRACTICE_FOLDER")
timezone_setting = os.getenv("TIMEZONE")

# 単体実行用の関数
def DigiMatsuExecute(session_id, session_name, agent_file, model_type="LLM", stream_mode=True, sub_seq=1, user_input="", contents=[], situation={}, overwrite_items={}, add_knowledge=[], prompt_temp_cd="", memory_use=True, seq_limit="", sub_seq_limit=""):
    export_files = []
    timestamp_log = "[01.実行開始(セッション設定)]"+str(datetime.now())+"<br>"
    
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
    timestamp_log += "[02.エージェント設定開始]"+str(datetime.now())+"<br>"
    agent = dma.DigiM_Agent(agent_file)
    
    # オーバーライト（エージェントデータの個別項目を更新）して、エージェントを再度宣言
    if overwrite_items:
        dmu.update_dict(agent.agent, overwrite_items)
        agent.set_property(agent.agent)

    # コンテンツコンテキストを取得
    timestamp_log += "[03.コンテンツコンテキスト読込開始]"+str(datetime.now())+"<br>"
    contents_context, contents_records, image_files = agent.set_contents_context(seq, sub_seq, contents)

    # 入力するクエリに纏めて、トークン数を取得
    user_query = user_input + contents_context
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    query_tokens = dmu.count_token(tokenizer, model_name, user_query)
    system_tokens = dmu.count_token(tokenizer, model_name, agent.system_prompt)

    # 会話のダイジェストを取得(ダイジェストはRAGとMemoryの類似度検索にのみ用い、プロンプトには含めない)
    timestamp_log += "[04.会話ダイジェスト読込開始]"+str(datetime.now())+"<br>"
    if session.chat_history_active_dict:
        max_seq, max_sub_seq, chat_history_max_digest_dict = session.get_history_max_digest()#session.chat_history_active_dict)
        if chat_history_max_digest_dict:
            digest_text = "会話履歴のダイジェスト:\n"+chat_history_max_digest_dict["text"]+"\n---\n"
            user_query = digest_text + user_query

    # クエリのベクトル化
    timestamp_log += "[05.クエリのベクトル化開始]"+str(datetime.now())+"<br>"
    query_vec = dmu.embed_text(user_query.replace("\n", ""))

    # RAGコンテキストを取得(追加ナレッジを反映)
    timestamp_log += "[06.RAG開始]"+str(datetime.now())+"<br>"
    if add_knowledge:
        agent.knowledge += add_knowledge
    knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vec)
    
    # プロンプトテンプレートを取得
    timestamp_log += "[07.プロンプトテンプレート設定]"+str(datetime.now())+"<br>"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # 会話メモリの取得
    timestamp_log += "[08.会話メモリの取得開始]"+str(datetime.now())+"<br>"
    if model_type == "LLM":
        memory_limit_tokens = agent.agent["ENGINE"][model_type]["MEMORY"]["limit"]
    else:
        memory_limit_tokens = agent.agent["ENGINE"][model_type]["MEMORY"]["limit"] - (system_tokens + query_tokens)
    memory_role = agent.agent["ENGINE"][model_type]["MEMORY"]["role"]
    memory_priority = agent.agent["ENGINE"][model_type]["MEMORY"]["priority"]
    memory_similarity_logic = agent.agent["ENGINE"][model_type]["MEMORY"]["similarity_logic"]
    memory_digest = agent.agent["ENGINE"][model_type]["MEMORY"]["digest"]
    memories_selected = []
    if memory_use:
        memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)

    # シチュエーションの設定
    timestamp_log += "[09.シチュエーション設定]"+str(datetime.now())+"<br>"
    situation_setting = "\n"
    time_setting = str(datetime.now(pytz.timezone(timezone_setting)).strftime('%Y/%m/%d %H:%M:%S'))
    if situation:
        if "SITUATION" in situation:
            situation_setting = situation["SITUATION"]+"\n"
        if "TIME" in situation:
            time_setting = situation["TIME"]
    situation_prompt = f"\n【状況】\n{situation_setting}現在は「{time_setting}」です。"

    # プロンプトを設定(最終的にテキスト制限値でアロケート)
    if model_type == "LLM":
        query = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'
    elif model_type == "IMAGEGEN":
        query = f'{prompt_template}{user_query}{situation_prompt}'
    
    # LLMの実行
    response = ""
    timestamp_begin = str(datetime.now())
    timestamp_log += "[10.LLM実行開始]"+timestamp_begin+"<br>"
#    response, completion, prompt_tokens, response_tokens = agent.generate_response(model_type, query, memories_selected, image_files)
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, memories_selected, image_files, stream_mode):
        if response_chunk:
            response += response_chunk
            yield response_chunk, export_files
    timestamp_end = str(datetime.now())
    timestamp_log += "[11.LLM実行完了]"+timestamp_end+"<br>"

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    # レスポンスとメモリ・コンテキストの類似度
    timestamp_log += "[12.結果の類似度算出開始]"+str(datetime.now())+"<br>"
    response_vec = dmu.embed_text(response.replace("\n", ""))
    memory_ref = dmc.get_memory_similarity_response(response_vec, memories_selected)
    knowledge_ref = dmc.get_rag_similarity_response(response_vec, knowledge_selected)
    
    # 入力されたコンテンツの保存
    timestamp_log += "[13.コンテンツの保存開始]"+str(datetime.now())+"<br>"
    contents_record_to = []
    for contents_record in contents_records:
        session.save_contents_file(contents_record["from"], contents_record["to"]["file_name"])
        contents_record_to.append(contents_record["to"])

    # ログデータの保存(SubSeq:setting) ※Overwriteやメモリ保存・使用の設定も追加する
    timestamp_log += "[14.ログ(setting)の保存開始]"+str(datetime.now())+"<br>"
    setting_chat_dict = {
        "session_name": session.session_name, 
        "situation": situation,
        "type": model_type,
        "agent_file": agent_file,
        "name": agent.name,
        "act": agent.act,
        "personality": agent.personality,
        "system_prompt": agent.system_prompt,
        "engine": agent.agent["ENGINE"][model_type],
        "knowledge": agent.agent["KNOWLEDGE"],
        "skill": agent.agent["SKILL"]
    }
    session.save_history(str(seq), "setting", setting_chat_dict, "SUB_SEQ", str(sub_seq))
    
    # ログデータの保存(SubSeq:prompt) ※ツールの設定も追加する
    timestamp_log += "[15.ログ(prompt)の保存開始]"+str(datetime.now())+"<br>"
    prompt_chat_dict = {
        "role": "user",
        "timestamp": timestamp_begin,
        "token": prompt_tokens,
        "text": prompt,
        "query": {
            "input": user_input,
            "token": query_tokens,
            "text": user_query,
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
    timestamp_log += "[16.ログ(image)の保存開始]"+str(datetime.now())+"<br>"
    if model_type=="IMAGEGEN":
        img_dict = {}
        i=0
        for img_completion_path in completion:
            img_file_name = "[OUT]seq"+str(seq)+"-"+str(sub_seq)+"_"+os.path.basename(img_completion_path)
            session.save_contents_file(img_completion_path, img_file_name)
            # メモリの保存(response)
            img_dict[i] = {
                "role": "image",
                "timestamp": timestamp_end,
                "file_name": img_file_name,
                "file_type": "image/jpeg"
            }
            i = i + 1
            export_files.append(session.session_folder_path +"contents/"+img_file_name)
        session.save_history(str(seq), "image", img_dict, "SUB_SEQ", str(sub_seq))
    
    # ログデータの保存(SubSeq:response)
    timestamp_log += "[17.ログ(response)の保存開始]"+str(datetime.now())+"<br>"
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
    timestamp_log += "[18.メモリダイジェストの作成開始]"+str(datetime.now())+"<br>"
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

    # ログデータの保存(SubSeq:log)
    timestamp_log += "[完了]"+str(datetime.now())+"<br>"
    log_dict = {
        "timestamp_log": timestamp_log
    }
    session.save_history(str(seq), "log", log_dict, "SUB_SEQ", str(sub_seq))
    
    yield "", export_files


# プラクティスで実行
def DigiMatsuExecute_Practice(session_id, session_name, in_agent_file, user_query, in_contents, in_situation={}, in_overwrite_items={}, practice={}, in_memory_use=True, magic_word_use="Y", stream_mode=True):
    session = dms.DigiMSession(session_id, session_name)
    sub_seq = 1
    results = []

    # プラクティスの選択
    habit = "DEFAULT"
    if magic_word_use == "Y":
        agent = dma.DigiM_Agent(in_agent_file)
        habit = agent.set_practice_by_command(user_query)
    practice_file = practice[habit]["PRACTICE"]
    practice = dmu.read_json_file(practice_folder_path+practice_file)
    
    # プラクティス(チェイン)の実行
    for chain in practice["CHAINS"]:
        result = {}
        model_type = chain["TYPE"]
        input = ""
        output = ""
        import_contents = []
        export_contents = []

        # TYPE「LLM」の場合
        if model_type in ["LLM", "IMAGEGEN"]:
            setting = chain["SETTING"]
            # "USER":ユーザー入力(引数)、他:プラクティスファイルの設定
            agent_file = setting["AGENT_FILE"] if setting["AGENT_FILE"] != "USER" else in_agent_file
            overwrite_items = setting["OVERWRITE_ITEMS"] if setting["OVERWRITE_ITEMS"] != "USER" else in_overwrite_items
            add_knowledge = setting["ADD_KNOWLEDGE"]
            prompt_temp_cd = setting["PROMPT_TEMPLATE"]
            
            # "USER":ユーザー入力(引数)、"INPUT{SubSeqNo}":サブSEQの入力結果、"RESULT{SubSeqNo}":サブSEQの出力結果
            user_input = ""
            if setting["USER_INPUT"] == "USER":
                user_input = user_query
            elif setting["USER_INPUT"].startswith("INPUT"):
                ref_subseq = int(setting["USER_INPUT"].replace("INPUT", "").strip())
                user_input = next((item["INPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
            elif setting["USER_INPUT"].startswith("OUTPUT"):
                ref_subseq = int(setting["USER_INPUT"].replace("OUTPUT", "").strip())
                user_input = next((item["OUTPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
            else:
                user_input = setting["USER_INPUT"]

            # コンテンツの設定
            import_contents = setting["CONTENTS"] if setting["CONTENTS"] != "USER" else in_contents
            if setting["CONTENTS"] == "USER":
                import_contents = in_contents
            elif setting["CONTENTS"].startswith("IMPORT_"):
                ref_subseq = int(setting["CONTENTS"].replace("IMPORT_", "").strip())
                import_contents = next((item["IMPORT_CONTENTS"] for item in results if item["SubSEQ"] == ref_subseq), None)
            elif setting["CONTENTS"].startswith("EXPORT_"):
                ref_subseq = int(setting["CONTENTS"].replace("EXPORT_", "").strip())
                import_contents = next((item["EXPORT_CONTENTS"] for item in results if item["SubSEQ"] == ref_subseq), None)
            else:
                import_contents = setting["CONTENTS"]

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
            response = ""
            for response_chunk, export_contents in DigiMatsuExecute(session_id, session_name, agent_file, model_type, stream_mode, sub_seq, user_input, import_contents, situation, overwrite_items, add_knowledge, prompt_temp_cd, memory_use): #, seq_limit, sub_seq_limit)
                response += response_chunk
                yield response_chunk
            
            input = user_input
            output = response

        elif model_type =="TOOL":
            # セッションの宣言
#            session = dms.DigiMSession(session_id, session_name)
            
            # シーケンスの設定(sub_seq=1ならば発番)
            if sub_seq == 1:
                seq = session.get_seq_history() + 1
            else:
                seq = session.get_seq_history()

            # ツールの実行
            setting = chain["SETTING"]
            input = user_query
            import_contents = in_contents

            timestamp_begin = str(datetime.now())
            output, export_contents = dmt.call_function_by_name(setting["FUNC_NAME"], session_id)
            timestamp_end = str(datetime.now())
            
            # ログデータの保存
            setting_chat_dict = {
                "session_name": session.session_name, 
                "situation": in_situation,
                "type": model_type,
                "agent_file": in_agent_file,
                "name": practice["NAME"],
                "tool": setting["FUNC_NAME"]
            }
            session.save_history(str(seq), "setting", setting_chat_dict, "SUB_SEQ", str(sub_seq))

            prompt_chat_dict = {
                "role": "user",
                "timestamp": timestamp_begin,                
                "text": input,
                "query": {
                    "input": input,
                    "contents": import_contents
                }
            }
            session.save_history(str(seq), "prompt", prompt_chat_dict, "SUB_SEQ", str(sub_seq))
        
            response_chat_dict = {
                "role": "assistant",
                "timestamp": timestamp_end,
                "text": output,
                "export_contents": export_contents
            }
            session.save_history(str(seq), "response", response_chat_dict, "SUB_SEQ", str(sub_seq))

            yield output
        
        # 結果のリストへの格納
        result["SubSEQ"]=sub_seq
        result["TYPE"]=model_type
        result["INPUT"]=input
        chat_history_dict=session.get_history()
        seq = session.get_seq_history()
        result["IMPORT_CONTENTS"]=[session.session_folder_path+"contents/"+i["file_name"] for i in chat_history_dict[str(seq)][str(sub_seq)]["prompt"]["query"]["contents"]]
        result["OUTPUT"]=output
        result["EXPORT_CONTENTS"]=export_contents
        results.append(result)

        # サブSEQ更新
        sub_seq = sub_seq + 1

    # ログデータの保存(Seq)
    seq = session.get_seq_history()
    session.save_history(str(seq), "practice", practice, "SEQ")
 
#    return results