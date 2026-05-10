"""ユーザーメモリ（短期/中期/長期）のストレージ抽象化。

3つの層を扱う:
  - short  (session_digest):    1セッション1レコード。終了時に生成。
  - mid    (period_profile):    期間ごとに集約（月次 or rolling）。
  - long   (persona_profile):   1ユーザー1レコード。差分マージで更新。

各層ごとに保存先を選択できる:
  - "EXCEL":  user/common/user_memory/<layer>.xlsx
  - "NOTION": NOTION_MST_FILE で指定したDB
  - "RDB":    PostgreSQL (digim_user_memory_<layer>)

system.env で層ごとに指定:
  USER_MEMORY_SHORT_BACKEND, USER_MEMORY_MID_BACKEND, USER_MEMORY_LONG_BACKEND
  USER_MEMORY_DEFAULT_LAYERS  (例: "long,mid,short")

長期は3000トークン上限で要約注入される前提（呼び出し側で制御）。
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import DigiM_Util as dmu

logger = logging.getLogger(__name__)

# system.env
if os.path.exists("system.env"):
    load_dotenv("system.env")

# setting.yaml
_setting = dmu.read_yaml_file("setting.yaml")
_user_memory_folder = _setting.get("USER_MEMORY_FOLDER", "user/common/user_memory/")
_mst_folder_path = _setting["MST_FOLDER"]

LAYERS = ("short", "mid", "long")

_NOTION_MST_FILE = os.getenv("NOTION_MST_FILE")

# ---------- Backend resolution ----------
def get_backend(layer: str) -> str:
    """層ごとのバックエンドを返す（EXCEL/NOTION/RDB）。デフォルトEXCEL。"""
    layer = (layer or "").lower()
    env_key = f"USER_MEMORY_{layer.upper()}_BACKEND"
    return (os.getenv(env_key) or "EXCEL").upper()


def get_default_layers() -> list:
    """デフォルトで有効な層リスト（system.envから）。

    USER_MEMORY_DEFAULT_LAYERS の挙動:
      - 未設定 (None) → "long,mid,short" を適用
      - 空文字列 ""    → 全層Off (空リストを返す)
      - "long,mid"    → ["long", "mid"]
    """
    raw = os.getenv("USER_MEMORY_DEFAULT_LAYERS")
    if raw is None:
        raw = "long,mid,short"
    return [s.strip().lower() for s in raw.split(",") if s.strip().lower() in LAYERS]


# ---------- Schema ----------
# 各層の論理スキーマ（excerpt列はテキスト、tags/list列はJSON）
_SHORT_FIELDS = [
    "id", "service_id", "user_id", "session_id", "session_name",
    "create_date", "topic", "excerpt", "axis_tags",
    "confidence", "source_seq", "active",
]
_MID_FIELDS = [
    "id", "service_id", "user_id", "period",
    "generated_at", "recurring_topics", "emerging", "declining",
    "shifts", "evidence_session_ids", "summary_text", "token_count", "active",
]
_LONG_FIELDS = [
    "service_id", "user_id", "generated_at", "last_reviewed",
    "role", "expertise", "recurring_interests", "values_principles",
    "constraints", "communication_style", "avoid_topics",
    "summary_text", "token_count",
]
_FIELDS = {"short": _SHORT_FIELDS, "mid": _MID_FIELDS, "long": _LONG_FIELDS}

# JSON化対象の列
_JSON_COLS = {
    "short": {"axis_tags", "source_seq"},
    "mid":   {"recurring_topics", "emerging", "declining", "shifts", "evidence_session_ids"},
    "long":  {"expertise", "recurring_interests", "values_principles",
              "constraints", "communication_style", "avoid_topics"},
}


def _empty_record(layer: str) -> dict:
    rec = {f: "" for f in _FIELDS[layer]}
    for c in _JSON_COLS[layer]:
        rec[c] = []
    if "active" in rec:
        rec["active"] = "Y"
    if "token_count" in rec:
        rec["token_count"] = 0
    if layer == "short" and "confidence" in rec:
        rec["confidence"] = 0.0
    return rec


def _normalize_record(layer: str, rec: dict) -> dict:
    """欠損補完・型整形。"""
    base = _empty_record(layer)
    base.update({k: v for k, v in (rec or {}).items() if k in base})
    for c in _JSON_COLS[layer]:
        v = base.get(c)
        if isinstance(v, str):
            try:
                base[c] = json.loads(v) if v else []
            except Exception:
                base[c] = []
    return base


# ---------- EXCEL backend ----------
def _excel_path(layer: str) -> str:
    Path(_user_memory_folder).mkdir(parents=True, exist_ok=True)
    return str(Path(_user_memory_folder) / f"{layer}.xlsx")


def _excel_load_all(layer: str) -> list:
    import pandas as pd
    path = _excel_path(layer)
    if not os.path.exists(path):
        return []
    try:
        df = pd.read_excel(path, sheet_name=layer, dtype=str).fillna("")
    except Exception as e:
        logger.warning(f"[user_memory] Excel読込失敗 layer={layer}: {e}")
        return []
    records = []
    for _, row in df.iterrows():
        rec = {col: row[col] if col in row.index else "" for col in _FIELDS[layer]}
        records.append(_normalize_record(layer, rec))
    return records


def _excel_save_all(layer: str, records: list):
    import pandas as pd
    path = _excel_path(layer)
    rows = []
    for rec in records:
        out = {}
        for col in _FIELDS[layer]:
            v = rec.get(col, "")
            if col in _JSON_COLS[layer]:
                v = json.dumps(v, ensure_ascii=False) if v else "[]"
            out[col] = v
        rows.append(out)
    df = pd.DataFrame(rows, columns=_FIELDS[layer])
    df.to_excel(path, sheet_name=layer, index=False)


# ---------- RDB backend ----------
_RDB_DDL = {
    "short": """
        CREATE TABLE IF NOT EXISTS digim_user_memory_short (
            id              TEXT PRIMARY KEY,
            service_id      TEXT,
            user_id         TEXT,
            session_id      TEXT UNIQUE,
            session_name    TEXT,
            create_date     TIMESTAMP,
            topic           TEXT,
            excerpt         TEXT,
            axis_tags       JSONB,
            confidence      DOUBLE PRECISION,
            source_seq      JSONB,
            active          CHAR(1) DEFAULT 'Y'
        )
    """,
    "mid": """
        CREATE TABLE IF NOT EXISTS digim_user_memory_mid (
            id                    TEXT PRIMARY KEY,
            service_id            TEXT,
            user_id               TEXT,
            period                TEXT,
            generated_at          TIMESTAMP,
            recurring_topics      JSONB,
            emerging              JSONB,
            declining             JSONB,
            shifts                JSONB,
            evidence_session_ids  JSONB,
            summary_text          TEXT,
            token_count           INTEGER,
            active                CHAR(1) DEFAULT 'Y',
            UNIQUE(service_id, user_id, period)
        )
    """,
    "long": """
        CREATE TABLE IF NOT EXISTS digim_user_memory_long (
            service_id            TEXT,
            user_id               TEXT,
            generated_at          TIMESTAMP,
            last_reviewed         TIMESTAMP,
            role                  TEXT,
            expertise             JSONB,
            recurring_interests   JSONB,
            values_principles     JSONB,
            constraints           JSONB,
            communication_style   JSONB,
            avoid_topics          JSONB,
            summary_text          TEXT,
            token_count           INTEGER,
            PRIMARY KEY(service_id, user_id)
        )
    """,
}


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rdb_config():
    return {
        "host":     os.getenv("POSTGRES_HOST"),
        "port":     _safe_int(os.getenv("POSTGRES_PORT"), 5432),
        "dbname":   os.getenv("POSTGRES_DB"),
        "user":     os.getenv("POSTGRES_USER"),
        "password": os.getenv("POSTGRES_PASSWORD"),
        "sslmode":  "require",
    }


def _rdb_connect():
    import psycopg2
    return psycopg2.connect(**_rdb_config())


def _ensure_rdb_table(conn, layer: str):
    with conn.cursor() as cur:
        cur.execute(_RDB_DDL[layer])
    conn.commit()


def _rdb_load_all(layer: str) -> list:
    conn = _rdb_connect()
    try:
        _ensure_rdb_table(conn, layer)
        cols = ", ".join(_FIELDS[layer])
        with conn.cursor() as cur:
            cur.execute(f"SELECT {cols} FROM digim_user_memory_{layer}")
            rows = cur.fetchall()
        records = []
        for row in rows:
            rec = dict(zip(_FIELDS[layer], row))
            for c in _JSON_COLS[layer]:
                if rec.get(c) is None:
                    rec[c] = []
            records.append(_normalize_record(layer, rec))
        return records
    finally:
        conn.close()


def _rdb_upsert(layer: str, rec: dict):
    rec = _normalize_record(layer, rec)
    cols = _FIELDS[layer]
    placeholders = []
    values = []
    for c in cols:
        v = rec.get(c)
        if c in _JSON_COLS[layer]:
            placeholders.append("%s::jsonb")
            values.append(json.dumps(v or [], ensure_ascii=False))
        else:
            placeholders.append("%s")
            values.append(v if v != "" else None)

    if layer == "short":
        conflict_keys = "(session_id)"
        update_cols = [c for c in cols if c not in ("id", "session_id")]
    elif layer == "mid":
        conflict_keys = "(service_id, user_id, period)"
        update_cols = [c for c in cols if c not in ("id", "service_id", "user_id", "period")]
    else:
        conflict_keys = "(service_id, user_id)"
        update_cols = [c for c in cols if c not in ("service_id", "user_id")]

    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    sql = (
        f"INSERT INTO digim_user_memory_{layer} ({', '.join(cols)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT {conflict_keys} DO UPDATE SET {update_set}"
    )

    conn = _rdb_connect()
    try:
        _ensure_rdb_table(conn, layer)
        with conn.cursor() as cur:
            cur.execute(sql, values)
        conn.commit()
    finally:
        conn.close()


def _rdb_delete(layer: str, key_filter: dict):
    conn = _rdb_connect()
    try:
        _ensure_rdb_table(conn, layer)
        where = " AND ".join(f"{k}=%s" for k in key_filter)
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM digim_user_memory_{layer} WHERE {where}", list(key_filter.values()))
        conn.commit()
    finally:
        conn.close()


def _to_notion_date(value) -> str:
    """内部の日時表現（"YYYY-MM-DD HH:MM:SS[.ffffff]"）をNotionのISO 8601文字列へ変換。"""
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # 空白区切り → ISO の T へ
    s = s.replace(" ", "T", 1)
    # Notion は秒以下のマイクロ秒もISOの範囲内であれば許容するが、安全のため秒で打ち切る
    if "." in s:
        s = s.split(".", 1)[0]
    return s


# ---------- NOTION backend ----------
# 各層ごとにNotionDBを使う場合は NOTION_MST_FILE のキーから取得
# NOTION_MST_FILE: { "DigiM_UserMemory_Short": "<db_id>", ... }
def _notion_db_id(layer: str):
    if not _NOTION_MST_FILE:
        return None
    notion_db_mst_path = str(Path(_mst_folder_path) / _NOTION_MST_FILE)
    notion_db_mst = dmu.read_json_file(notion_db_mst_path)
    key = f"DigiM_UserMemory_{layer.capitalize()}"
    return notion_db_mst.get(key)


def _notion_property_text(prop):
    """Notionプロパティから単純テキスト抽出。"""
    if not isinstance(prop, dict):
        return ""
    rich = prop.get("rich_text") or prop.get("title") or []
    return "".join(b.get("plain_text", "") for b in rich)


def _notion_fetch_db_schema(db_id: str) -> dict:
    """NotionのDB定義から {プロパティ名: 型} を返す。"""
    import os
    import requests
    notion_token = os.getenv("NOTION_TOKEN")
    notion_version = os.getenv("NOTION_VERSION") or "2022-06-28"
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": notion_version,
    }
    try:
        r = requests.get(f"https://api.notion.com/v1/databases/{db_id}", headers=headers, timeout=15)
        if r.status_code != 200:
            logger.warning(f"[user_memory] Notion DB schema取得失敗 {db_id}: {r.status_code} {r.text[:120]}")
            return {}
        data = r.json()
        return {name: (p or {}).get("type") for name, p in (data.get("properties") or {}).items()}
    except Exception as e:
        logger.warning(f"[user_memory] Notion DB schema例外 {db_id}: {e}")
        return {}


def _notion_load_all(layer: str) -> list:
    db_id = _notion_db_id(layer)
    if not db_id:
        logger.warning(f"[user_memory] NotionDB未設定 layer={layer}")
        return []
    import DigiM_Notion as dmn
    pages = dmn.get_all_pages(db_id)
    records = []
    for page in pages:
        props = page.get("properties", {})
        rec = _empty_record(layer)
        for col in _FIELDS[layer]:
            if col in props:
                ptype = props[col].get("type")
                if ptype == "rich_text" or ptype == "title":
                    raw = _notion_property_text(props[col])
                    if col in _JSON_COLS[layer]:
                        try:
                            rec[col] = json.loads(raw) if raw else []
                        except Exception:
                            rec[col] = []
                    else:
                        rec[col] = raw
                elif ptype == "number":
                    rec[col] = props[col].get("number")
                elif ptype == "date":
                    d = props[col].get("date") or {}
                    rec[col] = d.get("start", "")
                elif ptype == "checkbox":
                    rec[col] = "Y" if props[col].get("checkbox") else "N"
                elif ptype == "select":
                    s = props[col].get("select") or {}
                    rec[col] = s.get("name", "")
        records.append(_normalize_record(layer, rec))
    return records


def _notion_upsert(layer: str, rec: dict):
    """Notionへのupsert（同一キーの既存ページがあれば更新、無ければ作成）。"""
    db_id = _notion_db_id(layer)
    if not db_id:
        logger.warning(f"[user_memory] NotionDB未設定のためupsertスキップ layer={layer}")
        return
    import DigiM_Notion as dmn

    rec = _normalize_record(layer, rec)
    pages = dmn.get_all_pages(db_id)

    # 一意キーでマッチング
    if layer == "short":
        match_field = "session_id"
    elif layer == "mid":
        match_field = "id"
    else:  # long
        match_field = "user_id"

    target_page_id = None
    for page in pages:
        props = page.get("properties", {})
        if match_field in props:
            existing = _notion_property_text(props[match_field])
            if existing == str(rec.get(match_field, "")):
                target_page_id = page["id"]
                break

    title_value = rec.get("topic") or rec.get("user_id") or rec.get("session_id") or "user_memory"
    if target_page_id is None:
        # 新規作成
        resp = dmn.create_page(db_id, str(title_value)[:80], title_item="title")
        target_page_id = resp.get("id")
        if not target_page_id:
            return

    # NotionDBスキーマからプロパティ型を取得（新規/既存どちらでも安定して取得できる）
    schema_types = _notion_fetch_db_schema(db_id)

    # 各フィールドを更新
    for col in _FIELDS[layer]:
        v = rec.get(col, "")
        ptype = schema_types.get(col)
        try:
            if col in _JSON_COLS[layer]:
                dmn.update_notion_rich_text_content(target_page_id, col, json.dumps(v, ensure_ascii=False))
            elif ptype == "checkbox":
                # "Y"/"N"/bool/数値0,1 をbool化
                if isinstance(v, bool):
                    chk = v
                elif isinstance(v, (int, float)):
                    chk = bool(v)
                else:
                    chk = str(v).strip().upper() in ("Y", "TRUE", "1", "YES")
                dmn.update_notion_chk(target_page_id, col, chk)
            elif ptype == "number" or (isinstance(v, (int, float)) and col in ("token_count", "confidence")):
                if isinstance(v, str):
                    try:
                        v = float(v)
                    except Exception:
                        v = 0
                dmn.update_notion_num(target_page_id, col, v)
            elif ptype == "date" and v:
                dmn.update_notion_date(target_page_id, col, _to_notion_date(v))
            elif ptype == "select" and v:
                dmn.update_notion_select(target_page_id, col, str(v))
            else:
                dmn.update_notion_rich_text_content(target_page_id, col, str(v) if v is not None else "")
        except Exception as e:
            logger.debug(f"[user_memory] Notion更新スキップ {col}: {e}")


def _notion_delete(layer: str, key_filter: dict):
    db_id = _notion_db_id(layer)
    if not db_id:
        return
    import DigiM_Notion as dmn
    pages = dmn.get_all_pages(db_id)
    for page in pages:
        props = page.get("properties", {})
        if all(_notion_property_text(props.get(k, {})) == str(v) for k, v in key_filter.items()):
            try:
                dmn.archive_page(page["id"])
            except Exception as e:
                logger.warning(f"[user_memory] Notionアーカイブ失敗: {e}")


# ---------- public API ----------
def load_all(layer: str, service_id: str = "", user_id: str = "") -> list:
    """指定層の全レコードを取得。service_id/user_idでフィルタ可。"""
    backend = get_backend(layer)
    if backend == "RDB":
        records = _rdb_load_all(layer)
    elif backend == "NOTION":
        records = _notion_load_all(layer)
    else:
        records = _excel_load_all(layer)
    if service_id:
        records = [r for r in records if r.get("service_id") == service_id]
    if user_id:
        records = [r for r in records if r.get("user_id") == user_id]
    return records


def upsert(layer: str, record: dict):
    """指定層に1レコードをupsert。"""
    backend = get_backend(layer)
    if backend == "RDB":
        _rdb_upsert(layer, record)
        return
    if backend == "NOTION":
        _notion_upsert(layer, record)
        return
    # EXCEL: 全件読込→差し替え→全件保存
    records = _excel_load_all(layer)
    if layer == "short":
        match_field = "session_id"
    elif layer == "mid":
        match_field = "id"
    else:
        match_field = "user_id"
    found = False
    for i, r in enumerate(records):
        if r.get(match_field) == record.get(match_field) and r.get("service_id", "") == record.get("service_id", ""):
            records[i] = _normalize_record(layer, record)
            found = True
            break
    if not found:
        records.append(_normalize_record(layer, record))
    _excel_save_all(layer, records)


def delete(layer: str, key_filter: dict):
    """指定層からレコード削除。"""
    backend = get_backend(layer)
    if backend == "RDB":
        _rdb_delete(layer, key_filter)
        return
    if backend == "NOTION":
        _notion_delete(layer, key_filter)
        return
    records = _excel_load_all(layer)
    records = [r for r in records if not all(r.get(k) == v for k, v in key_filter.items())]
    _excel_save_all(layer, records)


def get_one(layer: str, key_filter: dict):
    """指定層から1レコード取得（無ければNone）。"""
    records = load_all(layer)
    for r in records:
        if all(r.get(k) == v for k, v in key_filter.items()):
            return r
    return None


def make_short_id(service_id: str, user_id: str, session_id: str) -> str:
    return f"{service_id}__{user_id}__{session_id}"


def make_mid_id(service_id: str, user_id: str, period: str) -> str:
    return f"{service_id}__{user_id}__{period}"


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
