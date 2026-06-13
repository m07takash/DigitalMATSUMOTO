"""
Engine-agnostic tool registry.

A single declarative source of truth for every tool DigiMatsu can call.
The same entry powers:
  - Practice TOOL chains  (lookup by name, dispatch via call_function_by_name)
  - Thinking-mode JSON dispatch (render schema as text, parse LLM JSON reply)
  - Optional native function-calling on providers that support it (future)

Tools are uniform-signature callables:
    func(service_info, user_info, session_id, session_name,
         agent_file, input, import_contents=[], add_info={})
The args the LLM emits are mapped onto (input, add_info) — see
`split_args_to_uniform_signature` below.
"""
import json
import re
from typing import Callable, Iterable, Optional, Any

# name -> {name, description, schema, func}
TOOL_REGISTRY: dict = {}


def register_tool(
    name: str,
    *,
    description: str,
    schema: Optional[dict] = None,
    func: Optional[Callable] = None,
    example: Optional[str] = None,
) -> None:
    """Register or replace a tool.

    Args:
        name: Tool identifier (also the slash-command name).
        description: Free-text describing what the tool does. Surfaces to the
            LLM (via Thinking-mode picker) and to the user (Skills panel).
        schema: JSON Schema describing the LLM-visible args. Used by
            Thinking-mode dispatch.
        func: The callable. Must match the uniform tool signature
            (svc, usr, sid, sname, agent_file, input, import_contents, add_info)
            unless the tool is internal-only.
        example: Optional one-line concrete usage example for the SKILL panel
            (e.g. "/WebSearch 2026 Super Bowl winner"). When set, the WebUI
            Skills panel shows this verbatim instead of the generic
            "/<name> <input>" syntax. Use multi-line strings (with literal
            "\\n") for tools that expect structured input.
    """
    entry = TOOL_REGISTRY.get(name, {})
    entry.update({
        "name": name,
        "description": description,
        "schema": schema or {"type": "object", "properties": {}, "required": []},
        "func": func or entry.get("func"),
        "example": example if example is not None else entry.get("example"),
    })
    TOOL_REGISTRY[name] = entry


def get_tool(name: str) -> Optional[dict]:
    return TOOL_REGISTRY.get(name)


def list_tools(names: Optional[Iterable[str]] = None) -> list:
    """Return all tools, or only the named subset (skipping unknown names)."""
    if names is None:
        return list(TOOL_REGISTRY.values())
    return [TOOL_REGISTRY[n] for n in names if n in TOOL_REGISTRY]


def render_tools_for_prompt(tools: list) -> str:
    """Format tools as a provider-agnostic text block to inject into a system/user prompt.

    Any LLM that follows instructions and emits JSON can consume this — no provider-specific
    `tools=[]` parameter required, so the same flow works on GPT/Gemini/Claude/Grok alike.
    """
    if not tools:
        return ""
    parts = ["[Available tools]"]
    for t in tools:
        parts.append(f"- name: {t['name']}")
        parts.append(f"  description: {t.get('description', '')}")
        parts.append(f"  args_schema: {json.dumps(t.get('schema', {}), ensure_ascii=False)}")
    parts.append("")
    parts.append("[Tool call protocol]")
    parts.append("If one or more of the tools above are appropriate, reply with JSON ONLY in this exact shape:")
    parts.append('{"tool_calls":[{"name":"<tool_name>","args":{...}}]}')
    parts.append('If no tool is needed, reply with: {"tool_calls":[]}')
    parts.append("Do not wrap the JSON in markdown fences or prose.")
    return "\n".join(parts)


_FENCE_RE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.MULTILINE)


def parse_tool_calls(response_text: str) -> list:
    """Best-effort extraction of the `tool_calls` array from an LLM response.

    Strips markdown fences, then greedily grabs the first `{` to the last `}` and json.loads.
    Returns a list of {"name": str, "args": dict} dicts; empty list on any parse failure
    or when the model explicitly returned no tool_calls.
    """
    if not response_text:
        return []
    s = _FENCE_RE.sub("", response_text).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return []
    try:
        obj = json.loads(s[i:j + 1])
    except Exception:
        return []
    if not isinstance(obj, dict):
        return []
    calls = obj.get("tool_calls")
    if not isinstance(calls, list):
        return []
    out = []
    for c in calls:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        args = c.get("args", {})
        if isinstance(name, str) and isinstance(args, dict):
            out.append({"name": name, "args": args})
    return out


def split_args_to_uniform_signature(args: dict) -> tuple:
    """Map an LLM-emitted args dict onto the uniform tool signature's (input, add_info).

    Convention: the `input` key (if present) becomes the positional `input` argument;
    everything else flows into `add_info`. This lets the LLM emit a flat args dict
    while existing tools keep their `(input, ..., add_info)` shape unchanged.
    """
    args = args or {}
    input_val = args.get("input", "")
    add_info = {k: v for k, v in args.items() if k != "input"}
    return input_val, add_info
