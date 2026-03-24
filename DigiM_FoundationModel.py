import os
import json
from pathlib import Path
import base64
from dotenv import load_dotenv

import openai
from openai import OpenAI
from google import genai
from google.genai import types
import anthropic
from llamaapi import LlamaAPI

import DigiM_Util as dmu

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
temp_folder_path = system_setting_dict["TEMP_FOLDER"]

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
openai_api_key = os.getenv("OPENAI_API_KEY")
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
llama_api_key = os.getenv("LLAMA_API_KEY")
xai_api_key = os.getenv("XAI_API_KEY")

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
        **model["PARAMETER"],
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

# OpenAIのResponses関数の実行
def generate_response_T_gpt_response(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=False):
    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key
    openai_client = OpenAI(timeout=600) #タイムアウトを設定(10min)

    # システムプロンプトではなくインストラクションを設定
    instructions = system_prompt

    # メモリをプロンプトに設定
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    # イメージ画像をプロンプトに設定
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        image_message.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}})
    
    # ユーザーのプロンプトを設定
    user_prompt = [{"type": "input_text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = memory_message + user_message

    # ツールを設定
    tools = agent_tools["TOOL_LIST"]

    # モデルの実行
    completion = openai_client.responses.create(
        model = model["MODEL"],
        **model["PARAMETER"],
        input = prompt,
        instructions = instructions,
        tools = tools
    )

    response = completion.output_text
    yield str(prompt), response, completion 

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
        **model["PARAMETER"],
        tools = tools,
        input = prompt,
        stream = stream_mode
    )

    response = completion.output_text
    yield str(prompt), response, completion

# Geminiの実行
def generate_response_T_gemini(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    gemini_client = genai.Client(api_key=gemini_api_key)
    contents=[]

    # システムプロンプトの設定
    system_instruction = system_prompt

    # メモリをプロンプトに設定
    memory_message = []
    for memory in memories:
        if memory["role"] == "user":
            memory_message.append({"role": "user", "parts":[{"text": memory["text"]}]})
        elif memory["role"] == "assistant":
            memory_message.append({"role": "model", "parts":[{"text": memory["text"]}]})

    contents += memory_message

    # イメージ画像をプロンプトに設定
    images = []
    for image_path in image_paths:
        image_data = dmu.encode_image_file(image_path)
        image_suffix = Path(image_path).suffix
        image_type = ""
        if image_suffix in ["jpeg", "jpg"]:
            image_type = "image/jpeg"
        elif image_suffix in ["png"]:
            image_type = "image/png"
        if image_type:
            images.append({"inlineData": {"mimeType": image_type, "data": image_data}})

    # ユーザーのプロンプトを設定
    user_prompt = [{"text": query}]
    contents.append({"role": "user", "parts": user_prompt})
    contents += images

    # ツールを設定【修正前】
###    tools = agent_tools["TOOL_LIST"]
###    tool_choice = agent_tools["CHOICE"]

    # thought_signatureなど非テキストパーツを除いてテキストのみ抽出するヘルパー
    def _extract_text(candidate_response):
        try:
            parts = candidate_response.candidates[0].content.parts
            return "".join(p.text for p in parts if hasattr(p, "text") and p.text)
        except Exception:
            return ""

    # モデルの実行（モデル／システムプロンプト）
    response_stream_total = ""
    if stream_mode:
        completion = gemini_client.models.generate_content_stream(
            model = model["MODEL"],
            config = types.GenerateContentConfig(system_instruction=system_instruction),
            contents = contents
            )
        for chunk_completion in completion:
            response = _extract_text(chunk_completion)
            response_stream_total += response if response else ""
            yield str(contents), response, chunk_completion

    # ストリーミングの結果が取得されない場合、ストリーミングではないモードで再実行
    if not stream_mode or response_stream_total == "":
        completion = gemini_client.models.generate_content(
            model = model["MODEL"],
            config = types.GenerateContentConfig(system_instruction=system_instruction),
            contents = contents
            )
        response = _extract_text(completion)
        yield str(contents), response, completion

# Claudeの実行
def generate_response_T_claude(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    claude_client = anthropic.Anthropic(api_key=anthropic_api_key)

    # メモリをプロンプトに設定
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    # イメージ画像をプロンプトに設定
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        image_message.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_base64}})

    # ユーザーのプロンプトを設定
    user_prompt = [{"type": "text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = memory_message + user_message

    # ツールを設定【要検討：いったんデフォルト設定】
    tools = agent_tools["TOOL_LIST"]
    tool_choice = agent_tools["CHOICE"]

    # モデルの実行
    if stream_mode:
        with claude_client.messages.stream(
            model = model["MODEL"],
            **model["PARAMETER"],
            system = system_prompt,
            messages = prompt
            ) as stream:
            for response in stream.text_stream:
                yield str(prompt), response, stream
    else:
        completion = claude_client.messages.create(
            model = model["MODEL"],
            **model["PARAMETER"],
            system = system_prompt,
            messages = prompt
            )
        response = completion.content[0].text
        yield str(prompt), response, completion

# Grokの実行
def generate_response_T_grok(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    from xai_sdk import Client
    from xai_sdk.chat import user, assistant, system, image

    grok_client = Client(api_key=xai_api_key, timeout=3600)
    grok_chat = grok_client.chat.create(model=model["MODEL"])

    # システムプロンプトの設定
    grok_chat.append(system(system_prompt))

    # メモリをプロンプトに設定
    memory_message = []
    for memory in memories:
        memory_data = {"role": memory["role"], "content": [{"type": "text", "text": memory["text"]}]}
        memory_message.append(memory_data)
        if memory["role"] == "user":
            grok_chat.append(user(memory["text"]))
        elif memory["role"] == "assistant":
            grok_chat.append(assistant(memory["text"]))

    # イメージ画像をプロンプトに設定
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        image_message.append(image(image_url=f"data:image/jpeg;base64,{image_base64}"))

    # ユーザーのプロンプトを設定
    user_prompt = [{"type": "text", "text": query}]# + image_message
    user_message = {"role": "user", "content": user_prompt}
    user_message = {"role": "user", "content": query}
    prompt = memory_message + [user_message]
    grok_chat.append(user(query, *image_message))

    # ツールを設定【要検討：いったんデフォルト設定】
    tools = agent_tools["TOOL_LIST"]
    tool_choice = agent_tools["CHOICE"]

    # モデルの実行
    if stream_mode:
        for completion, chunk_completion in grok_chat.stream():
            response = chunk_completion.content
            yield str(prompt), response, chunk_completion
    else:
        completion = grok_chat.sample()
        response = completion.content
        yield str(prompt), response, completion

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
        **model["PARAMETER"],
        "messages": system_message + memory_message + user_message,
        "max_tokens": 20000,
        "stream": False
    }
    completion = llama.run(api_request_json).json()

    response = completion["choices"][0]["message"]["content"]
    yield query, response, completion

# Geminiによる画像生成（nano banana 2等）
def generate_image_gemini(prompt, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    gemini_client = genai.Client(api_key=gemini_api_key)

    # メモリをプロンプトに設定
    memory_message = []
    for memory in memories:
        if memory["role"] == "user":
            memory_message.append({"role": "user", "parts": [{"text": memory["text"]}]})
        elif memory["role"] == "assistant":
            memory_message.append({"role": "model", "parts": [{"text": memory["text"]}]})

    # ユーザーのプロンプトを設定
    contents = memory_message + [{"role": "user", "parts": [{"text": prompt}]}]

    # 画像生成パラメータ（ImageConfigはaspect_ratioのみ対応）
    aspect_ratio = model.get("PARAMETER", {}).get("aspect_ratio")

    completion = gemini_client.models.generate_content(
        model=model["MODEL"],
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            **({"image_config": types.ImageConfig(aspect_ratio=aspect_ratio)} if aspect_ratio else {})
        )
    )

    # TEMPフォルダに保存
    img_files = []
    response_text = "画像を生成しました。"
    num = 0
    for part in completion.parts:
        if hasattr(part, "text") and part.text:
            response_text = part.text
        else:
            img = part.as_image() if hasattr(part, "as_image") else None
            if img is None and hasattr(part, "inline_data") and part.inline_data:
                img_bytes = base64.b64decode(part.inline_data.data)
                img_file = temp_folder_path + f"{num}_gemini_image.jpg"
                with open(img_file, "wb") as f:
                    f.write(img_bytes)
                img_files.append(img_file)
                num += 1
            elif img is not None:
                img_file = temp_folder_path + f"{num}_gemini_image.png"
                img.save(img_file)
                img_files.append(img_file)
                num += 1

    completion_result = img_files if img_files else completion
    yield str(contents), response_text, completion_result


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
    prompt_str = json.dumps(memory_message + user_message, ensure_ascii=False).replace("\n", "").replace("\\", "")

    # 画像生成モデルの実行
    completion = openai_client.images.generate(
        model=model["MODEL"],
        prompt=prompt_str[:3000],
        **model["PARAMETER"]
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
