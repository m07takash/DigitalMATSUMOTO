"""Storage abstraction for user memory (History / Nowaday / Persona).

Handles three layers:
  - history (session_digest):    One record per session, generated at session end.
  - nowaday (period_profile):    Aggregated per period (monthly or rolling).
  - persona (persona_profile):   One record per user, updated via diff merge.

Each layer can use a different storage backend:
  - "EXCEL":  user/common/user_memory/<layer>.xlsx
  - "NOTION": the DB specified by NOTION_MST_FILE
  - "RDB":    PostgreSQL (digim_user_memory_<layer>)

Configure per-layer via system.env:
  USER_MEMORY_HISTORY_BACKEND, USER_MEMORY_NOWADAY_BACKEND, USER_MEMORY_PERSONA_BACKEND
  USER_MEMORY_DEFAULT_LAYERS  (e.g., "persona,nowaday,history")

Persona is expected to be injected as a summary controlled by USER_MEMORY_PERSONA_TOKEN_LIMIT (managed by the caller).
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

LAYERS = ("history", "nowaday", "persona")

_NOTION_MST_FILE = os.getenv("NOTION_MST_FILE")

# ---------- Backend resolution ----------
def get_backend(layer: str) -> str:
    """Return the backend per layer (EXCEL/NOTION/RDB). Default is EXCEL."""
    layer = (layer or "").lower()
    env_key = f"USER_MEMORY_{layer.upper()}_BACKEND"
    return (os.getenv(env_key) or "EXCEL").upper()


def get_default_layers() -> list:
    """Default list of enabled layers (read from system.env).

    Behavior of USER_MEMORY_DEFAULT_LAYERS:
      - Unset (None) -> apply "persona,nowaday,history"
      - Empty string "" -> all layers off (returns an empty list)
      - "persona,nowaday"    → ["persona", "nowaday"]
    """
    raw = os.getenv("USER_MEMORY_DEFAULT_LAYERS")
    if raw is None:
        raw = "persona,nowaday,history"
    return [s.strip().lower() for s in raw.split(",") if s.strip().lower() in LAYERS]


# ---------- Schema ----------
# Logical schema per layer (excerpt is text; tags/list columns are JSON)
_HISTORY_FIELDS = [
    "id", "service_id", "user_id", "session_id", "session_name",
    "create_date", "topic", "excerpt", "axis_tags",
    "emotions",
    "confidence", "source_seq", "active",
]
_NOWADAY_FIELDS = [
    "id", "service_id", "user_id", "period",
    "generated_at", "recurring_topics", "emerging", "declining",
    "shifts", "basic_emotions", "secondary_emotions",
    "evidence_session_ids", "summary_text", "token_count", "active",
]
_PERSONA_FIELDS = [
    "service_id", "user_id", "generated_at", "last_reviewed",
    "role", "expertise", "recurring_interests", "values_principles",
    "constraints", "communication_style", "avoid_topics",
    "big5",
    "summary_text", "token_count",
]
_FIELDS = {"history": _HISTORY_FIELDS, "nowaday": _NOWADAY_FIELDS, "persona": _PERSONA_FIELDS}

# Columns to serialize as JSON
_JSON_COLS = {
    "history": {"axis_tags", "source_seq", "emotions"},
    "nowaday": {"recurring_topics", "emerging", "declining", "shifts",
                "evidence_session_ids", "basic_emotions", "secondary_emotions"},
    "persona": {"expertise", "recurring_interests", "values_principles",
                "constraints", "communication_style", "avoid_topics", "big5"},
}

# Default "empty" form for JSON columns (dict or array). When unspecified, treated as [].
_JSON_DEFAULTS = {
    "nowaday": {"basic_emotions": dict},
    "persona": {"big5": dict},
}


def _json_default_for(layer: str, col: str):
    t = (_JSON_DEFAULTS.get(layer) or {}).get(col)
    if t is dict:
        return {}
    return []


def _empty_record(layer: str) -> dict:
    rec = {f: "" for f in _FIELDS[layer]}
    for c in _JSON_COLS[layer]:
        rec[c] = _json_default_for(layer, c)
    if "active" in rec:
        rec["active"] = "Y"
    if "token_count" in rec:
        rec["token_count"] = 0
    if layer == "history" and "confidence" in rec:
        rec["confidence"] = 0.0
    return rec


def _normalize_record(layer: str, rec: dict) -> dict:
    """Fill missing fields and normalize types."""
    base = _empty_record(layer)
    base.update({k: v for k, v in (rec or {}).items() if k in base})
    for c in _JSON_COLS[layer]:
        v = base.get(c)
        default = _json_default_for(layer, c)
        if isinstance(v, str):
            try:
                base[c] = json.loads(v) if v else default
            except Exception:
                base[c] = default
        elif v is None:
            base[c] = default
    return base


# ---------- EXCEL backend ----------
# Per-file locks (a single Streamlit process can have multiple background threads
# concurrently calling upsert on the same layer; without locking, df.to_excel can
# race against itself and leave a corrupt or zero-byte file).
import threading as _um_threading
_excel_file_locks = {}
_excel_file_locks_meta = _um_threading.Lock()


def _get_excel_lock(file_path: str):
    with _excel_file_locks_meta:
        if file_path not in _excel_file_locks:
            _excel_file_locks[file_path] = _um_threading.Lock()
        return _excel_file_locks[file_path]


def _excel_path(layer: str) -> str:
    Path(_user_memory_folder).mkdir(parents=True, exist_ok=True)
    return str(Path(_user_memory_folder) / f"{layer}.xlsx")


def _excel_load_all(layer: str) -> list:
    import pandas as pd
    path = _excel_path(layer)
    if not os.path.exists(path):
        return []
    # Hold the lock so we don't read while another thread is replacing the file.
    with _get_excel_lock(path):
        # Lenient sheet resolution: prefer the canonical sheet name, but if the user
        # edited the file and renamed the sheet (e.g. "history" -> "history (1)"),
        # fall back to the first sheet so we don't silently return [].
        try:
            df = pd.read_excel(path, sheet_name=layer, dtype=str).fillna("")
        except ValueError as ve:
            try:
                df = pd.read_excel(path, sheet_name=0, dtype=str).fillna("")
                logger.warning(
                    f"[user_memory] Excel sheet '{layer}' not found in {path}; "
                    f"falling back to the first sheet ({ve})"
                )
            except Exception as e:
                logger.warning(f"[user_memory] Excel load failed layer={layer} path={path}: {e}")
                _excel_quarantine_corrupt_file(path, reason=str(e))
                return []
        except Exception as e:
            logger.warning(f"[user_memory] Excel load failed layer={layer} path={path}: {e}")
            _excel_quarantine_corrupt_file(path, reason=str(e))
            return []
    records = []
    for _, row in df.iterrows():
        rec = {col: row[col] if col in row.index else "" for col in _FIELDS[layer]}
        records.append(_normalize_record(layer, rec))
    return records


def _excel_quarantine_corrupt_file(path: str, reason: str = ""):
    """When the xlsx can't be parsed (zero-byte, half-written, foreign format),
    move it aside as <path>.corrupt.<ts> so subsequent writes can recreate a fresh
    file instead of crashing again. Keeps a copy for post-mortem."""
    try:
        if not os.path.exists(path):
            return
        # Don't quarantine readable files (defensive double-check).
        try:
            import pandas as pd
            pd.read_excel(path, sheet_name=0, dtype=str)
            return
        except Exception:
            pass
        ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
        bad_path = f"{path}.corrupt.{ts}"
        os.replace(path, bad_path)
        logger.error(f"[user_memory] quarantined corrupt Excel: {path} -> {bad_path} (reason: {reason})")
    except Exception as e:
        logger.warning(f"[user_memory] failed to quarantine {path}: {e}")


def _excel_save_all(layer: str, records: list):
    """Atomic + lock-protected Excel write.

    Strategy:
      1. Take the per-file lock.
      2. Serialize the DataFrame to a temp file in the same folder.
      3. fsync, then atomic os.replace() into the canonical path.
      4. If anything fails, the original (valid) file is untouched.

    Errors are logged and re-raised so the caller (and the centralized bg-error log)
    can record what was attempted.
    """
    import pandas as pd
    import tempfile
    path = _excel_path(layer)
    rows = []
    for rec in records:
        out = {}
        for col in _FIELDS[layer]:
            v = rec.get(col, "")
            if col in _JSON_COLS[layer]:
                if v:
                    v = json.dumps(v, ensure_ascii=False)
                else:
                    v = json.dumps(_json_default_for(layer, col), ensure_ascii=False)
            out[col] = v
        rows.append(out)
    df = pd.DataFrame(rows, columns=_FIELDS[layer])

    folder = os.path.dirname(path) or "."
    with _get_excel_lock(path):
        fd, tmp_path = tempfile.mkstemp(prefix=f".tmp_{layer}_", suffix=".xlsx", dir=folder)
        os.close(fd)  # pandas/openpyxl opens by path; we just needed a unique reserved name.
        try:
            df.to_excel(tmp_path, sheet_name=layer, index=False)
            # Flush the new file to disk so the rename swap actually carries the content.
            try:
                with open(tmp_path, "rb") as _f:
                    os.fsync(_f.fileno())
            except OSError:
                pass
            os.replace(tmp_path, path)
            logger.info(f"[user_memory] saved layer={layer} rows={len(rows)} path={path}")
        except Exception as e:
            # Clean up the temp file on any failure so we don't litter the folder.
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            logger.exception(
                f"[user_memory] Excel save FAILED layer={layer} path={path} "
                f"rows={len(rows)}: {type(e).__name__}: {e}"
            )
            raise


# ---------- RDB backend ----------
_RDB_DDL = {
    "history": """
        CREATE TABLE IF NOT EXISTS digim_user_memory_history (
            id              TEXT PRIMARY KEY,
            service_id      TEXT,
            user_id         TEXT,
            session_id      TEXT UNIQUE,
            session_name    TEXT,
            create_date     TIMESTAMP,
            topic           TEXT,
            excerpt         TEXT,
            axis_tags       JSONB,
            emotions        JSONB,
            confidence      DOUBLE PRECISION,
            source_seq      JSONB,
            active          CHAR(1) DEFAULT 'Y'
        )
    """,
    "nowaday": """
        CREATE TABLE IF NOT EXISTS digim_user_memory_nowaday (
            id                    TEXT PRIMARY KEY,
            service_id            TEXT,
            user_id               TEXT,
            period                TEXT,
            generated_at          TIMESTAMP,
            recurring_topics      JSONB,
            emerging              JSONB,
            declining             JSONB,
            shifts                JSONB,
            basic_emotions        JSONB,
            secondary_emotions    JSONB,
            evidence_session_ids  JSONB,
            summary_text          TEXT,
            token_count           INTEGER,
            active                CHAR(1) DEFAULT 'Y'
        )
    """,
    "persona": """
        CREATE TABLE IF NOT EXISTS digim_user_memory_persona (
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
            big5                  JSONB,
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
        if layer == "nowaday":
            # The legacy UNIQUE(service_id,user_id,period) constraint is dropped (moved to snapshot-history form)
            cur.execute(
                "ALTER TABLE digim_user_memory_nowaday "
                "DROP CONSTRAINT IF EXISTS digim_user_memory_nowaday_service_id_user_id_period_key"
            )
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
            values.append(json.dumps(v if v else _json_default_for(layer, c), ensure_ascii=False))
        else:
            placeholders.append("%s")
            values.append(v if v != "" else None)

    if layer == "history":
        conflict_keys = "(session_id)"
        update_cols = [c for c in cols if c not in ("id", "session_id")]
    elif layer == "nowaday":
        # Snapshot history: id is unique per generation. Only re-upsert of the same id updates (for editing/saving)
        conflict_keys = "(id)"
        update_cols = [c for c in cols if c not in ("id",)]
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
    """Convert the internal datetime form ("YYYY-MM-DD HH:MM:SS[.ffffff]") to a Notion ISO 8601 string."""
    if not value:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # Whitespace separator -> ISO 'T'
    s = s.replace(" ", "T", 1)
    # Notion accepts sub-second microseconds within ISO range, but truncate to seconds for safety
    if "." in s:
        s = s.split(".", 1)[0]
    return s


# ---------- NOTION backend ----------
# When a Notion DB is used per layer, read from the NOTION_MST_FILE key
# NOTION_MST_FILE: { "DigiM_UserMemory_History": "<db_id>", ... }
def _notion_db_id(layer: str):
    if not _NOTION_MST_FILE:
        return None
    notion_db_mst_path = str(Path(_mst_folder_path) / _NOTION_MST_FILE)
    notion_db_mst = dmu.read_json_file(notion_db_mst_path)
    key = f"DigiM_UserMemory_{layer.capitalize()}"
    return notion_db_mst.get(key)


def _notion_property_text(prop):
    """Extract plain text from a Notion property."""
    if not isinstance(prop, dict):
        return ""
    rich = prop.get("rich_text") or prop.get("title") or []
    return "".join(b.get("plain_text", "") for b in rich)


def _notion_fetch_db_schema(db_id: str) -> dict:
    """Return {property name: type} from the Notion DB definition."""
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
            logger.warning(f"[user_memory] Notion DB schema fetch failed {db_id}: {r.status_code} {r.text[:120]}")
            return {}
        data = r.json()
        return {name: (p or {}).get("type") for name, p in (data.get("properties") or {}).items()}
    except Exception as e:
        logger.warning(f"[user_memory] Notion DB schema exception {db_id}: {e}")
        return {}


def _notion_add_properties(db_id: str, new_props: dict) -> dict:
    """Add new properties to the Notion DB. new_props: {prop_name: type_str}.

    Existing properties are not touched (partial update). type_str is rich_text / number / checkbox / date / select, etc.
    Returns: dict of {property name: type} actually added (existing ones are skipped).
    """
    import os
    import requests
    notion_token = os.getenv("NOTION_TOKEN")
    notion_version = os.getenv("NOTION_VERSION") or "2022-06-28"
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": notion_version,
        "Content-Type": "application/json",
    }
    existing = _notion_fetch_db_schema(db_id)
    to_add = {name: t for name, t in new_props.items() if name not in existing}
    if not to_add:
        return {}
    payload_props = {}
    for name, t in to_add.items():
        if t == "rich_text":
            payload_props[name] = {"rich_text": {}}
        elif t == "number":
            payload_props[name] = {"number": {"format": "number"}}
        elif t == "checkbox":
            payload_props[name] = {"checkbox": {}}
        elif t == "date":
            payload_props[name] = {"date": {}}
        elif t == "select":
            payload_props[name] = {"select": {}}
        else:
            payload_props[name] = {"rich_text": {}}  # Unknown types fall back to rich_text
    body = {"properties": payload_props}
    try:
        r = requests.patch(
            f"https://api.notion.com/v1/databases/{db_id}",
            headers=headers, json=body, timeout=30,
        )
        if r.status_code != 200:
            logger.warning(f"[user_memory] Notion property add failed {db_id}: {r.status_code} {r.text[:200]}")
            return {}
        return to_add
    except Exception as e:
        logger.warning(f"[user_memory] Notion property add exception {db_id}: {e}")
        return {}


def ensure_notion_schema(layer: str) -> dict:
    """Add properties missing from the current schema (_FIELDS[layer]) to the Notion DB for the given layer.

    Existing property types are kept as-is; only missing ones are added as rich_text.
    Columns in JSON_COLS are also rich_text (since they store JSON strings).
    Returns: {"added": {...}, "skipped_existing": [...], "db_id": "..."}
    """
    db_id = _notion_db_id(layer)
    if not db_id:
        return {"added": {}, "skipped_existing": [], "db_id": None,
                "error": "Notion DB not configured"}
    existing = _notion_fetch_db_schema(db_id)
    needed = {col: "rich_text" for col in _FIELDS[layer]}
    missing = {name: t for name, t in needed.items() if name not in existing}
    added = _notion_add_properties(db_id, missing) if missing else {}
    return {
        "added": added,
        "skipped_existing": [c for c in _FIELDS[layer] if c in existing],
        "db_id": db_id,
    }


def _notion_load_all(layer: str) -> list:
    db_id = _notion_db_id(layer)
    if not db_id:
        logger.warning(f"[user_memory] Notion DB not configured layer={layer}")
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
                        default = _json_default_for(layer, col)
                        try:
                            rec[col] = json.loads(raw) if raw else default
                        except Exception:
                            rec[col] = default
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
    """Upsert into Notion (update an existing page with the same key; create if not found)."""
    db_id = _notion_db_id(layer)
    if not db_id:
        logger.warning(f"[user_memory] Skipping upsert because Notion DB is not configured layer={layer}")
        return
    import DigiM_Notion as dmn

    rec = _normalize_record(layer, rec)
    pages = dmn.get_all_pages(db_id)

    # Match by the unique key
    if layer == "history":
        match_field = "session_id"
    elif layer == "nowaday":
        match_field = "id"
    else:  # persona
        match_field = "user_id"

    target_page_id = None
    for page in pages:
        props = page.get("properties", {})
        if match_field in props:
            existing = _notion_property_text(props[match_field])
            if existing == str(rec.get(match_field, "")):
                target_page_id = page["id"]
                break

    # Use the unique key as the Notion page title.
    # create_page() archives existing pages with the same title, so a title
    # collision would wipe out different records (e.g. Nowaday snapshot history
    # or same-topic History). The unique key prevents this collision.
    if layer == "nowaday":
        title_value = rec.get("id") or f"{rec.get('user_id','')}__{rec.get('period','')}"
    elif layer == "history":
        title_value = rec.get("session_id") or rec.get("id") or rec.get("topic") or "history"
    else:  # persona: one record per user, unique by user_id
        title_value = rec.get("user_id") or "user_memory"
    if target_page_id is None:
        # Create a new record
        resp = dmn.create_page(db_id, str(title_value)[:80], title_item="title")
        target_page_id = resp.get("id")
        if not target_page_id:
            return

    # Read property types from the Notion DB schema (stable for both new and existing rows)
    schema_types = _notion_fetch_db_schema(db_id)

    # Update each field
    for col in _FIELDS[layer]:
        v = rec.get(col, "")
        ptype = schema_types.get(col)
        try:
            if col in _JSON_COLS[layer]:
                dmn.update_notion_rich_text_content(target_page_id, col, json.dumps(v, ensure_ascii=False))
            elif ptype == "checkbox":
                # Coerce "Y"/"N"/bool/0/1 to bool
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
            logger.debug(f"[user_memory] Notion update skipped {col}: {e}")


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
                logger.warning(f"[user_memory] Notion archive failed: {e}")


# ---------- public API ----------
def load_all(layer: str, service_id: str = "", user_id: str = "") -> list:
    """Fetch all records from the given layer. Can be filtered by service_id/user_id."""
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
    """Upsert one record into the given layer."""
    backend = get_backend(layer)
    if backend == "RDB":
        _rdb_upsert(layer, record)
        return
    if backend == "NOTION":
        _notion_upsert(layer, record)
        return
    # EXCEL: load all -> replace -> save all
    records = _excel_load_all(layer)
    if layer == "history":
        match_field = "session_id"
    elif layer == "nowaday":
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
    """Delete records from the given layer."""
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
    """Fetch one record from the given layer (None if not found)."""
    records = load_all(layer)
    for r in records:
        if all(r.get(k) == v for k, v in key_filter.items()):
            return r
    return None


def make_history_id(service_id: str, user_id: str, session_id: str) -> str:
    return f"{service_id}__{user_id}__{session_id}"


def make_nowaday_id(service_id: str, user_id: str, period: str, gen_ts: str = "") -> str:
    """Nowaday is a snapshot history: a new snapshot is appended per generation.

    Passing gen_ts (a numeric string for the generation time, e.g. 20260516_103000) makes the ID unique,
    so even the same `period` accumulates as a separate record instead of being overwritten.
    Context/analysis code picks the latest by descending generated_at.
    When gen_ts is omitted, the legacy form is used (backward compatible).
    """
    base = f"{service_id}__{user_id}__{period}"
    return f"{base}__{gen_ts}" if gen_ts else base


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
