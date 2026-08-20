import os
import re
import time
import threading
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

import inspect
import pytz
import DigiM_Util as dmu
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Session as dms
import DigiM_Tool as dmt
import DigiM_ToolRegistry as dmtr
import DigiM_JobRegistry as djr
import DigiM_UserMemoryBuilder as dmumb
import DigiM_UserMemorySetting as dmus

# Load folder paths and other settings from setting.yaml
system_setting_dict = dmu.read_yaml_file("setting.yaml")
user_folder_path = system_setting_dict["USER_FOLDER"]
session_folder_prefix = system_setting_dict["SESSION_FOLDER_PREFIX"]
temp_folder_path = system_setting_dict["TEMP_FOLDER"]
practice_folder_path = system_setting_dict["PRACTICE_FOLDER"]

# Load system.env and set environment variables
if os.path.exists("system.env"):
    load_dotenv("system.env")
timezone_setting = os.getenv("TIMEZONE")

# Session lock error
class SessionLockedError(RuntimeError):
    pass

# B-2: Common parser for execution settings
def _parse_execution_settings(execution):
    return {
        "contents_save":     execution.get("CONTENTS_SAVE", True),
        "memory_use":        execution.get("MEMORY_USE", True),
        "memory_save":       execution.get("MEMORY_SAVE", True),
        "memory_similarity": execution.get("MEMORY_SIMILARITY", False),
        "magic_word_use":    execution.get("MAGIC_WORD_USE", True),
        "stream_mode":       execution.get("STREAM_MODE", True),
        "save_digest":       execution.get("SAVE_DIGEST", True),
        "meta_search":       execution.get("META_SEARCH", True),
        "RAG_query_gene":    execution.get("RAG_QUERY_GENE", True),
        "web_search":        execution.get("WEB_SEARCH", False),
        "web_search_engine": execution.get("WEB_SEARCH_ENGINE", ""),
        # Default ON: web-search results are wrapped in a short guardrail
        # that tells the LLM to keep persona/context in charge and treat the
        # snippet as reference material only. Turning it off passes the raw
        # search text into the prompt unwrapped.
        "web_search_guardrail": execution.get("WEB_SEARCH_GUARDRAIL", True),
        # Default ON: citations are automatically inserted whenever there are
        # citable sources (web URLs or Book chunks). API callers can opt out
        # explicitly via execution["INSERT_CITATIONS"] = False.
        "insert_citations":  execution.get("INSERT_CITATIONS", True),
        # Default OFF: KNOWLEDGE is the agent's internalised knowledge and is
        # excluded from `## Reference Info` by policy. Turning this on appends a
        # separate section listing the KNOWLEDGE chunks the turn actually used.
        "cite_knowledge":    execution.get("CITE_KNOWLEDGE", False),
        # Default OFF: when on, the main prompt asks for Markdown tables and
        # Mermaid diagrams where they clarify the explanation.
        "diagram_mode":      execution.get("DIAGRAM_MODE", False),
        # Default OFF: when on, the prompt asks for bold/heading emphasis on
        # the points that carry the answer.
        "emphasis_mode":     execution.get("EMPHASIS_MODE", False),
        "private_mode":      execution.get("PRIVATE_MODE", False),
        "thinking_mode":     execution.get("THINKING_MODE", False),
    }


# Instruction appended to the main prompt when DIAGRAM_MODE is on. Mermaid is
# fenced so the WebUI renderer can pick the blocks out of the Markdown body.
DIAGRAM_INSTRUCTION = (
    "\n\n【図解の指示】\n"
    "説明の理解を助ける箇所では、文章に加えて図解を用いてください。\n"
    "・比較・分類・一覧は Markdown の表にする\n"
    "・関係性/流れ/構造は Mermaid のコードブロック（```mermaid）で図示する\n"
    "　（flowchart, sequenceDiagram, graph TD などを用途に応じて使い分ける）\n"
    "・図解が不要な内容に無理に図を付けない。文章だけで足りる場合はそのままでよい\n"
)

# Instruction appended when EMPHASIS_MODE is on. Bounded on purpose: emphasis
# only reads as emphasis while it stays rare, so the rules cap how much of the
# text may be marked up rather than just asking for "more emphasis".
EMPHASIS_INSTRUCTION = (
    "\n\n【強調の指示】\n"
    "読み手が要点を拾えるよう、本文中の重要箇所に Markdown の強調を用いてください。\n"
    "・結論・判断・数値・固有名詞など、その回答の核心となる語句を **太字** にする\n"
    "・特に注意すべき点や例外は **太字** に加えて簡潔な理由を添える\n"
    "・回答が長くなる場合は見出し（##／###）で区切り、箇条書きを併用する\n"
    "・強調は多用しない。1段落あたり1〜2箇所を目安とし、文全体を太字にしない\n"
    "・口調や人格設定は変えない。あくまで書式のみの指示\n"
)


_KV_RE_CI = re.compile(r"'([^']+)'\s*:\s*'((?:[^'\\]|\\.)*)'")
_NUM_RE_CI = re.compile(r"'([^']+)'\s*:\s*(-?\d+\.?\d*)")


def _iter_knowledge_chunks(knowledge_selected, book_names):
    """Yield (rag, cid, title, sim_q, sim_a, util, value_text) per non-book
    chunk.

    cid is the chunk's stable identifier (the `id`/`ID` field ChromaDB or the
    PageIndex layer stamps in). We use it — not title — to key the manifest
    the second-pass selector references, because titles collide across RAGs
    and can be edited by the LLM's fuzzy paraphrasing.

    knowledge_selected is a mixed list — Vector chunks are dicts, PageIndex
    entries arrive as pre-formatted LOG_TEMPLATE strings. Normalise both."""
    def _as_float(v):
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0
    for c in knowledge_selected or []:
        if isinstance(c, dict):
            rag = c.get("rag", "") or c.get("rag_name", "")
            cid = str(c.get("id", "") or c.get("ID", "") or "")
            title = c.get("title", "") or cid
            sim_q = _as_float(c.get("similarity_prompt", c.get("similarity_Q", 0.0)))
            sim_a = _as_float(c.get("similarity_response", c.get("similarity_A", 0.0)))
            body = c.get("value_text_short") or c.get("value_text") or ""
        elif isinstance(c, str):
            kv = dict(_KV_RE_CI.findall(c))
            nums = dict(_NUM_RE_CI.findall(c))
            rag = kv.get("rag", "")
            cid = kv.get("ID", "") or kv.get("id", "") or kv.get("page_id", "")
            title = kv.get("title", "") or cid
            sim_q = _as_float(nums.get("similarity_Q", nums.get("similarity_prompt", 0.0)))
            sim_a = _as_float(nums.get("similarity_A", nums.get("similarity_response", 0.0)))
            body = kv.get("summary", "") or kv.get("text_short", "")
        else:
            continue
        if not rag or rag in book_names or not cid:
            continue
        yield rag, cid, title, sim_q, sim_a, (sim_q - sim_a), body


def _build_cite_knowledge_manifest(knowledge_selected, agent_data):
    """Build a lookup of every non-book chunk in this turn's retrieval.

    Returns {(rag, id): {rag, id, title, body, sim_q, sim_a, util}, ...}.
    No cap — the second-pass selector needs to see every chunk to decide
    what was actually referenced (the user explicitly asked us to stop
    truncating at top-60). Empty when no non-book chunks were retrieved.

    Selection of "which chunks the LLM actually used" is delegated to a
    dedicated support agent call (see _detect_used_chunks below), so we
    no longer inject an inline directive into the primary prompt."""
    _book_names = {(b or {}).get("RAG_NAME")
                   for b in (agent_data.get("BOOK") or [])
                   if isinstance(b, dict) and b.get("RAG_NAME")}
    lookup = {}
    for rag, cid, title, sim_q, sim_a, util, body in _iter_knowledge_chunks(
            knowledge_selected, _book_names):
        key = (rag, cid)
        if key in lookup:
            continue
        lookup[key] = {"rag": rag, "id": cid, "title": title,
                       "body": body, "sim_q": sim_q, "sim_a": sim_a,
                       "util": util}
    import logging as _lg_bd
    if not lookup:
        _lg_bd.getLogger(__name__).info(
            "[cite_knowledge] manifest empty — no non-book knowledge chunks "
            f"(knowledge_selected size={len(knowledge_selected or [])}, "
            f"book_rags={sorted(_book_names)})")
    else:
        _lg_bd.getLogger(__name__).info(
            f"[cite_knowledge] manifest built — size={len(lookup)} "
            f"(from {len(knowledge_selected or [])} knowledge chunks)")
    return lookup


def _detect_used_chunks(service_info, user_info, session_id, session_name,
                         selector_agent_file, primary_response, chunk_lookup):
    """Second-pass LLM call that decides which chunks the primary answer
    actually referenced. Returns [(rag, cid, usage_note), ...] preserving
    the selector's order, dropping any (rag, cid) pair that doesn't map back
    to the manifest.

    The selector agent (SUPPORT_AGENT.KNOWLEDGE_USAGE_SELECTOR, defaults to
    agent_80DigiMKnowledgeUsageSelector.json) is a lightweight support
    agent. Its prompt template is `Knowledge Usage Selector` — mirrors the
    Insight-Old "参照した【知識情報】と参考にした点(箇条書き)" idea but is
    RAG-name-agnostic and returns structured JSON.

    Returns [] on any failure (missing agent, LLM error, parse error) so
    the caller falls through to the util-based fallback and Reference
    Knowledge still ends up populated when possible."""
    import logging as _lg_ku
    _log = _lg_ku.getLogger(__name__)
    if not chunk_lookup or not primary_response:
        return []
    if not selector_agent_file:
        selector_agent_file = "agent_80DigiMKnowledgeUsageSelector.json"
    try:
        selector = dma.DigiM_Agent(selector_agent_file)
        model_type = "LLM"
        practice_file = selector.agent["HABIT"]["DEFAULT"]["PRACTICE"]
        practice_path = Path(practice_folder_path) / practice_file
        try:
            practice = dmu.read_json_file(str(practice_path))
            first_chain = practice.get("CHAINS", [{}])[0]
            prompt_temp_cd = (first_chain.get("SETTING") or {}).get(
                "PROMPT_TEMPLATE", "Knowledge Usage Selector")
        except Exception:
            prompt_temp_cd = "Knowledge Usage Selector"
        prompt_template = selector.set_prompt_template(prompt_temp_cd)
    except Exception as _e:
        _log.warning(f"[cite_knowledge] selector agent load failed: {_e}")
        return []

    # Build the Retrieved Knowledge manifest the selector reads. Include ID
    # (the identifier it must return), RAG name, title, and a body preview
    # so it can judge whether content appears in the answer.
    from collections import defaultdict
    grouped = defaultdict(list)
    for meta in chunk_lookup.values():
        grouped[meta["rag"]].append(meta)
    manifest_lines = []
    for rag in sorted(grouped.keys()):
        manifest_lines.append(f"■ RAG: {rag}")
        for m in grouped[rag]:
            _body = (m.get("body") or "").replace("\n", " ")
            if len(_body) > 300:
                _body = _body[:300] + "..."
            manifest_lines.append(
                f"  - ID: {m['id']}\n"
                f"    タイトル: {m.get('title','')}\n"
                f"    本文抜粋: {_body}"
            )
    prompt = (
        f"{prompt_template}\n\n"
        f"【本回答】\n{primary_response}\n\n"
        f"【Retrieved Knowledge】\n" + "\n".join(manifest_lines) + "\n"
    )

    try:
        raw = ""
        for _p, chunk, _c in selector.generate_response(
                model_type, prompt, [], stream_mode=False):
            if chunk:
                raw += chunk
    except Exception as _e:
        _log.warning(f"[cite_knowledge] selector LLM call failed: {_e}")
        return []

    # Extract the JSON list from the response. Selector is instructed to
    # wrap in a ```json fence but be tolerant if it forgets.
    _json_fence_re = re.compile(
        r"```(?:json)?\s*(?P<body>\[.*?\])\s*```",
        re.DOTALL | re.IGNORECASE)
    m = _json_fence_re.search(raw or "")
    payload = m.group("body") if m else None
    if payload is None:
        # No fence — try to find a bare JSON array.
        m2 = re.search(r"(\[.*\])", raw or "", re.DOTALL)
        payload = m2.group(1) if m2 else "[]"
    import json as _json
    try:
        arr = _json.loads(payload)
    except Exception as _e:
        _log.warning(f"[cite_knowledge] selector JSON parse failed: {_e}; "
                     f"raw_tail={(raw or '')[-200:]!r}")
        return []
    if not isinstance(arr, list):
        return []
    entries = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        rag = str(item.get("rag", "")).strip()
        cid = str(item.get("ID", item.get("id", ""))).strip()
        usage = str(item.get("usage", "")).strip()
        if not rag or not cid:
            continue
        entries.append((rag, cid, usage))
    _log.info(f"[cite_knowledge] selector returned {len(entries)} entries "
              f"(manifest size={len(chunk_lookup)})")
    return entries


def _refresh_chunk_util(chunk_lookup, knowledge_selected):
    """Refresh sim_a / util in the lookup after the LLM's response has been
    embedded and similarity_response has been stamped into knowledge_selected
    by `get_knowledge_reference`. Lookup is keyed by (rag, id)."""
    if not chunk_lookup or not knowledge_selected:
        return
    by_key = {}
    def _f(v):
        try: return float(v) if v is not None else 0.0
        except (TypeError, ValueError): return 0.0
    for c in knowledge_selected:
        if isinstance(c, dict):
            rag = c.get("rag") or c.get("rag_name") or ""
            cid = str(c.get("id", "") or c.get("ID", "") or "")
            if not rag or not cid:
                continue
            by_key[(rag, cid)] = (
                _f(c.get("similarity_prompt", c.get("similarity_Q", 0.0))),
                _f(c.get("similarity_response", c.get("similarity_A", 0.0))),
            )
        elif isinstance(c, str):
            kv = dict(_KV_RE_CI.findall(c))
            nums = dict(_NUM_RE_CI.findall(c))
            rag = kv.get("rag", "")
            cid = kv.get("ID", "") or kv.get("id", "") or kv.get("page_id", "")
            if not rag or not cid:
                continue
            by_key[(rag, cid)] = (
                _f(nums.get("similarity_Q", nums.get("similarity_prompt", 0.0))),
                _f(nums.get("similarity_A", nums.get("similarity_response", 0.0))),
            )
    for key, meta in chunk_lookup.items():
        pair = by_key.get(key)
        if pair is None:
            continue
        sim_q, sim_a = pair
        meta["sim_q"] = sim_q
        meta["sim_a"] = sim_a
        meta["util"] = sim_q - sim_a


def _sanitize_reference_snippet(text, max_len=60):
    """Flatten a book/knowledge snippet so it fits on one bullet line.

    Book snippets are raw chunk bodies — they can contain markdown headers
    (`# ...`), tables (`| ... |`), fenced code blocks, bullet lists and
    embedded newlines. Left as-is, they poison the Reference Info block
    (each snippet renders as a nested heading + table, splitting the
    numbered list). This helper strips the structural markers and
    collapses whitespace so the snippet reads as a short prose fragment."""
    if not text:
        return ""
    s = str(text)
    # Drop fenced code / mermaid blocks entirely — they'd render as a
    # multi-line code box under the reference list.
    s = re.sub(r"```.*?```", " ", s, flags=re.DOTALL)
    # Strip leading heading / bullet / blockquote markers per line.
    s = re.sub(r"(^|\n)\s*(#+|>|\-|\*|\+|\d+\.)\s+", r"\1", s)
    # Table pipes → visual dividers.
    s = s.replace("|", " ")
    # Collapse any remaining whitespace (newlines, tabs, runs of spaces).
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[:max_len].rstrip() + "..."
    return s


def _build_plain_references_block(sources):
    """Same shape citation_inject._build_references_block produces, inlined
    here so the outer code can append it without depending on tool-plugin
    import paths. Empty when there are no citable sources.

    Dedup: web by URL, book by (rag_name, title). Ordering follows the input
    list — matches whatever call site already prioritised."""
    if not sources:
        return ""
    seen = set()
    lines = []
    for s in sources:
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
            lines.append(f"(web) {url}" + (f" - {title}" if title else ""))
        elif kind == "book":
            rag_name = (s.get("rag_name") or "").strip()
            title = (s.get("title") or "").strip()
            if not title:
                continue
            key = ("book", rag_name, title)
            if key in seen:
                continue
            seen.add(key)
            # Belt-and-suspenders sanitize (upstream _ci_sources build
            # already applied this, but the plain-references path is also
            # called by the WebUI skill fallback which builds sources with
            # raw snippets).
            snippet = _sanitize_reference_snippet(
                s.get("snippet") or "", max_len=60)
            tag = f"(book: {rag_name})" if rag_name else "(book)"
            parts = [tag, title]
            if snippet:
                parts.append("— " + snippet)
            lines.append(" ".join(parts))
    if not lines:
        return ""
    return "## Reference Info\n" + "\n".join(
        f"[{i}] {lbl}" for i, lbl in enumerate(lines, 1))


def _build_util_fallback_entries(chunk_lookup):
    """Fallback when the second-pass selector returned nothing.

    One representative from EVERY RAG in the manifest (best util within
    each RAG), ordered by util descending. Returns list of (rag, id, note)
    triples matching the selector output shape."""
    if not chunk_lookup:
        return []
    from collections import defaultdict
    by_rag = defaultdict(list)
    for meta in chunk_lookup.values():
        by_rag[meta.get("rag", "")].append(meta)
    picked = []
    for rag, items in by_rag.items():
        best = max(items, key=lambda m: m.get("util", 0.0))
        picked.append(best)
    picked.sort(key=lambda m: -m.get("util", 0.0))
    return [(m.get("rag", ""), m.get("id", ""), "(auto: 選定エージェント未実行)")
            for m in picked]


def _build_knowledge_section(entries, chunk_lookup, title_cap=20,
                              note_cap=30):
    """Assemble the ## Reference Knowledge section from the selector output.

    entries       — list of (rag, id, usage_note) from _detect_used_chunks
                    or _build_util_fallback_entries.
    chunk_lookup  — {(rag, id): {rag, id, title, util, ...}} from
                    _build_cite_knowledge_manifest.

    Format per line:
        - (RAG_NAME)Title-truncated: note-truncated

    (The Knowledge Utility score is intentionally omitted here — the
    numeric value routed via the manifest didn't reliably correspond to
    the actual chunk the selector picked, so showing it was misleading.
    The util is still stored in the debug dict for [Reference Knowledge
    Debug] in Detail Information if needed.)

    Entries whose (rag, id) doesn't map back to the manifest are dropped
    silently — the selector occasionally hallucinates an ID, and showing
    those rows confused the user more than it helped. If every entry
    drops, the whole section is suppressed (returns ""); the caller must
    NOT emit a bare header in that case."""
    import logging as _lg_ks
    if not entries:
        return ""
    lines = []
    dropped = 0
    for rag, cid, note in entries:
        meta = chunk_lookup.get((rag, cid))
        if meta is None:
            dropped += 1
            continue
        display_rag = meta.get("rag", rag)
        display_title = meta.get("title", cid)
        _t = display_title[:title_cap] + "..." if len(display_title) > title_cap else display_title
        _n = (note or "").replace("\n", " ").strip()
        if len(_n) > note_cap:
            _n = _n[:note_cap] + "..."
        lines.append(f"- ({display_rag}){_t}: {_n}")
    _lg_ks.getLogger(__name__).info(
        f"[cite_knowledge] emitting {len(lines)} rows "
        f"({len(entries) - dropped}/{len(entries)} matched against manifest of "
        f"{len(chunk_lookup)} chunks; {dropped} dropped as unmatched)")
    if not lines:
        return ""
    return "## Reference Knowledge\n" + "\n".join(lines)

# B-3: Common USER_INPUT resolution
def _resolve_user_input(user_input_setting, user_query, results):
    inputs = user_input_setting if isinstance(user_input_setting, list) else [user_input_setting]
    user_input = ""
    for item in inputs:
        if item == "USER":
            user_input += user_query
        elif item.startswith("INPUT"):
            ref_subseq = int(item.replace("INPUT_", "").strip())
            user_input += next((r["INPUT"] for r in results if r["SubSEQ"] == ref_subseq), "")
        elif item.startswith("OUTPUT"):
            ref_subseq = int(item.replace("OUTPUT_", "").strip())
            user_input += next((r["OUTPUT"] for r in results if r["SubSEQ"] == ref_subseq), "")
        else:
            user_input += item
    return user_input

# B-3: Common content resolution
def _resolve_contents(contents_setting, in_contents, results):
    if contents_setting == "USER":
        return in_contents
    if isinstance(contents_setting, str) and contents_setting.startswith("IMPORT_"):
        ref_subseq = int(contents_setting.replace("IMPORT_", "").strip())
        return next((r["IMPORT_CONTENTS"] for r in results if r["SubSEQ"] == ref_subseq), [])
    if isinstance(contents_setting, str) and contents_setting.startswith("EXPORT_"):
        ref_subseq = int(contents_setting.replace("EXPORT_", "").strip())
        return next((r["EXPORT_CONTENTS"] for r in results if r["SubSEQ"] == ref_subseq), [])
    return contents_setting

# B-4: RAG search-query generation phase (parallelization hook in C-1)
def _build_intent_queries(service_info, user_info, session_id, session_name, support_agent,
                          user_query, memories_selected, situation_prompt, query_vec, RAG_query_gene,
                          rag_query_hint="", user_memory_context="", memory_use=True):
    """Generate the RAG search query (intent) and return extra queries, vectors, and logs."""
    if not (RAG_query_gene and "RAG_QUERY_GENERATOR" in support_agent):
        return [], [], {}
    t_start = datetime.now()
    # Append the hint from Thinking to the query, if any
    _query = user_query
    if rag_query_hint:
        _query = _query + "\n\n【RAG検索のヒント】\n" + rag_query_hint
    # If user memory is enabled, also include the partner's profile in the query-generation context
    if user_memory_context:
        _query = _query + "\n\n" + user_memory_context.strip()
    # Propagate memory_use so the tool can drop the "use dialog history" prompt
    # instruction when the WebUI Memory Use toggle is off (benchmark mode).
    add_info = {"Memories_Selected": memories_selected, "Situation": situation_prompt,
                "QueryVecs": [query_vec], "MemoryUse": bool(memory_use)}
    agent_file = support_agent["RAG_QUERY_GENERATOR"]
    _, _, response, model_name, prompt_tokens, response_tokens = dmt.call_function_by_name(
        service_info, user_info, "RAG_query_generator",
        session_id, session_name, agent_file, _query, [], add_info)
    vec = dmu.embed_text(response.replace("\n", ""))
    duration = round((datetime.now() - t_start).total_seconds(), 2)
    log = {"agent_file": agent_file, "model": model_name, "llm_response": response,
           "rag_query_hint": rag_query_hint,
           "prompt_token": prompt_tokens, "response_token": response_tokens, "duration_sec": duration}
    return [response], [vec], log

# B-4: Metadata search phase (parallelization hook in C-1)
def _build_meta_searches(service_info, user_info, session_id, session_name, support_agent,
                         user_query, memories_selected, situation_prompt, query_vec, meta_search):
    """Retrieve metadata search info from the query."""
    if not (meta_search and "EXTRACT_DATE" in support_agent):
        return [], {}
    t_start = datetime.now()
    add_info = {"Memories_Selected": memories_selected, "Situation": situation_prompt, "QueryVecs": [query_vec]}
    agent_file = support_agent["EXTRACT_DATE"]
    _, _, response, model_name, prompt_tokens, response_tokens = dmt.call_function_by_name(
        service_info, user_info, "extract_date",
        session_id, session_name, agent_file, user_query, [], add_info)
    date_list = dmu.merge_periods(dmu.extract_list_pattern(response))
    duration = round((datetime.now() - t_start).total_seconds(), 2)
    log = {"date": {"agent_file": agent_file, "model": model_name, "condition_list": date_list,
                    "llm_response": response, "prompt_token": prompt_tokens, "response_token": response_tokens,
                    "duration_sec": duration}}
    return [{"DATE": date_list}], log

# B-4: Run Thinking Agent (analyze the question and decide execution parameters)
def _run_thinking_agent(service_info, user_info, session_id, session_name,
                        support_agent, agent, user_query, digest_text, situation_prompt,
                        previous_thinking=None, web_search_preview=""):
    """Run Thinking Agent and return the decision JSON and logs.

    When called inside a multi-turn Thinking loop (`MAX_THINKING_TURNS>1`),
    `previous_thinking` carries the prior turn's decision dict and
    `web_search_preview` carries the raw text of the mid-loop preview
    search (empty on turn 1). Both are injected into the Thinking prompt
    via `{PreviousThinking}` / `{WebSearchPreview}` placeholders so the
    agent can reconsider its judgement in light of what a search would
    actually surface."""
    import json as _json
    if "THINKING" not in support_agent:
        return {}, {}
    t_start = datetime.now()

    # Format the habit list. When a HABIT entry defines PURPOSE (short prose
    # describing when to choose it), pass that to Thinking as the primary
    # signal — MAGIC_WORDS remain the user-facing trigger phrases but they
    # are terse and don't describe when the habit is appropriate. Fall back
    # to MAGIC_WORDS so HABIT entries authored before PURPOSE existed keep
    # working unchanged.
    habit_info = ""
    for habit_key, habit_val in agent.habit.items():
        _purpose = (habit_val.get("PURPOSE") or "").strip()
        if _purpose:
            habit_info += f"- {habit_key}: {_purpose}\n"
        else:
            desc = ", ".join(habit_val.get("MAGIC_WORDS", []))
            habit_info += f"- {habit_key}: {desc}\n"

    # Format the book list. When a BOOK entry defines PURPOSE (short prose
    # describing when to consult it), pass that to Thinking so RAG_NAME alone
    # isn't the only judgement signal — otherwise fall back to the name only
    # so BOOK entries authored before PURPOSE existed keep working unchanged.
    book_info = ""
    for book in agent.agent.get("BOOK", []):
        _purpose = (book.get("PURPOSE") or "").strip()
        if _purpose:
            book_info += f"- {book['RAG_NAME']}: {_purpose}\n"
        else:
            book_info += f"- {book['RAG_NAME']}\n"

    # Serialize previous_thinking for the LLM (compact reasoning + key
    # decisions — the full raw dict is noisy). Falls back to empty when
    # this is the first turn.
    _prev_snippet = ""
    if previous_thinking and isinstance(previous_thinking, dict):
        _keep = ("reasoning", "habit", "web_search", "web_search_engine",
                 "web_search_query", "rag_query_gene", "rag_query_hint",
                 "books", "sufficient")
        _prev_snippet = _json.dumps(
            {k: previous_thinking[k] for k in _keep if k in previous_thinking},
            ensure_ascii=False, indent=2)

    add_info = {
        "Situation": situation_prompt,
        "DigestText": digest_text,
        "HabitInfo": habit_info,
        "BookInfo": book_info,
        "PreviousThinking": _prev_snippet,
        "WebSearchPreview": web_search_preview or "",
    }
    agent_file = support_agent["THINKING"]
    _, _, response, model_name, prompt_tokens, response_tokens = dmt.call_function_by_name(
        service_info, user_info, "thinking_agent",
        session_id, session_name, agent_file, user_query, [], add_info)

    # Extract JSON from the response
    result = {}
    reasoning = response
    try:
        # If a ```json ... ``` block exists, extract its content
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        json_str = json_match.group(1) if json_match else response
        result = _json.loads(json_str)
        reasoning = result.get("reasoning", response)
    except (_json.JSONDecodeError, AttributeError):
        pass

    duration = round((datetime.now() - t_start).total_seconds(), 2)
    log = {
        "agent_file": agent_file, "model": model_name,
        "reasoning": reasoning, "result": result,
        "prompt_token": prompt_tokens, "response_token": response_tokens,
        "duration_sec": duration
    }
    return result, log

# Phase 6/7: Resolve chain.PERSONAS into a list of real persona dicts
# WEB_UI: use in_personas (currently selected in the UI) as-is
# THINKING: read pre-selected results from execution["_THINKING_RESULT"]["personas"] (chosen by PersonaSelector)
# list: resolve the persona_id list via DigiM_AgentPersona
def _resolve_step_personas(chain_personas, in_personas, in_agent_file, execution=None):
    if not chain_personas:
        return []
    if isinstance(chain_personas, str):
        upper = chain_personas.upper()
        if upper == "WEB_UI":
            return list(in_personas or [])
        if upper == "THINKING":
            # Reference the list finalized by the persona selection at the Practice head
            thinking = (execution or {}).get("_THINKING_RESULT", {}) or {}
            picked = thinking.get("personas") or []
            if picked:
                return list(picked)
            # Fallback: UI selection
            return list(in_personas or [])
        return []
    if isinstance(chain_personas, list):
        try:
            import DigiM_AgentPersona as dap
        except Exception:
            return []
        try:
            all_p = dap.load_personas(template_agent=in_agent_file)
        except Exception:
            return []
        by_id = {p.get("persona_id"): p for p in all_p}
        return [by_id[pid] for pid in chain_personas if pid in by_id]
    return []


# Phase 6: build user input in include_query form ([Each persona's previous responses] + [Current question])
def _format_persona_responses_as_query(persona_responses, user_query):
    blobs = []
    for r in persona_responses:
        name = r.get("persona_name") or "?"
        text = r.get("text") or ""
        if text:
            blobs.append(f"- {name}:\n{text}")
    if not blobs:
        return user_query
    return ("[前回の各ペルソナの回答]\n" + "\n\n".join(blobs)
            + "\n\n[今回の質問]\n" + (user_query or ""))


# Phase 6: Apply the PERSONA_MERGE strategy and return the merged text
# methods: "summary" / "concat" / "first" / "include_query" / "none"
def _apply_persona_merge(merge_method, persona_responses, user_query, merge_level,
                        service_info, user_info, session_id, session_name, support_agent):
    method = (merge_method or "summary").lower()
    if method == "first":
        return persona_responses[0].get("text", "") if persona_responses else ""
    if method in ("concat", "none"):
        return "\n\n".join(
            f"【{r.get('persona_name','?')}】\n{r.get('text','')}"
            for r in persona_responses if r.get("text")
        )
    if method == "include_query":
        return _format_persona_responses_as_query(persona_responses, user_query)
    if method == "summary":
        merge_agent = (support_agent or {}).get("PERSONA_MERGE", "agent_50PersonaMerge.json")
        try:
            _, _, merged, _, _, _ = dmt.call_function_by_name(
                service_info, user_info, "dialog_persona_merge",
                session_id, session_name,
                merge_agent, user_query, persona_responses, summary_level=merge_level,
            )
            return merged
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(f"persona_merge failed (falling back to concat): {e}")
            return "\n\n".join(
                f"【{r.get('persona_name','?')}】\n{r.get('text','')}"
                for r in persona_responses if r.get("text")
            )
    return ""


# Run digest generation / save / unlock in the background
def _run_digest_background(session, service_info, user_info, session_id, session_name,
                            support_agent, memories_selected,
                            seq, sub_seq, cfg, unlock_on_complete=True):
    try:
        dialog_digest_agent_file = support_agent.get("DIALOG_DIGEST", "")
        add_info = {}
        add_info["Memories_Selected"] = memories_selected
        timestamp_digest_start = str(datetime.now())
        _, _, digest_response, digest_model_name, _, digest_response_tokens = dmt.call_function_by_name(
            service_info, user_info, "dialog_digest",
            session_id, session_name, dialog_digest_agent_file, "", [], add_info)
        timestamp_digest = str(datetime.now())
        digest_vec_file = ""
        if cfg["memory_similarity"]:
            digest_vec = dmu.embed_text(digest_response.replace("\n", ""))
            digest_vec_file = session.save_vec_file(str(seq), str(sub_seq), "digest", digest_vec)
        digest_chat_dict = {
            "agent_file": dialog_digest_agent_file, "model": digest_model_name,
            "role": "assistant",
            "timestamp_start": timestamp_digest_start, "timestamp": timestamp_digest,
            "token": digest_response_tokens, "text": digest_response,
            "vec_file": digest_vec_file
        }
        session.save_history_batch(str(seq), {str(sub_seq): {"digest": digest_chat_dict}})
    except Exception as e:
        import logging
        # Full traceback so the actual cause (e.g. missing SUPPORT_AGENT file) is visible.
        logging.getLogger(__name__).exception(f"Background digest generation failed: {e}")
        # Mirror to per-session + global rotated error logs so this isn't swallowed silently.
        _ctx = {"phase": "digest_background", "session_id": session_id,
                "session_name": session_name, "seq": seq, "sub_seq": sub_seq,
                "dialog_digest_agent_file": (support_agent or {}).get("DIALOG_DIGEST", "")}
        try:
            dms.save_global_error_log(e, context=_ctx)
        except Exception:
            pass
        try:
            session.save_error_log(e, context=_ctx)
        except Exception:
            pass
    finally:
        if unlock_on_complete:
            session.save_status("UNLOCKED")

# Function for one-shot execution
def DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type="LLM",
                     sub_seq=1, user_input="", contents=[], situation={}, overwrite_items={},
                     add_knowledge=[], prompt_temp_cd="", execution={}, seq_limit="", sub_seq_limit="",
                     persona=None, rag_query_text=""):
    export_files = []
    output_reference = {}
    timestamp_begin = str(datetime.now())
    timestamp_log = "[01.Execution start (session setup)]" + str(datetime.now()) + "<br>"

    # B-2: Load execution settings
    cfg = _parse_execution_settings(execution)

    # Declare the session
    _session_base_path = execution.get("_SESSION_BASE_PATH", "")
    session = dms.DigiMSession(session_id, session_name, base_path=_session_base_path)
    # seq prefers execution["_SEQ_OVERRIDE"] when set (avoids races during multi-persona parallel execution)
    _seq_override = execution.get("_SEQ_OVERRIDE")
    if _seq_override is not None:
        seq = _seq_override
    else:
        seq = session.get_seq_history() + 1 if sub_seq == 1 else session.get_seq_history()

    # Declare the agent (apply persona override if specified)
    timestamp_log += "[02.Agent setup start]" + str(datetime.now()) + "<br>"
    agent = dma.DigiM_Agent(agent_file, persona=persona)
    if overwrite_items:
        dmu.update_dict(agent.agent, overwrite_items)
        agent.set_property(agent.agent)

    # Build content context
    contents_context = ""
    contents_records = []
    image_files = {}
    if contents:
        timestamp_log += "[03.Content-context loading start]" + str(datetime.now()) + "<br>"
        contents_context, contents_records, image_files = agent.set_contents_context(seq, sub_seq, contents)

    user_query = user_input + contents_context
    digest_text = ""
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    query_tokens = dmu.count_token(tokenizer, model_name, user_query)
    system_tokens = dmu.count_token(tokenizer, model_name, agent.system_prompt)

    # Set up the situation
    timestamp_log += "[04.Situation setup]" + str(datetime.now()) + "<br>"
    situation_prompt = ""
    if situation:
        situation_setting = situation.get("SITUATION", "") + "\n" if "SITUATION" in situation else ""
        time_setting = situation.get("TIME", "")
        if time_setting:
            # Add a stronger directive when the datetime form is non-standard (fictional setting)
            is_standard = False
            try:
                datetime.strptime(time_setting, "%Y/%m/%d %H:%M:%S")
                is_standard = True
            except (ValueError, TypeError):
                pass
            if is_standard:
                situation_prompt = f"\n【状況】\n{situation_setting}現在は「{time_setting}」です。"
            else:
                situation_prompt = f"\n【重要な状況設定】\n{situation_setting}この会話では、現在の日時は「{time_setting}」として設定されています。会話履歴やシステム上の実際の日時に関わらず、必ずこの設定に従ってください。実際の日時には一切言及しないでください。"
        elif situation_setting.strip():
            situation_prompt = f"\n【状況】\n{situation_setting}"

    # Support-agent situation (Thinking / RAG Query Generator / Extract Date,
    # ...). Falls back to the current real date when the parent's TIME is
    # empty ("No Date"). Support agents need date awareness to judge
    # freshness ("recent" / "current") and generate meta-search date ranges even
    # when the main-response persona intentionally omits date grounding.
    _sup_sit = dict(situation or {})
    if not _sup_sit.get("TIME"):
        _sup_sit["TIME"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    _sup_setting = _sup_sit.get("SITUATION", "")
    _sup_setting = _sup_setting + "\n" if _sup_setting else ""
    _sup_time = _sup_sit["TIME"]
    try:
        datetime.strptime(_sup_time, "%Y/%m/%d %H:%M:%S")
        situation_prompt_support = f"\n【状況】\n{_sup_setting}現在は「{_sup_time}」です。"
    except (ValueError, TypeError):
        situation_prompt_support = f"\n【重要な状況設定】\n{_sup_setting}この会話では、現在の日時は「{_sup_time}」として設定されています。会話履歴やシステム上の実際の日時に関わらず、必ずこの設定に従ってください。実際の日時には一切言及しないでください。"

    # Read the conversation digest
    if cfg["memory_use"]:
        timestamp_log += "[05.Conversation-digest loading start]" + str(datetime.now()) + "<br>"
        if session.chat_history_active_dict:
            if seq_limit or sub_seq_limit:
                _, _, chat_history_digest_dict = session.get_history_digest(seq_limit, sub_seq_limit)
            else:
                _, _, chat_history_digest_dict = session.get_history_max_digest()
            if chat_history_digest_dict:
                digest_text = "会話履歴のダイジェスト:\n" + chat_history_digest_dict["text"] + "\n---\n"

    # Read the Thinking log (when passed through via Practice)
    thinking_log = execution.get("_THINKING_LOG", {})

    # Run web search
    web_context = ""
    web_search_log = {}
    if cfg["web_search"]:
        session.save_status_message("Starting web search")
        yield service_info, user_info, "[STATUS]Starting web search", [], []
        timestamp_log += "[06.Web search start]" + str(datetime.now()) + "<br>"
        # Prefer the Thinking-generated web search query, if any
        _thinking_result = execution.get("_THINKING_RESULT", {})
        _web_search_query = _thinking_result.get("web_search_query", "")
        if _web_search_query:
            search_text = "検索して欲しい内容:\n" + _web_search_query + "\n\n[参考]元の質問:\n" + user_query
        elif digest_text or situation_prompt:
            search_text = "検索して欲しい内容:\n" + user_query + "\n\n[参考]これまでの会話:\n" + digest_text + "\n\n[参考]今の状況:\n" + situation_prompt
        else:
            search_text = user_query
        _setting = system_setting_dict
        web_engine = cfg["web_search_engine"] or _setting.get("WEB_SEARCH_DEFAULT", "Perplexity")
        _web_model_map = {
            "Perplexity": _setting.get("PERPLEXITY_MODEL", "sonar"),
            "OpenAI": _setting.get("OPENAI_SEARCH_MODEL", "gpt-4.1-mini"),
            "Google": _setting.get("GOOGLE_SEARCH_MODEL", "gemini-2.5-flash"),
        }
        web_model = _web_model_map.get(web_engine, "")
        # Multi-turn Thinking's preview action stashes a completed search
        # here. Reuse it when the engine + search_text match to avoid a
        # duplicate API call (the same query would return the same result
        # anyway, and Web search is the most expensive step in the pipeline).
        _wsc = execution.get("_WEB_SEARCH_CACHE") or {}
        _cache_hit = (_wsc.get("engine") == web_engine
                      and _wsc.get("search_text") == search_text
                      and _wsc.get("result_text") is not None)
        if _cache_hit:
            web_result_text = _wsc["result_text"]
            export_urls = _wsc.get("urls") or []
            web_duration = float(_wsc.get("duration_sec") or 0.0)
        else:
            t_web_start = datetime.now()
            _, _, web_result_text, export_urls = dmt.call_function_by_name(
                service_info, user_info, "WebSearch",
                session_id, session_name, agent_file, search_text, [], {}, engine=web_engine)
            web_duration = round((datetime.now() - t_web_start).total_seconds(), 2)
        # Guardrails around the raw search text — LLMs tend to over-defer to
        # large chunks of external text (tone drifts, conversation context is
        # forgotten). Wrapping the snippet with "this is reference material,
        # your persona and the running dialogue take priority" measurably
        # improves grounding, at a cost of a few dozen prompt tokens.
        # Toggleable via cfg["web_search_guardrail"] — off passes the raw
        # snippet through unwrapped, for callers who want the search result
        # to speak for itself.
        if cfg.get("web_search_guardrail", True):
            web_context = (
                "\n[Reference material — Web search result (start)]\n"
                "Treat the block below as reference only. Follow these rules strictly:\n"
                "- Do not copy the text verbatim; do not drift into a summary tone.\n"
                "- Tone, vocabulary, and perspective must follow your own persona.\n"
                "- The running conversation and the user's intent come first; weave in only the facts you need.\n"
                "- You may use only a portion of the material and ignore the rest.\n"
                "---\n"
                + web_result_text +
                "\n---\n[Reference material END]\n"
            )
        else:
            web_context = "\n" + web_result_text + "\n"
        web_search_log = {"engine": web_engine, "model": web_model, "duration_sec": web_duration, "search_text": search_text, "urls": export_urls, "web_context": web_context}
        timestamp_log += f"[06.Web search done ({web_engine}/{web_model}, {web_duration}s)]" + str(datetime.now()) + "<br>"
    output_reference["Web_search"] = web_search_log
    user_query += f"\n{web_context}"

    # Vectorize the query (C-3: batch embedding)
    timestamp_log += "[07.Query vectorization start]" + str(datetime.now()) + "<br>"
    queries = [user_query]
    if digest_text or situation_prompt:
        user_query_ds = digest_text + user_query + situation_prompt
        queries.append(user_query_ds)
    query_vecs = dmu.embed_texts_batch([q.replace("\n", "") for q in queries])
    query_vec = query_vecs[0]

    # Run conversation memory / RAG query generation / meta search in parallel
    timestamp_log += "[08-10.Conversation memory / RAG search query / meta search (parallel)]" + str(datetime.now()) + "<br>"
    memory_limit_tokens = agent.agent["ENGINE"][model_type]["MEMORY"]["limit"]
    if model_type != "LLM":
        memory_limit_tokens -= (system_tokens + query_tokens)
    memory_role = agent.agent["ENGINE"][model_type]["MEMORY"]["role"]
    memory_priority = agent.agent["ENGINE"][model_type]["MEMORY"]["priority"]
    memory_similarity_logic = agent.agent["ENGINE"][model_type]["MEMORY"]["similarity_logic"]
    memory_digest = agent.agent["ENGINE"][model_type]["MEMORY"]["digest"]
    support_agent = agent.agent["SUPPORT_AGENT"]

    # Compose user-memory layers into the "About the dialogue partner" context.
    # Built before RAG query generation so that user memory is included in the generator's input text.
    # Skipped for IMAGEGEN because the 3000-char image prompt limit otherwise saturates.
    # Priority: execution["USER_MEMORY_LAYERS"] (immediate UI override) > user master > system default
    user_memory_context = ""
    user_memory_used = []
    user_memory_meta = {"history_keywords": []}
    if cfg["memory_use"] and model_type == "LLM":
        try:
            _svc_id = (service_info or {}).get("SERVICE_ID", "")
            _usr_id = (user_info or {}).get("USER_ID", "")
            _override_layers = execution.get("USER_MEMORY_LAYERS")
            if _override_layers is not None:
                # Immediate UI override (empty list is also respected = all off)
                import DigiM_UserMemory as _dmum_local
                _active_layers = [l for l in _override_layers if l in _dmum_local.LAYERS]
            else:
                _active_layers = dmus.resolve_active_layers(_usr_id)
            if _active_layers:
                user_memory_context, user_memory_used, user_memory_meta = dmumb.build_context_text(
                    _svc_id, _usr_id, _active_layers, query_text=user_query,
                )
        except Exception as _um_err:
            timestamp_log += f"[user_memory composition failed: {_um_err}]" + str(datetime.now()) + "<br>"

    need_intent = cfg["RAG_query_gene"] and "RAG_QUERY_GENERATOR" in support_agent
    need_meta = cfg["meta_search"] and "EXTRACT_DATE" in support_agent
    if need_intent or need_meta:
        session.save_status_message("Starting RAG search-query generation")
        yield service_info, user_info, "[STATUS]Starting RAG search-query generation", [], []

    with ThreadPoolExecutor(max_workers=3) as executor:
        # Kick off memory retrieval in parallel
        future_memory = None
        if cfg["memory_use"]:
            future_memory = executor.submit(
                session.get_memory, query_vec, model_name, tokenizer, memory_limit_tokens,
                memory_role, memory_priority, cfg["memory_similarity"],
                memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
        # Kick off RAG query generation in parallel (pass the Thinking hint if any)
        # When include_query etc. has prefixed user_input with prior persona responses,
        # use rag_query_text (= original user input) for RAG / meta search when provided.
        _rag_input_text = rag_query_text if rag_query_text else user_query
        _thinking_result = execution.get("_THINKING_RESULT", {})
        _rag_query_hint = _thinking_result.get("rag_query_hint", "")
        future_intent = executor.submit(
            _build_intent_queries, service_info, user_info, session_id, session_name,
            support_agent, _rag_input_text, [], situation_prompt_support, query_vec, cfg["RAG_query_gene"],
            _rag_query_hint, user_memory_context, cfg["memory_use"])
        # Kick off meta search in parallel
        future_meta = executor.submit(
            _build_meta_searches, service_info, user_info, session_id, session_name,
            support_agent, _rag_input_text, [], situation_prompt_support, query_vec, cfg["meta_search"])

        memories_selected = future_memory.result() if future_memory else []
        intent_queries, intent_vecs, RAG_query_gene_log = future_intent.result()
        meta_searches, meta_search_log = future_meta.result()

    intent_dur = RAG_query_gene_log.get("duration_sec", "-") if RAG_query_gene_log else "-"
    meta_dur = meta_search_log.get("date", {}).get("duration_sec", "-") if meta_search_log else "-"
    timestamp_log += f"[08-10 done: memory / RAG query ({intent_dur}s) / meta search ({meta_dur}s)]" + str(datetime.now()) + "<br>"
    queries += intent_queries
    query_vecs += intent_vecs
    output_reference["RAG_query_gene_log"] = RAG_query_gene_log
    output_reference["meta_search"] = meta_search_log

    # Build the RAG context
    timestamp_log += "[11.RAG start]" + str(datetime.now()) + "<br>"
    session.save_status_message("Starting RAG")
    yield service_info, user_info, "[STATUS]Starting RAG", [], []
    if add_knowledge:
        agent.knowledge += add_knowledge
    # AgentSearch / FunctionSearch need session + parent agent_file to call
    # downstream Practice / tool registry. The AgentSearch counter is shared
    # across the whole request — seed it from in_execution (set by an upstream
    # AgentSearch retriever) or initialise from the agent's root default.
    exec_info = {"SERVICE_INFO": service_info, "USER_INFO": user_info,
                  "_SESSION_ID": session_id, "_SESSION_NAME": session_name,
                  "_AGENT_FILE": agent_file,
                  # Full list of queries the retriever should consider: the
                  # user's raw query, digest+situation-augmented variant, and
                  # the RAG_QUERY_GENERATOR output. Graph retrieval iterates
                  # all of them for seed detection; Vector retrieval already
                  # uses the parallel query_vecs list.
                  "_QUERIES": list(queries)}
    if execution.get("_AGENT_SEARCH_STATE") is not None:
        exec_info["_AGENT_SEARCH_STATE"] = execution["_AGENT_SEARCH_STATE"]
    else:
        try:
            _ag_max = int(agent.agent.get("AGENT_SEARCH_MAX_CALLS", 3))
        except (TypeError, ValueError):
            _ag_max = 3
        exec_info["_AGENT_SEARCH_STATE"] = {"calls": 0, "max": _ag_max}
    knowledge_context, knowledge_selected = agent.set_knowledge_context(
        user_query, query_vecs, exec_info, meta_searches, private_mode=cfg["private_mode"])
    # Graph retrieval stashes seed provenance for the Detail Information
    # [Seed for Graph] panel and the Analytics Results Graph header.
    graph_seed_traces = exec_info.get("_GRAPH_SEED_TRACES") or {}
    output_reference["graph_seed_traces"] = graph_seed_traces

    # Set up the prompt template and query
    timestamp_log += "[12.Prompt template setup]" + str(datetime.now()) + "<br>"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Session-summary context block. Optional per-session dossier that the
    # operator maintains via the WebUI. Only injected when the feature is
    # enabled AND content exists — behaviour is identical to the previous
    # release for sessions without the toggle turned on.
    session_summary_context = ""
    try:
        _ss_enabled, _ss_template, _ss_content, _ss_updated_at = (
            session.get_session_summary()
        )
    except Exception:
        _ss_enabled, _ss_template, _ss_content, _ss_updated_at = False, "", "", ""
    if _ss_enabled and _ss_content:
        session_summary_context = (
            "\n[Current Session Summary]\n"
            "(Confirmed facts about this session so far. Prefer these values "
            "when they conflict with other retrieved context.)\n\n"
            f"{_ss_content}\n\n"
            "---\n"
        )

    # Formatting instructions ride at the tail so they apply to the whole turn
    # without displacing the persona/template voice set above.
    _format_prompt = DIAGRAM_INSTRUCTION if cfg.get("diagram_mode") else ""
    _format_prompt += EMPHASIS_INSTRUCTION if cfg.get("emphasis_mode") else ""

    # Cite-knowledge manifest: pre-build the (rag, id) -> meta lookup of
    # every non-book chunk in this turn. The primary prompt no longer
    # carries a self-declaration directive — a dedicated second-pass
    # selector agent (SUPPORT_AGENT.KNOWLEDGE_USAGE_SELECTOR) decides
    # which chunks were used after the primary answer is produced.
    _cite_chunk_lookup = {}
    if cfg.get("cite_knowledge") and model_type == "LLM":
        _cite_chunk_lookup = _build_cite_knowledge_manifest(
            knowledge_selected, agent.agent)

    if model_type == "LLM":
        # Order: Session summary -> Dialogue partner info -> Knowledge ->
        #        Template -> User query -> Situation
        # Summary sits above user_memory because it captures session-scoped
        # confirmed facts that should override generic memory retrieval.
        query = (
            f'{session_summary_context}{user_memory_context}{knowledge_context}'
            f'{prompt_template}{user_query}{situation_prompt}{_format_prompt}'
        )
    else:
        query = f'{prompt_template}{user_query}{situation_prompt}{_format_prompt}'
    output_reference["prompt"] = {
        "query": query, "user_query": user_query, "contents_context": contents_context,
        "web_context": web_context, "knowledge_context": knowledge_context,
        "prompt_template": prompt_template, "situation_prompt": situation_prompt,
        "memories_selected": memories_selected,
        "user_memory_context": user_memory_context,
        "user_memory_used": user_memory_used,
        "user_memory_meta": user_memory_meta,
        "session_summary_context": session_summary_context,
        "session_summary_enabled": _ss_enabled,
    }

    # Execute the LLM
    prompt = ""
    response = ""
    completion = []
    session.save_status_message("Running LLM")
    timestamp_log += "[13.LLM execution start]" + str(datetime.now()) + "<br>"
    response_service_info = {}
    response_user_info = {}
    _last_stream_flush = time.time()
    _STREAM_FLUSH_INTERVAL = 2  # Pseudo-streaming flush interval (seconds)
    for prompt, response_chunk, completion in agent.generate_response(
            model_type, query, memories_selected, image_files, cfg["stream_mode"]):
        if response_chunk:
            response += response_chunk
            response_service_info = service_info
            response_user_info = user_info
            yield response_service_info, response_user_info, response_chunk, export_files, knowledge_selected
            # Pseudo-streaming: periodically write the response into the status
            if cfg["stream_mode"] and time.time() - _last_stream_flush >= _STREAM_FLUSH_INTERVAL:
                session.save_status_message("Running LLM", response=response)
                _last_stream_flush = time.time()
    timestamp_end = str(datetime.now())
    timestamp_log += "[14.LLM execution done]" + str(datetime.now()) + "<br>"

    # Sanitize response text (strip control characters)
    response = dmu.sanitize_text(response)

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) if prompt else 0
    response_tokens = dmu.count_token(tokenizer, model_name, response) if response else 0

    # Similarity evaluation
    timestamp_log += "[15.Result similarity calculation start]" + str(datetime.now()) + "<br>"
    response_vec = dmu.embed_text(response.replace("\n", "")[:8000])
    memory_ref = dmc.get_memory_reference(memories_selected, cfg["memory_similarity"], response_vec, memory_similarity_logic)
    knowledge_ref = dmc.get_knowledge_reference(response_vec, knowledge_selected)
    output_reference["memory_ref"] = memory_ref
    output_reference["knowledge_ref"] = knowledge_ref

    # Save content
    contents_record_to = []
    if cfg["contents_save"]:
        timestamp_log += "[16.Content save start]" + str(datetime.now()) + "<br>"
        for rec in contents_records:
            session.save_contents_file(rec["from"], rec["to"]["file_name"])
            contents_record_to.append(rec["to"])

    # B-5: Bulk-save logs
    if cfg["memory_save"]:
        timestamp_log += "[17.Log save start]" + str(datetime.now()) + "<br>"

        # Save vector files (for similarity evaluation)
        query_vec_file = ""
        response_vec_file = ""
        if cfg["memory_similarity"]:
            query_vec_file = session.save_vec_file(str(seq), str(sub_seq), "query", query_vec)
            response_vec_file = session.save_vec_file(str(seq), str(sub_seq), "response", response_vec)

        setting_chat_dict = {
            "session_id": session.session_id,
            "session_name": session.session_name,
            "type": model_type,
            "agent_file": agent_file,
            "name": agent.name,
            "engine": agent.agent["ENGINE"][model_type],
            "feedback": agent.agent["FEEDBACK"],
            "persona_id": getattr(agent, "persona_id", "") or "",
            "persona_name": getattr(agent, "persona_name", "") or "",
        }
        prompt_chat_dict = {
            "role": "user",
            "timestamp": timestamp_begin,
            "token": prompt_tokens,
            "query": {
                "input": user_input, "token": query_tokens, "text": user_query,
                "contents": contents_record_to, "situation": situation,
                "tools": [], "vec_file": query_vec_file
            },
            "thinking": thinking_log,
            "web_search": web_search_log,
            "agent_search": exec_info.get("_AGENT_SEARCH_LOG", []),
            "function_search": exec_info.get("_FUNCTION_SEARCH_LOG", []),
            "RAG_query_genetor": RAG_query_gene_log,
            "meta_search": meta_search_log,
            "knowledge_rag": {"setting": agent.agent["KNOWLEDGE"]},
            "prompt_template": {"setting": prompt_temp_cd},
            "user_memory_context": user_memory_context,
            "user_memory_meta": user_memory_meta,
            "text": prompt
        }
        response_chat_dict = {
            "role": "assistant",
            "timestamp": timestamp_end,
            "token": response_tokens,
            "text": response,
            "vec_file": response_vec_file,
            "reference": {"memory": memory_ref, "knowledge_rag": knowledge_ref,
                          "user_memory": user_memory_used,
                          # Graph seed provenance keyed by RAG_NAME — the
                          # Detail Information [Seed for Graph] panel and
                          # the Chat Analytics Graph header read this.
                          "graph_seed_traces": graph_seed_traces}
        }

        # Insert citation markers into the response synchronously when the
        # user enabled the toggle AND Web search actually returned URLs.
        # The citation tool has its own internal fallback (append plain
        # `## Reference Info` to the original body) if the LLM step fails, so
        # the worst-case here is that the body is untouched.
        # Build the citation candidate list:
        #  - Web search URLs (always citable when present)
        #  - BOOK chunks (filtered by agent.BOOK RAG_NAMEs — KNOWLEDGE entries
        #    are the agent's internalised knowledge and are intentionally NOT
        #    cited per project policy). Two BOOK retriever types coexist:
        #    Vector → chunks land in knowledge_selected as dicts;
        #    PageIndex → chunks land as pre-formatted LOG_TEMPLATE strings.
        #    We extract from both.
        _ci_sources = []
        for _u in (web_search_log.get("urls") or []):
            if isinstance(_u, dict) and _u.get("url"):
                _ci_sources.append({"type": "web", "url": _u.get("url"),
                                     "title": _u.get("title", "")})
        _book_rag_names = {(_b or {}).get("RAG_NAME")
                            for _b in (agent.agent.get("BOOK") or [])
                            if isinstance(_b, dict) and _b.get("RAG_NAME")}
        if _book_rag_names and isinstance(knowledge_selected, list):
            import re as _re_ci
            _kv_re = _re_ci.compile(r"'([^']+)'\s*:\s*'((?:[^'\\]|\\.)*)'")
            _vector_chunks = []
            _pageindex_entries = []
            for _c in knowledge_selected:
                if isinstance(_c, dict):
                    if _c.get("rag") in _book_rag_names:
                        _vector_chunks.append(_c)
                elif isinstance(_c, str):
                    # Parse LOG_TEMPLATE 'key':'value' pairs (used for PageIndex BOOK)
                    _kv = dict(_kv_re.findall(_c))
                    if _kv.get("rag") in _book_rag_names:
                        _pageindex_entries.append(_kv)
            # Vector BOOK chunks: take top-K by similarity_response.
            # Snippet is sanitised: book chunk bodies frequently contain
            # markdown headers / tables / code fences that would otherwise
            # render inside Reference Info as nested widgets — flatten them.
            _vector_chunks.sort(key=lambda c: c.get("similarity_response", 0) or 0, reverse=True)
            for _c in _vector_chunks[:10]:
                _ci_sources.append({
                    "type": "book",
                    "rag_name": _c.get("rag", ""),
                    "title": _c.get("title", "") or _c.get("ID", ""),
                    "snippet": _sanitize_reference_snippet(
                        _c.get("value_text_short") or _c.get("value_text") or "",
                        max_len=60),
                })
            # PageIndex BOOK entries: LLM already filtered (max_pages),
            # take all (typically ≤5) since they were explicitly selected.
            for _kv in _pageindex_entries[:10]:
                _ci_sources.append({
                    "type": "book",
                    "rag_name": _kv.get("rag", ""),
                    "title": _kv.get("title", "") or _kv.get("page_id", ""),
                    "snippet": _sanitize_reference_snippet(
                        _kv.get("summary") or "", max_len=60),
                })

        if cfg["insert_citations"] and _ci_sources:
            citation_agent_file = (agent.agent.get("SUPPORT_AGENT") or {}).get("CITATION_INJECT", "")
            import logging as _lg_ci
            _ci_counts = {"web": sum(1 for s in _ci_sources if s.get("type") == "web"),
                          "book": sum(1 for s in _ci_sources if s.get("type") == "book")}
            _ci_book_titles = [s.get("title", "")[:40] for s in _ci_sources if s.get("type") == "book"]
            _lg_ci.getLogger(__name__).info(
                f"[citation_inject] starting: web={_ci_counts['web']}, book={_ci_counts['book']}, "
                f"book_rag_names={sorted(_book_rag_names)}, "
                f"book_titles={_ci_book_titles}, "
                f"agent_file={citation_agent_file!r}, body_len={len(response)}"
            )
            try:
                session.save_status_message("Inserting citations", response=response)
                _, _, _cited, _, _, _ = dmt.call_function_by_name(
                    service_info, user_info, "inject_citations",
                    session_id, session_name, citation_agent_file,
                    response, [], {"Sources": _ci_sources}
                )
                # Accept the injected output only when it actually inserted
                # citation markers or a References section. Otherwise the LLM
                # returned meta commentary ("no matches found, so I'm not
                # citing") that would replace the real answer with an apology
                # — even if the length passes the sanity check. Falling back
                # to the original body is the safe move: the user asked for
                # citations to be added, not for the response to be replaced
                # with an explanation of why they couldn't be.
                import re as _re_ci
                _has_marker = bool(_cited and (
                    _re_ci.search(r"\[\d+\]", _cited)
                    or "## Reference Info" in _cited
                    or "## References" in _cited
                ))
                if _cited and _has_marker and len(_cited) >= max(0.5 * len(response), 50):
                    # Normalize legacy `## References` header to the new name so
                    # UI + stripping code only need to know the new label.
                    if "## Reference Info" not in _cited and "## References" in _cited:
                        _cited = _cited.replace("## References", "## Reference Info")
                    response = _cited
                    response_chat_dict["text"] = response
                    _lg_ci.getLogger(__name__).info(
                        f"[citation_inject] applied: new body_len={len(response)}, "
                        f"contains '[1]': {'[1]' in response}, "
                        f"contains '## Reference Info': {'## Reference Info' in response}"
                    )
                else:
                    # Injection was rejected (LLM returned meta commentary or
                    # too short). The user still wants to SEE what was
                    # searched — silently dropping Reference Info here is
                    # what caused the "Reference not showing" bug when Web
                    # Search + Reference Knowledge were both on. Fall back to
                    # a plain References block built directly from the source
                    # list, without inline [N] markers in the body.
                    _refs_block = _build_plain_references_block(_ci_sources)
                    if _refs_block and "## Reference Info" not in response:
                        response = f"{(response or '').rstrip()}\n\n{_refs_block}"
                        response_chat_dict["text"] = response
                        _lg_ci.getLogger(__name__).info(
                            f"[citation_inject] kept original body but appended "
                            f"plain Reference Info block ({len(_ci_sources)} sources)"
                        )
                    else:
                        _lg_ci.getLogger(__name__).warning(
                            f"[citation_inject] kept original (no markers or length): "
                            f"cited_len={len(_cited) if _cited else 0}, body_len={len(response)}, "
                            f"has_marker={_has_marker}"
                        )
            except Exception as _ce:
                import logging as _lg
                _lg.getLogger(__name__).exception(f"Citation injection failed: {_ce}")
                _ctx = {"phase": "citation_inject", "session_id": session_id,
                        "session_name": session_name, "seq": seq, "sub_seq": sub_seq,
                        "citation_agent_file": citation_agent_file}
                try:
                    dms.save_global_error_log(_ce, context=_ctx)
                except Exception:
                    pass
                try:
                    session.save_error_log(_ce, context=_ctx)
                except Exception:
                    pass
                # Same fallback as the rejected-injection path — the user
                # asked to see references whenever Web/Book were searched,
                # so even on injector failure we surface the source list.
                _refs_block = _build_plain_references_block(_ci_sources)
                if _refs_block and "## Reference Info" not in response:
                    response = f"{(response or '').rstrip()}\n\n{_refs_block}"
                    response_chat_dict["text"] = response

        # Referenced KNOWLEDGE — populated by a dedicated second-pass
        # selector agent that reads the primary answer + the Retrieved
        # Knowledge manifest and returns the chunks that were actually
        # referenced. This replaces earlier attempts (inline directive,
        # util-based heuristic) that under-reported or biased toward
        # whichever RAG had the most/longest chunks. On selector failure
        # we still emit a one-per-RAG util fallback so the section is
        # populated whenever cite_knowledge is on and chunks were retrieved.
        if cfg.get("cite_knowledge"):
            try:
                import logging as _lg_ks
                _log = _lg_ks.getLogger(__name__)
                _ck_dbg = {
                    "cite_knowledge_on":  True,
                    "manifest_size":      len(_cite_chunk_lookup),
                    "selector_agent":     "",
                    "selector_entries":   0,
                    "fallback_used":      False,
                    "emitted_rows":       0,
                    "response_tail_200":  response[-200:] if response else "",
                    "skip_reason":        "",
                }
                if not _cite_chunk_lookup:
                    _ck_dbg["skip_reason"] = "no manifest (cite_knowledge off at manifest-build time OR no non-book chunks retrieved)"
                    _log.info(f"[cite_knowledge] {_ck_dbg['skip_reason']} — Reference Knowledge suppressed")
                else:
                    # Refresh util now that similarity_response is stamped
                    # (Detail Information reads this from the debug dict).
                    _refresh_chunk_util(_cite_chunk_lookup, knowledge_selected)
                    _selector_agent = (agent.agent.get("SUPPORT_AGENT") or {}).get(
                        "KNOWLEDGE_USAGE_SELECTOR", "agent_80DigiMKnowledgeUsageSelector.json")
                    _ck_dbg["selector_agent"] = _selector_agent
                    _entries = _detect_used_chunks(
                        service_info, user_info, session_id, session_name,
                        _selector_agent, response, _cite_chunk_lookup)
                    _ck_dbg["selector_entries"] = len(_entries)
                    _ck_dbg["llm_declared"] = [
                        {"rag": rag, "id": cid, "note": note,
                         "matched": (rag, cid) in _cite_chunk_lookup,
                         "title": (_cite_chunk_lookup.get((rag, cid), {}) or {}).get("title", "")}
                        for rag, cid, note in _entries
                    ]
                    if not _entries:
                        _entries = _build_util_fallback_entries(_cite_chunk_lookup)
                        _ck_dbg["fallback_used"] = True
                        _log.info(
                            f"[cite_knowledge] fallback (one per RAG) -> "
                            f"{len(_entries)} entries"
                        )
                    _ks = _build_knowledge_section(_entries, _cite_chunk_lookup)
                    if _ks:
                        # Append AFTER any ## Reference Info the citation
                        # injector just added, so the two sections coexist:
                        #   ## Reference Info       (Web / Book)
                        #   ## Reference Knowledge  (internal KNOWLEDGE)
                        response = f"{(response or '').rstrip()}\n\n{_ks}"
                        response_chat_dict["text"] = response
                        # Count matched only — unmatched rows are dropped from
                        # the visible section by _build_knowledge_section.
                        _ck_dbg["emitted_rows"] = sum(
                            1 for rag, cid, _n in _entries
                            if (rag, cid) in _cite_chunk_lookup)
                    else:
                        _ck_dbg["skip_reason"] = "no rows (selector empty OR every entry unmatched + fallback empty)"
                        _log.info(f"[cite_knowledge] {_ck_dbg['skip_reason']}")
                _ck_dbg["manifest"] = [
                    {"rag": m.get("rag", ""),
                     "id":  m.get("id", ""),
                     "title": m.get("title", ""),
                     "sim_q": m.get("sim_q", 0.0),
                     "sim_a": m.get("sim_a", 0.0),
                     "util":  m.get("util", 0.0)}
                    for m in (_cite_chunk_lookup or {}).values()
                ]
                response_chat_dict.setdefault("reference", {})["cite_knowledge_debug"] = _ck_dbg
            except Exception as _kse:
                import logging as _lg_ks
                _lg_ks.getLogger(__name__).exception(
                    f"Knowledge reference section skipped: {_kse}")

        # Image log (IMAGEGEN)
        img_dict = {}
        if model_type == "IMAGEGEN":
            for i, img_path in enumerate(completion):
                img_file_name = "[OUT]seq" + str(seq) + "-" + str(sub_seq) + "_" + os.path.basename(img_path)
                session.save_contents_file(img_path, img_file_name)
                _img_ext = os.path.splitext(img_file_name)[1].lstrip(".").lower()
                _img_mime = f"image/{_img_ext}" if _img_ext else "image/png"
                img_dict[i] = {"role": "image", "timestamp": timestamp_end,
                               "file_name": img_file_name, "file_type": _img_mime}
                export_files.append(str(Path(session.session_folder_path) / "contents" / img_file_name))

        timestamp_log += "[Done]" + str(datetime.now()) + "<br>"

        # B-5: Bulk write (digest is appended separately in the background)
        sub_seq_data = {
            str(sub_seq): {
                "setting": setting_chat_dict,
                "prompt": prompt_chat_dict,
                "response": response_chat_dict,
                "log": {"timestamp_log": timestamp_log}
            }
        }
        if model_type == "IMAGEGEN" and img_dict:
            sub_seq_data[str(sub_seq)]["image"] = img_dict
        session.save_history_batch(str(seq), sub_seq_data)
        session.save_user_dialog_session("UNSAVED")

        # Reflect the finalized response into the status (for pseudo-streaming)
        session.save_status_message("Generating digest", response=response)

        # Kick off digest generation in the background (UNLOCK the session after completion)
        if cfg["save_digest"]:
            _unlock_on_complete = execution.get("_UNLOCK_ON_DIGEST", True)
            timestamp_log += "[18.Memory digest generation started in background]" + str(datetime.now()) + "<br>"

            # Incremental form: feed the previous digest + the current turn.
            # The `kind` field tags each item so dialog_digest can hand the
            # LLM two DISTINCT sections — the accumulated prior digest
            # (which must be preserved verbatim so old topics don't drop
            # out) and the latest turn (which the LLM appends to the
            # accumulation). Without the tag the tool used to concatenate
            # everything and let the LLM re-summarise, which quietly ate
            # older topics.
            _slim_memories = []
            try:
                _, _, _prev_digest = session.get_history_digest(str(seq), str(sub_seq))
                if _prev_digest and _prev_digest.get("text"):
                    _slim_memories.append({
                        "role": "assistant",
                        "kind": "prev_digest",
                        "text": _prev_digest["text"],
                    })
            except Exception:
                pass
            # Use user_info.NAME for the speaker; fall back to USER_ID when absent (no master lookup)
            _udisp = (user_info or {}).get("NAME") or (user_info or {}).get("USER_ID") or "(unknown)"
            _aname = getattr(agent, "name", "") or "AI"
            _slim_memories.append({"role": "user", "kind": "latest_turn",
                                     "text": f"[User: {_udisp}] {user_query}"})
            _slim_memories.append({"role": "assistant", "kind": "latest_turn",
                                     "text": f"[Agent: {_aname}] {response}"})

            _digest_job_id = djr.new_job_id()
            _digest_args = (session, service_info, user_info, session_id, session_name,
                            support_agent, _slim_memories,
                            seq, sub_seq, cfg, _unlock_on_complete)

            def _digest_wrapper():
                try:
                    _run_digest_background(*_digest_args)
                except (SystemExit, KeyboardInterrupt):
                    try:
                        session.save_status("UNLOCKED", error="Cancelled by user")
                    except Exception:
                        pass
                finally:
                    djr.unregister_job(_digest_job_id)

            _digest_thread = threading.Thread(target=_digest_wrapper, daemon=True)
            djr.register_job(_digest_job_id, _digest_thread, "digest",
                             f"Digest generation: {session_name}", session_id=session_id,
                             user_id=user_info.get("USER_ID") if isinstance(user_info, dict) else None)
            _digest_thread.start()
            output_reference["_digest_bg_started"] = True

        # ── Session Summary background update ────────────────────────────
        # Distinct from memory digest — this one fills a user-defined
        # template (see DigiM_Session.get_session_summary) that the operator
        # can read in the Detail Information → Session Summary tab. Runs in
        # its own background thread so the chat return path stays fast.
        try:
            _summary_enabled, _summary_tpl, _summary_prev, _ = (
                session.get_session_summary()
            )
        except Exception:
            _summary_enabled, _summary_tpl, _summary_prev = False, "", ""
        if _summary_enabled and _summary_tpl:
            _summ_job_id = djr.new_job_id()
            _summ_agent_file = _get_session_summary_agent_file(agent, in_agent_file)
            def _summary_wrapper():
                try:
                    _new_summary, _ = update_session_summary(
                        template=_summary_tpl,
                        prev_summary=_summary_prev,
                        user_input=user_query,
                        agent_response=response,
                        agent_file=_summ_agent_file,
                        service_info=service_info,
                        user_info=user_info,
                    )
                    if _new_summary:
                        session.save_session_summary_content(_new_summary)
                except Exception:
                    pass
                finally:
                    djr.unregister_job(_summ_job_id)
            _summary_thread = threading.Thread(target=_summary_wrapper, daemon=True)
            djr.register_job(_summ_job_id, _summary_thread, "session_summary",
                              f"Session Summary update: {session_name}",
                              session_id=session_id,
                              user_id=user_info.get("USER_ID") if isinstance(user_info, dict) else None)
            _summary_thread.start()
            output_reference["_session_summary_bg_started"] = True

    yield response_service_info, user_info, "", export_files, output_reference

# ── Session Summary — user-defined session dossier ────────────────────────
# The prompt sits in DigiM_Execute (not DigiM_Tool) because it operates on the
# same session state — this way the background hook right above stays local.

def _get_session_summary_agent_file(agent_obj, fallback_agent_file):
    """Return the agent file to use for summary updates.

    Priority:
      1. Chat agent's SUPPORT_AGENT.SESSION_SUMMARY slot (per-agent override)
      2. The generic lightweight agent (`agent_65SessionSummary.json`)
         — shipped default, uses Gemini-2.5-Flash for cheap/fast updates
      3. The chat agent itself (ultimate fallback so the feature always works
         even if the lightweight agent file was removed)
    """
    try:
        _sa = agent_obj.agent.get("SUPPORT_AGENT", {}) or {}
        _sess_sa = _sa.get("SESSION_SUMMARY")
        if _sess_sa:
            return _sess_sa
    except Exception:
        pass
    # Global default — the shipped lightweight generic agent. Kept as a
    # data-file lookup (not a hardcoded import) so operators can swap it
    # by dropping in a different `agent_65*.json`.
    try:
        _generic_name = "agent_65SessionSummary.json"
        _generic_path = os.path.join(dma.agent_folder_path, _generic_name)
        if os.path.exists(_generic_path):
            return _generic_name
    except Exception:
        pass
    return fallback_agent_file


def update_session_summary(template: str, prev_summary: str,
                            user_input: str, agent_response: str,
                            agent_file: str, service_info: dict,
                            user_info: dict):
    """Regenerate the session summary after a turn.

    Prompts the LLM with:
      - the template (structure to fill in)
      - the previous summary (starting point — LLM should preserve confirmed facts)
      - the latest user_input + agent_response (new information)
    and expects an updated Markdown document that conforms to the template.
    Returns (new_summary, model_name). Returns (prev_summary, "") on error so
    the stored content never regresses to empty on transient LLM failures.
    """
    try:
        agent = dma.DigiM_Agent(agent_file)
    except Exception:
        return prev_summary, ""
    model_type = "LLM"
    model_name = agent.agent.get("ENGINE", {}).get(model_type, {}).get("MODEL", "")
    prompt = (
        "あなたはセッション状態を管理するエージェントです。\n"
        "以下のフォーマットに従い、これまでのサマリーと最新の対話を統合して更新版を出力してください。\n\n"
        "【フォーマット (このヘッダー構造を維持)】\n"
        f"{template}\n\n"
        "【現在のサマリー】\n"
        f"{prev_summary or '(まだサマリーはありません)'}\n\n"
        "【最新の対話】\n"
        f"User: {user_input}\n"
        f"Agent: {agent_response}\n\n"
        "【指示】\n"
        "- フォーマットの見出し (## ...) はそのまま維持\n"
        "- これまでの対話と最新の対話を踏まえて各項目を更新\n"
        "- 前ターンで確定済みの情報は消さない (最新情報で上書きされない限り保持)\n"
        "- 情報がない項目は空のまま (「未確認」等の埋め草を書かない)\n"
        "- Markdown 形式で出力し、前後に説明文をつけない (コードフェンスも不要)\n"
    )
    try:
        raw = ""
        for _p, chunk, _c in agent.generate_response(model_type, prompt):
            if chunk:
                raw += chunk
        _out = raw.strip()
        # Strip stray fences if the LLM ignored the instruction.
        if _out.startswith("```"):
            import re as _re
            _out = _re.sub(r"^```(?:markdown|md)?\s*", "", _out)
            _out = _re.sub(r"\s*```\s*$", "", _out)
        return _out or prev_summary, model_name
    except Exception:
        return prev_summary, model_name

# Run via a practice
def DigiMatsuExecute_Practice(service_info, user_info, session_id, session_name, in_agent_file, user_query, in_contents=[], in_situation={}, in_overwrite_items={}, in_add_knowledge=[], in_execution={}, in_persona=None, in_rag_query_text="", in_personas=None, in_org=None):

    # Fill user_info.NAME once so the speaker name persists in SETTING (reflected in subsequent history).
    # Look up the master only once per request. Keep a copy so we don't mutate the caller's dict.
    user_info = dict(user_info or {})
    if user_info.get("USER_ID") and not user_info.get("NAME"):
        try:
            import DigiM_Auth as _dma_um
            _um = _dma_um.load_user_master() or {}
            _nm = (_um.get(user_info["USER_ID"]) or {}).get("Name")
            if _nm:
                user_info["NAME"] = _nm
        except Exception:
            pass

    # B-2: Load execution settings
    last_only = in_execution.get("LAST_ONLY", False)
    cfg = _parse_execution_settings(in_execution)

    session = dms.DigiMSession(session_id, session_name)
    # For multi-persona parallel execution, set the starting position via sub_seq_start (default 1)
    sub_seq = in_execution.get("_SUB_SEQ_START", 1)
    results = []
    response_service_info = service_info
    response_user_info = user_info
    _digest_bg_started = False  # If the background digest is launched, we do not UNLOCK here

    # Lock the session (pre_locked=True means the caller has already locked it)
    _pre_locked = in_execution.get("_PRE_LOCKED", False)
    if session.get_status() == "LOCKED" and not _pre_locked:
        raise Exception("Session is locked. Please unlock the session before executing the practice.")
    session.save_status("LOCKED")

    try:
        agent = dma.DigiM_Agent(in_agent_file)
        thinking_result = {}

        # Thinking Mode: AI analyzes the question and decides execution parameters.
        # Optionally multi-turn (B-type loop): between turns we run the
        # preview action (Web search only for v1) requested by the current
        # turn's judgement, feed the raw result into the next turn's
        # Thinking prompt, and keep looping until `sufficient=true` or
        # MAX_THINKING_TURNS is reached. The preview search is cached in
        # `_WEB_SEARCH_CACHE` so the main execution's web-search path
        # reuses it (no double API call).
        if cfg["thinking_mode"] and "SUPPORT_AGENT" in agent.agent and "THINKING" in agent.agent["SUPPORT_AGENT"]:
            # Read the digest (for context-understanding by Thinking)
            _thinking_digest = ""
            if session.chat_history_active_dict:
                _, _, _digest_dict = session.get_history_max_digest()
                if _digest_dict:
                    _thinking_digest = _digest_dict["text"]

            # Read the situation. Falls back to the current real date when
            # the parent's TIME is empty ("No Date") so Thinking can still
            # judge freshness signals ("recent", "current", year-containing queries etc.)
            # instead of asking the LLM to reason without a clock.
            _sit = in_situation or {}
            _thinking_time = _sit.get("TIME") or datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            _thinking_situation = (_sit.get("SITUATION", "") + " " + _thinking_time).strip()

            _max_turns = int(in_execution.get("MAX_THINKING_TURNS", 1) or 1)
            _max_turns = max(1, min(_max_turns, 5))  # hard cap to prevent runaway cost
            thinking_result = {}
            thinking_log = {}
            thinking_history = []
            _web_preview_for_next = ""
            for _turn_idx in range(_max_turns):
                _label = "Thinking" if _max_turns == 1 else f"Thinking (turn {_turn_idx + 1}/{_max_turns})"
                session.save_status_message(f"{_label}...")
                yield service_info, user_info, f"[STATUS]{_label}...", {}
                _tr, _tl = _run_thinking_agent(
                    service_info, user_info, session_id, session_name,
                    agent.agent["SUPPORT_AGENT"], agent, user_query,
                    _thinking_digest, _thinking_situation,
                    previous_thinking=(thinking_result if _turn_idx > 0 else None),
                    web_search_preview=_web_preview_for_next,
                )
                if _tl is not None:
                    _tl = dict(_tl); _tl["turn"] = _turn_idx + 1
                    thinking_history.append(_tl)
                # Empty result → give up cleanly
                if not _tr:
                    thinking_log = _tl or {}
                    break
                thinking_result = _tr
                thinking_log = _tl or {}
                # Break out: LLM says its judgement is good enough, or we've
                # exhausted the turn budget. Default treats missing
                # `sufficient` as true so back-compat (single-turn) prompts
                # never trip the loop.
                _sufficient = bool(_tr.get("sufficient", True))
                if _sufficient or _turn_idx == _max_turns - 1:
                    break
                # Mid-loop action: preview Web search when this turn requested it.
                # Effective web toggle = user's UI ON OR Thinking's judgement.
                # (Applies the same "user-ON stays ON" rule as the final apply
                # below — only Thinking's engine choice can override cfg's.)
                _want_search = bool(_tr.get("web_search")) or bool(cfg["web_search"])
                _preview_engine = (_tr.get("web_search_engine")
                                    or cfg["web_search_engine"]
                                    or system_setting_dict.get("WEB_SEARCH_DEFAULT", "Perplexity"))
                if not _want_search:
                    _web_preview_for_next = ""
                    continue
                _preview_query = _tr.get("web_search_query", "") or ""
                # Build the same search_text shape the main path builds so
                # the cache key hits cleanly on the main-execution side.
                if _preview_query:
                    _search_text = "検索して欲しい内容:\n" + _preview_query + "\n\n[参考]元の質問:\n" + user_query
                elif _thinking_digest or _thinking_situation:
                    _search_text = ("検索して欲しい内容:\n" + user_query
                                    + "\n\n[参考]これまでの会話:\n" + _thinking_digest
                                    + "\n\n[参考]今の状況:\n" + _thinking_situation)
                else:
                    _search_text = user_query
                session.save_status_message(f"{_label}: preview web search")
                yield service_info, user_info, f"[STATUS]{_label}: preview web search...", {}
                try:
                    _t_start = datetime.now()
                    _, _, _ws_text, _ws_urls = dmt.call_function_by_name(
                        service_info, user_info, "WebSearch",
                        session_id, session_name, in_agent_file, _search_text, [], {},
                        engine=_preview_engine)
                    _ws_dur = round((datetime.now() - _t_start).total_seconds(), 2)
                    in_execution["_WEB_SEARCH_CACHE"] = {
                        "engine": _preview_engine,
                        "search_text": _search_text,
                        "result_text": _ws_text,
                        "urls": _ws_urls or [],
                        "duration_sec": _ws_dur,
                    }
                    _web_preview_for_next = _ws_text or ""
                except Exception as _ws_e:
                    import logging as _lg_th
                    _lg_th.getLogger(__name__).warning(
                        f"[thinking-loop] preview web search failed (turn {_turn_idx+1}): {_ws_e}")
                    _web_preview_for_next = ""

            # Apply Thinking output to execution settings (only items enabled by THINKING_TARGETS)
            _targets = in_execution.get("THINKING_TARGETS", {})
            if thinking_result:
                if _targets.get("web_search", True) and "web_search" in thinking_result:
                    # Thinking can promote OFF → ON, but should NOT silently
                    # disable a user-explicit ON toggle. Mirror semantics:
                    # the UI checkbox is a hard "yes please search" hint;
                    # Thinking can supplement, not veto, it.
                    if cfg["web_search"]:
                        # User already wants WebSearch — keep it on, but still
                        # let Thinking refine the engine choice (e.g. when it
                        # has a stronger signal about which engine fits).
                        if "web_search_engine" in thinking_result and thinking_result.get("web_search_engine"):
                            cfg["web_search_engine"] = thinking_result["web_search_engine"]
                    else:
                        cfg["web_search"] = thinking_result["web_search"]
                        if "web_search_engine" in thinking_result:
                            cfg["web_search_engine"] = thinking_result["web_search_engine"]
                if _targets.get("rag_query_gene", True) and "rag_query_gene" in thinking_result:
                    cfg["RAG_query_gene"] = thinking_result["rag_query_gene"]

            # Pass the Thinking log/result to the chain-run execution.
            # `_THINKING_LOG` carries the FINAL turn's log for backward-compat
            # (existing Detail Information consumers read a single log dict);
            # the full per-turn history is exposed as `_THINKING_HISTORY`.
            in_execution["_THINKING_LOG"] = thinking_log
            in_execution["_THINKING_HISTORY"] = thinking_history
            in_execution["_THINKING_RESULT"] = thinking_result
        else:
            in_execution["_THINKING_LOG"] = {}
            in_execution["_THINKING_HISTORY"] = []
            in_execution["_THINKING_RESULT"] = {}

        # Habit selection: prefer the Thinking output if available; otherwise judge by Magic Word
        _targets = in_execution.get("THINKING_TARGETS", {})
        habit = "DEFAULT"
        if thinking_result and _targets.get("habit", True) and "habit" in thinking_result and thinking_result["habit"] in agent.habit:
            habit = thinking_result["habit"]
        elif cfg["magic_word_use"]:
            habit = agent.set_practice_by_command(user_query)

        # Book selection: auto-add based on Thinking output
        if thinking_result and _targets.get("books", True) and "books" in thinking_result:
            for book_data in agent.agent.get("BOOK", []):
                if book_data["RAG_NAME"] in thinking_result["books"]:
                    if book_data not in in_add_knowledge:
                        in_add_knowledge.append(book_data)

        practice_file = agent.habit[habit]["PRACTICE"]
        habit_add_knowledge = agent.habit[habit].get("ADD_KNOWLEDGE", [])
        practice = dmu.read_json_file(practice_folder_path + practice_file)

        chains = practice["CHAINS"]
        last_idx = len(chains) - 1

        # Phase 7: if chain.PERSONAS="THINKING" appears in the practice, auto-select via PersonaSelector
        # Candidate pool is under the selected ORG (in_org); max count is execution["MAX_PERSONAS"] / setting.yaml
        # When THINKING_TARGETS.personas is False, skip selection (_resolve_step_personas falls back to UI selection)
        _personas_target_on = _targets.get("personas", True) if isinstance(_targets, dict) else True
        if _personas_target_on and any(c.get("PERSONAS") == "THINKING" for c in chains):
            _max_p = int(in_execution.get("MAX_PERSONAS",
                                           system_setting_dict.get("MAX_PERSONAS", 3)))
            _candidates = []
            try:
                import DigiM_AgentPersona as dap
                if isinstance(in_org, dict) and in_org:
                    _persona_files = agent.agent.get("PERSONA_FILES") or None
                    _persona_source = agent.agent.get("PERSONA_SOURCE")
                    _candidates = dap.find_personas_by_org(in_org, template_agent=in_agent_file,
                                                           persona_files=_persona_files,
                                                           source=_persona_source)
                else:
                    _candidates = list(in_personas or [])
            except Exception as _e:
                _candidates = list(in_personas or [])
            # Select via PersonaSelector
            session.save_status_message(f"Selecting personas (up to {_max_p})")
            yield service_info, user_info, f"[STATUS]Selecting personas (up to {_max_p}, candidates: {len(_candidates)})", {}
            try:
                _selected_ids, _select_reason, _, _, _ = dmt.call_function_by_name(
                    service_info, user_info, "select_personas",
                    session_id, session_name,
                    agent.agent.get("SUPPORT_AGENT", {}).get("PERSONA_SELECTOR", "agent_54PersonaSelector.json"),
                    user_query, _candidates, max_personas=_max_p,
                )
            except Exception as _e:
                _selected_ids, _select_reason = [], f"selector error: {_e}"
            _by_id = {p.get("persona_id"): p for p in _candidates}
            _thinking_personas = [_by_id[pid] for pid in _selected_ids if pid in _by_id]
            # Save into the Thinking result (consumed by _resolve_step_personas in the chain loop)
            in_execution.setdefault("_THINKING_RESULT", {})
            in_execution["_THINKING_RESULT"]["personas"] = _thinking_personas
            in_execution["_THINKING_RESULT"]["personas_reason"] = _select_reason
            in_execution["_THINKING_RESULT"]["personas_selected_ids"] = _selected_ids
            yield service_info, user_info, f"[STATUS]Personas selected: {len(_thinking_personas)} ({', '.join(p.get('name','?') for p in _thinking_personas)})", {}
        for i, chain in enumerate(chains):
            # Reflect chain progress in the status
            if len(chains) > 1:
                session.save_status_message(f"Chain {i+1}/{len(chains)} ({chain['TYPE']}) running")
                yield service_info, user_info, f"[STATUS]Chain {i+1}/{len(chains)} ({chain['TYPE']}) running", {}
            result = {}
            model_type = chain["TYPE"]
            input = ""
            output = ""
            import_contents = []
            export_contents = []
            # Record the step's starting sub_seq so that even multi-persona runs can be referenced from the next step as OUTPUT_<starting sub_seq>
            _step_start_sub_seq = sub_seq

            # When TYPE is "LLM"
            if model_type in ["LLM", "IMAGEGEN"]:
                setting = chain["SETTING"]
                agent_file = setting["AGENT_FILE"] if setting["AGENT_FILE"] != "USER" else in_agent_file
                if setting["OVERWRITE_ITEMS"] == "USER":
                    overwrite_items = in_overwrite_items
                else:
                    # Merge practice settings on top of in_overwrite_items (engine selection etc.); practice wins
                    overwrite_items = dict(in_overwrite_items)
                    if setting["OVERWRITE_ITEMS"]:
                        dmu.update_dict(overwrite_items, setting["OVERWRITE_ITEMS"])
                add_knowledge = []
                for ak in setting["ADD_KNOWLEDGE"]:
                    if "USER" in setting["ADD_KNOWLEDGE"]:
                        add_knowledge.extend(habit_add_knowledge)
                    else:
                        add_knowledge.append(ak)
                for ak in in_add_knowledge:
                    add_knowledge.append(ak)

                prompt_temp_cd = setting["PROMPT_TEMPLATE"]

                # B-3: USER_INPUT resolution
                user_input = _resolve_user_input(setting["USER_INPUT"], user_query, results)

                # B-3: Content resolution
                import_contents = _resolve_contents(setting["CONTENTS"], in_contents, results)

                # Set up the situation
                situation = {}
                if setting["SITUATION"] == "USER":
                    situation = in_situation
                else:
                    situation["TIME"] = in_situation["TIME"] if setting["SITUATION"]["TIME"] == "USER" else setting["SITUATION"]["TIME"]
                    situation["SITUATION"] = in_situation["SITUATION"] if setting["SITUATION"]["SITUATION"] == "USER" else setting["SITUATION"]["SITUATION"]

                seq_limit = chain.get("PreSEQ", "")
                sub_seq_limit = chain.get("PreSubSEQ", "")

                # Mid-chain digest background threads do not UNLOCK (only the last chain UNLOCKs)
                _is_last_chain = (i == last_idx)
                execution = {
                    "CONTENTS_SAVE":     cfg["contents_save"],
                    "MEMORY_USE":        cfg["memory_use"] and setting.get("MEMORY_USE", True),
                    "MEMORY_SAVE":       cfg["memory_save"],
                    "MEMORY_SIMILARITY": cfg["memory_similarity"],
                    "MAGIC_WORD_USE":    cfg["magic_word_use"],
                    "STREAM_MODE":       cfg["stream_mode"],
                    "SAVE_DIGEST":       cfg["save_digest"],
                    "META_SEARCH":       cfg["meta_search"] and setting.get("META_SEARCH", True),
                    "RAG_QUERY_GENE":    cfg["RAG_query_gene"] and setting.get("RAG_QUERY_GENE", True),
                    "WEB_SEARCH":        setting.get("WEB_SEARCH", cfg["web_search"]),
                    "WEB_SEARCH_ENGINE": cfg["web_search_engine"],
                    "WEB_SEARCH_GUARDRAIL": setting.get("WEB_SEARCH_GUARDRAIL", cfg["web_search_guardrail"]),
                    "INSERT_CITATIONS":  setting.get("INSERT_CITATIONS", cfg["insert_citations"]),
                    # Formatting/citation toggles from the WebUI. Without
                    # these lines the per-chain execution dict silently
                    # dropped them and `_parse_execution_settings` fell
                    # back to False — Diagrams / Emphasis / Reference
                    # Knowledge never fired even when the boxes were on.
                    "CITE_KNOWLEDGE":    cfg["cite_knowledge"],
                    "DIAGRAM_MODE":      cfg["diagram_mode"],
                    "EMPHASIS_MODE":     cfg["emphasis_mode"],
                    "PRIVATE_MODE":      cfg["private_mode"],
                    "THINKING_MODE":     cfg["thinking_mode"],
                    "_THINKING_LOG":     in_execution.get("_THINKING_LOG", {}),
                    "_THINKING_RESULT":  in_execution.get("_THINKING_RESULT", {}),
                    "_UNLOCK_ON_DIGEST": _is_last_chain,
                    # User Memory: propagate the immediate UI override downstream (None=unspecified -> downstream falls back to user master / system default)
                    "USER_MEMORY_LAYERS": in_execution.get("USER_MEMORY_LAYERS"),
                    # Propagate the multi-persona parallel-execution flags to the downstream DigiMatsuExecute
                    "_SEQ_OVERRIDE":     in_execution.get("_SEQ_OVERRIDE"),
                    "_SUB_SEQ_START":    in_execution.get("_SUB_SEQ_START"),
                    "_SESSION_BASE_PATH": in_execution.get("_SESSION_BASE_PATH", ""),
                    # AgentSearch shared recursion counter — pass-through so nested
                    # AgentSearch calls keep honoring the same cap.
                    "_AGENT_SEARCH_STATE": in_execution.get("_AGENT_SEARCH_STATE"),
                }

                # Phase 6/7: Decide multi-persona parallel execution within a step based on chain.PERSONAS
                step_personas = _resolve_step_personas(chain.get("PERSONAS"), in_personas, in_agent_file, in_execution)

                response = ""
                # Use rag_query_text only for the first chain step
                _rag_query_text_for_step = in_rag_query_text if i == 0 else ""

                if len(step_personas) >= 2:
                    # ---- Multi-persona parallel execution ----
                    yield service_info, user_info, f"[STATUS]chain[{i}] running {len(step_personas)} personas in parallel...", {}
                    # Lock in the seq up-front (when _SEQ_OVERRIDE is unset)
                    if execution.get("_SEQ_OVERRIDE") is None:
                        _step_seq = session.get_seq_history() + 1 if sub_seq == 1 else session.get_seq_history()
                        execution["_SEQ_OVERRIDE"] = _step_seq
                    _persona_responses = []
                    _max_workers = min(len(step_personas),
                                       max(1, int(system_setting_dict.get("MAX_PARALLEL_PERSONAS", 4))))

                    def _run_step_persona(p_idx, persona):
                        local_sub_seq = sub_seq + p_idx
                        local_resp = ""
                        try:
                            for _r_svc, _r_usr, _chunk, _exp, _oref in DigiMatsuExecute(
                                    service_info, user_info, session_id, session_name, agent_file, model_type,
                                    local_sub_seq, user_input, import_contents, situation, overwrite_items,
                                    add_knowledge, prompt_temp_cd, execution, seq_limit, sub_seq_limit,
                                    persona=persona, rag_query_text=_rag_query_text_for_step):
                                if _chunk and not _chunk.startswith("[STATUS]"):
                                    local_resp += _chunk
                        except Exception as _e:
                            local_resp = f"[ERROR] {_e}"
                        return persona, local_sub_seq, local_resp

                    with ThreadPoolExecutor(max_workers=_max_workers) as _ex:
                        _futures = [_ex.submit(_run_step_persona, _i, _p) for _i, _p in enumerate(step_personas)]
                        for _fut in as_completed(_futures):
                            _p, _ss, _resp = _fut.result()
                            _persona_responses.append({
                                "persona_id": _p.get("persona_id", ""),
                                "persona_name": _p.get("name", ""),
                                "sub_seq": _ss,
                                "text": _resp,
                            })
                            yield service_info, user_info, f"[STATUS]chain[{i}] {_p.get('name','?')} done", {}

                    # Sort by sub_seq (stabilize save order)
                    _persona_responses.sort(key=lambda r: r["sub_seq"])

                    # Attach setting.memory_flg="N" / chain_index / chain_role to each persona sub_seq
                    _seq_str = str(execution["_SEQ_OVERRIDE"])
                    for _r in _persona_responses:
                        try:
                            session.update_subseq_setting(_seq_str, str(_r["sub_seq"]), {
                                "memory_flg": "N",
                                "chain_index": i,
                                "chain_role": "persona",
                            })
                        except Exception:
                            pass

                    # Apply PERSONA_MERGE (output text = the output passed to the next step)
                    _merge_method = chain.get("PERSONA_MERGE", "summary")
                    _merge_level = chain.get("PERSONA_MERGE_LEVEL", "medium")
                    response = _apply_persona_merge(
                        _merge_method, _persona_responses, user_input, _merge_level,
                        service_info, user_info, session_id, session_name, agent.support_agent
                    )

                    # Advance sub_seq by N
                    sub_seq += len(step_personas) - 1   # The loop tail adds +1, so the total is N

                else:
                    # ---- Existing path: single-persona execution (or in_persona) ----
                    for response_service_info, response_user_info, response_chunk, export_contents, output_reference in DigiMatsuExecute(
                            service_info, user_info, session_id, session_name, agent_file, model_type,
                            sub_seq, user_input, import_contents, situation, overwrite_items,
                            add_knowledge, prompt_temp_cd, execution, seq_limit, sub_seq_limit,
                            persona=in_persona, rag_query_text=_rag_query_text_for_step):
                        if not last_only or i == last_idx:
                            yield response_service_info, response_user_info, response_chunk, output_reference
                        if response_chunk and not response_chunk.startswith("[STATUS]"):
                            response += response_chunk
                    if _is_last_chain and output_reference.get("_digest_bg_started", False):
                        _digest_bg_started = True

                input = user_input
                output = response

            elif model_type == "TOOL":
                seq = session.get_seq_history() + 1 if sub_seq == 1 else session.get_seq_history()
                setting = chain["SETTING"]

                # B-3: USER_INPUT resolution
                user_input = _resolve_user_input(
                    setting["USER_INPUT"], user_query, results) if "USER_INPUT" in setting else ""
                input = user_input

                # B-3: Content resolution
                import_contents = _resolve_contents(
                    setting["CONTENTS"], in_contents, results) if "CONTENTS" in setting else []

                agent_file = setting["AGENT_FILE"] if "AGENT_FILE" in setting and setting["AGENT_FILE"] != "USER" else in_agent_file
                add_info = setting.get("ADD_INFO", {})

                timestamp_begin = str(datetime.now())
                tool_result = dmt.call_function_by_name(
                    service_info, user_info, setting["FUNC_NAME"],
                    session_id, session_name, agent_file, input, import_contents, add_info)
                output = ""
                export_contents = []
                if inspect.isgenerator(tool_result):
                    for resp_svc, resp_usr, chunk, exp in tool_result:
                        output += dmu.sanitize_text(str(chunk)) if chunk else ""
                        if exp is not None:
                            export_contents = exp
                        if not last_only or i == last_idx:
                            yield resp_svc, resp_usr, chunk, {}
                    response_service_info = resp_svc
                    response_user_info = resp_usr
                else:
                    response_service_info, response_user_info, output, export_contents = tool_result
                    if not last_only or i == last_idx:
                        yield response_service_info, response_user_info, output, {}
                timestamp_end = str(datetime.now())

                # B-5: Bulk-save TOOL execution logs
                session.save_history_batch(str(seq), {
                    str(sub_seq): {
                        "setting": {
                            "response_service_info": response_service_info,
                            "response_user_info": response_user_info,
                            "session_name": session.session_name,
                            "situation": in_situation,
                            "type": model_type,
                            "agent_file": in_agent_file,
                            "name": practice["NAME"],
                            "tool": setting["FUNC_NAME"]
                        },
                        "prompt": {
                            "role": "neither",
                            "timestamp": timestamp_begin,
                            "text": input,
                            "query": {"token": 0, "input": input, "text": input,
                                      "contents": import_contents, "situation": {}}
                        },
                        "response": {
                            "role": "neither",
                            "timestamp": timestamp_end,
                            "token": 0,
                            "text": output,
                            "export_contents": export_contents
                        }
                    }
                })

            elif model_type == "TOOL_PICK":
                # Engine-agnostic SKILL dispatch: ask the agent's LLM which tool(s) to call
                # via a JSON reply, then run each picked tool through call_function_by_name.
                # Works on any provider — no provider-native function-calling required.
                seq = session.get_seq_history() + 1 if sub_seq == 1 else session.get_seq_history()
                setting = chain["SETTING"]

                user_input = _resolve_user_input(
                    setting["USER_INPUT"], user_query, results) if "USER_INPUT" in setting else user_query
                input = user_input

                import_contents = _resolve_contents(
                    setting["CONTENTS"], in_contents, results) if "CONTENTS" in setting else []

                agent_file = setting["AGENT_FILE"] if "AGENT_FILE" in setting and setting["AGENT_FILE"] != "USER" else in_agent_file
                add_info_base = setting.get("ADD_INFO", {})
                # SETTING.TOOL_LIST overrides the agent's SKILL.TOOL_LIST when present.
                allowed_names = setting.get("TOOL_LIST")

                timestamp_begin = str(datetime.now())
                pick_agent = dma.DigiM_Agent(agent_file)
                tool_calls, raw_response, _model_name, _pt, _rt = dmt.pick_tools(
                    pick_agent, user_input,
                    allowed_names=allowed_names,
                    situation_prompt=str(in_situation) if in_situation else "",
                )

                output_parts = []
                export_contents = []
                for call in tool_calls:
                    call_name = call.get("name", "")
                    call_input, call_add_info = dmtr.split_args_to_uniform_signature(call.get("args", {}))
                    merged_add_info = {**add_info_base, **call_add_info}
                    tool_result = dmt.call_function_by_name(
                        service_info, user_info, call_name,
                        session_id, session_name, agent_file,
                        call_input or input, import_contents, merged_add_info)
                    if inspect.isgenerator(tool_result):
                        _out = ""
                        for resp_svc, resp_usr, chunk, exp in tool_result:
                            _out += dmu.sanitize_text(str(chunk)) if chunk else ""
                            if exp is not None:
                                export_contents = exp
                        response_service_info, response_user_info = resp_svc, resp_usr
                        output_parts.append(f"[{call_name}] {_out}")
                    else:
                        response_service_info, response_user_info, _out, _exp = tool_result
                        if _exp:
                            export_contents = _exp
                        output_parts.append(f"[{call_name}] {_out}")

                output = "\n\n".join(output_parts) if output_parts else raw_response
                if not last_only or i == last_idx:
                    yield service_info, user_info, output, {}
                timestamp_end = str(datetime.now())

                session.save_history_batch(str(seq), {
                    str(sub_seq): {
                        "setting": {
                            "response_service_info": service_info,
                            "response_user_info": user_info,
                            "session_name": session.session_name,
                            "situation": in_situation,
                            "type": model_type,
                            "agent_file": agent_file,
                            "name": practice["NAME"],
                            "tool_calls": tool_calls,
                            "raw_response": raw_response,
                        },
                        "prompt": {
                            "role": "neither",
                            "timestamp": timestamp_begin,
                            "text": input,
                            "query": {"token": 0, "input": input, "text": input,
                                      "contents": import_contents, "situation": {}}
                        },
                        "response": {
                            "role": "neither",
                            "timestamp": timestamp_end,
                            "token": 0,
                            "text": output,
                            "export_contents": export_contents
                        }
                    }
                })

            # Collect results into the list
            # For multi-persona execution, use the step's starting sub_seq (stabilizes OUTPUT_<n> references)
            result["SubSEQ"] = _step_start_sub_seq
            result["TYPE"] = model_type
            result["INPUT"] = input
            chat_history_dict = session.get_history()
            seq = session.get_seq_history()
            result["IMPORT_CONTENTS"] = [
                str(Path(session.session_folder_path) / "contents" / item["file_name"])
                for item in chat_history_dict[str(seq)][str(sub_seq)]["prompt"]["query"]["contents"]
            ]
            result["OUTPUT"] = output
            result["EXPORT_CONTENTS"] = export_contents
            results.append(result)
            sub_seq += 1

        # B-5: Bulk-save SEQ-level logs
        seq = session.get_seq_history()
        session.save_history_batch(str(seq), seq_setting_data={
            "service_info": service_info,
            "user_info": user_info,
            "practice": practice
        })

        # Bulk-update the session status (collapses 7 YAML read/write cycles into 1)
        session.save_session_metadata(
            id=session.session_id,
            name=session.session_name,
            service_id=service_info["SERVICE_ID"],
            user_id=user_info["USER_ID"],
            agent=in_agent_file,
            last_update_date=str(datetime.now()),
            active="Y",
        )

    except Exception as e:
        # Persist a detailed error log (traceback + context) into the session folder
        # and into the global backend error log.
        _ctx = {
            "where": "DigiMatsuExecute_Practice",
            "session_id": session_id,
            "agent_file": in_agent_file,
            "persona_id": (in_persona or {}).get("persona_id") if isinstance(in_persona, dict) else "",
            "persona_name": (in_persona or {}).get("name") if isinstance(in_persona, dict) else "",
            "user_query_head": (user_query or "")[:200],
        }
        try:
            session.save_error_log(e, context=_ctx)
        except Exception:
            pass
        try:
            dms.save_global_error_log(e, context=_ctx)
        except Exception:
            pass
        session.save_status("UNLOCKED", error=str(e))
        raise e

    finally:
        # If the background digest is already running, it will UNLOCK there
        # During multi-persona parallel execution, the caller (MultiPersona) UNLOCKs collectively, so the inner Practice does not
        if not _digest_bg_started and not in_execution.get("_NO_UNLOCK"):
            session.save_status("UNLOCKED")


# Wrapper generator for multi-persona parallel execution.
# personas empty / single -> single call to DigiMatsuExecute_Practice (existing behavior).
# 2+ -> parallel via ThreadPoolExecutor. Each persona is saved under the same seq with a different sub_seq;
#       after completion the seq's MEMORY_FLG="N" is set (to suppress automatic memory reference next turn).
#       Digest generation is skipped (SAVE_DIGEST=False). The parallel path does not stream;
#       each worker drains its generator and yields a [STATUS] chunk per finished persona.
def DigiMatsuExecute_MultiPersona(service_info, user_info, session_id, session_name,
                                   in_agent_file, user_query,
                                   in_contents=[], in_situation={}, in_overwrite_items={},
                                   in_add_knowledge=[], in_execution={}, in_personas=None,
                                   in_rag_query_text="", in_org=None):
    in_personas = list(in_personas or [])

    # 0/1 persona: forward to the existing path (fully matches legacy behavior)
    if len(in_personas) <= 1:
        single_persona = in_personas[0] if in_personas else None
        yield from DigiMatsuExecute_Practice(
            service_info, user_info, session_id, session_name,
            in_agent_file, user_query, in_contents, in_situation,
            in_overwrite_items, in_add_knowledge, in_execution,
            in_persona=single_persona, in_rag_query_text=in_rag_query_text,
            in_org=in_org,
        )
        return

    # Phase 6: if the practice has chain.PERSONAS, delegate to the chain-level parallelism inside Practice.
    # (MultiPersona does not loop over the whole practice; pass in_personas to Practice instead.)
    # Magic-word-triggered habits' practices can also have chain.PERSONAS, so we scan every habit's practice.
    try:
        agent_for_inspect = dma.DigiM_Agent(in_agent_file)
        # Determine the habit actually triggered by the magic word and check it first
        candidate_habits = []
        try:
            magic_habit = agent_for_inspect.set_practice_by_command(user_query)
            if magic_habit:
                candidate_habits.append(magic_habit)
        except Exception:
            pass
        # Also scan all habits' practices as a fallback
        for h_key in (agent_for_inspect.agent.get("HABIT") or {}):
            if h_key not in candidate_habits:
                candidate_habits.append(h_key)

        has_chain_personas = False
        for h_key in candidate_habits:
            habit_practice_file = (agent_for_inspect.agent.get("HABIT", {})
                                   .get(h_key, {}).get("PRACTICE"))
            if not habit_practice_file:
                continue
            try:
                practice_data = dmu.read_json_file(str(Path(practice_folder_path) / habit_practice_file))
            except Exception:
                continue
            if practice_data and any(c.get("PERSONAS") for c in practice_data.get("CHAINS", [])):
                has_chain_personas = True
                break

        if has_chain_personas:
            yield from DigiMatsuExecute_Practice(
                service_info, user_info, session_id, session_name,
                in_agent_file, user_query, in_contents, in_situation,
                in_overwrite_items, in_add_knowledge, in_execution,
                in_persona=None, in_rag_query_text=in_rag_query_text,
                in_personas=in_personas, in_org=in_org,
            )
            return
    except Exception:
        pass

    # ---- 2+ personas: parallel execution ----
    max_workers_setting = system_setting_dict.get("MAX_PARALLEL_PERSONAS", 4)
    max_workers = min(len(in_personas), max(1, int(max_workers_setting)))

    # Lock the session and fix the seq up-front (avoid races between parallel workers)
    _session_base_path = in_execution.get("_SESSION_BASE_PATH", "")
    session = dms.DigiMSession(session_id, session_name, base_path=_session_base_path)
    _pre_locked = in_execution.get("_PRE_LOCKED", False)
    if session.get_status() == "LOCKED" and not _pre_locked:
        raise Exception("Session is locked. Please unlock the session before executing.")
    session.save_status("LOCKED")
    seq = session.get_seq_history() + 1

    # Build per-persona execution settings (suppress serialized processing)
    def _make_exec(idx):
        e = dict(in_execution)
        e["_PRE_LOCKED"] = True
        e["_SEQ_OVERRIDE"] = seq
        e["_SUB_SEQ_START"] = idx + 1   # split sub_seq per persona
        e["SAVE_DIGEST"] = False         # multi-persona skips digest generation
        e["_NO_UNLOCK"] = True            # each persona's Practice does not UNLOCK (this wrapper does it once at the end)
        return e

    def _run_one(idx, persona):
        last_oref = {}
        try:
            # Practice yields a 4-tuple (service_info, user_info, response_chunk, output_reference)
            for _yielded in DigiMatsuExecute_Practice(
                    service_info, user_info, session_id, session_name,
                    in_agent_file, user_query, in_contents, in_situation,
                    in_overwrite_items, in_add_knowledge, _make_exec(idx),
                    in_persona=persona, in_rag_query_text=in_rag_query_text):
                if isinstance(_yielded, tuple) and len(_yielded) >= 4:
                    _oref = _yielded[3]
                    if _oref:
                        last_oref = _oref
        except Exception as e:
            _ctx = {
                "where": "DigiMatsuExecute_MultiPersona._run_one",
                "session_id": session_id,
                "agent_file": in_agent_file,
                "persona_id": persona.get("persona_id", ""),
                "persona_name": persona.get("name", ""),
                "user_query_head": (user_query or "")[:200],
            }
            try:
                session.save_error_log(e, context=_ctx)
            except Exception:
                pass
            try:
                dms.save_global_error_log(e, context=_ctx)
            except Exception:
                pass
            return persona, str(e), last_oref
        return persona, None, last_oref

    yield service_info, user_info, f"[STATUS]Running {len(in_personas)} personas in parallel...", {}

    errors = []
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_run_one, i, p): (i, p) for i, p in enumerate(in_personas)}
            done_count = 0
            for fut in as_completed(futures):
                persona, err, _oref = fut.result()
                done_count += 1
                pid = persona.get("persona_id", "")
                pname = persona.get("name", "")
                if err:
                    errors.append((pid, err))
                    yield service_info, user_info, f"[STATUS]{pid}({pname}) error: {err}", {}
                else:
                    yield service_info, user_info, f"[STATUS]{pid}({pname}) done ({done_count}/{len(in_personas)})", {}

        # After completion: mark this seq with MEMORY_FLG="N" (so multi-persona responses are excluded from next-turn memory)
        try:
            session.chg_seq_memory_flg(str(seq), "N")
        except Exception as e:
            yield service_info, user_info, f"[STATUS]MEMORY_FLG update failed: {e}", {}
    finally:
        session.save_status("UNLOCKED")

    if errors:
        yield service_info, user_info, f"[STATUS]Done ({len(errors)} errors)", {"_persona_errors": errors}
    else:
        yield service_info, user_info, f"[STATUS]All personas done", {}
