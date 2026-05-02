import os
import re
import ast
import logging
from datetime import datetime
from pathlib import Path

import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from openai import AzureOpenAI

from DigiM_Util import read_yaml_file
import DigiM_Session as dms

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# 設定読み込み
# ------------------------------------------------------------------ #
load_dotenv("system.env")

def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

DB_CONFIG = {
    "host":     os.getenv("POSTGRES_HOST"),
    "port":     _safe_int(os.getenv("POSTGRES_PORT"), 5432),
    "dbname":   os.getenv("POSTGRES_DB"),
    "user":     os.getenv("POSTGRES_USER"),
    "password": os.getenv("POSTGRES_PASSWORD"),
    "sslmode":  "require",
}

# setting.yaml から取得
_setting = read_yaml_file("setting.yaml")

SESSION_PREFIX = _setting["SESSION_FOLDER_PREFIX"]  # "session"

def _trunc(value, max_len: int) -> str | None:
    """文字列をmax_len文字以内にトランケート（Noneはそのまま返す）"""
    if value is None:
        return None
    s = str(value)
    return s[:max_len] if len(s) > max_len else s

def _safe_ts(value) -> datetime | None:
    """文字列をdatetimeに変換（失敗したらNone）"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None

def _session_created_date(session_id: str) -> datetime | None:
    """session_id (例: 20260324_070640_0) から作成日時を導出"""
    m = re.match(r"^(\d{8})_(\d{6})", str(session_id))
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except Exception:
            pass
    return None

def _parse_duration(timestamp_log: str) -> float | None:
    """timestamp_log から [21.LLM実行開始] ～ [22.LLM実行完了] の秒数を算出"""
    if not timestamp_log:
        return None
    try:
        pat = r"\[2[12]\.[^\]]+\](\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)"
        matches = re.findall(pat, timestamp_log)
        if len(matches) >= 2:
            t1 = datetime.fromisoformat(matches[0])
            t2 = datetime.fromisoformat(matches[1])
            return (t2 - t1).total_seconds()
    except Exception:
        pass
    return None

def _parse_knowledge_ref(ref_str: str) -> dict:
    """LOG_TEMPLATE形式の文字列をdictに変換"""
    from DigiM_Util import parse_log_template
    return parse_log_template(ref_str)

def _get_prompt_template(prompt: dict) -> str:
    """prompt.prompt_template から設定名を取得"""
    pt = prompt.get("prompt_template")
    if isinstance(pt, dict):
        return pt.get("setting") or pt.get("name") or ""
    return str(pt) if pt else ""

def _get_model_name(engine: dict) -> str:
    """engine dict から MODEL を安全に取得（_configs/_default混入を無視）"""
    return engine.get("MODEL", "") if isinstance(engine, dict) else ""


# ------------------------------------------------------------------ #
# パース: セッション1件分
# ------------------------------------------------------------------ #
def parse_session(session_id: str, status: dict, memory: dict, from_seq: int = 0) -> tuple[dict, list[dict], list[dict]]:
    """
    Returns:
        session_row  : dict  → digim_sessions 1行
        dialog_rows  : list  → digim_dialogs N行 (seq > from_seq のみ)
        ref_rows     : list  → digim_references N行
    """
    session_id = str(status.get("id", ""))

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
        seq_memory_flg = setting_block.get("MEMORY_FLG", "Y")  # 後方互換: seq単位
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

            ts_log   = log.get("timestamp_log", "") if isinstance(log, dict) else ""
            duration = _parse_duration(ts_log)

            meta_cond = meta.get("condition_list", [])
            meta_used = isinstance(meta_cond, list) and len(meta_cond) > 0

            sit = query.get("situation", {})
            # memory_flg: sub_seq.setting.memory_flg を優先、無ければseq単位のSETTING.MEMORY_FLG
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
                "user_input":                query.get("input"),
                "query_text":                query.get("text"),
                "response_text":             response.get("text"),
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
# DB書き込み
# ------------------------------------------------------------------ #
INSERT_SESSION = """
INSERT INTO digim_sessions
    (session_id, session_name, user_id, service_id, agent_file,
     active, status, user_dialog, last_update_date, created_date)
VALUES
    (%(session_id)s, %(session_name)s, %(user_id)s, %(service_id)s, %(agent_file)s,
     %(active)s, %(status)s, %(user_dialog)s, %(last_update_date)s, %(created_date)s)
ON CONFLICT (session_id) DO UPDATE SET
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
     user_input, query_text, response_text, digest_text,
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
     %(user_input)s, %(query_text)s, %(response_text)s, %(digest_text)s,
     %(prompt_timestamp)s, %(response_timestamp)s, %(response_duration_sec)s,
     %(prompt_tokens_total)s, %(query_tokens)s, %(response_tokens)s, %(digest_tokens)s, %(digest_model)s,
     %(rag_query_used)s, %(rag_query_model)s, %(rag_query_prompt_tokens)s, %(rag_query_response_tokens)s,
     %(meta_search_date_used)s, %(meta_search_date_result)s, %(web_search_used)s,
     %(knowledge_ref_count)s, %(memory_ref_count)s)
ON CONFLICT (session_id, seq, sub_seq) DO NOTHING;
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
    # sessions
    cur.execute(INSERT_SESSION, session_row)

    # dialogs & references
    ref_idx = 0
    for dr in dialog_rows:
        cur.execute(INSERT_DIALOG, dr)

        # dialog_id を取得
        cur.execute(
            "SELECT id FROM digim_dialogs WHERE session_id=%s AND seq=%s AND sub_seq=%s",
            (dr["session_id"], dr["seq"], dr["sub_seq"])
        )
        row = cur.fetchone()
        if not row:
            ref_idx += (dr["knowledge_ref_count"] or 0)
            continue
        dialog_id = row[0]

        # このdialogに紐づくreference行を追加
        count = dr["knowledge_ref_count"] or 0
        for rr in ref_rows[ref_idx: ref_idx + count]:
            rr["dialog_id"] = dialog_id
            cur.execute(INSERT_REF, rr)
        ref_idx += count

# ------------------------------------------------------------------ #
# メイン
# ------------------------------------------------------------------ #
def main():
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
                logger.info(f"[SKIP] {folder_name}: 書き込み済み (last_seq={last_seq})")
                skip += 1
                continue
            # 新しいseqが存在する → UNDO に更新してから差分書き込み
            dms.save_db_export_undo(session_id, last_seq)
            logger.info(f"[UNDO] {folder_name}: seq {last_seq+1}～{memory_max_seq} を追加書き込み")
        else:
            # 未エクスポート or UNDO → UNDO (last_seq=0 or 既存値) でマーク
            dms.save_db_export_undo(session_id, last_seq)
            logger.info(f"[UNDO] {folder_name}: seq {last_seq+1}～{memory_max_seq} を書き込み")

        from_seq = last_seq  # 0 なら全件、N なら seq > N を対象

        try:
            session_row, dialog_rows, ref_rows = parse_session(session_id, status, memory, from_seq)
            write_session(cur, session_row, dialog_rows, ref_rows)
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
    logger.info(f"完了 — 全{total}件: 書込={done} スキップ={skip} エラー={error}")

# ------------------------------------------------------------------ #
# ベクトル化
# ------------------------------------------------------------------ #
EMBED_MAX_CHARS = 4000  # 日本語1文字≒2トークン、8192トークン上限対策
EMBED_BATCH     = 10    # 1バッチあたりの件数
EMBED_SLEEP     = 1.0   # バッチ間の待機秒数（レート制限対策）

def vectorize_dialogs():
    """未ベクトル化の digim_dialogs レコードに query_vec / response_vec を設定する"""
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_api_key  = os.getenv("AZURE_OPENAI_API_KEY")
    embed_model    = os.getenv("AZURE_OPENAI_EMBED_MODEL", "text-embedding-3-large")

    if not all([azure_endpoint, azure_api_key]):
        logger.warning("[VEC] AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY が未設定のためスキップします")
        return

    client = AzureOpenAI(
        azure_endpoint=azure_endpoint,
        api_key=azure_api_key,
        api_version="2024-12-01-preview",
    )

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
    logger.info(f"[VEC] 未ベクトル化件数: {total}件")

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
                def _embed(text):
                    return client.embeddings.create(
                        input=text[:EMBED_MAX_CHARS].replace("\n", " "),
                        model=embed_model,
                    ).data[0].embedding

                query_vec    = _embed(row["user_input"])
                response_vec = _embed(row["response_text"])

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

        logger.info(f"[VEC] 進捗: {done}/{total}件完了 (エラー: {error}件)")
        time.sleep(EMBED_SLEEP)

    cur.close()
    conn.close()
    logger.info(f"[VEC] 完了 — 成功: {done}件 / エラー: {error}件")


if __name__ == "__main__":
    main()