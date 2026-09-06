"""Background scheduler (master-JSON driven, multi-job support).

Job definitions are loaded from user/common/mst/scheduled_jobs.json:
  kind="rag_update"          : Re-vectorize RAG data (dmc.generate_rag)
  kind="user_memory_nowaday" : Batch that updates Nowaday -> Persona
  kind="agent_run"           : Run an agent (DigiMatsuExecute_Practice)

cron format: "off" | "daily" (03:00) | "weekly" (Mon 03:00) | "monthly" (1st 03:00) | 5-field cron
Jobs with "off" / enabled=False are not registered.

When APScheduler is not installed, startup is skipped (run_now() still works).
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

# Per-session message generation costs one LLM call per target, so a job that
# matches a wide filter can get expensive fast. Refuse above this unless the
# job raises it explicitly.
PUSH_MAX_GENERATED_SESSIONS = 20

_scheduler = None
_scheduler_lock = threading.Lock()
_active = {}  # job_id -> cron expr


# ====== Settings loading ======

def _normalize_expr(raw) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s or s.lower() == "off":
        return ""
    return _PRESETS.get(s.lower(), s)


# ====== Job implementations ======

def _run_job(job: dict):
    """Dispatch a registered job by kind and write the result back to the master."""
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
        elif kind == "agent_push":
            session_id = _exec_agent_push(job)
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
    """Run the agent and return the newly issued session ID. Runs as the owner user."""
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

    # Engine override (optional)
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

    # Drain the generator (response content is persisted to the chat history)
    for _ in dme.DigiMatsuExecute_Practice(
        service_info, user_info, session_id, session_name, agent_file, user_input,
        in_overwrite_items=overwrite_items, in_execution=exec_dict,
    ):
        pass

    return session_id


def _push_resolve_targets(job: dict) -> list:
    """Session IDs an agent_push job should post into.

    Modes:
      active_all — every active session, narrowed by `filter`
      selected   — the explicit `session_ids` list (active ones only)
      new        — create `new_count` fresh sessions and post into those

    Targets are expressed as a filter rather than a stored group so that
    sessions created after the job was registered are picked up automatically.
    """
    import DigiM_Session as dms

    params = job.get("params") or {}
    target = params.get("target") or {}
    mode = (target.get("mode") or "active_all").lower()
    owner = job.get("owner_user_id") or "Scheduler"

    if mode == "new":
        count = max(1, int(target.get("new_count") or 1))
        return ["SCH" + dms.set_new_session_id() for _ in range(count)]

    sessions = [s for s in dms.get_session_list() if s.get("active") == "Y"]

    if mode == "selected":
        wanted = set(target.get("session_ids") or [])
        return [s["id"] for s in sessions if s["id"] in wanted]

    _f = target.get("filter") or {}
    out = []
    for s in sessions:
        if _f.get("agent_file") and s.get("agent") != _f["agent_file"]:
            continue
        if _f.get("user_id") and s.get("user_id") != _f["user_id"]:
            continue
        if _f.get("service_id") and s.get("service_id") != _f["service_id"]:
            continue
        out.append(s["id"])
    return out


def _push_generate_message(job: dict, session_id: str = "") -> str:
    """Ask the agent to compose the push text. With `session_id` the agent
    sees that conversation's memory, so the message can react to it; without,
    it composes once for everyone."""
    import DigiM_Execute as dme
    import DigiM_Session as dms

    params = job.get("params") or {}
    message = params.get("message") or {}
    agent_file = params.get("agent_file")
    owner = job.get("owner_user_id") or "Scheduler"
    prompt = message.get("prompt") or ""

    service_info = {"SERVICE_ID": "Scheduler", "SERVICE_DATA": {"job_id": job.get("job_id", "")}}
    user_info = {"USER_ID": owner, "USER_DATA": {}}

    gen_session_id = session_id or ("SCH" + dms.set_new_session_id())
    exec_dict = {
        "STREAM_MODE": False,
        # Composing the text must never mutate the target conversation; the
        # message is written separately once every target is known.
        "MEMORY_SAVE": False,
        "CONTENTS_SAVE": False,
        "SAVE_DIGEST": False,
        "LAST_ONLY": True,
    }
    exec_dict.update(params.get("execution") or {})
    exec_dict["MEMORY_SAVE"] = False
    exec_dict["SAVE_DIGEST"] = False

    text = ""
    for _svc, _usr, chunk, _exp, _ref in dme.DigiMatsuExecute_Practice(
            service_info, user_info, gen_session_id,
            f"[Push] {job.get('name') or job.get('job_id')}",
            agent_file, prompt, in_execution=exec_dict):
        if chunk and not str(chunk).startswith("[STATUS]"):
            text += chunk
    return text.strip()


def _exec_agent_push(job: dict) -> str:
    """Post a scheduled agent message into the target sessions.

    Returns the first target session id (recorded as last_session_id) and
    stores the full per-session outcome on the job so the UI can show it.
    """
    import DigiM_Session as dms

    params = job.get("params") or {}
    message = params.get("message") or {}
    msg_mode = (message.get("mode") or "fixed").lower()
    agent_file = params.get("agent_file") or ""
    save_to_memory = params.get("save_to_memory", True)
    owner = job.get("owner_user_id") or "Scheduler"
    job_name = job.get("name") or job.get("job_id")

    if not agent_file:
        raise ValueError("agent_push requires params.agent_file")

    targets = _push_resolve_targets(job)
    if not targets:
        raise ValueError("agent_push matched no target session")

    max_gen = int(params.get("max_generated_sessions") or PUSH_MAX_GENERATED_SESSIONS)
    if msg_mode == "generated_per_session" and len(targets) > max_gen:
        raise ValueError(
            f"generated_per_session would call the LLM {len(targets)} times "
            f"(limit {max_gen}); narrow the target or raise max_generated_sessions")

    shared_text = ""
    if msg_mode == "fixed":
        shared_text = message.get("text") or ""
        if not shared_text:
            raise ValueError("agent_push message.mode=fixed requires message.text")
    elif msg_mode == "generated_shared":
        shared_text = _push_generate_message(job)

    delivered, failed = [], []
    for sid in targets:
        try:
            text = (_push_generate_message(job, sid)
                    if msg_mode == "generated_per_session" else shared_text)
            if not text:
                raise ValueError("empty message")
            session = dms.DigiMSession(sid)
            session.save_push_message(
                text, agent_file=agent_file, job_id=job.get("job_id", ""),
                job_name=job_name, owner_user_id=owner,
                save_to_memory=bool(save_to_memory))
            delivered.append(sid)
        except Exception as e:
            logger.error(f"[scheduler] push failed session={sid}: {e}")
            failed.append({"session_id": sid, "error": str(e)})

    try:
        _j = dmsj.get(job.get("job_id", "")) or dict(job)
        _j["last_push"] = {
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "targets": len(targets), "delivered": delivered, "failed": failed,
        }
        dmsj.upsert(_j)
    except Exception as e:
        logger.warning(f"[scheduler] could not record push result: {e}")

    if not delivered:
        raise RuntimeError(f"agent_push delivered to no session ({len(failed)} failed)")
    return delivered[0]


# ====== APScheduler control ======

def _build_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception as e:
        logger.warning(f"[scheduler] APScheduler is not installed; startup skipped: {e}")
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
            logger.warning(f"[scheduler] invalid cron job_id={job_id} cron={expr}: {e}")
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
    """Run the specified job once immediately (synchronously). Used by the WebUI "Run Now" button."""
    j = dmsj.get(job_id)
    if not j:
        return {"ok": False, "error": "job not found"}
    try:
        _run_job(j)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_status() -> dict:
    """Current scheduler state."""
    jobs = dmsj.load_all()
    running = bool(_scheduler is not None and getattr(_scheduler, "running", False))
    return {
        "running": running,
        "active_job_ids": list(_active.keys()),
        "jobs": jobs,
    }


# ====== Backward compatibility ======

def start() -> bool:
    """Legacy API compatibility."""
    res = start_all()
    return bool(res.get("started"))


def stop():
    stop_all()
