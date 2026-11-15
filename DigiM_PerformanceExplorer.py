"""Performance Explorer backend (User section).

Reads the analytics archive tables only, so a session kept as JSON is out of
scope until it has been mirrored and backed up.
"""
import os
import re
import json
import math
import hashlib
import logging
import unicodedata
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import psycopg2

import DigiM_MstStore as dmms
import DigiM_SessionStore as dmss

logger = logging.getLogger(__name__)

T_SESSIONS = "digim_sessions_archive"
T_DIALOGS = "digim_dialogs_archive"
T_REFS = "digim_references_archive"
T_STEPS = "digim_steps_archive"
T_SCORES = "digim_pe_scores"

NO_GROUP = "(no group)"
USER_UNKNOWN = "(unknown)"

# Rows that are not an agent's answer to the user: job pushes and the
# bookkeeping entries of skills and tools.
_NON_ANSWER_TYPES = ("PUSH", "SKILL", "TOOL", "TOOL_PICK")

# text-embedding-3 vectors are trained so that a prefix is itself a usable
# embedding. The first 256 dims keep the neighbourhood structure clustering
# needs and cut the transfer of 3072-dim vectors by 12x.
VEC_DIMS = 256

# Sessions these services own are run by the system (jobs, benchmarks, the
# support-agent test), not by a person typing.
SYSTEM_SERVICES = frozenset(["Scheduler", "Benchmark", "SupportEval"])

MAX_CLUSTERS = 10
SCORE_BANDS = [(80, 100), (60, 79), (40, 59), (20, 39), (0, 19)]

STOP_WORDS = frozenset([
    "こと", "もの", "ため", "それ", "これ", "あれ", "よう", "ところ", "とき", "そう", "どこ", "ここ", "そこ",
    "人", "自分", "相手", "方", "今", "前", "後", "場合", "必要", "重要", "意味", "以下", "以上", "一つ",
    "問題", "結果", "状況", "全体", "部分", "感じ", "点", "面", "的", "性", "化", "等", "他", "中", "上", "下",
    "情報", "データ", "内容", "対象", "傾向", "話", "気", "目", "手", "力", "さん", "たち", "ほう", "わけ",
    "可能", "可能性", "回答", "質問", "お願い", "こちら", "そちら", "みたい", "はず", "つもり", "あと", "まま",
])


def _connect(readonly=True):
    conn = psycopg2.connect(**dmss.pg_connect_kwargs())
    if readonly:
        conn.set_session(readonly=True, autocommit=True)
    return conn


def available():
    if not (os.getenv("POSTGRES_HOST") and os.getenv("POSTGRES_DB")):
        return False, "PostgreSQL is not configured (POSTGRES_HOST / POSTGRES_DB)."
    try:
        with closing(_connect()) as conn, conn.cursor() as cur:
            for t in (T_SESSIONS, T_DIALOGS, T_REFS):
                cur.execute("SELECT to_regclass(%s)", (t,))
                if cur.fetchone()[0] is None:
                    return False, f"{t} does not exist yet. Run History Retention > Backup Now once."
    except Exception as e:
        return False, f"PostgreSQL is not reachable: {e}"
    return True, ""


# ---------------------------------------------------------------- time

def display_tz():
    return ZoneInfo(os.getenv("TIMEZONE") or "Asia/Tokyo")


def _stored_tz():
    # History timestamps are naive values of the writing process's local
    # clock, which is not the timezone people read the charts in.
    return datetime.now().astimezone().tzinfo


def to_stored(dt):
    return dt.replace(tzinfo=display_tz()).astimezone(_stored_tz()).replace(tzinfo=None)


def to_display(dt):
    return dt.replace(tzinfo=_stored_tz()).astimezone(display_tz()).replace(tzinfo=None)


def _series_to_display(s):
    return s.dt.tz_localize(_stored_tz()).dt.tz_convert(display_tz()).dt.tz_localize(None)


def pick_bucket(p_from, p_to):
    days = (p_to - p_from).total_seconds() / 86400.0
    if days <= 3:
        return "hour"
    if days <= 62:
        return "day"
    if days <= 370:
        return "week"
    return "month"


def bucket_start(ts, bucket):
    if bucket == "hour":
        return ts.dt.floor("h")
    if bucket == "day":
        return ts.dt.normalize()
    if bucket == "week":
        return (ts - pd.to_timedelta(ts.dt.weekday, unit="D")).dt.normalize()
    return ts.dt.to_period("M").dt.to_timestamp()


def bucket_label(ts, bucket):
    if bucket == "hour":
        return ts.strftime("%m-%d %H:00")
    if bucket == "day":
        return ts.strftime("%Y-%m-%d")
    if bucket == "week":
        return ts.strftime("week of %Y-%m-%d")
    return ts.strftime("%Y-%m")


def _bucket_range(p_from, p_to, bucket):
    freq = {"hour": "h", "day": "D", "week": "W-MON", "month": "MS"}[bucket]
    first = bucket_start(pd.Series([pd.Timestamp(p_from)]), bucket).iloc[0]
    return pd.date_range(first, pd.Timestamp(p_to), freq=freq)


# ---------------------------------------------------------------- scope

def user_groups():
    out = {}
    for uid, info in (dmms.load("users") or {}).items():
        raw = info.get("Group", "") if isinstance(info, dict) else ""
        out[uid] = [g for g in raw if g] if isinstance(raw, list) else ([raw] if raw else [])
    return out


def _groups_of(user_id, gmap, recorded=None):
    # The groups recorded at backup time win: they survive the user leaving
    # the master and do not move when the user changes group later.
    if isinstance(recorded, (list, tuple)) and len(recorded):
        return list(recorded)
    return gmap.get(user_id) or [NO_GROUP]


_HAS = {}


def _exists(cur, table, column=None):
    """Whether an archive table (or one of its columns) exists yet. Both the
    steps archive and user_groups appear with the first backup after an
    upgrade, so only a positive answer is remembered."""
    key = (table, column)
    if not _HAS.get(key):
        if column is None:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
        else:
            cur.execute("SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass(%s) "
                        "AND attname = %s AND NOT attisdropped)", (table, column))
        _HAS[key] = bool(cur.fetchone()[0])
    return _HAS[key]


def archive_lag():
    """What the mirror holds that the archive does not have yet.

    Both sections read the archive only, so rows a backup has not copied are
    silently missing from every figure. Empty dict when the archive is current
    or the mirror is not there to compare with.
    """
    out = {}
    try:
        with closing(_connect()) as conn, conn.cursor() as cur:
            if not _exists(cur, "digim_dialogs"):
                return out
            cur.execute(f"""
                SELECT count(*) FILTER (WHERE a.session_id IS NULL),
                       count(*) FILTER (WHERE a.session_id IS NOT NULL AND d.query_vec IS NOT NULL AND a.query_vec IS NULL),
                       count(*) FILTER (WHERE a.session_id IS NOT NULL
                                        AND a.user_input IS DISTINCT FROM d.user_input)
                FROM digim_dialogs d LEFT JOIN {T_DIALOGS} a
                  ON a.session_id = d.session_id AND a.seq = d.seq AND a.sub_seq = d.sub_seq""")
            answers, vectors, changed = cur.fetchone()
            steps = 0
            if _exists(cur, "digim_steps"):
                if _exists(cur, T_STEPS):
                    cur.execute(f"SELECT (SELECT count(*) FROM digim_steps) - (SELECT count(*) FROM {T_STEPS})")
                    steps = max(int(cur.fetchone()[0]), 0)
                else:
                    cur.execute("SELECT count(*) FROM digim_steps")
                    steps = int(cur.fetchone()[0])
            for k, v in (("answers", answers), ("vectors", vectors), ("changed", changed), ("steps", steps)):
                if v:
                    out[k] = int(v)
    except Exception as e:
        logger.warning(f"[PE] archive lag is not readable: {e}")
    return out


def refresh_archive():
    """Copy the mirror to the archive now: what a backup does for the analytics tables."""
    import DigiM_HistoryArchive as dmha
    m = dmha.archive_mirror()
    _HAS.clear()
    return dmha._mirror_summary(m)


def filter_options():
    with closing(_connect()) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT user_id, count(*) FROM {T_SESSIONS} GROUP BY 1 ORDER BY 2 DESC")
        users = [(u or USER_UNKNOWN) for u, _ in cur.fetchall()]
        cur.execute(f"SELECT agent_file, count(*) FROM {T_DIALOGS} WHERE flg = 'Y' GROUP BY 1 ORDER BY 2 DESC")
        agents = [a for a, _ in cur.fetchall() if a]
        cur.execute(f"SELECT min(prompt_timestamp), max(prompt_timestamp) FROM {T_DIALOGS}")
        t_min, t_max = cur.fetchone()
        recorded = set()
        if _exists(cur, T_SESSIONS, "user_groups"):
            cur.execute(f"SELECT DISTINCT unnest(user_groups) FROM {T_SESSIONS}")
            recorded = {g for g, in cur.fetchall() if g}
    gmap = user_groups()
    groups = sorted({g for u in users for g in _groups_of(u, gmap)} | recorded)
    return {
        "users": list(dict.fromkeys(users)), "groups": groups, "agents": agents,
        "first": to_display(t_min) if t_min else None,
        "last": to_display(t_max) if t_max else None,
    }


def _fetch_rows(p_from, p_to, with_deleted=False):
    """Every answer row of the turns that started inside [p_from, p_to)."""
    live = "" if with_deleted else " WHERE flg = 'Y'"
    with closing(_connect()) as conn:
        with conn.cursor() as cur:
            groups = "s.user_groups" if _exists(cur, T_SESSIONS, "user_groups") else "NULL::text[]"
        sql = f"""
            WITH t AS (
                SELECT session_id, seq, min(prompt_timestamp) AS turn_ts
                FROM {T_DIALOGS}{live} GROUP BY 1, 2
                HAVING min(prompt_timestamp) >= %s AND min(prompt_timestamp) < %s)
            SELECT d.session_id, d.seq, d.sub_seq, t.turn_ts, s.user_id, s.session_name, s.service_id,
                   {groups} AS user_groups,
                   d.agent_file, d.agent_name, d.model_name, d.model_type, d.practice_name,
                   d.flg, d.memory_flg, d.user_input, d.response_text,
                   EXTRACT(EPOCH FROM (d.response_timestamp - d.prompt_timestamp)) AS answer_sec,
                   d.response_duration_sec AS llm_sec,
                   d.prompt_tokens_total, d.response_tokens, d.knowledge_ref_count,
                   (d.query_vec IS NOT NULL) AS has_qvec, (d.response_vec IS NOT NULL) AS has_rvec
            FROM t JOIN {T_DIALOGS} d USING (session_id, seq)
                   LEFT JOIN {T_SESSIONS} s USING (session_id)
            {live.replace("flg", "d.flg")}
            ORDER BY d.session_id, d.seq, d.sub_seq"""
        df = pd.read_sql_query(sql, conn, params=(to_stored(p_from), to_stored(p_to)))
    if df.empty:
        return df
    df["user_id"] = df["user_id"].fillna("").replace("", USER_UNKNOWN)
    df["turn"] = df["session_id"] + ":" + df["seq"].astype(str)
    df["akey"] = df["turn"] + ":" + df["sub_seq"].astype(str)
    for c in ("user_input", "response_text", "agent_file", "agent_name", "model_name", "practice_name",
              "session_name", "service_id"):
        df[c] = df[c].fillna("")
    # Turns saved before the executor stripped them still carry the block a
    # BEFORE skill injected (a whole web search result) inside the input.
    blocks = df["user_input"].str.contains("SKILL:", regex=False)
    if blocks.any():
        import DigiM_Tool as dmt
        df.loc[blocks, "user_input"] = df.loc[blocks, "user_input"].map(lambda t: dmt.strip_skill_wraps(t).strip())
    df["had_skill_block"] = blocks
    # Turns mirrored before the reference sections moved out of the answer
    # still end with the source lists shown under it.
    import DigiM_Util as dmu
    df["response_text"] = df["response_text"].map(dmu.answer_body)
    # A diagram is part of the answer but not prose: its source would count
    # as length and come up as the answer's words.
    df["response_prose"] = df["response_text"].str.replace(_MERMAID_RE, "", regex=True).str.strip()
    # A column that is NULL on every row arrives as object, which breaks the
    # aggregations.
    for c in ("answer_sec", "llm_sec", "prompt_tokens_total", "response_tokens", "knowledge_ref_count"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df[~df["model_type"].isin(_NON_ANSWER_TYPES)].copy()


def _turns_of(answers):
    # The user's own words are on the first answer row; later rows of a chain
    # carry the previous agent's output as their input.
    turns = (answers.groupby("turn", sort=False).head(1)
             [["turn", "session_id", "seq", "sub_seq", "turn_ts", "user_id", "session_name", "service_id",
               "user_input", "has_qvec", "user_groups", "had_skill_block"]]
             .rename(columns={"sub_seq": "input_sub_seq"}).copy())
    turns["ts"] = _series_to_display(turns["turn_ts"])
    return turns


def load_scope(p_from, p_to, axis="Group", users=None, groups=None, agents=None):
    """Turns that started inside [p_from, p_to) (display timezone), with their answers.

    A turn is one user input; its answers are every agent row of that turn,
    because a chain or a parallel persona run answers one input several times.
    """
    answers = _fetch_rows(p_from, p_to)
    scope = {"period": (p_from, p_to), "axis": axis, "bucket": pick_bucket(p_from, p_to),
             "filters": {"users": list(users or []), "groups": list(groups or []), "agents": list(agents or [])}}
    scope["left_out"] = {"job_turns": 0, "system_turns": 0, "skill_blocks": 0}
    if answers.empty:
        scope["turns"], scope["answers"] = pd.DataFrame(), pd.DataFrame()
        return scope
    turns = _turns_of(answers)

    # This section is about what people typed. A turn a scheduled job started,
    # or one in a session a system service owns, has a registered prompt as
    # its input.
    jobs = _job_turns(sorted(set(turns["session_id"])))
    is_job = turns["turn"].isin(jobs)
    is_system = turns["service_id"].isin(SYSTEM_SERVICES) & ~is_job
    scope["left_out"] = {"job_turns": int(is_job.sum()), "system_turns": int(is_system.sum()),
                         "skill_blocks": int(turns.loc[~(is_job | is_system), "had_skill_block"].sum())}
    turns = turns[~(is_job | is_system)]

    gmap = user_groups()
    turns["groups"] = [_groups_of(u, gmap, r) for u, r in zip(turns["user_id"], turns["user_groups"])]
    if users:
        turns = turns[turns["user_id"].isin(users)]
    if groups:
        turns = turns[turns["groups"].map(lambda gs: any(g in groups for g in gs))]
        turns["groups"] = turns["groups"].map(lambda gs: [g for g in gs if g in groups])
    if agents:
        answers = answers[answers["agent_file"].isin(agents)]
    turns = turns[turns["turn"].isin(set(answers["turn"]))].reset_index(drop=True)
    answers = answers[answers["turn"].isin(set(turns["turn"]))].reset_index(drop=True)
    turns["axis"] = turns["groups"] if axis == "Group" else turns["user_id"].map(lambda u: [u])

    scope["turns"], scope["answers"] = turns, answers
    return scope


def _job_turns(session_ids):
    """Turns a scheduled job started, as far as the step records know."""
    if not session_ids:
        return set()
    with closing(_connect()) as conn, conn.cursor() as cur:
        if not _exists(cur, T_STEPS):
            return set()
        cur.execute(f"SELECT DISTINCT session_id, seq FROM {T_STEPS} "
                    f"WHERE step_kind = 'job' AND session_id = ANY(%s)", (list(session_ids),))
        return {f"{s}:{q}" for s, q in cur.fetchall()}


def axis_frame(scope):
    """One row per (turn, axis value): a user in two groups counts in both."""
    t = scope["turns"]
    if t.empty:
        return t.assign(axis_value=[])
    return t.explode("axis").rename(columns={"axis": "axis_value"}).reset_index(drop=True)


# ---------------------------------------------------------------- usage

def usage_summary(scope):
    t, a = scope["turns"], scope["answers"]
    return {
        "turns": len(t), "sessions": t["session_id"].nunique() if len(t) else 0,
        "users": t["user_id"].nunique() if len(t) else 0, "answers": len(a),
        "references": len(scope["refs"]) if "refs" in scope else 0,
    }


def usage_heatmap(scope):
    t = scope["turns"]
    out = pd.DataFrame({"weekday": t["ts"].dt.weekday, "hour": t["ts"].dt.hour})
    out = out.groupby(["weekday", "hour"]).size().rename("turns").reset_index()
    out["day"] = out["weekday"].map(dict(enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])))
    return out


OTHER = "(other)"


def axis_values(scope, max_series=8):
    """The axis values that get their own series: the busiest ones, in name order."""
    x = axis_frame(scope)
    if x.empty:
        return []
    return sorted(x["axis_value"].value_counts().head(max_series).index)


def usage_timeline(scope, keep):
    x = axis_frame(scope)
    x["bucket"] = bucket_start(x["ts"], scope["bucket"])
    x["series"] = x["axis_value"].where(x["axis_value"].isin(keep), OTHER)
    return x.groupby(["bucket", "series"]).size().rename("turns").reset_index()


def usage_by_axis(scope):
    x = axis_frame(scope)
    a = scope["answers"]
    x["input_chars"] = x["user_input"].str.len()
    g = x.groupby("axis_value").agg(
        turns=("turn", "size"), sessions=("session_id", "nunique"), users=("user_id", "nunique"),
        active_days=("ts", lambda s: s.dt.normalize().nunique()), avg_input_chars=("input_chars", "mean"))
    per_turn = a.assign(chars=a["response_prose"].str.len()).groupby("turn").agg(
        answers=("akey", "size"), answer_chars=("chars", "mean"), sec=("answer_sec", "mean"),
        tokens=("response_tokens", "sum"), refs=("knowledge_ref_count", "sum"))
    m = x.merge(per_turn, left_on="turn", right_index=True, how="left").groupby("axis_value").agg(
        answers=("answers", "sum"), avg_answer_chars=("answer_chars", "mean"),
        avg_answer_sec=("sec", "mean"), response_tokens=("tokens", "sum"), references=("refs", "sum"))
    out = g.join(m).reset_index().sort_values("turns", ascending=False)
    for c in ("avg_input_chars", "avg_answer_chars"):
        out[c] = out[c].round(0)
    out["avg_answer_sec"] = out["avg_answer_sec"].round(1)
    return out


# ---------------------------------------------------------------- keywords

_URL_RE = re.compile(r"https?://\S+")
_MERMAID_RE = re.compile(r"```mermaid\s.*?```", re.DOTALL)
_KEEP_NOUN = {"一般", "固有名詞", "サ変接続"}
_KEEP_SUFFIX = {"一般", "サ変接続"}
_TAGGER = None


def _tagger():
    global _TAGGER
    if _TAGGER is None:
        import MeCab
        _TAGGER = MeCab.Tagger()
        # The first parse on a fresh tagger can hand back nodes whose surface
        # is already freed.
        _TAGGER.parse("")
    return _TAGGER


def _valid_term(w):
    if len(w) < 2 or len(w) > 30:
        return False
    if w.isascii():
        return any(c.isalpha() for c in w)
    return not all(c.isdigit() or unicodedata.category(c).startswith(("P", "S")) for c in w)


def extract_terms(text, limit=6000):
    """Compound nouns of a text, once each, in order of appearance."""
    text = unicodedata.normalize("NFKC", _URL_RE.sub(" ", text or ""))[:limit]
    out, seen, buf = [], set(), []

    def flush():
        if buf:
            w = "".join(buf).strip()
            buf.clear()
            if w not in seen and _valid_term(w):
                seen.add(w)
                out.append(w)

    node = _tagger().parseToNode(text)
    while node:
        s = node.surface
        f = node.feature.split(",")
        if s and f[0] == "名詞":
            sub = f[1] if len(f) > 1 else ""
            spaced = node.rlength > node.length
            if sub in _KEEP_NOUN:
                if buf and spaced:
                    # "Knowledge Utility" is one term; Japanese nouns across a
                    # space or a line break are two.
                    if s.isascii() and buf[-1].isascii():
                        buf.append(" ")
                    else:
                        flush()
                buf.append(s)
            elif sub == "接尾" and buf and not spaced and len(f) > 2 and f[2] in _KEEP_SUFFIX:
                buf.append(s)
            else:
                flush()
        else:
            flush()
        node = node.next
    flush()
    return out


# Morphological analysis is the slow step (about 2 s per million characters),
# and the same texts come back every time the period or a filter changes.
_TERM_CACHE = {}
_TERM_CACHE_MAX = 60000


def _terms_cached(text):
    h = hash(text)
    hit = _TERM_CACHE.get(h)
    if hit is None:
        if len(_TERM_CACHE) >= _TERM_CACHE_MAX:
            _TERM_CACHE.clear()
        hit = _TERM_CACHE[h] = tuple(extract_terms(text))
    return hit


def _explode_terms(keys, texts, on_progress=None, done=0, total=0):
    ks, ts = [], []
    for i, (k, text) in enumerate(zip(keys, texts), 1):
        for w in _terms_cached(text):
            ks.append(k)
            ts.append(w)
        if on_progress and i % 200 == 0:
            on_progress(done + i, total)
    return pd.DataFrame({"key": ks, "term": ts})


def tokenize_scope(scope, on_progress=None, inputs=True):
    """Fills scope["input_terms"] / scope["answer_terms"]: one row per (turn | answer, term)."""
    t, a = scope["turns"], scope["answers"]
    if not inputs:
        t = t.iloc[0:0]
    text_answers = a[a["response_prose"] != ""]
    total = len(t) + len(text_answers)
    scope["input_terms"] = _explode_terms(t["turn"], t["user_input"], on_progress, 0, total)
    scope["answer_terms"] = _explode_terms(text_answers["akey"], text_answers["response_prose"],
                                           on_progress, len(t), total)
    scope["n_text_answers"] = len(text_answers)
    scope["_answer_terms_by_stop"] = {}
    return scope


def _answer_terms(scope, stop):
    """Answer terms without the stop words, and each term's count over all answers."""
    cache = scope.setdefault("_answer_terms_by_stop", {})
    hit = cache.get(stop)
    if hit is None:
        at = scope["answer_terms"]
        at = at[~at["term"].isin(stop)]
        hit = cache[stop] = (at, at.groupby("term")["key"].size())
    return hit


def parse_stop_words(extra):
    words = [w.strip() for w in re.split(r"[,、\n]", extra or "") if w.strip()]
    return STOP_WORDS | frozenset(words)


def keyword_ranking(scope, top_n=30, stop=STOP_WORDS):
    """Input keywords by the number of turns that mention them, with when they peaked."""
    it = scope["input_terms"]
    it = it[~it["term"].isin(stop)]
    if it.empty:
        return pd.DataFrame()
    turns = scope["turns"].set_index("turn")
    top = it.groupby("term")["key"].size().sort_values(ascending=False).head(int(top_n))
    bucket = scope["bucket"]
    buckets = _bucket_range(*scope["period"], bucket)
    sub = it[it["term"].isin(top.index)].copy()
    sub["ts"] = sub["key"].map(turns["ts"])
    sub["user_id"] = sub["key"].map(turns["user_id"])
    sub["bucket"] = bucket_start(sub["ts"], bucket)
    rows = []
    for rank, (term, n) in enumerate(top.items(), 1):
        s = sub[sub["term"] == term]
        per = s.groupby("bucket").size().reindex(buckets, fill_value=0)
        peak = per.idxmax()
        rows.append({
            "rank": rank, "keyword": term, "turns": int(n),
            "share": round(100.0 * n / len(turns), 1), "users": s["user_id"].nunique(),
            "peak": f"{bucket_label(peak, bucket)} ({int(per.max())})",
            "first": s["ts"].min().strftime("%Y-%m-%d"), "last": s["ts"].max().strftime("%Y-%m-%d"),
            "trend": per.tolist(),
        })
    return pd.DataFrame(rows)


def turns_with_keyword(scope, keyword):
    it = scope["input_terms"]
    return set(it.loc[it["term"] == keyword, "key"])


def response_terms(scope, turn_ids=None, top_n=10, stop=STOP_WORDS, akeys=None):
    """Terms of the answers to the given turns, ranked by how characteristic they are.

    Plain counts put the words every answer uses on top, so the count is
    weighted by how rare the term is across all answers in scope.
    """
    at, df_all = _answer_terms(scope, stop)
    n_all = max(scope.get("n_text_answers", 0), 1)
    if turn_ids is None and akeys is None:
        sub, n_sub = at, n_all
    else:
        a = scope["answers"]
        keys = set(akeys) if akeys is not None else set(a.loc[a["turn"].isin(turn_ids), "akey"])
        sub = at[at["key"].isin(keys)]
        n_sub = max(sub["key"].nunique(), 1)
    if sub.empty:
        return pd.DataFrame(columns=["keyword", "answers", "share", "lift", "score"]), {}
    out = sub.groupby("term")["key"].size().rename("answers").to_frame()
    out["all"] = df_all.reindex(out.index)
    out["share"] = (100.0 * out["answers"] / n_sub).round(1)
    out["lift"] = ((out["answers"] / n_sub) / (out["all"] / n_all)).round(2)
    out["score"] = (out["answers"] * np.log1p(n_all / out["all"])).round(2)
    out = out.sort_values(["score", "answers"], ascending=False).reset_index().rename(columns={"term": "keyword"})
    freq = dict(zip(out["keyword"].head(50), out["score"].head(50)))
    return out[["keyword", "answers", "share", "lift", "score"]].head(int(top_n)), freq


def wordcloud_png(freq, width=300, height=180):
    if not freq:
        return None
    import io
    from wordcloud import WordCloud
    import DigiM_VAnalytics as dmva
    font = dmva.IPA_FONT_PATH if os.path.exists(dmva.IPA_FONT_PATH) else None
    # Laid out at half size and scaled up: the layout search is what costs.
    wc = WordCloud(font_path=font, background_color="white", width=width, height=height, scale=2,
                   prefer_horizontal=0.95, colormap="tab10", random_state=0).generate_from_frequencies(freq)
    buf = io.BytesIO()
    wc.to_image().save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- vectors

def _load_vectors(session_ids, column):
    sql = (f"SELECT session_id, seq, sub_seq, subvector({column}, 1, {VEC_DIMS})::real[] "
           f"FROM {T_DIALOGS} WHERE session_id = ANY(%s) AND {column} IS NOT NULL")
    with closing(_connect()) as conn, conn.cursor() as cur:
        cur.execute(sql, (list(session_ids),))
        rows = cur.fetchall()
    if not rows:
        return [], np.zeros((0, VEC_DIMS), np.float32)
    keys = [f"{s}:{q}:{b}" for s, q, b, _ in rows]
    return keys, _unit(np.asarray([v for _, _, _, v in rows], dtype=np.float32))


def _unit(m):
    if m.size == 0:
        return m
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def load_vectors(scope):
    """Fills scope["qvec"] (turn -> row) and scope["rvec"] (answer -> row) with unit vectors."""
    t, a = scope["turns"], scope["answers"]
    sids = sorted(set(t["session_id"]))
    qk, qm = _load_vectors(sids, "query_vec")
    pos = {k: i for i, k in enumerate(qk)}
    in_key = t["turn"] + ":" + t["input_sub_seq"].astype(str)
    idx = [(turn, pos[k]) for turn, k in zip(t["turn"], in_key) if k in pos]
    scope["qvec"] = {"keys": [x[0] for x in idx], "m": qm[[x[1] for x in idx]] if idx else np.zeros((0, VEC_DIMS), np.float32)}
    rk, rm = _load_vectors(sids, "response_vec")
    pos = {k: i for i, k in enumerate(rk)}
    idx = [(k, pos[k]) for k in a["akey"] if k in pos]
    scope["rvec"] = {"keys": [x[0] for x in idx], "m": rm[[x[1] for x in idx]] if idx else np.zeros((0, VEC_DIMS), np.float32)}
    return scope


def missing_vectors(scope):
    a = scope["answers"]
    has_text = (a["user_input"].str.strip() != "") | (a["response_text"].str.strip() != "")
    need = a[has_text & ~(a["has_qvec"] & a["has_rvec"])]
    return need[["session_id", "seq", "sub_seq"]]


def vectorize_missing(keys, on_progress=None, batch=16):
    """Embeds archive rows that have no vector yet and stores them in the archive.

    The mirror may already have been pruned, so the archive cannot wait for the
    mirror's own vectorize run to reach these rows.
    """
    import DigiM_DB_Export as dbex
    import DigiM_Util as dmu
    embed = dbex.dialog_embedder()
    if embed is None:
        raise RuntimeError("Embedding is not configured (AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY).")
    keys = [tuple(k) for k in keys]
    done = failed = 0
    with closing(_connect(readonly=False)) as conn, conn.cursor() as cur:
        for i in range(0, len(keys), batch):
            chunk = keys[i:i + batch]
            cur.execute(
                f"SELECT session_id, seq, sub_seq, user_input, response_text, "
                f"query_vec IS NULL, response_vec IS NULL FROM {T_DIALOGS} "
                f"WHERE (session_id, seq, sub_seq) IN %s", (tuple(chunk),))
            jobs = []
            for sid, seq, sub, q, r, q_null, r_null in cur.fetchall():
                if q_null and (q or "").strip():
                    jobs.append((sid, seq, sub, "query_vec", q))
                r = dmu.answer_body(r or "")
                if r_null and r.strip():
                    jobs.append((sid, seq, sub, "response_vec", r))
            try:
                vecs = embed([j[4] for j in jobs]) if jobs else []
                for (sid, seq, sub, col, _), v in zip(jobs, vecs):
                    cur.execute(f"UPDATE {T_DIALOGS} SET {col} = %s::vector "
                                f"WHERE session_id = %s AND seq = %s AND sub_seq = %s AND {col} IS NULL",
                                (json.dumps([float(x) for x in v]), sid, seq, sub))
                conn.commit()
                done += len(chunk)
            except Exception as e:
                conn.rollback()
                failed += len(chunk)
                logger.error(f"[PE][VEC] batch at {i} failed: {e}")
            if on_progress:
                on_progress(min(i + batch, len(keys)), len(keys))
    return {"done": done, "failed": failed}


def embed_query(text):
    import DigiM_DB_Export as dbex
    embed = dbex.dialog_embedder()
    if embed is None:
        return None
    v = np.asarray(embed([text])[0], dtype=np.float32)[:VEC_DIMS].reshape(1, -1)
    return _unit(v)[0]


# ---------------------------------------------------------------- clustering

def _dispersion(m):
    """Mean pairwise cosine distance of unit vectors, without the n x n matrix."""
    n = len(m)
    if n < 2:
        return float("nan")
    s = m.sum(axis=0)
    return float(1.0 - (float(s @ s) - n) / (n * (n - 1)))


def _entropy(counts):
    p = np.asarray([c for c in counts if c > 0], dtype=float)
    p = p / p.sum()
    return float(-(p * np.log(p)).sum())


def _js_divergence(p, q):
    p, q = np.asarray(p, float), np.asarray(q, float)
    p, q = p / p.sum(), q / q.sum()
    m = (p + q) / 2

    def kl(a, b):
        mask = a > 0
        return float((a[mask] * np.log2(a[mask] / b[mask])).sum())
    return (kl(p, m) + kl(q, m)) / 2


def cluster_inputs(scope, k=6, seed=0):
    """K-means over the input vectors. Clusters are numbered by size, C1 the largest."""
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    keys, m = scope["qvec"]["keys"], scope["qvec"]["m"]
    k = int(max(2, min(k, MAX_CLUSTERS, len(keys))))
    if len(keys) < 2:
        return None
    km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(m)
    order = np.argsort(-np.bincount(km.labels_, minlength=k))
    renum = {int(old): new + 1 for new, old in enumerate(order)}
    labels = np.asarray([renum[int(x)] for x in km.labels_])
    cent = _unit(km.cluster_centers_[order])
    xy = PCA(n_components=2, random_state=seed).fit_transform(m) if m.shape[0] > 2 else np.zeros((len(keys), 2))
    frame = pd.DataFrame({"turn": keys, "cluster": labels, "x": xy[:, 0], "y": xy[:, 1],
                          "centrality": np.einsum("ij,ij->i", m, cent[labels - 1])})
    return {"k": k, "frame": frame, "centroids": cent}


def cluster_summary(scope, cl, stop=STOP_WORDS, n_terms=5):
    """Size, characteristic input terms, and how tightly inputs and answers sit together."""
    f = cl["frame"]
    it = scope["input_terms"]
    it = it[~it["term"].isin(stop) & it["key"].isin(set(f["turn"]))]
    df_all = it.groupby("term")["key"].size()
    n_all = max(len(f), 1)
    qpos = {t: i for i, t in enumerate(scope["qvec"]["keys"])}
    rpos = {a: i for i, a in enumerate(scope["rvec"]["keys"])}
    answers = scope["answers"]
    rows = []
    for c in range(1, cl["k"] + 1):
        turns = f.loc[f["cluster"] == c, "turn"]
        sub = it[it["key"].isin(set(turns))]
        tf = sub.groupby("term")["key"].size()
        score = (tf * np.log1p(n_all / df_all.reindex(tf.index))).sort_values(ascending=False)
        akeys = answers.loc[answers["turn"].isin(set(turns)), "akey"]
        rm = scope["rvec"]["m"][[rpos[a] for a in akeys if a in rpos]]
        d_in = _dispersion(scope["qvec"]["m"][[qpos[t] for t in turns]])
        d_out = _dispersion(rm)
        rows.append({
            "cluster": f"C{c}", "turns": len(turns), "share": round(100.0 * len(turns) / n_all, 1),
            "keywords": " / ".join(score.head(n_terms).index), "answers": len(akeys),
            "input_spread": round(d_in, 3), "answer_spread": round(d_out, 3),
            "answer_vs_input": round(d_out / d_in, 2) if d_in and not math.isnan(d_in) and not math.isnan(d_out) else None,
        })
    return pd.DataFrame(rows)


def diversity_by_axis(scope, cl):
    """Per group/user: how its inputs spread over the clusters and in vector space."""
    f = cl["frame"]
    x = axis_frame(scope).merge(f[["turn", "cluster"]], on="turn")
    qpos = {t: i for i, t in enumerate(scope["qvec"]["keys"])}
    k = cl["k"]
    overall = np.bincount(f["cluster"], minlength=k + 1)[1:]
    rows = []
    for name, g in [("(all)", f.assign(axis_value="(all)"))] + list(x.groupby("axis_value")):
        cnt = np.bincount(g["cluster"], minlength=k + 1)[1:]
        m = scope["qvec"]["m"][[qpos[t] for t in g["turn"]]]
        top = int(cnt.argmax()) + 1
        rows.append({
            "axis_value": name, "turns": int(cnt.sum()), "clusters_used": int((cnt > 0).sum()),
            "evenness": round(_entropy(cnt) / math.log(k), 3) if k > 1 else 0.0,
            "top_cluster": f"C{top} ({round(100.0 * cnt[top - 1] / cnt.sum())}%)",
            "spread": round(_dispersion(m), 3),
            "distance_from_all": round(_js_divergence(cnt, overall), 3),
        })
    out = pd.DataFrame(rows)
    return pd.concat([out.iloc[:1], out.iloc[1:].sort_values("turns", ascending=False)], ignore_index=True)


def cluster_axis_matrix(scope, cl):
    x = axis_frame(scope).merge(cl["frame"][["turn", "cluster"]], on="turn")
    x["cluster"] = "C" + x["cluster"].astype(str)
    return x.groupby(["axis_value", "cluster"]).size().rename("turns").reset_index()


def representative_inputs(scope, cl, cluster, axis_value=None, n=3):
    """Inputs closest to the cluster centre, with the answers they got."""
    f = cl["frame"]
    f = f[f["cluster"] == cluster]
    x = axis_frame(scope)
    if axis_value is not None:
        f = f[f["turn"].isin(set(x.loc[x["axis_value"] == axis_value, "turn"]))]
    f = f.sort_values("centrality", ascending=False).head(n)
    turns = scope["turns"].set_index("turn")
    answers = scope["answers"]
    out = []
    for turn in f["turn"]:
        t = turns.loc[turn]
        a = answers[answers["turn"] == turn]
        out.append({
            "turn": turn, "user_id": t["user_id"], "ts": t["ts"], "input": t["user_input"],
            "answers": [{"agent": r["agent_name"] or r["agent_file"], "model": r["model_name"],
                         "text": r["response_text"], "akey": r["akey"]} for _, r in a.iterrows()],
        })
    return out


# ---------------------------------------------------------------- knowledge

def load_refs(scope):
    """Fills scope["refs"]: one row per reference of the answers in scope, with its utility."""
    a = scope["answers"]
    sids = sorted(set(a["session_id"]))
    # A graph edge has no title; its triple text is the only readable name.
    sql = (f"SELECT session_id, seq, sub_seq, rag_name, db_name, chunk_id, "
           f"COALESCE(NULLIF(title, ''), left(text_short, 60), chunk_id) AS title, "
           f"similarity_prompt, similarity_response FROM {T_REFS} WHERE session_id = ANY(%s)")
    with closing(_connect()) as conn:
        r = pd.read_sql_query(sql, conn, params=(sids,))
    r["akey"] = r["session_id"] + ":" + r["seq"].astype(str) + ":" + r["sub_seq"].astype(str)
    r = r[r["akey"].isin(set(a["akey"]))].drop(columns=["session_id", "seq", "sub_seq"])
    for c in ("rag_name", "db_name", "chunk_id", "title"):
        r[c] = r[c].fillna("")
    r["chunk"] = r["rag_name"] + " | " + r["db_name"] + " | " + r["chunk_id"]

    # The stored values are cosine distances. Graph references carry 0/0 and
    # have no utility. For the rest, utility is the same number the per-turn
    # Knowledge Utility screen shows by default (Norm(All)): both distances
    # are scaled by the answer's largest one before subtracting, which keeps
    # the sums of different answers comparable.
    q, s = r["similarity_prompt"].fillna(0.0), r["similarity_response"].fillna(0.0)
    scored = ~((q == 0) & (s == 0))
    mq = q.where(scored).groupby(r["akey"]).transform("max")
    ms = s.where(scored).groupby(r["akey"]).transform("max")
    r["utility"] = (q / mq - s / ms).where(scored & (mq > 0) & (ms > 0))
    r["dist_q"], r["dist_a"] = q.where(scored), s.where(scored)
    meta = r.groupby("chunk").agg(rag_name=("rag_name", "first"), db_name=("db_name", "first"),
                                  chunk_id=("chunk_id", "first"), title=("title", "first"))
    scope["refs"] = r[["akey", "chunk", "utility", "dist_q", "dist_a"]].reset_index(drop=True)
    scope["chunks"] = meta
    return scope


def knowledge_ranking(scope, turn_ids=None, top_n=10, by="ref_count", akeys=None, rag_name=None):
    """Every referenced chunk with its count and cumulative utility; `top` marks the top N."""
    r = scope["refs"]
    if akeys is not None:
        r = r[r["akey"].isin(set(akeys))]
    elif turn_ids is not None:
        a = scope["answers"]
        r = r[r["akey"].isin(set(a.loc[a["turn"].isin(turn_ids), "akey"]))]
    if r.empty:
        return pd.DataFrame()
    g = r.groupby("chunk").agg(ref_count=("akey", "size"), answers=("akey", "nunique"),
                               scored=("utility", "count"), utility_sum=("utility", "sum"),
                               utility_avg=("utility", "mean"),
                               dist_q=("dist_q", "mean"), dist_a=("dist_a", "mean"))
    g.loc[g["scored"] == 0, "utility_sum"] = np.nan
    g = g.join(scope["chunks"]).reset_index()
    if rag_name is not None:
        g = g[g["rag_name"] == rag_name]
        if g.empty:
            return pd.DataFrame()
    g = g.sort_values([by, "ref_count"], ascending=False, na_position="last").reset_index(drop=True)
    g["rank"] = g.index + 1
    g["top"] = g["rank"] <= int(top_n)
    for c in ("utility_sum", "utility_avg", "dist_q", "dist_a"):
        g[c] = g[c].round(3)
    return g


# ---------------------------------------------------------------- achievement

SCORE_DDL = f"""
CREATE TABLE IF NOT EXISTS {T_SCORES} (
    theme_hash   TEXT NOT NULL,
    unit_kind    TEXT NOT NULL,
    unit_key     TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    model        TEXT NOT NULL,
    score        INTEGER,
    reason       TEXT,
    theme_text   TEXT,
    scored_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (theme_hash, unit_kind, unit_key, content_hash, model)
);
CREATE INDEX IF NOT EXISTS idx_{T_SCORES}_scored_at ON {T_SCORES} (scored_at);
"""


def default_themes():
    """[(name, criteria)] from PERFORMANCE_EXPLORER_THEMES in setting.yaml."""
    import DigiM_Util as dmu
    out = []
    for item in (dmu.read_yaml_file("setting.yaml") or {}).get("PERFORMANCE_EXPLORER_THEMES") or []:
        if isinstance(item, dict):
            name, crit = str(item.get("NAME") or "").strip(), str(item.get("CRITERIA") or "").strip()
        else:
            name, crit = str(item or "").strip(), ""
        if name or crit:
            out.append((name, crit))
    return out


def _md5(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def score_band(score):
    for lo, hi in SCORE_BANDS:
        if lo <= score <= hi:
            return f"{lo}-{hi}"
    return ""


def achievement_units(scope, kind="Session", max_chars=6000, per_input=1500):
    """What gets scored: a session's inputs in the period taken together, or one input."""
    t = scope["turns"].sort_values(["session_id", "ts"])
    rows = []
    if kind == "Session":
        for sid, g in t.groupby("session_id", sort=False):
            parts = [f"[{i}] {s[:per_input]}" for i, s in enumerate(g["user_input"], 1) if s.strip()]
            if not parts:
                continue
            rows.append({"unit_key": sid, "text": "\n".join(parts)[:max_chars], "user_id": g["user_id"].iloc[0],
                         "axis": g["axis"].iloc[0], "ts": g["ts"].iloc[0], "label": g["session_name"].iloc[0] or sid,
                         "turns": list(g["turn"])})
    else:
        for _, r in t.iterrows():
            if not r["user_input"].strip():
                continue
            rows.append({"unit_key": r["turn"], "text": r["user_input"][:max_chars // 2], "user_id": r["user_id"],
                         "axis": r["axis"], "ts": r["ts"], "label": r["session_name"] or r["session_id"],
                         "turns": [r["turn"]]})
    out = pd.DataFrame(rows)
    if len(out):
        out["content_hash"] = out["text"].map(_md5)
    return out


def rank_units_for_theme(scope, units, theme_vec):
    """Units ordered by closeness to the theme, so a capped run scores the likeliest ones.

    Units without a vector go last: nothing says they are unrelated.
    """
    pos = {t: i for i, t in enumerate(scope["qvec"]["keys"])}
    m = scope["qvec"]["m"]
    sims = []
    for turns in units["turns"]:
        idx = [pos[t] for t in turns if t in pos]
        if not idx or theme_vec is None:
            sims.append(np.nan)
            continue
        v = m[idx].mean(axis=0)
        n = np.linalg.norm(v)
        sims.append(float(v @ theme_vec / n) if n else np.nan)
    out = units.assign(relevance=sims)
    return out.sort_values("relevance", ascending=False, na_position="last").reset_index(drop=True)


def cached_scores(theme_hash, unit_kind, model):
    try:
        with closing(_connect()) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s)", (T_SCORES,))
            if cur.fetchone()[0] is None:
                return {}
            cur.execute(f"SELECT unit_key, content_hash, score, reason FROM {T_SCORES} "
                        f"WHERE theme_hash = %s AND unit_kind = %s AND model = %s", (theme_hash, unit_kind, model))
            return {(k, h): (s, r) for k, h, s, r in cur.fetchall()}
    except Exception as e:
        logger.warning(f"[PE] score cache is not readable: {e}")
        return {}


def _save_scores(rows):
    if not rows:
        return
    with closing(_connect(readonly=False)) as conn, conn.cursor() as cur:
        cur.execute(SCORE_DDL)
        cur.executemany(
            f"INSERT INTO {T_SCORES} (theme_hash, unit_kind, unit_key, content_hash, model, score, reason, theme_text) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            f"ON CONFLICT (theme_hash, unit_kind, unit_key, content_hash, model) "
            f"DO UPDATE SET score = EXCLUDED.score, reason = EXCLUDED.reason, scored_at = NOW()", rows)
        conn.commit()


def _parse_scores(text, n):
    """{position: (score, reason)} from the model's JSON, tolerating prose around it."""
    out = {}
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    items = []
    if m:
        try:
            items = json.loads(m.group(0))
        except Exception:
            items = []
    if not items:
        for o in re.findall(r"\{[^{}]*\}", text or "", re.DOTALL):
            try:
                items.append(json.loads(o))
            except Exception:
                pass
    for it in items if isinstance(items, list) else []:
        try:
            i, sc = int(it.get("id")), int(round(float(it.get("score"))))
        except Exception:
            continue
        if 1 <= i <= n:
            out[i] = (max(0, min(100, sc)), str(it.get("reason", ""))[:500])
    return out


def score_units(theme, units, call_llm, model, instruction, unit_kind="Session",
                batch=5, on_progress=None, save=True):
    """Scores each unit against the theme with the LLM, reusing stored scores.

    A stored score is keyed by the theme text, the scored text and the model,
    so re-running the same analysis costs nothing and a changed session is
    scored again.
    """
    theme_hash = _md5(instruction + "\n" + theme)
    cache = cached_scores(theme_hash, unit_kind, model)
    results, todo = {}, []
    for _, u in units.iterrows():
        hit = cache.get((u["unit_key"], u["content_hash"]))
        if hit:
            results[u["unit_key"]] = (hit[0], hit[1], True)
        else:
            todo.append(u)
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        body = "\n\n".join(f"### id: {j}\n{u['text']}" for j, u in enumerate(chunk, 1))
        prompt = f"{instruction}\n\n## Theme\n{theme}\n\n## Inputs to score\n{body}"
        try:
            parsed = _parse_scores(call_llm(prompt), len(chunk))
        except Exception as e:
            logger.error(f"[PE] scoring call failed: {e}")
            parsed = {}
        fresh = []
        for j, u in enumerate(chunk, 1):
            if j in parsed:
                sc, reason = parsed[j]
                results[u["unit_key"]] = (sc, reason, False)
                fresh.append((theme_hash, unit_kind, u["unit_key"], u["content_hash"], model, sc, reason, theme[:2000]))
        if save:
            try:
                _save_scores(fresh)
            except Exception as e:
                logger.warning(f"[PE] scores were not stored: {e}")
        if on_progress:
            on_progress(min(i + batch, len(todo)), len(todo))
    out = units[units["unit_key"].isin(results)].copy()
    out["score"] = out["unit_key"].map(lambda k: results[k][0])
    out["reason"] = out["unit_key"].map(lambda k: results[k][1])
    out["cached"] = out["unit_key"].map(lambda k: results[k][2])
    out["band"] = out["score"].map(score_band)
    return out.sort_values("score", ascending=False).reset_index(drop=True)


def achievement_ranking(scored):
    x = scored.explode("axis").rename(columns={"axis": "axis_value"})
    g = x.groupby("axis_value").agg(units=("score", "size"), best=("score", "max"),
                                    average=("score", "mean"), users=("user_id", "nunique"))
    g["average"] = g["average"].round(1)
    g = g.sort_values(["best", "average"], ascending=False).reset_index()
    g.insert(0, "rank", g.index + 1)
    return g


def band_counts(scored):
    labels = [f"{lo}-{hi}" for lo, hi in SCORE_BANDS]
    c = scored["band"].value_counts().reindex(labels, fill_value=0)
    return pd.DataFrame({"band": labels, "units": c.values})


# ---------------------------------------------------------------- LLM context

def _clip(text, n):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[:n] + "…"


def topic_context(scope, ranking, stop=STOP_WORDS, detail=10, top_n=10):
    p_from, p_to = scope["period"]
    lines = [f"Period: {p_from:%Y-%m-%d %H:%M} - {p_to:%Y-%m-%d %H:%M} / turns: {len(scope['turns'])} / "
             f"axis: {scope['axis']}",
             "\n[User input keywords: rank, keyword, turns, share%, users, peak period]"]
    for _, r in ranking.iterrows():
        lines.append(f"{r['rank']}. {r['keyword']}: {r['turns']} turns, {r['share']}%, {r['users']} users, peak {r['peak']}")
    lines.append("\n[Agent answers to the top keywords: characteristic terms (answers containing the term)]")
    for _, r in ranking.head(detail).iterrows():
        terms, _ = response_terms(scope, turns_with_keyword(scope, r["keyword"]), top_n, stop)
        lines.append(f"- {r['keyword']}: " + ", ".join(f"{k}({n})" for k, n in zip(terms["keyword"], terms["answers"])))
    return "\n".join(lines)


def diversity_context(scope, cl, summary, diversity, stop=STOP_WORDS, top_n=5):
    lines = [f"Clusters of user inputs: k={cl['k']}, turns={len(cl['frame'])}, axis={scope['axis']}",
             "spread = mean pairwise cosine distance (larger = more varied). "
             "answer_vs_input above 1 means the answers vary more than the inputs they answer.",
             "\n[Clusters]"]
    for c, (_, r) in enumerate(summary.iterrows(), 1):
        lines.append(f"{r['cluster']}: {r['turns']} turns ({r['share']}%), keywords: {r['keywords']}, "
                     f"input_spread {r['input_spread']}, answer_spread {r['answer_spread']}, "
                     f"answer_vs_input {r['answer_vs_input']}")
        turns = set(cl["frame"].loc[cl["frame"]["cluster"] == c, "turn"])
        for rep in representative_inputs(scope, cl, c, n=2):
            lines.append(f"  input example: {_clip(rep['input'], 160)}")
        terms, _ = response_terms(scope, turns, top_n, stop)
        lines.append("  answer terms: " + ", ".join(terms["keyword"]))
        if "refs" in scope:
            kr = knowledge_ranking(scope, turns, top_n)
            if len(kr):
                lines.append("  knowledge: " + "; ".join(
                    f"{_clip(t or c_, 40)} [{rag}] x{n}" for t, c_, rag, n in
                    zip(kr["title"].head(top_n), kr["chunk_id"], kr["rag_name"], kr["ref_count"])))
    lines.append(f"\n[Per {scope['axis'].lower()}: evenness = entropy over clusters scaled to 0-1, "
                 "distance_from_all = Jensen-Shannon divergence from the overall cluster mix]")
    for _, r in diversity.iterrows():
        lines.append(f"{r['axis_value']}: {r['turns']} turns, {r['clusters_used']} clusters, evenness {r['evenness']}, "
                     f"top {r['top_cluster']}, spread {r['spread']}, distance_from_all {r['distance_from_all']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- agent section

SUPPORT_KINDS = ("thinking", "rag_query", "meta_search", "web_search", "digest")
STEP_LABELS = {"thinking": "Thinking", "rag_query": "RAG query generation", "meta_search": "Meta search",
               "web_search": "Web search", "digest": "Dialog digest", "main": "Main LLM"}


def agent_label(agent_file):
    return re.sub(r"^agent_|\.json$", "", agent_file or "") or "(unknown)"


def load_agent_scope(p_from, p_to, agents=None):
    """The same turns as load_scope, seen from the agents that answered them.

    Deleted answers are loaded too (scope["deleted"]): a user deleting an
    answer is one of the few signals of dissatisfaction the data holds.
    """
    rows = _fetch_rows(p_from, p_to, with_deleted=True)
    scope = {"period": (p_from, p_to), "axis": "Agent", "bucket": pick_bucket(p_from, p_to),
             "filters": {"users": [], "groups": [], "agents": list(agents or [])}}
    if not rows.empty and agents:
        rows = rows[rows["agent_file"].isin(agents)]
    if rows.empty:
        scope["turns"] = scope["answers"] = scope["deleted"] = pd.DataFrame()
        return scope
    rows = rows.assign(agent=rows["agent_file"].map(agent_label))
    live = rows[rows["flg"] == "Y"].reset_index(drop=True)
    scope["deleted"] = rows[rows["flg"] != "Y"].reset_index(drop=True)
    scope["answers"] = live
    if live.empty:
        scope["turns"] = pd.DataFrame()
        return scope
    turns = _turns_of(live)
    by_turn = live.groupby("turn")["agent"].agg(lambda x: sorted(set(x)))
    # A turn answered by two agents counts for both, like a user in two groups.
    turns["axis"] = turns["turn"].map(by_turn)
    scope["turns"] = turns.reset_index(drop=True)
    return scope


def agent_summary(scope):
    a = scope["answers"]
    g = a.assign(chars=a["response_prose"].str.len()).groupby("agent").agg(
        answers=("akey", "size"), turns=("turn", "nunique"), sessions=("session_id", "nunique"),
        users=("user_id", "nunique"), avg_answer_chars=("chars", "mean"),
        avg_answer_sec=("answer_sec", "mean"), avg_llm_sec=("llm_sec", "mean"),
        avg_prompt_tokens=("prompt_tokens_total", "mean"), avg_response_tokens=("response_tokens", "mean"),
        response_tokens=("response_tokens", "sum"), refs_per_answer=("knowledge_ref_count", "mean"),
        models=("model_name", lambda x: ", ".join(sorted({m for m in x if m}))))
    out = g.reset_index().sort_values("answers", ascending=False)
    for c in ("avg_answer_chars", "avg_prompt_tokens", "avg_response_tokens"):
        out[c] = out[c].round(0)
    for c in ("avg_answer_sec", "avg_llm_sec", "refs_per_answer"):
        out[c] = out[c].round(1)
    return out


def agent_models(scope):
    a = scope["answers"]
    g = a.assign(chars=a["response_prose"].str.len()).groupby(["agent", "model_name"]).agg(
        answers=("akey", "size"), avg_answer_chars=("chars", "mean"), avg_answer_sec=("answer_sec", "mean"),
        avg_llm_sec=("llm_sec", "mean"), avg_response_tokens=("response_tokens", "mean"))
    out = g.reset_index().sort_values(["agent", "answers"], ascending=[True, False])
    out["avg_answer_chars"] = out["avg_answer_chars"].round(0)
    out["avg_response_tokens"] = out["avg_response_tokens"].round(0)
    for c in ("avg_answer_sec", "avg_llm_sec"):
        out[c] = out[c].round(1)
    return out


def load_steps(scope):
    """Fills scope["steps"]: the support steps of the answers in scope, or
    None while the steps archive does not exist yet."""
    a = scope["answers"]
    with closing(_connect()) as conn:
        with conn.cursor() as cur:
            if not _exists(cur, T_STEPS):
                scope["steps"] = None
                return scope
        st = pd.read_sql_query(
            f"SELECT session_id, seq, sub_seq, step_no, step_kind, step_name, phase, agent_file AS step_agent, "
            f"model_name AS step_model, duration_sec, prompt_tokens, response_tokens, status, detail "
            f"FROM {T_STEPS} WHERE session_id = ANY(%s)", conn, params=(sorted(set(a["session_id"])),))
    st["akey"] = st["session_id"] + ":" + st["seq"].astype(str) + ":" + st["sub_seq"].astype(str)
    st = st.merge(a[["akey", "turn", "agent", "answer_sec"]], on="akey")
    for c in ("duration_sec", "prompt_tokens", "response_tokens"):
        st[c] = pd.to_numeric(st[c], errors="coerce")
    for c in ("step_name", "phase", "step_agent", "step_model", "status"):
        st[c] = st[c].fillna("")
    st["detail"] = st["detail"].map(lambda d: d if isinstance(d, dict) else {})
    scope["steps"] = st.drop(columns=["session_id", "seq", "sub_seq"]).reset_index(drop=True)
    return scope


def steps_coverage(scope):
    """(answers with at least one step, answers in scope): the steps exist
    only for sessions whose history was still there when they were mirrored."""
    st = scope.get("steps")
    return (st["akey"].nunique() if st is not None else 0), len(scope["answers"])


def habit_summary(scope):
    """Which practice ran, per agent."""
    a = scope["answers"]
    g = a.assign(practice=a["practice_name"].replace("", "(none)")).groupby(["agent", "practice"]).agg(
        answers=("akey", "size"), turns=("turn", "nunique")).reset_index()
    g["share"] = (100.0 * g["answers"] / g.groupby("agent")["answers"].transform("sum")).round(1)
    return g.sort_values(["agent", "answers"], ascending=[True, False])


def habit_timeline(scope, top=6):
    a = scope["answers"].merge(scope["turns"][["turn", "ts"]], on="turn")
    a["practice"] = a["practice_name"].replace("", "(none)")
    keep = a["practice"].value_counts().head(top).index
    a["series"] = a["practice"].where(a["practice"].isin(keep), OTHER)
    a["bucket"] = bucket_start(a["ts"], scope["bucket"])
    return a.groupby(["bucket", "series"]).size().rename("answers").reset_index(), sorted(keep)


def thinking_choices(scope):
    """What the Thinking agent decided: (habit table, book table)."""
    st = scope["steps"]
    th = st[st["step_kind"] == "thinking"]
    if th.empty:
        return pd.DataFrame(), pd.DataFrame()
    th = th.assign(habit=th["detail"].map(lambda d: str(d.get("habit") or "(none)")))
    habits = th.groupby(["agent", "habit"]).agg(turns=("akey", "size"), avg_sec=("duration_sec", "mean")).reset_index()
    habits["share"] = (100.0 * habits["turns"] / habits.groupby("agent")["turns"].transform("sum")).round(1)
    habits["avg_sec"] = habits["avg_sec"].round(1)
    books = th.assign(book=th["detail"].map(lambda d: d.get("books") or [])).explode("book").dropna(subset=["book"])
    books = books.groupby(["agent", "book"]).size().rename("turns").reset_index() if len(books) else pd.DataFrame()
    return (habits.sort_values(["agent", "turns"], ascending=[True, False]),
            books.sort_values(["agent", "turns"], ascending=[True, False]) if len(books) else books)


def rag_summary(scope, akeys=None):
    """Per knowledge base: how often it was referenced and what it contributed."""
    r = scope["refs"]
    a = scope["answers"]
    if akeys is not None:
        r = r[r["akey"].isin(set(akeys))]
        a = a[a["akey"].isin(set(akeys))]
    if r.empty:
        return pd.DataFrame()
    r = r.join(scope["chunks"][["rag_name", "db_name"]], on="chunk")
    g = r.groupby(["rag_name", "db_name"]).agg(
        references=("akey", "size"), chunks=("chunk", "nunique"), answers=("akey", "nunique"),
        utility_sum=("utility", "sum"), utility_avg=("utility", "mean"), scored=("utility", "count")).reset_index()
    g.loc[g["scored"] == 0, ["utility_sum", "utility_avg"]] = np.nan
    g["answer_share"] = (100.0 * g["answers"] / max(len(a), 1)).round(1)
    g["utility_sum"], g["utility_avg"] = g["utility_sum"].round(2), g["utility_avg"].round(3)
    return g.drop(columns=["scored"]).sort_values("references", ascending=False)


def skill_summary(scope):
    """(skills, rewrites): how often each skill ran and what it cost."""
    st = scope["steps"]
    sk = st[st["step_kind"] == "skill"]
    skills = pd.DataFrame()
    if len(sk):
        sk = sk.assign(chars_in=sk["detail"].map(lambda d: d.get("chars_in")),
                       chars_out=sk["detail"].map(lambda d: d.get("chars_out")),
                       merge=sk["detail"].map(lambda d: str(d.get("merge") or "")))
        skills = sk.groupby(["step_name", "phase"]).agg(
            runs=("akey", "size"), avg_sec=("duration_sec", "mean"), total_sec=("duration_sec", "sum"),
            timed=("duration_sec", "count"),
            prompt_tokens=("prompt_tokens", "sum"), response_tokens=("response_tokens", "sum"),
            errors=("status", lambda x: int((x == "error").sum())),
            skipped=("status", lambda x: int((x == "skipped").sum())),
            merge=("merge", lambda x: ", ".join(sorted({m for m in x if m}))),
            models=("step_model", lambda x: ", ".join(sorted({m for m in x if m})))).reset_index()
        # Run time is recorded from this version on; a total of 0 over runs
        # that were never timed would read as "instant".
        skills.loc[skills["timed"] == 0, ["avg_sec", "total_sec"]] = np.nan
        skills["avg_sec"], skills["total_sec"] = skills["avg_sec"].round(1), skills["total_sec"].round(0)
        skills = skills.drop(columns=["timed"]).sort_values("runs", ascending=False)
    rw = st[st["step_kind"] == "rewrite"]
    rewrites = pd.DataFrame()
    if len(rw):
        rw = rw.assign(before=rw["detail"].map(lambda d: d.get("original_chars")),
                       after=rw["detail"].map(lambda d: d.get("chars")))
        rewrites = rw.groupby(["agent", "step_name"]).agg(
            rewrites=("akey", "size"), answers=("akey", "nunique"),
            avg_chars_before=("before", "mean"), avg_chars_after=("after", "mean")).reset_index()
        for c in ("avg_chars_before", "avg_chars_after"):
            rewrites[c] = pd.to_numeric(rewrites[c], errors="coerce").round(0)
    return skills, rewrites


def support_summary(scope, agent=None):
    """Per support agent and model: runs, time and tokens."""
    st = scope["steps"]
    st = st[st["step_kind"].isin(SUPPORT_KINDS)]
    if agent:
        st = st[st["agent"] == agent]
    if st.empty:
        return pd.DataFrame()
    st = st.assign(step=st["step_kind"].map(STEP_LABELS),
                   who=st["step_agent"].map(agent_label).where(st["step_agent"] != "", st["step_name"]))
    g = st.groupby(["step", "who", "step_model"]).agg(
        runs=("akey", "size"), avg_sec=("duration_sec", "mean"), total_sec=("duration_sec", "sum"),
        prompt_tokens=("prompt_tokens", "sum"), response_tokens=("response_tokens", "sum")).reset_index()
    g["avg_sec"], g["total_sec"] = g["avg_sec"].round(1), g["total_sec"].round(0)
    return g.sort_values(["step", "runs"], ascending=[True, False])


def time_breakdown(scope, agent=None):
    """Average seconds per answer spent in each step, over the answers that have step data.

    The query generators and the meta search run in parallel, so the parts
    can add up to more than the time the user waited.
    """
    st = scope["steps"]
    a = scope["answers"]
    if agent:
        st, a = st[st["agent"] == agent], a[a["agent"] == agent]
    covered = a[a["akey"].isin(set(st["akey"]))]
    n = len(covered)
    if not n:
        return pd.DataFrame(), 0, float("nan")
    rows = [{"step": STEP_LABELS[k], "sec_per_answer": st.loc[st["step_kind"] == k, "duration_sec"].sum() / n}
            for k in SUPPORT_KINDS]
    rows.append({"step": STEP_LABELS["main"], "sec_per_answer": covered["llm_sec"].sum() / n})
    out = pd.DataFrame(rows)
    out["sec_per_answer"] = out["sec_per_answer"].round(1)
    return out[out["sec_per_answer"] > 0], n, float(covered["answer_sec"].mean())


def feedback_signals(scope):
    """Per agent: what users did to its answers afterwards."""
    a, d = scope["answers"], scope["deleted"]
    g = a.groupby("agent").agg(answers=("akey", "size"),
                               memory_excluded=("memory_flg", lambda x: int((x == "N").sum())))
    g["deleted"] = d.groupby("agent").size() if len(d) else 0
    st = scope.get("steps")
    if st is not None:
        rw = st[st["step_kind"] == "rewrite"]
        g["rewritten"] = rw.groupby("agent")["akey"].nunique()
    else:
        g["rewritten"] = np.nan
    g = g.fillna({"deleted": 0}).reset_index()
    g["deleted"] = g["deleted"].astype(int)
    total = g["answers"] + g["deleted"]
    g["deleted_rate"] = (100.0 * g["deleted"] / total).round(1)
    g["memory_excluded_rate"] = (100.0 * g["memory_excluded"] / g["answers"]).round(1)
    return g.sort_values("answers", ascending=False)


def reask_pairs(scope):
    """Consecutive turns of a session with the similarity of their inputs.

    A user who asks nearly the same thing again right away was probably not
    served by the first answer, which stands in for the feedback nobody writes.
    """
    t = scope["turns"].sort_values(["session_id", "seq"])
    pos = {k: i for i, k in enumerate(scope["qvec"]["keys"])}
    m = scope["qvec"]["m"]
    agents = scope["answers"].groupby("turn")["agent"].agg(lambda x: sorted(set(x)))
    rows = []
    prev = None
    for r in t.itertuples(index=False):
        if prev is not None and prev.session_id == r.session_id and r.seq == prev.seq + 1 \
                and prev.turn in pos and r.turn in pos:
            rows.append({"turn": prev.turn, "next_turn": r.turn, "agent": agents.get(prev.turn, []),
                         "similarity": float(m[pos[prev.turn]] @ m[pos[r.turn]]),
                         "input": prev.user_input, "next_input": r.user_input, "ts": prev.ts})
        prev = r
    return pd.DataFrame(rows)


def reask_summary(pairs, threshold=0.93):
    if pairs.empty:
        return pd.DataFrame()
    x = pairs.explode("agent").dropna(subset=["agent"])
    x["reasked"] = x["similarity"] >= threshold
    g = x.groupby("agent").agg(followed_turns=("turn", "size"), reasked=("reasked", "sum")).reset_index()
    g["reask_rate"] = (100.0 * g["reasked"] / g["followed_turns"]).round(1)
    return g.sort_values("followed_turns", ascending=False)


# ---------------------------------------------------------------- agent knowledge

def agent_knowledge_config(agent_file):
    """The agent's KNOWLEDGE then BOOK entries, in the order the agent lists them.

    None when the agent file is gone (a renamed or deleted agent still has
    answers in the archive).
    """
    import DigiM_Agent as dma
    out = []
    try:
        for origin in ("KNOWLEDGE", "BOOK"):
            try:
                items = dma.get_agent_item(agent_file, origin) or []
            except KeyError:
                items = []
            for it in items:
                if not isinstance(it, dict) or not it.get("RAG_NAME"):
                    continue
                out.append({
                    "rag_name": it["RAG_NAME"], "origin": "Knowledge" if origin == "KNOWLEDGE" else "Book",
                    "retriever": it.get("RETRIEVER", "Vector"), "active": it.get("ACTIVE", True) is not False,
                    "collections": [d.get("DATA_NAME") for d in (it.get("DATA") or [])
                                    if isinstance(d, dict) and d.get("DATA_TYPE") == "DB" and d.get("DATA_NAME")],
                })
    except FileNotFoundError:
        return None
    return out


_MAP_CACHE = {}


def knowledge_map(collections):
    """Every chunk of the collections placed in 2D (id, db, title, x, y), or None.

    The same picture the per-turn Knowledge Utility scatter draws: PCA over
    the chunks' value vectors. Kept per process, keyed by the collections and
    their sizes, because reading a collection back costs far more than the
    screen can pay on every rerun.
    """
    import DigiM_Context as dmc
    from sklearn.decomposition import PCA
    client = dmc.get_chroma_client()
    cols = []
    for name in collections:
        try:
            cols.append((name, client.get_collection(name)))
        except Exception:
            continue
    key = tuple((n, c.count()) for n, c in cols)
    if key in _MAP_CACHE:
        return _MAP_CACHE[key]
    ids, dbs, titles, vecs = [], [], [], []
    for name, col in cols:
        got = col.get(include=["metadatas"])
        for cid, meta in zip(got["ids"], got["metadatas"]):
            raw = str((meta or {}).get("vector_data_value_text", "")).strip("[] ")
            if not raw:
                continue
            v = np.fromstring(raw, sep=",", dtype=np.float32)
            if v.size:
                ids.append(str(cid)); dbs.append(name); titles.append(str((meta or {}).get("title", ""))); vecs.append(v)
    dims = {v.size for v in vecs}
    if len(vecs) < 3 or len(dims) != 1:
        _MAP_CACHE[key] = None
        return None
    xy = PCA(n_components=2, random_state=0).fit_transform(_unit(np.vstack(vecs)))
    out = pd.DataFrame({"chunk_id": ids, "db_name": dbs, "title": titles, "x": xy[:, 0], "y": xy[:, 1]})
    _MAP_CACHE[key] = out
    return out


def knowledge_sections(scope, agent, top_n=10):
    """One entry per knowledge base of the agent, in configured order, with
    the ranking of its knowledge among the agent's answers."""
    a = scope["answers"]
    akeys = set(a.loc[a["agent"] == agent, "akey"])
    files = a.loc[a["agent"] == agent, "agent_file"]
    cfg = agent_knowledge_config(files.iloc[0]) if len(files) else None
    used = knowledge_ranking(scope, top_n=top_n, akeys=akeys)
    used_rags = list(used["rag_name"].drop_duplicates()) if len(used) else []
    sections = list(cfg or [])
    listed = {c["rag_name"] for c in sections}
    # Referenced in the period but no longer on the agent (or the agent file
    # itself is gone): shown after the configured ones, most referenced first.
    for rag in used_rags:
        if rag not in listed:
            sections.append({"rag_name": rag, "origin": "Not configured now", "retriever": "", "active": False,
                             "collections": []})
    out = []
    for c in sections:
        r = knowledge_ranking(scope, top_n=top_n, akeys=akeys, rag_name=c["rag_name"])
        out.append({**c, "ranking": r, "references": int(r["ref_count"].sum()) if len(r) else 0,
                    "distinct": len(r)})
    return out, cfg is not None

