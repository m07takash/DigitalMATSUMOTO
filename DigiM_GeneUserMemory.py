"""User memory generation pipeline (History / Nowaday / Persona).

Responsibilities per layer:
  - History: At session end (or any time), generate one record from that session and upsert.
  - Nowaday: Aggregate History records within a period and update the Nowaday profile.
  - Persona: Merge existing Persona with a new Nowaday profile and update Persona.

Uses the user-configured `agent_58/59/60` for LLM calls.

Replaces the legacy DigiM_GeneUserDialog.py.
"""
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Session as dms
import DigiM_UserMemory as dmum

logger = logging.getLogger(__name__)

if os.path.exists("system.env"):
    load_dotenv("system.env")

_setting = dmu.read_yaml_file("setting.yaml")
_practice_folder = _setting["PRACTICE_FOLDER"]

HISTORY_AGENT_FILE = "agent_62UserMemoryHistory.json"
NOWADAY_AGENT_FILE = "agent_61UserMemoryNowaday.json"
PERSONA_AGENT_FILE = "agent_60UserMemoryPersona.json"


# ---------- Plutchik emotion vocabulary / Big5 traits ----------
PLUTCHIK_PRIMARY = (
    "joy", "trust", "fear", "surprise",
    "sadness", "disgust", "anger", "anticipation",
)
PLUTCHIK_SECONDARY = (
    "love", "submission", "awe", "disapproval",
    "remorse", "contempt", "aggressiveness", "optimism",
)
_PLUTCHIK_ALL = set(PLUTCHIK_PRIMARY) | set(PLUTCHIK_SECONDARY)

BIG5_TRAITS = (
    "openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism",
)


def _filter_plutchik_emotions(items):
    """Normalize the LLM output emotions list to Plutchik vocabulary only. Dedupe and normalize case."""
    if not isinstance(items, list):
        return []
    out, seen = [], set()
    for it in items:
        if not isinstance(it, str):
            continue
        key = it.strip().lower()
        if key in _PLUTCHIK_ALL and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _clip01(v, default=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(default)
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _normalize_basic_emotions(d):
    """Coerce basic_emotions to a dict of 8 keys with float values in [0..1]."""
    if not isinstance(d, dict):
        d = {}
    return {k: _clip01(d.get(k), 0.0) for k in PLUTCHIK_PRIMARY}


def _normalize_secondary_emotions(items):
    """Restrict secondary_emotions to Plutchik secondary-emotion English keys only."""
    if not isinstance(items, list):
        return []
    out, seen = [], set()
    for it in items:
        if not isinstance(it, str):
            continue
        k = it.strip().lower()
        if k in PLUTCHIK_SECONDARY and k not in seen:
            seen.add(k)
            out.append(k)
    return out


def _normalize_big5(d):
    """Normalize big5 to {trait: {score, confidence, status}}."""
    if not isinstance(d, dict):
        d = {}
    out = {}
    for trait in BIG5_TRAITS:
        item = d.get(trait) or {}
        if not isinstance(item, dict):
            item = {}
        out[trait] = {
            "score":      _clip01(item.get("score"), 0.5),
            "confidence": _clip01(item.get("confidence"), 0.0),
            "status":     _normalize_status(item.get("status")),
        }
    return out


# ---------- LLM output parsing ----------
def _strip_json_fences(text: str) -> str:
    if not text:
        return ""
    s = text.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    # If there's non-JSON noise at the start, extract from the first '{' to the last '}'
    if not s.startswith("{"):
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if m:
            s = m.group(0)
    return s


def _parse_json_safely(text: str) -> dict:
    raw = _strip_json_fences(text)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        logger.warning(f"[user_memory] JSON parse failed: {raw[:200]!r}")
        return {}


# ---------- LLM execution helpers ----------
def _run_agent(agent_file: str, prompt_template_cd: str, user_query: str, memories=None) -> str:
    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    prompt_template = agent.set_prompt_template(prompt_template_cd)
    full_query = f"{prompt_template}\n{user_query}".strip()
    response = ""
    for _, response_chunk, _ in agent.generate_response(model_type, full_query, memories=memories or [], stream_mode=False):
        if response_chunk:
            response += response_chunk
    return response


def _gather_session_dialog_text(session_id: str, model_name=None, tokenizer=None, memory_limit_tokens=8000) -> str:
    """Convert user utterances + responses + feedback from a whole session into text.

    Exclusion conditions:
      - SETTING.FLG="N" seqs (already filtered by chat_history_active_dict)
      - SETTING.MEMORY_FLG="N" seqs (excluded from memory references)
      - sub_seq with setting.memory_flg="N" (excluded from memory references)
    Feedback is appended at the end with role="feedback" (treated as a strong expression of intent).
    """
    session = dms.DigiMSession(session_id)
    history = session.chat_history_active_dict or {}
    rows = []
    for k in sorted(history.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        seq_block = history[k]
        if not isinstance(seq_block, dict):
            continue
        # seq-level memory-exclusion flag
        if seq_block.get("SETTING", {}).get("MEMORY_FLG", "Y") == "N":
            continue
        for sk in sorted([s for s in seq_block.keys() if s != "SETTING"], key=lambda x: int(x) if x.isdigit() else 0):
            sub = seq_block.get(sk)
            if not isinstance(sub, dict):
                continue
            # sub_seq-level memory-exclusion flag
            if (sub.get("setting", {}) or {}).get("memory_flg", "Y") == "N":
                continue
            q = (sub.get("prompt", {}) or {}).get("query", {}) or {}
            r = sub.get("response", {}) or {}
            user_text = q.get("text") or q.get("input") or ""
            assistant_text = r.get("text") or ""
            if user_text:
                rows.append({"role": "user", "seq": k, "sub_seq": sk, "content": user_text})
            if assistant_text:
                rows.append({"role": "assistant", "seq": k, "sub_seq": sk, "content": assistant_text})
            # Feedback (a strong expression of intent)
            fb = sub.get("feedback") or {}
            if isinstance(fb, dict):
                fb_parts = []
                for fk, fv in fb.items():
                    if not fv:
                        continue
                    if isinstance(fv, (dict, list)):
                        fb_parts.append(f"{fk}={json.dumps(fv, ensure_ascii=False)}")
                    else:
                        fb_parts.append(f"{fk}={fv}")
                if fb_parts:
                    rows.append({"role": "feedback", "seq": k, "sub_seq": sk, "content": " / ".join(fb_parts)})
    return json.dumps(rows, ensure_ascii=False)


# ---------- History memory ----------
def generate_history(service_id: str, user_id: str, session_id: str) -> dict:
    """Generate a History memory record from a session and upsert. Returns the created record."""
    session = dms.DigiMSession(session_id)
    session_name = session.session_name or dms.get_session_name(session_id)
    create_date = dms.get_last_update_date(session_id)
    dialog_text = _gather_session_dialog_text(session_id)
    if not dialog_text or dialog_text == "[]":
        logger.info(f"[user_memory.history] empty conversation; skipping session={session_id}")
        return {}

    raw = _run_agent(HISTORY_AGENT_FILE, "User Memory History", dialog_text)
    parsed = _parse_json_safely(raw)

    rec = {
        "id": dmum.make_history_id(service_id, user_id, session_id),
        "service_id": service_id,
        "user_id": user_id,
        "session_id": session_id,
        "session_name": session_name,
        "create_date": create_date,
        "topic": (parsed.get("topic") or "")[:120],
        "excerpt": (parsed.get("excerpt") or "")[:600],
        "axis_tags": parsed.get("axis_tags") or {},
        "emotions": _filter_plutchik_emotions(parsed.get("emotions") or []),
        "confidence": float(parsed.get("confidence") or 0.0),
        "source_seq": [],
        "active": "Y",
    }
    dmum.upsert("history", rec)
    try:
        session.save_user_dialog_session("SAVED")
    except Exception:
        pass
    logger.info(f"[user_memory.history] saved session={session_id} topic={rec['topic']!r}")
    return rec


# ---------- Nowaday memory ----------
# Max characters of history_records passed to the LLM in a single Nowaday generation
NOWADAY_INPUT_MAX_CHARS = int(os.getenv("USER_MEMORY_NOWADAY_MAX_CHARS") or "50000")


def _trim_histories_by_chars(histories: list, max_chars: int) -> tuple:
    """Sort by create_date descending and pack until the total JSON-serialized size fits within max_chars.

    Returns: (selected: list[newest -> oldest], total_chars: int, dropped_count: int)
    """
    sorted_h = sorted(histories, key=lambda r: r.get("create_date") or "", reverse=True)
    selected = []
    total = 0
    for r in sorted_h:
        compact = json.dumps({
            "session_id": r.get("session_id"),
            "create_date": r.get("create_date"),
            "topic": r.get("topic"),
            "excerpt": r.get("excerpt"),
            "axis_tags": r.get("axis_tags"),
        }, ensure_ascii=False)
        size = len(compact)
        if total + size > max_chars and selected:
            break
        selected.append(r)
        total += size
    dropped = len(sorted_h) - len(selected)
    return selected, total, dropped


def _resolve_period_window(period: str):
    """Return a (start, end) datetime pair from a period spec.

    "all" / empty -> (None, None) no filter (all periods)
    "since_YYYY-MM-DD" -> from that date until now
    "YYYY-MM" -> 0:00 of day 1 of that month -> 0:00 of day 1 of the next month
    "rolling_<N>d" -> N days ago until now
    Anything else -> (None, None) no filter
    """
    if not period or period == "all":
        return None, None
    m = re.match(r"^since_(\d{4})-(\d{1,2})-(\d{1,2})$", period)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = datetime(y, mo, d)
        end = datetime.now()
        return start, end
    m = re.match(r"^(\d{4})-(\d{1,2})$", period)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        start = datetime(y, mo, 1)
        if mo == 12:
            end = datetime(y + 1, 1, 1)
        else:
            end = datetime(y, mo + 1, 1)
        return start, end
    m = re.match(r"^rolling_(\d+)d$", period)
    if m:
        days = int(m.group(1))
        from datetime import timedelta
        end = datetime.now()
        start = end - timedelta(days=days)
        return start, end
    return None, None


def _filter_histories_by_period(histories: list, period: str) -> list:
    start, end = _resolve_period_window(period)
    if start is None:
        return histories
    out = []
    for r in histories:
        try:
            cd = str(r.get("create_date") or "").strip().replace("Z", "+00:00")
            ts = datetime.fromisoformat(cd)
            # Notion etc. are timezone-aware (+00:00); the window is naive, so align them
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
            if start <= ts < end:
                out.append(r)
        except Exception:
            continue
    return out


def build_nowaday_profile(service_id: str, user_id: str, period: str) -> dict:
    """Aggregate History within the period and upsert the Nowaday profile.

    period: "YYYY-MM" or "rolling_<N>d" or "since_YYYY-MM-DD" or "all"
    """
    histories_all = dmum.load_all("history", service_id=service_id, user_id=user_id)
    histories = _filter_histories_by_period(histories_all, period)
    if not histories:
        logger.info(f"[user_memory.nowaday] zero History rows in period user={user_id} period={period}")
        return {}

    # Context-window safety: truncate to the char cap (newest first), then reorder oldest -> newest
    selected_desc, total_chars, dropped_count = _trim_histories_by_chars(histories, NOWADAY_INPUT_MAX_CHARS)
    history_records_for_llm = list(reversed(selected_desc))
    if dropped_count > 0:
        logger.info(f"[user_memory.nowaday] history truncated user={user_id} period={period} kept={len(history_records_for_llm)} dropped={dropped_count} chars={total_chars}/{NOWADAY_INPUT_MAX_CHARS}")

    # Incremental seed: latest snapshot for the same service/user/period (multiple may exist due to history-style storage)
    _same = [m for m in dmum.load_all("nowaday", service_id=service_id, user_id=user_id)
             if (m.get("period") or "") == period and (m.get("active") or "Y") == "Y"]
    _same.sort(key=lambda r: r.get("generated_at") or "", reverse=True)
    existing = _same[0] if _same else None

    payload = {
        "period": period,
        "existing_nowaday_profile": {
            "recurring_topics": (existing or {}).get("recurring_topics") or [],
            "emerging": (existing or {}).get("emerging") or [],
            "declining": (existing or {}).get("declining") or [],
            "shifts": (existing or {}).get("shifts") or [],
            "summary_text": (existing or {}).get("summary_text") or "",
        },
        "history_records": [
            {
                "session_id": s.get("session_id"),
                "create_date": s.get("create_date"),
                "topic": s.get("topic"),
                "excerpt": s.get("excerpt"),
                "axis_tags": s.get("axis_tags"),
                "emotions": s.get("emotions") or [],
            } for s in history_records_for_llm
        ],
        "truncated_older_count": dropped_count,
    }
    raw = _run_agent(NOWADAY_AGENT_FILE, "User Memory Nowaday", json.dumps(payload, ensure_ascii=False))
    parsed = _parse_json_safely(raw)
    if not parsed:
        logger.warning(f"[user_memory.nowaday] LLM output parse failed user={user_id}")
        return {}

    summary = (parsed.get("summary_text") or "").strip()
    _gen = dmum.now_ts()
    _gen_compact = _gen.replace("-", "").replace(":", "").replace(" ", "_")
    rec = {
        "id": dmum.make_nowaday_id(service_id, user_id, period, _gen_compact),
        "service_id": service_id,
        "user_id": user_id,
        "period": period,
        "generated_at": _gen,
        "recurring_topics": parsed.get("recurring_topics") or [],
        "emerging": parsed.get("emerging") or [],
        "declining": parsed.get("declining") or [],
        "shifts": parsed.get("shifts") or [],
        "basic_emotions": _normalize_basic_emotions(parsed.get("basic_emotions")),
        "secondary_emotions": _normalize_secondary_emotions(parsed.get("secondary_emotions")),
        "evidence_session_ids": [s.get("session_id") for s in history_records_for_llm if s.get("session_id")],
        "summary_text": summary,
        "token_count": len(summary),
        "active": "Y",
    }
    dmum.upsert("nowaday", rec)
    logger.info(f"[user_memory.nowaday] saved user={user_id} period={period} sources={len(history_records_for_llm)}/{len(histories)}")
    return rec


def build_nowaday_for_all_users(period: str) -> dict:
    """Update Nowaday profile for all users (targets user_ids that appear in History)."""
    histories = dmum.load_all("history")
    pairs = {(r.get("service_id", ""), r.get("user_id", "")) for r in histories if r.get("user_id")}
    done, errors = [], []
    for sid, uid in pairs:
        try:
            rec = build_nowaday_profile(sid, uid, period)
            if rec:
                done.append((sid, uid))
        except Exception as e:
            logger.error(f"[user_memory.nowaday] failed for {uid}: {e}")
            errors.append((sid, uid))
    return {"done": done, "errors": errors}


# ---------- Persona memory ----------
PERSONA_TOKEN_LIMIT = int(os.getenv("USER_MEMORY_PERSONA_TOKEN_LIMIT") or "3000")
# Rough Japanese approximation: 1 token ~= 1.5 chars. We round down to 1 token = 1 char for safety.
PERSONA_CHAR_LIMIT = PERSONA_TOKEN_LIMIT
# pending items with confidence >= this threshold are auto-promoted to approved
PERSONA_AUTO_APPROVE_THRESHOLD = float(os.getenv("USER_MEMORY_AUTO_APPROVE_THRESHOLD") or "0.8")
# Per field (expertise, etc.), total character cap for Approved + Pending labels
PERSONA_MAX_CHARS_PER_FIELD = int(os.getenv("USER_MEMORY_PERSONA_MAX_CHARS_PER_FIELD") or "300")
# Valid statuses: pending (unreviewed) / approved / deleted
_VALID_STATUSES = ("pending", "approved", "deleted")


def _normalize_status(status: str) -> str:
    """Coerce legacy values like 'edited' to 'approved'. Otherwise keep; unknown -> 'pending'."""
    s = (status or "").strip().lower()
    if s == "edited":
        return "approved"
    if s in _VALID_STATUSES:
        return s
    return "pending"


def _trim_summary_text(summary: str, char_limit: int) -> str:
    if not summary:
        return ""
    if len(summary) <= char_limit:
        return summary
    return summary[: max(0, char_limit - 1)] + "…"


def _merge_persona_lists(existing: list, new: list, max_chars: int = None) -> list:
    """Merge existing (approved kept) with new at the label level; auto-approve when confidence >= threshold.

    The cap is max_chars (total character count of Approved + Pending labels). Default is
    PERSONA_MAX_CHARS_PER_FIELD. Approved is prioritized; within the same status, packed by
    descending confidence.
    Deleted entries are retained entirely (for deletion memory; excluded from aggregation).
    """
    if max_chars is None:
        max_chars = PERSONA_MAX_CHARS_PER_FIELD
    if not isinstance(existing, list):
        existing = []
    if not isinstance(new, list):
        new = []
    by_label = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        lbl = (item.get("label") or "").strip()
        if not lbl:
            continue
        by_label[lbl] = {
            "label": lbl,
            "confidence": float(item.get("confidence") or 0.0),
            "status": _normalize_status(item.get("status")),
            "evidence": item.get("evidence") or [],
        }
    for item in new:
        if not isinstance(item, dict):
            continue
        lbl = (item.get("label") or "").strip()
        if not lbl:
            continue
        if lbl in by_label:
            cur = by_label[lbl]
            # approved is protected (only confidence updated to the max). pending is overwritten. deleted is untouched.
            if cur["status"] == "approved":
                cur["confidence"] = max(cur["confidence"], float(item.get("confidence") or 0.0))
            elif cur["status"] == "pending":
                cur["confidence"] = float(item.get("confidence") or cur["confidence"])
        else:
            by_label[lbl] = {
                "label": lbl,
                "confidence": float(item.get("confidence") or 0.0),
                "status": "pending",
                "evidence": [],
            }
    # Auto-approve: pending with confidence >= threshold -> approved
    for v in by_label.values():
        if v["status"] == "pending" and v["confidence"] >= PERSONA_AUTO_APPROVE_THRESHOLD:
            v["status"] = "approved"
    # deleted is kept after merge (to reject re-suggestion)
    items = list(by_label.values())
    # status priority (approved > pending > deleted) -> confidence descending
    status_order = {"approved": 0, "pending": 1, "deleted": 2}
    items.sort(key=lambda x: (status_order.get(x.get("status"), 9), -x.get("confidence", 0)))
    visible = [x for x in items if x.get("status") != "deleted"]
    deleted = [x for x in items if x.get("status") == "deleted"]

    # Truncate by character count (Approved + Pending label total <= max_chars)
    visible_kept = []
    total_chars = 0
    for it in visible:
        label_len = len((it.get("label") or "").strip())
        if total_chars + label_len > max_chars:
            break
        visible_kept.append(it)
        total_chars += label_len
    return visible_kept + deleted


_PERSONA_LIST_FIELDS = (
    "expertise", "recurring_interests", "values_principles",
    "constraints", "communication_style", "avoid_topics",
)


def _merge_big5(existing: dict, new: dict) -> dict:
    """Merge existing Persona.big5 (approved is protected) with LLM-output big5 per trait.

    - approved: keep the score; only update confidence when the new value is higher.
    - pending : overwrite with the new value. Promote to approved when confidence >= threshold.
    - Missing traits are filled with the midpoint (0.5).
    """
    existing = existing if isinstance(existing, dict) else {}
    new = new if isinstance(new, dict) else {}
    out = {}
    for trait in BIG5_TRAITS:
        cur = existing.get(trait) or {}
        nxt = new.get(trait) or {}
        if not isinstance(cur, dict):
            cur = {}
        if not isinstance(nxt, dict):
            nxt = {}
        cur_status = _normalize_status(cur.get("status"))
        if cur_status == "approved":
            score = _clip01(cur.get("score"), 0.5)
            conf = max(_clip01(cur.get("confidence"), 0.0), _clip01(nxt.get("confidence"), 0.0))
            status = "approved"
        elif cur_status == "deleted":
            score = _clip01(cur.get("score"), 0.5)
            conf = _clip01(cur.get("confidence"), 0.0)
            status = "deleted"
        else:
            if nxt:
                score = _clip01(nxt.get("score"), _clip01(cur.get("score"), 0.5))
                conf = _clip01(nxt.get("confidence"), _clip01(cur.get("confidence"), 0.0))
                status = "pending"
            else:
                score = _clip01(cur.get("score"), 0.5)
                conf = _clip01(cur.get("confidence"), 0.0)
                status = cur_status or "pending"
        if status == "pending" and conf >= PERSONA_AUTO_APPROVE_THRESHOLD:
            status = "approved"
        out[trait] = {"score": score, "confidence": conf, "status": status}
    return out


def merge_persona(service_id: str, user_id: str, nowaday_profiles=None, save: bool = True) -> dict:
    """Merge existing Persona with Nowaday profile(s) via the LLM and upsert the Persona DB.

    nowaday_profiles: list[dict]. If not given, use the latest single Nowaday.
    save: when False, do not upsert; only return the draft rec (for UI preview).
    """
    existing = dmum.get_one("persona", {"service_id": service_id, "user_id": user_id}) or {}
    if nowaday_profiles is None:
        nowadays = dmum.load_all("nowaday", service_id=service_id, user_id=user_id)
        nowadays.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
        nowaday_profiles = nowadays[:1]

    payload = {
        "existing_persona": {k: existing.get(k) for k in _PERSONA_LIST_FIELDS} | {
            "role": existing.get("role", ""),
            "summary_text": existing.get("summary_text", ""),
            "big5": existing.get("big5") or {},
        },
        "nowaday_profiles": [
            {k: m.get(k) for k in (
                "period", "recurring_topics", "emerging", "declining", "shifts",
                "basic_emotions", "secondary_emotions", "summary_text"
            )} for m in (nowaday_profiles or [])
        ],
    }
    if not payload["nowaday_profiles"]:
        logger.info(f"[user_memory.persona] no Nowaday profile; skipping user={user_id}")
        return {}

    raw = _run_agent(PERSONA_AGENT_FILE, "User Memory Persona", json.dumps(payload, ensure_ascii=False))
    parsed = _parse_json_safely(raw)
    if not parsed:
        logger.warning(f"[user_memory.persona] LLM output parse failed user={user_id}")
        return {}

    merged_lists = {}
    for f in _PERSONA_LIST_FIELDS:
        merged_lists[f] = _merge_persona_lists(existing.get(f) or [], parsed.get(f) or [])

    merged_big5 = _merge_big5(existing.get("big5") or {}, parsed.get("big5") or {})

    summary = _trim_summary_text(parsed.get("summary_text") or "", PERSONA_CHAR_LIMIT)

    rec = {
        "service_id": service_id,
        "user_id": user_id,
        "generated_at": dmum.now_ts(),
        "last_reviewed": existing.get("last_reviewed", ""),
        "role": parsed.get("role") or existing.get("role", ""),
        "big5": merged_big5,
        "summary_text": summary,
        "token_count": len(summary),
    }
    rec.update(merged_lists)
    if save:
        dmum.upsert("persona", rec)
        logger.info(f"[user_memory.persona] saved user={user_id} chars={len(summary)}")
    else:
        logger.info(f"[user_memory.persona] draft (no save) user={user_id} chars={len(summary)}")
    return rec


# ---------- For the verification loop ----------
def update_persona_item_status(service_id: str, user_id: str, field: str, label: str, status: str, new_label: str = "") -> bool:
    """Update the status of one Persona item (called from the verification-loop UI).

    status: "approved" | "pending" | "deleted"  (legacy "edited" is treated as "approved")
    new_label: if given, replace the label.
    """
    if field not in _PERSONA_LIST_FIELDS:
        return False
    existing = dmum.get_one("persona", {"service_id": service_id, "user_id": user_id}) or {}
    items = list(existing.get(field) or [])
    target_idx = None
    for i, it in enumerate(items):
        if isinstance(it, dict) and (it.get("label") or "").strip() == label.strip():
            target_idx = i
            break
    if target_idx is None:
        return False
    items[target_idx]["status"] = _normalize_status(status)
    if new_label:
        items[target_idx]["label"] = new_label
    existing[field] = items
    existing["last_reviewed"] = dmum.now_ts()
    # Fill in service_id/user_id if missing
    existing.setdefault("service_id", service_id)
    existing.setdefault("user_id", user_id)
    dmum.upsert("persona", existing)
    return True


def save_history_for_unsaved_sessions(service_id: str = "", user_id: str = "") -> dict:
    """Process sessions whose user_dialog is UNSAVED; delete those marked DISCARD."""
    sessions = dms.get_session_list()
    total_in_filter = 0
    saved, discarded, errors = [], [], []
    error_details = []  # (sid, exc) so we can surface them centrally
    for s in sessions:
        sid = s.get("id")
        if not sid:
            continue
        # Filter by service_id/user_id
        if service_id and s.get("service_id") != service_id:
            continue
        if user_id and s.get("user_id") != user_id:
            continue
        total_in_filter += 1
        try:
            status = dms.get_user_dialog_session(sid)
        except Exception:
            status = "UNSAVED"
        try:
            if status == "UNSAVED":
                rec = generate_history(s.get("service_id", ""), s.get("user_id", ""), sid)
                if rec:
                    saved.append(sid)
            elif status == "DISCARD":
                dmum.delete("history", {"session_id": sid})
                discarded.append(sid)
        except Exception as e:
            # Full traceback to the logger AND to the centralized backend error log,
            # so the failure does not disappear when stderr points at /dev/null.
            logger.exception(f"[user_memory.history] failed for {sid}: {e}")
            try:
                dms.save_global_error_log(e, context={
                    "where": "save_history_for_unsaved_sessions",
                    "session_id": sid,
                    "service_id": s.get("service_id", ""),
                    "user_id": s.get("user_id", ""),
                })
            except Exception:
                pass
            errors.append(sid)
            error_details.append((sid, str(e)))
    logger.info(
        f"[user_memory.history] processed sessions: total_matched={total_in_filter} "
        f"saved={len(saved)} discarded={len(discarded)} errors={len(errors)} "
        f"filter(service_id={service_id!r}, user_id={user_id!r})"
    )
    return {"saved": saved, "discarded": discarded, "errors": errors, "error_details": error_details,
            "total_matched": total_in_filter}


# ---------- Combined pipeline ----------
def update_user_memory_pipeline(target_user_ids=None, period: str = "all", service_id: str = "") -> dict:
    """Combined pipeline that runs History -> Nowaday -> Persona in order.

    Args:
        target_user_ids: List of target user IDs. None or empty -> all users.
        period: Period filter for Nowaday/Persona update. "all" or "since_YYYY-MM-DD" or the existing form.
        service_id: Target service ID (used to filter sessions on the History side).

    Returns: {"history": {...}, "nowaday": [...], "persona": [...], "errors": [...]}
    """
    result = {"history": {}, "nowaday": [], "persona": [], "errors": []}

    # 1. History: process UNSAVED sessions for the target users (or all users)
    if target_user_ids:
        per_user_history = {"saved": [], "discarded": [], "errors": []}
        for uid in target_user_ids:
            r = save_history_for_unsaved_sessions(service_id=service_id, user_id=uid)
            per_user_history["saved"].extend(r.get("saved", []))
            per_user_history["discarded"].extend(r.get("discarded", []))
            per_user_history["errors"].extend(r.get("errors", []))
        result["history"] = per_user_history
    else:
        result["history"] = save_history_for_unsaved_sessions(service_id=service_id)

    # 2. Resolve the target user list: argument first; otherwise users appearing in History
    if target_user_ids:
        users = [(service_id, uid) for uid in target_user_ids]
    else:
        histories = dmum.load_all("history")
        if service_id:
            histories = [r for r in histories if r.get("service_id") == service_id]
        users = sorted({(r.get("service_id", ""), r.get("user_id", "")) for r in histories if r.get("user_id")})

    # 3. Run Nowaday -> Persona per user
    for sid, uid in users:
        try:
            nowaday_rec = build_nowaday_profile(sid, uid, period or "all")
            if nowaday_rec:
                result["nowaday"].append((sid, uid))
        except Exception as e:
            logger.exception(f"[user_memory.pipeline] nowaday failed {uid}: {e}")
            try:
                dms.save_global_error_log(e, context={
                    "where": "update_user_memory_pipeline.nowaday",
                    "service_id": sid, "user_id": uid, "period": period,
                })
            except Exception:
                pass
            result["errors"].append(("nowaday", uid, str(e)))
            continue
        try:
            persona_rec = merge_persona(sid, uid)
            if persona_rec:
                result["persona"].append((sid, uid))
        except Exception as e:
            logger.exception(f"[user_memory.pipeline] persona failed {uid}: {e}")
            try:
                dms.save_global_error_log(e, context={
                    "where": "update_user_memory_pipeline.persona",
                    "service_id": sid, "user_id": uid,
                })
            except Exception:
                pass
            result["errors"].append(("persona", uid, str(e)))

    # Summary log line so ops can see at a glance what the run did,
    # even without trawling the per-step logger.
    logger.info(
        f"[user_memory.pipeline] done: "
        f"users={len(users)} "
        f"history={result['history'] if isinstance(result['history'], dict) else 'n/a'} "
        f"nowaday_saved={len(result['nowaday'])} persona_saved={len(result['persona'])} "
        f"errors={len(result['errors'])}"
    )
    return result


# ---------- Backfill ----------
# Backfill emotions (Plutchik) / Big5 into existing records.
# Unlike the production pipeline (generate_history / build_nowaday_profile / merge_persona)
# that rebuilds from full conversations or all History, this backfill uses a "narrow" prompt
# that fills only the missing fields from the compressed outputs (topic/excerpt/summary/list).
_BACKFILL_HISTORY_PROMPT = """以下の対話セッション要点(topic / excerpt / axis_tags)から、ユーザーが示した特徴的な感情をプルチックの感情の輪に基づいて推定し、英語キーのリストで出力してください。

候補(英語キーで返答):
- 基本8感情: joy, trust, fear, surprise, sadness, disgust, anger, anticipation
- 二次感情(隣接ダイアド): love(joy+trust), submission(trust+fear), awe(fear+surprise), disapproval(surprise+sadness), remorse(sadness+disgust), contempt(disgust+anger), aggressiveness(anger+anticipation), optimism(anticipation+joy)

【入力】
{payload}

出力はJSONのみ。該当なしは空配列:
{{"emotions": ["joy", "..."]}}
"""

_BACKFILL_NOWADAY_PROMPT = """以下のNowadayプロファイル要点(summary_text/recurring_topics/emerging/declining/shifts)から、対象期間にユーザーから感じ取れる感情傾向を推定し、JSONで出力してください。

【入力】
{payload}

出力(JSONのみ):
{{
  "basic_emotions": {{
    "joy": 0.0, "trust": 0.0, "fear": 0.0, "surprise": 0.0,
    "sadness": 0.0, "disgust": 0.0, "anger": 0.0, "anticipation": 0.0
  }},
  "secondary_emotions": ["love/submission/awe/disapproval/remorse/contempt/aggressiveness/optimism のうち発生しているものを英語キーで列挙(なければ空配列)"]
}}

ルール:
- basic_emotions は 8キー固定、各値 0.0〜1.0。出現していない感情は 0.0。
- 推測は控えめに、要点から無理なく読み取れる範囲で。"""

_BACKFILL_PERSONA_PROMPT = """以下のPersona(role/summary_text/各種リスト)から、ユーザーのビッグファイブ(Five Factor Model)の5特性を推定し、JSONで出力してください。

【入力】
{payload}

出力(JSONのみ):
{{
  "big5": {{
    "openness":          {{"score": 0.5, "confidence": 0.0, "status": "pending"}},
    "conscientiousness": {{"score": 0.5, "confidence": 0.0, "status": "pending"}},
    "extraversion":      {{"score": 0.5, "confidence": 0.0, "status": "pending"}},
    "agreeableness":     {{"score": 0.5, "confidence": 0.0, "status": "pending"}},
    "neuroticism":       {{"score": 0.5, "confidence": 0.0, "status": "pending"}}
  }}
}}

ルール:
- score は 0.0〜1.0 (0.5が中央)。
- confidence は抽出根拠の十分さを 0.0〜1.0 で。Persona summary や承認済みリストが具体的であるほど高く。
- status は "pending" を出力(システムが自動でapprovedへ昇格させます)。"""


def _backfill_one(prompt_template: str, payload: dict) -> dict:
    raw = _run_agent(HISTORY_AGENT_FILE, "No Template",
                     prompt_template.format(payload=json.dumps(payload, ensure_ascii=False)))
    return _parse_json_safely(raw) or {}


def backfill_history_record(rec: dict, dry_run: bool = False) -> dict:
    """If a single History record has no emotions, estimate via the LLM and fill it in."""
    if rec.get("emotions"):
        return {"action": "skip_existing", "session_id": rec.get("session_id")}
    parsed = _backfill_one(_BACKFILL_HISTORY_PROMPT, {
        "topic": rec.get("topic", ""),
        "excerpt": rec.get("excerpt", ""),
        "axis_tags": rec.get("axis_tags") or {},
    })
    emotions = _filter_plutchik_emotions(parsed.get("emotions") or [])
    rec["emotions"] = emotions
    if dry_run:
        return {"action": "dry_run", "session_id": rec.get("session_id"), "emotions": emotions}
    dmum.upsert("history", rec)
    return {"action": "saved", "session_id": rec.get("session_id"), "emotions": emotions}


def backfill_nowaday_record(rec: dict, dry_run: bool = False) -> dict:
    """Fill basic_emotions / secondary_emotions for a single Nowaday record."""
    has_basic = isinstance(rec.get("basic_emotions"), dict) and any(
        (v or 0) > 0 for v in (rec.get("basic_emotions") or {}).values()
    )
    has_secondary = bool(rec.get("secondary_emotions"))
    if has_basic and has_secondary:
        return {"action": "skip_existing", "id": rec.get("id")}
    parsed = _backfill_one(_BACKFILL_NOWADAY_PROMPT, {
        "period": rec.get("period", ""),
        "summary_text": rec.get("summary_text", ""),
        "recurring_topics": rec.get("recurring_topics") or [],
        "emerging": rec.get("emerging") or [],
        "declining": rec.get("declining") or [],
        "shifts": rec.get("shifts") or [],
    })
    rec["basic_emotions"] = _normalize_basic_emotions(parsed.get("basic_emotions"))
    rec["secondary_emotions"] = _normalize_secondary_emotions(parsed.get("secondary_emotions"))
    if dry_run:
        return {"action": "dry_run", "id": rec.get("id"),
                "basic_emotions": rec["basic_emotions"], "secondary_emotions": rec["secondary_emotions"]}
    dmum.upsert("nowaday", rec)
    return {"action": "saved", "id": rec.get("id"),
            "basic_emotions": rec["basic_emotions"], "secondary_emotions": rec["secondary_emotions"]}


def backfill_persona_record(rec: dict, dry_run: bool = False) -> dict:
    """Fill big5 for a single Persona record (existing approved values are preserved)."""
    big5 = rec.get("big5") or {}
    has_any = isinstance(big5, dict) and any(
        isinstance(big5.get(t), dict) and (big5[t].get("confidence") or 0) > 0 for t in BIG5_TRAITS
    )
    if has_any:
        return {"action": "skip_existing", "user_id": rec.get("user_id")}
    parsed = _backfill_one(_BACKFILL_PERSONA_PROMPT, {
        "role": rec.get("role", ""),
        "summary_text": rec.get("summary_text", ""),
        "expertise": rec.get("expertise") or [],
        "recurring_interests": rec.get("recurring_interests") or [],
        "values_principles": rec.get("values_principles") or [],
        "constraints": rec.get("constraints") or [],
        "communication_style": rec.get("communication_style") or [],
        "avoid_topics": rec.get("avoid_topics") or [],
    })
    merged = _merge_big5(rec.get("big5") or {}, parsed.get("big5") or {})
    rec["big5"] = merged
    if dry_run:
        return {"action": "dry_run", "user_id": rec.get("user_id"), "big5": merged}
    dmum.upsert("persona", rec)
    return {"action": "saved", "user_id": rec.get("user_id"), "big5": merged}


def _ensure_backfill_schema(layer: str):
    """Only with the Notion backend: add properties for the new fields to the DB."""
    if dmum.get_backend(layer) != "NOTION":
        logger.info(f"[user_memory.backfill][{layer}] backend={dmum.get_backend(layer)} schema check skipped")
        return
    result = dmum.ensure_notion_schema(layer)
    if result.get("added"):
        logger.info(f"[user_memory.backfill][{layer}] Notion properties added: {list(result['added'].keys())}")


def backfill_user_memory(layer_filter: str = "", user_filter: str = "",
                         ensure_schema: bool = True, dry_run: bool = False) -> dict:
    """Backfill emotions / Big5 into existing records across all (or specified) layers.

    Args:
        layer_filter: "history" / "nowaday" / "persona" / empty (= all layers)
        user_filter:  Filter target rows by user_id
        ensure_schema: With the Notion backend, auto-add DB properties
        dry_run: Only print LLM output; do not save
    """
    layers = ("history", "nowaday", "persona") if not layer_filter else (layer_filter,)
    if ensure_schema:
        for lyr in layers:
            _ensure_backfill_schema(lyr)

    summary = {}
    for lyr in layers:
        records = dmum.load_all(lyr)
        if user_filter:
            records = [r for r in records if r.get("user_id") == user_filter]
        logger.info(f"[user_memory.backfill][{lyr}] {len(records)} records (user_filter={user_filter or 'all'})")
        per_record_fn = {
            "history": backfill_history_record,
            "nowaday": backfill_nowaday_record,
            "persona": backfill_persona_record,
        }[lyr]
        results = []
        for rec in records:
            try:
                res = per_record_fn(rec, dry_run=dry_run)
                logger.info(f"[user_memory.backfill][{lyr}] {res.get('action')} "
                            f"{res.get('session_id') or res.get('id') or res.get('user_id')}")
                results.append(res)
            except Exception as e:
                logger.exception(f"[user_memory.backfill][{lyr}] record failed: {e}")
                results.append({"action": "error", "error": str(e)})
        summary[lyr] = {
            "total": len(records),
            "saved": sum(1 for r in results if r.get("action") == "saved"),
            "skipped": sum(1 for r in results if r.get("action") == "skip_existing"),
            "dry_run": sum(1 for r in results if r.get("action") == "dry_run"),
            "errors": sum(1 for r in results if r.get("action") == "error"),
        }
    return summary


# ---------- CLI ----------
# CLI entry for backfilling emotions / Big5 into existing records.
#   python3 DigiM_GeneUserMemory.py --backfill
#   python3 DigiM_GeneUserMemory.py --backfill --layer history --user RealMatsumoto
#   python3 DigiM_GeneUserMemory.py --backfill --dry-run
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="User memory utilities (backfill, etc.)")
    parser.add_argument("--backfill", action="store_true", help="Backfill emotions/Big5 into existing records")
    parser.add_argument("--layer", choices=("history", "nowaday", "persona"), default="")
    parser.add_argument("--user", default="", help="Filter targets by user_id")
    parser.add_argument("--no-schema", action="store_true", help="Skip auto-adding Notion schema properties")
    parser.add_argument("--dry-run", action="store_true", help="Only call the LLM; do not save")
    args = parser.parse_args()
    if args.backfill:
        result = backfill_user_memory(
            layer_filter=args.layer, user_filter=args.user,
            ensure_schema=not args.no_schema, dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
