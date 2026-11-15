import os
import re
import ast
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from openai import AzureOpenAI

from DigiM_Util import read_yaml_file, split_display_only_sections, answer_body
import DigiM_Session as dms

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# Configuration loading
# ------------------------------------------------------------------ #
load_dotenv("system.env")

def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

# The same connection as every other store, POSTGRES_SSLMODE included. It
# was hard-wired to sslmode=require, so a local container without SSL could
# hold the chat history but never receive the analytics mirror.
import DigiM_SessionStore as _dmss
DB_CONFIG = _dmss.pg_connect_kwargs()

# Loaded from setting.yaml
_setting = read_yaml_file("setting.yaml")

SESSION_PREFIX = _setting["SESSION_FOLDER_PREFIX"]  # "session"

def _trunc(value, max_len: int) -> str | None:
    """Truncate a string to max_len characters (returns None unchanged)."""
    if value is None:
        return None
    s = str(value)
    return s[:max_len] if len(s) > max_len else s

def _safe_ts(value) -> datetime | None:
    """Convert a string to datetime (returns None on failure)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None

def _session_created_date(session_id: str) -> datetime | None:
    """Derive the creation datetime from session_id (e.g., 20260324_070640_0)."""
    m = re.match(r"^(\d{8})_(\d{6})", str(session_id))
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except Exception:
            pass
    return None

def _parse_duration(timestamp_log: str) -> float | None:
    """Seconds between the LLM start and end entries of timestamp_log."""
    if not timestamp_log:
        return None
    try:
        # The step numbers have been renumbered before (21/22 became 13/14),
        # so the two entries are found by their label, with the old numbers
        # kept for logs written in that format.
        ts = r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)"
        matches = re.findall(r"\[\d+\.[^\]]*LLM[^\]]*\]" + ts, timestamp_log)
        if len(matches) < 2:
            matches = re.findall(r"\[2[12]\.[^\]]+\]" + ts, timestamp_log)
        if len(matches) >= 2:
            t1 = datetime.fromisoformat(matches[0])
            t2 = datetime.fromisoformat(matches[1])
            return (t2 - t1).total_seconds()
    except Exception:
        pass
    return None

def _parse_knowledge_ref(ref_str: str) -> dict:
    """Parse a LOG_TEMPLATE-formatted string into a dict."""
    from DigiM_Util import parse_log_template
    return parse_log_template(ref_str)

def _get_prompt_template(prompt: dict) -> str:
    """Read the setting name from prompt.prompt_template."""
    pt = prompt.get("prompt_template")
    if isinstance(pt, dict):
        return pt.get("setting") or pt.get("name") or ""
    return str(pt) if pt else ""

def _own_words(text):
    """The user's input without the blocks a BEFORE skill injected into it.

    The executor strips them before saving now, but turns saved earlier still
    carry a web search result inside the input, which then reads as something
    the user typed.
    """
    if not text or "SKILL:" not in text:
        return text
    import DigiM_Tool as dmt
    return dmt.strip_skill_wraps(text).strip()


def _get_model_name(engine: dict) -> str:
    """Safely read MODEL from the engine dict (ignore _configs / _default contamination)."""
    return engine.get("MODEL", "") if isinstance(engine, dict) else ""


# ------------------------------------------------------------------ #
# Parser: a single session
# ------------------------------------------------------------------ #
def _answer_parts(response: dict):
    """(answer, reference sections) of a response entry.

    Analytics count, embed and score `response_text` as what the agent said,
    so the source lists shown under it go to their own column. Turns saved
    before `ref_sections` existed carry them at the end of the text.
    """
    text = response.get("text") if isinstance(response, dict) else None
    if not isinstance(text, str):
        return text, None
    body, tail = split_display_only_sections(text)
    kept = response.get("ref_sections")
    kept = kept if isinstance(kept, str) else ""
    refs = "\n\n".join(p.strip() for p in (tail, kept) if p and p.strip())
    return (body.rstrip() if tail else body), (refs or None)


_mirror_columns_checked = False


def _ensure_mirror_columns(cur):
    """Add the columns this version writes to a mirror made from older docs.

    Without them every post-turn export fails until someone runs the ALTER
    from the setup guide. Checked once per process: ALTER TABLE takes an
    exclusive lock even when the column is already there.
    """
    global _mirror_columns_checked
    if _mirror_columns_checked:
        return
    cur.execute("SELECT 1 FROM pg_attribute WHERE attrelid = 'digim_dialogs'::regclass "
                "AND attname = 'response_refs' AND NOT attisdropped")
    if cur.fetchone() is None:
        cur.execute("ALTER TABLE digim_dialogs ADD COLUMN IF NOT EXISTS response_refs TEXT")
    _mirror_columns_checked = True


def parse_session(session_id: str, status: dict, memory: dict, from_seq: int = 0) -> tuple[dict, list[dict], list[dict]]:
    """
    Returns:
        session_row  : dict  -> one row for digim_sessions
        dialog_rows  : list  -> N rows for digim_dialogs (only seq > from_seq)
        ref_rows     : list  -> N rows for digim_references
    """
    # A status.yaml rebuilt after damage can lack `id`; the caller's id is
    # the one the history was loaded under, so it is the fallback rather
    # than "" (which wrote the whole session under an empty key).
    session_id = str(status.get("id") or session_id)

    # ---------- digim_sessions ----------
    session_row = {
        "session_id":       session_id,
        "session_name":     _trunc(status.get("name"), 255),
        "user_id":          _trunc(status.get("user_id"), 128),
        "service_id":       _trunc(status.get("service_id"), 64),
        "agent_file":       _trunc(status.get("agent"), 255),
        "active":           status.get("active", "Y"),
        "status":           _trunc(status.get("status"), 32),
        "user_dialog":      _trunc(status.get("user_dialog"), 32),
        "last_update_date": _safe_ts(status.get("last_update_date")),
        "created_date":     _session_created_date(session_id),
    }

    dialog_rows = []
    ref_rows = []

    for seq_key, seq_val in memory.items():
        if not isinstance(seq_val, dict):
            continue
        try:
            seq = int(seq_key)
        except ValueError:
            continue

        if seq <= from_seq:
            continue

        setting_block = seq_val.get("SETTING", {})
        flg = setting_block.get("FLG", "Y")
        seq_memory_flg = setting_block.get("MEMORY_FLG", "Y")  # Backward compat: seq-level
        practice_name = setting_block.get("practice", {}).get("NAME", "")

        for sub_key, sub_val in seq_val.items():
            if sub_key == "SETTING" or not isinstance(sub_val, dict):
                continue
            try:
                sub_seq = int(sub_key)
            except ValueError:
                continue

            setting  = sub_val.get("setting", {})
            prompt   = sub_val.get("prompt", {})
            response = sub_val.get("response", {})
            digest   = sub_val.get("digest", {})
            log      = sub_val.get("log", {})

            engine = setting.get("engine", {})
            query  = prompt.get("query", {})
            rag_qg = prompt.get("RAG_query_genetor", {})
            meta   = prompt.get("meta_search", {}).get("date", {})
            ws     = prompt.get("web_search", {})
            ref    = response.get("reference", {})
            kr     = prompt.get("knowledge_rag", {})

            kr_refs  = ref.get("knowledge_rag", []) if isinstance(ref, dict) else []
            mem_refs = ref.get("memory", []) if isinstance(ref, dict) else []

            _answer, _refs = _answer_parts(response)

            ts_log   = log.get("timestamp_log", "") if isinstance(log, dict) else ""
            duration = _parse_duration(ts_log)

            meta_cond = meta.get("condition_list", [])
            meta_used = isinstance(meta_cond, list) and len(meta_cond) > 0

            sit = query.get("situation", {})
            # memory_flg: prefer sub_seq.setting.memory_flg; otherwise fall back to the seq-level SETTING.MEMORY_FLG
            memory_flg = setting.get("memory_flg") or seq_memory_flg
            dialog_row = {
                "session_id":                session_id,
                "seq":                       seq,
                "sub_seq":                   sub_seq,
                "flg":                       flg,
                "memory_flg":                memory_flg,
                "persona_id":                _trunc(setting.get("persona_id"), 64),
                "persona_name":              _trunc(setting.get("persona_name"), 128),
                "chain_index":               setting.get("chain_index"),
                "chain_role":                _trunc(setting.get("chain_role"), 32),
                "practice_name":             _trunc(practice_name, 128),
                "model_type":                _trunc(setting.get("type"), 32),
                "agent_file":                _trunc(setting.get("agent_file"), 255),
                "agent_name":                _trunc(setting.get("name"), 255),
                "model_name":                _trunc(_get_model_name(engine), 128),
                "prompt_template":           _trunc(_get_prompt_template(prompt), 128),
                "situation_time":            _safe_ts(sit.get("TIME") if isinstance(sit, dict) else None),
                "user_input":                _own_words(query.get("input")),
                "query_text":                query.get("text"),
                "response_text":             _answer,
                "response_refs":             _refs,
                "digest_text":               digest.get("text"),
                "prompt_timestamp":          _safe_ts(prompt.get("timestamp")),
                "response_timestamp":        _safe_ts(response.get("timestamp")),
                "response_duration_sec":     duration,
                "prompt_tokens_total":       prompt.get("token"),
                "query_tokens":              query.get("token"),
                "response_tokens":           response.get("token"),
                "digest_tokens":             digest.get("token"),
                "digest_model":              _trunc(digest.get("model"), 128),
                "rag_query_used":            bool(rag_qg),
                "rag_query_model":           _trunc(rag_qg.get("model") if rag_qg else None, 128),
                "rag_query_prompt_tokens":   rag_qg.get("prompt_token") if rag_qg else None,
                "rag_query_response_tokens": rag_qg.get("response_token") if rag_qg else None,
                "meta_search_date_used":     meta_used,
                "meta_search_date_result":   _trunc(meta.get("llm_response") if meta else None, 255),
                "web_search_used":           bool(ws),
                "knowledge_ref_count":       len(kr_refs),
                "memory_ref_count":          len(mem_refs),
            }
            dialog_rows.append(dialog_row)

            # ---------- digim_references ----------
            for ref_str in kr_refs:
                r = _parse_knowledge_ref(ref_str)
                if not r:
                    continue
                ref_row = {
                    "session_id":          session_id,
                    "seq":                 seq,
                    "sub_seq":             sub_seq,
                    "rag_name":            r.get("rag"),
                    "db_name":             r.get("DB"),
                    "query_seq":           str(r.get("QUERY_SEQ", ""))[:64],
                    "query_mode":          str(r.get("QUERY_MODE", ""))[:64],
                    "chunk_id":            _trunc(r.get("ID"), 255),
                    "chunk_timestamp":     _safe_ts(r.get("timestamp")),
                    "category":            _trunc(r.get("category"), 128),
                    "similarity_prompt":   r.get("similarity_Q"),
                    "similarity_response": r.get("similarity_A"),
                    "title":               _trunc(r.get("title"), 255),
                    "text_short":          _trunc(r.get("text_short"), 255),
                }
                ref_rows.append(ref_row)

    return session_row, dialog_rows, ref_rows

# ------------------------------------------------------------------ #
# DB writes
# ------------------------------------------------------------------ #
INSERT_SESSION = """
INSERT INTO digim_sessions
    (session_id, session_name, user_id, service_id, agent_file,
     active, status, user_dialog, last_update_date, created_date)
VALUES
    (%(session_id)s, %(session_name)s, %(user_id)s, %(service_id)s, %(agent_file)s,
     %(active)s, %(status)s, %(user_dialog)s, %(last_update_date)s, %(created_date)s)
ON CONFLICT (session_id) DO UPDATE SET
    user_id          = COALESCE(NULLIF(EXCLUDED.user_id, ''), digim_sessions.user_id),
    service_id       = COALESCE(NULLIF(EXCLUDED.service_id, ''), digim_sessions.service_id),
    session_name     = EXCLUDED.session_name,
    agent_file       = EXCLUDED.agent_file,
    active           = EXCLUDED.active,
    status           = EXCLUDED.status,
    user_dialog      = EXCLUDED.user_dialog,
    last_update_date = EXCLUDED.last_update_date;
"""

INSERT_DIALOG = """
INSERT INTO digim_dialogs
    (session_id, seq, sub_seq, flg, memory_flg,
     persona_id, persona_name, chain_index, chain_role,
     practice_name, model_type,
     agent_file, agent_name, model_name, prompt_template, situation_time,
     user_input, query_text, response_text, response_refs, digest_text,
     prompt_timestamp, response_timestamp, response_duration_sec,
     prompt_tokens_total, query_tokens, response_tokens, digest_tokens, digest_model,
     rag_query_used, rag_query_model, rag_query_prompt_tokens, rag_query_response_tokens,
     meta_search_date_used, meta_search_date_result, web_search_used,
     knowledge_ref_count, memory_ref_count)
VALUES
    (%(session_id)s, %(seq)s, %(sub_seq)s, %(flg)s, %(memory_flg)s,
     %(persona_id)s, %(persona_name)s, %(chain_index)s, %(chain_role)s,
     %(practice_name)s, %(model_type)s,
     %(agent_file)s, %(agent_name)s, %(model_name)s, %(prompt_template)s, %(situation_time)s,
     %(user_input)s, %(query_text)s, %(response_text)s, %(response_refs)s, %(digest_text)s,
     %(prompt_timestamp)s, %(response_timestamp)s, %(response_duration_sec)s,
     %(prompt_tokens_total)s, %(query_tokens)s, %(response_tokens)s, %(digest_tokens)s, %(digest_model)s,
     %(rag_query_used)s, %(rag_query_model)s, %(rag_query_prompt_tokens)s, %(rag_query_response_tokens)s,
     %(meta_search_date_used)s, %(meta_search_date_result)s, %(web_search_used)s,
     %(knowledge_ref_count)s, %(memory_ref_count)s)
ON CONFLICT (session_id, seq, sub_seq) DO NOTHING
RETURNING id;
"""

INSERT_REF = """
INSERT INTO digim_references
    (dialog_id, session_id, seq, sub_seq, rag_name, db_name,
     query_seq, query_mode, chunk_id, chunk_timestamp, category,
     similarity_prompt, similarity_response, title, text_short)
VALUES
    (%(dialog_id)s, %(session_id)s, %(seq)s, %(sub_seq)s, %(rag_name)s, %(db_name)s,
     %(query_seq)s, %(query_mode)s, %(chunk_id)s, %(chunk_timestamp)s, %(category)s,
     %(similarity_prompt)s, %(similarity_response)s, %(title)s, %(text_short)s);
"""

def write_session(cur, session_row: dict, dialog_rows: list, ref_rows: list):
    _ensure_mirror_columns(cur)
    # sessions
    cur.execute(INSERT_SESSION, session_row)

    # dialogs & references. A single turn can carry hundreds of chunk
    # references, so they are collected and sent as one batch — row-by-row
    # INSERTs put a network round trip on every chunk, which made a busy
    # session take tens of seconds to mirror.
    # References are matched to their dialog by turn, not by walking
    # knowledge_ref_count: that count includes references the parser could
    # not read, so one unreadable entry shifted every later reference onto
    # the wrong turn.
    refs_by_turn = defaultdict(list)
    for rr in ref_rows:
        refs_by_turn[(rr["seq"], rr["sub_seq"])].append(rr)
    pending_refs = []
    for dr in dialog_rows:
        cur.execute(INSERT_DIALOG, dr)
        row = cur.fetchone()
        if not row:
            # Already mirrored, and its references went in with it. Adding
            # them again is how a re-read turn used to duplicate them.
            continue
        for rr in refs_by_turn.get((dr["seq"], dr["sub_seq"]), ()):
            rr["dialog_id"] = row[0]
            pending_refs.append(rr)

    if pending_refs:
        psycopg2.extras.execute_batch(cur, INSERT_REF, pending_refs, page_size=500)

# ------------------------------------------------------------------ #
# digim_steps: what ran around the main LLM call
# ------------------------------------------------------------------ #
# One row per support agent, web search, skill, digest or rewrite of an
# answer. digim_dialogs carries only a few of their token counts, and the
# history they come from is deleted by a purge, so without these rows the
# cost and time of everything but the main call cannot be analysed later.
STEPS_DDL = """
CREATE TABLE IF NOT EXISTS digim_steps (
    session_id      VARCHAR(64)  NOT NULL,
    seq             INTEGER      NOT NULL,
    sub_seq         INTEGER      NOT NULL,
    step_no         INTEGER      NOT NULL,
    step_kind       VARCHAR(32)  NOT NULL,
    step_name       VARCHAR(255),
    phase           VARCHAR(16),
    agent_file      VARCHAR(255),
    model_name      VARCHAR(128),
    duration_sec    DOUBLE PRECISION,
    prompt_tokens   INTEGER,
    response_tokens INTEGER,
    status          VARCHAR(32),
    detail          JSONB,
    PRIMARY KEY (session_id, seq, sub_seq, step_no)
);
CREATE INDEX IF NOT EXISTS idx_digim_steps_kind_name ON digim_steps (step_kind, step_name);
CREATE INDEX IF NOT EXISTS idx_digim_steps_agent_file ON digim_steps (agent_file);
"""
_STEP_FIELDS = ("step_kind", "step_name", "phase", "agent_file", "model_name", "duration_sec",
                "prompt_tokens", "response_tokens", "status", "detail")
UPSERT_STEP = f"""
INSERT INTO digim_steps (session_id, seq, sub_seq, step_no, {", ".join(_STEP_FIELDS)})
VALUES (%(session_id)s, %(seq)s, %(sub_seq)s, %(step_no)s,
        {", ".join("%(" + f + ")s" + ("::jsonb" if f == "detail" else "") for f in _STEP_FIELDS)})
ON CONFLICT (session_id, seq, sub_seq, step_no) DO UPDATE
SET {", ".join(f + " = EXCLUDED." + f for f in _STEP_FIELDS)}
WHERE ({", ".join("digim_steps." + f for f in _STEP_FIELDS)})
      IS DISTINCT FROM ({", ".join("EXCLUDED." + f for f in _STEP_FIELDS)})
RETURNING (xmax = 0);
"""
_steps_ready = False


def _num(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _seconds_between(start, end):
    a, b = _safe_ts(start), _safe_ts(end)
    try:
        return (b - a).total_seconds() if a and b else None
    except Exception:
        return None


def _skill_phase(phase, default):
    # Saved sessions still carry the retired CONTEXT phase.
    import DigiM_Agent as dma
    return dma.normalize_skill_phase(phase, default)


def parse_steps(session_id: str, memory: dict, from_seq: int = 0) -> tuple[list[dict], set]:
    """(step rows, answers parsed) for the turns after from_seq.

    The answers are returned as well so the writer can tell an answer that
    has no steps from one that was not parsed.
    """
    rows, answers = [], set()
    for seq_key, seq_val in memory.items():
        if not isinstance(seq_val, dict) or not str(seq_key).isdigit() or int(seq_key) <= from_seq:
            continue
        seq = int(seq_key)
        thinking_seen = None
        # A turn a scheduled job started carries the job on its SETTING. Its
        # input is the job's registered prompt, not something a user typed.
        job = (seq_val.get("SETTING") or {}).get("PUSH") if isinstance(seq_val.get("SETTING"), dict) else None
        for sub_key in sorted((k for k in seq_val if str(k).isdigit()), key=int):
            entry = seq_val[sub_key]
            if not isinstance(entry, dict):
                continue
            sub_seq = int(sub_key)
            answers.add((seq, sub_seq))
            prompt = entry.get("prompt") or {}
            response = entry.get("response") or {}
            steps = []

            def add(kind, name="", phase=None, agent_file=None, model=None, duration=None,
                    prompt_tokens=None, response_tokens=None, status=None, detail=None):
                steps.append({
                    "session_id": session_id, "seq": seq, "sub_seq": sub_seq, "step_no": len(steps) + 1,
                    "step_kind": kind, "step_name": _trunc(name, 255), "phase": _trunc(phase, 16),
                    "agent_file": _trunc(agent_file, 255), "model_name": _trunc(model, 128),
                    "duration_sec": _num(duration), "prompt_tokens": _int(prompt_tokens),
                    "response_tokens": _int(response_tokens), "status": _trunc(status, 32),
                    "detail": json.dumps(detail, ensure_ascii=False, sort_keys=True) if detail else None,
                })

            if isinstance(job, dict) and job:
                add("job", job.get("job_name") or job.get("job_id"),
                    detail={"job_id": job.get("job_id"), "at": str(job.get("at") or "")})
                job = None

            th = prompt.get("thinking")
            if isinstance(th, dict) and th:
                # The turn's one thinking run is copied onto every entry of
                # the turn; counting each copy multiplies its cost.
                mark = (th.get("duration_sec"), th.get("prompt_token"), th.get("response_token"))
                if mark != thinking_seen:
                    thinking_seen = mark
                    res = th.get("result") if isinstance(th.get("result"), dict) else {}
                    add("thinking", agent_file=th.get("agent_file"), model=th.get("model"),
                        duration=th.get("duration_sec"), prompt_tokens=th.get("prompt_token"),
                        response_tokens=th.get("response_token"),
                        detail={k: res.get(k) for k in ("habit", "books", "tools", "web_search",
                                                        "rag_query_gene", "sufficient") if k in res})

            def skills(bucket, default_phase):
                if not isinstance(bucket, dict):
                    return
                for name, c in sorted(bucket.items(), key=lambda kv: (
                        _int((kv[1] or {}).get("order")) or 100 if isinstance(kv[1], dict) else 100, kv[0])):
                    if not isinstance(c, dict):
                        continue
                    if c.get("error"):
                        status = "error"
                    elif "applied" in c:
                        status = "applied" if c.get("applied") else "skipped"
                    else:
                        status = "ok"
                    chars_out = c.get("chars_out")
                    if chars_out is None and isinstance(c.get("raw"), str):
                        chars_out = len(c["raw"])
                    add("skill", name, phase=_skill_phase(c.get("phase"), default_phase), model=c.get("model"),
                        duration=c.get("duration_sec"),
                        prompt_tokens=c.get("prompt_token"), response_tokens=c.get("response_token"),
                        status=status, detail={k: v for k, v in (
                            ("merge", c.get("merge")), ("chars_in", c.get("chars_in")),
                            ("chars_out", chars_out)) if v not in (None, "")})

            skills(prompt.get("skills"), "BEFORE")

            rqg = prompt.get("RAG_query_genetor")
            if isinstance(rqg, dict) and rqg:
                gens = [g for g in (rqg.get("generators") or []) if isinstance(g, dict)]
                for i, g in enumerate(gens or [rqg], 1):
                    add("rag_query", f"#{i}", agent_file=g.get("agent_file"), model=g.get("model"),
                        duration=g.get("duration_sec"), prompt_tokens=g.get("prompt_token"),
                        response_tokens=g.get("response_token"))

            meta = (prompt.get("meta_search") or {}).get("date") if isinstance(prompt.get("meta_search"), dict) else None
            if isinstance(meta, dict) and meta:
                cond = meta.get("condition_list")
                add("meta_search", "date", agent_file=meta.get("agent_file"), model=meta.get("model"),
                    duration=meta.get("duration_sec"), prompt_tokens=meta.get("prompt_token"),
                    response_tokens=meta.get("response_token"),
                    status="used" if cond else "none")

            ws = prompt.get("web_search")
            if isinstance(ws, dict) and ws:
                skipped = bool(ws.get("skipped_reason") or ws.get("skipped_by"))
                add("web_search", ws.get("engine"), model=ws.get("model"), duration=ws.get("duration_sec"),
                    status="skipped" if skipped else "ok",
                    detail={"urls": len(ws.get("urls") or []),
                            "chars_out": len(ws.get("web_context") or "")})

            skills(response.get("skills"), "AFTER")

            dg = entry.get("digest")
            if isinstance(dg, dict) and dg and (dg.get("text") or dg.get("token")):
                add("digest", agent_file=dg.get("agent_file"), model=dg.get("model"),
                    duration=_seconds_between(dg.get("timestamp_start"), dg.get("timestamp")),
                    response_tokens=dg.get("token"))

            # Rewrites are added by the user long after the turn, so they
            # come last and never renumber the steps above.
            for rw in response.get("rewrites") or []:
                if isinstance(rw, dict):
                    add("rewrite", rw.get("skill") or ", ".join(map(str, rw.get("skills") or [])),
                        detail={"chars": rw.get("chars"), "original_chars": len(rw.get("original") or ""),
                                "timestamp": str(rw.get("timestamp") or "")})
            rows.extend(steps)
    return rows, answers


def write_steps(cur, session_id: str, step_rows: list, answers: set, dry_run: bool = False) -> dict:
    """Bring digim_steps in line with the parsed answers. Only rows that
    differ are written. Steps numbered past the end of a parsed answer are
    stale and removed; answers that were not parsed are left alone."""
    global _steps_ready
    if not _steps_ready and not dry_run:
        # Two sessions exporting for the first time would otherwise race on
        # CREATE TABLE IF NOT EXISTS, which is not atomic across sessions.
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('digim_steps:ddl'))")
        cur.execute(STEPS_DDL)
        _steps_ready = True
    out = {"steps_added": 0, "steps_updated": 0, "steps_removed": 0}
    if dry_run:
        cur.execute("SELECT to_regclass('digim_steps') IS NOT NULL")
        if not cur.fetchone()[0]:
            out["steps_added"] = len(step_rows)
            return out
    if not answers:
        return out
    counts = Counter((r["seq"], r["sub_seq"]) for r in step_rows)
    for r in step_rows:
        cur.execute(UPSERT_STEP, r)
        hit = cur.fetchone()
        if hit:
            out["steps_added" if hit[0] else "steps_updated"] += 1
    cur.execute("SELECT seq, sub_seq, MAX(step_no) FROM digim_steps WHERE session_id=%s GROUP BY 1, 2", (session_id,))
    for seq, sub_seq, top in cur.fetchall():
        keep = counts.get((seq, sub_seq), 0)
        if (seq, sub_seq) in answers and top > keep:
            cur.execute("DELETE FROM digim_steps WHERE session_id=%s AND seq=%s AND sub_seq=%s AND step_no > %s",
                        (session_id, seq, sub_seq, keep))
            out["steps_removed"] += cur.rowcount
    return out


def _saved_vector(session_id: str, file_name: str, row: int = 0):
    """One vector from a session's vecs folder, as pgvector text, or None."""
    if not file_name:
        return None
    path = Path(dms.user_folder_path) / (dms.session_folder_prefix + session_id) / "vecs" / file_name
    try:
        import numpy as np
        a = np.load(path)
        v = a[row] if a.ndim == 2 else a
        return "[" + ",".join(repr(float(x)) for x in v) + "]" if v.size else None
    except Exception:
        return None


def fill_saved_vectors(cur, session_id: str, memory: dict, from_seq: int = 0, dry_run: bool = False) -> int:
    """Give mirror rows without a vector the one the turn itself saved.

    Each turn embeds its input for retrieval and its answer for the knowledge
    references, and keeps both in the session folder. Using them costs no
    embedding call, where vectorize_dialogs would pay for the same text again.
    Rows that already have a vector are left as they are.
    """
    cur.execute("SELECT seq, sub_seq, query_vec IS NULL, response_vec IS NULL FROM digim_dialogs "
                "WHERE session_id=%s AND seq > %s AND (query_vec IS NULL OR response_vec IS NULL)",
                (session_id, from_seq))
    filled = 0
    for seq, sub_seq, need_q, need_r in cur.fetchall():
        entry = (memory.get(str(seq)) or {}).get(str(sub_seq))
        if not isinstance(entry, dict):
            continue
        query = (entry.get("prompt") or {}).get("query") or {}
        labels = query.get("query_labels") or []
        jobs = []
        # Row 0 of the query vectors is the input as typed; the others are
        # the input with history and the generated search queries.
        if need_q and labels and isinstance(labels[0], dict) and labels[0].get("kind") == "input":
            jobs.append(("query_vec", _saved_vector(session_id, query.get("queries_vec_file"))))
        if need_r:
            jobs.append(("response_vec", _saved_vector(session_id, (entry.get("response") or {}).get("answer_vec_file"))))
        for col, vec in jobs:
            if vec is None:
                continue
            filled += 1
            if not dry_run:
                cur.execute(f"UPDATE digim_dialogs SET {col} = %s::vector "
                            f"WHERE session_id=%s AND seq=%s AND sub_seq=%s AND {col} IS NULL",
                            (vec, session_id, seq, sub_seq))
    return filled


def _archive_session(session_id: str):
    """Copy the session's mirror rows to the analytics archive right away.

    The Performance Explorer reads the archive only, so without this a turn
    would not show up there until somebody ran a backup. A failure here must
    not fail the export: the next backup copies the rows anyway.
    """
    try:
        import DigiM_HistoryArchive as dmha
        dmha.archive_mirror([session_id])
    except Exception as e:
        logger.warning("[db_export] archive copy of session=%s failed: %s", session_id, e)


# ------------------------------------------------------------------ #
# Single-session entry (used by the automatic post-turn export)
# ------------------------------------------------------------------ #
def _mirrored_through(cur, session_id: str) -> int:
    """Highest seq the mirror already holds for the session.

    Exports resume from here, not from status.yaml's last_seq: that one can
    lag the mirror (a session mirrored before its status was rebuilt, or a
    crash between the commit and the status write) and then every reference
    of the mirrored turns is inserted again, or run ahead of it and mark
    turns done that were never written.
    """
    cur.execute("SELECT COALESCE(MAX(seq), 0) FROM digim_dialogs WHERE session_id=%s", (session_id,))
    return int(cur.fetchone()[0])


def _resume_from(cur, session_id: str) -> int:
    """seq to export after. The last mirrored turn is read again: an image
    generation or the next persona of a chain can be saved into that turn
    after it was exported, and starting past it lost those entries for good.
    write_session skips the rows that are already there."""
    return max(_mirrored_through(cur, session_id) - 1, 0)


def export_session(session_id: str, conn=None) -> dict:
    """Export one session's un-exported delta into sessions/dialogs/references.

    Split out of main() so a finished turn can mirror itself immediately
    instead of waiting for an operator to sweep every session. Honours the
    same db_export status bookkeeping, so a failure just leaves the session
    UNDO and the next turn retries the same range.
    """
    status = dms.get_status_data(session_id) or {}
    memory = dms.get_session_data(session_id)
    memory_max_seq = max((int(k) for k in memory if str(k).isdigit()), default=0)
    export_status, last_seq = dms.get_db_export_info(session_id)
    if not memory_max_seq:
        # Nothing to mirror. Recording it as done keeps it off the pending
        # list; its first real turn flips it back to UNDO.
        if export_status != dms.DB_EXPORT_DONE:
            dms.save_db_export_done(session_id, 0)
        return {"status": "empty", "session_id": session_id}

    if export_status == dms.DB_EXPORT_DONE and last_seq >= memory_max_seq:
        return {"status": "skip", "session_id": session_id, "last_seq": last_seq}

    dms.save_db_export_undo(session_id, last_seq)

    own_conn = conn is None
    if own_conn:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
    cur = conn.cursor()
    try:
        _lock_session(cur, session_id)
        from_seq = _resume_from(cur, session_id)
        session_row, dialog_rows, ref_rows = parse_session(session_id, status, memory, from_seq)
        write_session(cur, session_row, dialog_rows, ref_rows)
        write_steps(cur, session_row["session_id"], *parse_steps(session_row["session_id"], memory, from_seq))
        fill_saved_vectors(cur, session_row["session_id"], memory, from_seq)
        conn.commit()
        dms.save_db_export_done(session_id, memory_max_seq)
        if own_conn:
            _archive_session(session_row["session_id"])
        return {"status": "ok", "session_id": session_id,
                "dialogs": len(dialog_rows), "refs": len(ref_rows),
                "from_seq": from_seq, "last_seq": memory_max_seq}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        if own_conn:
            conn.close()


def export_session_safe(session_id: str) -> dict:
    """Never-raising wrapper for the background caller — a failed mirror must
    not surface as a chat error. The session stays UNDO and is retried."""
    try:
        return export_session(session_id)
    except Exception as e:
        logger.warning("[db_export] session=%s failed: %s", session_id, e)
        return {"status": "error", "session_id": session_id, "error": str(e)}


def _lock_session(cur, session_id: str):
    # The post-turn export and a resync both read the session's mirror rows
    # and then write them; two at once would act on what the other changes.
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("digim_mirror:" + str(session_id),))


# ------------------------------------------------------------------ #
# Resync: make a session's mirror rows match its whole history
# ------------------------------------------------------------------ #
_DIALOG_FIELDS = [c for c in re.findall(r"%\((\w+)\)s", INSERT_DIALOG)
                  if c not in ("session_id", "seq", "sub_seq")]
_REF_FIELDS = [c for c in re.findall(r"%\((\w+)\)s", INSERT_REF)
               if c not in ("dialog_id", "session_id", "seq", "sub_seq")]
_SESSION_FIELDS = ("session_name", "agent_file", "active", "status", "user_dialog", "last_update_date")
# Only filled in, never cleared: a status.yaml without them must not blank a
# row that has them.
_SESSION_IDS = ("user_id", "service_id")
# query_vec / response_vec are embeddings of these two columns.
_VECTOR_SOURCES = ("user_input", "response_text")
_TS_COLS = {"situation_time", "prompt_timestamp", "response_timestamp", "chunk_timestamp", "last_update_date"}
_NUM_COLS = {"response_duration_sec", "similarity_prompt", "similarity_response", "chain_index",
             "prompt_tokens_total", "query_tokens", "response_tokens", "digest_tokens",
             "rag_query_prompt_tokens", "rag_query_response_tokens",
             "knowledge_ref_count", "memory_ref_count"}


def _canon(col: str, v):
    """A value as the column would hold it, so what parse_session produced
    and what PostgreSQL hands back compare equal when a write would not
    change anything (strings cast to timestamps and floats, "" vs NULL)."""
    if v is None or v == "":
        return None
    if col in _TS_COLS:
        if isinstance(v, str):
            try:
                v = datetime.fromisoformat(v)
            except ValueError:
                return v
        return v.replace(tzinfo=None).isoformat(sep=" ") if isinstance(v, datetime) else v
    if col in _NUM_COLS:
        try:
            return round(float(v), 9)
        except (TypeError, ValueError):
            return v
    if isinstance(v, (bool, Decimal)):
        return v
    return str(v)


def _relink(cur, session_id: str | None = None, dry_run: bool = False) -> int:
    """Point references at the dialog of their own turn; returns how many
    were (or would be) moved."""
    cond = ("d.session_id = r.session_id AND d.seq = r.seq AND d.sub_seq = r.sub_seq "
            "AND r.dialog_id IS DISTINCT FROM d.id")
    scope, args = ("", ()) if session_id is None else (" AND r.session_id = %s", (session_id,))
    if dry_run:
        cur.execute(f"SELECT COUNT(*) FROM digim_references r JOIN digim_dialogs d ON {cond}{scope}", args)
        return int(cur.fetchone()[0])
    cur.execute(f"UPDATE digim_references r SET dialog_id = d.id FROM digim_dialogs d WHERE {cond}{scope}", args)
    return cur.rowcount


def resync_session(session_id: str, conn=None, dry_run: bool = False) -> dict:
    """Make the session's mirror rows match its whole history.

    The per-turn export only appends, so a mirrored turn stays as it was
    when exported: a later feedback, memory exclusion, rewritten answer or
    late digest never reaches it, and entries saved into a turn after its
    export were missing. The mirror is what analytics keep after a purge
    deletes the history, so the purge runs this first.

    Dialog rows keep their id, and their vectors unless the text they were
    embedded from changed (those go back to NULL for vectorize_dialogs).
    Mirror rows the history does not have are left alone: a history that
    failed to load must not erase what the mirror still holds.
    """
    status = dms.get_status_data(session_id) or {}
    memory = dms.get_session_data(session_id) or {}
    max_seq = max((int(k) for k in memory if str(k).isdigit()), default=0)
    srow, drows, rrows = parse_session(session_id, status, memory, 0)
    sid = srow["session_id"]
    rep = {"status": "ok", "session_id": sid, "dry_run": dry_run, "session_updated": False,
           "dialogs_added": 0, "dialogs_updated": 0, "vectors_cleared": 0,
           "turns_refs_rewritten": 0, "refs_removed": 0, "refs_added": 0, "refs_relinked": 0,
           "steps_added": 0, "steps_updated": 0, "steps_removed": 0, "vectors_filled": 0,
           "mirror_only_dialogs": 0}
    if not drows:
        rep["status"] = "empty"
        return rep

    own_conn = conn is None
    if own_conn:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
    cur = conn.cursor()
    try:
        _lock_session(cur, sid)
        _ensure_mirror_columns(cur)
        cur.execute(f"SELECT {', '.join(_SESSION_FIELDS + _SESSION_IDS)} FROM digim_sessions WHERE session_id=%s", (sid,))
        old_s = cur.fetchone()
        rep["session_updated"] = old_s is None or any(
            _canon(c, o) != _canon(c, srow[c]) for c, o in zip(_SESSION_FIELDS, old_s)) or any(
            srow.get(c) and not o for c, o in zip(_SESSION_IDS, old_s[len(_SESSION_FIELDS):]))
        if rep["session_updated"] and not dry_run:
            cur.execute(INSERT_SESSION, srow)

        cur.execute("SELECT id, seq, sub_seq, (query_vec IS NOT NULL OR response_vec IS NOT NULL), "
                    f"{', '.join(_DIALOG_FIELDS)} FROM digim_dialogs WHERE session_id=%s", (sid,))
        have = {(r[1], r[2]): r for r in cur.fetchall()}
        cur.execute(f"SELECT seq, sub_seq, dialog_id, {', '.join(_REF_FIELDS)} "
                    "FROM digim_references WHERE session_id=%s", (sid,))
        have_refs = defaultdict(list)
        for r in cur.fetchall():
            have_refs[(r[0], r[1])].append(r)
        want_refs = defaultdict(list)
        for rr in rrows:
            want_refs[(rr["seq"], rr["sub_seq"])].append(rr)

        for dr in drows:
            key = (dr["seq"], dr["sub_seq"])
            old = have.get(key)
            if old is None:
                rep["dialogs_added"] += 1
                dialog_id = None
                if not dry_run:
                    cur.execute(INSERT_DIALOG, dr)
                    dialog_id = cur.fetchone()[0]
            else:
                dialog_id = old[0]
                changed = [c for c, o in zip(_DIALOG_FIELDS, old[4:]) if _canon(c, o) != _canon(c, dr[c])]
                if changed:
                    rep["dialogs_updated"] += 1
                    stale = bool(old[3]) and any(c in _VECTOR_SOURCES for c in changed)
                    rep["vectors_cleared"] += int(stale)
                    if not dry_run:
                        sets = ", ".join(f"{c} = %({c})s" for c in changed)
                        if stale:
                            sets += ", query_vec = NULL, response_vec = NULL"
                        cur.execute(f"UPDATE digim_dialogs SET {sets} WHERE id = %(_dialog_id)s",
                                    dict(dr, _dialog_id=dialog_id))

            got = have_refs.pop(key, [])
            want = want_refs.get(key, [])
            same = (Counter(tuple(_canon(c, v) for c, v in zip(_REF_FIELDS, r[3:])) for r in got)
                    == Counter(tuple(_canon(c, rr[c]) for c in _REF_FIELDS) for rr in want))
            if not same:
                rep["turns_refs_rewritten"] += 1
                rep["refs_removed"] += len(got)
                rep["refs_added"] += len(want)
                if not dry_run:
                    cur.execute("DELETE FROM digim_references WHERE session_id=%s AND seq=%s AND sub_seq=%s",
                                (sid, key[0], key[1]))
                    for rr in want:
                        rr["dialog_id"] = dialog_id
                    if want:
                        psycopg2.extras.execute_batch(cur, INSERT_REF, want, page_size=500)
            else:
                rep["refs_relinked"] += sum(1 for r in got if r[2] != dialog_id)

        # Turns only the mirror has: their references may still point at
        # a neighbouring turn.
        for key, got in have_refs.items():
            if key in have:
                rep["refs_relinked"] += sum(1 for r in got if r[2] != have[key][0])
        rep["mirror_only_dialogs"] = len(set(have) - {(d["seq"], d["sub_seq"]) for d in drows})
        rep.update(write_steps(cur, sid, *parse_steps(sid, memory, 0), dry_run=dry_run))
        rep["vectors_filled"] = fill_saved_vectors(cur, sid, memory, 0, dry_run=dry_run)

        if dry_run:
            conn.rollback()
            return rep
        _relink(cur, sid)
        conn.commit()
        dms.save_db_export_done(session_id, max_seq)
        return rep
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        if own_conn:
            conn.close()


def resync_session_safe(session_id: str, dry_run: bool = False) -> dict:
    try:
        return resync_session(session_id, dry_run=dry_run)
    except Exception as e:
        logger.warning("[db_export] resync session=%s failed: %s", session_id, e)
        return {"status": "error", "session_id": session_id, "error": str(e)}


def resync_sessions(session_ids=None, dry_run: bool = False) -> dict:
    """resync_session over the given sessions, or every session that still
    has a folder. Totals plus the sessions that changed or failed."""
    if session_ids is None:
        session_ids = [str(s.get("id")) for s in dms.get_session_list() if s.get("id")]
    total = Counter()
    changed, errors = [], []
    for sid in session_ids:
        r = resync_session_safe(sid, dry_run=dry_run)
        if r.get("status") == "error":
            errors.append({"id": sid, "error": r.get("error")})
            continue
        nums = {k: v for k, v in r.items() if isinstance(v, (int, bool)) and k != "dry_run"}
        total.update({k: int(v) for k, v in nums.items()})
        if any(v for k, v in nums.items() if k != "mirror_only_dialogs"):
            changed.append(sid)
    return {"dry_run": dry_run, "sessions": len(session_ids), "changed": changed,
            "totals": dict(total), "errors": errors}


def relink_references(dry_run: bool = False) -> dict:
    """Re-attach every reference to the dialog of its own turn across the
    whole mirror. This reaches the sessions whose history is gone, which a
    resync cannot: the references' own seq / sub_seq were always right, only
    dialog_id was assigned by counting."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            moved = _relink(cur, dry_run=dry_run)
            cur.execute("SELECT COUNT(*) FROM digim_references r WHERE NOT EXISTS ("
                        "SELECT 1 FROM digim_dialogs d WHERE d.session_id = r.session_id "
                        "AND d.seq = r.seq AND d.sub_seq = r.sub_seq)")
            no_turn = int(cur.fetchone()[0])
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
        return {"dry_run": dry_run, "relinked": moved, "refs_without_their_turn": no_turn}
    finally:
        conn.close()


def auto_export_enabled() -> bool:
    """Post-turn mirroring is opt-out via DB_EXPORT_AUTO, and only meaningful
    when a PostgreSQL target is actually configured."""
    if (os.getenv("DB_EXPORT_AUTO") or "Y").upper() in ("N", "NO", "0", "FALSE"):
        return False
    return bool(DB_CONFIG.get("host") and DB_CONFIG.get("dbname"))


def pending_sessions() -> list:
    """Sessions whose analytics mirror is behind. Every history save flips a
    DONE session back to UNDO, so the status alone says which ones need work
    and no history has to be read to find them. The per-turn auto-export only
    retries a session when it gets its next turn, so an idle session that
    failed once stays here until something retries it."""
    out = []
    for status in dms.get_session_list():
        sid = str(status.get("id", ""))
        st, _ = dms.get_db_export_info(sid)
        if st != dms.DB_EXPORT_DONE:
            out.append(sid)
    return out


def retry_pending() -> dict:
    """Export the sessions `pending_sessions()` names. Returns counts plus the
    errors, which a caller should show rather than swallow."""
    rep = {"pending": 0, "exported": 0, "skipped": 0, "empty": 0, "errors": []}
    ids = pending_sessions()
    rep["pending"] = len(ids)
    for sid in ids:
        r = export_session_safe(sid)
        st = r.get("status")
        if st == "ok":
            rep["exported"] += 1
        elif st == "skip":
            rep["skipped"] += 1
        elif st == "empty":
            rep["empty"] += 1
        else:
            rep["errors"].append({"id": sid, "error": r.get("error", st)})
    logger.info("[db_export] retry_pending: %s", {k: v for k, v in rep.items() if k != "errors"})
    return rep


def count_unvectorized() -> int:
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM digim_dialogs WHERE query_vec IS NULL")
            return int(cur.fetchone()[0])
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Main entry
# ------------------------------------------------------------------ #
def main(full: bool = False):
    """Catch-up export. By default only the pending sessions are touched;
    `full` re-reads every session's history the way this used to, for the
    case where the status bookkeeping itself is suspect."""
    if not full:
        return retry_pending()
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()

    sessions = dms.get_session_list()
    total = len(sessions)
    done = skip = error = 0

    for status in sessions:
        session_id = str(status.get("id", ""))
        folder_name = SESSION_PREFIX + session_id

        memory = dms.get_session_data(session_id)
        memory_max_seq = max((int(k) for k in memory if k.isdigit()), default=0)

        export_status, last_seq = dms.get_db_export_info(session_id)

        if export_status == dms.DB_EXPORT_DONE:
            if last_seq >= memory_max_seq:
                logger.info(f"[SKIP] {folder_name}: already written (last_seq={last_seq})")
                skip += 1
                continue
            # A newer seq exists -> mark as UNDO and write the delta
            dms.save_db_export_undo(session_id, last_seq)
            logger.info(f"[UNDO] {folder_name}: appending seq {last_seq+1}-{memory_max_seq}")
        else:
            # Not yet exported or already UNDO -> mark as UNDO (last_seq=0 or the existing value)
            dms.save_db_export_undo(session_id, last_seq)
            logger.info(f"[UNDO] {folder_name}: writing seq {last_seq+1}-{memory_max_seq}")

        try:
            _lock_session(cur, session_id)
            from_seq = _resume_from(cur, session_id)
            session_row, dialog_rows, ref_rows = parse_session(session_id, status, memory, from_seq)
            write_session(cur, session_row, dialog_rows, ref_rows)
            write_steps(cur, session_row["session_id"], *parse_steps(session_row["session_id"], memory, from_seq))
            fill_saved_vectors(cur, session_row["session_id"], memory, from_seq)
            conn.commit()
            dms.save_db_export_done(session_id, memory_max_seq)
            logger.info(f"[OK]   {folder_name}: dialogs={len(dialog_rows)} refs={len(ref_rows)} last_seq={memory_max_seq}")
            done += 1
        except Exception as e:
            conn.rollback()
            logger.error(f"[ERR]  {folder_name}: {e}")
            error += 1

    cur.close()
    conn.close()
    logger.info(f"Done -- total={total}: wrote={done} skipped={skip} errors={error}")

# ------------------------------------------------------------------ #
# Vectorization
# ------------------------------------------------------------------ #
EMBED_MAX_CHARS = 4000  # ~2 tokens per Japanese character; safety margin against the 8192-token limit
EMBED_BATCH     = 10    # Records per batch
EMBED_SLEEP     = 1.0   # Seconds to sleep between batches (rate-limit mitigation)

def dialog_embedder():
    """embed(texts) -> vectors, or None when embedding is not configured.

    Everything that fills query_vec / response_vec goes through this, so the
    vectors of the mirror and of its archive stay comparable.
    """
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_api_key  = os.getenv("AZURE_OPENAI_API_KEY")
    embed_model    = os.getenv("AZURE_OPENAI_EMBED_MODEL", "text-embedding-3-large")

    if not all([azure_endpoint, azure_api_key]):
        return None

    client = AzureOpenAI(
        azure_endpoint=azure_endpoint,
        api_key=azure_api_key,
        api_version="2024-12-01-preview",
    )

    def _embed(texts):
        res = client.embeddings.create(
            input=[t[:EMBED_MAX_CHARS].replace("\n", " ") for t in texts],
            model=embed_model,
        )
        return [d.embedding for d in sorted(res.data, key=lambda d: d.index)]

    return _embed


def vectorize_dialogs():
    """Populate query_vec / response_vec for un-vectorized digim_dialogs rows."""
    embed = dialog_embedder()
    if embed is None:
        logger.warning("[VEC] AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY are not set; skipping")
        return

    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("""
        SELECT COUNT(*) FROM digim_dialogs
        WHERE query_vec IS NULL
          AND user_input IS NOT NULL
          AND response_text IS NOT NULL
    """)
    total = cur.fetchone()[0]
    logger.info(f"[VEC] un-vectorized rows: {total}")

    if total == 0:
        cur.close()
        conn.close()
        return

    done = error = 0

    while True:
        cur.execute("""
            SELECT id, user_input, response_text FROM digim_dialogs
            WHERE query_vec IS NULL
              AND user_input IS NOT NULL
              AND response_text IS NOT NULL
            ORDER BY id
            LIMIT %s
        """, (EMBED_BATCH,))
        rows = cur.fetchall()
        if not rows:
            break

        for row in rows:
            try:
                query_vec, response_vec = embed([row["user_input"], answer_body(row["response_text"])])

                cur.execute("""
                    UPDATE digim_dialogs
                    SET query_vec = %s::vector, response_vec = %s::vector
                    WHERE id = %s
                """, (str(query_vec), str(response_vec), row["id"]))
                conn.commit()
                done += 1

            except Exception as e:
                conn.rollback()
                logger.error(f"[VEC][ERR] id={row['id']}: {e}")
                error += 1

        logger.info(f"[VEC] progress: {done}/{total} done (errors: {error})")
        time.sleep(EMBED_SLEEP)

    cur.close()
    conn.close()
    logger.info(f"[VEC] done -- success: {done} / errors: {error}")


def _cli(argv) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="DigiM_DB_Export.py",
                                 description="Mirror chat history into digim_sessions / dialogs / references.")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("pending", help="export the sessions whose mirror is behind (the default)")
    sub.add_parser("full", help="re-read every session and append what the mirror lacks")
    p = sub.add_parser("resync", help="make the mirror rows match the history (every session with a folder "
                                      "unless --session is given)")
    p.add_argument("--session", action="append", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--archive", action="store_true",
                   help="then copy the mirror to the analytics archive tables, as a backup would")
    p = sub.add_parser("relink", help="re-attach every reference to the dialog of its own turn")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("vectorize", help="embed the dialogs that have no vectors yet (billed)")
    a = ap.parse_args(argv[1:])
    if a.cmd in (None, "pending"):
        out = retry_pending()
    elif a.cmd == "full":
        out = main(full=True)
    elif a.cmd == "resync":
        out = resync_sessions(a.session, dry_run=a.dry_run)
        if len(out["changed"]) > 20:
            out["changed"] = out["changed"][:20] + [f"... {len(out['changed']) - 20} more"]
        if a.archive:
            import DigiM_HistoryArchive as dmha
            out["archive"] = dmha._mirror_summary(dmha.archive_mirror(a.session, dry_run=a.dry_run))
    elif a.cmd == "relink":
        out = relink_references(dry_run=a.dry_run)
    else:
        out = vectorize_dialogs()
    if out is not None:
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv))
