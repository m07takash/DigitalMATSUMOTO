"""Per-service settings (master `services`) and delivery of scheduled-job
messages to a service's own front end.

DigiM does not talk to LINE / Teams / Slack / Azure Bot Service itself: each
front end already owns its channel tokens, message format and rate limits,
and is usually a customised app of its own. A job only POSTs one JSON shape to
the endpoint the service registered, in batches, and the front end delivers.

Master shape (user/common/mst/services.json, keyed by SERVICE_ID — the
`service_info.SERVICE_ID` the front end sends to /run):
  {
    "LINE": {
      "NAME": "LINE (Azure Bot Service)",
      "ACTIVE": true,
      "PUSH": {
        "URL": "https://bot.example.com/digim/push",
        "TOKEN_ENV": "PUSH_TOKEN_LINE",   # system.env key; the value never goes in the master
        "BATCH_SIZE": 20,                 # sessions per POST
        "INTERVAL_SEC": 1,                # wait between POSTs to the same service
        "TIMEOUT_SEC": 15
      }
    }
  }
"""
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List

import DigiM_MstStore as dmms

logger = logging.getLogger(__name__)

if os.path.exists("system.env"):
    from dotenv import load_dotenv
    load_dotenv("system.env")

DEFAULT_BATCH_SIZE = 20
DEFAULT_INTERVAL_SEC = 1.0
DEFAULT_TIMEOUT_SEC = 15.0
CONTENT_KINDS = ("response", "pair")


def load_all() -> Dict[str, Any]:
    try:
        data = dmms.load("services", default={})
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def push_config(service_id: str) -> Dict[str, Any]:
    """Resolved PUSH settings, or {} when the service has no usable endpoint."""
    svc = load_all().get(service_id or "")
    if not isinstance(svc, dict) or svc.get("ACTIVE") is False:
        return {}
    p = svc.get("PUSH") or {}
    url = str(p.get("URL") or "").strip()
    if not url:
        return {}

    def _num(key, default, cast):
        try:
            return max(cast(p.get(key)), cast(0)) if p.get(key) not in (None, "") else default
        except (TypeError, ValueError):
            return default

    return {
        "url": url,
        "token_env": str(p.get("TOKEN_ENV") or ""),
        "batch_size": max(1, _num("BATCH_SIZE", DEFAULT_BATCH_SIZE, int)),
        "interval_sec": _num("INTERVAL_SEC", DEFAULT_INTERVAL_SEC, float),
        "timeout_sec": _num("TIMEOUT_SEC", DEFAULT_TIMEOUT_SEC, float) or DEFAULT_TIMEOUT_SEC,
    }


def endpoints() -> List[str]:
    """SERVICE_IDs a job can currently deliver to (for the editor's hint)."""
    return [sid for sid in load_all() if push_config(sid)]


def _post(cfg: dict, payload: dict) -> List[dict]:
    """POST one batch. Returns the sessions the front end reported as failed;
    raises when the batch as a whole was not accepted."""
    import requests
    headers = {"Content-Type": "application/json", "X-DigiM-Event": "push"}
    token = os.getenv(cfg["token_env"]) if cfg["token_env"] else ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    res = requests.post(cfg["url"], json=payload, headers=headers, timeout=cfg["timeout_sec"])
    if not (200 <= res.status_code < 300):
        raise RuntimeError(f"HTTP {res.status_code}: {res.text[:200]}")
    # A front end may accept the batch yet fail to reach some users (blocked
    # bot, expired conversation reference); it reports those back by id.
    try:
        body = res.json()
    except ValueError:
        return []
    out = []
    for f in (body.get("failed") or []) if isinstance(body, dict) else []:
        if isinstance(f, dict) and f.get("session_id"):
            out.append({"session_id": f["session_id"], "error": str(f.get("error") or "rejected by front end")})
        elif isinstance(f, str):
            out.append({"session_id": f, "error": "rejected by front end"})
    return out


def deliver(job: dict, items: List[dict], content: str = "response") -> Dict[str, Any]:
    """Send job messages to each session's service front end.

    items: [{session_id, seq, input, response, response_display}] — one per
    target session, as the job delivered it into the history.
    Sessions are grouped by their own service_id (the conversation partner's
    channel), sent BATCH_SIZE at a time with INTERVAL_SEC between POSTs.
    """
    import DigiM_Session as dms

    content = content if content in CONTENT_KINDS else "response"
    report = {"sent": [], "failed": [], "no_endpoint": [], "batches": 0}
    groups: Dict[str, List[dict]] = {}
    for it in items:
        sid = it.get("session_id")
        if not sid:
            continue
        if not (it.get("response") or "").strip():
            # A run with MEMORY_SAVE off leaves no saved answer to read back.
            report["failed"].append({"session_id": sid, "service_id": "", "error": "empty response"})
            continue
        try:
            svc_id, usr_id = dms.get_ids(sid)
        except Exception:
            svc_id, usr_id = "", ""
        msg = {
            "session_id": sid,
            "session_name": dms.get_session_name(sid),
            "user_id": usr_id or "",
            "seq": it.get("seq"),
            "agent_file": it.get("agent_file") or "",
            "response": it.get("response") or "",
            "response_display": it.get("response_display") or it.get("response") or "",
        }
        if content == "pair":
            msg["input"] = it.get("input") or ""
        groups.setdefault(svc_id or "", []).append(msg)

    for svc_id, msgs in groups.items():
        cfg = push_config(svc_id)
        if not cfg:
            report["no_endpoint"] += [{"session_id": m["session_id"], "service_id": svc_id} for m in msgs]
            continue
        chunks = [msgs[i:i + cfg["batch_size"]] for i in range(0, len(msgs), cfg["batch_size"])]
        for n, chunk in enumerate(chunks):
            if n and cfg["interval_sec"]:
                time.sleep(cfg["interval_sec"])
            payload = {
                "event": "push",
                "service_id": svc_id,
                "job_id": job.get("job_id", ""),
                "job_name": job.get("name") or job.get("job_id", ""),
                "content": content,
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "batch": {"no": n + 1, "of": len(chunks), "size": len(chunk)},
                "messages": chunk,
            }
            report["batches"] += 1
            try:
                rejected = _post(cfg, payload)
            except Exception as e:
                logger.error(f"[services] push to {svc_id} failed (batch {n + 1}/{len(chunks)}): {e}")
                report["failed"] += [{"session_id": m["session_id"], "service_id": svc_id, "error": str(e)}
                                     for m in chunk]
                continue
            bad = {r["session_id"]: r["error"] for r in rejected}
            for m in chunk:
                if m["session_id"] in bad:
                    report["failed"].append({"session_id": m["session_id"], "service_id": svc_id,
                                             "error": bad[m["session_id"]]})
                else:
                    report["sent"].append(m["session_id"])
    return report
