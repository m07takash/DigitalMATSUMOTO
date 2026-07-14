import os
import json
from pathlib import Path
import base64
from dotenv import load_dotenv

import openai
from openai import OpenAI, AzureOpenAI
from google import genai
from google.genai import types
import anthropic
from llamaapi import LlamaAPI

import mimetypes
import DigiM_Util as dmu

def _get_image_mime(image_path):
    """Detect MIME type from the file path (default: image/png)."""
    mime, _ = mimetypes.guess_type(image_path)
    return mime if mime and mime.startswith("image/") else "image/png"

# Load folder paths and other settings from setting.yaml
system_setting_dict = dmu.read_yaml_file("setting.yaml")
temp_folder_path = system_setting_dict["TEMP_FOLDER"]

# Load system.env and set environment variables
if os.path.exists("system.env"):
    load_dotenv("system.env")
openai_api_key = os.getenv("OPENAI_API_KEY")
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
llama_api_key = os.getenv("LLAMA_API_KEY")
xai_api_key = os.getenv("XAI_API_KEY")
# Azure OpenAI Service (for chat/image)
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")

# Singleton LLM clients
_clients = {}

def _get_openai_client(timeout=None):
    key = f"openai_{timeout}"
    if key not in _clients:
        _clients[key] = OpenAI(api_key=openai_api_key, timeout=timeout)
    return _clients[key]

def _get_azure_openai_client(timeout=None, api_version=None):
    """Azure OpenAI Service client. api_version can be overridden per agent."""
    _api_version = api_version or azure_openai_api_version
    key = f"azure_openai_{timeout}_{_api_version}"
    if key not in _clients:
        _clients[key] = AzureOpenAI(
            api_key=azure_openai_api_key,
            azure_endpoint=azure_openai_endpoint,
            api_version=_api_version,
            timeout=timeout,
        )
    return _clients[key]

def _get_gemini_client():
    if "gemini" not in _clients:
        _clients["gemini"] = genai.Client(api_key=gemini_api_key)
    return _clients["gemini"]

def _get_anthropic_client():
    if "anthropic" not in _clients:
        _clients["anthropic"] = anthropic.Anthropic(api_key=anthropic_api_key)
    return _clients["anthropic"]

def _get_llama_client():
    if "llama" not in _clients:
        _clients["llama"] = LlamaAPI(llama_api_key)
    return _clients["llama"]

# Resolve a function by its string name
def _sanitize_text(text):
    """Strip characters that cause JSON parse errors."""
    if not isinstance(text, str):
        return text
    import re
    # Remove the NUL character
    text = text.replace("\0", "")
    # Strip lone surrogates
    text = re.sub(r'[\ud800-\udfff]', '', text)
    # Strip C0 control characters that break JSON (keep \t, \n, \r)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text

def _sanitize_messages(messages):
    """Sanitize every text element inside a messages list."""
    if isinstance(messages, str):
        return _sanitize_text(messages)
    if isinstance(messages, list):
        return [_sanitize_messages(m) for m in messages]
    if isinstance(messages, dict):
        return {k: _sanitize_messages(v) for k, v in messages.items()}
    return messages

def call_function_by_name(func_name, *args, **kwargs):
    if func_name in globals():
        func = globals()[func_name]
        return func(*args, **kwargs)  # Forward arguments to the function
    else:
        return "Function not found"

# Run GPT (OpenAI Chat Completions).
#
# Model-agnostic: `model["MODEL"]` is the model id string and `model["PARAMETER"]`
# is forwarded verbatim as kwargs to `openai_client.chat.completions.create`.
# That means new GPT-family models slot in with an ENGINE-block entry alone —
# no code change here. Currently exercised by (non-exhaustive):
#   gpt-5.6                              → reasoning_effort low/medium/high
#   gpt-5.5, gpt-5.4                     → default reasoning
#   gpt-5-mini-2025-08-07, gpt-5-nano-2025-08-07
#   gpt-4o family (image input supported below via image_paths)
# For GPT-5.6 the caller controls the reasoning tier through PARAMETER —
# in agent_10Sample.json the three named modes map as:
#   Sol   → {"reasoning_effort": "high"}   (太陽: 最大出力)
#   Terra → {"reasoning_effort": "medium"} (地球: 標準)
#   Luna  → {"reasoning_effort": "low"}    (月:   最小/最速)
# If the installed OpenAI SDK is too old to accept `reasoning_effort`, the call
# raises TypeError on unknown kwarg — bump `openai>=1.55` or higher, or drop
# the PARAMETER key in the agent JSON.
def generate_response_T_gpt(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    openai_client = _get_openai_client()

    # Build the system prompt
    system_message = [
        {"role": "system", "content": system_prompt}
    ]

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    # Add images to the prompt
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        image_message.append({"type": "image_url", "image_url": {"url": f"data:{_get_image_mime(image_path)};base64,{image_base64}"}})

    # Build the user prompt
    user_prompt = [{"type": "text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = _sanitize_messages(system_message + memory_message + user_message)

    # Execute the model
    completion = openai_client.chat.completions.create(
        model = model["MODEL"],
        **model["PARAMETER"],
        messages = prompt,
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

# Run Azure OpenAI Service (gpt-* on Azure)
# MODEL must contain the Azure deployment name.
# Setting "api_version" inside PARAMETER overrides the API version per agent.
def generate_response_T_azure_openai(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    params = dict(model.get("PARAMETER") or {})
    _api_version = params.pop("api_version", None)
    azure_client = _get_azure_openai_client(api_version=_api_version)

    system_message = [{"role": "system", "content": system_prompt}]

    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        image_message.append({"type": "image_url", "image_url": {"url": f"data:{_get_image_mime(image_path)};base64,{image_base64}"}})

    user_prompt = [{"type": "text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = _sanitize_messages(system_message + memory_message + user_message)

    completion = azure_client.chat.completions.create(
        model=model["MODEL"],   # On Azure this is the deployment name
        **params,
        messages=prompt,
        stream=stream_mode,
    )

    if stream_mode:
        for chunk_completion in completion:
            if chunk_completion.choices:
                response = chunk_completion.choices[0].delta.content
                yield str(prompt), response, chunk_completion
    else:
        response = completion.choices[0].message.content
        yield str(prompt), response, completion


# Run the OpenAI Responses API
def generate_response_T_gpt_response(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=False):
    openai_client = _get_openai_client(timeout=600)

    # Set instructions instead of a system prompt
    instructions = system_prompt

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    # Add images to the prompt
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        image_message.append({"type": "image_url", "image_url": {"url": f"data:{_get_image_mime(image_path)};base64,{image_base64}"}})
    
    # Build the user prompt
    user_prompt = [{"type": "input_text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = _sanitize_messages(memory_message + user_message)

    # Execute the model
    completion = openai_client.responses.create(
        model = model["MODEL"],
        **model["PARAMETER"],
        input = prompt,
        instructions = instructions
    )

    response = completion.output_text
    yield str(prompt), response, completion 

# Run an OpenAI tool (see https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses)
def generate_response_openai_tool(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    openai_client = _get_openai_client()

    # Build the system prompt
    system_message = [
        {"role": "developer",
         "content": [{"type": "input_text", "text": system_prompt}]}
    ]

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    # Add images to the prompt
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        #image_message.append({"type": "image_url", "image_url": {"url": image_url["image_url"]}})
        image_message.append({"type": "image_url", "image_url": {"url": f"data:{_get_image_mime(image_path)};base64,{image_base64}"}})

    # Build the user prompt
    user_prompt = [{"type": "input_text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = _sanitize_messages(system_message + memory_message + user_message)

    # Execute the model
    completion = openai_client.responses.create(
        model = model["MODEL"],
        **model["PARAMETER"],
        input = prompt,
        stream = stream_mode
    )

    response = completion.output_text
    yield str(prompt), response, completion

# Run Gemini
def generate_response_T_gemini(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    gemini_client = _get_gemini_client()
    contents=[]

    # Build the system prompt
    system_instruction = system_prompt

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        if memory["role"] == "user":
            memory_message.append({"role": "user", "parts":[{"text": memory["text"]}]})
        elif memory["role"] == "assistant":
            memory_message.append({"role": "model", "parts":[{"text": memory["text"]}]})

    contents += memory_message

    # Add images to the prompt
    images = []
    for image_path in image_paths:
        image_data = dmu.encode_image_file(image_path)
        image_type = _get_image_mime(image_path)
        images.append({"inlineData": {"mimeType": image_type, "data": image_data}})

    # Build the user prompt
    user_prompt = [{"text": query}]
    contents.append({"role": "user", "parts": user_prompt})
    contents += images
    contents = _sanitize_messages(contents)
    system_instruction = _sanitize_text(system_instruction)

    # Helper that strips non-text parts (e.g., thought_signature) and extracts text only
    def _extract_text(candidate_response):
        try:
            parts = candidate_response.candidates[0].content.parts
            return "".join(p.text for p in parts if hasattr(p, "text") and p.text)
        except Exception:
            return ""

    # Execute the model (model + system prompt)
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

    # If streaming yields no results, retry in non-streaming mode
    if not stream_mode or response_stream_total == "":
        completion = gemini_client.models.generate_content(
            model = model["MODEL"],
            config = types.GenerateContentConfig(system_instruction=system_instruction),
            contents = contents
            )
        response = _extract_text(completion)
        yield str(contents), response, completion

# Run Claude
def generate_response_T_claude(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    claude_client = _get_anthropic_client()

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    # Add images to the prompt
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        image_message.append({"type": "image", "source": {"type": "base64", "media_type": _get_image_mime(image_path), "data": image_base64}})

    # Build the user prompt
    user_prompt = [{"type": "text", "text": query}] + image_message
    user_message = [{"role": "user", "content": user_prompt}]
    prompt = _sanitize_messages(memory_message + user_message)
    system_prompt = _sanitize_text(system_prompt)

    # Execute the model
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

# Run Grok
def generate_response_T_grok(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    from xai_sdk import Client
    from xai_sdk.chat import user, assistant, system, image

    grok_client = Client(api_key=xai_api_key, timeout=3600)
    grok_chat = grok_client.chat.create(model=model["MODEL"])

    # Build the system prompt
    grok_chat.append(system(system_prompt))

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        memory_data = {"role": memory["role"], "content": [{"type": "text", "text": memory["text"]}]}
        memory_message.append(memory_data)
        if memory["role"] == "user":
            grok_chat.append(user(memory["text"]))
        elif memory["role"] == "assistant":
            grok_chat.append(assistant(memory["text"]))

    # Add images to the prompt
    image_message = []
    for image_path in image_paths:
        image_base64 = dmu.encode_image_file(image_path)
        image_message.append(image(image_url=f"data:{_get_image_mime(image_path)};base64,{image_base64}"))

    # Build the user prompt
    user_prompt = [{"type": "text", "text": query}]# + image_message
    user_message = {"role": "user", "content": user_prompt}
    user_message = {"role": "user", "content": query}
    prompt = _sanitize_messages(memory_message + [user_message])
    grok_chat.append(user(_sanitize_text(query), *image_message))

    # Execute the model
    if stream_mode:
        for completion, chunk_completion in grok_chat.stream():
            response = chunk_completion.content
            yield str(prompt), response, chunk_completion
    else:
        completion = grok_chat.sample()
        response = completion.content
        yield str(prompt), response, completion

# Run Llama
def generate_response_T_llama(query, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    llama = _get_llama_client()

    # Build the system prompt
    system_message = [
        {"role": "system", "content": system_prompt}
    ]

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    # Add images to the prompt
    image_message = []
#    for image_path in image_paths:
#        image_base64 = dmu.encode_image_file(image_path)
#        image_message.append({"type": "image_url", "image_url": {"url": f"data:{_get_image_mime(image_path)};base64,{image_base64}"}})

    # Build the user prompt
    prompt = [{"type": "text", "text": query}] + image_message
    user_message = [{"role": "user", "content": prompt}]

    # Execute the model
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

# Image generation via Gemini (nano banana 2, etc.)
def generate_image_gemini(prompt, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    gemini_client = _get_gemini_client()

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        if memory["role"] == "user":
            memory_message.append({"role": "user", "parts": [{"text": memory["text"]}]})
        elif memory["role"] == "assistant":
            memory_message.append({"role": "model", "parts": [{"text": memory["text"]}]})

    # Build the user prompt
    contents = memory_message + [{"role": "user", "parts": [{"text": prompt}]}]

    # Image-generation parameters (ImageConfig supports only aspect_ratio)
    aspect_ratio = model.get("PARAMETER", {}).get("aspect_ratio")

    completion = gemini_client.models.generate_content(
        model=model["MODEL"],
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
            **({"image_config": types.ImageConfig(aspect_ratio=aspect_ratio)} if aspect_ratio else {})
        )
    )

    # Save under the temp folder (always match the extension with the real format)
    def _ext_from_bytes(b, fallback_mime=""):
        # Detect the actual format from the bytes and return the extension
        try:
            import io as _io
            from PIL import Image as _PIL
            _fmt = (_PIL.open(_io.BytesIO(b)).format or "").lower()
            if _fmt == "jpeg":
                return "jpg"
            if _fmt in ("png", "gif", "webp", "bmp"):
                return _fmt
        except Exception:
            pass
        if fallback_mime:
            _m = fallback_mime.lower()
            if "jpeg" in _m or "jpg" in _m:
                return "jpg"
            for _e in ("png", "gif", "webp", "bmp"):
                if _e in _m:
                    return _e
        return "png"

    img_files = []
    response_text = "Image generated."
    num = 0
    for part in completion.parts:
        if hasattr(part, "text") and part.text:
            response_text = part.text
            continue
        # Extract image bytes (prefer inline_data, otherwise via as_image())
        img_bytes = None
        mime_hint = ""
        if hasattr(part, "inline_data") and part.inline_data:
            try:
                _raw = part.inline_data.data
                # The SDK may yield raw bytes or a base64 string depending on the version; try both
                img_bytes = _raw if isinstance(_raw, (bytes, bytearray)) else base64.b64decode(_raw)
            except Exception:
                img_bytes = None
            mime_hint = getattr(part.inline_data, "mime_type", "") or ""
        if img_bytes is None and hasattr(part, "as_image"):
            try:
                _im = part.as_image()
                if _im is not None:
                    if hasattr(_im, "image_bytes") and _im.image_bytes:
                        img_bytes = _im.image_bytes
                        mime_hint = getattr(_im, "mime_type", "") or mime_hint
                    else:
                        # If it is a PIL Image, re-encode to PNG
                        import io as _io2
                        _buf = _io2.BytesIO()
                        _im.save(_buf, format="PNG")
                        img_bytes = _buf.getvalue()
                        mime_hint = "image/png"
            except Exception:
                pass
        if not img_bytes:
            continue
        _ext = _ext_from_bytes(img_bytes, mime_hint)
        img_file = temp_folder_path + f"{num}_gemini_image.{_ext}"
        with open(img_file, "wb") as f:
            f.write(img_bytes)
        img_files.append(img_file)
        num += 1

    completion_result = img_files if img_files else completion
    yield str(contents), response_text, completion_result


# Image generation for an insight
def generate_image_dalle(prompt, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    openai_client = _get_openai_client()

    # Build the system prompt
    system_message = [{"role": "system", "content": system_prompt}]

    # Build the user prompt
    user_message = [{"role": "user", "content": prompt}]

    # Add memory to the prompt
    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    # Stringify the prompt (strip invalid characters)
    prompt_str = json.dumps(_sanitize_messages(memory_message + user_message), ensure_ascii=False).replace("\n", "").replace("\\", "")

    # Execute the image-generation model
    params = dict(model["PARAMETER"])
    if "output_format" not in params:
        params["output_format"] = "png"
    completion = openai_client.images.generate(
        model=model["MODEL"],
        prompt=prompt_str[:3000],
        **params
    )

    # Save under the temp folder
    img_files = []
    num = 0
    ext = params.get("output_format", "png")
    for i, d in enumerate(completion.data):
        img_file = temp_folder_path + f"{num}_dalle.{ext}"
        with open(img_file, "wb") as f:
            f.write(base64.b64decode(d.b64_json))
        img_files.append(img_file)
        num = num + 1

    response = "Image generated."
    completion = img_files

    yield prompt_str, response, completion


# Image generation via Azure OpenAI Service (DALL-E on Azure)
def generate_image_azure_dalle(prompt, system_prompt, model, memories=[], image_paths=[], agent_tools={}, stream_mode=True):
    params = dict(model.get("PARAMETER") or {})
    _api_version = params.pop("api_version", None)
    azure_client = _get_azure_openai_client(api_version=_api_version)

    system_message = [{"role": "system", "content": system_prompt}]
    user_message = [{"role": "user", "content": prompt}]

    memory_message = []
    for memory in memories:
        memory_message.append({"role": memory["role"], "content": memory["text"]})

    prompt_str = json.dumps(_sanitize_messages(memory_message + user_message), ensure_ascii=False).replace("\n", "").replace("\\", "")

    if "output_format" not in params:
        params["output_format"] = "png"
    completion = azure_client.images.generate(
        model=model["MODEL"],   # On Azure this is the deployment name
        prompt=prompt_str[:3000],
        **params,
    )

    img_files = []
    num = 0
    ext = params.get("output_format", "png")
    for i, d in enumerate(completion.data):
        img_file = temp_folder_path + f"{num}_azure_dalle.{ext}"
        with open(img_file, "wb") as f:
            f.write(base64.b64decode(d.b64_json))
        img_files.append(img_file)
        num += 1

    response = "Image generated."
    yield prompt_str, response, img_files
