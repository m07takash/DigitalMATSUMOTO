import os
from dotenv import load_dotenv
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


# セッションの会話履歴の削除
def forget_history(service_info, user_info, session_id, input):
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
def remember_history(service_info, user_info, session_id, input):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "Y")
        
    response = "会話履歴を全て思い出しました"
    export_contents = []
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, export_contents


# エージェントのシンプルな実行
def genLLMAgentSimple(service_info, user_info, session_id, session_name, agent_file, model_type="LLM", sub_seq=1, query="", import_contents=[], situation={}, overwrite_items={}, add_knowledge=[], prompt_temp_cd="No Template", execution={}, seq_limit="", sub_seq_limit=""):
    agent = dma.DigiM_Agent(agent_file)
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]

    # 実行の設定
    execution = {}
    execution["CONTENTS_SAVE"] = False
    execution["MEMORY_SAVE"] = False
    execution["STREAM_MODE"] = False
    execution["SAVE_DIGEST"] = False

    # LLM実行
    response = ""
    for response_service_info, response_user_info, response_chunk, export_contents, knowledge_ref in dme.DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type, sub_seq, query, import_contents, situation=situation, overwrite_items=overwrite_items, add_knowledge=add_knowledge, prompt_temp_cd=prompt_temp_cd, execution=execution, seq_limit=seq_limit, sub_seq_limit=sub_seq_limit):
        response += response_chunk
    
    return response_service_info, response_user_info, response, model_name, 0, 0


# 通常LLMの実行
def generate_pureLLM(service_info, user_info, agent_file, query, memories_selected=[], prompt_temp_cd="No Template"):
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    
    # 通常LLMに設定
    dma.set_normal_agent(agent)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # プロンプトの設定
    prompt = f'{prompt_template}{query}'

    # LLMの実行
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected):
        if response_chunk:
            response += response_chunk
    
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    
    response_service_info = service_info
    response_user_info = user_info
    
    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens


# 会話のダイジェスト生成
def dialog_digest(service_info, user_info, user_query, memories_selected=[], agent_file="agent_51DialogDigest.json"):
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


# テキストから日付の抽出
def extract_date(service_info, user_info, user_query, situation_prompt, query_vecs, memories_selected=[], agent_file="agent_55ExtractDate.json"):
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
        prompt_temp_cd = "Extract Date"
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


# テキストからRAGクエリの生成
def RAG_query_generator(service_info, user_info, user_query, situation_prompt, query_vecs, memories_selected=[], agent_file="agent_56RAGQueryGenerator.json"):
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


# WEB検索(PerplexityAI)
def WebSearch_PerplexityAI(service_info, user_info, session_id, input):
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
