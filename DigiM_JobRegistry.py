import threading
import ctypes
import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

# job_id -> dict(thread, type, message, start_time, session_id, user_id, cancel_requested)
_JOBS = {}
_LOCK = threading.Lock()


def new_job_id():
    return str(uuid.uuid4())


def register_job(job_id, thread, job_type, message="", session_id=None, user_id=None):
    with _LOCK:
        _JOBS[job_id] = {
            "thread": thread,
            "type": job_type,
            "message": message,
            "start_time": datetime.now(),
            "session_id": session_id,
            "user_id": user_id,
            "cancel_requested": False,
        }


def unregister_job(job_id):
    with _LOCK:
        _JOBS.pop(job_id, None)


def is_cancelled(job_id):
    with _LOCK:
        j = _JOBS.get(job_id)
        return bool(j and j["cancel_requested"])


def list_jobs(user_id=None):
    with _LOCK:
        # 生きていないスレッドのエントリを掃除
        for jid in list(_JOBS.keys()):
            if not _JOBS[jid]["thread"].is_alive():
                del _JOBS[jid]
        result = []
        for jid, j in _JOBS.items():
            if user_id is not None and j.get("user_id") not in (None, user_id):
                continue
            result.append({
                "job_id": jid,
                "type": j["type"],
                "message": j["message"],
                "start_time": j["start_time"],
                "session_id": j["session_id"],
                "user_id": j["user_id"],
                "cancel_requested": j["cancel_requested"],
            })
        return result


# スレッドに非同期例外を注入して停止を試みる
def _async_raise(thread_ident, exctype):
    if thread_ident is None:
        return False
    tid = ctypes.c_long(thread_ident)
    res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exctype))
    if res == 0:
        logger.warning(f"async_raise: invalid thread id {thread_ident}")
        return False
    if res > 1:
        # 想定外の複数スレッドにヒット → ロールバック
        ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.c_long(0))
        logger.error("async_raise: PyThreadState_SetAsyncExc hit multiple threads")
        return False
    return True


def cancel_job(job_id):
    with _LOCK:
        j = _JOBS.get(job_id)
        if not j:
            return False
        j["cancel_requested"] = True
        thread = j["thread"]
    if not thread.is_alive():
        return True
    logger.info(f"Cancelling job {job_id} (thread={thread.ident})")
    return _async_raise(thread.ident, SystemExit)
