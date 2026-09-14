"""Background scheduler (master-JSON driven, multi-job support).

Job definitions are loaded from user/common/mst/scheduled_jobs.json:
  kind="rag_update"          : Re-vectorize RAG data (dmc.generate_rag)
  kind="user_memory_nowaday" : Batch that updates Nowaday -> Persona
  kind="agent_run"           : Run an agent (DigiMatsuExecute_Practice)

steps ([{"kind", "params"}]) make a job a serial workflow: steps run top to
bottom, each with its own params; a failed step stops the job and marks the
rest skipped (see last_steps). Jobs without steps run as their legacy
pre_steps followed by the job's own kind (DigiM_ScheduledJobs.job_steps).

cron format: "off" | "daily" (03:00) | "weekly" (Mon 03:00) | "monthly" (1st 03:00) | 5-field cron
Jobs with "off" / enabled=False are not registered.

When APScheduler is not installed, startup is skipped (run_now() still works).
"""
import logging
import os
import threading
import time
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

# Step kinds offered by the workflow editor, in menu order.
STEP_KINDS = ("agent_run", "rag_update", "user_memory_nowaday")

_scheduler = None
_scheduler_lock = threading.Lock()
_active = {}  # job_id -> cron expr


# ====== Settings loading ======

# A one-shot schedule is stored as "once:YYYY-MM-DD HH:MM" rather than a cron
# string, because cron cannot express a year and would otherwise re-fire every
# year on the same day.
_ONCE_PREFIX = "once:"


def webui_service_id() -> str:
    """SERVICE_ID the WebUI filters its session list on.

    A scheduler-created session stamped "Scheduler" is invisible there, since
    the list requires service_id AND user_id to match the logged-in context.
    """
    import json as _json
    raw = os.getenv("WEB_DEFAULT_SERVICE") or ""
    try:
        return (_json.loads(raw) or {}).get("SERVICE_ID") or "Streamlit"
    except Exception:
        return "Streamlit"


def system_timezone() -> str:
    """The scheduler-wide default, used when a job does not name its own."""
    return os.getenv("TIMEZONE") or "Asia/Tokyo"


def resolve_timezone(name: str = ""):
    """tzinfo for a job. Falls back to the system default, then UTC, so a
    typo in a saved job cannot stop the whole scheduler from starting."""
    import pytz
    for candidate in (name, system_timezone()):
        if not candidate:
            continue
        try:
            return pytz.timezone(candidate)
        except Exception:
            logger.warning(f"[scheduler] unknown timezone {candidate!r}; falling back")
    return pytz.utc


def _parse_once(raw):
    """datetime for a one-shot schedule, or None when `raw` is not one."""
    s = str(raw or "").strip()
    if not s.lower().startswith(_ONCE_PREFIX):
        return None
    stamp = s[len(_ONCE_PREFIX):].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def _normalize_expr(raw) -> str:
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s or s.lower() == "off":
        return ""
    if s.lower().startswith(_ONCE_PREFIX):
        return s          # handled by a DateTrigger, not CronTrigger
    return _PRESETS.get(s.lower(), s)


def describe_schedule(raw, tz: str = "") -> str:
    """Human-readable rendering of a stored schedule, for the UI."""
    s = str(raw or "").strip()
    if not s or s.lower() == "off":
        return "disabled"
    _tz_sfx = f" [{tz or system_timezone()}]"
    once = _parse_once(s)
    if once:
        return f"once at {once.strftime('%Y-%m-%d %H:%M')}" + _tz_sfx
    expr = _PRESETS.get(s.lower(), s)
    labels = {"0 3 1 * *": "monthly, 1st at 03:00",
              "0 3 * * 1": "weekly, Monday at 03:00",
              "0 3 * * *": "daily at 03:00"}
    if expr in labels:
        return labels[expr] + _tz_sfx
    parts = expr.split()
    if len(parts) == 5:
        mi, ho, dom, mo, dow = parts
        if dom == "*" and mo == "*" and dow == "*" and mi.isdigit() and ho.isdigit():
            return f"daily at {int(ho):02d}:{int(mi):02d}" + _tz_sfx
        return f"cron: {expr}" + _tz_sfx
    return f"cron: {expr}" + _tz_sfx


# ====== Job implementations ======

def _run_job(job: dict):
    """Dispatch a registered job by kind and write the result back to the master."""
    job_id = job.get("job_id", "")
    # Stamp in the job's own zone. The container clock is often UTC while
    # schedules are written in local wall-clock time, and a last_run that
    # disagrees with the schedule by the UTC offset reads as "it ran at the
    # wrong time".
    _tz = resolve_timezone(job.get("timezone") or "")
    started_at = datetime.now(_tz).strftime("%Y-%m-%d %H:%M:%S")
    # A failed prep step stops the job: running the main step on data the step
    # was meant to refresh (a reflection over a stale RAG) would report success
    # while producing the wrong thing.
    steps = dmsj.job_steps(job)
    kinds = [st["kind"] for st in steps]
    step_log = [{"kind": k, "status": "pending"} for k in kinds]
    dmsj.update_run_result(job_id, status="running", started_at=started_at)
    dmsj.update_steps(job_id, step_log)
    logger.info(f"[scheduler] run start job_id={job_id} steps={kinds}")
    try:
        session_id = ""
        for i, k in enumerate(kinds):
            step_log[i].update(status="running", started_at=datetime.now(_tz).strftime("%Y-%m-%d %H:%M:%S"))
            dmsj.update_steps(job_id, step_log)
            _t0 = time.monotonic()
            try:
                # Each step reads its own params; id / name / timezone / owner
                # are shared by the whole job.
                session_id = _run_step(dict(job, kind=k, params=steps[i]["params"]), k) or session_id
            except Exception as e:
                step_log[i].update(status="error", seconds=round(time.monotonic() - _t0, 1), error=str(e))
                for _rest in step_log[i + 1:]:
                    _rest["status"] = "skipped"
                dmsj.update_steps(job_id, step_log)
                if len(kinds) == 1:
                    raise
                raise RuntimeError(f"step {i + 1}/{len(kinds)} ({k}) failed: {e}") from e
            step_log[i].update(status="success", seconds=round(time.monotonic() - _t0, 1))
            dmsj.update_steps(job_id, step_log)
        dmsj.update_run_result(job_id, status="success", session_id=session_id, started_at=started_at)
        logger.info(f"[scheduler] run success job_id={job_id}")
    except Exception as e:
        logger.exception(f"[scheduler] run error job_id={job_id}: {e}")
        dmsj.update_run_result(job_id, status="error", error=str(e), started_at=started_at)
    finally:
        # A one-shot has no next occurrence; leaving it enabled makes every
        # later reload report "already passed" as an error.
        if _parse_once(job.get("cron")) is not None:
            try:
                _j = dmsj.get(job_id)
                if _j and _j.get("enabled"):
                    _j["enabled"] = False
                    dmsj.upsert(_j)
                    logger.info(f"[scheduler] one-shot completed; disabled job_id={job_id}")
            except Exception as _e:
                logger.warning(f"[scheduler] could not disable one-shot {job_id}: {_e}")


def _scheduled_situation(job: dict, agent_file: str) -> dict:
    """The situation a WebUI "Real Date" turn would carry, in the job's zone.

    Without one the main agent gets no clock at all, and the support agents'
    fallback reads the container clock (usually UTC) — a 08:00 JST job would
    then treat the previous day as "today" in its web search and date filters.
    """
    try:
        import DigiM_Agent as _dma
        _defaults = _dma.get_agent_item(agent_file, "EXECUTION_DEFAULTS") or {}
    except Exception:
        _defaults = {}
    if _defaults.get("TIME_MODE") == "No Date":
        return {"TIME": "", "SITUATION": "", "TIME_MODE": "No Date"}
    now = datetime.now(resolve_timezone(job.get("timezone") or ""))
    return {"TIME": now.strftime("%Y/%m/%d %H:%M:%S"), "SITUATION": "", "TIME_MODE": "Real Date"}


def _run_step(job: dict, kind: str) -> str:
    """Returns the session a step touched, or "" for kinds that create none."""
    if kind == "rag_update":
        _exec_rag_update(job)
    elif kind == "user_memory_nowaday":
        _exec_user_memory_nowaday(job)
    elif kind == "agent_run":
        return _exec_agent_run(job)
    elif kind == "agent_push":
        return _exec_agent_push(job)
    else:
        raise ValueError(f"unknown kind: {kind}")
    return ""


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


def _agent_overwrite_items(agent_file: str, engine: str) -> dict:
    """ENGINE override for a named LLM entry in the agent JSON."""
    if not engine:
        return {}
    try:
        import DigiM_Util as _dmu
        setting = _dmu.read_yaml_file("setting.yaml") or {}
        agent_folder = setting.get("AGENT_FOLDER", "user/common/agent/")
        agent_data = _dmu.read_json_file(agent_file, agent_folder)
        engines_map = (agent_data.get("ENGINE") or {}).get("LLM") or {}
        if engine in engines_map:
            return {"ENGINE": {"LLM": engines_map[engine]}}
    except Exception as e:
        logger.warning(f"[scheduler] engine override skipped: {e}")
    return {}


def _exec_agent_run(job: dict) -> str:
    """Run an agent on a schedule and deliver the result.

    One job kind covers both shapes that used to be separate:
      target.mode = "new"                   -> the run creates its own session
                                               and the turn IS the conversation
      target.mode = "active_all"/"selected" -> the produced text is posted into
                                               those sessions as a PUSH turn
    message.mode = "fixed" skips the LLM and posts user_input as-is.
    Returns the first session touched (recorded as last_session_id).
    """
    import DigiM_Execute as dme
    import DigiM_Session as dms

    params = job.get("params") or {}
    agent_file = params.get("agent_file")
    if not agent_file:
        raise ValueError("agent_run requires params.agent_file")

    user_input = params.get("user_input", "")
    execution = params.get("execution") or {}
    owner = job.get("owner_user_id") or "Scheduler"
    job_name = job.get("name") or job.get("job_id")

    target = params.get("target") or {}
    mode = (target.get("mode") or "new").lower()
    msg_mode = ((params.get("message") or {}).get("mode") or "generated").lower()
    per_session = bool(params.get("per_session"))
    save_to_memory = params.get("save_to_memory", True)

    # The WebUI session list matches on service_id AND user_id (unless the
    # viewer is Admin), so a session stamped "Scheduler" is invisible to the
    # person it was created for. Use the id the WebUI actually filters on.
    service_info = {"SERVICE_ID": target.get("service_id") or webui_service_id(),
                    "SERVICE_DATA": {"job_id": job.get("job_id", "")}}
    user_info = {"USER_ID": target.get("user_id") or owner, "USER_DATA": {}}
    overwrite_items = _agent_overwrite_items(agent_file, params.get("engine") or "")

    # target.mode=new keeps the original behaviour: no PUSH indirection, the
    # executed turn IS the session's content, which is what a plain
    # "run this prompt on a schedule" job wants.
    if mode == "new":
        count = max(1, int(target.get("new_count") or 1))
        # Whose session list the new conversations land in. Defaults to the
        # job owner; service_id has to match what the WebUI filters on or the
        # session exists but is never listed.
        _new_user_id = target.get("user_id") or owner
        _new_service_id = target.get("service_id") or webui_service_id()
        exec_dict = {"STREAM_MODE": False, "SAVE_DIGEST": True, "LAST_ONLY": True}
        exec_dict.update(execution)
        first = ""
        for n in range(count):
            session_id = "SCH" + dms.set_new_session_id()
            session_name = f"[Scheduler] {job_name}" + (f" #{n + 1}" if count > 1 else "")
            if msg_mode == "fixed":
                if not user_input:
                    raise ValueError("message.mode=fixed requires params.user_input")
                _sess = dms.DigiMSession(session_id, session_name)
                # Nothing runs DigiMatsuExecute on this path, so the session
                # metadata that normally lands as a side effect has to be
                # written here — without status.yaml the session never shows
                # up in the WebUI list, which scans folders.
                _sess.save_session_metadata(
                    id=session_id, name=session_name, active="Y", status="UNLOCKED",
                    service_id=_new_service_id, user_id=_new_user_id, agent=agent_file,
                    user_dialog="N")
                _sess.save_push_message(
                    user_input, agent_file=agent_file, job_id=job.get("job_id", ""),
                    job_name=job_name, owner_user_id=owner,
                    save_to_memory=bool(save_to_memory))
            else:
                for _ in dme.DigiMatsuExecute_Practice(
                        service_info, user_info, session_id, session_name,
                        agent_file, user_input,
                        in_situation=_scheduled_situation(job, agent_file),
                        in_overwrite_items=overwrite_items, in_execution=exec_dict):
                    pass
            first = first or session_id
        return first

    targets = _push_resolve_targets(job)
    if not targets:
        raise ValueError("agent_run matched no target session")

    # MEMORY_SAVE means the run itself is kept: it executes inside each target
    # as an ordinary turn, so Detail Information / Analytics (RAG, web search,
    # thinking) exist for it. Without it the text is composed in a throwaway
    # session and only the text is posted.
    save_turn = msg_mode != "fixed" and bool(execution.get("MEMORY_SAVE"))
    max_gen = int(params.get("max_generated_sessions") or PUSH_MAX_GENERATED_SESSIONS)
    if msg_mode != "fixed" and (per_session or save_turn) and len(targets) > max_gen:
        _why = "per-session generation" if per_session else "MEMORY_SAVE (runs inside each target)"
        raise ValueError(
            f"{_why} would call the LLM {len(targets)} times "
            f"(limit {max_gen}); narrow the target or raise max_generated_sessions")

    shared_text = ""
    if msg_mode == "fixed":
        shared_text = user_input
        if not shared_text:
            raise ValueError("message.mode=fixed requires params.user_input")
    elif not (per_session or save_turn):
        shared_text = _push_generate_message(job)

    delivered, failed = [], []
    for sid in targets:
        try:
            if save_turn:
                if not _push_generate_message(job, sid, save=True):
                    raise ValueError("empty message")
                _sess = dms.DigiMSession(sid)
                _sess.save_history_batch(str(_sess.get_seq_history()), seq_setting_data={
                    "PUSH": {"job_id": job.get("job_id", ""), "job_name": job_name,
                             "at": str(datetime.now())}})
                delivered.append(sid)
                continue
            text = (_push_generate_message(job, sid)
                    if (msg_mode != "fixed" and per_session) else shared_text)
            if not text:
                raise ValueError("empty message")
            dms.DigiMSession(sid).save_push_message(
                text, agent_file=agent_file, job_id=job.get("job_id", ""),
                job_name=job_name, owner_user_id=owner,
                save_to_memory=bool(save_to_memory),
                prompt_text="" if msg_mode == "fixed" else _push_prompt(params))
            delivered.append(sid)
        except Exception as e:
            logger.error(f"[scheduler] delivery failed session={sid}: {e}")
            failed.append({"session_id": sid, "error": str(e)})

    try:
        _j = dmsj.get(job.get("job_id", "")) or dict(job)
        _j["last_push"] = {
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "targets": len(targets), "delivered": delivered, "failed": failed,
        }
        dmsj.upsert(_j)
    except Exception as e:
        logger.warning(f"[scheduler] could not record delivery result: {e}")

    if not delivered:
        raise RuntimeError(f"agent_run delivered to no session ({len(failed)} failed)")
    return delivered[0]


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


def _push_prompt(params: dict) -> str:
    return params.get("user_input") or (params.get("message") or {}).get("prompt") or ""


def _push_generate_message(job: dict, session_id: str = "", save: bool = False) -> str:
    """Ask the agent to compose the push text. With `session_id` the agent
    sees that conversation's memory, so the message can react to it; without,
    it composes once for everyone. `save=True` (with a session_id) keeps the
    run as a normal turn of that session instead of discarding it."""
    import DigiM_Execute as dme
    import DigiM_Session as dms

    params = job.get("params") or {}
    agent_file = params.get("agent_file")
    owner = job.get("owner_user_id") or "Scheduler"
    prompt = _push_prompt(params)

    gen_session_id = session_id or ("SCH" + dms.set_new_session_id())

    # Composing against an existing conversation runs inside that session, and
    # DigiMatsuExecute_Practice stamps the session name and the caller's
    # service/user identity onto it as a side effect. Reuse what the session
    # already has, otherwise the chat gets renamed to "[Push] <job>" and its
    # service_id flips to "Scheduler" — which hides it from the owner in the
    # WebUI, since the session list filters on service_id + user_id.
    if session_id:
        _svc_id, _usr_id = dms.get_ids(session_id)
        service_info = {"SERVICE_ID": _svc_id, "SERVICE_DATA": {"job_id": job.get("job_id", "")}}
        user_info = {"USER_ID": _usr_id or owner, "USER_DATA": {}}
        gen_session_name = dms.get_session_name(session_id)
    else:
        _t = (job.get("params") or {}).get("target") or {}
        service_info = {"SERVICE_ID": _t.get("service_id") or webui_service_id(),
                        "SERVICE_DATA": {"job_id": job.get("job_id", "")}}
        user_info = {"USER_ID": _t.get("user_id") or owner, "USER_DATA": {}}
        gen_session_name = f"[Push] {job.get('name') or job.get('job_id')}"
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
    if not (save and session_id):
        exec_dict["MEMORY_SAVE"] = False
        exec_dict["SAVE_DIGEST"] = False

    text = ""
    for _item in dme.DigiMatsuExecute_Practice(
            service_info, user_info, gen_session_id, gen_session_name,
            agent_file, prompt,
            in_situation=_scheduled_situation(job, agent_file),
            in_overwrite_items=_agent_overwrite_items(agent_file, params.get("engine") or ""),
            in_execution=exec_dict):
        # The generator yields both 4- and 5-element tuples (status pings vs a
        # completed turn), so index rather than unpack — element 2 is the text
        # in either shape.
        chunk = _item[2] if isinstance(_item, (tuple, list)) and len(_item) > 2 else ""
        if chunk and not str(chunk).startswith("[STATUS]"):
            text += str(chunk)
    return text.strip()


def _exec_agent_push(job: dict) -> str:
    """Kept so jobs saved as kind=agent_push keep running — agent_run now
    covers both delivery shapes."""
    return _exec_agent_run(job)


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
        from apscheduler.triggers.date import DateTrigger
    except Exception as e:
        return {"started": [], "error": str(e)}

    started = []
    errors = {}
    for j, expr in targets:
        job_id = j.get("job_id")
        _tz = resolve_timezone(j.get("timezone") or "")
        _once = _parse_once(expr)
        if _once is not None:
            # Compare in the job's own zone; a wall-clock time is only "past"
            # relative to where it was meant to fire.
            _now_tz = datetime.now(_tz)
            _once_tz = _tz.localize(_once) if hasattr(_tz, "localize") else _once.replace(tzinfo=_tz)
            if _once_tz <= _now_tz:
                # Already elapsed — leave it registered-but-idle rather than
                # firing immediately, which would surprise anyone editing a
                # past-dated job.
                errors[job_id] = f"one-shot time already passed: {_once:%Y-%m-%d %H:%M}"
                logger.info(f"[scheduler] skip elapsed one-shot job_id={job_id} at={_once} tz={_tz}")
                continue
            trigger = DateTrigger(run_date=_once, timezone=_tz)
        else:
            try:
                trigger = CronTrigger.from_crontab(expr, timezone=_tz)
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
