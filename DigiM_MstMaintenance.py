"""Editing the masters from the WebUI (Master Maintenance).

Every read and write goes through DigiM_MstStore, so the same screen edits the
JSON files or the `digim_mst` rows depending on MST_STORE_METHOD. users goes
through DigiM_Auth, which also covers the legacy LOGIN_AUTH_METHOD=RDB table.

A save is refused when the master changed after the editor opened it (another
user, the scheduler writing last_run, a second tab): writing the editor's copy
back would silently undo that change. Each save first copies the previous
document to MST_FOLDER/_backup/<name>/, whichever backend is in use.
"""
import hashlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Tuple

import DigiM_MstStore as dmms
import DigiM_Util as dmu

PW_MASK = "********"
BACKUP_KEEP = 30

# label, what the master holds, what has to happen before a change takes effect
MASTER_INFO = {
    "users": ("Users", "Login users, groups, permissions (Allowed) and per-user defaults.",
              "Takes effect at the user's next login."),
    "rags": ("RAG", "RAG data sources and how each is chunked and vectorized.",
             "Run Update RAG to rebuild the data."),
    "prompt_templates": ("Prompt templates", "PROMPT_TEMPLATE and SPEAKING_STYLE texts used by agents and practices.",
                         "Used from the next turn."),
    "notion_db": ("Notion DB", "Notion database ids by logical name.", "Used from the next read or write."),
    "category_map": ("Category map", "Categories and their colors (feedback, analytics).", "Used from the next render."),
    "scheduled_jobs": ("Scheduled jobs", "Scheduler jobs (the Scheduler screen edits the same data).",
                       "Press Reload Schedulers on the Scheduler screen to apply schedule changes."),
    "session_summary_presets": ("Session summary presets", "Templates offered for the Session Summary.",
                                "Used from the next selection."),
    "services": ("Services", "Per-SERVICE_ID front-end endpoints for scheduled-job delivery.",
                 "Used from the next job run."),
}

# Masters whose entries sit one level down (prompt_templates holds ~70 KB
# under two keys, so editing a top-level entry would mean the whole file).
ENTRY_DEPTH = {"prompt_templates": 2}


def names() -> List[str]:
    return [n for n in dmms.MASTERS if n in MASTER_INFO] + [n for n in dmms.MASTERS if n not in MASTER_INFO]


def info(name: str) -> Tuple[str, str, str]:
    return MASTER_INFO.get(name, (name, "", ""))


def backend(name: str) -> str:
    if name == "users":
        import DigiM_Auth as dmam
        if getattr(dmam, "_legacy_rdb", lambda: False)():
            return "PostgreSQL table digim_users (LOGIN_AUTH_METHOD=RDB)"
    if dmms.method() == "PostgreSQL":
        return f"PostgreSQL digim_mst (name = '{name}')"
    sample = "" if os.path.exists(dmms.path(name)) else " (not created yet: showing the sample)"
    return dmms.path(name) + sample


def _empty(name: str):
    return [] if name == "scheduled_jobs" else {}


def load(name: str):
    if name == "users":
        import DigiM_Auth as dmam
        return dmam.load_user_master() or {}
    data = dmms.load(name, _empty(name))
    return data if data is not None else _empty(name)


def digest(data) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def masked(name: str, data):
    """Copy for display: a password hash is not something an editor needs to
    see, and it would sit in the browser for as long as the page is open."""
    data = json.loads(json.dumps(data))
    if name == "users" and isinstance(data, dict):
        for u in data.values():
            if isinstance(u, dict) and u.get("PW"):
                u["PW"] = PW_MASK
    return data


def _unmask(name: str, new, old):
    """Put back the passwords the editor left masked; hash any it typed."""
    if name != "users" or not isinstance(new, dict):
        return new, []
    errors = []
    for uid, u in new.items():
        if not isinstance(u, dict):
            continue
        pw = u.get("PW")
        prev = (old.get(uid) or {}).get("PW") if isinstance(old, dict) else None
        if pw == PW_MASK:
            if prev:
                u["PW"] = prev
            else:
                errors.append(f"users.{uid}: new user needs a password (PW)")
        elif isinstance(pw, str) and pw and not pw.startswith(("$2a$", "$2b$", "$2y$")):
            u["PW"] = dmu.hash_password(pw)
        elif not pw:
            errors.append(f"users.{uid}: PW is empty")
    return new, errors


# ------------------------------------------------------------- entries --
def entries(name: str, data) -> List[Tuple[Tuple, str]]:
    """[(path, label)] of the editable units of a master."""
    out = []
    if isinstance(data, list):
        for i, v in enumerate(data):
            lbl = (v.get("name") or v.get("job_id")) if isinstance(v, dict) else ""
            out.append(((i,), f"#{i + 1} {lbl or ''}".strip()))
        return out
    if not isinstance(data, dict):
        return out
    if ENTRY_DEPTH.get(name, 1) == 2:
        for k, v in data.items():
            if isinstance(v, dict):
                out += [((k, k2), f"{k} / {k2}") for k2 in v]
            else:
                out.append(((k,), str(k)))
        return out
    return [((k,), str(k)) for k in data]


def get_at(data, path):
    for p in path:
        data = data[p]
    return data


def set_at(data, path, value):
    data = json.loads(json.dumps(data))
    cur = data
    for p in path[:-1]:
        cur = cur[p]
    if isinstance(cur, list) and path[-1] == len(cur):
        cur.append(value)
    else:
        cur[path[-1]] = value
    return data


def delete_at(data, path):
    data = json.loads(json.dumps(data))
    cur = data
    for p in path[:-1]:
        cur = cur[p]
    del cur[path[-1]]
    return data


# ---------------------------------------------------------- validation --
def validate(name: str, data) -> Tuple[List[str], List[str]]:
    errors, warns = [], []
    want = list if name == "scheduled_jobs" else dict
    if not isinstance(data, want):
        return [f"{name} must be a JSON {'array' if want is list else 'object'}"], []

    if name == "users":
        for uid, u in data.items():
            if not isinstance(u, dict):
                errors.append(f"{uid}: must be an object"); continue
            if not isinstance(u.get("Allowed", {}), dict):
                errors.append(f"{uid}.Allowed: must be an object")
            if not isinstance(u.get("Group", []), (list, str)):
                errors.append(f"{uid}.Group: must be a list or a string")
    elif name == "prompt_templates":
        # Readers look up PROMPT_TEMPLATE.<name>; a template put at the top
        # level is silently never found.
        if not isinstance(data.get("PROMPT_TEMPLATE"), dict):
            errors.append("PROMPT_TEMPLATE must be an object of {name: text}")
        for k, v in data.items():
            if k not in ("PROMPT_TEMPLATE", "SPEAKING_STYLE"):
                warns.append(f"top-level key {k!r} is not read (templates go under PROMPT_TEMPLATE)")
            elif isinstance(v, dict):
                errors += [f"{k}.{k2}: must be text" for k2, t in v.items() if not isinstance(t, str)]
    elif name == "rags":
        for k, v in data.items():
            if not isinstance(v, dict):
                errors.append(f"{k}: must be an object")
            elif str(v.get("active", "Y")) not in ("Y", "N"):
                warns.append(f"{k}.active is {v.get('active')!r} (Update RAG builds only \"Y\")")
    elif name == "scheduled_jobs":
        import DigiM_ScheduledJobs as dmsj
        seen = set()
        for i, j in enumerate(data):
            if not isinstance(j, dict):
                errors.append(f"#{i + 1}: must be an object"); continue
            jid = j.get("job_id")
            if not jid:
                errors.append(f"#{i + 1}: job_id is empty")
            elif jid in seen:
                errors.append(f"#{i + 1}: duplicate job_id {jid!r}")
            seen.add(jid)
            if j.get("kind") and j["kind"] not in dmsj.VALID_KINDS:
                errors.append(f"{jid}: unknown kind {j['kind']!r}")
    elif name == "services":
        for k, v in data.items():
            if not isinstance(v, dict):
                errors.append(f"{k}: must be an object"); continue
            p = v.get("PUSH") or {}
            if not isinstance(p, dict):
                errors.append(f"{k}.PUSH: must be an object"); continue
            # The master is plain JSON or a DB row anyone with access can read.
            for secret in ("TOKEN", "PASSWORD", "SECRET", "API_KEY"):
                if secret in p:
                    errors.append(f"{k}.PUSH.{secret}: put the value in system.env and name it in TOKEN_ENV")
            for key, lo in (("BATCH_SIZE", 1), ("INTERVAL_SEC", 0), ("TIMEOUT_SEC", 0)):
                if key in p:
                    try:
                        if float(p[key]) < lo:
                            errors.append(f"{k}.PUSH.{key}: must be >= {lo}")
                    except (TypeError, ValueError):
                        errors.append(f"{k}.PUSH.{key}: must be a number")
            if v.get("ACTIVE") and not str(p.get("URL") or "").strip():
                warns.append(f"{k}: ACTIVE but PUSH.URL is empty (nothing will be sent)")
            if v.get("ACTIVE") and p.get("TOKEN_ENV") and not os.getenv(p["TOKEN_ENV"]):
                warns.append(f"{k}: {p['TOKEN_ENV']} is not set in system.env (sent without Authorization)")
    elif name == "session_summary_presets":
        for k, v in data.items():
            if not isinstance(v, dict) or not isinstance(v.get("template", ""), str):
                errors.append(f"{k}: must be {{\"description\", \"template\"}}")
    return errors, warns


# ---------------------------------------------------------------- save --
class Conflict(Exception):
    pass


def _indent(name: str) -> int:
    # Keep each file the way it is written now, so a save does not turn into
    # a whole-file re-indent in the diff.
    try:
        with open(dmms.path(name), encoding="utf-8") as f:
            for line in f:
                if line.startswith(" "):
                    return len(line) - len(line.lstrip(" "))
    except OSError:
        pass
    return 4


def _backup_dir(name: str) -> str:
    setting = dmu.read_yaml_file("setting.yaml") or {}
    return os.path.join(setting.get("MST_FOLDER", "user/common/mst/"), "_backup", name)


def backups(name: str) -> List[str]:
    d = _backup_dir(name)
    if not os.path.isdir(d):
        return []
    return sorted((os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")), reverse=True)


def read_backup(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_backup(name: str, data, actor: str) -> str:
    d = _backup_dir(name)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{datetime.now():%Y%m%d_%H%M%S}_{actor or 'unknown'}.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=4, ensure_ascii=False) + "\n")
    for old in backups(name)[BACKUP_KEEP:]:
        try:
            os.remove(old)
        except OSError:
            pass
    return path


def save(name: str, new_data, base_digest: str, actor: str = "") -> Dict[str, Any]:
    """Validate, check nobody changed the master since `base_digest`, back up
    the current document, then write. Raises Conflict / ValueError."""
    current = load(name)
    if base_digest and digest(current) != base_digest:
        raise Conflict(f"{name} was changed after you opened it. Reload and apply your edit again.")
    new_data, pw_errors = _unmask(name, json.loads(json.dumps(new_data)), current)
    errors, warns = validate(name, new_data)
    if pw_errors or errors:
        raise ValueError("; ".join(pw_errors + errors))
    backup = _write_backup(name, current, actor)
    if name == "users":
        import DigiM_Auth as dmam
        dmam.save_user_master(new_data)
    else:
        dmms.save(name, new_data, indent=_indent(name))
    return {"backup": backup, "warnings": warns, "digest": digest(load(name))}
