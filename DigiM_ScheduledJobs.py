"""スケジュールジョブのマスタCRUD。

マスタ実体: user/common/mst/scheduled_jobs.json （配列）
1ジョブのフィールド:
  job_id          : 文字列。一意。空ならcreate()で自動採番。
  name            : 表示名
  kind            : "rag_update" | "user_memory_nowaday" | "agent_run"
  cron            : "off" | "daily" | "weekly" | "monthly" | 5フィールドcron
  enabled         : bool
  owner_user_id   : 作成/最終編集ユーザー(セッションに紐付け / 監査用)
  params          : kind毎の追加パラメータ(主にagent_run用)
                    agent_run: {agent_file, user_input, engine?, execution{...}}
  last_run        : "YYYY-MM-DD HH:MM:SS" (UTC+TIMEZONE)
  last_status     : "success" | "error" | "running" | "" (未実行)
  last_error      : 直近エラーメッセージ
  last_session_id : agent_run のみ、最新の発番セッションID
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

VALID_KINDS = ("rag_update", "user_memory_nowaday", "agent_run")


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
        "enabled": False,
        "owner_user_id": "",
        "params": {},
        "last_run": "",
        "last_status": "",
        "last_error": "",
        "last_session_id": "",
        "created_at": _now_str(),
        "updated_at": _now_str(),
    }


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
    # フィールド補完(後方互換)
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
    """job_id が空ならcreate、既存ならupdate。"""
    if job.get("kind") not in VALID_KINDS:
        raise ValueError(f"invalid kind: {job.get('kind')}")
    with _LOCK:
        jobs = load_all()
        if not job.get("job_id"):
            new_job = _empty_job()
            new_job.update(job)
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
        # 指定job_idが無い → 新規登録扱い
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


def update_run_result(job_id: str, status: str, error: str = "",
                      session_id: str = "", started_at: str = ""):
    """実行結果を該当ジョブに書き込む。startedとendedの両方を扱える。
    status="running" のとき started_at を last_run に書く(未完了表示用)。
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
