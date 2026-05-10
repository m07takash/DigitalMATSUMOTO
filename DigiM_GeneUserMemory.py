"""ユーザーメモリ（短期/中期/長期）の生成パイプライン。

3つの層の責務:
  - 短期: セッション終了時 / 任意タイミングで、そのセッションから1レコードを生成しupsert
  - 中期: 期間内の短期レコードを集約し中期プロファイルを更新
  - 長期: 既存長期ペルソナと新しい中期プロファイルをマージし長期ペルソナを更新

LLMはユーザー設定済みの `agent_58/59/60` を呼び出す。

旧 DigiM_GeneUserDialog.py はこのモジュールに置換されました。
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

SHORT_AGENT_FILE = "agent_58UserMemoryShort.json"
MID_AGENT_FILE   = "agent_59UserMemoryMid.json"
LONG_AGENT_FILE  = "agent_60UserMemoryLong.json"


# ---------- LLM出力パース ----------
def _strip_json_fences(text: str) -> str:
    if not text:
        return ""
    s = text.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    # 先頭にJSON以外の文字がある場合は最初の{～最後の}を抜き出す
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
        logger.warning(f"[user_memory] JSONパース失敗: {raw[:200]!r}")
        return {}


# ---------- LLM実行ヘルパ ----------
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
    """セッション全体からユーザー発言+応答+フィードバックをテキスト化。

    除外条件:
      - SETTING.FLG="N" の seq（chat_history_active_dict が既に弾く）
      - SETTING.MEMORY_FLG="N" の seq（メモリ参照対象外）
      - sub_seq の setting.memory_flg="N"（メモリ参照対象外）
    フィードバックは role="feedback" として末尾に付与（本人意思の強い表明として扱う）。
    """
    session = dms.DigiMSession(session_id)
    history = session.chat_history_active_dict or {}
    rows = []
    for k in sorted(history.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        seq_block = history[k]
        if not isinstance(seq_block, dict):
            continue
        # seq単位のメモリ除外フラグ
        if seq_block.get("SETTING", {}).get("MEMORY_FLG", "Y") == "N":
            continue
        for sk in sorted([s for s in seq_block.keys() if s != "SETTING"], key=lambda x: int(x) if x.isdigit() else 0):
            sub = seq_block.get(sk)
            if not isinstance(sub, dict):
                continue
            # sub_seq単位のメモリ除外フラグ
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
            # フィードバック（本人意思が強く出るところ）
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


# ---------- 短期メモリ ----------
def generate_short(service_id: str, user_id: str, session_id: str) -> dict:
    """セッションから短期メモリレコードを生成しupsert。生成したレコードを返す。"""
    session = dms.DigiMSession(session_id)
    session_name = session.session_name or dms.get_session_name(session_id)
    create_date = dms.get_last_update_date(session_id)
    dialog_text = _gather_session_dialog_text(session_id)
    if not dialog_text or dialog_text == "[]":
        logger.info(f"[user_memory.short] 会話履歴が空のためスキップ session={session_id}")
        return {}

    raw = _run_agent(SHORT_AGENT_FILE, "User Memory Short", dialog_text)
    parsed = _parse_json_safely(raw)

    rec = {
        "id": dmum.make_short_id(service_id, user_id, session_id),
        "service_id": service_id,
        "user_id": user_id,
        "session_id": session_id,
        "session_name": session_name,
        "create_date": create_date,
        "topic": (parsed.get("topic") or "")[:120],
        "excerpt": (parsed.get("excerpt") or "")[:600],
        "axis_tags": parsed.get("axis_tags") or {},
        "confidence": float(parsed.get("confidence") or 0.0),
        "source_seq": [],
        "active": "Y",
    }
    dmum.upsert("short", rec)
    try:
        session.save_user_dialog_session("SAVED")
    except Exception:
        pass
    logger.info(f"[user_memory.short] saved session={session_id} topic={rec['topic']!r}")
    return rec


# ---------- 中期メモリ ----------
def _resolve_period_window(period: str):
    """period から (start, end) のdatetime対を返す。

    "all" / 空 → (None, None) フィルタなし（全期間）
    "since_YYYY-MM-DD" → その日以降〜今
    "YYYY-MM" → その月の1日0:00 〜 翌月1日0:00
    "rolling_<N>d" → 今からN日前 〜 今
    上記以外 → (None, None) フィルタなし
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


def _filter_shorts_by_period(shorts: list, period: str) -> list:
    start, end = _resolve_period_window(period)
    if start is None:
        return shorts
    out = []
    for r in shorts:
        try:
            cd = r.get("create_date") or ""
            ts = datetime.fromisoformat(str(cd).replace("Z", ""))
        except Exception:
            continue
        if start <= ts < end:
            out.append(r)
    return out


def build_mid_profile(service_id: str, user_id: str, period: str) -> dict:
    """指定期間の短期を集約して中期プロファイルをupsert。

    period: "YYYY-MM" or "rolling_<N>d"
    """
    shorts_all = dmum.load_all("short", service_id=service_id, user_id=user_id)
    shorts = _filter_shorts_by_period(shorts_all, period)
    if not shorts:
        logger.info(f"[user_memory.mid] 期間内の短期が0件 user={user_id} period={period}")
        return {}

    existing = dmum.get_one("mid", {
        "service_id": service_id, "user_id": user_id, "period": period,
    })

    payload = {
        "period": period,
        "existing_mid_profile": {
            "recurring_topics": (existing or {}).get("recurring_topics") or [],
            "emerging": (existing or {}).get("emerging") or [],
            "declining": (existing or {}).get("declining") or [],
            "shifts": (existing or {}).get("shifts") or [],
            "summary_text": (existing or {}).get("summary_text") or "",
        },
        "short_records": [
            {
                "session_id": s.get("session_id"),
                "create_date": s.get("create_date"),
                "topic": s.get("topic"),
                "excerpt": s.get("excerpt"),
                "axis_tags": s.get("axis_tags"),
            } for s in shorts
        ],
    }
    raw = _run_agent(MID_AGENT_FILE, "User Memory Mid", json.dumps(payload, ensure_ascii=False))
    parsed = _parse_json_safely(raw)
    if not parsed:
        logger.warning(f"[user_memory.mid] LLM出力パース失敗 user={user_id}")
        return {}

    summary = (parsed.get("summary_text") or "").strip()
    rec = {
        "id": dmum.make_mid_id(service_id, user_id, period),
        "service_id": service_id,
        "user_id": user_id,
        "period": period,
        "generated_at": dmum.now_ts(),
        "recurring_topics": parsed.get("recurring_topics") or [],
        "emerging": parsed.get("emerging") or [],
        "declining": parsed.get("declining") or [],
        "shifts": parsed.get("shifts") or [],
        "evidence_session_ids": [s.get("session_id") for s in shorts if s.get("session_id")],
        "summary_text": summary,
        "token_count": len(summary),
        "active": "Y",
    }
    dmum.upsert("mid", rec)
    logger.info(f"[user_memory.mid] saved user={user_id} period={period} sources={len(shorts)}")
    return rec


def build_mid_for_all_users(period: str) -> dict:
    """全ユーザーの中期プロファイルを更新（短期に登場するuser_idを対象）。"""
    shorts = dmum.load_all("short")
    pairs = {(r.get("service_id", ""), r.get("user_id", "")) for r in shorts if r.get("user_id")}
    done, errors = [], []
    for sid, uid in pairs:
        try:
            rec = build_mid_profile(sid, uid, period)
            if rec:
                done.append((sid, uid))
        except Exception as e:
            logger.error(f"[user_memory.mid] {uid} で失敗: {e}")
            errors.append((sid, uid))
    return {"done": done, "errors": errors}


# ---------- 長期メモリ ----------
LONG_TOKEN_LIMIT = int(os.getenv("USER_MEMORY_LONG_TOKEN_LIMIT") or "3000")
# 雑な日本語近似: 1トークン≒1.5文字。安全側に倒し1トークン=1文字で扱う。
LONG_CHAR_LIMIT = LONG_TOKEN_LIMIT
# confidence がこの値以上のpending項目は自動でapprovedへ昇格
LONG_AUTO_APPROVE_THRESHOLD = float(os.getenv("USER_MEMORY_AUTO_APPROVE_THRESHOLD") or "0.8")
# 各フィールド(expertise等)で保持する Approved + Pending ラベルの合計文字数上限
LONG_MAX_CHARS_PER_FIELD = int(os.getenv("USER_MEMORY_LONG_MAX_CHARS_PER_FIELD") or "300")
# 有効ステータス: pending(未レビュー) / approved(承認済) / deleted(削除済)
_VALID_STATUSES = ("pending", "approved", "deleted")


def _normalize_status(status: str) -> str:
    """旧 'edited' 等を 'approved' へ寄せる。それ以外は既存ステータス、未知は 'pending'。"""
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
    """existing(承認済はキープ) と new をラベル単位でマージし、confidence>=閾値は自動承認。

    保持上限は max_chars（Approved + Pending ラベルの合計文字数）。デフォルトは
    LONG_MAX_CHARS_PER_FIELD。Approved を優先 → 同status内は confidence 降順で詰める。
    deletedは削除記憶として全て保持(集計対象外)。
    """
    if max_chars is None:
        max_chars = LONG_MAX_CHARS_PER_FIELD
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
            # approvedは保護（信頼度のみ最大値で更新）。pendingは新値で上書き。deletedは触らない。
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
    # 自動承認: pending かつ confidence >= 閾値 → approved
    for v in by_label.values():
        if v["status"] == "pending" and v["confidence"] >= LONG_AUTO_APPROVE_THRESHOLD:
            v["status"] = "approved"
    # deletedはマージ後も保持（再提案を弾く用途）
    items = list(by_label.values())
    # status優先 (approved > pending > deleted) → confidence降順
    status_order = {"approved": 0, "pending": 1, "deleted": 2}
    items.sort(key=lambda x: (status_order.get(x.get("status"), 9), -x.get("confidence", 0)))
    visible = [x for x in items if x.get("status") != "deleted"]
    deleted = [x for x in items if x.get("status") == "deleted"]

    # 文字数で打ち切り (Approved + Pending の label 文字数合計 <= max_chars)
    visible_kept = []
    total_chars = 0
    for it in visible:
        label_len = len((it.get("label") or "").strip())
        if total_chars + label_len > max_chars:
            break
        visible_kept.append(it)
        total_chars += label_len
    return visible_kept + deleted


_LONG_LIST_FIELDS = (
    "expertise", "recurring_interests", "values_principles",
    "constraints", "communication_style", "avoid_topics",
)


def merge_long_persona(service_id: str, user_id: str, mid_profiles=None) -> dict:
    """既存長期ペルソナと中期プロファイルをLLMでマージし、長期DBにupsert。

    mid_profiles: list[dict]  指定がなければ最新の中期1件を使う。
    """
    existing = dmum.get_one("long", {"service_id": service_id, "user_id": user_id}) or {}
    if mid_profiles is None:
        mids = dmum.load_all("mid", service_id=service_id, user_id=user_id)
        mids.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
        mid_profiles = mids[:1]

    payload = {
        "existing_long_persona": {k: existing.get(k) for k in _LONG_LIST_FIELDS} | {
            "role": existing.get("role", ""),
            "summary_text": existing.get("summary_text", ""),
        },
        "mid_profiles": [
            {k: m.get(k) for k in (
                "period", "recurring_topics", "emerging", "declining", "shifts", "summary_text"
            )} for m in (mid_profiles or [])
        ],
    }
    if not payload["mid_profiles"]:
        logger.info(f"[user_memory.long] 中期プロファイルがないためスキップ user={user_id}")
        return {}

    raw = _run_agent(LONG_AGENT_FILE, "User Memory Long", json.dumps(payload, ensure_ascii=False))
    parsed = _parse_json_safely(raw)
    if not parsed:
        logger.warning(f"[user_memory.long] LLM出力パース失敗 user={user_id}")
        return {}

    merged_lists = {}
    for f in _LONG_LIST_FIELDS:
        merged_lists[f] = _merge_persona_lists(existing.get(f) or [], parsed.get(f) or [])

    summary = _trim_summary_text(parsed.get("summary_text") or "", LONG_CHAR_LIMIT)

    rec = {
        "service_id": service_id,
        "user_id": user_id,
        "generated_at": dmum.now_ts(),
        "last_reviewed": existing.get("last_reviewed", ""),
        "role": parsed.get("role") or existing.get("role", ""),
        "summary_text": summary,
        "token_count": len(summary),
    }
    rec.update(merged_lists)
    dmum.upsert("long", rec)
    logger.info(f"[user_memory.long] saved user={user_id} chars={len(summary)}")
    return rec


# ---------- 検証ループ用 ----------
def update_long_item_status(service_id: str, user_id: str, field: str, label: str, status: str, new_label: str = "") -> bool:
    """長期ペルソナの1項目のstatusを更新（検証ループUIから呼ばれる）。

    status: "approved" | "pending" | "deleted"  (旧 "edited" は "approved" として扱う)
    new_label: 指定があればラベルを差し替える。
    """
    if field not in _LONG_LIST_FIELDS:
        return False
    existing = dmum.get_one("long", {"service_id": service_id, "user_id": user_id}) or {}
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
    # service_id/user_idがなければ補完
    existing.setdefault("service_id", service_id)
    existing.setdefault("user_id", user_id)
    dmum.upsert("long", existing)
    return True


def save_short_for_unsaved_sessions(service_id: str = "", user_id: str = "") -> dict:
    """全セッションのうち user_dialog 状態が UNSAVED のものを処理し、DISCARDのものはdelete。"""
    sessions = dms.get_session_list()
    saved, discarded, errors = [], [], []
    for s in sessions:
        sid = s.get("id")
        if not sid:
            continue
        # service_id/user_id でフィルタ
        if service_id and s.get("service_id") != service_id:
            continue
        if user_id and s.get("user_id") != user_id:
            continue
        try:
            status = dms.get_user_dialog_session(sid)
        except Exception:
            status = "UNSAVED"
        try:
            if status == "UNSAVED":
                rec = generate_short(s.get("service_id", ""), s.get("user_id", ""), sid)
                if rec:
                    saved.append(sid)
            elif status == "DISCARD":
                dmum.delete("short", {"session_id": sid})
                discarded.append(sid)
        except Exception as e:
            logger.error(f"[user_memory.short] {sid} で失敗: {e}")
            errors.append(sid)
    return {"saved": saved, "discarded": discarded, "errors": errors}


# ---------- 統合パイプライン ----------
def update_user_memory_pipeline(target_user_ids=None, period: str = "all", service_id: str = "") -> dict:
    """Short → Mid → Long を順に処理する統合パイプライン。

    Args:
        target_user_ids: 対象ユーザーIDのリスト。None または空 → 全ユーザー
        period: 中期/長期更新時の期間フィルタ。"all" or "since_YYYY-MM-DD" or 既存形式
        service_id: 対象サービスID(短期側のセッション絞込みに使用)

    Returns: {"short": {...}, "mid": [...], "long": [...], "errors": [...]}
    """
    result = {"short": {}, "mid": [], "long": [], "errors": []}

    # 1. 短期: 対象ユーザー(または全ユーザー)のUNSAVEDセッションを処理
    if target_user_ids:
        per_user_short = {"saved": [], "discarded": [], "errors": []}
        for uid in target_user_ids:
            r = save_short_for_unsaved_sessions(service_id=service_id, user_id=uid)
            per_user_short["saved"].extend(r.get("saved", []))
            per_user_short["discarded"].extend(r.get("discarded", []))
            per_user_short["errors"].extend(r.get("errors", []))
        result["short"] = per_user_short
    else:
        result["short"] = save_short_for_unsaved_sessions(service_id=service_id)

    # 2. 対象ユーザーリストの確定: 引数優先、無ければ短期DBに登場するユーザー
    if target_user_ids:
        users = [(service_id, uid) for uid in target_user_ids]
    else:
        shorts = dmum.load_all("short")
        if service_id:
            shorts = [r for r in shorts if r.get("service_id") == service_id]
        users = sorted({(r.get("service_id", ""), r.get("user_id", "")) for r in shorts if r.get("user_id")})

    # 3. 中期 → 長期 を各ユーザーで実行
    for sid, uid in users:
        try:
            mid_rec = build_mid_profile(sid, uid, period or "all")
            if mid_rec:
                result["mid"].append((sid, uid))
        except Exception as e:
            logger.error(f"[user_memory.pipeline] mid失敗 {uid}: {e}")
            result["errors"].append(("mid", uid, str(e)))
            continue
        try:
            long_rec = merge_long_persona(sid, uid)
            if long_rec:
                result["long"].append((sid, uid))
        except Exception as e:
            logger.error(f"[user_memory.pipeline] long失敗 {uid}: {e}")
            result["errors"].append(("long", uid, str(e)))

    return result
