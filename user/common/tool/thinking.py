"""Tool plugin: thinking-mode / RAG-query / page-index search tools.

Migrated from DigiM_Tool.py — see that file for the historical implementation.
"""
import json as _json
import re as _re
from pathlib import Path

import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_ToolRegistry as dmtr


_settings = dmu.read_yaml_file("setting.yaml")
practice_folder_path = _settings.get("PRACTICE_FOLDER", "user/common/practice/")

_INPUT_TEXT = {
    "type": "string",
    "description": "Free-form text — typically the user's query or relevant input for this tool.",
}


# Thinking Agent: analyze the user's question and return execution parameters as JSON
def thinking_agent(service_info, user_info, session_id, session_name, agent_file,
                   user_query, import_contents=[], add_info={}):
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

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Thinking"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    context = ""
    if habit_info:
        context += f"\n【Available habits】\n{habit_info}\n"
    if book_info:
        context += f"\n【Available books】\n{book_info}\n"
    if digest_text:
        context += f"\n【Conversation digest】\n{digest_text}\n"

    prompt = f'{context}{prompt_template}{user_query}{situation_prompt}'

    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, [], stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# Generate the RAG query from text
def RAG_query_generator(service_info, user_info, session_id, session_name, agent_file,
                        user_query, import_contents=[], add_info={}):
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

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "RAG Query Generator"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs)

    prompt = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'

    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# PageIndex search: have the LLM select page IDs relevant to the query.
# Non-uniform signature: (exec_info, agent_file, query, pages, max_pages=5).
def page_index_search(exec_info, agent_file, query, pages, max_pages=5):
    if not agent_file:
        agent_file = "agent_59PageIndexSearch.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"

    page_list_text = ""
    for p in pages:
        tags = ", ".join(p.get("tags", [])) if p.get("tags") else ""
        page_list_text += f"- {p['id']}: {p['title']} — {p.get('summary', '')} [{tags}]\n"

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Page Index Search"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    prompt = f"{prompt_template}\n\n【Page list】\n{page_list_text}\nMax selections: {max_pages}\n\n【User question】\n{query}"

    response = ""
    for _, response_chunk, _ in agent.generate_response(model_type, prompt, [], stream_mode=False):
        if response_chunk:
            response += response_chunk

    selected_ids = []
    try:
        json_match = _re.search(r'\[.*?\]', response, _re.DOTALL)
        if json_match:
            selected_ids = _json.loads(json_match.group(0))
    except (_json.JSONDecodeError, AttributeError):
        pass

    valid_ids = {p["id"] for p in pages}
    selected_ids = [pid for pid in selected_ids if pid in valid_ids][:max_pages]

    return selected_ids


# ----- registrations ---------------------------------------------------------

dmtr.register_tool(
    "thinking_agent",
    description=(
        "Run the meta-cognitive 'Thinking' agent which analyses the user's "
        "question and decides downstream execution parameters (which habit / "
        "book / RAG / web search to engage). Returns structured decision text. "
        "Typically used by the orchestrator rather than picked by another LLM."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=thinking_agent,
)

dmtr.register_tool(
    "RAG_query_generator",
    description=(
        "Generate a refined query string optimized for retrieval against the "
        "agent's RAG knowledge base. Use when the raw user text needs to be "
        "reformulated into a search-friendly query."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=RAG_query_generator,
)

# Internal orchestration tool — non-uniform signature. Registered so
# legacy `dmt.page_index_search(...)` callers resolve via the shim.
# DO NOT include in Agent SKILL.TOOL_LIST — args do not fit the standard schema.
dmtr.register_tool(
    "page_index_search",
    description=(
        "Internal orchestration helper — select page IDs relevant to a query "
        "from a pre-loaded page list. Non-uniform signature: "
        "(exec_info, agent_file, query, pages, max_pages). "
        "NOT safe for SKILL/Thinking dispatch."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    func=page_index_search,
)
