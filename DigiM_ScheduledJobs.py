"""CRUD for the scheduled-job master.

Master file: user/common/mst/scheduled_jobs.json (array)
Fields per job:
  job_id          : String. Unique. If empty, create() assigns one automatically.
  name            : Display name
  kind            : "rag_update" | "user_memory_nowaday" | "agent_run"
  cron            : "off" | "daily" | "weekly" | "monthly" | a 5-field cron string
  enabled         : bool
  owner_user_id   : Creator / last-editor user (linked to the session, for audit)
  params          : Extra parameters per kind (mainly for agent_run)
                    agent_run: {agent_file, user_input, engine?, execution{...}}
  last_run        : "YYYY-MM-DD HH:MM:SS" (UTC + TIMEZONE)
  last_status     : "success" | "error" | "running" | "" (not yet run)
  last_error      : Latest error message
  last_session_id : agent_run only; the most recently issued session ID
  created_at, updated_at
"""
import json
import os
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

import DigiM_Util as dmu

if os.path.exists("system.env"):
    load_dotenv("system.env")

_LOCK = threading.Lock()
_FILE_NAME = "scheduled_jobs.json"

VALID_KINDS = ("rag_update", "user_memory_nowaday", "agent_run", "agent_push")


def _mst_path() -> str:
    setting = dmu.read_yaml_file("setting.yaml") or {}
    mst_folder = setting.get("MST_FOLDER", "user/common/mst/")
    return os.path.join(mst_folder, _FILE_NAME)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _empty_job(job_id: str = "") -> Dict[str, Any]:
    return {
        "job_id": job_id or f"job_{uuid.uuid4().hex[:10]}",
        "name": "",
        "kind": "rag_update",
        "cron": "off",
        # Empty means the scheduler-wide TIMEZONE; set per job to schedule in
        # a different zone without moving everything else.
        "timezone": "",
        "enabled": False,
        "owner_user_id": "",
        "params": {},
        # Serial workflow: [{"id", "kind", "params"}], run top to bottom.
        # Empty means the legacy shape (pre_steps + kind/params); see job_steps.
        "steps": [],
        "pre_steps": [],
        "last_run": "",
        "last_status": "",
        "last_error": "",
        "last_session_id": "",
        "last_steps": [],
        "created_at": _now_str(),
        "updated_at": _now_str(),
    }


# Legacy pre_steps could only hold kinds that need no params.
_PARAMLESS_KINDS = ("rag_update", "user_memory_nowaday")


def new_step(kind: str = "agent_run") -> Dict[str, Any]:
    return {"id": f"st_{uuid.uuid4().hex[:8]}", "kind": kind, "params": {}}


def job_steps(job: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The job as its ordered list of steps.

    Jobs saved before workflows have no `steps`; they are their pre_steps
    followed by the job's own kind + params, so they keep running unchanged.
    """
    raw = [st for st in (job.get("steps") or []) if isinstance(st, dict) and st.get("kind")]
    if not raw:
        raw = [{"kind": st["kind"]} for st in (job.get("pre_steps") or [])
               if isinstance(st, dict) and st.get("kind") in _PARAMLESS_KINDS]
        raw.append({"kind": job.get("kind") or "rag_update", "params": job.get("params") or {}})
    out = []
    for st in raw:
        step = new_step("agent_run" if st.get("kind") == "agent_push" else st.get("kind"))
        step["id"] = st.get("id") or step["id"]
        step["params"] = dict(st.get("params") or {})
        out.append(step)
    return out


def load_all() -> List[Dict[str, Any]]:
    path = _mst_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    # Fill in missing fields for backward compatibility
    out = []
    for job in data:
        if not isinstance(job, dict):
            continue
        base = _empty_job(job.get("job_id", ""))
        base.update(job)
        out.append(base)
    return out


def save_all(jobs: List[Dict[str, Any]]):
    path = _mst_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get(job_id: str) -> Optional[Dict[str, Any]]:
    for job in load_all():
        if job.get("job_id") == job_id:
            return job
    return None


def upsert(job: Dict[str, Any]) -> Dict[str, Any]:
    """Create if job_id is empty, update if it exists."""
    # agent_push was folded into agent_run (same execution, the old split was
    # only target + delivery); normalize on write so the UI shows one kind.
    if job.get("kind") == "agent_push":
        job = dict(job); job["kind"] = "agent_run"
    if job.get("steps"):
        # kind/params mirror the last step, so readers that predate workflows
        # (and the check below) still see a real kind.
        job = dict(job)
        job["steps"] = job_steps(job)
        for _st in job["steps"]:
            if _st["kind"] not in VALID_KINDS:
                raise ValueError(f"invalid step kind: {_st['kind']}")
        job["kind"], job["params"] = job["steps"][-1]["kind"], job["steps"][-1]["params"]
    if job.get("kind") not in VALID_KINDS:
        raise ValueError(f"invalid kind: {job.get('kind')}")
    with _LOCK:
        jobs = load_all()
        if not job.get("job_id"):
            new_job = _empty_job()
            _generated_id = new_job["job_id"]
            new_job.update(job)
            # The caller sends job_id="" to mean "new", and that empty value
            # would otherwise overwrite the id just generated — leaving every
            # new job with an empty id, colliding with each other.
            new_job["job_id"] = _generated_id
            new_job["created_at"] = _now_str()
            new_job["updated_at"] = _now_str()
            jobs.append(new_job)
            save_all(jobs)
            return new_job
        for i, existing in enumerate(jobs):
            if existing.get("job_id") == job["job_id"]:
                merged = dict(existing)
                merged.update(job)
                merged["updated_at"] = _now_str()
                jobs[i] = merged
                save_all(jobs)
                return merged
        # No job with the specified job_id -> treat as a new registration
        new_job = _empty_job(job["job_id"])
        new_job.update(job)
        jobs.append(new_job)
        save_all(jobs)
        return new_job


def delete(job_id: str) -> bool:
    with _LOCK:
        jobs = load_all()
        new_jobs = [j for j in jobs if j.get("job_id") != job_id]
        if len(new_jobs) == len(jobs):
            return False
        save_all(new_jobs)
        return True


def update_steps(job_id: str, steps: List[Dict[str, Any]]):
    """Record per-step progress of the current / last run."""
    with _LOCK:
        jobs = load_all()
        for i, job in enumerate(jobs):
            if job.get("job_id") != job_id:
                continue
            job["last_steps"] = steps
            job["updated_at"] = _now_str()
            jobs[i] = job
            save_all(jobs)
            return


def update_run_result(job_id: str, status: str, error: str = "",
                      session_id: str = "", started_at: str = ""):
    """Write the execution result into the matching job.
    Handles both "started" and "ended" states.
    When status="running", write started_at into last_run (to display in-progress state).
    """
    with _LOCK:
        jobs = load_all()
        for i, job in enumerate(jobs):
            if job.get("job_id") != job_id:
                continue
            job["last_status"] = status
            job["last_run"] = started_at or _now_str()
            job["last_error"] = error or ""
            if session_id:
                job["last_session_id"] = session_id
            job["updated_at"] = _now_str()
            jobs[i] = job
            save_all(jobs)
            return
