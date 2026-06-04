"""Storage abstraction for agent personas (both Excel and RDB).

Switched by AGENT_PERSONA_SOURCE (default: EXCEL):
  - "EXCEL": use xlsx files under user/common/agent/persona_data/
  - "RDB":   use the PostgreSQL `digim_agent_personas` table
  - "BOTH":  merge Excel + RDB (the same persona_id prefers RDB)

psycopg2 is lazy-imported, so no DB is required for the EXCEL mode.

Excel schema (sheet name: personas, one row per persona):
  persona_id / template_agent / org(JSON) /
  company / dept / name / act /
  personality(JSON) / habits(CSV or "ALL") /
  knowledge(CSV or "ALL") / define_code(JSON) /
  character_text / character_file / active(Y|N)

ORG matching:
  Matches when the persona-side ORG (dict) contains every key of the agent-side
  ORG (dict) with equal values (the agent side is a subset of the persona side).
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
    """Normalize a cell value (None / empty / JSON / CSV)."""
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
            logger.warning(f"failed to parse JSON for persona column {col}: {s!r}")
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


# ---------- File backend (Excel + CSV) ----------
_FILE_EXTS = (".xlsx", ".csv")


def _read_persona_dataframe(path: Path):
    """Read one persona file (.xlsx or .csv) into a DataFrame of strings.
    Schema is the same as the Excel sheet `personas` (same column names).
    For CSV, the file itself is one persona table (no sheet concept).
    """
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return pd.read_excel(str(path), sheet_name="personas", dtype=str).fillna("")
    if suffix == ".csv":
        # utf-8-sig handles a UTF-8 BOM if present; falls back to CP932 for legacy Excel-exported CSVs.
        for enc in ("utf-8-sig", "cp932", "utf-8"):
            try:
                return pd.read_csv(str(path), dtype=str, encoding=enc).fillna("")
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("utf-8/cp932", b"", 0, 1, f"could not decode {path}")
    raise ValueError(f"unsupported persona file extension: {suffix}")


def _load_personas_excel(persona_files=None):
    """Load personas from xlsx and csv files under PERSONA_DATA_FOLDER.

    Function name is kept for backward compatibility; despite the name it now
    also handles CSV files with the same column schema.
    """
    folder = Path(PERSONA_DATA_FOLDER)
    if not folder.exists():
        return []
    if persona_files:
        targets = [folder / f for f in persona_files]
    else:
        targets = sorted(p for ext in _FILE_EXTS for p in folder.glob(f"*{ext}"))

    personas = []
    for path in targets:
        if not path.exists():
            logger.warning(f"persona file does not exist: {path}")
            continue
        if path.suffix.lower() not in _FILE_EXTS:
            logger.warning(f"unsupported persona file extension (skipping): {path}")
            continue
        try:
            df = _read_persona_dataframe(path)
        except Exception as e:
            logger.warning(f"failed to read persona file {path}: {e}")
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
def load_personas(template_agent=None, persona_files=None, source=None):
    """Return all personas. When template_agent is specified, return only those
    targeting that template (or those unspecified, i.e. shared across all templates).
    Specifying source lets you switch the reference source per agent ("EXCEL"/"RDB"/"BOTH").
    When unspecified, falls back to the AGENT_PERSONA_SOURCE environment variable."""
    src = (source or get_source()).upper()
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


def find_personas_by_org(agent_org, template_agent=None, persona_files=None, source=None):
    """Return personas whose ORG (dict) contains every key of the agent-side ORG with equal
    values (subset match). If agent_org is an empty dict, return all personas.
    `source` lets you switch the reference source per agent."""
    personas = load_personas(template_agent, persona_files, source=source)
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


def upsert_personas_from_file(file_path):
    """UPSERT every persona from a file (.xlsx or .csv) into the RDB. Rows with active='N'
    are also recorded as logical deletes (kept as-is).
    Returns: counts (upsert, skip)."""
    df = _read_persona_dataframe(Path(file_path))
    cnt_upsert, cnt_skip = 0, 0
    for _, row in df.iterrows():
        persona = _row_to_persona(row)
        if not persona.get("persona_id"):
            cnt_skip += 1
            continue
        _upsert_persona_rdb(persona)
        cnt_upsert += 1
    return cnt_upsert, cnt_skip


# Legacy alias (kept so existing callers using the Excel-only name keep working)
upsert_personas_from_excel = upsert_personas_from_file
