"""Tool plugin: web search across Perplexity / OpenAI / Google / Claude.

Migrated from DigiM_Tool.py — see that file for the historical implementation.

The generic `WebSearch(...)` dispatcher reads engine= kwarg (or args.engine via
`_websearch_dispatch`), then routes through `WEB_SEARCH_ENGINES`. Cfg-driven
call sites in DigiM_Execute keep passing `engine=` explicitly via
`call_function_by_name`; LLM-driven SKILL/Thinking picks specify the engine
via args.engine on the JSON tool_call.
"""
import os

import requests
from dotenv import load_dotenv

import DigiM_Util as dmu
import DigiM_ToolRegistry as dmtr


_INPUT_TEXT = {
    "type": "string",
    "description": "Free-form text — typically the user's query or relevant input for this tool.",
}


# ----- engine implementations ------------------------------------------------

# Web search (Perplexity AI)
def WebSearch_PerplexityAI(service_info, user_info, session_id, session_name, agent_file,
                           input, import_contents=[], add_info={}):
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
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_prompt + "\n" + input,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort,
            },
        ],
    }

    results = requests.post(url, json=payload, headers=headers)
    response = results.json()["choices"][0]["message"]["content"]
    export_contents = results.json()["search_results"]

    return service_info, user_info, response, export_contents


# Web search (OpenAI web_search)
def WebSearch_OpenAI(service_info, user_info, session_id, session_name, agent_file,
                     input, import_contents=[], add_info={}):
    from openai import OpenAI
    if os.path.exists("system.env"):
        load_dotenv("system.env")
    api_key = os.getenv("OPENAI_API_KEY")

    system_setting_dict = dmu.read_yaml_file("setting.yaml")
    system_prompt = system_setting_dict.get("OPENAI_SEARCH_SYSTEM_PROMPT", "Be precise and concise.")
    user_prompt = system_setting_dict.get("OPENAI_SEARCH_USER_PROMPT", "以下の入力に基づいて、関連する情報を提供してください。")
    model = system_setting_dict.get("OPENAI_SEARCH_MODEL", "gpt-4.1-mini")

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        tools=[{"type": "web_search_preview"}],
        input=user_prompt + "\n" + input,
        instructions=system_prompt,
    )

    response_text = ""
    export_urls = []
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if hasattr(content, "text"):
                    response_text += content.text
                    if hasattr(content, "annotations"):
                        for ann in content.annotations:
                            if hasattr(ann, "url"):
                                export_urls.append({"url": ann.url, "title": getattr(ann, "title", "")})

    return service_info, user_info, response_text, export_urls


# Web search (Google Grounding Search)
def WebSearch_Google(service_info, user_info, session_id, session_name, agent_file,
                     input, import_contents=[], add_info={}):
    from google import genai
    from google.genai import types
    if os.path.exists("system.env"):
        load_dotenv("system.env")
    api_key = os.getenv("GEMINI_API_KEY")

    system_setting_dict = dmu.read_yaml_file("setting.yaml")
    user_prompt = system_setting_dict.get("GOOGLE_SEARCH_USER_PROMPT", "以下の入力に基づいて、関連する情報を提供してください。")
    model = system_setting_dict.get("GOOGLE_SEARCH_MODEL", "gemini-2.5-flash-preview-05-20")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=user_prompt + "\n" + input,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        ),
    )

    response_text = response.text if response.text else ""
    export_urls = []
    if response.candidates and response.candidates[0].grounding_metadata:
        gm = response.candidates[0].grounding_metadata
        if gm.grounding_chunks:
            for chunk in gm.grounding_chunks:
                if hasattr(chunk, "web") and chunk.web:
                    export_urls.append({"url": chunk.web.uri, "title": chunk.web.title or ""})

    return service_info, user_info, response_text, export_urls


# Web search (Anthropic Claude server-side web_search tool)
def WebSearch_Claude(service_info, user_info, session_id, session_name, agent_file,
                     input, import_contents=[], add_info={}):
    import anthropic
    if os.path.exists("system.env"):
        load_dotenv("system.env")
    api_key = os.getenv("ANTHROPIC_API_KEY")

    system_setting_dict = dmu.read_yaml_file("setting.yaml")
    model = system_setting_dict.get("CLAUDE_SEARCH_MODEL", "claude-sonnet-4-6")
    user_prompt = system_setting_dict.get("CLAUDE_SEARCH_USER_PROMPT", "以下の入力に基づいて、関連する情報を提供してください。")
    system_prompt = system_setting_dict.get("CLAUDE_SEARCH_SYSTEM_PROMPT", "Be precise and concise.")
    max_tokens = system_setting_dict.get("CLAUDE_SEARCH_MAX_TOKENS", 4096)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        messages=[{"role": "user", "content": user_prompt + "\n" + input}],
    )

    response_text = ""
    export_urls = []
    seen_urls = set()
    for block in response.content:
        if getattr(block, "type", None) == "text":
            response_text += getattr(block, "text", "") or ""
            for citation in (getattr(block, "citations", None) or []):
                url = getattr(citation, "url", None)
                title = getattr(citation, "title", "") or ""
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    export_urls.append({"url": url, "title": title})

    return service_info, user_info, response_text, export_urls


# ----- dispatch -------------------------------------------------------------

WEB_SEARCH_ENGINES = {
    "Perplexity": WebSearch_PerplexityAI,
    "OpenAI": WebSearch_OpenAI,
    "Google": WebSearch_Google,
    "Claude": WebSearch_Claude,
}


def WebSearch(service_info, user_info, session_id, session_name, agent_file,
              input, import_contents=[], add_info={}, engine="Perplexity"):
    func = WEB_SEARCH_ENGINES.get(engine, WebSearch_PerplexityAI)
    return func(service_info, user_info, session_id, session_name, agent_file, input, import_contents, add_info)


# Registry wrapper: lets the LLM specify the engine via args.engine, and accepts
# an explicit engine= kwarg for code-driven callers (e.g. cfg-driven path).
def _websearch_dispatch(service_info, user_info, session_id, session_name,
                        agent_file, input, import_contents=[], add_info={}, engine=None):
    if engine is None:
        engine = (add_info or {}).get("engine", "Perplexity")
    return WebSearch(service_info, user_info, session_id, session_name,
                     agent_file, input, import_contents, add_info, engine=engine)


# ----- registrations --------------------------------------------------------

dmtr.register_tool(
    "WebSearch",
    description=(
        "Run a web search via the engine specified in args.engine "
        "('Perplexity' | 'OpenAI' | 'Google' | 'Claude'; default Perplexity). "
        "Use when the question requires up-to-date information from the open web."
    ),
    schema={
        "type": "object",
        "properties": {
            "input": _INPUT_TEXT,
            "engine": {
                "type": "string",
                "enum": ["Perplexity", "OpenAI", "Google", "Claude"],
                "description": "Which web-search backend to use.",
                "default": "Perplexity",
            },
        },
        "required": ["input"],
    },
    func=_websearch_dispatch,
)

dmtr.register_tool(
    "WebSearch_PerplexityAI",
    description="Web search via Perplexity AI. Prefer the generic 'WebSearch' tool unless a specific engine is required.",
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=WebSearch_PerplexityAI,
)

dmtr.register_tool(
    "WebSearch_OpenAI",
    description="Web search via the OpenAI web_search tool. Prefer the generic 'WebSearch' tool unless a specific engine is required.",
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=WebSearch_OpenAI,
)

dmtr.register_tool(
    "WebSearch_Google",
    description="Web search via Google Grounding Search (Gemini). Prefer the generic 'WebSearch' tool unless a specific engine is required.",
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=WebSearch_Google,
)

dmtr.register_tool(
    "WebSearch_Claude",
    description="Web search via the Anthropic Claude server-side web_search tool. Prefer the generic 'WebSearch' tool unless a specific engine is required.",
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=WebSearch_Claude,
)
