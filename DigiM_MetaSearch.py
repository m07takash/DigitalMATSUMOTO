"""Generalized META_SEARCH: extractor-driven WHERE + per-chunk BONUS.

Legacy shape (still accepted, auto-converted):
    "META_SEARCH": {"CONDITION": ["DATE"], "BONUS": 0.5}

New shape:
    "META_SEARCH": {
        "CONDITIONS": [
            {
              "TYPE": "DATE"|"CATEGORY"|"NUMBER"|"TEXT",
              "EXTRACTOR": "DATE",           # default = TYPE
              "FIELD": "create_date_ts",     # Chroma metadata key
              "EXTRACTOR_HINT": ...,          # list | dict | "@auto"
              "MATCH": "range"|"in"|"equals"|"contains",
              "BONUS": 0.5                    # <1 boosts, >1 penalises
            }, ...
        ]
    }

Extractor call output (single LLM call, keys are EXTRACTOR names):
    {
      "DATE":   [{"start":"2024/01/01","end":"2024/12/31"}, ...],  # list of ranges
      "PLACE":  ["Tokyo","Osaka"],                                  # list of strings
      "RATING": [{"min":3,"max":5}, {"max":1}]                     # list of numeric ranges
    }

For MATCH:contains the LLM value is a list of substrings; each chunk's FIELD
value is checked for any substring hit (post-filter, no WHERE support in Chroma).
"""
import os
import json
import logging
from pathlib import Path
from typing import Any

import DigiM_Util as dmu

logger = logging.getLogger("DigiM_MetaSearch")

_system_setting_dict = dmu.read_yaml_file("setting.yaml")
_rag_folder_db_path = _system_setting_dict["RAG_FOLDER_DB"]
_SIDECAR_DIRNAME = "_meta_field_values"


# ---------------------------------------------------------------- normalize
def _legacy_to_conditions(ms: dict) -> list:
    """Convert `{"CONDITION": ["DATE"], "BONUS": 0.5}` → CONDITIONS list.
    Supports DATE only (the only type the legacy shape ever meant)."""
    if not isinstance(ms, dict):
        return []
    if "CONDITIONS" in ms and isinstance(ms["CONDITIONS"], list):
        return list(ms["CONDITIONS"])
    if "CONDITION" not in ms:
        return []
    out = []
    bonus = ms.get("BONUS", 1.0)
    for t in (ms.get("CONDITION") or []):
        if t == "DATE":
            out.append({
                "TYPE": "DATE",
                "EXTRACTOR": "DATE",
                "FIELD": "create_date_ts",
                "MATCH": "range",
                "BONUS": bonus,
            })
    return out


def get_conditions(rag_data: dict) -> list:
    """Return normalized CONDITIONS list for one rag_data dict.
    `rag_data` here is the DATA entry (has META_SEARCH under it).
    Absent / empty META_SEARCH → []."""
    ms = rag_data.get("META_SEARCH") if isinstance(rag_data, dict) else None
    if not ms:
        return []
    conds = _legacy_to_conditions(ms)
    normalized = []
    for c in conds:
        if not isinstance(c, dict):
            continue
        c = dict(c)
        c.setdefault("EXTRACTOR", c.get("TYPE"))
        c.setdefault("MATCH", "range")
        c.setdefault("BONUS", 1.0)
        if not c.get("FIELD") or not c.get("EXTRACTOR"):
            continue
        normalized.append(c)
    return normalized


# ---------------------------------------------------------------- sidecar
def sidecar_path(data_name: str) -> Path:
    return Path(_rag_folder_db_path) / _SIDECAR_DIRNAME / f"{data_name}.json"


def load_sidecar(data_name: str) -> dict:
    p = sidecar_path(data_name)
    if not p.exists():
        return {}
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to read sidecar %s: %s", p, e)
        return {}


def save_sidecar(data_name: str, values_by_field: dict) -> None:
    p = sidecar_path(data_name)
    os.makedirs(p.parent, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(values_by_field, f, indent=4, ensure_ascii=False)
        f.write("\n")
    tmp.replace(p)


def collect_distinct_field_values(rag_chunks: list, fields: list) -> dict:
    """Given a list of chunk dicts and target metadata field names, return
    {field: sorted list of distinct non-empty stringified values}.
    Only used at ingestion time to produce the sidecar."""
    if not fields:
        return {}
    acc: dict = {f: set() for f in fields}
    for chunk in rag_chunks:
        if not isinstance(chunk, dict):
            continue
        for f in fields:
            v = chunk.get(f)
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                for x in v:
                    s = str(x).strip()
                    if s:
                        acc[f].add(s)
            else:
                s = str(v).strip()
                if s:
                    acc[f].add(s)
    return {f: sorted(vs) for f, vs in acc.items() if vs}


def sidecar_fields_for_data(rag_datas_iter) -> dict:
    """For each DATA_NAME across the given rag_datas, return the set of
    FIELDs whose EXTRACTOR_HINT is "@auto" (sidecar-driven). Used by
    ingestion so it only bothers computing distinct values that will
    actually be consumed."""
    out: dict = {}
    for rd in rag_datas_iter or []:
        if not isinstance(rd, dict):
            continue
        data_name = rd.get("DATA_NAME")
        if not data_name:
            continue
        for c in get_conditions(rd):
            hint = c.get("EXTRACTOR_HINT")
            if hint == "@auto":
                out.setdefault(data_name, set()).add(c["FIELD"])
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------- extractor specs
def collect_extractor_specs(rag_datas_iter) -> list:
    """Deduplicate extractor requests across all RAG data. Returns
    a list of {"EXTRACTOR", "TYPE", "HINT"} used to build one LLM prompt.
    HINT is resolved: "@auto" is expanded to the sidecar's distinct values
    for the referenced (DATA_NAME, FIELD)."""
    seen = {}
    for rd in rag_datas_iter or []:
        if not isinstance(rd, dict):
            continue
        data_name = rd.get("DATA_NAME")
        for c in get_conditions(rd):
            hint = c.get("EXTRACTOR_HINT")
            if hint == "@auto":
                sidecar = load_sidecar(data_name) if data_name else {}
                hint = sidecar.get(c["FIELD"], [])
            key = (c["EXTRACTOR"], c.get("TYPE"), _hashable(hint))
            if key in seen:
                if hint and isinstance(hint, list) and isinstance(seen[key]["HINT"], list):
                    merged = sorted(set(seen[key]["HINT"]) | set(map(str, hint)))
                    seen[key]["HINT"] = merged
                continue
            seen[key] = {"EXTRACTOR": c["EXTRACTOR"],
                         "TYPE": c.get("TYPE"),
                         "HINT": hint}
    return list(seen.values())


def _hashable(v):
    if isinstance(v, (list, tuple)):
        return tuple(sorted(str(x) for x in v))
    if isinstance(v, dict):
        return tuple(sorted((str(k), str(vv)) for k, vv in v.items()))
    return v


# ---------------------------------------------------------------- WHERE builder
def _range_clauses_for_condition(field: str, values: list) -> list:
    """DATE-shaped ranges: [{"start":"YYYY/MM/DD","end":"..."}].
    NUMBER-shaped ranges: [{"min":...,"max":...,
                             "exclusive_min":bool,"exclusive_max":bool}]."""
    from datetime import datetime as _dt
    clauses = []
    for r in (values or []):
        if not isinstance(r, dict):
            continue
        if "start" in r or "end" in r:
            try:
                lo = _dt.strptime(r["start"], "%Y/%m/%d").timestamp() if r.get("start") else None
                hi = _dt.strptime(r["end"],   "%Y/%m/%d").timestamp() if r.get("end")   else None
            except Exception:
                continue
            parts = []
            if lo is not None:
                parts.append({field: {"$gte": lo}})
            if hi is not None:
                parts.append({field: {"$lte": hi}})
            if parts:
                clauses.append(parts[0] if len(parts) == 1 else {"$and": parts})
        else:
            lo = r.get("min")
            hi = r.get("max")
            emin = bool(r.get("exclusive_min"))
            emax = bool(r.get("exclusive_max"))
            parts = []
            if lo is not None:
                parts.append({field: {"$gt" if emin else "$gte": lo}})
            if hi is not None:
                parts.append({field: {"$lt" if emax else "$lte": hi}})
            if parts:
                clauses.append(parts[0] if len(parts) == 1 else {"$and": parts})
    return clauses


def _in_clauses_for_condition(field: str, values: list) -> list:
    if not values:
        return []
    xs = [str(v) if not isinstance(v, str) else v for v in values]
    xs = [v for v in xs if v]
    if not xs:
        return []
    return [{field: {"$in": xs}}]


def _equals_clauses_for_condition(field: str, values: list) -> list:
    if not values:
        return []
    return [{field: {"$eq": v}} for v in values]


def build_where_extension(rag_data: dict, extracted: dict) -> Any:
    """Build the WHERE fragment for the meta-search sub-query. Returns:
      - dict: composite $or WHERE clause to intersect with base WHERE
      - None: nothing to add (no expressible condition matched extractor)"""
    clauses = []
    for c in get_conditions(rag_data):
        vals = extracted.get(c["EXTRACTOR"]) if isinstance(extracted, dict) else None
        if not vals:
            continue
        m = c.get("MATCH", "range")
        f = c["FIELD"]
        if m in ("range", "range_or"):
            clauses.extend(_range_clauses_for_condition(f, vals))
        elif m == "in":
            clauses.extend(_in_clauses_for_condition(f, vals))
        elif m == "equals":
            clauses.extend(_equals_clauses_for_condition(f, vals))
        elif m == "contains":
            continue
        else:
            logger.warning("Unknown META_SEARCH MATCH: %s", m)
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


def compute_chunk_bonus(rag_data: dict, extracted: dict, chunk_meta: dict) -> float:
    """Per-chunk BONUS multiplier. Evaluates each META_SEARCH.CONDITION
    on this chunk; matched conditions contribute their BONUS via product.
    Returns 1.0 when nothing matched (no boost/penalty)."""
    if not chunk_meta:
        return 1.0
    product = 1.0
    matched_any = False
    for c in get_conditions(rag_data):
        vals = extracted.get(c["EXTRACTOR"]) if isinstance(extracted, dict) else None
        if not vals:
            continue
        f = c["FIELD"]
        mv = chunk_meta.get(f)
        m = c.get("MATCH", "range")
        if _condition_matches(m, mv, vals):
            product *= float(c.get("BONUS", 1.0))
            matched_any = True
    return product if matched_any else 1.0


def _condition_matches(match_op: str, meta_value, extracted_values) -> bool:
    if meta_value is None:
        return False
    if match_op in ("range", "range_or"):
        try:
            mv = float(meta_value)
        except (TypeError, ValueError):
            return False
        from datetime import datetime as _dt
        for r in (extracted_values or []):
            if not isinstance(r, dict):
                continue
            lo = None
            hi = None
            emin = bool(r.get("exclusive_min"))
            emax = bool(r.get("exclusive_max"))
            if "start" in r or "end" in r:
                try:
                    if r.get("start"):
                        lo = _dt.strptime(r["start"], "%Y/%m/%d").timestamp()
                    if r.get("end"):
                        hi = _dt.strptime(r["end"], "%Y/%m/%d").timestamp()
                except Exception:
                    continue
            else:
                lo = r.get("min")
                hi = r.get("max")
            if lo is not None:
                if emin and not mv > lo:
                    continue
                if not emin and not mv >= lo:
                    continue
            if hi is not None:
                if emax and not mv < hi:
                    continue
                if not emax and not mv <= hi:
                    continue
            return True
        return False
    if match_op == "in":
        try:
            xs = [str(x) for x in extracted_values]
        except Exception:
            return False
        return str(meta_value) in xs
    if match_op == "equals":
        return any(str(v) == str(meta_value) for v in (extracted_values or []))
    if match_op == "contains":
        s = str(meta_value)
        for v in (extracted_values or []):
            if v and str(v) in s:
                return True
        return False
    return False


def has_any_condition(rag_data: dict) -> bool:
    return bool(get_conditions(rag_data))
