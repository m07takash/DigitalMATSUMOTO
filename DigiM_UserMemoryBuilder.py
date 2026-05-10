"""ユーザーメモリ層を会話履歴メモリに注入する形式へ合成する。

呼び出しフロー:
    items = build_memory_items(service_id, user_id, active_layers)
    memories_with_um = items + memories_selected
    agent.generate_response(..., memories=memories_with_um, ...)

返却するアイテムは既存 memory パイプラインの形式に合わせる:
    {"role": "user"/"assistant", "type": ..., "timestamp": ..., "token": int,
     "text": str, "vec_text": [], "similarity_prompt": 0,
     "seq": "_um", "sub_seq": "<layer>"}

注入元のIDは `user_memory_used` キー(リスト)としても返し、効果ログに使う。
"""
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

import DigiM_Util as dmu
import DigiM_UserMemory as dmum
import DigiM_UserMemorySetting as dmus

logger = logging.getLogger(__name__)

if os.path.exists("system.env"):
    load_dotenv("system.env")

LONG_TOKEN_LIMIT = int(os.getenv("USER_MEMORY_LONG_TOKEN_LIMIT") or "3000")


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _approx_tokens(text: str) -> int:
    """日本語混じりの粗い近似（1文字≒1トークン）。"""
    return len(text or "")


def _format_long(rec: dict) -> str:
    if not rec:
        return ""
    parts = []
    role = rec.get("role")
    if role:
        parts.append(f"・役割: {role}")

    def _items_to_text(label, items):
        if not isinstance(items, list):
            return None
        kept = [it.get("label", "").strip() for it in items
                if isinstance(it, dict) and (it.get("status") not in ("deleted",)) and (it.get("label", "").strip())]
        if not kept:
            return None
        return f"・{label}: " + "、".join(kept)

    for label, key in (
        ("専門", "expertise"),
        ("関心", "recurring_interests"),
        ("価値観", "values_principles"),
        ("制約", "constraints"),
        ("口調/説明の好み", "communication_style"),
        ("避けたい話題", "avoid_topics"),
    ):
        line = _items_to_text(label, rec.get(key))
        if line:
            parts.append(line)

    summary = (rec.get("summary_text") or "").strip()
    if summary:
        parts.append("")
        parts.append(summary)
    text = "[ユーザー長期理解]\n" + "\n".join(parts)
    if len(text) > LONG_TOKEN_LIMIT:
        text = text[: LONG_TOKEN_LIMIT - 1] + "…"
    return text


def _format_mid(rec: dict) -> str:
    if not rec:
        return ""
    parts = [f"[ユーザー中期理解 期間={rec.get('period', '')}]"]
    summary = (rec.get("summary_text") or "").strip()
    if summary:
        parts.append(summary)
    for label, key in (
        ("継続トピック", "recurring_topics"),
        ("新規関心", "emerging"),
        ("減退話題", "declining"),
        ("変化", "shifts"),
    ):
        v = rec.get(key)
        if isinstance(v, list) and v:
            parts.append(f"・{label}: " + "、".join(str(x) for x in v))
    return "\n".join(parts)


def _format_short(records: list, max_items: int = 5) -> str:
    if not records:
        return ""
    # 最新優先で max_items 件
    sorted_rs = sorted(records, key=lambda r: r.get("create_date", ""), reverse=True)[:max_items]
    parts = ["[ユーザー短期理解(直近セッション要点)]"]
    for r in sorted_rs:
        parts.append(f"・[{r.get('create_date', '')[:10]}][{r.get('topic', '')[:30]}] {r.get('excerpt', '')[:200]}")
    return "\n".join(parts)


def build_memory_items(service_id: str, user_id: str, active_layers: list = None,
                      short_max_items: int = 5) -> tuple:
    """active_layers に沿って memory 形式のアイテムを返す。

    Returns: (memory_items: list, used_ids: list)
    """
    if active_layers is None:
        active_layers = dmus.resolve_active_layers(user_id)
    items = []
    used_ids = []
    if not user_id:
        return items, used_ids

    if "long" in active_layers:
        try:
            long_rec = dmum.get_one("long", {"service_id": service_id, "user_id": user_id})
            if long_rec:
                text = _format_long(long_rec)
                if text:
                    items.append({
                        "role": "user", "type": "user_memory_long",
                        "timestamp": _now_ts(), "token": _approx_tokens(text),
                        "text": text, "vec_text": [], "similarity_prompt": 0,
                        "seq": "_um", "sub_seq": "long",
                    })
                    used_ids.append(f"long:{user_id}")
        except Exception as e:
            logger.warning(f"[user_memory.builder] long失敗: {e}")

    if "mid" in active_layers:
        try:
            mids = dmum.load_all("mid", service_id=service_id, user_id=user_id)
            mids = [m for m in mids if (m.get("active") or "Y") == "Y"]
            mids.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
            if mids:
                mid_rec = mids[0]
                text = _format_mid(mid_rec)
                if text:
                    items.append({
                        "role": "user", "type": "user_memory_mid",
                        "timestamp": _now_ts(), "token": _approx_tokens(text),
                        "text": text, "vec_text": [], "similarity_prompt": 0,
                        "seq": "_um", "sub_seq": "mid",
                    })
                    used_ids.append(f"mid:{mid_rec.get('id')}")
        except Exception as e:
            logger.warning(f"[user_memory.builder] mid失敗: {e}")

    if "short" in active_layers:
        try:
            shorts = dmum.load_all("short", service_id=service_id, user_id=user_id)
            shorts = [s for s in shorts if (s.get("active") or "Y") == "Y"]
            text = _format_short(shorts, max_items=short_max_items)
            if text:
                items.append({
                    "role": "user", "type": "user_memory_short",
                    "timestamp": _now_ts(), "token": _approx_tokens(text),
                    "text": text, "vec_text": [], "similarity_prompt": 0,
                    "seq": "_um", "sub_seq": "short",
                })
                used_ids.append(f"short:{user_id}:n={min(len(shorts), short_max_items)}")
        except Exception as e:
            logger.warning(f"[user_memory.builder] short失敗: {e}")

    return items, used_ids
