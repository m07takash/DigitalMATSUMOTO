"""Progress messages shown while a turn runs (master `messages`).

The executor writes one line to status.yaml at each step; the WebUI shows it
as "⏳ ..." and the API returns it as progress.message. The wording lives in
the master, so an operator can change it, and change it per channel: a LINE
user and a WebUI operator read the same step differently.

Master shape (user/common/mst/messages.json):
  {
    "STATUS": {"<code>": {"DEFAULT": "text with {param}", "<SERVICE_ID>": "..."}},
    "SKILL":  {"<skill name>": {"BEFORE": "...", "AFTER": "...", "<SERVICE_ID>": {...}}}
  }
Lookup: the service's text, then DEFAULT, then the built-in English below.
A skill without an entry keeps the generic "SKILL[<phase>]:<name>" line.
"""
import logging
from typing import Any, Dict, List

import DigiM_MstStore as dmms

logger = logging.getLogger(__name__)

# code -> (built-in text, its parameters). The built-in text is what the
# executor showed before the master existed.
BUILTIN = {
    "web_search_start":      ("Starting web search", ()),
    "rag_query_gene_start":  ("Starting RAG search-query generation", ()),
    "rag_start":             ("Starting RAG", ()),
    "llm_running":           ("Running LLM", ()),
    "citations_inserting":   ("Inserting citations", ()),
    "digest_generating":     ("Generating digest", ()),
    "thinking":              ("Thinking...", ()),
    "thinking_turn":         ("Thinking (turn {turn}/{max_turns})...", ("turn", "max_turns")),
    "thinking_preview":      ("Thinking: preview web search", ()),
    "thinking_turn_preview": ("Thinking (turn {turn}/{max_turns}): preview web search", ("turn", "max_turns")),
    "personas_selecting":    ("Selecting personas (up to {max})", ("max",)),
    "skill_before":          ("SKILL[BEFORE]:{name}", ("name",)),
    "skill_after":           ("SKILL[AFTER]:{name}", ("name",)),
    "chain_running":         ("Chain {index}/{count} ({type}) running", ("index", "count", "type")),
    "batch_qa":              ("Batch Q&A [{sheet}] ({index}/{count})", ("sheet", "index", "count")),
    "running":               ("Running...", ()),
}
SKILL_PHASES = ("BEFORE", "AFTER")


class _Keep(dict):
    # An unknown {placeholder} in an edited text stays as written instead of
    # failing the turn.
    def __missing__(self, key):
        return "{" + key + "}"


def _master() -> Dict[str, Any]:
    try:
        data = dmms.load("messages", default={})
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _pick(entry, service_id: str) -> str:
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return ""
    for key in (service_id, "DEFAULT"):
        v = entry.get(key) if key else None
        if isinstance(v, str) and v.strip():
            return v
    return ""


def render(code: str, service_id: str = "", **params) -> str:
    text = _pick(((_master().get("STATUS") or {}).get(code)), service_id) or BUILTIN.get(code, (code, ()))[0]
    try:
        return text.format_map(_Keep({k: v for k, v in params.items()}))
    except Exception:
        return BUILTIN.get(code, (text, ()))[0].format_map(_Keep(params))


def skill_label(name: str, phase: str, service_id: str = "") -> str:
    """The master's line for one skill, or "" when it has none."""
    entry = (_master().get("SKILL") or {}).get(name)
    if not isinstance(entry, dict):
        return ""
    svc = entry.get(service_id) if service_id else None
    for src in (svc, entry):
        if isinstance(src, dict):
            v = src.get(phase) or src.get("DEFAULT")
            if isinstance(v, str) and v.strip():
                return v
    return ""


def skill_status(names: List[str], phase: str, service_id: str = "") -> tuple:
    """(text, code, params) for one or several skills running in `phase`.

    Several skills sharing one pass (the REPLACE group) read as one line.
    """
    names = [n for n in names if n]
    labels = [skill_label(n, phase, service_id) for n in names]
    code = "skill_before" if phase == "BEFORE" else "skill_after"
    joined = "+".join(names)
    if any(labels):
        return " / ".join(l or n for l, n in zip(labels, names)), code, {"name": joined}
    return render(code, service_id, name=joined), code, {"name": joined}


def status(session, code: str, service_info: dict = None, response: str = "", **params) -> str:
    """Write the step to status.yaml (text, plus code and parameters for a
    front end that words it itself) and return the text."""
    sid = ((service_info or {}).get("SERVICE_ID") or "") if isinstance(service_info, dict) else ""
    text = render(code, sid, **params)
    session.save_status_message(text, response=response, code=code, params=params)
    return text


def skill(session, names: List[str], phase: str, service_info: dict = None) -> str:
    sid = ((service_info or {}).get("SERVICE_ID") or "") if isinstance(service_info, dict) else ""
    text, code, params = skill_status(names, phase, sid)
    session.save_status_message(text, code=code, params=params)
    return text
