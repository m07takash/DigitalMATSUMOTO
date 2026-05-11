"""ユーザーメモリの Nowaday/Persona 更新スケジューラ。

system.env の USER_MEMORY_NOWADAY_SCHEDULE で起動条件を切替:
  "off"     ... スケジューラ起動しない
  "monthly" ... 毎月1日 03:00 (cron: "0 3 1 * *")
  "weekly"  ... 毎週月曜 03:00 (cron: "0 3 * * 1")
  cron文字列(5フィールド): そのcronで起動

単一プロセスで1度だけ起動するようstart()は冪等。
APSchedulerが入っていない環境では起動をスキップする（手動更新は引き続き可能）。
"""
import logging
import os
import threading
from datetime import datetime

from dotenv import load_dotenv

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


def _get_schedule_expr() -> str:
    raw = (os.getenv("USER_MEMORY_NOWADAY_SCHEDULE") or "off").strip()
    if raw.lower() == "off":
        return ""
    return _PRESETS.get(raw.lower(), raw)


def _job_fn():
    """スケジューラから呼ばれる。Nowaday→Persona を順に更新。"""
    import DigiM_GeneUserMemory as g
    period = datetime.now().strftime("%Y-%m")
    logger.info(f"[user_memory.scheduler] run start period={period}")
    try:
        result_nowaday = g.build_nowaday_for_all_users(period)
        for sid, uid in result_nowaday.get("done", []):
            try:
                g.merge_persona(sid, uid)
            except Exception as e:
                logger.error(f"[user_memory.scheduler] persona failed {uid}: {e}")
        logger.info(f"[user_memory.scheduler] run end nowaday_done={len(result_nowaday.get('done', []))} nowaday_err={len(result_nowaday.get('errors', []))}")
    except Exception as e:
        logger.error(f"[user_memory.scheduler] job error: {e}")


def start() -> bool:
    """スケジューラ起動（冪等）。起動成功でTrue。"""
    global _scheduler
    expr = _get_schedule_expr()
    if not expr:
        logger.info("[user_memory.scheduler] OFF（USER_MEMORY_NOWADAY_SCHEDULE）")
        return False
    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            return True
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
        except Exception as e:
            logger.warning(f"[user_memory.scheduler] APScheduler未インストールのため起動スキップ: {e}")
            return False
        try:
            trigger = CronTrigger.from_crontab(expr)
        except Exception as e:
            logger.warning(f"[user_memory.scheduler] cron式不正: {expr} ({e})")
            return False
        sched = BackgroundScheduler(timezone=os.getenv("TIMEZONE") or "Asia/Tokyo")
        sched.add_job(_job_fn, trigger=trigger, id="user_memory_nowaday_persona", replace_existing=True)
        sched.start()
        _scheduler = sched
        logger.info(f"[user_memory.scheduler] started cron='{expr}'")
        return True


def stop():
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            _scheduler.shutdown(wait=False)
        _scheduler = None
