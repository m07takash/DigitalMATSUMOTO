"""エージェントペルソナのストレージ抽象化（Excel / RDB両対応）。

AGENT_PERSONA_SOURCE で切替（既定: EXCEL）:
  - "EXCEL": user/common/agent/persona_data/ 配下のxlsxを使用
  - "RDB":   PostgreSQL の digim_agent_personas テーブルを使用
  - "BOTH":  Excel + RDB をマージ（同persona_idはRDB優先）

psycopg2は遅延importなのでEXCEL運用時はDB不要。

Excelスキーマ（シート名: personas、1行1ペルソナ）:
  persona_id / template_agent / org(JSON) /
  company / dept / name / act /
  personality(JSON) / habits(CSV or "ALL") /
  knowledge(CSV or "ALL") / define_code(JSON) /
  character_text / character_file / active(Y|N)

ORGマッチング:
  agent側ORG（dict）の全キーを、persona側ORG（dict）が同値で含めばマッチ（agent側がpersona側の部分集合）。
"""
import json
import logging
import os
from pathlib import Path

import pandas as pd

import DigiM_Util as dmu

logger = logging.getLogger(__name__)

system_setting_dict = dmu.read_yaml_file("setting.yaml")
agent_folder_path = system_setting_dict.get("AGENT_FOLDER", "user/common/agent/")
PERSONA_DATA_FOLDER = str(Path(agent_folder_path) / "persona_data") + "/"

_PERSONA_COLUMNS = [
    "persona_id", "template_agent", "org",
    "company", "dept", "name", "act",
    "personality", "habits", "knowledge", "define_code",
    "character_text", "character_file", "active",
]
_JSON_COLUMNS = {"org", "personality", "define_code"}
_LIST_COLUMNS = {"habits", "knowledge"}


def get_source():
    return (os.getenv("AGENT_PERSONA_SOURCE") or "EXCEL").upper()


def _parse_cell(col, value):
    """セル値を正規化（None/空/JSON/CSV）。"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        s = ""
    else:
        s = str(value).strip()
    if not s:
        if col == "active":
            return "Y"
        if col in _JSON_COLUMNS:
            return {}
        if col in _LIST_COLUMNS:
            return ["ALL"]
        return ""
    if col in _JSON_COLUMNS:
        try:
            return json.loads(s)
        except Exception:
            logger.warning(f"persona列 {col} のJSONパース失敗: {s!r}")
            return {}
    if col in _LIST_COLUMNS:
        if s.upper() == "ALL":
            return ["ALL"]
        return [v.strip() for v in s.split(",") if v.strip()]
    return s


def _row_to_persona(row):
    persona = {}
    for col in _PERSONA_COLUMNS:
        if col in row.index:
            persona[col] = _parse_cell(col, row[col])
        else:
            persona[col] = _parse_cell(col, None)
    return persona


# ---------- Excel backend ----------
def _load_personas_excel(persona_files=None):
    folder = Path(PERSONA_DATA_FOLDER)
    if not folder.exists():
        return []
    if persona_files:
        targets = [folder / f for f in persona_files]
    else:
        targets = sorted(folder.glob("*.xlsx"))

    personas = []
    for path in targets:
        if not path.exists():
            logger.warning(f"ペルソナファイル未存在: {path}")
            continue
        try:
            df = pd.read_excel(str(path), sheet_name="personas", dtype=str).fillna("")
        except Exception as e:
            logger.warning(f"ペルソナファイル読込失敗 {path}: {e}")
            continue
        for _, row in df.iterrows():
            persona = _row_to_persona(row)
            if not persona.get("persona_id"):
                continue
            if persona.get("active", "Y") == "N":
                continue
            personas.append(persona)
    return personas


# ---------- RDB backend ----------
_RDB_DDL = """
CREATE TABLE IF NOT EXISTS digim_agent_personas (
    persona_id     TEXT PRIMARY KEY,
    template_agent TEXT,
    org            JSONB,
    company        TEXT,
    dept           TEXT,
    name           TEXT,
    act            TEXT,
    personality    JSONB,
    habits         JSONB,
    knowledge      JSONB,
    define_code    JSONB,
    character_text TEXT,
    character_file TEXT,
    active         CHAR(1) DEFAULT 'Y'
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
    import psycopg2
    return psycopg2.connect(**_rdb_config())


def _ensure_table(conn):
    with conn.cursor() as cur:
        cur.execute(_RDB_DDL)
    conn.commit()


def _load_personas_rdb():
    conn = _rdb_connect()
    try:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT persona_id, template_agent, org, company, dept, name, act,
                       personality, habits, knowledge, define_code,
                       character_text, character_file, active
                FROM digim_agent_personas
                WHERE active='Y' OR active IS NULL
            """)
            rows = cur.fetchall()
        personas = []
        for row in rows:
            personas.append({
                "persona_id":     row[0] or "",
                "template_agent": row[1] or "",
                "org":            row[2] or {},
                "company":        row[3] or "",
                "dept":           row[4] or "",
                "name":           row[5] or "",
                "act":            row[6] or "",
                "personality":    row[7] or {},
                "habits":         row[8] or ["ALL"],
                "knowledge":      row[9] or ["ALL"],
                "define_code":    row[10] or {},
                "character_text": row[11] or "",
                "character_file": row[12] or "",
                "active":         row[13] or "Y",
            })
        return personas
    finally:
        conn.close()


def _upsert_persona_rdb(persona):
    conn = _rdb_connect()
    try:
        _ensure_table(conn)
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO digim_agent_personas
                (persona_id, template_agent, org, company, dept, name, act,
                 personality, habits, knowledge, define_code,
                 character_text, character_file, active)
                VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s,
                        %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
                        %s, %s, %s)
                ON CONFLICT (persona_id) DO UPDATE SET
                    template_agent = EXCLUDED.template_agent,
                    org            = EXCLUDED.org,
                    company        = EXCLUDED.company,
                    dept           = EXCLUDED.dept,
                    name           = EXCLUDED.name,
                    act            = EXCLUDED.act,
                    personality    = EXCLUDED.personality,
                    habits         = EXCLUDED.habits,
                    knowledge      = EXCLUDED.knowledge,
                    define_code    = EXCLUDED.define_code,
                    character_text = EXCLUDED.character_text,
                    character_file = EXCLUDED.character_file,
                    active         = EXCLUDED.active
            """, (
                persona.get("persona_id", ""),
                persona.get("template_agent", ""),
                json.dumps(persona.get("org", {}), ensure_ascii=False),
                persona.get("company", ""),
                persona.get("dept", ""),
                persona.get("name", ""),
                persona.get("act", ""),
                json.dumps(persona.get("personality", {}), ensure_ascii=False),
                json.dumps(persona.get("habits", ["ALL"]), ensure_ascii=False),
                json.dumps(persona.get("knowledge", ["ALL"]), ensure_ascii=False),
                json.dumps(persona.get("define_code", {}), ensure_ascii=False),
                persona.get("character_text", ""),
                persona.get("character_file", ""),
                persona.get("active", "Y"),
            ))
        conn.commit()
    finally:
        conn.close()


# ---------- public API ----------
def load_personas(template_agent=None, persona_files=None):
    """全ペルソナ取得。template_agent指定時はそのテンプレ用または未指定（全テンプレ共通）に絞る。"""
    src = get_source()
    if src == "RDB":
        personas = _load_personas_rdb()
    elif src == "BOTH":
        personas_excel = _load_personas_excel(persona_files)
        personas_rdb = _load_personas_rdb()
        rdb_ids = {p["persona_id"] for p in personas_rdb}
        personas = personas_rdb + [p for p in personas_excel if p["persona_id"] not in rdb_ids]
    else:
        personas = _load_personas_excel(persona_files)

    if template_agent:
        personas = [p for p in personas
                    if not p.get("template_agent") or p["template_agent"] == template_agent]
    return personas


def find_personas_by_org(agent_org, template_agent=None, persona_files=None):
    """agent側ORG（dict）の全キーを persona側ORGが同値で含むペルソナを返す（subset match）。
    agent_orgが空dictなら全件返す。"""
    personas = load_personas(template_agent, persona_files)
    if not isinstance(agent_org, dict) or not agent_org:
        return personas
    matched = []
    for p in personas:
        org = p.get("org") or {}
        if not isinstance(org, dict):
            continue
        if all(org.get(k) == v for k, v in agent_org.items()):
            matched.append(p)
    return matched


def upsert_personas_from_excel(file_path):
    """ExcelファイルからRDBへ全ペルソナをUPSERT。active='N'の行も論理削除としてそのまま記録。
    戻り値: 処理件数 (登録/更新, スキップ)"""
    df = pd.read_excel(file_path, sheet_name="personas", dtype=str).fillna("")
    cnt_upsert, cnt_skip = 0, 0
    for _, row in df.iterrows():
        persona = _row_to_persona(row)
        if not persona.get("persona_id"):
            cnt_skip += 1
            continue
        _upsert_persona_rdb(persona)
        cnt_upsert += 1
    return cnt_upsert, cnt_skip
