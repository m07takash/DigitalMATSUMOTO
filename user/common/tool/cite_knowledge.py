"""Tool plugin: Reference Knowledge (the `cite_knowledge` flag skill).

Works out which KNOWLEDGE chunks an answer actually drew on, and renders the
`## Reference Knowledge` section from that. `cite_knowledge` sets an execution
flag rather than dispatching a function, but the work and the prompt handling
are tool content, so they live here instead of in the executor.

Pipeline, in the order the executor calls it:

    build_manifest()              every non-book chunk this turn retrieved
    refresh_chunk_util()          re-stamp sim_a / util once the answer is embedded
    detect_used_chunks()          second-pass selector LLM: which were used
    build_util_fallback_entries() when the selector returned nothing
    build_knowledge_section()     the visible section

Nothing is registered: there is no tool to dispatch by name.
`DigiM_Tool.__getattr__` resolves these as `dmt.<name>`.
"""
from pathlib import Path

import re

import DigiM_Agent as dma
import DigiM_Util as dmu

system_setting_dict = dmu.read_yaml_file("setting.yaml")
practice_folder_path = system_setting_dict["PRACTICE_FOLDER"]


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


def build_manifest(knowledge_selected, agent_data):
    """Build a lookup of every non-book chunk in this turn's retrieval.

    Returns {(rag, id): {rag, id, title, body, sim_q, sim_a, util}, ...}.
    No cap — the second-pass selector needs to see every chunk to decide
    what was actually referenced (the user explicitly asked us to stop
    truncating at top-60). Empty when no non-book chunks were retrieved.

    Selection of "which chunks the LLM actually used" is delegated to a
    dedicated support agent call (see detect_used_chunks below), so we
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


def detect_used_chunks(service_info, user_info, session_id, session_name,
                         selector_agent_file, primary_response, chunk_lookup):
    """Second-pass LLM call that decides which chunks the primary answer
    actually referenced. Returns [(rag, cid, usage_note), ...] preserving
    the selector's order, dropping any (rag, cid) pair that doesn't map back
    to the manifest.

    The selector agent (SUPPORT_AGENT.KNOWLEDGE_USAGE_SELECTOR, defaults to
    agent_58KnowledgeUsageSelector.json) is a lightweight support
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
        selector_agent_file = "agent_58KnowledgeUsageSelector.json"
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


def refresh_chunk_util(chunk_lookup, knowledge_selected):
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


def build_util_fallback_entries(chunk_lookup):
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


def build_knowledge_section(entries, chunk_lookup, title_cap=20,
                              note_cap=30):
    """Assemble the ## Reference Knowledge section from the selector output.

    entries       — list of (rag, id, usage_note) from detect_used_chunks
                    or build_util_fallback_entries.
    chunk_lookup  — {(rag, id): {rag, id, title, util, ...}} from
                    build_manifest.

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
