"""Tool plugin: dialog summarization, session-naming, and persona merge.

Migrated from DigiM_Tool.py — see that file for the historical implementation.
"""
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


# Generate the conversation digest
def dialog_digest(service_info, user_info, session_id, session_name, agent_file,
                  user_query, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_60DialogDigest.json"
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

    # Split the incoming memories into two clearly-labelled sections. The
    # incremental caller (DigiM_Execute) tags each item with `kind`:
    #   prev_digest  — the accumulated digest from prior turns; MUST be
    #                  preserved verbatim so older topics don't quietly
    #                  fall out of the running memory.
    #   latest_turn  — the user + assistant messages from THIS turn only;
    #                  the LLM should extract new bullets from these and
    #                  append them to the accumulation.
    # Legacy callers without `kind` are treated as latest_turn (backward
    # compat — behaviour then matches the pre-tag version).
    prev_digest_text = ""
    latest_turn_lines = []
    for item in memories_selected:
        kind = item.get("kind") or "latest_turn"
        text = item.get("text", "")
        if kind == "prev_digest":
            prev_digest_text = text
        else:
            latest_turn_lines.append(
                f'{{"role": "{item.get("role","")}", "content": "{text}"}}'
            )
    latest_turn_text = ", ".join(latest_turn_lines)

    # Build the prompt with explicitly separated sections so the LLM can't
    # accidentally re-summarise the previous digest and drop old topics.
    _prev_block = (
        f"\n\n【これまでの累積ダイジェスト — この内容は絶対に一字一句そのまま保持し、"
        f"要約しなおしたり短縮したり項目を減らしたりしない】\n{prev_digest_text}\n"
    ) if prev_digest_text else "\n\n【これまでの累積ダイジェスト】\n(初回のためまだ無し)\n"
    _latest_block = (
        f"\n【最新の会話（この分だけを新規に箇条書きで追記対象とする）】\n{latest_turn_text}\n"
    )
    query = f"{prompt_template}{user_query}{_prev_block}{_latest_block}"

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    response = "【Conversation digest so far】\n" + response
    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# Generate the session name
def gene_session_name(service_info, user_info, session_id, session_name, agent_file,
                     user_query, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_61SessionName.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    memories_selected = []
    if "Memories_Selected" in add_info:
        memories_selected = add_info["Memories_Selected"]

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Session Name"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    digest_memories_text = ", ".join(
        f'{{"role": "{item["role"]}", "content": "{item["text"]}"}}'
        for item in memories_selected
    )

    query = f'{prompt_template}\n{digest_memories_text}\n{user_query}'

    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# Fair integration / summary across multiple persona responses.
# Non-uniform signature: persona_responses + summary_level instead of (input, import_contents, add_info).
def dialog_persona_merge(service_info, user_info, session_id, session_name, agent_file,
                          user_query, persona_responses, summary_level="medium"):
    if not agent_file:
        agent_file = "agent_64PersonaMerge.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    level_map = {
        "light":  "簡潔（200字程度）",
        "medium": "標準（500字程度）",
        "heavy":  "詳細（1000字程度）",
    }
    summary_level_text = level_map.get(summary_level, summary_level)

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Persona Merge"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)
    prompt_template = prompt_template.replace("{summary_level}", summary_level_text)

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


# ----- registrations ---------------------------------------------------------

dmtr.register_tool(
    "dialog_digest",
    description=(
        "Summarize the recent conversation memory of the current session into a "
        "short digest. Use when downstream steps need compressed context rather "
        "than the full history."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": []},
    func=dialog_digest,
)

dmtr.register_tool(
    "gene_session_name",
    description=(
        "Generate a short, descriptive session name from the user's first query "
        "(or short conversation digest). Typically called automatically when a "
        "new session is started without an explicit name."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=gene_session_name,
)

# Internal orchestration tool — non-uniform signature. Registered so
# legacy `dmt.dialog_persona_merge(...)` callers resolve via the shim.
# DO NOT include in Agent SKILL.TOOL_LIST — args do not fit the standard schema.
dmtr.register_tool(
    "dialog_persona_merge",
    description=(
        "Internal orchestration helper — merge multiple persona responses into one. "
        "Non-uniform signature: (svc, usr, sid, sname, agent_file, user_query, "
        "persona_responses, summary_level). NOT safe for SKILL/Thinking dispatch."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    func=dialog_persona_merge,
)
