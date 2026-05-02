"""ユーザー認証マスタの読み書き（JSON / RDB両対応）。

system.env の LOGIN_AUTH_METHOD で切替:
  - "JSON"（既定）: USER_MST_FILE で指定したJSONを使用
  - "RDB": PostgreSQL の digim_users テーブルを使用

LOGIN_AUTH_METHOD="RDB" のとき、PostgreSQL接続情報（POSTGRES_HOST 等）が
未設定／接続不可なら例外を伝播する（呼び出し側でハンドリング）。
"""
import json
import logging
import os

import DigiM_Util as dmu

logger = logging.getLogger(__name__)

system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]


def get_method():
    return (os.getenv("LOGIN_AUTH_METHOD") or "JSON").upper()


# ---------- JSON backend ----------
def _json_path():
    return mst_folder_path + (os.getenv("USER_MST_FILE") or "")


def _load_users_json():
    path = _json_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}


def _save_users_json(users):
    path = _json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


# ---------- RDB backend ----------
_RDB_DDL = """
CREATE TABLE IF NOT EXISTS digim_users (
    user_id    TEXT PRIMARY KEY,
    name       TEXT,
    pw         TEXT,
    group_cd   JSONB,
    agent      TEXT,
    allowed    JSONB
)
"""


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
    import psycopg2  # 遅延import: JSONモードのみで使う場合にimport不要
    return psycopg2.connect(**_rdb_config())


def _ensure_user_table(conn):
    with conn.cursor() as cur:
        cur.execute(_RDB_DDL)
    conn.commit()


def _load_users_rdb():
    conn = _rdb_connect()
    try:
        _ensure_user_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, name, pw, group_cd, agent, allowed FROM digim_users")
            rows = cur.fetchall()
        users = {}
        for user_id, name, pw, group_cd, agent, allowed in rows:
            # group_cd は JSONB（配列）または旧仕様の文字列にも一応対応
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
            }
        return users
    finally:
        conn.close()


def _save_users_rdb(users):
    """全ユーザーをUPSERT。ユーザー追加・パスワード変更等のユースケース向け。
    引数に含まれないユーザーは削除しない（誤削除防止）。"""
    conn = _rdb_connect()
    try:
        _ensure_user_table(conn)
        with conn.cursor() as cur:
            for user_id, info in users.items():
                # Groupは文字列・リストの両方を受け付け、JSONBには配列で保存
                raw_group = info.get("Group", "")
                if isinstance(raw_group, list):
                    groups = [g for g in raw_group if g]
                elif raw_group:
                    groups = [raw_group]
                else:
                    groups = []
                cur.execute(
                    """
                    INSERT INTO digim_users (user_id, name, pw, group_cd, agent, allowed)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb)
                    ON CONFLICT (user_id) DO UPDATE
                    SET name=EXCLUDED.name, pw=EXCLUDED.pw,
                        group_cd=EXCLUDED.group_cd, agent=EXCLUDED.agent,
                        allowed=EXCLUDED.allowed
                    """,
                    (
                        user_id,
                        info.get("Name", ""),
                        info.get("PW", ""),
                        json.dumps(groups, ensure_ascii=False),
                        info.get("Agent", ""),
                        json.dumps(info.get("Allowed", {}), ensure_ascii=False),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


# ---------- public API ----------
def load_user_master():
    if get_method() == "RDB":
        return _load_users_rdb()
    return _load_users_json()


def save_user_master(users):
    if get_method() == "RDB":
        _save_users_rdb(users)
        return
    _save_users_json(users)
