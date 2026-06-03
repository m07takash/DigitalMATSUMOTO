"""Compose the user-memory layers into the "About the dialogue partner" context.

Usage flow:
    context_text, used_ids, meta = build_context_text(service_id, user_id, active_layers, query_text=...)
    full_query = context_text + knowledge_context + prompt_template + user_query + ...

context_text is inserted at the head of the prompt (right before the Knowledge block).
The History layer picks relevant records via a hybrid of MeCab tokens, tag match, and timestamp.
"""
import logging
import math
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

PERSONA_TOKEN_LIMIT = int(os.getenv("USER_MEMORY_PERSONA_TOKEN_LIMIT") or "3000")
# History layer: total character cap (the amount included in the context)
HISTORY_MAX_CHARS = int(os.getenv("USER_MEMORY_HISTORY_MAX_CHARS") or "800")
# History layer: score weighting (tag-match ratio vs. time score)
HISTORY_RECENCY_WEIGHT = float(os.getenv("USER_MEMORY_HISTORY_RECENCY_WEIGHT") or "0.3")
# History layer: half-life (days) for the time score. Roughly the age at which the time score halves.
HISTORY_RECENCY_HALF_LIFE_DAYS = float(os.getenv("USER_MEMORY_HISTORY_RECENCY_HALF_LIFE_DAYS") or "30")


# ---------- Plutchik emotion vocabulary with Japanese display labels ----------
_PLUTCHIK_JA = {
    "joy": "喜び", "trust": "信頼", "fear": "恐れ", "surprise": "驚き",
    "sadness": "悲しみ", "disgust": "嫌悪", "anger": "怒り", "anticipation": "期待",
    "love": "愛", "submission": "服従", "awe": "畏怖", "disapproval": "不満",
    "remorse": "後悔", "contempt": "軽蔑", "aggressiveness": "攻撃性", "optimism": "楽観",
}
_BIG5_JA = {
    "openness": "開放性", "conscientiousness": "誠実性", "extraversion": "外向性",
    "agreeableness": "協調性", "neuroticism": "神経症傾向",
}


def _emotion_label(key: str) -> str:
    return _PLUTCHIK_JA.get((key or "").strip().lower(), key)


def _emotions_to_text(emotions) -> str:
    if not isinstance(emotions, list) or not emotions:
        return ""
    labels = [_emotion_label(e) for e in emotions]
    # Dedupe while preserving order
    seen, out = set(), []
    for l in labels:
        if l and l not in seen:
            seen.add(l)
            out.append(l)
    return "、".join(out)


def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def _approx_tokens(text: str) -> int:
    """Rough approximation for mixed Japanese text (~1 token per character)."""
    return len(text or "")


def _format_persona(rec: dict) -> str:
    if not rec:
        return ""
    parts = []
    role = rec.get("role")
    if role:
        parts.append(f"・役割: {role}")

    def _items_to_text(label, items):
        if not isinstance(items, list):
            return None
        # approved/edited are kept verbatim; pending items are suffixed with "(暗定)" (tentative). Only `deleted` is excluded.
        kept = []
        for it in items:
            if not isinstance(it, dict):
                continue
            lbl = (it.get("label") or "").strip()
            if not lbl:
                continue
            st = (it.get("status") or "").strip().lower()
            if st == "deleted":
                continue
            if st == "pending":
                kept.append(f"{lbl}(暫定)")
            else:
                kept.append(lbl)
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

    # Big5: approved/edited are kept verbatim; pending items are suffixed with "(暗定)" (tentative). Only `deleted` is excluded.
    big5 = rec.get("big5") or {}
    if isinstance(big5, dict) and big5:
        big5_parts = []
        for trait_key, ja in _BIG5_JA.items():
            it = big5.get(trait_key) or {}
            if not isinstance(it, dict):
                continue
            st = (it.get("status") or "").strip().lower()
            if st == "deleted":
                continue
            try:
                score = float(it.get("score") or 0.5)
            except (TypeError, ValueError):
                score = 0.5
            suffix = "(暫定)" if st == "pending" else ""
            big5_parts.append(f"{ja}={score:.2f}{suffix}")
        if big5_parts:
            parts.append("・Big5: " + "、".join(big5_parts))

    summary = (rec.get("summary_text") or "").strip()
    if summary:
        parts.append("")
        parts.append(summary)
    text = "## 人物像\n" + "\n".join(parts)
    if len(text) > PERSONA_TOKEN_LIMIT:
        text = text[: PERSONA_TOKEN_LIMIT - 1] + "…"
    return text


def _format_nowaday(rec: dict) -> str:
    if not rec:
        return ""
    period = (rec.get("period") or "").strip()
    header = f"## 最近の傾向（{period}）" if period else "## 最近の傾向"
    parts = [header]
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

    # Emotional tendency (Plutchik): only basic emotions with intensity >= 0.2, sorted descending.
    basic = rec.get("basic_emotions") or {}
    if isinstance(basic, dict) and basic:
        items = []
        for k, v in basic.items():
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f >= 0.2:
                items.append((k, f))
        if items:
            items.sort(key=lambda x: -x[1])
            parts.append("・基本感情: " + "、".join(f"{_emotion_label(k)}({v:.1f})" for k, v in items))

    secondary = rec.get("secondary_emotions") or []
    if isinstance(secondary, list) and secondary:
        labels = [_emotion_label(s) for s in secondary if isinstance(s, str)]
        labels = [l for l in labels if l]
        if labels:
            parts.append("・二次感情: " + "、".join(labels))
    return "\n".join(parts)


def _extract_record_tags(rec: dict) -> list:
    """Return a flattened list of tag terms from axis_tags + emotions (English Plutchik keys + Japanese labels)."""
    tags = rec.get("axis_tags") or {}
    out = []
    if isinstance(tags, dict):
        for axis_vals in tags.values():
            if isinstance(axis_vals, list):
                for t in axis_vals:
                    if isinstance(t, str) and t.strip():
                        out.append(t.strip())
    emotions = rec.get("emotions") or []
    if isinstance(emotions, list):
        for e in emotions:
            if not isinstance(e, str):
                continue
            key = e.strip().lower()
            if not key:
                continue
            out.append(key)
            ja = _PLUTCHIK_JA.get(key)
            if ja:
                out.append(ja)
    return out


# Japanese keyword dictionary used to detect Plutchik emotions in the query text (partial match)
_JA_EMOTION_LOOKUP = {
    "joy": ["喜び", "うれし", "嬉し", "楽し", "ハッピー"],
    "trust": ["信頼", "安心", "頼れ"],
    "fear": ["恐れ", "怖", "不安", "心配"],
    "surprise": ["驚き", "びっくり", "意外"],
    "sadness": ["悲しみ", "悲し", "つら", "辛", "寂し"],
    "disgust": ["嫌悪", "嫌い", "うんざり"],
    "anger": ["怒り", "イライラ", "腹立", "ムカ"],
    "anticipation": ["期待", "楽しみ", "ワクワク"],
    "love": ["愛", "好き", "大好"],
    "submission": ["服従"],
    "awe": ["畏怖", "畏敬"],
    "disapproval": ["不満", "不承知"],
    "remorse": ["後悔"],
    "contempt": ["軽蔑"],
    "aggressiveness": ["攻撃"],
    "optimism": ["楽観"],
}


def _detect_query_emotions(query_text: str) -> set:
    """Estimate Plutchik emotion keys from emotion keywords found in the query text."""
    if not query_text:
        return set()
    text = query_text
    out = set()
    for key, words in _JA_EMOTION_LOOKUP.items():
        if any(w in text for w in words):
            out.add(key)
    return out


_mecab_tagger = None


def _get_mecab():
    global _mecab_tagger
    if _mecab_tagger is None:
        try:
            import MeCab
            _mecab_tagger = MeCab.Tagger()
        except Exception as e:
            logger.warning(f"[user_memory.builder] MeCab init failed: {e}")
            _mecab_tagger = False
    return _mecab_tagger if _mecab_tagger else None


def _tokenize_nouns(text: str) -> set:
    """Extract nouns of length >= 2 from text. Returns an empty set when MeCab fails."""
    if not text:
        return set()
    tagger = _get_mecab()
    if tagger is None:
        return set()
    nouns = set()
    try:
        parsed = tagger.parse(text)
        for line in parsed.split("\n"):
            if line in ("EOS", ""):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            word = parts[0]
            feat = parts[1] if len(parts) > 1 else ""
            if "名詞" in feat and len(word) >= 2:  # MeCab tag for "noun" -- keep in Japanese
                nouns.add(word.lower())
    except Exception as e:
        logger.warning(f"[user_memory.builder] MeCab parsing failed: {e}")
    return nouns


def _select_histories_by_tags_and_recency(records: list, query_text: str, max_chars: int) -> tuple:
    """Sort by axis_tags-based tag match x timestamp decay, then truncate by total characters.

    Falls back to recency-only when query_text is empty.
    Returns: (selected_records: list, query_keywords: list)
    """
    if not records:
        return [], []
    now = datetime.now()
    half_life = max(HISTORY_RECENCY_HALF_LIFE_DAYS, 1.0)

    # 1. Extract nouns from the user input (MeCab) + detect emotion keywords. Match against full tags without splitting.
    query_nouns = _tokenize_nouns(query_text) if query_text else set()
    query_emotions = _detect_query_emotions(query_text) if query_text else set()
    # Mix both the English emotion key and its Japanese translation into the search terms
    query_emotion_words = set()
    for k in query_emotions:
        query_emotion_words.add(k)
        ja = _PLUTCHIK_JA.get(k)
        if ja:
            query_emotion_words.add(ja.lower())
    query_terms = query_nouns | query_emotion_words
    has_query = bool(query_terms)
    query_keywords = sorted(query_terms)

    # 2. Scoring: split records into a matched group and an unmatched group
    matched_group = []
    unmatched_group = []
    for r in records:
        # Time-decay score
        try:
            ts = datetime.fromisoformat(str(r.get("create_date", "")).replace("Z", "").split(".")[0])
            days_old = max(0.0, (now - ts).total_seconds() / 86400.0)
            recency_score = 0.5 ** (days_old / half_life)
        except Exception:
            recency_score = 0.0

        record_tags = _extract_record_tags(r)
        match_count = 0
        match_ratio = 0.0
        if has_query and record_tags:
            # Per-tag match: a tag containing any query term (noun + emotion word) counts as a "matched tag"
            matched_tag_count = 0
            for t in record_tags:
                t_lower = t.lower()
                if any(n in t_lower for n in query_terms):
                    matched_tag_count += 1
            match_count = matched_tag_count
            match_ratio = match_count / len(record_tags)

        if match_count > 0:
            # Matched group: base on match ratio, refined by the time score
            combined = (1 - HISTORY_RECENCY_WEIGHT) * match_ratio + HISTORY_RECENCY_WEIGHT * recency_score
            matched_group.append((combined, r))
        else:
            # Unmatched group: time score only
            unmatched_group.append((recency_score, r))

    matched_group.sort(key=lambda x: -x[0])
    unmatched_group.sort(key=lambda x: -x[0])
    # Prefer the matched group, then fill the remainder from the unmatched group
    ordered = [r for _, r in matched_group] + [r for _, r in unmatched_group]

    # 4. Pack until the character cap is reached
    selected = []
    total_chars = 0
    for r in ordered:
        line = _history_line(r)
        if total_chars + len(line) > max_chars:
            continue
        selected.append(r)
        total_chars += len(line)
    return selected, query_keywords


def _history_line(r: dict) -> str:
    base = f"・[{r.get('create_date', '')[:10]}][{r.get('topic', '')[:30]}] {r.get('excerpt', '')[:200]}"
    emo_text = _emotions_to_text(r.get("emotions") or [])
    if emo_text:
        return base + f"（感情: {emo_text}）"
    return base


def _format_history(records: list, query_text: str = "", max_chars: int = None) -> tuple:
    """Returns: (text: str, query_keywords: list)"""
    if not records:
        return "", []
    if max_chars is None:
        max_chars = HISTORY_MAX_CHARS
    selected, query_keywords = _select_histories_by_tags_and_recency(records, query_text, max_chars)
    if not selected:
        return "", query_keywords
    parts = ["## 直近セッション"]
    for r in selected:
        parts.append(_history_line(r))
    return "\n".join(parts), query_keywords


def build_context_text(service_id: str, user_id: str, active_layers: list = None,
                       query_text: str = "") -> tuple:
    """Return the "About the dialogue partner" context string based on active_layers.

    Args:
        query_text: The user's current input. Used by the History layer's tag-match search.
                    If empty, the History layer falls back to recency-only.

    Returns: (context_text: str, used_ids: list, meta: dict)
      context_text: Text inserted at the head of the prompt (before Knowledge). "" if none.
      used_ids:    Reference IDs for impact logging.
      meta:        Auxiliary info. Example: {"history_keywords": [...]} (query nouns used by the History search).
    """
    if active_layers is None:
        active_layers = dmus.resolve_active_layers(user_id)
    parts = []
    used_ids = []
    meta = {"history_keywords": []}
    if not user_id or not active_layers:
        return "", used_ids, meta

    if "persona" in active_layers:
        try:
            persona_rec = dmum.get_one("persona", {"service_id": service_id, "user_id": user_id})
            if persona_rec:
                text = _format_persona(persona_rec)
                if text:
                    parts.append(text)
                    used_ids.append(f"persona:{user_id}")
        except Exception as e:
            logger.warning(f"[user_memory.builder] persona failed: {e}")

    if "nowaday" in active_layers:
        try:
            nowadays = dmum.load_all("nowaday", service_id=service_id, user_id=user_id)
            nowadays = [m for m in nowadays if (m.get("active") or "Y") == "Y"]
            nowadays.sort(key=lambda r: r.get("generated_at", ""), reverse=True)
            if nowadays:
                nowaday_rec = nowadays[0]
                text = _format_nowaday(nowaday_rec)
                if text:
                    parts.append(text)
                    used_ids.append(f"nowaday:{nowaday_rec.get('id')}")
        except Exception as e:
            logger.warning(f"[user_memory.builder] nowaday failed: {e}")

    if "history" in active_layers:
        try:
            histories = dmum.load_all("history", service_id=service_id, user_id=user_id)
            histories = [s for s in histories if (s.get("active") or "Y") == "Y"]
            text, history_keywords = _format_history(histories, query_text=query_text)
            meta["history_keywords"] = list(history_keywords) if history_keywords else []
            if text:
                parts.append(text)
                used_count = max(0, text.count("\n") - 0)
                used_ids.append(f"history:{user_id}:n={used_count}")
        except Exception as e:
            logger.warning(f"[user_memory.builder] history failed: {e}")

    if not parts:
        return "", used_ids, meta

    body = "\n\n".join(parts)
    context_text = (
        "# 対話相手について\n"
        "応答時の口調・関心・避けたい話題の参考にしてください。\n\n"
        f"{body}\n\n"
    )
    return context_text, used_ids, meta
