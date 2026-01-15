import os
from datetime import datetime
from dotenv import load_dotenv

import inspect
import pytz
import DigiM_Util as dmu
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Session as dms
import DigiM_Tool as dmt

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
user_folder_path = system_setting_dict["USER_FOLDER"]
session_folder_prefix = system_setting_dict["SESSION_FOLDER_PREFIX"]
temp_folder_path = system_setting_dict["TEMP_FOLDER"]
practice_folder_path = system_setting_dict["PRACTICE_FOLDER"]

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
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
    contents_save = execution.get("CONTENTS_SAVE", True)
    memory_use = execution.get("MEMORY_USE", True)
    memory_save = execution.get("MEMORY_SAVE", True)
    memory_similarity = execution.get("MEMORY_SIMILARITY", False)
    magic_word_use = execution.get("MAGIC_WORD_USE", True)
    stream_mode = execution.get("STREAM_MODE", True)
    save_digest = execution.get("SAVE_DIGEST", True)
    meta_search = execution.get("META_SEARCH", True)
    RAG_query_gene = execution.get("RAG_QUERY_GENE", True)
    web_search = execution.get("WEB_SEARCH", False)

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
    situation_prompt = ""
    if situation:
        situation_setting = ""
        time_setting = str(datetime.now(pytz.timezone(timezone_setting)).strftime('%Y/%m/%d %H:%M:%S'))
        if "SITUATION" in situation:
            situation_setting = situation["SITUATION"]+"\n"
        if "TIME" in situation:
            time_setting = situation["TIME"]
        situation_prompt = f"\n【状況】\n{situation_setting}現在は「{time_setting}」です。"

    # 会話のダイジェストを取得
    if memory_use:
        timestamp_log += "[05.会話ダイジェスト読込開始]"+str(datetime.now())+"<br>"
        if session.chat_history_active_dict:
            max_seq, max_sub_seq, chat_history_max_digest_dict = session.get_history_max_digest()
            if chat_history_max_digest_dict:
                digest_text = "会話履歴のダイジェスト:\n"+chat_history_max_digest_dict["text"]+"\n---\n"

    # Web検索を実行
    timestamp_log += "[06.WEB検索を開始]"+str(datetime.now())+"<br>"
    web_context = ""
    web_search_log = {}
    if web_search:
        search_text = user_query
        if digest_text or situation_prompt:
            search_text = "検索して欲しい内容:\n"+user_query +"\n\n[参考]これまでの会話:\n"+ digest_text +"\n\n[参考]今の状況:\n"+ situation_prompt
        response_service_info, response_user_info, web_result_text, export_urls = dmt.WebSearch_PerplexityAI(service_info, user_info, session_id, session_name, agent_file, search_text, [], {})
        web_context = "[参考]関連するWEBの検索結果:\n" + web_result_text
        web_search_log["urls"] = export_urls
        web_search_log["web_context"] = web_context

    user_query += f"\n{web_context}"

    # クエリのベクトル化（RAGの検索は「0.ユーザ入力」「1.ユーザー入力＋メモリダイジェスト」の類似している方を取る）
    timestamp_log += "[07.クエリのベクトル化開始]"+str(datetime.now())+"<br>"
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
        memories_selected = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
    
    # サポートエージェントの設定
    support_agent = agent.agent["SUPPORT_AGENT"]

    # RAG検索用クエリ(意図)の生成
    timestamp_log += "[11.RAG検索用クエリ(意図)の生成]"+str(datetime.now())+"<br>"
    RAG_query_gene_log = {}
    if RAG_query_gene and "RAG_QUERY_GENERATOR" in support_agent:
        # 付属情報の設定
        add_info = {}
        add_info["Memories_Selected"] = memories_selected
        add_info["Situation"] = situation_prompt
        add_info["QueryVecs"] = [query_vec] 

        RAG_query_gene_agent_file = support_agent["RAG_QUERY_GENERATOR"]
        _, _, RAG_query_gene_response, RAG_query_gene_model_name, RAG_query_gene_prompt_tokens, RAG_query_gene_response_tokens = dmt.RAG_query_generator(service_info, user_info, session_id, session_name, RAG_query_gene_agent_file, user_query, [], add_info)
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
        # 付属情報の設定
        add_info = {}
        add_info["Memories_Selected"] = memories_selected
        add_info["Situation"] = situation_prompt
        add_info["QueryVecs"] = [query_vec] 

        # ユーザー入力から時間を取得
        extract_date_agent_file = support_agent["EXTRACT_DATE"]
        _, _, extract_date_response, extract_date_model_name, extract_date_prompt_tokens, extract_date_response_tokens = dmt.extract_date(service_info, user_info, session_id, session_name, extract_date_agent_file, user_query, [], add_info)
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
            yield response_service_info, response_user_info, response_chunk, export_files, knowledge_selected
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
    response_vec = dmu.embed_text(response.replace("\n", "")[:8000])
    memory_ref = dmc.get_memory_reference(memories_selected, memory_similarity, response_vec, memory_similarity_logic)
    knowledge_ref = dmc.get_knowledge_reference(response_vec, knowledge_selected)
    
    # 入力されたコンテンツの保存
    if contents_save:
        timestamp_log += "[24.コンテンツの保存開始]"+str(datetime.now())+"<br>"
        contents_record_to = []
        for contents_record in contents_records:
            session.save_contents_file(contents_record["from"], contents_record["to"]["file_name"])
            contents_record_to.append(contents_record["to"])

    # ログの保存
    if memory_save:

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
            "web_search": web_search_log,
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
            dialog_digest_agent_file = ""
            if "DIALOG_DIGEST" in support_agent:
                dialog_digest_agent_file = support_agent["DIALOG_DIGEST"]

            # 付属情報の設定
            add_info = {}
            session.set_history()
            add_info["Memories_Selected"] = session.get_memory(query_vec, model_name, tokenizer, memory_limit_tokens, memory_role, memory_priority, memory_similarity, memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
            _, _, digest_response, digest_model_name, digest_prompt_tokens, digest_response_tokens = dmt.dialog_digest(service_info, user_info, session_id, session_name, dialog_digest_agent_file, "", [], add_info)

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

        # ユーザーダイアログを未保存に設定
        session.save_user_dialog_session("UNSAVED")
    
    yield response_service_info, user_info, "", export_files, knowledge_ref


# プラクティスで実行
def DigiMatsuExecute_Practice(service_info, user_info, session_id, session_name, in_agent_file, user_query, in_contents=[], in_situation={}, in_overwrite_items={}, in_add_knowledge=[], in_execution={}):

    # 実行設定の取得
    last_only = in_execution.get("LAST_ONLY", False) #APIで基本的に使用
    contents_save = in_execution.get("CONTENTS_SAVE", True)
    memory_use = in_execution.get("MEMORY_USE", True)
    memory_save = in_execution.get("MEMORY_SAVE", True)
    memory_similarity = in_execution.get("MEMORY_SIMILARITY", False)
    magic_word_use = in_execution.get("MAGIC_WORD_USE", True)
    stream_mode = in_execution.get("STREAM_MODE", True)
    save_digest = in_execution.get("SAVE_DIGEST", True)
    meta_search = in_execution.get("META_SEARCH", True)
    RAG_query_gene = in_execution.get("RAG_QUERY_GENE", True)
    web_search = in_execution.get("WEB_SEARCH", False)

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
        # エージェントの選択
        agent = dma.DigiM_Agent(in_agent_file)      

        # Habitの設定
        habit = "DEFAULT"
        if magic_word_use:
            agent = dma.DigiM_Agent(in_agent_file)
            habit = agent.set_practice_by_command(user_query)

        # プラクティスの選択
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
                # プラクティスの設定から追加
                for add_knowledge_data in setting["ADD_KNOWLEDGE"]:
                    if "USER" in setting["ADD_KNOWLEDGE"]: #"USER"が含まれていたら、呼び出し元エージェントの追加知識DBを参照
                        add_knowledge.extend(habit_add_knowledge)
                    else:
                        add_knowledge.append(add_knowledge_data)
                # 入力から追加
                for add_knowledge_data in in_add_knowledge:
                    add_knowledge.append(add_knowledge_data)
                
                # プロンプトテンプレート
                prompt_temp_cd = setting["PROMPT_TEMPLATE"]
                
                # "USER":ユーザー入力(引数)、"INPUT{SubSeqNo}":サブSEQの入力結果、OUTPUT{SubSeqNo}":サブSEQの出力結果
                user_input = ""
                if isinstance(setting["USER_INPUT"], list):
                    for set_user_input in setting["USER_INPUT"]:
                        print(set_user_input)
                        ref_subseq = 0
                        if set_user_input == "USER":
                            user_input += user_query
                        elif set_user_input.startswith("INPUT"):
                            ref_subseq = int(set_user_input.replace("INPUT_", "").strip())
                            user_input += next((item["INPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
                        elif set_user_input.startswith("OUTPUT"):
                            ref_subseq += int(set_user_input.replace("OUTPUT_", "").strip())
                            user_input += next((item["OUTPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
                        else:
                            user_input += set_user_input
                else:
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
                
                # 参照するメモリの設定
                seq_limit = ""
                sub_seq_limit = ""
                if "PreSEQ" in chain and "PreSubSEQ" in chain:
                    seq_limit = chain["PreSEQ"] #メモリ参照範囲のSeq
                    sub_seq_limit = chain["PreSubSEQ"] #メモリ参照範囲のsubSeq

                # 実行の設定
                execution = {}
                execution["CONTENTS_SAVE"] = contents_save
                execution["MEMORY_USE"] = memory_use and setting.get("MEMORY_USE", True)
                execution["MEMORY_SAVE"] = memory_save
                execution["MEMORY_SIMILARITY"] = memory_similarity
                execution["MAGIC_WORD_USE"] = magic_word_use
                execution["STREAM_MODE"] = stream_mode
                execution["SAVE_DIGEST"] = save_digest
                execution["META_SEARCH"] = meta_search and setting.get("META_SEARCH", True)
                execution["RAG_QUERY_GENE"] = RAG_query_gene and setting.get("RAG_QUERY_GENE", True)
                execution["WEB_SEARCH"]  = setting.get("WEB_SEARCH", web_search) #WEB検索だけはOR条件

                # LLM実行
                response = ""
                for response_service_info, response_user_info, response_chunk, export_contents, knowledge_ref in DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type, sub_seq, user_input, import_contents, situation, overwrite_items, add_knowledge, prompt_temp_cd, execution, seq_limit, sub_seq_limit):
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

                # "USER":ユーザー入力(引数)、"INPUT{SubSeqNo}":サブSEQの入力結果、OUTPUT{SubSeqNo}":サブSEQの出力結果
#                user_input = ""
#                if "USER_INPUT" in setting:
#                    if setting["USER_INPUT"] == "USER":
#                        user_input = user_query
#                    elif setting["USER_INPUT"].startswith("INPUT"):
#                        ref_subseq = int(setting["USER_INPUT"].replace("INPUT_", "").strip())
#                        user_input = next((item["INPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
#                    elif setting["USER_INPUT"].startswith("OUTPUT"):
#                        ref_subseq = int(setting["USER_INPUT"].replace("OUTPUT_", "").strip())
#                        user_input = next((item["OUTPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
#                    else:
#                        user_input = setting["USER_INPUT"]

                # "USER":ユーザー入力(引数)、"INPUT{SubSeqNo}":サブSEQの入力結果、OUTPUT{SubSeqNo}":サブSEQの出力結果
                user_input = ""
                if "USER_INPUT" in setting:
                    if isinstance(setting["USER_INPUT"], list):
                        for set_user_input in setting["USER_INPUT"]:
                            print(set_user_input)
                            ref_subseq = 0
                            if set_user_input == "USER":
                                user_input += user_query
                            elif set_user_input.startswith("INPUT"):
                                ref_subseq = int(set_user_input.replace("INPUT_", "").strip())
                                user_input += next((item["INPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
                            elif set_user_input.startswith("OUTPUT"):
                                ref_subseq += int(set_user_input.replace("OUTPUT_", "").strip())
                                user_input += next((item["OUTPUT"] for item in results if item["SubSEQ"] == ref_subseq), None)
                            else:
                                user_input += set_user_input
                    else:
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
                input = user_input

                # コンテンツの設定
                import_contents = []
                if "CONTENTS" in setting:
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
                
                # エージェントファイルの設定
                agent_file = ""
                if "AGENT_FILE" in setting:
                    agent_file = setting["AGENT_FILE"] if setting["AGENT_FILE"] != "USER" else in_agent_file

                # 付随情報の設定
                add_info={}
                if "ADD_INFO" in setting:
                    add_info = setting["ADD_INFO"]

                timestamp_begin = str(datetime.now())
                tool_result = dmt.call_function_by_name(service_info, user_info, setting["FUNC_NAME"], session_id, session_name, agent_file, input, import_contents, add_info)

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
                    "role": "neither",
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
                    "role": "neither",
                    "timestamp": timestamp_end,
                    "token": 0,
                    "text": output,
                    "export_contents": export_contents
                }
                session.save_history(str(seq), "response", response_chat_dict, "SUB_SEQ", str(sub_seq))

#                if not last_only:
#                    yield response_service_info, response_user_info, output
#                elif last_only and i==last_idx:
#                    yield response_service_info, response_user_info, output
            
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
        session.save_history(str(seq), "service_info", service_info, "SEQ")
        session.save_history(str(seq), "user_info", user_info, "SEQ")
        session.save_history(str(seq), "practice", practice, "SEQ")

        # セッションステータス(status.yaml)の更新
        session.save_session_id()
        session.save_session_name()
        session.save_service_id(service_info["SERVICE_ID"])
        session.save_user_id(user_info["USER_ID"])
        session.save_agent_file(in_agent_file)
        session.save_last_update_date(str(datetime.now()))
        session.save_active_session("Y")

    except Exception as e:
        session.save_status("UNLOCKED")
        print(f"Error during practice execution: {e}")
        raise e
    
    finally:
        session.save_status("UNLOCKED")