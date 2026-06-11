"""Tool plugin: Knowledge Utility interpretation.

Summarises one or more RAG/Vector DB usage snapshots into a structured
analyst-style commentary. Accepts back-data (CSV inventory + selected
docs with question/response similarities) plus optional scatter/bar
images for vision-capable models.

Usage (from WebDigiMatsuAgent_modified.py button handler):

    add_info = {
        "UserQuery":  "...",     # the question that triggered the RAG run
        "AIResponse": "...",     # the AI's generated answer
        "Sections": [
            {
                "RAGName": "DigitalMATSUMOTO",
                "SimilarityUtility": {"avg_sim_Q": 0.42, ...},
                "InventoryCsvPath": "user/<session>/analytics/.._ScatterData(PCA)_<rag>.csv",
                "SelectedDocs": [
                    {"title": "...", "similarity_Q": 0.6, "similarity_A": 0.8,
                     "knowledge_utility": 0.2, "DB": "...", "ID": "...",
                     "QUERY_SEQ": "...", "QUERY_MODE": "..."},
                    ...
                ],
                "ImagePaths": [".../scatter_ref.png", ".../scatter_cat.png",
                               ".../similarity.png"],   # optional
            },
            ...
        ],
        "UseImages": True,  # default True; auto-skipped if the agent's
                            # LLM isn't vision-capable (best-effort)
    }
    dmt.call_function_by_name(svc, usr, "knowledge_utility_interpret",
        session_id, session_name, agent_file, "", [], add_info)
"""
from pathlib import Path

import pandas as pd

import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_ToolRegistry as dmtr


_settings = dmu.read_yaml_file("setting.yaml")
practice_folder_path = _settings.get("PRACTICE_FOLDER", "user/common/practice/")

_MAX_SELECTED_DOCS_IN_PROMPT = 30
_MAX_CATEGORIES_IN_INVENTORY = 8
_MAX_INVENTORY_SAMPLE_ROWS = 5
_INPUT_TEXT = {
    "type": "string",
    "description": "Free-form text — typically the user's query or relevant input for this tool.",
}


def _fmt_num(x, digits=3, signed=False):
    try:
        spec = f"+.{digits}f" if signed else f".{digits}f"
        return format(float(x), spec)
    except (TypeError, ValueError):
        return str(x) if x is not None else ""


def _format_selected_docs(selected):
    """Return a table-style block summarising selected docs with delta = sim_A - sim_Q."""
    if not selected:
        return "  (no selected docs)"
    lines = ["  rank | title | sim_Q | sim_A | delta(A-Q) | knowledge_utility"]
    # sort by absolute delta descending (most informative for LLM)
    annotated = []
    for d in selected:
        try:
            sq = float(d.get("similarity_Q", 0))
            sa = float(d.get("similarity_A", 0))
            delta = sa - sq
        except (TypeError, ValueError):
            sq, sa, delta = None, None, None
        annotated.append({**d, "_sq": sq, "_sa": sa, "_delta": delta})
    # primary order: by question similarity descending (matches the on-screen rank order);
    # the prompt instructs the model to interpret delta independently.
    annotated.sort(key=lambda x: (x["_sq"] is None, -(x["_sq"] or 0)))
    for i, d in enumerate(annotated[:_MAX_SELECTED_DOCS_IN_PROMPT], 1):
        title = (d.get("title") or "").strip().replace("|", "/")
        if len(title) > 80:
            title = title[:80] + "…"
        ku = d.get("knowledge_utility")
        lines.append(
            f"  {i:>3} | {title} | {_fmt_num(d['_sq'])} | {_fmt_num(d['_sa'])} | "
            f"{_fmt_num(d['_delta'], signed=True):>7s} | {_fmt_num(ku, signed=True):>7s}"
        )
    if len(annotated) > _MAX_SELECTED_DOCS_IN_PROMPT:
        lines.append(f"  ... and {len(annotated) - _MAX_SELECTED_DOCS_IN_PROMPT} more")
    return "\n".join(lines)


def _summarise_inventory(csv_path):
    """Read scatter-plot CSV and return a compact textual summary."""
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        return f"  (inventory CSV unreadable: {e})"
    lines = [f"  total documents: {len(df)}"]
    # Category distribution
    if "category" in df.columns:
        counts = df["category"].astype(str).value_counts()
        lines.append("  top categories:")
        for cat, count in counts.head(_MAX_CATEGORIES_IN_INVENTORY).items():
            lines.append(f"    - {cat}: {count}")
        if len(counts) > _MAX_CATEGORIES_IN_INVENTORY:
            lines.append(f"    ... and {len(counts) - _MAX_CATEGORIES_IN_INVENTORY} more categories")
    # Date range
    if "create_date" in df.columns:
        try:
            dates = pd.to_datetime(df["create_date"], errors="coerce").dropna()
            if len(dates):
                lines.append(f"  date range: {dates.min().date()} → {dates.max().date()}")
        except Exception:
            pass
    # A few title samples to give the model concrete grounding
    if "title" in df.columns and len(df):
        lines.append("  sample titles:")
        for t in df["title"].astype(str).head(_MAX_INVENTORY_SAMPLE_ROWS):
            lines.append(f"    - {t[:80]}")
    return "\n".join(lines)


def _format_section(sec):
    """Render a single RAG-DB section as text."""
    rag_name = sec.get("RAGName", "(unknown RAG)")
    parts = [f"--- RAG DB: {rag_name} ---"]
    su = sec.get("SimilarityUtility") or {}
    if su:
        parts.append("Aggregate similarity metrics:")
        for k, v in su.items():
            parts.append(f"  - {k}: {v}")
    csv_path = sec.get("InventoryCsvPath")
    if csv_path and Path(csv_path).exists():
        parts.append("Inventory (full DB content):")
        parts.append(_summarise_inventory(csv_path))
    selected = sec.get("SelectedDocs") or []
    parts.append(f"Selected docs for this query ({len(selected)} entries):")
    parts.append(_format_selected_docs(selected))
    return "\n".join(parts)


def _engine_supports_vision(agent, model_type="LLM"):
    """Heuristic check whether the agent's active LLM model id is vision-capable.
    Conservative: returns True only on known vision-capable model families."""
    try:
        model_id = (agent.agent["ENGINE"][model_type]["MODEL"] or "").lower()
    except Exception:
        return False
    # Known vision-capable families
    vision_markers = (
        "gpt-4o", "gpt-5", "gemini-", "claude-opus", "claude-sonnet", "claude-haiku",
        "grok-vision", "grok-4",
    )
    return any(m in model_id for m in vision_markers)


def knowledge_utility_interpret(service_info, user_info, session_id, session_name,
                                 agent_file, input, import_contents=[], add_info={}):
    """Interpret RAG-DB utility snapshots; see module docstring for add_info shape."""
    if not agent_file:
        agent_file = "agent_78DigiMKnowledgeInterpret.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Knowledge Interpret"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    user_query = (add_info or {}).get("UserQuery") or input or ""
    ai_response = (add_info or {}).get("AIResponse", "")
    sections = (add_info or {}).get("Sections") or []
    use_images_req = bool((add_info or {}).get("UseImages", True))

    use_images = use_images_req and _engine_supports_vision(agent, model_type)

    section_blocks = [_format_section(sec) for sec in sections]
    data_block = "\n\n".join(section_blocks) if section_blocks else "(no RAG sections supplied)"

    image_paths = []
    if use_images:
        for sec in sections:
            for img in (sec.get("ImagePaths") or []):
                if img and Path(img).exists():
                    image_paths.append(img)

    prompt = (
        f"{prompt_template}\n\n"
        f"【ユーザーの質問】\n{user_query}\n\n"
        f"【AI の回答】\n{ai_response}\n\n"
        f"【知識利用データ】\n{data_block}"
    )

    response = ""
    for _prompt, response_chunk, _completion in agent.generate_response(
        model_type, prompt, [], image_paths=image_paths, stream_mode=False
    ):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# ----- registrations ---------------------------------------------------------

dmtr.register_tool(
    "knowledge_utility_interpret",
    description=(
        "Interpret RAG/Vector DB utilisation given (a) user query, (b) AI response, "
        "(c) per-DB inventory + selected docs with question/response similarities. "
        "Internal tool — called from the Analytics Results UI; not safe to "
        "include in Agent SKILL.TOOL_LIST because the args do not fit the standard "
        "schema (it expects structured add_info.Sections)."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": []},
    func=knowledge_utility_interpret,
)
