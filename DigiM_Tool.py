import os
import json
from pathlib import Path
from dotenv import load_dotenv
import re
import time
import pandas as pd
import requests
import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Session as dms
import DigiM_Execute as dme

# Load folder paths and other settings from setting.yaml
system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]
character_folder_path = system_setting_dict["CHARACTER_FOLDER"]
practice_folder_path = system_setting_dict["PRACTICE_FOLDER"]

# Resolve a function by its string name
def call_function_by_name(service_info, user_info, func_name, *args, **kwargs):
    if func_name in globals():
        func = globals()[func_name]
        return func(service_info, user_info, *args, **kwargs)  # Forward arguments to the function
    else:
        response = f"Error: Tool function '{func_name}' not found."
        export_contents = []
        return service_info, user_info, response, export_contents

# Reply with a fixed message
def fixed_message(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    response = input
    export_contents = []

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, export_contents

# Delete the session's chat history
def forget_history(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "N")

    response = "All conversation history has been forgotten."
    export_contents = []

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, export_contents

# Restore the session's chat history
def remember_history(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
    session = dms.DigiMSession(session_id)
    chat_history_dict = session.get_history()

    for seq in chat_history_dict.keys():
        session.chg_seq_history(seq, "Y")

    response = "All conversation history has been restored."
    export_contents = []

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, export_contents

# Extract a date from text
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

    # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Extract Date"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Execute RAG
    user_query = input
    knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs)

    # Build the prompt
    prompt = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens

# PageIndex search: have the LLM select page IDs relevant to the query
def page_index_search(exec_info, agent_file, query, pages, max_pages=5):
    import json as _json
    if not agent_file:
        agent_file = "agent_59PageIndexSearch.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"

    # Format the page list
    page_list_text = ""
    for p in pages:
        tags = ", ".join(p.get("tags", [])) if p.get("tags") else ""
        page_list_text += f"- {p['id']}: {p['title']} — {p.get('summary', '')} [{tags}]\n"

    # Fetch the prompt template
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Page Index Search"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Assemble the prompt
    prompt = f"{prompt_template}\n\n【Page list】\n{page_list_text}\nMax selections: {max_pages}\n\n【User question】\n{query}"

    # Run the LLM
    response = ""
    for _, response_chunk, _ in agent.generate_response(model_type, prompt, [], stream_mode=False):
        if response_chunk:
            response += response_chunk

    # Extract the ID list from the response
    selected_ids = []
    try:
        import re
        json_match = re.search(r'\[.*?\]', response, re.DOTALL)
        if json_match:
            selected_ids = _json.loads(json_match.group(0))
    except (_json.JSONDecodeError, AttributeError):
        pass

    # Filter to valid IDs only
    valid_ids = {p["id"] for p in pages}
    selected_ids = [pid for pid in selected_ids if pid in valid_ids][:max_pages]

    return selected_ids

# Thinking Agent: analyze the user's question and return execution parameters as JSON
def thinking_agent(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_70DigiMThinking.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    situation_prompt = add_info.get("Situation", "")
    digest_text = add_info.get("DigestText", "")
    habit_info = add_info.get("HabitInfo", "")
    book_info = add_info.get("BookInfo", "")

    # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Thinking"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Insert additional info into the prompt
    context = ""
    if habit_info:
        context += f"\n【Available habits】\n{habit_info}\n"
    if book_info:
        context += f"\n【Available books】\n{book_info}\n"
    if digest_text:
        context += f"\n【Conversation digest】\n{digest_text}\n"

    prompt = f'{context}{prompt_template}{user_query}{situation_prompt}'

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, [], stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens

# Generate the RAG query from text
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

    # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "RAG Query Generator"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Execute RAG
    knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs)

    # Build the prompt
    prompt = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens

# Generate the conversation digest
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

    # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Dialog Digest"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Convert memory to text
    digest_memories_text = ", ".join(
        f'{{"role": "{item["role"]}", "content": "{item["text"]}"}}'
        for item in memories_selected
    )

    # Build the prompt
    query = f'{prompt_template}{user_query}\n{digest_memories_text}'

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    # Output format
    response = "【Conversation digest so far】\n" + response

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens

# Fair integration / summary across multiple persona responses.
# persona_responses: [{"persona_name": "...", "text": "..."}, ...]
# summary_level: "light"/"medium"/"heavy" or a free-form string (e.g. "around 300 chars")
def dialog_persona_merge(service_info, user_info, session_id, session_name, agent_file,
                          user_query, persona_responses, summary_level="medium"):
    if not agent_file:
        agent_file = "agent_50PersonaMerge.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    # Mapping of summary-level keyword -> description (free-form strings are passed through)
    level_map = {
        "light":  "簡潔（200字程度）",  # concise, ~200 chars
        "medium": "標準（500字程度）",  # standard, ~500 chars
        "heavy":  "詳細（1000字程度）",  # detailed, ~1000 chars
    }
    summary_level_text = level_map.get(summary_level, summary_level)

    # Fetch the prompt template and substitute {summary_level}
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Persona Merge"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)
    prompt_template = prompt_template.replace("{summary_level}", summary_level_text)

    # Convert persona responses to text
    responses_text = "\n\n".join(
        f"【{(r.get('persona_name') or '?')}】\n{r.get('text', '')}"
        for r in persona_responses
    )

    query = (
        f"{prompt_template}\n\n"
        f"【Original question】\n{user_query}\n\n"
        f"【Each persona's response】\n{responses_text}"
    )

    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# Phase 7: Select up to N optimal personas based on the question content
# candidate_personas: [{"persona_id": "P0001", "name": "...", "act": "...", "character_text": "..."}, ...]
# Returns: (selected_persona_ids, reasoning, model_name, prompt_tokens, response_tokens)
def select_personas(service_info, user_info, session_id, session_name, agent_file,
                    user_query, candidate_personas, max_personas=3):
    if not candidate_personas:
        return [], "no candidates", "", 0, 0
    if not agent_file:
        agent_file = "agent_54PersonaSelector.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    # Fetch the prompt template
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Persona Selector"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Compact-serialize candidate personas to JSON (id / name / act / leading excerpt of character_text)
    candidates_json = json.dumps([
        {
            "id": p.get("persona_id", ""),
            "name": p.get("name", ""),
            "act": p.get("act", ""),
            "character": (p.get("character_text") or "")[:120],
        }
        for p in candidate_personas
    ], ensure_ascii=False, indent=2)

    # Substitute placeholders
    prompt_template = (prompt_template
                       .replace("{max_personas}", str(max_personas))
                       .replace("{candidate_personas}", candidates_json))

    query = f'{prompt_template}{user_query}'

    # Execute the LLM (non-streaming)
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    # Extract JSON
    selected_ids = []
    reasoning = ""
    try:
        json_str = response.strip()
        # Remove ```json ... ``` fences
        if json_str.startswith("```"):
            json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
            json_str = re.sub(r"\s*```$", "", json_str)
        # Extract the JSON block
        m = re.search(r"\{.*\}", json_str, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            ids_raw = parsed.get("personas") or []
            if isinstance(ids_raw, list):
                # Keep only IDs that exist in the candidate pool
                candidate_ids = {p.get("persona_id") for p in candidate_personas}
                selected_ids = [str(pid) for pid in ids_raw if str(pid) in candidate_ids]
                # Trim from the front when exceeding the cap
                if max_personas and len(selected_ids) > max_personas:
                    selected_ids = selected_ids[:max_personas]
            reasoning = parsed.get("reasoning", "")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"persona selector JSON parse failed: {e}, raw={response[:200]!r}")

    return selected_ids, reasoning, model_name, prompt_tokens, response_tokens


# Generate the session name
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

    # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Session Name"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Convert memory to text
    digest_memories_text = ", ".join(
        f'{{"role": "{item["role"]}", "content": "{item["text"]}"}}'
        for item in memories_selected
    )

    # Build the prompt
    query = f'{prompt_template}\n{digest_memories_text}\n{user_query}'

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens

# Web search (Perplexity AI)
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

# Web search (OpenAI web_search)
def WebSearch_OpenAI(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
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

    # Extract text and URLs from the response
    response_text = ""
    export_urls = []
    for item in response.output:
        if item.type == "message":
            for content in item.content:
                if hasattr(content, "text"):
                    response_text += content.text
                    # Extract URLs from annotations
                    if hasattr(content, "annotations"):
                        for ann in content.annotations:
                            if hasattr(ann, "url"):
                                export_urls.append({"url": ann.url, "title": getattr(ann, "title", "")})

    return service_info, user_info, response_text, export_urls

# Web search (Google Grounding Search)
def WebSearch_Google(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
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

    # Extract text and URLs from the response
    response_text = response.text if response.text else ""
    export_urls = []
    if response.candidates and response.candidates[0].grounding_metadata:
        gm = response.candidates[0].grounding_metadata
        if gm.grounding_chunks:
            for chunk in gm.grounding_chunks:
                if hasattr(chunk, "web") and chunk.web:
                    export_urls.append({"url": chunk.web.uri, "title": chunk.web.title or ""})

    return service_info, user_info, response_text, export_urls

# Dispatch web search (switch function by engine name)
WEB_SEARCH_ENGINES = {
    "Perplexity": WebSearch_PerplexityAI,
    "OpenAI": WebSearch_OpenAI,
    "Google": WebSearch_Google,
}

def WebSearch(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}, engine="Perplexity"):
    func = WEB_SEARCH_ENGINES.get(engine, WebSearch_PerplexityAI)
    return func(service_info, user_info, session_id, session_name, agent_file, input, import_contents, add_info)

# Business analysis
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
        rule_text = "Include the following in your input.\nClient: <company name>\nBiz: <business name>"
        return service_info, user_info, rule_text, []

    test_folder_path = "test/"
    test_file = "Tool_MgrAnalysis.xlsx"
    test_sheet_name = "Test"
    raw_name_Q = "Q"

    # Execution settings
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

    # Unlock the session once
    session = dms.DigiMSession(session_id, session_name)
    session.save_status("UNLOCKED")

    # Load the test file and loop
    test_file_path = str(Path(test_folder_path) / test_file)
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
            if response_chunk and not str(response_chunk).startswith("[STATUS]"):
                response += response_chunk

        Q_no += 1
        time.sleep(3)

    export_contents = []

    return response_service_info, response_user_info, response, export_contents

# Compare texts
def compare_texts(service_info, user_info, head1, text1, head2, text2, query_compare=""):
    agent_file = "agent_53CompareTexts.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    # Resolve the prompt template assigned to the agent
    if query_compare == "":
        prompt_temp_cd = "Compare Texts"
        prompt_template = agent.set_prompt_template(prompt_temp_cd)
    else:
        prompt_template = query_compare

    # Build the prompt
    prompt = f'{prompt_template}\n\n[{head1}]\n{text1}\n\n[{head2}]\n{text2}'

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens

# Generate critique on image data
def art_critics(service_info, user_info, memories_selected=[], image_paths=[], agent_file="agent_52ArtCritic.json"):
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Art Critic"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Build the prompt
    prompt = f'{prompt_template}'

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, image_paths):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    response_service_info = service_info
    response_user_info = user_info

    return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens
