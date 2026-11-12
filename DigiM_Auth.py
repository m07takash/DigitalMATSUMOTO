"""Read/write the user authentication master (both JSON and RDB).

Toggled by LOGIN_AUTH_METHOD in system.env:
  - "JSON" (default): use the JSON file specified by USER_MST_FILE
  - "RDB": use the PostgreSQL `digim_users` table

When LOGIN_AUTH_METHOD="RDB", if PostgreSQL connection info (POSTGRES_HOST etc.)
is missing or unreachable, the exception is propagated (the caller handles it).
"""
import json
import logging
import os

import DigiM_Util as dmu
import DigiM_MstStore as dmms

logger = logging.getLogger(__name__)

system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]


def get_method():
    return (os.getenv("LOGIN_AUTH_METHOD") or "JSON").upper()


# ---------- master store (JSON file, or digim_mst under MST_STORE_METHOD) ----------
def _load_users_store():
    try:
        return dmms.load("users") or {}
    except Exception:
        return {}


def _save_users_store(users):
    dmms.save("users", users, indent=2)


# ---------- RDB backend ----------
_RDB_DDL = """
CREATE TABLE IF NOT EXISTS digim_users (
    user_id    TEXT PRIMARY KEY,
    name       TEXT,
    pw         TEXT,
    group_cd   JSONB,
    agent      TEXT,
    allowed    JSONB,
    defaults   JSONB
)
"""
# A table created before `defaults` existed loses every per-user Default on
# the RDB path, which the WebUI then replaces with its hard-coded values.
_RDB_MIGRATE = "ALTER TABLE digim_users ADD COLUMN IF NOT EXISTS defaults JSONB"


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _rdb_config():
    # One definition of the connection, so POSTGRES_SSLMODE reaches every
    # store: a local container without SSL could not be used otherwise.
    import DigiM_SessionStore as _dmss
    return _dmss.pg_connect_kwargs()


def _rdb_connect():
    import psycopg2  # Lazy import: not needed when running in JSON-only mode
    return psycopg2.connect(**_rdb_config())


def _ensure_user_table(conn):
    with conn.cursor() as cur:
        cur.execute(_RDB_DDL)
        cur.execute(_RDB_MIGRATE)
    conn.commit()


def _load_users_rdb():
    conn = _rdb_connect()
    try:
        _ensure_user_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, name, pw, group_cd, agent, allowed, defaults FROM digim_users")
            rows = cur.fetchall()
        users = {}
        for user_id, name, pw, group_cd, agent, allowed, defaults in rows:
            # group_cd is JSONB (array). Also tolerate the legacy string form.
            if isinstance(group_cd, list):
                groups = group_cd
            elif isinstance(group_cd, str) and group_cd:
                groups = [group_cd]
            else:
                groups = []
            users[user_id] = {
                "Name": name or "",
                "PW": pw or "",
                "Group": groups,
                "Agent": agent or "",
                "Allowed": allowed or {},
                "Defaults": defaults or {},
            }
        return users
    finally:
        conn.close()


def _save_users_rdb(users):
    """UPSERT all users. Intended for use cases such as adding users or changing passwords.
    Users not present in the argument are NOT deleted (to prevent accidental removal)."""
    conn = _rdb_connect()
    try:
        _ensure_user_table(conn)
        with conn.cursor() as cur:
            for user_id, info in users.items():
                # Group accepts both string and list; stored as an array in JSONB
                raw_group = info.get("Group", "")
                if isinstance(raw_group, list):
                    groups = [g for g in raw_group if g]
                elif raw_group:
                    groups = [raw_group]
                else:
                    groups = []
                cur.execute(
                    """
                    INSERT INTO digim_users (user_id, name, pw, group_cd, agent, allowed, defaults)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (user_id) DO UPDATE
                    SET name=EXCLUDED.name, pw=EXCLUDED.pw,
                        group_cd=EXCLUDED.group_cd, agent=EXCLUDED.agent,
                        allowed=EXCLUDED.allowed, defaults=EXCLUDED.defaults
                    """,
                    (
                        user_id,
                        info.get("Name", ""),
                        info.get("PW", ""),
                        json.dumps(groups, ensure_ascii=False),
                        info.get("Agent", ""),
                        json.dumps(info.get("Allowed", {}), ensure_ascii=False),
                        json.dumps(info.get("Defaults", {}), ensure_ascii=False),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


# ---------- public API ----------
# MST_STORE_METHOD (setting.yaml) is the one switch for every master, users
# included. LOGIN_AUTH_METHOD=RDB predates it and still selects the
# normalized `digim_users` table, but only while the master store is on JSON;
# once the store is PostgreSQL the users master lives in `digim_mst` with the
# rest, and the old flag is reported rather than obeyed.
def _legacy_rdb() -> bool:
    if get_method() != "RDB":
        return False
    if dmms.method() == "PostgreSQL":
        logger.warning("LOGIN_AUTH_METHOD=RDB is ignored: MST_STORE_METHOD=PostgreSQL "
                       "keeps users in digim_mst. Run `python3 DigiM_MstStore.py import users` "
                       "once if they still live in digim_users.")
        return False
    return True


def load_user_master():
    if _legacy_rdb():
        return _load_users_rdb()
    return _load_users_store()


def save_user_master(users):
    if _legacy_rdb():
        _save_users_rdb(users)
        return
    _save_users_store(users)
