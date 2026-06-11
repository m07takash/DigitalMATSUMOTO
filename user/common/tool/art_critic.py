"""Tool plugin: art-critic image evaluation.

Migrated from DigiM_Tool.py — see that file for the historical implementation.
"""
from pathlib import Path

import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_ToolRegistry as dmtr


_settings = dmu.read_yaml_file("setting.yaml")
practice_folder_path = _settings.get("PRACTICE_FOLDER", "user/common/practice/")


# Generate critique on image data.
# Non-uniform signature: (svc, usr, memories_selected, image_paths, agent_file).
def art_critics(service_info, user_info, memories_selected=[], image_paths=[],
                agent_file="agent_52ArtCritic.json"):
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Art Critic"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    prompt = f'{prompt_template}'

    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, image_paths):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# ----- registrations ---------------------------------------------------------

# Internal orchestration tool — non-uniform signature (image_paths instead of input).
# Registered so legacy `dmt.art_critics(...)` callers resolve via the shim.
# DO NOT include in Agent SKILL.TOOL_LIST — args do not fit the standard schema.
dmtr.register_tool(
    "art_critics",
    description=(
        "Internal orchestration helper — critique image content via an LLM. "
        "Non-uniform signature: (svc, usr, memories_selected, image_paths, agent_file). "
        "NOT safe for SKILL/Thinking dispatch."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    func=art_critics,
)
