"""Sample LINE front end for DigitalMATSUMOTO.

Two endpoints, usable separately:

  POST /digim/push     what a scheduled job sends (services master PUSH.URL).
                       Each message is pushed to its LINE user with the
                       Messaging API. Works on localhost: only DigiM calls it.
  POST /line/webhook   LINE's webhook (optional). A user's message is run
                       through DigiM's /run as service "LINE" and the answer is
                       pushed back, which is also how a LINE session comes to
                       exist. LINE needs a public HTTPS URL for this one.

Settings come from the environment (DIGIM_ENV_FILE, default ../../system.env):
  LINE_CHANNEL_ACCESS_TOKEN  Messaging API channel access token
  LINE_CHANNEL_SECRET        channel secret (webhook signature check)
  PUSH_TOKEN_LINE            the token DigiM sends (services master TOKEN_ENV)
  DIGIM_API_URL              default http://localhost:8899
  LINE_AGENT_FILE            agent for webhook turns (empty: API_AGENT_FILE)
  LINE_PUSH_DRY_RUN=Y        log instead of calling LINE

Run:  uvicorn line_receiver:app --host 0.0.0.0 --port 8898
"""
import base64
import hashlib
import hmac
import logging
import os
import uuid

import requests
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

_HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.getenv("DIGIM_ENV_FILE") or os.path.join(_HERE, "..", "..", "system.env"))

LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
PUSH_TOKEN = os.getenv("PUSH_TOKEN_LINE", "")
DIGIM_API = (os.getenv("DIGIM_API_URL") or "http://localhost:8899").rstrip("/")
AGENT_FILE = os.getenv("LINE_AGENT_FILE", "")
DRY_RUN = (os.getenv("LINE_PUSH_DRY_RUN") or "N").upper() == "Y"
SERVICE_ID = "LINE"
LINE_TEXT_LIMIT = 5000          # Messaging API limit per text message

logging.basicConfig(level=logging.INFO, format="%(asctime)s [line_receiver] %(message)s")
log = logging.getLogger(__name__)
app = FastAPI()


def _push(to: str, texts: list, retry_key: str = "") -> str:
    """Push up to 5 text bubbles to one user. Returns "" or an error."""
    msgs = [{"type": "text", "text": t[:LINE_TEXT_LIMIT]} for t in texts if t][:5]
    if not msgs:
        return "empty message"
    if DRY_RUN:
        log.info(f"[dry-run] push to={to} bubbles={len(msgs)} first={msgs[0]['text'][:60]!r}")
        return ""
    if not LINE_TOKEN:
        return "LINE_CHANNEL_ACCESS_TOKEN is not set"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    # The same key twice within 24h is accepted once, so a resent batch does
    # not reach the user twice.
    if retry_key:
        headers["X-Line-Retry-Key"] = retry_key
    r = requests.post("https://api.line.me/v2/bot/message/push",
                      headers=headers, json={"to": to, "messages": msgs}, timeout=10)
    if r.status_code == 409:      # already accepted under this retry key
        return ""
    if r.status_code != 200:
        return f"LINE {r.status_code}: {r.text[:200]}"
    return ""


@app.get("/health")
def health():
    return {"status": "ok", "dry_run": DRY_RUN, "line_token": bool(LINE_TOKEN),
            "push_token": bool(PUSH_TOKEN), "webhook_secret": bool(LINE_SECRET)}


@app.post("/digim/push")
async def digim_push(request: Request, authorization: str = Header(default="")):
    if PUSH_TOKEN and not hmac.compare_digest(authorization, f"Bearer {PUSH_TOKEN}"):
        raise HTTPException(status_code=401, detail="bad token")
    body = await request.json()
    failed = []
    for m in body.get("messages") or []:
        to = str(m.get("user_id") or "")
        sid = m.get("session_id")
        # A LINE user id is "U" + 32 hex; anything else was not started from LINE.
        if not (to.startswith("U") and len(to) == 33):
            failed.append({"session_id": sid, "error": f"not a LINE user id: {to!r}"})
            continue
        texts = []
        if body.get("content") == "pair" and m.get("input"):
            texts.append(m["input"])
        # The plain answer: reference sections read poorly in a chat bubble.
        texts.append(m.get("response") or "")
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{body.get('job_id')}:{sid}:{m.get('seq')}"))
        err = _push(to, texts, key)
        if err:
            failed.append({"session_id": sid, "error": err})
    log.info(f"push job={body.get('job_id')} batch={body.get('batch')} "
             f"messages={len(body.get('messages') or [])} failed={len(failed)}")
    return {"failed": failed}


def _answer(user_id: str, text: str):
    payload = {
        "service_info": {"SERVICE_ID": SERVICE_ID, "SERVICE_DATA": {}},
        "user_info": {"USER_ID": user_id, "USER_DATA": {}},
        # One session per LINE user keeps the conversation going across days.
        "session_id": f"LINE{user_id}",
        "user_input": text,
    }
    if AGENT_FILE:
        payload["agent_file"] = AGENT_FILE
    try:
        r = requests.post(f"{DIGIM_API}/run", json=payload, timeout=600)
        r.raise_for_status()
        reply = r.json().get("response") or "(empty response)"
    except Exception as e:
        log.error(f"/run failed user={user_id}: {e}")
        reply = "ごめんなさい、いま応答できませんでした。"
    err = _push(user_id, [reply])
    if err:
        log.error(f"reply push failed user={user_id}: {err}")


@app.post("/line/webhook")
async def line_webhook(request: Request, background: BackgroundTasks,
                       x_line_signature: str = Header(default="")):
    raw = await request.body()
    if not LINE_SECRET:
        raise HTTPException(status_code=503, detail="LINE_CHANNEL_SECRET is not set")
    sig = base64.b64encode(hmac.new(LINE_SECRET.encode(), raw, hashlib.sha256).digest()).decode()
    if not hmac.compare_digest(sig, x_line_signature):
        raise HTTPException(status_code=401, detail="bad signature")
    import json
    for ev in json.loads(raw or b"{}").get("events") or []:
        if ev.get("type") == "message" and (ev.get("message") or {}).get("type") == "text":
            uid = (ev.get("source") or {}).get("userId")
            if uid:
                # A turn takes longer than LINE waits for the webhook, so answer
                # 200 now and push the reply when DigiM is done.
                background.add_task(_answer, uid, ev["message"]["text"])
    return {"status": "ok"}
