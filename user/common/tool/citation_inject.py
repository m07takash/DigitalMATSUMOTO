"""Tool plugin: Citation injector.

Takes a finished LLM response plus a list of web-search source URLs and
returns the same response with `[N]` citation markers inserted at the
end of sentences whose content matches a source, plus a `## References`
section listing the URLs at the bottom.

Behaviour contract:
  * The main body text is NOT rewritten. Only [N] markers are inserted.
  * If the underlying LLM call fails for any reason (timeout, exception,
    parse error, empty result), we fall back to appending a plain
    `## References` section to the original response. The original body
    text is left untouched in every failure path.

Usage (from DigiM_Execute after the main LLM call):

    add_info = {
        # Heterogeneous source list. Each item is one of:
        #   {"type": "web",       "url": "...",      "title": "..."}
        #   {"type": "book", "rag_name": "...", "title": "...", "snippet": "..."}
        # Sources without `type` are treated as "web" (legacy callers).
        # Web sources dedup by URL, knowledge sources dedup by (rag_name, title).
        "Sources": [
            {"type": "web",       "url": "https://...", "title": "..."},
            {"type": "book", "rag_name": "Identity", "title": "...", "snippet": "..."},
        ],
    }
    _, _, cited_text, _, _, _ = dmt.call_function_by_name(
        svc, usr, "inject_citations",
        session_id, session_name, agent_file,
        original_response_text, [], add_info)
"""
from pathlib import Path

import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_ToolRegistry as dmtr


_settings = dmu.read_yaml_file("setting.yaml")
practice_folder_path = _settings.get("PRACTICE_FOLDER", "user/common/practice/")

_INPUT_TEXT = {
    "type": "string",
    "description": "The original LLM response text to annotate with [N] citations.",
}


def _normalise_sources(sources):
    """Coerce a heterogeneous Sources list into uniform dicts:
      {"type": "web"|"book", "key": <dedup_key>, "label": <display_label>}
    Sources without `type` are treated as `"web"` (legacy callers).
    De-duplication: web by URL, knowledge by (rag_name, title).
    """
    seen = set()
    out = []
    for s in sources or []:
        if not isinstance(s, dict):
            continue
        kind = (s.get("type") or "web").lower()
        if kind == "web":
            url = (s.get("url") or "").strip()
            if not url:
                continue
            key = ("web", url)
            if key in seen:
                continue
            seen.add(key)
            title = (s.get("title") or "").strip()
            label = f"(web) {url}" + (f" - {title}" if title else "")
            out.append({"type": "web", "key": key, "label": label,
                        "url": url, "title": title})
        elif kind == "book":
            rag_name = (s.get("rag_name") or "").strip()
            title = (s.get("title") or "").strip()
            if not title:
                continue
            key = ("book", rag_name, title)
            if key in seen:
                continue
            seen.add(key)
            snippet = (s.get("snippet") or "").strip()
            tag = f"(book: {rag_name})" if rag_name else "(book)"
            label_parts = [tag, title]
            if snippet:
                label_parts.append("— " + snippet)
            out.append({"type": "book", "key": key, "label": " ".join(label_parts),
                        "rag_name": rag_name, "title": title, "snippet": snippet})
        # silently drop unknown types
    return out


def _build_references_block(sources):
    """Return a plain `## References` block from a heterogeneous sources list."""
    norm = _normalise_sources(sources)
    if not norm:
        return ""
    lines = [f"[{i}] {n['label']}" for i, n in enumerate(norm, 1)]
    return "## References\n" + "\n".join(lines)


def _fallback_response(original_text, sources):
    """Return original body + auto-built References (no [N] markers in body)."""
    refs = _build_references_block(sources)
    if not refs:
        return original_text or ""
    return f"{(original_text or '').rstrip()}\n\n{refs}"


def inject_citations(service_info, user_info, session_id, session_name, agent_file,
                     input, import_contents=[], add_info={}):
    """Inject [N] citation markers + References. Graceful fallback on any failure."""
    sources = (add_info or {}).get("Sources") or []
    original = input or ""

    # No sources -> nothing to cite. Return original unchanged.
    if not original.strip() or not sources:
        return service_info, user_info, original, "", 0, 0

    # Resolve agent (SUPPORT_AGENT.CITATION_INJECT typically; bundled default if absent)
    try:
        if not agent_file:
            agent_file = "agent_79DigiMCitationInject.json"
        agent = dma.DigiM_Agent(agent_file)
        model_type = "LLM"
        model_name = agent.agent["ENGINE"][model_type]["MODEL"]
        tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

        practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
        practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
        if practice["CHAINS"][0]["TYPE"] == "LLM":
            prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
        else:
            prompt_temp_cd = "Citation Injector"
        prompt_template = agent.set_prompt_template(prompt_temp_cd)
    except Exception:
        # Couldn't even load the support agent: pure-text fallback
        return service_info, user_info, _fallback_response(original, sources), "", 0, 0

    # Build a numbered sources block. The LLM must reuse [N] verbatim.
    normalised = _normalise_sources(sources)
    if not normalised:
        # All inputs were unusable after normalisation: return body unchanged.
        return service_info, user_info, original, "", 0, 0
    source_lines = [f"[{i}] {n['label']}" for i, n in enumerate(normalised, 1)]
    sources_block = "\n".join(source_lines)

    prompt = (
        f"{prompt_template}\n\n"
        f"【本回答】\n{original}\n\n"
        f"【参照ソース一覧（番号は変更不可）】\n{sources_block}"
    )

    try:
        response = ""
        for _prompt, response_chunk, _completion in agent.generate_response(
            model_type, prompt, [], stream_mode=False
        ):
            if response_chunk:
                response += response_chunk
        response = (response or "").strip()
    except Exception:
        return service_info, user_info, _fallback_response(original, sources), model_name, 0, 0

    # Sanity: the LLM should have returned something. If empty or much shorter than original,
    # don't trust it — fall back.
    if not response or len(response) < max(0.5 * len(original), 50):
        return service_info, user_info, _fallback_response(original, sources), model_name, 0, 0

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# ----- registrations ---------------------------------------------------------

dmtr.register_tool(
    "inject_citations",
    description=(
        "Add [N] citation markers + a References section to a finished response, "
        "using the supplied web-search source URLs. Body text is not rewritten. "
        "Internal tool — invoked from DigiM_Execute after the main LLM call when "
        "the Insert Citations toggle is on; not safe to include in Agent "
        "SKILL.TOOL_LIST because the args are structured (Sources list)."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=inject_citations,
)
