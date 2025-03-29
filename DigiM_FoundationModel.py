import os
import json
import base64
import PIL.Image
from dotenv import load_dotenv

import openai
from openai import OpenAI
from google import genai
from google.genai import types
from llamaapi import LlamaAPI

import DigiM_Util as dmu
import DigiM_Tool as dmt

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
temp_folder_path = os.getenv("TEMP_FOLDER")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
llama_api_key = os.getenv("LLAMA_API_KEY")

# 文字列から関数名を取得
def call_function_by_name(func_name, *args, **kwargs):
    if func_name in globals():
        func = globals()[func_name]
        return func(*args, **kwargs)  # 引数を関数に渡す
    else:
        return "Function not found"

# GPTの実行
def generate_response_T_gpt(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
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
    user_prompt = [{"type": "text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = system_message + memory_message + user_message

    # ツールを設定【要検討：いったんデフォルト設定】
    tools = agent_tools["TOOL_LIST"]
    tool_choice = agent_tools["CHOICE"]
    
    # モデルの実行
    completion = openai_client.chat.completions.create(
        model = model["MODEL"],
        temperature = model["PARAMETER"]["temperature"],
        messages = prompt,
        tools = tools,
        tool_choice = tool_choice,
        stream = stream_mode
    )

    if stream_mode:
        for chunk_completion in completion:
            if chunk_completion.choices:
                response = chunk_completion.choices[0].delta.content
                yield str(prompt), response, chunk_completion
    else:
        response = completion.choices[0].message.content
        yield str(prompt), response, completion

#    #レスポンスから出力を抽出
#    response = completion.choices[0].message.content
#    prompt_tokens = dmu.count_token(model["TOKENIZER"], model["MODEL"], str(prompt)) #completion.usage.prompt_tokens
#    response_tokens = dmu.count_token(model["TOKENIZER"], model["MODEL"], response) #completion.usage.completion_tokens

#    return response, completion, prompt_tokens, response_tokens


# oシリーズの実行
def generate_response_T_o(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key
    openai_client = OpenAI()

    # システムプロンプトの設定
    system_message = [
        {"role": "developer", 
         "content": [{"type": "text", "text": system_prompt}]}
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
    user_prompt = [{"type": "text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = system_message + memory_message + user_message

    # ツールを設定【要検討：いったんデフォルト設定】
    tools = agent_tools["TOOL_LIST"]
    tool_choice = agent_tools["CHOICE"]
    
    # モデルの実行
    completion = openai_client.chat.completions.create(
        model = model["MODEL"],
        messages = prompt,
        reasoning_effort = model["PARAMETER"]["reasoning_effort"]
    )

    response = completion.choices[0].message.content
    yield str(prompt), response, completion

#    #レスポンスから出力を抽出
#    response = completion.choices[0].message.content
#    prompt_tokens = dmu.count_token(model["TOKENIZER"], model["MODEL"], str(prompt)) #completion.usage.prompt_tokens
#    response_tokens = dmu.count_token(model["TOKENIZER"], model["MODEL"], response) #completion.usage.completion_tokens

#    return response, completion, prompt_tokens, response_tokens
        

# OpenAIツールの実行(https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses)
def generate_response_openai_tool(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key
    openai_client = OpenAI()

    # システムプロンプトの設定
    system_message = [
        {"role": "developer", 
         "content": [{"type": "input_text", "text": system_prompt}]}
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
    user_prompt = [{"type": "input_text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = system_message + memory_message + user_message

    # ツールを設定【要検討：いったんデフォルト設定】
    tools = agent_tools["TOOL_LIST"]
    tool_choice = agent_tools["CHOICE"]
    
    # モデルの実行
    completion = openai_client.responses.create(
        model = model["MODEL"],
        tools = tools,
        input = prompt
    )

    response = completion.output_text
    yield str(prompt), response, completion

#    #レスポンスから出力を抽出
#    response = completion.choices[0].message.content
#    prompt_tokens = dmu.count_token(model["TOKENIZER"], model["MODEL"], str(prompt)) #completion.usage.prompt_tokens
#    response_tokens = dmu.count_token(model["TOKENIZER"], model["MODEL"], response) #completion.usage.completion_tokens

#    return response, completion, prompt_tokens, response_tokens


# Geminiの実行(https://github.com/google-gemini/cookbook/blob/main/gemini-2/get_started.ipynb)
def generate_response_T_gemini(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    gemini_client = genai.Client(api_key=gemini_api_key)

    # メモリをプロンプトに設定
    memory_message = []
    for memory in memories:
        memory_message.append(types.Content(role=memory["role"], parts=[types.Part.from_text(memory["text"])]))
    
    # イメージ画像をプロンプトに設定
    image = []
    for image_path in image_paths:
        image.append(PIL.Image.open(image_path))
    
    # ユーザーのプロンプトを設定
    user_prompt = query
    if image:
        user_prompt = [query] + image

    # ツールを設定【修正前】
###    tools = agent_tools["TOOL_LIST"]
###    tool_choice = agent_tools["CHOICE"]
    
    # モデルの実行（モデル／システムプロンプト）
    chat = gemini_client.chats.create(
        model=model["MODEL"],
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=model["PARAMETER"]["temperature"],
        ),
        history=memory_message
    )

    prompt = query
    if stream_mode:
        completion = chat.send_message_stream(user_prompt)
        for chunk_completion in completion:
            response = chunk_completion.text
            yield prompt, response, chunk_completion
    else:
        completion = chat.send_message_stream(user_prompt)
        response = completion.text
        yield prompt, response, completion
    
    #レスポンスから出力を抽出
#    response = completion.text
#    prompt_tokens = completion.usage_metadata.prompt_token_count
#    response_tokens = completion.usage_metadata.candidates_token_count

#    return response, completion, prompt_tokens, response_tokens


# llamaの実行
def generate_response_T_llama(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    llama = LlamaAPI(llama_api_key)

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
#    for image_path in image_paths:
#        image_base64 = dmu.encode_image_file(image_path)
#        image_message.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}})
    
    # ユーザーのプロンプトを設定
    prompt = [{"type": "text", "text": query}] + image_message
    user_message = [{"role": "user", "content": prompt}]    

    # ツールを設定【要検討：いったんデフォルト設定】
#    tools = agent_tools["TOOL_LIST"]
#    tool_choice = agent_tools["CHOICE"]
    
    # モデルの実行
    api_request_json = {
        "model": model["MODEL"],
        "temperature": model["PARAMETER"]["temperature"],
        "messages": system_message + memory_message + user_message,
        "max_tokens": 20000,
        "stream": False
    }
    completion = llama.run(api_request_json).json()

    response = completion["choices"][0]["message"]["content"]
    yield query, response, completion

#    prompt_tokens = completion["usage"]["prompt_tokens"]
#    response_tokens = completion["usage"]["completion_tokens"]

#    return response, completion, prompt_tokens, response


# 考察に対する画像生成
def generate_image_dalle(prompt, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
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
#    prompt_str = json.dumps(system_message + memory_message + user_message, ensure_ascii=False).replace("\n", "").replace("\\", "")
    prompt_str = json.dumps(memory_message + user_message, ensure_ascii=False).replace("\n", "").replace("\\", "")

    # 画像生成モデルの実行
    completion = openai_client.images.generate(
        model=model["MODEL"],
        prompt=prompt_str[:3000],
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
        img_file = temp_folder_path + f"{num}_dalle.jpg"
        with open(img_file, "wb") as f:
            f.write(base64.b64decode(d.b64_json))
        img_files.append(img_file)
        num = num + 1

    response = "画像を生成しました。"
    completion = img_files

    yield prompt_str, response, completion
