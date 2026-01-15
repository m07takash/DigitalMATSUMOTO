import os
from dotenv import load_dotenv
import re
import time
import pandas as pd
import requests
import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Session as dms
import DigiM_Execute as dme

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]
character_folder_path = system_setting_dict["CHARACTER_FOLDER"]
practice_folder_path = system_setting_dict["PRACTICE_FOLDER"]

# 文字列から関数名を取得
def call_function_by_name(service_info, user_info, func_name, *args, **kwargs):
    if func_name in globals():
        func = globals()[func_name]
        return func(service_info, user_info, *args, **kwargs)  # 引数を関数に渡す
    else:
        return "Function not found"


# 固定メッセージの回答
def fixed_message(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    response = input
    export_contents = []

    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, export_contents


# セッションの会話履歴の削除
def forget_history(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "N")
        
    response = "会話履歴を全て忘れました"
    export_contents = []

    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, export_contents


# セッションの会話履歴の回復
def remember_history(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "Y")
        
    response = "会話履歴を全て思い出しました"
    export_contents = []
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, export_contents


# テキストから日付の抽出
def extract_date(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_55ExtractDate.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    memories_selected = []
    if "Memories_Selected" in add_info:
        memories_selected = add_info["Memories_Selected"]
    if "Situation" in add_info:
        situation_prompt = add_info["Situation"]
    if "QueryVecs" in add_info:
        query_vecs = add_info["QueryVecs"]

    # エージェントファイルのDEFAULTに設定しているPRACTICEの1つ目からプロンプトテンプレートを取得する
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(practice_folder_path+practice_file)
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Extract Date"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # RAG実行
    user_query = input
    knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs)

    # プロンプトの設定
    prompt = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'

    # LLMの実行
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, stream_mode=False):
        if response_chunk:
            response += response_chunk
    
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens


# テキストからRAGクエリの生成
def RAG_query_generator(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_56RAGQueryGenerator.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    memories_selected = []
    if "Memories_Selected" in add_info:
        memories_selected = add_info["Memories_Selected"]
    if "Situation" in add_info:
        situation_prompt = add_info["Situation"]
    if "QueryVecs" in add_info:
        query_vecs = add_info["QueryVecs"]

    # エージェントファイルのDEFAULTに設定しているPRACTICEの1つ目からプロンプトテンプレートを取得する
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(practice_folder_path+practice_file)
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "RAG Query Generator"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # RAG実行
    knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs)

    # プロンプトの設定
    prompt = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'

    # LLMの実行
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, stream_mode=False):
        if response_chunk:
            response += response_chunk
    
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens


# 会話のダイジェスト生成
def dialog_digest(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_51DialogDigest.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    memories_selected = []
    if "Memories_Selected" in add_info:
        memories_selected = add_info["Memories_Selected"]

    # エージェントファイルのDEFAULTに設定しているPRACTICEの1つ目からプロンプトテンプレートを取得する
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(practice_folder_path+practice_file)
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Dialog Digest"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # メモリをテキスト化
    digest_memories_selected = [{"role": item["role"], "content": item["text"]} for item in memories_selected]
    digest_memories_text = str(digest_memories_selected)[1:-1]

    # プロンプトの設定
    query = f'{prompt_template}{user_query}\n{digest_memories_text}'

    # LLMの実行
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk
    
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    
    # 出力形式
    response = "【これまでの会話のダイジェスト】\n" + response
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens


# セッション名の生成
def gene_session_name(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_57SessionName.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    memories_selected = []
    if "Memories_Selected" in add_info:
        memories_selected = add_info["Memories_Selected"]

    # エージェントファイルのDEFAULTに設定しているPRACTICEの1つ目からプロンプトテンプレートを取得する
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(practice_folder_path+practice_file)
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Session Name"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # メモリをテキスト化
    digest_memories_selected = [{"role": item["role"], "content": item["text"]} for item in memories_selected]
    digest_memories_text = str(digest_memories_selected)[1:-1]

    # プロンプトの設定
    query = f'{prompt_template}\n{digest_memories_text}\n{user_query}'

    # LLMの実行
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk
    
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens


# ユーザーダイアログの生成(会話履歴の中におけるユーザーの特徴や意見)
def gene_user_dialog(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_58UserDialog.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    memory_limit_tokens = agent.agent["ENGINE"][model_type]["MEMORY"]["limit"]
    memory_role = agent.agent["ENGINE"][model_type]["MEMORY"]["role"]

    session = dms.DigiMSession(session_id, session_name)
    memories_selected = session.get_memory([], model_name, tokenizer, memory_limit_tokens, memory_role)

    # エージェントファイルのDEFAULTに設定しているPRACTICEの1つ目からプロンプトテンプレートを取得する
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(practice_folder_path+practice_file)
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "User Dialog"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # メモリをテキスト化
    user_dialogs_selected = [{"role": item["role"], "content": item["text"]} for item in memories_selected if item.get("sub_seq") == "1"]
    user_dialogs_text = str(user_dialogs_selected)[1:-1]

    # プロンプトの設定
    query = f'{prompt_template}\n{user_dialogs_text}'

    # LLMの実行
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk
    
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens


# WEB検索(PerplexityAI)
def WebSearch_PerplexityAI(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    if os.path.exists("system.env"):
        load_dotenv("system.env")
    api_key = os.getenv("PERPLEXITY_API_KEY")

    system_setting_dict = dmu.read_yaml_file("setting.yaml")
    url = system_setting_dict["PERPLEXITY_URL"]
    model = system_setting_dict["PERPLEXITY_MODEL"]
    system_prompt = system_setting_dict["PERPLEXITY_SYSTEM_PROMPT"]
    user_prompt = system_setting_dict["PERPLEXITY_USER_PROMPT"]
    max_tokens = system_setting_dict["PERPLEXITY_MAX_TOKENS"]
    reasoning_effort = system_setting_dict["PERPLEXITY_REASONING_EFFORT"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt +"\n"+ input,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort
            }
        ]
    }

    response_service_info = service_info
    response_user_info = user_info

    results = requests.post(url, json=payload, headers=headers)

    response = results.json()["choices"][0]["message"]["content"]
    export_contents = results.json()["search_results"]

    return response_service_info, response_user_info, response, export_contents


# 経営分析
def management_analysis(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    try:
        client_name = re.search(r"Client:(.+)", input).group(1).strip()
        biz_name = re.search(r"Biz:(.+)", input).group(1).strip()
        query = ""
        remaining_lines = []
        for line in input.splitlines():
            if not line.startswith("Client:") and not line.startswith("Biz:"):
                remaining_lines.append(line)
        if remaining_lines:
            query = "\n".join(remaining_lines).strip()
    except AttributeError:
        rule_text = "入力に以下を含めてください。\nClient:「会社名」\nBiz:「事業名」"
        return service_info, user_info, rule_text, []

    test_folder_path = "test/"
    test_file = "Tool_MgrAnalysis.xlsx"
    test_sheet_name = "Test"
    raw_name_Q = "Q"

    #実行設定
    situation = {}
    overwrite_items = {}
    add_knowledges = []
    execution = {}
    execution["MEMORY_USE"] = True
    execution["MEMORY_SIMILARITY"] = False
    execution["MAGIC_WORD_USE"] = False
    execution["STREAM_MODE"] = False
    execution["SAVE_DIGEST"] = True
    execution["META_SEARCH"] = True
    execution["RAG_QUERY_GENE"] = True

    #一度セッションをアンロック
    session = dms.DigiMSession(session_id, session_name)
    session.save_status("UNLOCKED")

    # テストファイルを読み込んでループ
    test_file_path = test_folder_path + test_file
    test_sheet = pd.read_excel(test_file_path, sheet_name=test_sheet_name)
    Q_no = 0
    for index, row in test_sheet.iterrows():
        questionaire = str(row[raw_name_Q]).replace("{client}", client_name).replace("{biz}", biz_name)
        user_input = query + questionaire

        web_flg = str(row["WEB"])
        if web_flg == "Y":
            execution["WEB_SEARCH"] = True
        else:
            execution["WEB_SEARCH"] = False

        response = ""
        for response_service_info, response_user_info, response_chunk, output_reference in dme.DigiMatsuExecute_Practice(service_info, user_info, session_id, session_name, agent_file, user_input, import_contents, situation, overwrite_items, add_knowledges, execution):
            response += response_chunk
        
        Q_no += 1         
        time.sleep(3)
    
    export_contents = []

    return response_service_info, response_user_info, response, export_contents


# テキストの比較
def compare_texts(service_info, user_info, head1, text1, head2, text2, query_compare=""):
    agent_file = "agent_53CompareTexts.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    
    # エージェントに設定されるプロンプトテンプレートを設定
    if query_compare == "":
        prompt_temp_cd = "Compare Texts"
        prompt_template = agent.set_prompt_template(prompt_temp_cd)
    else:
        prompt_template = query_compare

    # プロンプトの設定
    prompt = f'{prompt_template}\n\n[{head1}]\n{text1}\n\n[{head2}]\n{text2}'

    # LLMの実行
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt):
        if response_chunk:
            response += response_chunk
    
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens

    
# 画像データへの批評の生成
def art_critics(service_info, user_info, memories_selected=[], image_paths=[], agent_file="agent_52ArtCritic.json"):
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    
    # エージェントファイルのDEFAULTに設定しているPRACTICEの1つ目からプロンプトテンプレートを取得する
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(practice_folder_path+practice_file)
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Art Critic"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)
    
    # プロンプトの設定
    prompt = f'{prompt_template}'

    # LLMの実行
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, image_paths):
        if response_chunk:
            response += response_chunk
    
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens
