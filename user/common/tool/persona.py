"""Tool plugin: persona selector.

Migrated from DigiM_Tool.py — see that file for the historical implementation.
"""
import json
import re
from pathlib import Path

import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_ToolRegistry as dmtr


_settings = dmu.read_yaml_file("setting.yaml")
practice_folder_path = _settings.get("PRACTICE_FOLDER", "user/common/practice/")


# Phase 7: Select up to N optimal personas based on the question content.
# Non-uniform signature: (..., candidate_personas, max_personas).
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

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Persona Selector"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    candidates_json = json.dumps([
        {
            "id": p.get("persona_id", ""),
            "name": p.get("name", ""),
            "act": p.get("act", ""),
            "character": (p.get("character_text") or "")[:120],
        }
        for p in candidate_personas
    ], ensure_ascii=False, indent=2)

    prompt_template = (prompt_template
                       .replace("{max_personas}", str(max_personas))
                       .replace("{candidate_personas}", candidates_json))

    query = f'{prompt_template}{user_query}'

    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    selected_ids = []
    reasoning = ""
    try:
        json_str = response.strip()
        if json_str.startswith("```"):
            json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
            json_str = re.sub(r"\s*```$", "", json_str)
        m = re.search(r"\{.*\}", json_str, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            ids_raw = parsed.get("personas") or []
            if isinstance(ids_raw, list):
                candidate_ids = {p.get("persona_id") for p in candidate_personas}
                selected_ids = [str(pid) for pid in ids_raw if str(pid) in candidate_ids]
                if max_personas and len(selected_ids) > max_personas:
                    selected_ids = selected_ids[:max_personas]
            reasoning = parsed.get("reasoning", "")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"persona selector JSON parse failed: {e}, raw={response[:200]!r}")

    return selected_ids, reasoning, model_name, prompt_tokens, response_tokens


# ----- registrations ---------------------------------------------------------

# Internal orchestration tool — non-uniform signature and return shape.
# Registered so legacy `dmt.select_personas(...)` callers resolve via the shim.
# DO NOT include in Agent SKILL.TOOL_LIST — args/return do not fit the standard schema.
dmtr.register_tool(
    "select_personas",
    description=(
        "Internal orchestration helper — pick up to N personas best matching a question. "
        "Non-uniform signature: (svc, usr, sid, sname, agent_file, user_query, "
        "candidate_personas, max_personas). NOT safe for SKILL/Thinking dispatch."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    func=select_personas,
)
