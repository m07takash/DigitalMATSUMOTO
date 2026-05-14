"""ユーザーメモリ（History/Nowaday/Persona）の生成パイプライン。

3つの層の責務:
  - History: セッション終了時 / 任意タイミングで、そのセッションから1レコードを生成しupsert
  - Nowaday: 期間内のHistoryレコードを集約しNowadayプロファイルを更新
  - Persona: 既存Personaと新しいNowadayプロファイルをマージしPersonaを更新

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

HISTORY_AGENT_FILE = "agent_58UserMemoryHistory.json"
NOWADAY_AGENT_FILE = "agent_59UserMemoryNowaday.json"
PERSONA_AGENT_FILE = "agent_60UserMemoryPersona.json"


# ---------- 感情語彙 (Plutchik) / Big5 トレイト ----------
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
    """LLM出力の emotions リストを Plutchik 語彙のみに正規化。重複・大小も整える。"""
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
    """basic_emotions を 8キーの dict[float 0..1] に強制。"""
    if not isinstance(d, dict):
        d = {}
    return {k: _clip01(d.get(k), 0.0) for k in PLUTCHIK_PRIMARY}


def _normalize_secondary_emotions(items):
    """secondary_emotions を Plutchik 二次感情の英語キーのみに絞る。"""
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
    """big5 を {trait: {score, confidence, status}} に正規化。"""
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


# ---------- History メモリ ----------
def generate_history(service_id: str, user_id: str, session_id: str) -> dict:
    """セッションからHistoryメモリレコードを生成しupsert。生成したレコードを返す。"""
    session = dms.DigiMSession(session_id)
    session_name = session.session_name or dms.get_session_name(session_id)
    create_date = dms.get_last_update_date(session_id)
    dialog_text = _gather_session_dialog_text(session_id)
    if not dialog_text or dialog_text == "[]":
        logger.info(f"[user_memory.history] 会話履歴が空のためスキップ session={session_id}")
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


# ---------- Nowaday メモリ ----------
# 1回のNowaday生成でLLMに渡す history_records 全体の最大文字数
NOWADAY_INPUT_MAX_CHARS = int(os.getenv("USER_MEMORY_NOWADAY_MAX_CHARS") or "50000")


def _trim_histories_by_chars(histories: list, max_chars: int) -> tuple:
    """create_date降順に並べ、JSON化サイズの合計が max_chars 以内になるまで詰める。

    Returns: (selected: list[最新→古い順], total_chars: int, dropped_count: int)
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


def _filter_histories_by_period(histories: list, period: str) -> list:
    start, end = _resolve_period_window(period)
    if start is None:
        return histories
    out = []
    for r in histories:
        try:
            cd = r.get("create_date") or ""
            ts = datetime.fromisoformat(str(cd).replace("Z", ""))
        except Exception:
            continue
        if start <= ts < end:
            out.append(r)
    return out


def build_nowaday_profile(service_id: str, user_id: str, period: str) -> dict:
    """指定期間のHistoryを集約してNowadayプロファイルをupsert。

    period: "YYYY-MM" or "rolling_<N>d" or "since_YYYY-MM-DD" or "all"
    """
    histories_all = dmum.load_all("history", service_id=service_id, user_id=user_id)
    histories = _filter_histories_by_period(histories_all, period)
    if not histories:
        logger.info(f"[user_memory.nowaday] 期間内のHistoryが0件 user={user_id} period={period}")
        return {}

    # コンテキストウインドウ対策: 最新優先で文字数上限まで切り詰め、古い順に並べ直す
    selected_desc, total_chars, dropped_count = _trim_histories_by_chars(histories, NOWADAY_INPUT_MAX_CHARS)
    history_records_for_llm = list(reversed(selected_desc))
    if dropped_count > 0:
        logger.info(f"[user_memory.nowaday] history切り詰め user={user_id} period={period} kept={len(history_records_for_llm)} dropped={dropped_count} chars={total_chars}/{NOWADAY_INPUT_MAX_CHARS}")

    existing = dmum.get_one("nowaday", {
        "service_id": service_id, "user_id": user_id, "period": period,
    })

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
        logger.warning(f"[user_memory.nowaday] LLM出力パース失敗 user={user_id}")
        return {}

    summary = (parsed.get("summary_text") or "").strip()
    rec = {
        "id": dmum.make_nowaday_id(service_id, user_id, period),
        "service_id": service_id,
        "user_id": user_id,
        "period": period,
        "generated_at": dmum.now_ts(),
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
    """全ユーザーのNowadayプロファイルを更新（Historyに登場するuser_idを対象）。"""
    histories = dmum.load_all("history")
    pairs = {(r.get("service_id", ""), r.get("user_id", "")) for r in histories if r.get("user_id")}
    done, errors = [], []
    for sid, uid in pairs:
        try:
            rec = build_nowaday_profile(sid, uid, period)
            if rec:
                done.append((sid, uid))
        except Exception as e:
            logger.error(f"[user_memory.nowaday] {uid} で失敗: {e}")
            errors.append((sid, uid))
    return {"done": done, "errors": errors}


# ---------- Persona メモリ ----------
PERSONA_TOKEN_LIMIT = int(os.getenv("USER_MEMORY_PERSONA_TOKEN_LIMIT") or "3000")
# 雑な日本語近似: 1トークン≒1.5文字。安全側に倒し1トークン=1文字で扱う。
PERSONA_CHAR_LIMIT = PERSONA_TOKEN_LIMIT
# confidence がこの値以上のpending項目は自動でapprovedへ昇格
PERSONA_AUTO_APPROVE_THRESHOLD = float(os.getenv("USER_MEMORY_AUTO_APPROVE_THRESHOLD") or "0.8")
# 各フィールド(expertise等)で保持する Approved + Pending ラベルの合計文字数上限
PERSONA_MAX_CHARS_PER_FIELD = int(os.getenv("USER_MEMORY_PERSONA_MAX_CHARS_PER_FIELD") or "300")
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
    PERSONA_MAX_CHARS_PER_FIELD。Approved を優先 → 同status内は confidence 降順で詰める。
    deletedは削除記憶として全て保持(集計対象外)。
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
        if v["status"] == "pending" and v["confidence"] >= PERSONA_AUTO_APPROVE_THRESHOLD:
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


_PERSONA_LIST_FIELDS = (
    "expertise", "recurring_interests", "values_principles",
    "constraints", "communication_style", "avoid_topics",
)


def _merge_big5(existing: dict, new: dict) -> dict:
    """既存Persona.big5(approvedは保護) と LLM出力の big5 をトレイト単位でマージ。

    - approved: スコアは保持。confidence のみ上振れたら更新。
    - pending : 新値で上書き。confidence>=閾値で自動approvedへ昇格。
    - 欠損トレイトは中央(0.5)で補完。
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


def merge_persona(service_id: str, user_id: str, nowaday_profiles=None) -> dict:
    """既存PersonaとNowadayプロファイルをLLMでマージし、Persona DBにupsert。

    nowaday_profiles: list[dict]  指定がなければ最新のNowaday 1件を使う。
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
        logger.info(f"[user_memory.persona] Nowadayプロファイルがないためスキップ user={user_id}")
        return {}

    raw = _run_agent(PERSONA_AGENT_FILE, "User Memory Persona", json.dumps(payload, ensure_ascii=False))
    parsed = _parse_json_safely(raw)
    if not parsed:
        logger.warning(f"[user_memory.persona] LLM出力パース失敗 user={user_id}")
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
    dmum.upsert("persona", rec)
    logger.info(f"[user_memory.persona] saved user={user_id} chars={len(summary)}")
    return rec


# ---------- 検証ループ用 ----------
def update_persona_item_status(service_id: str, user_id: str, field: str, label: str, status: str, new_label: str = "") -> bool:
    """Personaの1項目のstatusを更新（検証ループUIから呼ばれる）。

    status: "approved" | "pending" | "deleted"  (旧 "edited" は "approved" として扱う)
    new_label: 指定があればラベルを差し替える。
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
    # service_id/user_idがなければ補完
    existing.setdefault("service_id", service_id)
    existing.setdefault("user_id", user_id)
    dmum.upsert("persona", existing)
    return True


def save_history_for_unsaved_sessions(service_id: str = "", user_id: str = "") -> dict:
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
                rec = generate_history(s.get("service_id", ""), s.get("user_id", ""), sid)
                if rec:
                    saved.append(sid)
            elif status == "DISCARD":
                dmum.delete("history", {"session_id": sid})
                discarded.append(sid)
        except Exception as e:
            logger.error(f"[user_memory.history] {sid} で失敗: {e}")
            errors.append(sid)
    return {"saved": saved, "discarded": discarded, "errors": errors}


# ---------- 統合パイプライン ----------
def update_user_memory_pipeline(target_user_ids=None, period: str = "all", service_id: str = "") -> dict:
    """History → Nowaday → Persona を順に処理する統合パイプライン。

    Args:
        target_user_ids: 対象ユーザーIDのリスト。None または空 → 全ユーザー
        period: Nowaday/Persona 更新時の期間フィルタ。"all" or "since_YYYY-MM-DD" or 既存形式
        service_id: 対象サービスID(History側のセッション絞込みに使用)

    Returns: {"history": {...}, "nowaday": [...], "persona": [...], "errors": [...]}
    """
    result = {"history": {}, "nowaday": [], "persona": [], "errors": []}

    # 1. History: 対象ユーザー(または全ユーザー)のUNSAVEDセッションを処理
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

    # 2. 対象ユーザーリストの確定: 引数優先、無ければ History DBに登場するユーザー
    if target_user_ids:
        users = [(service_id, uid) for uid in target_user_ids]
    else:
        histories = dmum.load_all("history")
        if service_id:
            histories = [r for r in histories if r.get("service_id") == service_id]
        users = sorted({(r.get("service_id", ""), r.get("user_id", "")) for r in histories if r.get("user_id")})

    # 3. Nowaday → Persona を各ユーザーで実行
    for sid, uid in users:
        try:
            nowaday_rec = build_nowaday_profile(sid, uid, period or "all")
            if nowaday_rec:
                result["nowaday"].append((sid, uid))
        except Exception as e:
            logger.error(f"[user_memory.pipeline] nowaday失敗 {uid}: {e}")
            result["errors"].append(("nowaday", uid, str(e)))
            continue
        try:
            persona_rec = merge_persona(sid, uid)
            if persona_rec:
                result["persona"].append((sid, uid))
        except Exception as e:
            logger.error(f"[user_memory.pipeline] persona失敗 {uid}: {e}")
            result["errors"].append(("persona", uid, str(e)))

    return result


# ---------- バックフィル ----------
# 既存レコードに後追いで感情(Plutchik) / Big5 を埋める。本番パイプラインの
# generate_history / build_nowaday_profile / merge_persona は対話全文や全Historyから
# 作り直すのに対し、こちらは既存レコードの圧縮済み出力(topic/excerpt/summary/list)から
# 抜けているフィールドだけを埋める「狭い」プロンプトを使う。
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
    """1件のHistoryレコードに emotions が無ければLLMで推定して埋める。"""
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
    """1件のNowadayレコードに basic_emotions / secondary_emotions を埋める。"""
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
    """1件のPersonaレコードに big5 を埋める(既存approvedは保護)。"""
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
    """Notionバックエンド時のみ、新フィールドのプロパティをDBに追加。"""
    if dmum.get_backend(layer) != "NOTION":
        logger.info(f"[user_memory.backfill][{layer}] backend={dmum.get_backend(layer)} schema check skipped")
        return
    result = dmum.ensure_notion_schema(layer)
    if result.get("added"):
        logger.info(f"[user_memory.backfill][{layer}] Notion properties added: {list(result['added'].keys())}")


def backfill_user_memory(layer_filter: str = "", user_filter: str = "",
                         ensure_schema: bool = True, dry_run: bool = False) -> dict:
    """全(or指定)層の既存レコードに感情/Big5を後追いで埋める。

    Args:
        layer_filter: "history" / "nowaday" / "persona" / 空(=全層)
        user_filter:  user_id で対象を絞る
        ensure_schema: Notionバックエンド時にDBプロパティを自動追加
        dry_run: 保存せずLLM結果のみ表示
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
# 既存レコードへの感情/Big5バックフィル用エントリ。
#   python3 DigiM_GeneUserMemory.py --backfill
#   python3 DigiM_GeneUserMemory.py --backfill --layer history --user RealMatsumoto
#   python3 DigiM_GeneUserMemory.py --backfill --dry-run
if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="User memory utilities (backfill, etc.)")
    parser.add_argument("--backfill", action="store_true", help="既存レコードに感情/Big5を後追いで埋める")
    parser.add_argument("--layer", choices=("history", "nowaday", "persona"), default="")
    parser.add_argument("--user", default="", help="user_id で対象を絞る")
    parser.add_argument("--no-schema", action="store_true", help="Notionスキーマ自動追加をスキップ")
    parser.add_argument("--dry-run", action="store_true", help="LLM呼び出しのみで保存しない")
    args = parser.parse_args()
    if args.backfill:
        result = backfill_user_memory(
            layer_filter=args.layer, user_filter=args.user,
            ensure_schema=not args.no_schema, dry_run=args.dry_run,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
