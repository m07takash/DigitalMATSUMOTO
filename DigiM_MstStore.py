"""Master-data store: one backend for every file under MST_FOLDER.

Toggled by MST_STORE_METHOD in setting.yaml:
  - "JSON" (default): the file under MST_FOLDER, exactly as before
  - "PostgreSQL":     one row per master in `digim_mst` (name / JSONB payload)

Callers address a master by its logical name (`users`, `rags`, ...), never
by path, so the backend can change without touching them. The value that
comes back is the parsed JSON in both modes.

PostgreSQL mode reads through a short TTL cache: masters are consulted on
every turn (prompt templates per agent load, category_map inside the chat
render loop), and a round trip per read would put a database call on the
render path. A save drops the local cache; another process sees the change
within MST_STORE_CACHE_SEC. A failed connection falls back to the JSON file
for that call, loudly, so a bad DB cannot keep the app from booting.
"""
import json
import logging
import os
import sys
import threading
import time
from typing import Any, Optional

import DigiM_Util as dmu

logger = logging.getLogger(__name__)

_setting = dmu.read_yaml_file("setting.yaml") or {}
_mst_folder = _setting.get("MST_FOLDER", "user/common/mst/")
_CACHE_SEC = float(_setting.get("MST_STORE_CACHE_SEC", 10) or 0)

if os.path.exists("system.env"):
    from dotenv import load_dotenv
    load_dotenv("system.env")

# Logical name -> (env var that may rename the file, default file name).
# The env overrides predate this module and stay honoured so a deployment
# that renamed a master keeps reading the same file.
MASTERS = {
    "users":                   ("USER_MST_FILE",            "users.json"),
    "rags":                    ("RAG_MST_FILE",             "rags.json"),
    "prompt_templates":        ("PROMPT_TEMPLATE_MST_FILE", "prompt_templates.json"),
    "notion_db":               ("NOTION_MST_FILE",          "notion_db.json"),
    "category_map":            ("",                         "category_map.json"),
    "scheduled_jobs":          ("",                         "scheduled_jobs.json"),
    "session_summary_presets": ("",                         "session_summary_presets.json"),
}

_TABLE = "digim_mst"
_PG_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
    name        TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def method() -> str:
    m = str(_setting.get("MST_STORE_METHOD") or "JSON").strip().lower()
    if m in ("postgresql", "postgres", "pg"):
        return "PostgreSQL"
    if m not in ("json", "file"):
        logger.warning("Unknown MST_STORE_METHOD=%r; defaulting to JSON.", m)
    return "JSON"


def file_name(name: str) -> str:
    env_key, default = MASTERS.get(name, ("", f"{name}.json"))
    return (os.getenv(env_key) if env_key else "") or _setting.get(env_key, "") or default


def path(name: str) -> str:
    return os.path.join(_mst_folder, file_name(name))


# ----------------------------------------------------------------- JSON --
def _json_load(name: str, default):
    # A fresh checkout ships only sample_<name>.json. Reading it until the
    # first save writes <name>.json keeps the masters without an env override
    # (category_map / scheduled_jobs / session_summary_presets) from starting
    # out empty.
    if not os.path.exists(path(name)):
        sample = os.path.join(_mst_folder, "sample_" + file_name(name))
        if os.path.exists(sample):
            return dmu.read_json_file("sample_" + file_name(name), _mst_folder)
    data = dmu.read_json_file(file_name(name), _mst_folder)
    # read_json_file hands back {} for a missing file; a list-shaped master
    # (scheduled_jobs) must not turn into a dict on that path.
    if data == {} and default is not None and not os.path.exists(path(name)):
        return default
    return data


def _json_save(name: str, data, indent: int):
    dmu.save_json_file(data, path(name), indent=indent)


# ----------------------------------------------------------- PostgreSQL --
_conn = None
_conn_lock = threading.Lock()
_ddl_done = False
_cache: dict = {}            # name -> (expires_at, data)
_cache_lock = threading.Lock()


def _connect():
    global _conn
    if _conn is not None and getattr(_conn, "closed", 1) == 0:
        return _conn
    import psycopg2
    import DigiM_SessionStore as _dmss
    _conn = psycopg2.connect(**_dmss.pg_connect_kwargs())
    _conn.autocommit = True
    return _conn


def _cursor():
    global _conn, _ddl_done
    last = None
    for attempt in (1, 2):
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
            if not _ddl_done:
                cur.execute(_PG_DDL.format(table=_TABLE))
                _ddl_done = True
            return cur
        except Exception as e:
            last = e
            try:
                conn.close()
            except Exception:
                pass
            _conn = None
            _ddl_done = False
            if attempt == 2:
                raise last


def _cache_get(name: str):
    if _CACHE_SEC <= 0:
        return None
    with _cache_lock:
        hit = _cache.get(name)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    return None


def _cache_put(name: str, data):
    if _CACHE_SEC <= 0:
        return
    with _cache_lock:
        _cache[name] = (time.monotonic() + _CACHE_SEC, data)


def _cache_drop(name: Optional[str] = None):
    with _cache_lock:
        if name is None:
            _cache.clear()
        else:
            _cache.pop(name, None)


def _pg_load(name: str, default):
    cached = _cache_get(name)
    if cached is not None:
        return json.loads(json.dumps(cached))
    with _conn_lock:
        cur = _cursor()
        try:
            cur.execute(f"SELECT data FROM {_TABLE} WHERE name=%s", (name,))
            row = cur.fetchone()
        finally:
            try:
                cur.close()
            except Exception:
                pass
    if row is None:
        return default if default is not None else {}
    data = row[0]
    _cache_put(name, data)
    return json.loads(json.dumps(data))


def _pg_save(name: str, data):
    with _conn_lock:
        cur = _cursor()
        try:
            cur.execute(
                f"INSERT INTO {_TABLE} (name, data, updated_at) "
                f"VALUES (%s, %s::jsonb, NOW()) "
                f"ON CONFLICT (name) DO UPDATE SET data=EXCLUDED.data, updated_at=NOW()",
                (name, json.dumps(data, ensure_ascii=False)))
        finally:
            try:
                cur.close()
            except Exception:
                pass
    _cache_drop(name)


def _pg_exists(name: str) -> bool:
    with _conn_lock:
        cur = _cursor()
        try:
            cur.execute(f"SELECT 1 FROM {_TABLE} WHERE name=%s", (name,))
            return cur.fetchone() is not None
        finally:
            try:
                cur.close()
            except Exception:
                pass


# --------------------------------------------------------------- public --
def load(name: str, default: Any = None):
    """The master's parsed JSON. `default` is what a missing master yields
    (a dict by default; pass [] for a list-shaped one)."""
    if method() == "PostgreSQL":
        try:
            return _pg_load(name, default)
        except Exception as e:
            logger.error("MstStore: PostgreSQL read of %r failed (%s); reading %s instead",
                         name, e, path(name))
    return _json_load(name, default)


def save(name: str, data, indent: int = 2):
    if method() == "PostgreSQL":
        try:
            _pg_save(name, data)
            return
        except Exception as e:
            # The file write below is not what the next PG read returns, so
            # this cannot be quiet.
            logger.error("MstStore: PostgreSQL write of %r failed (%s); wrote %s instead "
                         "— that change is NOT in the database", name, e, path(name))
    _json_save(name, data, indent)


def exists(name: str) -> bool:
    if method() == "PostgreSQL":
        try:
            return _pg_exists(name)
        except Exception as e:
            logger.error("MstStore: PostgreSQL check of %r failed (%s)", name, e)
    return os.path.exists(path(name))


# ------------------------------------------------------------ migration --
def import_json_to_db(names=None) -> dict:
    """Copy the JSON masters into `digim_mst`. The row wins over the file
    from then on, so this is a one-shot step when switching to PostgreSQL."""
    out = {}
    for name in (names or MASTERS):
        if not os.path.exists(path(name)):
            out[name] = "no file"
            continue
        data = _json_load(name, [] if name == "scheduled_jobs" else {})
        _pg_save(name, data)
        out[name] = "imported"
    return out


def export_db_to_json(names=None, indent: int = 2) -> dict:
    """Write the `digim_mst` rows back out as files, for going back to JSON
    mode or for taking a diffable backup."""
    out = {}
    for name in (names or MASTERS):
        if not _pg_exists(name):
            out[name] = "no row"
            continue
        _json_save(name, _pg_load(name, None), indent)
        out[name] = "exported"
    return out


def _cli(argv):
    cmd = (argv[1] if len(argv) > 1 else "").lower()
    names = argv[2:] or None
    if cmd == "import":
        print(json.dumps(import_json_to_db(names), indent=2))
    elif cmd == "export":
        print(json.dumps(export_db_to_json(names), indent=2))
    elif cmd == "list":
        for name in MASTERS:
            print(f"{name:<26} {'row' if (method() == 'PostgreSQL' and _pg_exists(name)) else '-':<4} "
                  f"{'file' if os.path.exists(path(name)) else '-':<5} {path(name)}")
    else:
        print(f"usage: python3 {os.path.basename(argv[0])} import|export|list [name ...]\n"
              f"method: {method()}   masters: {', '.join(MASTERS)}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
