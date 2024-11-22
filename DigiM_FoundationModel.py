import os
import json
import base64
from dotenv import load_dotenv

import openai
from openai import OpenAI
import google.generativeai as genai

import DigiM_Util as dmu
import DigiM_Tool as dmt

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
temp_folder_path = os.getenv("TEMP_FOLDER")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")

# 文字列から関数名を取得
def call_function_by_name(func_name, *args, **kwargs):
    if func_name in globals():
        func = globals()[func_name]
        return func(*args, **kwargs)  # 引数を関数に渡す
    else:
        return "Function not found"

# GPTの実行
def generate_response_T_gpt(prompt, system_prompt, model, memories=[], image_paths=[], agent_tools={}):
    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key
    openai_client = OpenAI()

    # システムプロンプトの設定
    system_message = [
        {"role": "system", "content": system_prompt}
    ]

    # メモリをプロンプトに設定
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})
    
    # イメージ画像をプロンプトに設定
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        #image_message.append({"type": "image_url", "image_url": {"url": image_url["image_url"]}})
        image_message.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}})
    
    # ユーザーのプロンプトを設定
    user_prompt = [{"type": "text", "text": prompt}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]    

    # ツールを設定【要検討：いったんデフォルト設定】
    tools = agent_tools["TOOL_LIST"]
    tool_choice = agent_tools["CHOICE"]
    
    # モデルの実行
    completion = openai_client.chat.completions.create(
        model = model["MODEL"],
        temperature = model["PARAMETER"]["temperature"],
        messages = system_message + memory_message + user_message,
        tools = tools,
        tool_choice = tool_choice
    )

    #レスポンスから出力を抽出
    response = completion.choices[0].message.content
    prompt_tokens = completion.usage.prompt_tokens
    response_tokens = completion.usage.completion_tokens

    return response, completion, prompt_tokens, response_tokens


# Geminiの実行【GPTを参考に修正】
def generate_response_T_gemini(api_key, persona, model, parameter, prompt, image_urls, memory_docs):   
    genai.configure(api_key=api_key)
    
    #モデルの実行
    gemini = genai.GenerativeModel(model)
    completion = gemini.generate_content(
        prompt,
        generation_config={"temperature": parameter["temperature"]}
    )
    response = completion.text
    prompt_tokens = gemini.count_tokens(prompt).total_tokens
    response_tokens = gemini.count_tokens(response).total_tokens
    return response, completion, prompt_tokens, response_tokens


# 考察に対する画像生成
def generate_image_dalle(prompt, system_prompt, model, memories=[], image_paths=[], agent_tools={}):
    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key
    openai_client = OpenAI()

    # システムプロンプトの設定
    system_message = [{"role": "system", "content": system_prompt}]

    # ユーザーのプロンプトを設定
    user_message = [{"role": "user", "content": prompt}]

    # メモリをプロンプトに設定
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})
        
    # プロンプトを文字列に 
    prompt_str = json.dumps(system_message + memory_message + user_message, ensure_ascii=False)
    
    # 画像生成モデルの実行
    completion = openai_client.images.generate(
        model=model["MODEL"],
        prompt=prompt_str,
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
        img_file = temp_folder_path + f"{str(len(memories))}_dalle{num}.jpg"
        with open(img_file, "wb") as f:
            f.write(base64.b64decode(d.b64_json))
        img_files.append(img_file)
        num = num + 1

    completion = img_files

    # 画像のコンテキスト取得
    agent_data = dmu.read_json_file(model["CONTEXT_AGENT_FILE"])
    response, prompt_tokens, response_tokens = dmt.art_critics(agent_data, image_paths=[img_file])

    return response, completion, prompt_tokens, response_tokens