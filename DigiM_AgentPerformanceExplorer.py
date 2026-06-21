"""Backend for Agent Performance Explorer (APE).

Scope today:
  - Tab 1 "Overview"  → activity scale aggregates
  - Tab 2 "KB Util"   → per-RAG / per-chunk reference counts + cumulative
    knowledge_utility, ready for the WebUI scatter (existing chunks of a
    Chroma collection / PageIndex pages as background, referenced ones
    highlighted, colored by QUERY_SEQ × QUERY_MODE).

The data source is `user/session*/chat_memory.json`. Every turn whose
`setting.agent_file` matches the target agent is included; this mirrors
the legacy "Relationship with Agent" deep scan in User Memory Explorer
but rolls it up agent-side instead of user-side.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterator

import DigiM_Util as dmu

logger = logging.getLogger(__name__)

_setting = dmu.read_yaml_file("setting.yaml") if hasattr(dmu, "read_yaml_file") else {}
_ARCHIVE_FOLDER = (_setting or {}).get("ARCHIVE_FOLDER", "user/archive/")


# ---------------------------------------------------------------------------
# PostgreSQL source (Session → Export DB writes here via DigiM_DB_Export)
# ---------------------------------------------------------------------------
# Tables (from DigiM_DB_Export.py):
#   digim_sessions(session_id, user_id, service_id, agent_file, ...)
#   digim_dialogs (id, session_id, seq, sub_seq, agent_file, persona_id,
#                  persona_name, model_name, prompt_timestamp,
#                  response_timestamp, user_input, response_text,
#                  prompt_tokens_total, response_tokens, ...)
#   digim_references(dialog_id, session_id, seq, sub_seq, rag_name, db_name,
#                    query_seq, query_mode, chunk_id, similarity_prompt,
#                    similarity_response, title, text_short, category, ...)

def _pg_connect():
    """Return a PG connection or None if creds/lib unavailable."""
    try:
        import psycopg2
    except ImportError:
        return None
    try:
        from dotenv import load_dotenv
        load_dotenv("system.env")
    except Exception:
        pass
    host = os.getenv("POSTGRES_HOST")
    if not host:
        return None
    try:
        return psycopg2.connect(
            host=host,
            port=int(os.getenv("POSTGRES_PORT") or 5432),
            dbname=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
            sslmode="require",
        )
    except Exception as e:
        logger.info(f"[APE] PG unavailable, falling back to file scan: {e}")
        return None


def _pg_list_agents() -> set[str]:
    """Distinct agent_file values from digim_dialogs."""
    conn = _pg_connect()
    if not conn:
        return set()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT agent_file FROM digim_dialogs "
                         "WHERE agent_file IS NOT NULL")
            return {row[0] for row in cur.fetchall() if row[0]}
    except Exception as e:
        logger.warning(f"[APE] PG list_agents failed: {e}")
        return set()
    finally:
        try: conn.close()
        except Exception: pass


def _pg_scan_turns(agent_file: str, period_from: str = "",
                    period_to: str = "") -> tuple[list[dict], set[str]]:
    """Pull all turns for an agent + their references in two SQL passes.
    Returns (turns_list, session_ids_seen) so callers can de-dupe vs file scans."""
    conn = _pg_connect()
    if not conn:
        return [], set()

    out: list[dict] = []
    seen_sids: set[str] = set()
    try:
        with conn.cursor() as cur:
            # 1) dialogs + session metadata. NOTE: the current schema does
            # not yet carry persona_id / persona_name on digim_dialogs (the
            # INSERT_DIALOG in DigiM_DB_Export references those, but they
            # haven't been migrated into the live table). APE works fine
            # without them — persona-aware splits fall back to "".
            sql_d = """
                SELECT d.id, d.session_id, d.seq, d.sub_seq, d.model_name,
                       d.prompt_timestamp, d.response_timestamp,
                       d.user_input, d.response_text,
                       d.prompt_tokens_total, d.response_tokens,
                       s.user_id
                FROM digim_dialogs d
                LEFT JOIN digim_sessions s ON s.session_id = d.session_id
                WHERE d.agent_file = %s
            """
            params = [agent_file]
            if period_from:
                sql_d += " AND (d.response_timestamp IS NULL OR d.response_timestamp >= %s::date)"
                params.append(period_from)
            if period_to:
                # +1 day so the WHOLE Period-To day is included.
                sql_d += " AND (d.response_timestamp IS NULL OR d.response_timestamp < (%s::date + 1))"
                params.append(period_to)
            cur.execute(sql_d, params)
            rows = cur.fetchall()
            if not rows:
                return [], set()

            by_id: dict = {}
            for r in rows:
                (dlg_id, sid, seq, sub_seq, model,
                 pts, rts, user_input, response_text,
                 ptok, rtok, uid) = r
                seen_sids.add(str(sid))
                ts = (str(rts) if rts else (str(pts) if pts else ""))
                by_id[dlg_id] = {
                    "session_id":   str(sid),
                    "seq":          str(seq),
                    "sub_seq":      str(sub_seq),
                    "timestamp":    ts,
                    "user_id":      uid or "",
                    "persona_id":   "",  # not in current schema
                    "persona_name": "",
                    "model":        model or "",
                    "query":        user_input or "",
                    "response":     response_text or "",
                    "prompt_token":   ptok or 0,
                    "response_token": rtok or 0,
                    "knowledge_refs": [],
                    "thinking":   {},
                    "web_search": {},
                }

            # 2) references for those dialog ids — chunked IN
            ids = list(by_id.keys())
            chunk = 1000
            for i in range(0, len(ids), chunk):
                slice_ids = ids[i:i+chunk]
                cur.execute("""
                    SELECT dialog_id, rag_name, db_name, query_seq, query_mode,
                           chunk_id, similarity_prompt, similarity_response, title
                    FROM digim_references
                    WHERE dialog_id = ANY(%s)
                """, (slice_ids,))
                for (did, rag, db, qs, qm, cid, sQ, sA, title) in cur.fetchall():
                    if did not in by_id:
                        continue
                    by_id[did]["knowledge_refs"].append({
                        "rag": rag or "", "DB": db or "",
                        "QUERY_SEQ": str(qs) if qs is not None else "0",
                        "QUERY_MODE": str(qm) if qm is not None else "NORMAL",
                        "ID": cid or "",
                        "similarity_Q": float(sQ) if sQ is not None else 0.0,
                        "similarity_A": float(sA) if sA is not None else 0.0,
                        "title": title or "",
                    })
            out = list(by_id.values())
    except Exception as e:
        logger.warning(f"[APE] PG scan_turns failed: {e}")
        return [], set()
    finally:
        try: conn.close()
        except Exception: pass
    return out, seen_sids


# ---------------------------------------------------------------------------
# Session-folder + archive scan
# ---------------------------------------------------------------------------

_SESSION_GLOB = "user/session2*"
_ARCHIVE_GLOB = "*.zip"


def _iter_chat_memory(session_glob: str = _SESSION_GLOB,
                       archive_folder: str = _ARCHIVE_FOLDER) -> Iterator[tuple[str, dict]]:
    """Yield (session_id, chat_memory_dict) over both live session folders and
    archived ZIPs.

    Archived ZIPs (`archive_old_sessions` writes these) hold one folder per
    session each containing `chat_memory.json`. Once a session is archived,
    its live folder is deleted — so the two sources cannot double-count under
    normal operation. For safety we still de-dupe by session_id (live wins)."""
    seen: set[str] = set()

    # 1) Live session folders
    for sf in sorted(glob.glob(session_glob), reverse=True):
        path = os.path.join(sf, "chat_memory.json")
        if not os.path.exists(path):
            continue
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        sid = os.path.basename(sf).replace("session", "")
        if sid in seen:
            continue
        seen.add(sid)
        yield sid, data

    # 2) Archived ZIPs — each session folder lives at the ZIP root as
    #    "sessionYYYYMMDD_HHMMSS_N/chat_memory.json"
    if archive_folder and os.path.isdir(archive_folder):
        for zip_path in sorted(glob.glob(os.path.join(archive_folder, _ARCHIVE_GLOB)),
                                reverse=True):
            try:
                zf = zipfile.ZipFile(zip_path, "r")
            except Exception:
                continue
            try:
                for name in zf.namelist():
                    if not name.endswith("/chat_memory.json"):
                        continue
                    folder = name.rsplit("/", 1)[0]
                    sid = folder.replace("session", "")
                    if sid in seen:
                        continue
                    try:
                        data = json.loads(zf.read(name).decode("utf-8"))
                    except Exception:
                        continue
                    seen.add(sid)
                    yield sid, data
            finally:
                zf.close()


def list_agents_with_history(session_glob: str = _SESSION_GLOB,
                              archive_folder: str = _ARCHIVE_FOLDER,
                              use_pg: bool = True) -> list[str]:
    """Return every agent_file that appears as the responder in any saved
    turn — across PostgreSQL (digim_dialogs), live session folders AND
    archived ZIPs. PG is the warehouse populated by Session → Export DB; we
    union with file sources so sessions that haven't been exported yet still
    show up."""
    agents: set[str] = set()
    if use_pg:
        agents |= _pg_list_agents()
    for _sid, data in _iter_chat_memory(session_glob, archive_folder):
        for seq_key, seq_block in data.items():
            if not isinstance(seq_block, dict):
                continue
            for sub_key, sub in seq_block.items():
                if sub_key == "SETTING" or not isinstance(sub, dict):
                    continue
                af = (sub.get("setting") or {}).get("agent_file") or ""
                if af:
                    agents.add(af)
    return sorted(agents)


def scan_agent_turns(agent_file: str, session_glob: str = _SESSION_GLOB,
                      period_from: str = "", period_to: str = "",
                      archive_folder: str = _ARCHIVE_FOLDER,
                      use_pg: bool = True) -> list[dict]:
    """Return a flat list of turn dicts for this agent in the given period.

    Each turn dict carries the fields APE later joins / aggregates over —
    timestamp, user/persona, query/response bytes, knowledge_rag references,
    token counts, and any thinking / web_search metadata. Knowledge entries
    are pre-parsed with `dmu.parse_log_template` so downstream code can read
    `similarity_Q` / `rag` etc. as native types.

    Source precedence: PostgreSQL (warehouse populated by Session →
    Export DB) → live session folders → archived ZIPs. Per session_id we
    take the first source that has it (PG wins, then live, then archive)
    so already-exported sessions are read from PG (fast, indexed) and
    not-yet-exported sessions are picked up directly from disk."""
    out: list[dict] = []
    seen_sids: set[str] = set()

    # 1) PostgreSQL warehouse — the primary source for any session that has
    #    been "Export DB"-ed by the user from the WebUI.
    if use_pg:
        pg_turns, pg_sids = _pg_scan_turns(agent_file, period_from, period_to)
        # Filter to period at the PG output side too (we already filtered SQL
        # but a missing response_timestamp is permissive; trust SQL plus tail
        # guard here).
        out.extend(pg_turns)
        seen_sids |= pg_sids

    # 2) + 3) Live folders + archives, skipping sessions already covered by PG.
    for sid, data in _iter_chat_memory(session_glob, archive_folder):
        if sid in seen_sids:
            continue
        seen_sids.add(sid)
        seq1_setting = (data.get("1", {}) or {}).get("SETTING", {}) or {}
        user_info = seq1_setting.get("user_info") or {}

        for seq_key, seq_block in data.items():
            if not isinstance(seq_block, dict):
                continue
            for sub_key, sub in seq_block.items():
                if sub_key == "SETTING" or not isinstance(sub, dict):
                    continue
                setting = sub.get("setting") or {}
                if setting.get("agent_file") != agent_file:
                    continue
                prompt = sub.get("prompt") or {}
                response = sub.get("response") or {}
                ts = (response.get("timestamp")
                      or prompt.get("timestamp", "") or "")
                ts_date = ts[:10] if ts else ""
                if period_from and ts_date and ts_date < period_from:
                    continue
                if period_to and ts_date and ts_date > period_to:
                    continue

                refs_raw = ((response.get("reference") or {})
                            .get("knowledge_rag") or [])
                refs: list[dict] = []
                for r in refs_raw:
                    if isinstance(r, str):
                        try:
                            refs.append(dmu.parse_log_template(r))
                        except Exception:
                            pass
                    elif isinstance(r, dict):
                        refs.append(r)

                out.append({
                    "session_id":  sid,
                    "seq":         str(seq_key),
                    "sub_seq":     str(sub_key),
                    "timestamp":   ts,
                    "user_id":     user_info.get("USER_ID") or "",
                    "persona_id":  setting.get("persona_id") or "",
                    "persona_name": setting.get("persona_name") or "",
                    "model":       (setting.get("engine") or {}).get("MODEL") or "",
                    "query":       ((prompt.get("query") or {}).get("input") or ""),
                    "response":    response.get("text") or "",
                    "prompt_token":   prompt.get("token") or 0,
                    "response_token": response.get("token") or 0,
                    "knowledge_refs": refs,
                    "thinking":   prompt.get("thinking") or {},
                    "web_search": prompt.get("web_search") or {},
                })
    return out


# ---------------------------------------------------------------------------
# Tab 1 — Overview
# ---------------------------------------------------------------------------

def overview_stats(turns: list[dict]) -> dict:
    """High-level activity stats for the Overview tab."""
    sessions = sorted({t["session_id"] for t in turns})
    users    = sorted({t["user_id"]    for t in turns if t["user_id"]})
    timestamps = sorted([t["timestamp"][:10] for t in turns if t["timestamp"]])
    total_chars = sum(len(t["query"]) + len(t["response"]) for t in turns)
    avg_turns_per_sess = round(len(turns) / max(len(sessions), 1), 1)

    # Per-month bucket for the activity bar chart
    months: Counter = Counter()
    for t in turns:
        if t["timestamp"]:
            months[t["timestamp"][:7]] += 1

    # Per-user turn counts (top N for the cohort widget)
    by_user = Counter(t["user_id"] for t in turns if t["user_id"])

    return {
        "sessions":     len(sessions),
        "turns":        len(turns),
        "users":        len(users),
        "total_chars":  total_chars,
        "first_ts":     timestamps[0]  if timestamps else "",
        "last_ts":      timestamps[-1] if timestamps else "",
        "avg_turns_per_session": avg_turns_per_sess,
        "monthly":      dict(sorted(months.items())),
        "user_top":     by_user.most_common(20),
    }


# ---------------------------------------------------------------------------
# Tab 2 — Knowledge / Book utilization
# ---------------------------------------------------------------------------

# Query-type → matplotlib color (mirrors DigiM_VAnalytics.analytics_knowledge).
# Tuple: (NORMAL=dark, others=light). Keys are str so int/str both work.
QUERY_SEQ_COLORS = {
    "0": ("deepskyblue", "lightskyblue"),
    "1": ("blue",        "cornflowerblue"),
    "2": ("purple",      "plum"),
    "default": ("gray", "lightgray"),
}


def aggregate_chunk_refs(turns: list[dict]) -> dict:
    """Reduce every parsed reference dict in `turns` into per-(rag, db, id)
    aggregates the scatter and rank widgets share.

    Returns:
        {
          "<rag_name>": {
            "<db>": {
              "<id>": {
                "ref_count": int,
                "similarity_Q_sum": float,
                "similarity_Q_max": float,
                "similarity_A_sum": float,
                "knowledge_utility_sum": float,
                "knowledge_utility_max": float,
                "title_sample": str,
                "by_query_seq": Counter[(str, str)],  # (QUERY_SEQ, QUERY_MODE)
                "timestamps": [ts, ...],
              }, ...
            }, ...
          }, ...
        }
    """
    agg: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: {
            "ref_count": 0,
            "similarity_Q_sum": 0.0,
            "similarity_Q_max": 0.0,
            "similarity_A_sum": 0.0,
            "knowledge_utility_sum": 0.0,
            "knowledge_utility_max": -1e9,
            "title_sample": "",
            "by_query_seq": Counter(),
            "timestamps": [],
        }
    )))

    for t in turns:
        for r in t["knowledge_refs"]:
            rag = str(r.get("rag", "") or r.get("RAG_NAME", ""))
            db  = str(r.get("DB", "")  or r.get("bucket", "")  or "Vector")
            cid = str(r.get("ID", "")  or r.get("id", "")     or r.get("page_id", ""))
            if not rag or not cid:
                continue
            try:
                sQ = float(r.get("similarity_Q", 0) or 0)
            except (TypeError, ValueError):
                sQ = 0.0
            try:
                sA = float(r.get("similarity_A", 0) or 0)
            except (TypeError, ValueError):
                sA = 0.0
            util = sQ - sA

            slot = agg[rag][db][cid]
            slot["ref_count"] += 1
            slot["similarity_Q_sum"] += sQ
            slot["similarity_Q_max"] = max(slot["similarity_Q_max"], sQ)
            slot["similarity_A_sum"] += sA
            slot["knowledge_utility_sum"] += util
            slot["knowledge_utility_max"] = max(slot["knowledge_utility_max"], util)

            qs = str(r.get("QUERY_SEQ", "") or "0")
            qm = str(r.get("QUERY_MODE", "") or "NORMAL")
            slot["by_query_seq"][(qs, qm)] += 1

            title = str(r.get("title", "") or "")
            if title and not slot["title_sample"]:
                slot["title_sample"] = title
            if t["timestamp"]:
                slot["timestamps"].append(t["timestamp"])

    # Convert defaultdicts to plain dicts before returning
    plain: dict = {}
    for rag, dbs in agg.items():
        plain[rag] = {}
        for db, chunks in dbs.items():
            plain[rag][db] = dict(chunks)
    return plain


def rank_chunks(rag_aggregate: dict, by: str = "ref_count",
                 top_n: int = 20) -> list[dict]:
    """Flat ranking table from one RAG's aggregate (single DB-or-multiple).

    by ∈ {"ref_count", "knowledge_utility_sum", "knowledge_utility_max"}.
    """
    rows: list[dict] = []
    for db, chunks in rag_aggregate.items():
        for cid, slot in chunks.items():
            rc = slot["ref_count"] or 1
            rows.append({
                "DB":    db,
                "ID":    cid,
                "title": slot.get("title_sample", ""),
                "ref_count": slot["ref_count"],
                "similarity_Q_avg": round(slot["similarity_Q_sum"] / rc, 3),
                "similarity_A_avg": round(slot["similarity_A_sum"] / rc, 3),
                "knowledge_utility_avg": round(slot["knowledge_utility_sum"] / rc, 3),
                "knowledge_utility_sum": round(slot["knowledge_utility_sum"], 3),
                "knowledge_utility_max": round(slot["knowledge_utility_max"], 3),
                "top_query_type": (
                    slot["by_query_seq"].most_common(1)[0][0]
                    if slot["by_query_seq"] else ("?", "?")
                ),
            })
    rows.sort(key=lambda r: r.get(by, 0), reverse=True)
    return rows[:top_n]


def dominant_query_color(by_query_seq: Counter, normalised: bool = True) -> str:
    """Pick the QUERY_SEQ × QUERY_MODE color that wins by reference count."""
    if not by_query_seq:
        return QUERY_SEQ_COLORS["default"][0]
    (qs, qm), _ = by_query_seq.most_common(1)[0]
    pair = QUERY_SEQ_COLORS.get(str(qs), QUERY_SEQ_COLORS["default"])
    return pair[0 if (qm == "NORMAL") else 1]


def rag_summary(rag_aggregate: dict) -> dict:
    """Per-RAG headline numbers for the summary panel."""
    chunk_ids: set[tuple[str, str]] = set()
    total_refs = 0
    util_sum = 0.0
    util_max = -1e9
    for db, chunks in rag_aggregate.items():
        for cid, slot in chunks.items():
            chunk_ids.add((db, cid))
            total_refs += slot["ref_count"]
            util_sum += slot["knowledge_utility_sum"]
            if slot["knowledge_utility_max"] > util_max:
                util_max = slot["knowledge_utility_max"]
    return {
        "unique_chunks":  len(chunk_ids),
        "total_refs":     total_refs,
        "utility_sum":    round(util_sum, 3),
        "utility_max":    round(util_max, 3) if total_refs else 0.0,
    }
