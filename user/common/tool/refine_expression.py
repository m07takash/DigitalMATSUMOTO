"""Tool plugin: Japanese expression refiner.

Takes a finished response and returns the same text with unnatural Japanese
fixed — wording no one would actually say, overblown phrasing that reads like
translated English, and sentences that do not connect. What the text says, and
the voice it says it in, are left alone.

Declared as an AFTER SKILL with `MERGE: "REPLACE"`, so the refined text becomes
the answer. With any other MERGE the proofread version would be stored beside
the answer while the original stayed the answer of record — almost never what a
proofreader is for.

Behaviour contract:
  * Only the wording changes. Nothing is added, summarised, or reordered
    beyond what a broken connection needs.
  * Every failure path (load error, exception, empty or suspiciously short
    result) returns the original text unchanged — a proofreading pass must
    never be able to lose the response.

The rules themselves live in `PROMPT_TEMPLATE."Refine Expression"`, so new
kinds of awkward phrasing can be added without touching this file.
"""
from pathlib import Path

import logging
import re

import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_ToolRegistry as dmtr


logger = logging.getLogger(__name__)

_settings = dmu.read_yaml_file("setting.yaml")
practice_folder_path = _settings.get("PRACTICE_FOLDER", "user/common/practice/")

_DEFAULT_AGENT = "agent_6ARefineExpression.json"
_DEFAULT_PROMPT_CD = "Refine Expression"
# Proofreading returns roughly what it was given. A much shorter answer means
# the model summarised, refused, or answered about the text instead of
# returning it, so the original is kept.
_MIN_LENGTH_RATIO = 0.7

_INPUT_TEXT = {
    "type": "string",
    "description": "The response text to proofread for unnatural Japanese.",
}

_FENCE_RE = re.compile(r"\A```[\w-]*\n(.*)\n```\Z", re.S)

# The template makes the model list what it found before rewriting. Naming the
# problems first catches far more of them than asking for the corrected text
# alone, and the body still comes back on its own because only what follows the
# marker is returned.
_FIXED_MARKER = "<<<FIXED>>>"
_CHECK_MARKER = "<<<CHECK>>>"


def _split_check_and_body(text):
    """(check_notes, body). A model that ignores the format and just returns the
    rewritten text still works: the whole response becomes the body."""
    _i = text.rfind(_FIXED_MARKER)
    if _i < 0:
        return "", text
    _notes = text[:_i]
    _j = _notes.find(_CHECK_MARKER)
    if _j >= 0:
        _notes = _notes[_j + len(_CHECK_MARKER):]
    return _notes.strip(), text[_i + len(_FIXED_MARKER):].strip()


def _unwrap_fence(text):
    """Some models hand the whole body back inside a code fence even when told
    not to. Only a fence wrapping the entire answer is stripped, so fenced
    code *inside* the body survives."""
    m = _FENCE_RE.match(text.strip())
    return m.group(1) if m else text


def _resolve_editor_agent(agent_file, add_info):
    """ARGS_HINT override, then the calling agent's SUPPORT_AGENT slot, then
    the bundled generic editor. The calling agent is deliberately never used
    itself: its persona would rewrite the text in its own voice instead of
    only repairing the wording."""
    hinted = (add_info or {}).get("model_agent")
    if hinted:
        return hinted
    try:
        slot = (dma.get_agent_item(agent_file, "SUPPORT_AGENT") or {}).get("REFINE_EXPRESSION")
    except Exception:
        slot = ""
    if isinstance(slot, dict):
        slot = slot.get("AGENT_FILE", "")
    return slot or _DEFAULT_AGENT


def refine_expression(service_info, user_info, session_id, session_name, agent_file,
                      input, import_contents=[], add_info={}):
    original = input or ""
    if not original.strip():
        return service_info, user_info, original, "", 0, 0

    try:
        agent = dma.DigiM_Agent(_resolve_editor_agent(agent_file, add_info))
        model_type = "LLM"
        model_name = agent.agent["ENGINE"][model_type]["MODEL"]
        tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

        practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
        practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
        if practice["CHAINS"][0]["TYPE"] == "LLM":
            prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
        else:
            prompt_temp_cd = _DEFAULT_PROMPT_CD
        prompt_template = agent.set_prompt_template(prompt_temp_cd)
    except Exception:
        logger.exception("[refine_expression] editor agent unavailable; text returned unchanged")
        return service_info, user_info, original, "", 0, 0

    prompt = f"{prompt_template}\n\n【本文】\n{original}"

    try:
        response = ""
        for _prompt, chunk, _completion in agent.generate_response(
            model_type, prompt, [], stream_mode=False
        ):
            if chunk:
                response += chunk
        _notes, response = _split_check_and_body((response or "").strip())
        response = _unwrap_fence(response).strip()
        if _notes:
            # The only record of what the pass decided — the caller gets the
            # body alone, so without this a bad call is unexplainable.
            logger.info("[refine_expression] %s findings:\n%s", model_name, _notes)
    except Exception:
        logger.exception("[refine_expression] %s failed; text returned unchanged", model_name)
        return service_info, user_info, original, model_name, 0, 0

    if len(response) < _MIN_LENGTH_RATIO * len(original):
        logger.warning("[refine_expression] %s returned %d chars for %d; text returned unchanged",
                       model_name, len(response), len(original))
        return service_info, user_info, original, model_name, 0, 0

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# ----- registrations ---------------------------------------------------------

dmtr.register_tool(
    "refine_expression",
    description=(
        "Proofread a finished Japanese text and fix only unnatural expression: "
        "wording no one would actually say, overblown phrasing that reads like "
        "translated English, and sentences that do not connect to each other. "
        "Facts, claims, structure, and tone are preserved, and the corrected "
        "body is returned on its own. Use when a draft reads awkwardly; do NOT "
        "use to shorten, summarise, translate, or restyle the text."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=refine_expression,
    example="/refine_expression ← 直前の応答の表現を直す",
)
