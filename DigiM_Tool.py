import os
from dotenv import load_dotenv
import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Context as dmc

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
charactor_folder_path = os.getenv("CHARACTOR_FOLDER")
agent_folder_path = os.getenv("AGENT_FOLDER")
mst_folder_path = os.getenv("MST_FOLDER")
openai_api_key = os.getenv("OPENAI_API_KEY")

# 文字列から関数名を取得
def call_function_by_name(func_name, *args, **kwargs):
    if func_name in globals():
        func = globals()[func_name]
        return func(*args, **kwargs)  # 引数を関数に渡す
    else:
        return "Function not found"

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
    response, completion, prompt_tokens, response_tokens = agent.generate_response(prompt)

    # 出力形式
    response = "【これまでの会話のダイジェスト】\n" + response
    
    return response, prompt_tokens, response_tokens


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
    response, completion, prompt_tokens, response_tokens = agent.generate_response(prompt, memories_selected, image_paths)
    
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
    response, completion, prompt_tokens, response_tokens = agent.generate_response(prompt, memories_selected)
    
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
    response, completion, prompt_tokens, response_tokens = agent.generate_response(prompt, memories_selected)
    
    return response, prompt_tokens, response_tokens

# 画像生成
def generate_image_dalle(prompt, model, file_header="temp"):
    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key
    openai_client = OpenAI()
    
    # 画像生成モデルの実行
    completion = openai_client.images.generate(
        model=model["MODEL"],
        prompt=prompt,
        n=model["PARAMETER"]["n"],  #イメージ枚数
        size=model["PARAMETER"]["size"],
        response_format=model["PARAMETER"]["response_format"],  # レスポンスフォーマット url or b64_json
        quality=model["PARAMETER"]["quality"],  # 品質 standard or hd
        style=model["PARAMETER"]["style"]  # スタイル vivid or natural
    )

    # TEMPフォルダに保存
    img_files = []
    num = 0
    for i, d in enumerate(completion.data):
        img_file = temp_folder_path + f"{file_header}_dalle{num}.jpg"
        with open(img_file, "wb") as f:
            f.write(base64.b64decode(d.b64_json))
        img_files.append(img_file)
        num = num + 1
    
    return img_files
