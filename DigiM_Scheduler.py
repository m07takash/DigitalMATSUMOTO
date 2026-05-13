"""バックグラウンドスケジューラ（マスタJSON駆動 / 複数ジョブ対応）。

ジョブ定義は user/common/mst/scheduled_jobs.json から読込:
  kind="rag_update"          : RAGデータ再ベクトル化(dmc.generate_rag)
  kind="user_memory_nowaday" : Nowaday→Persona の自動更新バッチ
  kind="agent_run"           : エージェント実行(DigiMatsuExecute_Practice)

cronの書式: "off" | "daily"(03:00) | "weekly"(月曜03:00) | "monthly"(1日03:00) | 5フィールドcron
"off" / enabled=False のジョブは登録されない。

APScheduler 未インストール環境では起動をスキップする（手動 run_now() は引き続き可能）。
"""
import logging
import os
import threading
from datetime import datetime

from dotenv import load_dotenv

import DigiM_ScheduledJobs as dmsj

logger = logging.getLogger(__name__)

if os.path.exists("system.env"):
    load_dotenv("system.env")

_PRESETS = {
    "monthly": "0 3 1 * *",
    "weekly":  "0 3 * * 1",
    "daily":   "0 3 * * *",
}

_scheduler = None
_scheduler_lock = threading.Lock()
_active = {}  # job_id -> cron expr


# ====== 設定読込 ======

def _normalize_expr(raw) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s or s.lower() == "off":
        return ""
    return _PRESETS.get(s.lower(), s)


# ====== ジョブ実装 ======

def _run_job(job: dict):
    """登録ジョブをkindごとにディスパッチ。実行結果をマスタに書き戻す。"""
    job_id = job.get("job_id", "")
    kind = job.get("kind", "")
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    dmsj.update_run_result(job_id, status="running", started_at=started_at)
    logger.info(f"[scheduler] run start job_id={job_id} kind={kind}")
    try:
        if kind == "rag_update":
            _exec_rag_update(job)
            dmsj.update_run_result(job_id, status="success", started_at=started_at)
        elif kind == "user_memory_nowaday":
            _exec_user_memory_nowaday(job)
            dmsj.update_run_result(job_id, status="success", started_at=started_at)
        elif kind == "agent_run":
            session_id = _exec_agent_run(job)
            dmsj.update_run_result(job_id, status="success", session_id=session_id, started_at=started_at)
        else:
            raise ValueError(f"unknown kind: {kind}")
        logger.info(f"[scheduler] run success job_id={job_id}")
    except Exception as e:
        logger.exception(f"[scheduler] run error job_id={job_id}: {e}")
        dmsj.update_run_result(job_id, status="error", error=str(e), started_at=started_at)


def _exec_rag_update(job: dict):
    import DigiM_Context as dmc
    dmc.generate_rag()
    if (os.getenv("USER_MEMORY_HISTORY_AUTO_SAVE_FLG") or "N") == "Y":
        try:
            import DigiM_GeneUserMemory as _g
            _g.save_history_for_unsaved_sessions()
        except Exception as e:
            logger.error(f"[scheduler] history auto save failed: {e}")


def _exec_user_memory_nowaday(job: dict):
    import DigiM_GeneUserMemory as g
    period = datetime.now().strftime("%Y-%m")
    result = g.build_nowaday_for_all_users(period)
    for sid, uid in result.get("done", []):
        try:
            g.merge_persona(sid, uid)
        except Exception as e:
            logger.error(f"[scheduler] persona merge failed user={uid}: {e}")


def _exec_agent_run(job: dict) -> str:
    """エージェントを実行し、発番したセッションIDを返す。所有者ユーザーで実行。"""
    import DigiM_Execute as dme
    import DigiM_Session as dms

    params = job.get("params") or {}
    agent_file = params.get("agent_file")
    user_input = params.get("user_input", "")
    engine = params.get("engine") or ""
    execution = params.get("execution") or {}
    owner = job.get("owner_user_id") or "Scheduler"

    if not agent_file:
        raise ValueError("agent_run requires params.agent_file")

    service_info = {"SERVICE_ID": "Scheduler", "SERVICE_DATA": {"job_id": job.get("job_id", "")}}
    user_info = {"USER_ID": owner, "USER_DATA": {}}

    session_id = "SCH" + dms.set_new_session_id()
    session_name = f"[Scheduler] {job.get('name') or job.get('job_id')}"

    # エンジン切り替え（任意）
    overwrite_items = {}
    if engine:
        try:
            import DigiM_Util as _dmu
            setting = _dmu.read_yaml_file("setting.yaml") or {}
            agent_folder = setting.get("AGENT_FOLDER", "user/common/agent/")
            agent_data = _dmu.read_json_file(agent_file, agent_folder)
            engines_map = (agent_data.get("ENGINE") or {}).get("LLM") or {}
            if engine in engines_map:
                overwrite_items["ENGINE"] = {"LLM": engines_map[engine]}
        except Exception as e:
            logger.warning(f"[scheduler] engine override skipped: {e}")

    exec_dict = {
        "STREAM_MODE": False,
        "SAVE_DIGEST": True,
        "LAST_ONLY": True,
    }
    exec_dict.update(execution or {})

    # ジェネレータを最後まで消費（応答内容はチャット履歴に保存される）
    for _ in dme.DigiMatsuExecute_Practice(
        service_info, user_info, session_id, session_name, agent_file, user_input,
        in_overwrite_items=overwrite_items, in_execution=exec_dict,
    ):
        pass

    return session_id


# ====== APScheduler 制御 ======

def _build_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception as e:
        logger.warning(f"[scheduler] APScheduler未インストールのため起動スキップ: {e}")
        return None
    return BackgroundScheduler(timezone=os.getenv("TIMEZONE") or "Asia/Tokyo")


def _start_all_locked() -> dict:
    global _scheduler, _active
    jobs = dmsj.load_all()
    targets = []  # (job, expr)
    for j in jobs:
        if not j.get("enabled"):
            continue
        expr = _normalize_expr(j.get("cron"))
        if not expr:
            continue
        targets.append((j, expr))

    if not targets:
        logger.info("[scheduler] no active jobs in master")
        _active = {}
        return {"started": [], "skipped": [j.get("job_id") for j in jobs]}

    if _scheduler is None:
        _scheduler = _build_scheduler()
        if _scheduler is None:
            return {"started": [], "error": "APScheduler not installed"}

    try:
        from apscheduler.triggers.cron import CronTrigger
    except Exception as e:
        return {"started": [], "error": str(e)}

    started = []
    errors = {}
    for j, expr in targets:
        job_id = j.get("job_id")
        try:
            trigger = CronTrigger.from_crontab(expr)
        except Exception as e:
            errors[job_id] = f"invalid cron: {expr}"
            logger.warning(f"[scheduler] cron式不正 job_id={job_id} cron={expr}: {e}")
            continue

        def _make_fn(job_def):
            def _fn():
                _run_job(job_def)
            return _fn

        _scheduler.add_job(_make_fn(j), trigger=trigger, id=job_id, replace_existing=True)
        _active[job_id] = expr
        started.append(job_id)
        logger.info(f"[scheduler] job added job_id={job_id} cron='{expr}'")

    if not getattr(_scheduler, "running", False):
        try:
            _scheduler.start()
        except Exception as e:
            logger.error(f"[scheduler] start failed: {e}")
            return {"started": started, "errors": errors, "fatal": str(e)}

    return {"started": started, "errors": errors}


def _stop_all_locked():
    global _scheduler, _active
    if _scheduler is not None and getattr(_scheduler, "running", False):
        try:
            _scheduler.shutdown(wait=False)
        except Exception as e:
            logger.error(f"[scheduler] shutdown failed: {e}")
    _scheduler = None
    _active = {}


def start_all() -> dict:
    with _scheduler_lock:
        return _start_all_locked()


def stop_all():
    with _scheduler_lock:
        _stop_all_locked()


def reload() -> dict:
    with _scheduler_lock:
        _stop_all_locked()
        return _start_all_locked()


def run_now(job_id: str) -> dict:
    """指定ジョブを即時1回実行(同期)。WebUIの"Run Now"用。"""
    j = dmsj.get(job_id)
    if not j:
        return {"ok": False, "error": "job not found"}
    try:
        _run_job(j)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_status() -> dict:
    """現在のスケジューラ状態。"""
    jobs = dmsj.load_all()
    running = bool(_scheduler is not None and getattr(_scheduler, "running", False))
    return {
        "running": running,
        "active_job_ids": list(_active.keys()),
        "jobs": jobs,
    }


# ====== 後方互換 ======

def start() -> bool:
    """旧API互換。"""
    res = start_all()
    return bool(res.get("started"))


def stop():
    stop_all()
