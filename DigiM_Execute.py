import os
import json
from datetime import datetime

import inspect
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

# セッションロックエラー
class SessionLockedError(RuntimeError):
    pass

# 単体実行用の関数
def DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type="LLM", sub_seq=1, user_input="", contents=[], situation={}, overwrite_items={}, add_knowledge=[], prompt_temp_cd="", execution={}, seq_limit="", sub_seq_limit=""):  
    export_files = []
    timestamp_begin = str(datetime.now())
    timestamp_log = "[01.実行開始(セッション設定)]"+str(datetime.now())+"<br>"

    # 実行設定の取得
    memory_use = execution.get("MEMORY_USE", True)
    memory_similarity = execution.get("MEMORY_SIMILARITY", False)
    magic_word_use = execution.get("MAGIC_WORD_USE", True)
    stream_mode = execution.get("STREAM_MODE", True)
    save_digest = execution.get("SAVE_DIGEST", True)
    meta_search = execution.get("META_SEARCH", True)
    RAG_query_gene = execution.get("RAG_QUERY_GENE", True)

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
    digest_text = ""
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    query_tokens = dmu.count_token(tokenizer, model_name, user_query)
    system_tokens = dmu.count_token(tokenizer, model_name, agent.system_prompt)

    # シチュエーションの設定
    timestamp_log += "[04.シチュエーション設定]"+str(datetime.now())+"<br>"
    situation_setting = ""
    time_setting = str(datetime.now(pytz.timezone(timezone_setting)).strftime('%Y/%m/%d %H:%M:%S'))
    if situation:
        if "SITUATION" in situation:
            situation_setting = situation["SITUATION"]+"\n"
        if "TIME" in situation:
            time_setting = situation["TIME"]
    situation_prompt = f"\n【状況】\n{situation_setting}現在は「{time_setting}」です。"

    # 会話のダイジェストを取得
    if memory_use:
        timestamp_log += "[05.会話ダイジェスト読込開始]"+str(datetime.now())+"<br>"
        if session.chat_history_active_dict:
            max_seq, max_sub_seq, chat_history_max_digest_dict = session.get_history_max_digest()#session.chat_history_active_dict)
            if chat_history_max_digest_dict:
                digest_text = "会話履歴のダイジェスト:\n"+chat_history_max_digest_dict["text"]+"\n---\n"
    
    # クエリのベクトル化（RAGの検索は「0.ユーザ入力」「1.ユーザー入力＋メモリダイジェスト」の類似している方を取る）
    timestamp_log += "[06.クエリのベクトル化開始]"+str(datetime.now())+"<br>"
    queries = []
    query_vecs = []    
    queries.append(user_query)
    query_vec = dmu.embed_text(user_query.replace("\n", ""))
    query_vecs.append(query_vec)
    
    # ダイジェストもしくはシチュエーション設定(時刻以外)があれば追加
    if digest_text or situation_prompt:
        user_query_digest_situation = digest_text + user_query + situation_prompt
        queries.append(user_query_digest_situation)
        query_vec_digest_situation = dmu.embed_text(user_query_digest_situation.replace("\n", ""))
        query_vecs.append(query_vec_digest_situation)

    # 会話メモリの取得
    timestamp_log += "[07.会話メモリの取得開始]"+str(datetime.now())+"<br>"
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
        memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
#        memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_digest, seq_limit, sub_seq_limit)
    
    # サポートエージェントの設定
    support_agent = agent.agent["SUPPORT_AGENT"]

    # RAG検索用クエリ(意図)の生成
    timestamp_log += "[11.RAG検索用クエリ(意図)の生成]"+str(datetime.now())+"<br>"
    RAG_query_gene_log = {}
    if RAG_query_gene and "RAG_QUERY_GENERATOR" in support_agent:
        RAG_query_gene_agent_file = support_agent["RAG_QUERY_GENERATOR"]
        _, _, RAG_query_gene_response, RAG_query_gene_model_name, RAG_query_gene_prompt_tokens, RAG_query_gene_response_tokens = dmt.RAG_query_generator(service_info, user_info, user_query, situation_prompt, query_vecs, memories_selected, agent_file=RAG_query_gene_agent_file)
        queries.append(RAG_query_gene_response)
        query_vec_RAGquery = dmu.embed_text(RAG_query_gene_response.replace("\n", ""))
        query_vecs.append(query_vec_RAGquery)
        # ログに格納
        RAG_query_gene_log = {}
        RAG_query_gene_log["agent_file"] = RAG_query_gene_agent_file
        RAG_query_gene_log["model"] = RAG_query_gene_model_name
        RAG_query_gene_log["llm_response"] = RAG_query_gene_response
        RAG_query_gene_log["prompt_token"] = RAG_query_gene_prompt_tokens
        RAG_query_gene_log["response_token"] = RAG_query_gene_response_tokens
    
    # クエリからメタデータ検索情報の取得
    meta_search_log = {}
    meta_searches = []
    get_date_list = []
    timestamp_log += "[12.クエリからメタデータ検索情報の取得]"+str(datetime.now())+"<br>"
    if meta_search and "EXTRACT_DATE" in support_agent:
        # ユーザー入力から時間を取得
        extract_date_agent_file = support_agent["EXTRACT_DATE"]
        _, _, extract_date_response, extract_date_model_name, extract_date_prompt_tokens, extract_date_response_tokens = dmt.extract_date(service_info, user_info, user_query, situation_prompt, [query_vec], memories_selected, agent_file=extract_date_agent_file)
        get_date_list += dmu.extract_list_pattern(extract_date_response) 
        meta_searches.append({"DATE": get_date_list})
        # ログに格納
        meta_search_log["date"] = {}
        meta_search_log["date"]["agent_file"] = extract_date_agent_file
        meta_search_log["date"]["model"] = extract_date_model_name
        meta_search_log["date"]["condition_list"] = get_date_list
        meta_search_log["date"]["llm_response"] = extract_date_response
        meta_search_log["date"]["prompt_token"] = extract_date_prompt_tokens
        meta_search_log["date"]["response_token"] = extract_date_response_tokens
    
    # RAGコンテキストを取得(追加ナレッジを反映)
    timestamp_log += "[13.RAG開始]"+str(datetime.now())+"<br>"
    if add_knowledge:
        agent.knowledge += add_knowledge
    exec_info = {"SERVICE_INFO": service_info, "USER_INFO": user_info}
    knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs, exec_info, meta_searches, )
    
    # プロンプトテンプレートを取得
    timestamp_log += "[14.プロンプトテンプレート設定]"+str(datetime.now())+"<br>"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # プロンプトを設定(最終的にテキスト制限値でアロケート)
    if model_type == "LLM":
        query = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'
    elif model_type == "IMAGEGEN":
        query = f'{prompt_template}{user_query}{situation_prompt}'
    
    # LLMの実行
    prompt = ""
    response = ""
    timestamp_log += "[21.LLM実行開始]"+str(datetime.now())+"<br>"
    response_service_info = {}
    response_user_info = {}
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, memories_selected, image_files, stream_mode):
        if response_chunk:
            response += response_chunk
            response_service_info = service_info
            response_user_info = user_info
            yield response_service_info, response_user_info, response_chunk, export_files
    timestamp_end = str(datetime.now())
    timestamp_log += "[22.LLM実行完了]"+str(datetime.now())+"<br>"

    prompt_tokens = 0
    response_tokens = 0
    if prompt:
        prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    if response:
        response_tokens = dmu.count_token(tokenizer, model_name, response)

    # レスポンスとメモリ・コンテキストの類似度
    timestamp_log += "[23.結果の類似度算出開始]"+str(datetime.now())+"<br>"
    response_vec = dmu.embed_text(response.replace("\n", ""))
    memory_ref = dmc.get_memory_reference(memories_selected, memory_similarity, response_vec, memory_similarity_logic)
    knowledge_ref = dmc.get_knowledge_reference(response_vec, knowledge_selected)
    
    # 入力されたコンテンツの保存
    timestamp_log += "[24.コンテンツの保存開始]"+str(datetime.now())+"<br>"
    contents_record_to = []
    for contents_record in contents_records:
        session.save_contents_file(contents_record["from"], contents_record["to"]["file_name"])
        contents_record_to.append(contents_record["to"])

    # ログデータの保存(setting) ※Overwriteやメモリ保存・使用の設定も追加する
    timestamp_log += "[31.ログ(setting)の保存開始]"+str(datetime.now())+"<br>"
    setting_chat_dict = {
        "session_id": session.session_id,
        "session_name": session.session_name, 
        "type": model_type,
        "agent_file": agent_file,
        "name": agent.name,
        "engine": agent.agent["ENGINE"][model_type],
        "communication": agent.agent["COMMUNICATION"]
    }
    session.save_history(str(seq), "setting", setting_chat_dict, "SUB_SEQ", str(sub_seq))
    
    # ログデータの保存(prompt) ※ツールの設定も追加する
    timestamp_log += "[32.ログ(prompt)の保存開始]"+str(datetime.now())+"<br>"

    # メモリ類似度を評価する場合
    query_vec_file = ""
    if memory_similarity:
        query_vec_file = session.save_vec_file(str(seq), str(sub_seq), "query", query_vec)

    prompt_chat_dict = {
        "role": "user",
        "timestamp": timestamp_begin,
        "token": prompt_tokens,
        "query": {
            "input": user_input,
            "token": query_tokens,
            "text": user_query,
            "contents": contents_record_to,
            "situation": situation,
            "tools": [],
            "vec_file": query_vec_file
        },
        "RAG_query_genetor": RAG_query_gene_log,
        "meta_search": meta_search_log,
        "knowledge_rag":{
            "setting": agent.agent["KNOWLEDGE"]
        },
        "prompt_template":{
            "setting": prompt_temp_cd
        },
        "text": prompt
    }
    session.save_history(str(seq), "prompt", prompt_chat_dict, "SUB_SEQ", str(sub_seq))

    # ログデータの保存(image)
    timestamp_log += "[33.ログ(image)の保存開始]"+str(datetime.now())+"<br>"
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
    
    # ログデータの保存(response)
    timestamp_log += "[34.ログ(response)の保存開始]"+str(datetime.now())+"<br>"
    
    # メモリ類似度を評価する場合
    response_vec_file = ""
    if memory_similarity:
        response_vec_file = session.save_vec_file(str(seq), str(sub_seq), "response", response_vec)
    
    response_chat_dict = {
        "role": "assistant",
        "timestamp": timestamp_end,
        "token": response_tokens,
        "text": response,
        "vec_file": response_vec_file,
        "reference": {
            "memory": memory_ref,
            "knowledge_rag": knowledge_ref
        }
    }
    session.save_history(str(seq), "response", response_chat_dict, "SUB_SEQ", str(sub_seq))

    # メモリダイジェストの作成
    if save_digest:
        timestamp_log += "[41.メモリダイジェストの作成開始]"+str(datetime.now())+"<br>"
        session.set_history()
        digest_memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
#        digest_memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_digest, seq_limit, sub_seq_limit)

        if "DIALOG_DIGEST" in support_agent:
            dialog_digest_agent_file = support_agent["DIALOG_DIGEST"]
            _, _, digest_response, digest_model_name, digest_prompt_tokens, digest_response_tokens = dmt.dialog_digest(service_info, user_info, "", digest_memories_selected, dialog_digest_agent_file)
        else:
            dialog_digest_agent_file = "Default"
            _, _, digest_response, digest_model_name, digest_prompt_tokens, digest_response_tokens = dmt.dialog_digest(service_info, user_info, "", digest_memories_selected)

        timestamp_digest = str(datetime.now())
        
        # メモリ類似度を評価する場合
        digest_vec_file = ""
        if memory_similarity:
            digest_vec = dmu.embed_text(digest_response.replace("\n", ""))
            digest_vec_file = session.save_vec_file(str(seq), str(sub_seq), "digest", digest_vec)
        
        # ログデータの保存(digest)
        digest_chat_dict = {
            "agent_file": dialog_digest_agent_file,
            "model": digest_model_name,
            "role": "assistant",
            "timestamp": timestamp_digest,
            "token": digest_response_tokens,
            "text": digest_response,
            "vec_file": digest_vec_file
        }
        session.save_history(str(seq), "digest", digest_chat_dict, "SUB_SEQ", str(sub_seq))

    # ログデータの保存(log)
    timestamp_log += "[完了]"+str(datetime.now())+"<br>"
    log_dict = {
        "timestamp_log": timestamp_log
    }
    session.save_history(str(seq), "log", log_dict, "SUB_SEQ", str(sub_seq))
    
    yield response_service_info, user_info, "", export_files


# プラクティスで実行
def DigiMatsuExecute_Practice(service_info, user_info, session_id, session_name, in_agent_file, user_query, in_contents=[], in_situation={}, in_overwrite_items={}, in_execution={}):

    # 実行設定の取得
    last_only = in_execution.get("LAST_ONLY", False) #APIで基本的に使用
    memory_use = in_execution.get("MEMORY_USE", True)
    memory_similarity = in_execution.get("MEMORY_SIMILARITY", False)
    magic_word_use = in_execution.get("MAGIC_WORD_USE", True)
    stream_mode = in_execution.get("STREAM_MODE", True)
    save_digest = in_execution.get("SAVE_DIGEST", True)
    meta_search = in_execution.get("META_SEARCH", True)
    RAG_query_gene = in_execution.get("RAG_QUERY_GENE", True)
    
    # セッションの設定
    session = dms.DigiMSession(session_id, session_name)
    sub_seq = 1
    results = []
    response_service_info = service_info
    response_user_info = user_info

    # セッションのロック
    if session.get_status() == "LOCKED":
        raise Exception("Session is locked. Please unlock the session before executing the practice.")
    else:
        session.save_status("LOCKED")
    
    try:
        # プラクティスの選択
        agent = dma.DigiM_Agent(in_agent_file)
        
        habit = "DEFAULT"
        if magic_word_use:
            agent = dma.DigiM_Agent(in_agent_file)
            habit = agent.set_practice_by_command(user_query)

        practice_file = agent.habit[habit]["PRACTICE"]
        habit_add_knowledge = agent.habit[habit]["ADD_KNOWLEDGE"] if "ADD_KNOWLEDGE" in agent.habit[habit] else []
        practice = dmu.read_json_file(practice_folder_path+practice_file)
        
        # プラクティス(チェイン)の実行
        chains = practice["CHAINS"]
        last_idx = len(chains) - 1
        for i, chain in enumerate(chains): #for chain in practice["CHAINS"]:
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
                add_knowledge = []
                for add_knowledge_data in setting["ADD_KNOWLEDGE"]:
                    if "USER" in setting["ADD_KNOWLEDGE"]: #"USER"が含まれていたら、呼び出し元エージェントの追加知識DBを参照
                        add_knowledge.extend(habit_add_knowledge)
                    else:
                        add_knowledge.append(add_knowledge_data)
                prompt_temp_cd = setting["PROMPT_TEMPLATE"]
                
                # "USER":ユーザー入力(引数)、"INPUT{SubSeqNo}":サブSEQの入力結果、OUTPUT{SubSeqNo}":サブSEQの出力結果
                user_input = ""
                if setting["USER_INPUT"] == "USER":
                    user_input = user_query
                elif setting["USER_INPUT"].startswith("INPUT"):
                    ref_subseq = int(setting["USER_INPUT"].replace("INPUT_", "").strip())
                    user_input = next((item["INPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
                elif setting["USER_INPUT"].startswith("OUTPUT"):
                    ref_subseq = int(setting["USER_INPUT"].replace("OUTPUT_", "").strip())
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
                
        #        seq_limit = chain["PreSEQ"] #メモリ参照範囲のSeq
        #        sub_seq_limit = chain["PreSubSEQ"] #メモリ参照範囲のsubSeq

                # 実行の設定
                execution = {}
                execution["MEMORY_USE"] = memory_use and setting["MEMORY_USE"]
                execution["MEMORY_SIMILARITY"] = memory_similarity
                execution["MAGIC_WORD_USE"] = magic_word_use
                execution["STREAM_MODE"] = stream_mode
                execution["SAVE_DIGEST"] = save_digest
                execution["META_SEARCH"] = meta_search
                execution["RAG_QUERY_GENE"] = RAG_query_gene

                # LLM実行
                response = ""
                for response_service_info, response_user_info, response_chunk, export_contents in DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type, sub_seq, user_input, import_contents, situation, overwrite_items, add_knowledge, prompt_temp_cd, execution): #, seq_limit, sub_seq_limit)
                    response += response_chunk
                    if not last_only:
                        yield response_service_info, response_user_info, response_chunk
                    elif last_only and i==last_idx:
                        yield response_service_info, response_user_info, response_chunk
                    
                input = user_input
                output = response

            elif model_type =="TOOL":           
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
#                response_service_info, response_user_info, output, export_contents = dmt.call_function_by_name(service_info, user_info, setting["FUNC_NAME"], session_id, input)
                tool_result = dmt.call_function_by_name(service_info, user_info, setting["FUNC_NAME"], session_id, input)
                output = ""
                export_contents = []
                if inspect.isgenerator(tool_result):
                    for resp_svc, resp_usr, chunk, exp in tool_result:
                        output += str(chunk) if chunk else ""
                        if exp is not None:
                            export_contents = exp
                        if not last_only:
                            yield resp_svc, resp_usr, chunk
                        elif last_only and i == last_idx:
                            yield resp_svc, resp_usr, chunk
                    response_service_info = resp_svc
                    response_user_info = resp_usr
                else:
                    response_service_info, response_user_info, output, export_contents = tool_result
                    if not last_only:
                        yield response_service_info, response_user_info, output
                    elif last_only and i == last_idx:
                        yield response_service_info, response_user_info, output
                timestamp_end = str(datetime.now())
                
                # ログデータの保存
                setting_chat_dict = {
                    "response_service_info": response_service_info,
                    "response_user_info": response_user_info, 
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
                        "token": 0,
                        "input": input,
                        "text": input,
                        "contents": import_contents,
                        "situation": {}
                    }
                }
                session.save_history(str(seq), "prompt", prompt_chat_dict, "SUB_SEQ", str(sub_seq))
            
                response_chat_dict = {
                    "role": "assistant",
                    "timestamp": timestamp_end,
                    "token": 0,
                    "text": output,
                    "export_contents": export_contents
                }
                session.save_history(str(seq), "response", response_chat_dict, "SUB_SEQ", str(sub_seq))
                if not last_only:
                    yield response_service_info, response_user_info, output
                elif last_only and i==last_idx:
                    yield response_service_info, response_user_info, output
            
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
        session.save_history(str(seq), "service_info", response_service_info, "SEQ")
        session.save_history(str(seq), "user_info", response_user_info, "SEQ")
        session.save_history(str(seq), "practice", practice, "SEQ")

    except Exception as e:
        session.save_status("UNLOCKED")
        print(f"Error during practice execution: {e}")
        raise e
    
    finally:
        session.save_status("UNLOCKED")