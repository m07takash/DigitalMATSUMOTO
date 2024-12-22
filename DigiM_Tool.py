import os
from dotenv import load_dotenv
import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Context as dmc
import DigiM_Session as dms

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
charactor_folder_path = os.getenv("CHARACTOR_FOLDER")
agent_folder_path = os.getenv("AGENT_FOLDER")
mst_folder_path = os.getenv("MST_FOLDER")

# 文字列から関数名を取得
def call_function_by_name(func_name, *args, **kwargs):
    if func_name in globals():
        func = globals()[func_name]
        return func(*args, **kwargs)  # 引数を関数に渡す
    else:
        return "Function not found"


# セッションの会話履歴の削除
def forget_history(session_id):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "N")
        
    response = "会話履歴を全て忘れました"
    export_contents = []
    return response, export_contents


# セッションの会話履歴の回復
def remember_history(session_id):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "Y")
        
    response = "会話履歴を全て思い出しました"
    export_contents = []
    return response, export_contents


# 会話のダイジェスト生成
def dialog_digest(query, memories_selected={}):
    agent_file = agent_folder_path+"agent_51DialogDigest.json"
    agent = dma.DigiM_Agent(agent_file)

    # 通常LLMに設定
    # dma.set_normal_agent(agent)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_temp_cd = "Dialog Digest"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # メモリをテキスト化
    digest_memories_selected = [{"role": item["role"], "content": item["text"]} for item in memories_selected]
    digest_memories_text = str(digest_memories_selected)[1:-1]

    # プロンプトの設定
    prompt = f'{prompt_template}{query}\n{digest_memories_text}'

    # LLMの実行
    response, completion, prompt_tokens, response_tokens = agent.generate_response("LLM", prompt)

    # 出力形式
    response = "【これまでの会話のダイジェスト】\n" + response
    
    return response, prompt_tokens, response_tokens


# 通常LLMの実行
def generate_pureLLM(agent_file, query, memories_selected={}):
    agent_file = agent_folder_path + agent_file
    agent = dma.DigiM_Agent(agent_file)

    # 通常LLMに設定
    dma.set_normal_agent(agent)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_temp_cd = "Insight Template Pure"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # プロンプトの設定
    prompt = f'{prompt_template}{query}'

    # LLMの実行
    response, completion, prompt_tokens, response_tokens = agent.generate_response("LLM", prompt, memories_selected)
    
    return response, prompt_tokens, response_tokens


# テキストの比較
def compare_texts(head1, text1, head2, text2):
    agent_file = agent_folder_path + "agent_53CompareTexts.json"
    agent = dma.DigiM_Agent(agent_file)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_temp_cd = "Compare Texts"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # プロンプトの設定
    prompt = f'{prompt_template}\n\n[{head1}]\n{text1}\n\n[{head2}]\n{text2}'

    # LLMの実行
    response, completion, prompt_tokens, response_tokens = agent.generate_response("LLM", prompt)
    
    return response, prompt_tokens, response_tokens

################################################################

# 画像データへの批評の生成
def art_critics(memories_selected={}, image_paths=[]):
    agent_file = agent_folder_path+"agent_52ArtCritic.json"
    agent = dma.DigiM_Agent(agent_file)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_temp_cd = "Art Critic"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)
    
    # プロンプトの設定
    prompt = f'{prompt_template}'

    # LLMの実行
    response, completion, prompt_tokens, response_tokens = agent.generate_response("LLM", prompt, memories_selected, image_paths)
    
    return response, prompt_tokens, response_tokens


# エシカルチェック
def ethical_check(query, memories_selected={}):
    agent_file = agent_folder_path+"agent_11EthicalCheck.json"
    agent = dma.DigiM_Agent(agent_file)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_temp_cd = "Ethical Check"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)
    
    # プロンプトの設定
    prompt = f'{prompt_template}{query}'

    # LLMの実行
    response, completion, prompt_tokens, response_tokens = agent.generate_response("LLM", prompt, memories_selected)
    
    return response, prompt_tokens, response_tokens


# 川柳の作成
def senryu_sensei(query, memories_selected={},):
    agent_file = agent_folder_path+"agent_12SenryuSensei.json"
    agent = dma.DigiM_Agent(agent_file)

    # RAGコンテキストを取得
    knowledge_context, knowledge_selected, query_vec = agent.set_knowledge_context(query)
    
    # エージェントに設定されるプロンプトテンプレートを設定
    prompt_temp_cd = "Senryu Template"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)
    
    # プロンプトの設定
    prompt = f'{knowledge_context}{prompt_template}{query}'
    
    # LLMの実行
    response, completion, prompt_tokens, response_tokens = agent.generate_response("LLM", prompt, memories_selected)
    
    return response, prompt_tokens, response_tokens
