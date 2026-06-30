"""Personal Evaluation plugin.

Reads a workbook with two sheets:
  - `Category`     — 7 theory rows (`カテゴリー / 評価項目 / 理論 / 分析方法`)
  - `PersonalTest` — Q/A rows (`No / Category / Question Style / Question /
                                Memory No / Memo / Answer / Ground Truth /
                                Compare`)

For each Category the plugin tries to score the answers along the per-row
`Memo` axis (Big Five / Schwartz / SDT / Attachment), and renders a radar
chart + score table + raw narratives. The 3 narrative-only categories
(Goals / Narrative Identity / Social Identity) are rendered as text and
left for the optional LLM evaluation step to interpret.

`Memo` parsing notes:
  - "神経症傾向の逆（Emotional Stability）" → axis="神経症傾向", reverse=True
    (a high score on Emotional Stability means LOW neuroticism, so we flip
    the contribution at scoring time so the chart consistently reads
    "high = strong neuroticism" axis-side).
  - parentheticals are stripped from axis labels for chart readability.

Answer-to-score heuristics (Big Five style):
  - "はい" / "Yes"           → 1.0
  - "どちらでもない" / "中"   → 0.5
  - "いいえ" / "No"          → 0.0
  - bare number 1-5          → (n-1)/4
  - bare number 1-7          → (n-1)/6
  - everything else          → unscored (still kept for narrative view)
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path as _Path
from typing import Any

import pandas as pd


# Plugin folder — used to resolve the template Excel relative to *this* file
# so the path is correct regardless of where Streamlit was launched from.
_PLUGIN_DIR = _Path(__file__).resolve().parent


# Answer keyword → score (0.0 to 1.0)
_KEYWORD_SCORE = [
    # Order matters: prefer longest phrases first
    (("どちらでもない",), 0.5),
    (("はい", "yes", "Yes", "YES"), 1.0),
    (("いいえ", "no ", "No", "NO", "いえ"), 0.0),
    (("そう思う", "Agree", "agree"), 1.0),
    (("そう思わない", "Disagree", "disagree"), 0.0),
    (("中立", "Neutral", "neutral"), 0.5),
    (("非常に当てはまる", "Strongly Agree"), 1.0),
    (("全く当てはまらない", "Strongly Disagree"), 0.0),
]


# --------------------------------------------------------------------------
# Plugin contract
# --------------------------------------------------------------------------

class Plugin:
    name         = "PersonalEvaluation"
    display_name = "Personal Evaluation (人格評価スイート)"
    description  = (
        "Big Five / Schwartz Value Theory / Self-Determination / Personal "
        "Strivings / Narrative Identity / Social Identity / Attachment の "
        "7理論に基づく人格評価。`PersonalTest` シートに Answer 入りの xlsx "
        "を渡すと、Category シートの理論ごとに採点・レーダーチャート・"
        "ナラティブで結果を出力します。"
    )

    @staticmethod
    def sample_path() -> str:
        # Template lives alongside main.py so the plugin folder is self-
        # contained. Returned as a string for st.download_button consumers.
        return str(_PLUGIN_DIR / "PersonalTestQA.xlsx")

    @staticmethod
    def run(input_path: str) -> dict[str, Any]:
        # PersonalTest sheet is the only required one — scoring works off of
        # its `Category` + `Memo` columns alone. The Category sheet is purely
        # for label / theory metadata and is optional.
        try:
            df_qa = pd.read_excel(input_path, sheet_name="PersonalTest")
        except Exception as e:
            return {"error": f"Failed to read PersonalTest sheet: {e}"}
        try:
            df_cat = pd.read_excel(input_path, sheet_name="Category")
        except Exception:
            df_cat = pd.DataFrame()  # missing Category sheet is fine

        # Category meta lookup (empty dict when Category sheet is absent)
        cat_meta = _build_category_meta(df_cat) if not df_cat.empty else {}
        # Group QA by category, in the order they first appear
        categories: dict[str, dict] = {}
        cat_order: list[str] = []
        for _, row in df_qa.iterrows():
            cat = _norm(row.get("Category"))
            if not cat:
                continue
            if cat not in categories:
                categories[cat] = {"rows": []}
                cat_order.append(cat)
            categories[cat]["rows"].append(row.to_dict())

        # Per-category analysis
        for cat in cat_order:
            categories[cat]["meta"] = cat_meta.get(cat, {})
            categories[cat].update(_analyze_category(cat, categories[cat]["rows"]))

        return {
            "input_path":  input_path,
            "row_count":   int(len(df_qa)),
            "category_order": cat_order,
            "categories":  categories,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    @staticmethod
    def render(result: dict[str, Any]) -> None:
        import streamlit as st
        if "error" in result:
            st.error(result["error"])
            return
        st.caption(
            f"Total questions: **{result['row_count']}**  /  "
            f"Categories: **{len(result.get('category_order', []))}**  /  "
            f"Generated: {result.get('generated_at', '')}"
        )
        # Top-level cross-category summary (renders before the per-category
        # deep dives so the reader gets the high-level picture first).
        _render_summary(result)
        _render_section_llm_button("サマリー", "\n".join(_summary_md(result)))
        st.markdown("---")
        for cat in result.get("category_order", []):
            data = result["categories"][cat]
            _render_category(cat, data)
            _render_section_llm_button(cat, _category_to_md(cat, data))
            st.markdown("---")

    @staticmethod
    def report_md(result: dict[str, Any]) -> str:
        if "error" in result:
            return f"# Personal Evaluation\n\nError: {result['error']}\n"
        lines = [
            "# Personal Evaluation Report",
            "",
            f"- **Generated**: {result.get('generated_at','')}",
            f"- **Total questions**: {result['row_count']}",
            f"- **Categories**: {len(result.get('category_order', []))}",
        ]
        lines.extend(_summary_md(result))
        lines.append("")
        for cat in result.get("category_order", []):
            lines.append(f"## {cat}")
            lines.append(_category_to_md(cat, result["categories"][cat]))
            lines.append("")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------

def _norm(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and pd.isna(x):
        return ""
    return str(x).strip()


def _build_category_meta(df_cat: pd.DataFrame) -> dict[str, dict]:
    """Index the Category sheet by the short header (e.g. '特性')."""
    out: dict[str, dict] = {}
    for _, row in df_cat.iterrows():
        header = _norm(row.get("カテゴリー"))
        if not header:
            continue
        # "特性 (Traits)\n「どんな人か？」" → "特性"
        short = re.split(r"[\s(\n（]", header, maxsplit=1)[0]
        out[short] = {
            "header":  header,
            "items":   _norm(row.get("評価項目")),
            "theory":  _norm(row.get("理論")),
            "method":  _norm(row.get("分析方法")),
        }
    return out


def _parse_axis(memo: str) -> tuple[str, bool]:
    """`Memo` cell → (axis_label, reverse_flag).

    Examples:
      "外向性（Extraversion）"           → ("Extraversion",  False)
      "神経症傾向の逆（Emotional Stability）" → ("神経症傾向", True)
      "BPMSFS：自律性・充足（Autonomy Sat...）" → ("自律性・充足", False)
    """
    if not memo:
        return ("", False)
    m = memo.strip()
    reverse = "逆" in m
    # Drop reverse marker
    m = re.sub(r"の逆", "", m)
    # Prefer the English label inside parentheses (Big Five / SDT-friendly)
    paren = re.search(r"（([^）]+)）|\(([^)]+)\)", m)
    if paren:
        return (paren.group(1) or paren.group(2), reverse)
    # Drop the "BPMSFS：" / "MWMS：" prefix if any
    m = re.sub(r"^[A-Z]+\s*[:：]\s*", "", m).strip()
    return (m, reverse)


# --------------------------------------------------------------------------
# Narrative similarity (used for 目標 / 人格形成 / 社会性 / 愛着 — categories
# where Answer and Ground Truth are long free-form text, not Likert items).
# --------------------------------------------------------------------------

# Categories that should be rendered as narrative comparisons rather than
# scored radar charts. Keyed on the Category column value.
_NARRATIVE_CATEGORIES = {"目標", "人格形成", "社会性", "愛着"}

# Dimensional structure (for the per-axis similarity radar) — applies only
# to the categories where Memo names a stable dimension.
_NARRATIVE_DIM_ORDER = {
    "社会性": [
        "グループの設定",
        "中心性(Centrality)",
        "連帯感(Solidarity)",
        "満足感(Satisfaction)",
        "自己カテゴリー化(Self-stereotyping)",
        "集団との類似性(In-group homogeneity)",
    ],
    "愛着": [
        "回避(Avoidance)",
        "不安(Anxiety)",
        "信頼(Trust)",
        "自尊(Worth)",
        "いたわり(Caregiving)",
        "喪失(Loss)",
    ],
}


def _tokenize(text: str) -> list[str]:
    """Tokenise a string for content-level overlap scoring.
    Words for Latin runs, single characters for CJK — same convention used
    by `dmt.eval_answer_vs_groundtruth`."""
    if not text:
        return []
    s = re.sub(r"\s+", " ", text).strip().lower()
    out: list[str] = []
    word = ""
    for ch in s:
        if ("a" <= ch <= "z") or ("0" <= ch <= "9") or ch in "_-":
            word += ch
        else:
            if word:
                out.append(word); word = ""
            if ch.strip():
                out.append(ch)  # CJK char or other punctuation
    if word:
        out.append(word)
    return out


def _similarity(a: str, b: str) -> dict[str, float | int]:
    """Compute A↔B similarity metrics: SequenceMatcher ratio + token F1 +
    raw lengths. All values clamp into [0,1] where applicable."""
    import difflib
    if not a and not b:
        return {"seq": 1.0, "f1": 1.0, "len_a": 0, "len_b": 0}
    if not a or not b:
        return {"seq": 0.0, "f1": 0.0, "len_a": len(a), "len_b": len(b)}
    seq = round(difflib.SequenceMatcher(None, a, b).ratio(), 3)
    ta, tb = _tokenize(a), _tokenize(b)
    from collections import Counter
    ca, cb = Counter(ta), Counter(tb)
    overlap = sum((ca & cb).values())
    if not overlap:
        f1 = 0.0
    else:
        prec = overlap / sum(ca.values())
        rec  = overlap / sum(cb.values())
        f1 = round(2 * prec * rec / (prec + rec), 3)
    return {"seq": seq, "f1": f1, "len_a": len(a), "len_b": len(b)}


def _analyze_narrative(cat: str, rows: list[dict]) -> dict:
    """Build per-row + per-dimension similarity stats for narrative categories.

    Per-row record:
      no, memo, axis, question, answer, ground_truth, seq, f1, len_a, len_b
    Per-dimension aggregate (社会性 / 愛着 only):
      {axis: {"seq": mean, "f1": mean, "n": count}}
    """
    items: list[dict] = []
    for r in rows:
        memo = _norm(_get_cell(r, "Memo", "メモ", "MEMO"))
        answer = _norm(_get_cell(r, "Answer", "回答", "ANSWER"))
        gt = _norm(_get_cell(r, "Ground Truth", "GroundTruth", "GT"))
        question = _norm(_get_cell(r, "Question", "質問"))
        no = _norm(_get_cell(r, "No", "no", "番号"))
        sim = _similarity(answer, gt)
        items.append({
            "no": no, "memo": memo, "axis": memo,
            "question": question, "answer": answer, "ground_truth": gt,
            "seq": sim["seq"], "f1": sim["f1"],
            "len_a": sim["len_a"], "len_b": sim["len_b"],
        })

    # Per-dimension aggregate using the Memo as axis label.
    dim_agg: dict[str, dict[str, float | int]] = {}
    for it in items:
        if not it["answer"] or not it["ground_truth"]:
            continue
        ax = it["axis"] or "(unmapped)"
        d = dim_agg.setdefault(ax, {"_seq": [], "_f1": [], "n": 0})
        d["_seq"].append(it["seq"]); d["_f1"].append(it["f1"]); d["n"] += 1
    for ax, d in dim_agg.items():
        d["seq"] = round(sum(d["_seq"]) / len(d["_seq"]), 3) if d["_seq"] else 0.0
        d["f1"]  = round(sum(d["_f1"])  / len(d["_f1"]),  3) if d["_f1"]  else 0.0
        d.pop("_seq"); d.pop("_f1")

    # Overall mean (rows with both A and GT present).
    pairs = [it for it in items if it["answer"] and it["ground_truth"]]
    overall_seq = round(sum(it["seq"] for it in pairs) / len(pairs), 3) if pairs else 0.0
    overall_f1  = round(sum(it["f1"]  for it in pairs) / len(pairs), 3) if pairs else 0.0

    # Narrative categories don't fit the axes_avg shape; keep empty so the
    # default "no axes" diagnostic doesn't fire for them (the renderer
    # dispatches by category before that branch).
    return {
        "narratives":     [{
            "no": it["no"], "axis": it["axis"], "memo": it["memo"],
            "reverse": False, "question_style": "",
            "question": it["question"], "answer": it["answer"],
            "ground_truth": it["ground_truth"],
        } for it in items],
        "narrative_items": items,
        "dim_agg":         dim_agg,
        "axes_avg":        {},
        "axes_avg_gt":     {},
        "scored":          sum(1 for it in items if it["answer"]),
        "scored_gt":       sum(1 for it in items if it["ground_truth"]),
        "unscored":        sum(1 for it in items if not it["answer"]),
        "narrative_overall_seq": overall_seq,
        "narrative_overall_f1":  overall_f1,
        "narrative_pairs":       len(pairs),
    }


def _score_answer(answer: Any) -> float | None:
    """Heuristic 0.0–1.0 score from an Answer cell, or None when unscorable.

    Tries, in order:
      1. Keyword scan (はい / いいえ / どちらでもない / Agree / Disagree / ...)
      2. Bare number alone: `^\\s*([1-7])\\s*$`
      3. Narrative-with-Likert: head-of-string patterns like `4かな`, `7、まったく`,
         `「2」くらい`, `評価は「6」` (matches the Matsumoto-style answers).

    Numeric Likert normalization is **proportional**: `n / 7` (NOT the older
    `(n - 1) / (max - 1)`).
      - All numeric Likert use in this plugin is MWMS / BPNSFS — both 1–7.
        Defaulting to 1–7 also fixes the previous heuristic bug where small
        values (e.g. 4) got over-scored by being treated as a 1–5 scale.
      - `n / 7` keeps the smallest valid response (1) at ~0.14 instead of 0,
        so the radar stays informative when every item is answered 1
        (a respondent who genuinely "doesn't agree with anything"
        shouldn't render visually identical to "didn't answer at all").
      - The radar midpoint of 4 lands at 4/7 ≈ 0.57 instead of exactly 0.5,
        a small skew we accept in exchange for a visible floor.
    """
    if answer is None:
        return None
    a = _norm(answer)
    if not a:
        return None
    # 1. Keyword scan
    for keys, score in _KEYWORD_SCORE:
        for k in keys:
            if k in a:
                return score
    # 2. Bare number
    m = re.match(r"^\s*([1-7])\s*$", a)
    if m:
        n = int(m.group(1))
        return n / 7.0
    # 3. Narrative-with-Likert (head-of-string only — avoids picking up
    #    incidental digits later in the text). Looks at the first 80 chars.
    head = a[:80]
    # 3a. Bracketed digit anywhere in the head: 「N」 / [N] / (N)
    m = re.search(r"[「『\[\(（]\s*([1-7])\s*[」』\]\)）]", head)
    if m:
        n = int(m.group(1))
        return n / 7.0
    # 3b. Leading digit with Japanese particle/punct: "4かな", "7、", "2."
    m = re.match(r"\s*([1-7])\s*[、。,.\sかなだですよねぐらいくら]", head)
    if m:
        n = int(m.group(1))
        return n / 7.0
    # 3c. Anywhere phrase like "評価(は|を)「N」" / "Nくらい" / "Nに近い"
    m = re.search(r"([1-7])\s*(?:くらい|に近い|前後|程度|あたり)", head)
    if m:
        n = int(m.group(1))
        return n / 7.0
    return None


def _get_cell(row: dict, *names: str) -> Any:
    """Lenient cell lookup — accepts a few spelling/casing variants per slot
    so user-edited Excel files with `メモ` / `回答` / `MemoryNo` etc. still
    feed the scorer correctly."""
    for n in names:
        if n in row and not (isinstance(row[n], float) and pd.isna(row[n])):
            return row[n]
    # Case-insensitive / whitespace-insensitive fallback
    norm_keys = {str(k).strip().lower(): k for k in row.keys()}
    for n in names:
        k = norm_keys.get(n.strip().lower())
        if k is not None:
            v = row[k]
            if not (isinstance(v, float) and pd.isna(v)):
                return v
    return None


def _analyze_category(cat: str, rows: list[dict]) -> dict:
    # Per-category dispatch:
    #   - 価値観 / 動機 need axis-construction logic the default can't express
    #     (Schwartz "A vs B" splits, BPNSFS Satisfaction+Frustration→net pairing)
    #   - 目標 / 人格形成 / 社会性 / 愛着 are long free-form narratives where
    #     the comparison metric is A↔GT similarity, not a Likert axis score.
    #   - Everything else (i.e. 特性) uses the default Likert path with the
    #     GT-parallel scoring track.
    if cat == "価値観":
        return _analyze_values(rows)
    if cat == "動機":
        return _analyze_motivation(rows)
    if cat in _NARRATIVE_CATEGORIES:
        return _analyze_narrative(cat, rows)
    return _analyze_default(rows)


def _analyze_default(rows: list[dict]) -> dict:
    """Single-axis-per-row scoring. Also computes a parallel GT track so the
    renderer can overlay Answer/GT on the same radar."""
    axes_raw: dict[str, list[float]] = {}
    axes_raw_gt: dict[str, list[float]] = {}
    narratives: list[dict] = []
    scored = unscored = scored_gt = 0
    for r in rows:
        memo = _norm(_get_cell(r, "Memo", "メモ", "MEMO"))
        answer = _norm(_get_cell(r, "Answer", "回答", "ANSWER"))
        gt = _norm(_get_cell(r, "Ground Truth", "GroundTruth", "GT"))
        question = _norm(_get_cell(r, "Question", "質問"))
        question_style = _norm(_get_cell(r, "Question Style", "QuestionStyle"))
        no = _norm(_get_cell(r, "No", "no", "番号"))
        axis, reverse = _parse_axis(memo)

        score = _score_answer(answer)
        if score is not None and axis:
            adj = (1.0 - score) if reverse else score
            axes_raw.setdefault(axis, []).append(adj)
            scored += 1
        elif answer:
            unscored += 1

        gt_score = _score_answer(gt)
        if gt_score is not None and axis:
            adj_gt = (1.0 - gt_score) if reverse else gt_score
            axes_raw_gt.setdefault(axis, []).append(adj_gt)
            scored_gt += 1

        narratives.append({
            "no": no, "axis": axis, "memo": memo, "reverse": reverse,
            "question_style": question_style, "question": question,
            "answer": answer, "ground_truth": gt,
        })

    axes_avg    = {k: round(sum(v) / len(v), 3) for k, v in axes_raw.items() if v}
    axes_avg_gt = {k: round(sum(v) / len(v), 3) for k, v in axes_raw_gt.items() if v}

    return {
        "axes_avg":     axes_avg,
        "axes_avg_gt":  axes_avg_gt,
        "axes_raw":     axes_raw,
        "axes_raw_gt":  axes_raw_gt,
        "narratives":   narratives,
        "scored":       scored,
        "scored_gt":    scored_gt,
        "unscored":     unscored,
    }


# Schwartz 10 values — canonical English label → JP label (for axis ticks).
_SCHWARTZ_10 = [
    "Self-Direction", "Stimulation", "Hedonism", "Achievement", "Power",
    "Security", "Conformity", "Tradition", "Benevolence", "Universalism",
]
_SCHWARTZ_JP = {
    "Self-Direction": "自律", "Stimulation": "刺激", "Hedonism": "快楽",
    "Achievement": "達成", "Power": "権力", "Security": "安全",
    "Conformity": "順応", "Tradition": "伝統", "Benevolence": "博愛",
    "Universalism": "普遍主義",
}
# Higher-order groups (variance-pair structure).
_SCHWARTZ_GROUPS = [
    ("変化への開放 (Openness to change)",
     ["Self-Direction", "Stimulation"],
     "新しい経験・自律性・刺激を志向。独立心や探究心が高い人の特徴。"),
    ("自己増進 (Self-enhancement)",
     ["Hedonism", "Achievement", "Power"],
     "個人的成功・快楽・影響力を志向。野心的で成果や地位を重視する傾向。"),
    ("保存 (Conservation)",
     ["Security", "Conformity", "Tradition"],
     "秩序・安全・既存の習慣を志向。安定や規範を大切にする傾向。"),
    ("自己超越 (Self-transcendence)",
     ["Benevolence", "Universalism"],
     "他者・社会・自然への配慮を志向。利他的で公平性や調和を重視。"),
]


def _parse_value_pair(memo: str) -> tuple[str, str] | None:
    """Parse a Schwartz "A（jp）vs B（jp）" memo → (A_english, B_english).

    Whitespace around `vs` is optional — the template ships without a leading
    space (`）vs Conformity` rather than `） vs Conformity`).
    """
    if not memo:
        return None
    parts = re.split(r"\s*vs\s*", memo, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None
    a, b = parts
    # Strip the Japanese paren label: "Self-Direction（自律）" → "Self-Direction"
    a = re.sub(r"[（(].*$", "", a).strip()
    b = re.sub(r"[（(].*$", "", b).strip()
    if a in _SCHWARTZ_10 and b in _SCHWARTZ_10:
        return (a, b)
    return None


def _analyze_values(rows: list[dict]) -> dict:
    """Schwartz 10 values — each "A vs B" row contributes `score` to A and
    `(1 - score)` to B. Same for Ground Truth."""
    axes_raw    = {v: [] for v in _SCHWARTZ_10}
    axes_raw_gt = {v: [] for v in _SCHWARTZ_10}
    narratives: list[dict] = []
    scored = unscored = scored_gt = 0
    for r in rows:
        memo = _norm(_get_cell(r, "Memo", "メモ", "MEMO"))
        answer = _norm(_get_cell(r, "Answer", "回答", "ANSWER"))
        gt = _norm(_get_cell(r, "Ground Truth", "GroundTruth", "GT"))
        question = _norm(_get_cell(r, "Question", "質問"))
        question_style = _norm(_get_cell(r, "Question Style", "QuestionStyle"))
        no = _norm(_get_cell(r, "No", "no", "番号"))
        pair = _parse_value_pair(memo)
        axis_label = f"{pair[0]} vs {pair[1]}" if pair else ""

        score = _score_answer(answer)
        if score is not None and pair:
            axes_raw[pair[0]].append(score)
            axes_raw[pair[1]].append(1.0 - score)
            scored += 1
        elif answer:
            unscored += 1

        gt_score = _score_answer(gt)
        if gt_score is not None and pair:
            axes_raw_gt[pair[0]].append(gt_score)
            axes_raw_gt[pair[1]].append(1.0 - gt_score)
            scored_gt += 1

        narratives.append({
            "no": no, "axis": axis_label, "memo": memo, "reverse": False,
            "question_style": question_style, "question": question,
            "answer": answer, "ground_truth": gt,
        })

    axes_avg    = {k: round(sum(v) / len(v), 3) for k, v in axes_raw.items() if v}
    axes_avg_gt = {k: round(sum(v) / len(v), 3) for k, v in axes_raw_gt.items() if v}
    return {
        "axes_avg":      axes_avg,
        "axes_avg_gt":   axes_avg_gt,
        "narratives":    narratives,
        "scored":        scored,
        "scored_gt":     scored_gt,
        "unscored":      unscored,
        "_axis_order":   _SCHWARTZ_10,
    }


# BPNSFS net dimensions — Satisfaction direct, Frustration reverse-coded
# (high frustration → low net score).
_BPNSFS_AXES = ["Autonomy", "Competence", "Relatedness"]
# MWMS subscales.
_MWMS_AXES = ["IM", "INTEG", "IDEN", "INTRO", "EXT", "AMO"]
_MWMS_JP = {
    "IM": "内発的動機づけ", "INTEG": "統合的調整", "IDEN": "同一化的調整",
    "INTRO": "取り入れ的調整", "EXT": "外的調整", "AMO": "無動機",
}


def _motivation_bucket(memo: str) -> tuple[str, str, bool] | None:
    """Classify a Motivation memo into (group, axis_label, reverse_flag).

    Returns:
        ("BPNSFS", "Autonomy" | "Competence" | "Relatedness", reverse_for_frustration)
        ("MWMS",   "IM" | "INTEG" | "IDEN" | "INTRO" | "EXT" | "AMO", False)
        None if not classifiable.
    """
    if not memo:
        return None
    m = memo.strip()
    if m.startswith(("BPNSFS", "BPMSFS")):  # tolerate the typo in the template
        # Examples: "BPNSFS：自律性・充足（Autonomy Satisfaction）"
        #           "BPMSFS：関係性・不満（Relatedness Frustration）"
        is_frus = "不満" in m or "Frustration" in m.lower() or "frustration" in m
        if "Autonomy" in m or "自律" in m:
            return ("BPNSFS", "Autonomy", is_frus)
        if "Competence" in m or "有能" in m:
            return ("BPNSFS", "Competence", is_frus)
        if "Relatedness" in m or "関係" in m:
            return ("BPNSFS", "Relatedness", is_frus)
        return None
    if m.startswith("MWMS"):
        for code in _MWMS_AXES:
            if f"（{code}）" in m or f"({code})" in m:
                return ("MWMS", code, False)
    return None


def _analyze_motivation(rows: list[dict]) -> dict:
    """SDT-style motivation analysis: BPNSFS (3 net axes) + MWMS (6 axes).
    Frustration items reverse-contribute to BPNSFS net scores."""
    bpnsfs_raw    = {a: [] for a in _BPNSFS_AXES}
    bpnsfs_raw_gt = {a: [] for a in _BPNSFS_AXES}
    mwms_raw      = {a: [] for a in _MWMS_AXES}
    mwms_raw_gt   = {a: [] for a in _MWMS_AXES}
    narratives: list[dict] = []
    scored = unscored = scored_gt = 0
    for r in rows:
        memo = _norm(_get_cell(r, "Memo", "メモ", "MEMO"))
        answer = _norm(_get_cell(r, "Answer", "回答", "ANSWER"))
        gt = _norm(_get_cell(r, "Ground Truth", "GroundTruth", "GT"))
        question = _norm(_get_cell(r, "Question", "質問"))
        question_style = _norm(_get_cell(r, "Question Style", "QuestionStyle"))
        no = _norm(_get_cell(r, "No", "no", "番号"))
        bucket = _motivation_bucket(memo)
        axis_label = bucket[1] if bucket else ""

        score = _score_answer(answer)
        if score is not None and bucket:
            grp, axis, rev = bucket
            adj = (1.0 - score) if rev else score
            (bpnsfs_raw if grp == "BPNSFS" else mwms_raw)[axis].append(adj)
            scored += 1
        elif answer:
            unscored += 1

        gt_score = _score_answer(gt)
        if gt_score is not None and bucket:
            grp, axis, rev = bucket
            adj_gt = (1.0 - gt_score) if rev else gt_score
            (bpnsfs_raw_gt if grp == "BPNSFS" else mwms_raw_gt)[axis].append(adj_gt)
            scored_gt += 1

        narratives.append({
            "no": no, "axis": axis_label, "memo": memo, "reverse": False,
            "question_style": question_style, "question": question,
            "answer": answer, "ground_truth": gt,
        })

    def _avg(d):
        return {k: round(sum(v) / len(v), 3) for k, v in d.items() if v}
    return {
        # Flat fields keep `axes_avg` populated so the diagnostic fallback in
        # `_render_category` doesn't fire for narrative-rich-but-no-axes runs.
        "axes_avg":      {**_avg(bpnsfs_raw), **{f"MWMS_{k}": v for k, v in _avg(mwms_raw).items()}},
        "axes_avg_gt":   {**_avg(bpnsfs_raw_gt), **{f"MWMS_{k}": v for k, v in _avg(mwms_raw_gt).items()}},
        "bpnsfs_avg":    _avg(bpnsfs_raw),
        "bpnsfs_avg_gt": _avg(bpnsfs_raw_gt),
        "mwms_avg":      _avg(mwms_raw),
        "mwms_avg_gt":   _avg(mwms_raw_gt),
        "narratives":    narratives,
        "scored":        scored,
        "scored_gt":     scored_gt,
        "unscored":      unscored,
    }


def _radar(labels: list[str], values: list[float], title: str,
            values_gt: list[float] | None = None):
    """Polar radar chart (returns the matplotlib Figure).

    When `values_gt` is provided and non-empty, overlays a second layer in
    green (Ground Truth) on top of the Answer-in-blue base. Both layers are
    aligned to the same `labels`; pass `0.0` for a missing axis on either
    side to keep them indexed.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from math import pi
    if not labels or not values:
        return None
    n = len(labels)
    angles = [i / n * 2 * pi for i in range(n)]
    angles += angles[:1]

    fig = plt.figure(figsize=(5.0, 5.0))
    ax = plt.subplot(111, polar=True)
    ax.set_theta_offset(pi / 2)
    ax.set_theta_direction(-1)
    plt.xticks(angles[:-1], labels, fontfamily="IPAexGothic", fontsize=8.5)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75])
    ax.set_yticklabels(["0.25", "0.50", "0.75"], fontsize=7)

    # Answer = blue base layer
    vv = list(values) + [values[0]]
    ax.plot(angles, vv, linewidth=1.6, color="#1565C0", label="Answer(AI)")
    ax.fill(angles, vv, alpha=0.22, color="#1565C0")

    # Ground Truth = green overlay (drawn second so it sits on top)
    if values_gt and any(v > 0 for v in values_gt):
        vg = list(values_gt) + [values_gt[0]]
        ax.plot(angles, vg, linewidth=1.6, color="#2E7D32", linestyle="-", label="Ground Truth")
        ax.fill(angles, vg, alpha=0.18, color="#2E7D32")
        ax.legend(loc="upper right", bbox_to_anchor=(1.30, 1.10), fontsize=8, frameon=False)

    ax.grid(True, alpha=0.4)
    plt.title(title, fontfamily="IPAexGothic", fontsize=11)
    plt.tight_layout()
    return fig


def _score_table(axes: dict, axes_gt: dict, axis_order: list[str] | None = None) -> pd.DataFrame:
    """Compose an Axis / Answer / Ground Truth table.

    Empty GT column is dropped so the existing single-track table still looks
    clean when the user hasn't filled the GT column.
    """
    order = axis_order or list(axes.keys())
    rows = []
    for a in order:
        if a not in axes and a not in (axes_gt or {}):
            continue
        rows.append({
            "Axis": a,
            "Answer(AI)": axes.get(a, 0.0),
            "Ground Truth": (axes_gt or {}).get(a, None),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if df["Ground Truth"].isna().all():
        df = df.drop(columns=["Ground Truth"])
    if axis_order is None and "Ground Truth" not in df.columns:
        df = df.sort_values("Answer(AI)", ascending=False)
    return df


def _render_category(cat: str, data: dict) -> None:
    import streamlit as st
    meta = data.get("meta") or {}
    st.markdown(f"### {cat}")
    if meta.get("theory"):
        st.caption(f"理論: **{meta['theory']}**")
    # 動機 carries a long axis-listing description that the user explicitly
    # asked to hide (BPNSFS / MWMS sub-axis enumeration). The radar + score
    # table below already convey the same info.
    if meta.get("items") and cat != "動機":
        _items = meta["items"]
        if "•" in _items:
            # Bullet-formatted in the Excel — emit each bullet on its own
            # line so the structure is legible (st.caption is single-line).
            _lines = [_l.strip() for _l in _items.split("•") if _l.strip()]
            st.markdown("  \n".join(f"・{_l}" for _l in _lines))
        else:
            st.caption(_items[:300])

    # Category-specific rendering.
    if cat == "価値観":
        _render_values_category(data)
        _render_narratives_expander(data)
        return
    if cat == "動機":
        _render_motivation_category(data)
        _render_narratives_expander(data)
        return
    if cat == "目標":
        # Specialised: LLM-driven structured analysis (Venn + ratings + connectors).
        _render_goals_category(data)
        _render_narratives_expander(data)
        return
    if cat in _NARRATIVE_CATEGORIES:
        # For 人格形成 / 社会性 / 愛着 we run the new LLM-driven scored radar
        # ABOVE the existing similarity diagnostics. The two are complementary:
        #   - LLM scored radar = what each side IS (substantive content)
        #   - Text similarity   = how closely Answer text matches GT text
        if cat in _NARRATIVE_SCORED_AXES:
            _render_narrative_scored_category(cat, data)
        _render_narrative_category(cat, data)
        return

    axes = data.get("axes_avg") or {}
    if axes:
        axes_gt = data.get("axes_avg_gt") or {}
        col1, col2 = st.columns([3, 2])
        if len(axes) >= 3:
            labels = list(axes.keys())
            vals   = [axes[k] for k in labels]
            vals_gt = [axes_gt.get(k, 0.0) for k in labels] if axes_gt else None
            fig = _radar(labels, vals, f"{cat} (n={data['scored']})", values_gt=vals_gt)
            if fig is not None:
                with col1:
                    import streamlit as _st
                    _st.pyplot(fig)
                    import matplotlib.pyplot as _plt
                    _plt.close(fig)
        with col2:
            st.markdown("**Scores (0–1):**")
            st.dataframe(
                _score_table(axes, axes_gt),
                hide_index=True, use_container_width=True,
            )
        _scored_caption = f"scored: **{data['scored']}**  /  unscored: **{data['unscored']}**"
        if data.get("scored_gt"):
            _scored_caption += f"  /  GT scored: **{data['scored_gt']}**"
        st.caption(_scored_caption)
    elif data["narratives"]:
        # No axes were scored. Provide a self-diagnosing hint so the user
        # can tell whether it's `Memo` / `Answer` that's the culprit,
        # rather than seeing an empty section with no explanation.
        n_rows = len(data["narratives"])
        n_with_memo = sum(1 for n in data["narratives"] if n.get("memo"))
        n_with_answer = sum(1 for n in data["narratives"] if n.get("answer"))
        if n_with_memo == 0 and n_with_answer == 0:
            st.info(
                f"narrative-only category — {n_rows} 件 (Memo / Answer どちらも空)。"
                " 採点軸を出すには Memo 列に軸ラベル (例: `外向性（Extraversion）`)、"
                " Answer 列に `はい / どちらでもない / いいえ` を入れてください。"
            )
        elif n_with_memo == 0:
            st.warning(
                f"Memo 列が空のため採点軸が作れません ({n_rows} 件中 Answer 入力 {n_with_answer} 件)。"
                f" 各行の `Memo` 列に軸ラベル (例: `外向性（Extraversion）`) を入れてください。"
            )
        elif n_with_answer == 0:
            st.warning(
                f"Answer 列が全行で空です ({n_rows} 件中 Memo 入力 {n_with_memo} 件)。"
                " 回答を入れて再 Run してください。"
            )
        else:
            st.warning(
                f"採点できる Answer が 1 件もありませんでした"
                f" ({n_rows} 件中 Answer 入力 {n_with_answer} 件 / Memo 入力 {n_with_memo} 件)。"
                " Answer は `はい` / `どちらでもない` / `いいえ` / `Agree` / `Disagree` /"
                " `1`〜`7` のいずれかにしてください。"
                " (narrative-only category の場合は LLM 評価で読み込まれます)"
            )

    _render_narratives_expander(data)


def _render_narratives_expander(data: dict) -> None:
    import streamlit as st
    if not data.get("narratives"):
        return
    with st.expander(f"Answers ({len(data['narratives'])})"):
        for n in data["narratives"]:
            head = f"**[{n['no']}] {n['axis'] or n['memo']}**"
            if n.get("reverse"):
                head += " _(reverse)_"
            st.markdown(head)
            if n["question"]:
                st.markdown(f"- Q: {n['question']}")
            if n["answer"]:
                st.markdown(f"- A: {n['answer']}")
            if n["ground_truth"]:
                st.markdown(f"- GT: {n['ground_truth']}")


# --------------------------------------------------------------------------
# Category-specific renderers
# --------------------------------------------------------------------------

def _render_values_category(data: dict) -> None:
    """Schwartz Values: 10-axis dual-layer radar + 4-group aggregation with
    priority commentary."""
    import streamlit as st
    axes    = data.get("axes_avg") or {}
    axes_gt = data.get("axes_avg_gt") or {}
    if not axes:
        st.info("価値観の Answer がまだ採点できていません。Memo は `Self-Direction（自律）vs Conformity（順応）` の形式で、Answer 列に `はい/どちらでもない/いいえ` を入れてください。")
        return

    # --- 10-axis radar + table ---
    labels = [f"{v}\n({_SCHWARTZ_JP[v]})" for v in _SCHWARTZ_10]
    vals    = [axes.get(v, 0.0) for v in _SCHWARTZ_10]
    vals_gt = [axes_gt.get(v, 0.0) for v in _SCHWARTZ_10] if axes_gt else None
    col1, col2 = st.columns([3, 2])
    fig = _radar(labels, vals, f"価値観 (10値)", values_gt=vals_gt)
    if fig is not None:
        with col1:
            st.pyplot(fig)
            import matplotlib.pyplot as _plt
            _plt.close(fig)
    with col2:
        st.markdown("**10値スコア (Answer(AI) / Ground Truth):**")
        st.dataframe(
            _score_table(axes, axes_gt, axis_order=_SCHWARTZ_10),
            hide_index=True, use_container_width=True,
        )
    _cap = f"scored: **{data['scored']}**  /  unscored: **{data['unscored']}**"
    if data.get("scored_gt"):
        _cap += f"  /  GT scored: **{data['scored_gt']}**"
    st.caption(_cap)

    # --- 4-group aggregation (Schwartz higher-order structure) ---
    # Order is fixed by _SCHWARTZ_GROUPS — NOT sorted by score, so the four
    # groups always appear in the canonical sequence:
    #   変化への開放 → 自己増進 → 保存 → 自己超越
    st.markdown("#### 4グループ集約 (Schwartz 高次構造)")
    groups = []
    for label, members, desc in _SCHWARTZ_GROUPS:
        ms = [axes.get(m, 0.0) for m in members]
        ms_gt = [axes_gt.get(m, 0.0) for m in members] if axes_gt else []
        avg = round(sum(ms) / len(ms), 3)
        avg_gt = round(sum(ms_gt) / len(ms_gt), 3) if ms_gt else None
        groups.append({"label": label, "members": members, "desc": desc,
                        "answer": avg, "gt": avg_gt})

    _gt_col = groups[0].get("gt") is not None
    _df_g = pd.DataFrame([
        {
            "No": i + 1,
            "Group": g["label"],
            "Members": " / ".join(g["members"]),
            "Answer(AI)": g["answer"],
            **({"Ground Truth": g["gt"]} if _gt_col else {}),
        } for i, g in enumerate(groups)
    ])
    st.dataframe(_df_g, hide_index=True, use_container_width=True)

    st.markdown("**各グループの解説:**")
    for i, g in enumerate(groups):
        _delta = ""
        if g["gt"] is not None:
            _diff = g["answer"] - g["gt"]
            if abs(_diff) >= 0.1:
                _delta = f"  *(GT との差: {_diff:+.2f})*"
        st.markdown(
            f"**{i+1}. {g['label']}**  *score={g['answer']:.2f}*{_delta}  \n"
            f"  {g['desc']}"
        )


def _render_motivation_category(data: dict) -> None:
    """SDT-style Motivation: BPNSFS (3 net axes) + MWMS (6 subscales) — two
    side-by-side dual-layer radars."""
    import streamlit as st
    bp    = data.get("bpnsfs_avg") or {}
    bp_gt = data.get("bpnsfs_avg_gt") or {}
    mw    = data.get("mwms_avg") or {}
    mw_gt = data.get("mwms_avg_gt") or {}

    if not bp and not mw:
        st.info("動機の Answer がまだ採点できていません。Memo は `BPNSFS：自律性・充足（Autonomy Satisfaction）` のような形式で、Answer 列に `はい/どちらでもない/いいえ` を入れてください。")
        return

    # --- BPNSFS (3 axes — needs ≥3 for radar to be informative, 3 is OK) ---
    st.markdown("#### 基本的心理欲求 (BPNSFS)")
    c1, c2 = st.columns([3, 2])
    if bp:
        labels = [f"{a}\n({_BPNSFS_JP.get(a, '')})" for a in _BPNSFS_AXES]
        vals    = [bp.get(a, 0.0) for a in _BPNSFS_AXES]
        vals_gt = [bp_gt.get(a, 0.0) for a in _BPNSFS_AXES] if bp_gt else None
        fig = _radar(labels, vals, "BPNSFS", values_gt=vals_gt)
        if fig is not None:
            with c1:
                st.pyplot(fig)
                import matplotlib.pyplot as _plt
                _plt.close(fig)
        with c2:
            st.markdown("**スコア:**")
            st.dataframe(
                _score_table(bp, bp_gt, axis_order=_BPNSFS_AXES),
                hide_index=True, use_container_width=True,
            )
    else:
        st.caption("BPNSFS 軸の採点行がありません。")

    # --- MWMS (6 subscales) ---
    st.markdown("#### 仕事の動機づけ (MWMS)")
    c3, c4 = st.columns([3, 2])
    if mw:
        labels = [f"{a}\n({_MWMS_JP[a]})" for a in _MWMS_AXES]
        vals    = [mw.get(a, 0.0) for a in _MWMS_AXES]
        vals_gt = [mw_gt.get(a, 0.0) for a in _MWMS_AXES] if mw_gt else None
        fig = _radar(labels, vals, "MWMS", values_gt=vals_gt)
        if fig is not None:
            with c3:
                st.pyplot(fig)
                import matplotlib.pyplot as _plt
                _plt.close(fig)
        with c4:
            st.markdown("**スコア:**")
            st.dataframe(
                _score_table(mw, mw_gt, axis_order=_MWMS_AXES),
                hide_index=True, use_container_width=True,
            )
    else:
        st.caption("MWMS 軸の採点行がありません。")

    _cap = f"scored: **{data['scored']}**  /  unscored: **{data['unscored']}**"
    if data.get("scored_gt"):
        _cap += f"  /  GT scored: **{data['scored_gt']}**"
    st.caption(_cap)


# Japanese reading labels for BPNSFS axes (used for radar ticks).
_BPNSFS_JP = {"Autonomy": "自律性", "Competence": "有能感", "Relatedness": "関係性"}


# --------------------------------------------------------------------------
# Narrative-scored categories — LLM-driven radar + similarities/differences
# (人格形成 / 社会性 / 愛着). Each category has a fixed axis list; the LLM
# scores Answer(AI) and Ground Truth on every axis using a 5-step discrete
# rubric and produces a similarities + differences commentary capped at
# ~300 chars each. See `DigiM_Evaluation.llm_extract_narrative_scored`.
# --------------------------------------------------------------------------

_NARRATIVE_SCORED_AXES = {
    "人格形成": [
        ("物語的一貫性", "narrative coherence",
         "エピソード全体が時系列的・因果的に整合し、首尾一貫したストーリーとして語られているか"),
        ("行為主体性 vs 共同性", "agency / communion",
         "自己決定・達成志向 (Agency) と、他者との関係性・親密さ (Communion) の両面が見られるか。両者がバランスよく統合されているほど高得点"),
        ("感情の連鎖", "redemption / contamination",
         "ネガティブな出来事からポジティブな気付き・成長への変容 (Redemption) が描かれているか。逆にポジティブが急にネガティブに反転する (Contamination) パターンは減点要素"),
        ("意味づけ", "autobiographical reasoning / meaning-making",
         "過去の経験から自分の在り方への教訓・洞察を抽出している程度。出来事を解釈・概念化する深さ"),
    ],
    "社会性": [
        ("中心性 (Centrality)", "centrality",
         "そのグループへの所属が自己定義の中心にどれだけ位置するか (自己概念への組み込み度)"),
        ("連帯感 (Solidarity)", "solidarity",
         "グループのメンバーとの感情的な結びつき・絆・愛着の強さ"),
        ("満足感 (Satisfaction)", "satisfaction",
         "そのグループの一員であることへの満足度・誇りの度合い"),
        ("自己カテゴリー化 (Self-stereotyping)", "self-stereotyping",
         "自分をそのグループの典型的・代表的メンバーとして認識する程度"),
        ("集団との類似性 (In-group homogeneity)", "in-group homogeneity",
         "集団内のメンバーが互いに似ていると認識する程度 (内集団の同質性知覚)"),
    ],
    "愛着": [
        ("回避 (Avoidance)", "avoidance",
         "他者との情緒的接近を避け、距離・独立を維持しようとする傾向"),
        ("不安 (Anxiety)", "anxiety",
         "他者からの拒絶・見捨てへの強い不安・過剰な関係依存"),
        ("信頼 (Trust)", "trust",
         "他者の善意・信頼性を肯定的に捉えられる程度"),
        ("自尊 (Worth)", "worth",
         "自分は愛される価値があると感じる程度 (自己受容)"),
        ("いたわり (Caregiving)", "caregiving",
         "他者へのケア・配慮・サポートを能動的に行う傾向"),
        ("喪失 (Loss)", "loss",
         "重要な対象を失った経験への意識・統合度 (喪失体験との折り合い)"),
    ],
}


def _render_narrative_scored_category(cat: str, data: dict) -> None:
    """LLM-driven radar + similarities/differences commentary for narrative
    categories (人格形成 / 社会性 / 愛着).

    Reads `_NARRATIVE_SCORED_AXES[cat]` for the per-category axis list, fires
    the LLM once on click, caches the result under
    `_pe_narr_scored_<plugin>_<cat>` and renders a dual-layer radar
    (Answer(AI) blue / Ground Truth green) + score table + 類似点/相違点 text.
    Called BEFORE the existing similarity bar / text-comparison renderer
    so it sits at the top of the section."""
    import streamlit as st

    axes_config = _NARRATIVE_SCORED_AXES.get(cat) or []
    if not axes_config:
        return

    items: list[dict] = data.get("narrative_items") or []
    if not items:
        return

    _plugin = _PLUGIN_DIR.name
    _key = f"_pe_narr_scored_{_plugin}_{cat}"
    _btn_k = f"btn_pe_narr_scored_{cat}"
    _agent_state_key = f"eval_llm_agent_{_plugin}"

    cols = st.columns([2, 6])
    if cols[0].button(
        f"{cat} を構造化分析する (LLM)",
        key=_btn_k,
        help=f"{cat} を {len(axes_config)} 軸で LLM 採点し、Answer(AI) と Ground Truth を重ねレーダー比較 + 類似点 / 相違点を要約します",
    ):
        _agent_file = st.session_state.get(_agent_state_key)
        if not _agent_file:
            cols[1].warning("先に LLM Evaluation セクションでエージェントを選択してください。")
        else:
            try:
                with st.spinner(f"LLM が {cat} を採点中..."):
                    # Concatenate all per-question Answer / GT into a single
                    # block for the LLM. Memo is included so it can group
                    # by the dimension naming convention used in the Excel.
                    _ans_block = "\n\n".join(
                        f"[{it.get('no','')}] {it.get('memo','')}\n"
                        f"Q: {it.get('question','')}\n"
                        f"A: {it.get('answer','')}"
                        for it in items
                    )
                    _gt_block = "\n\n".join(
                        f"[{it.get('no','')}] {it.get('memo','')}\n"
                        f"Q: {it.get('question','')}\n"
                        f"GT: {it.get('ground_truth','')}"
                        for it in items
                    )
                    import DigiM_Evaluation as _de
                    parsed, _model = _de.llm_extract_narrative_scored(
                        category_name=cat,
                        axes=axes_config,
                        answer_text=_ans_block,
                        gt_text=_gt_block,
                        agent_file=_agent_file,
                        service_info=st.session_state.get("web_service", {}),
                        user_info=st.session_state.get("web_user", {}),
                    )
                    from datetime import datetime as _dt
                    st.session_state[_key] = {
                        "data": parsed, "model": _model, "agent": _agent_file,
                        "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
            except Exception as _e:
                st.error(f"{cat} の構造化分析に失敗しました: {_e}")
                return

    res = st.session_state.get(_key)
    if not res:
        st.caption(
            f"💡 「{cat} を構造化分析する (LLM)」を押すと、{len(axes_config)} 軸の LLM スコアで"
            f" Answer(AI) と Ground Truth を比較する重ねレーダーと、類似点・相違点 (各300字以内) を出力します。"
        )
        return

    d = res.get("data") or {}
    ans_scores = d.get("answer_scores") or {}
    gt_scores  = d.get("gt_scores") or {}

    # ---- Dual-layer radar (Answer blue / GT green) ----
    labels = [a[0] for a in axes_config]
    vals_a  = [float(ans_scores.get(lbl, 0.0)) for lbl in labels]
    vals_gt = [float(gt_scores.get(lbl, 0.0))  for lbl in labels]

    st.markdown(f"#### {cat} — LLM スコアによる重ねレーダー (Answer(AI) ↔ Ground Truth)")
    c1, c2 = st.columns([3, 2])
    if len(labels) >= 3:
        # Wrap long labels — narrative axes have parens with English which
        # otherwise overflow into the chart area.
        _short_labels = [re.split(r"[ \(（]", lbl, maxsplit=1)[0] for lbl in labels]
        fig = _radar(_short_labels, vals_a,
                       f"{cat} (LLM, 5段階離散)", values_gt=vals_gt)
        if fig is not None:
            with c1:
                st.pyplot(fig)
                import matplotlib.pyplot as _plt
                _plt.close(fig)
    with c2:
        st.markdown("**スコア (Answer(AI) / Ground Truth):**")
        _df = pd.DataFrame([
            {"Axis": lbl, "Answer(AI)": vals_a[i], "Ground Truth": vals_gt[i],
             "Δ (A-GT)": round(vals_a[i] - vals_gt[i], 2)}
            for i, lbl in enumerate(labels)
        ])
        st.dataframe(_df, hide_index=True, use_container_width=True)

    # ---- Similarities / Differences (300-char commentary) ----
    sim_text = d.get("similarities", "") or "_(LLM 出力なし)_"
    dif_text = d.get("differences",  "") or "_(LLM 出力なし)_"
    st.markdown("**類似点:**")
    st.markdown(sim_text)
    st.markdown("**相違点:**")
    st.markdown(dif_text)
    st.caption(
        f"Agent: `{res.get('agent','')}`  /  Model: `{res.get('model','')}`  /  "
        f"Generated: {res.get('timestamp','')}"
    )
    st.markdown("---")


# --------------------------------------------------------------------------
# 目標 (Goals) — structured LLM-driven analysis (Venn + ratings + connectors)
# --------------------------------------------------------------------------

# H/M/L → 表示色 (赤 / 緑 / 青) — Streamlit Markdown 用の HTML カラー。
_HML_COLORS = {"H": "#D32F2F", "M": "#2E7D32", "L": "#1565C0"}
_HML_LABEL  = {"H": "High",    "M": "Medium",  "L": "Low"}


def _hml_badge(level: str) -> str:
    """Return an inline-styled HTML badge for a H/M/L rating."""
    lv = (level or "M").upper()
    color = _HML_COLORS.get(lv, "#666")
    label = _HML_LABEL.get(lv, "?")
    return (f'<span style="display:inline-block;padding:0 6px;border-radius:4px;'
            f'background:{color};color:white;font-weight:600;font-size:0.85em;">'
            f'{label}</span>')


def _ratings_inline(d: dict, prefix: str = "") -> str:
    """Render 4-axis ratings as inline colored badges. `prefix` selects between
    the common dict's `answer_*` / `gt_*` slots and the side-only dict's
    bare keys (`importance`, `commitment`, etc.)."""
    keys = [
        ("importance",  "大切さ"),
        ("commitment",  "本気度"),
        ("feasibility", "達成見込"),
        ("achievement", "達成度"),
    ]
    out = []
    for k, ja in keys:
        out.append(f"{ja} {_hml_badge(d.get(prefix + k, 'M'))}")
    return "  ".join(out)


# --- 3-column band geometry --------------------------------------------------
# Replaces the original 2-circle Venn diagram, which couldn't keep many
# overlapping labels readable. The new layout sets three vertical bands
# (Answer(AI) / 共通 / Ground Truth) side-by-side, each carrying its own
# tinted background. Labels stack purely vertically within their column so
# horizontal collisions across columns can never happen.
#
# Both `_render_goals_venn` (kept under the same name for backward compat)
# and `_render_goals_connectors` consume `_venn_positions` and the same
# `_draw_venn_base` background.
_BAND_X      = {"answer": -2.0, "common": 0.0, "gt": +2.0}  # column centres
_BAND_WIDTH  = 1.6                                            # background tint width
_BAND_Y_TOP  = 1.10                                           # vertical extent of bands
_BAND_COLORS = {"answer": "#1565C0", "common": "#555555", "gt": "#2E7D32"}
_BAND_LABELS = {"answer": "Answer(AI)", "common": "共通", "gt": "Ground Truth"}


def _venn_positions(answer_only: list, common: list, gt_only: list) -> dict[str, tuple[float, float]]:
    """Return label → (x, y) layout for every Goals region.

    Three vertical bands at x=-2.0 / 0.0 / +2.0. Within each band labels
    are **scattered** rather than stacked on a rigid grid:

    - Stratified Y: each item gets its own vertical strip in input order,
      so the LLM's importance ordering still reads top-down.
    - Hashed X jitter: each label's horizontal offset is derived from
      MD5(label) — an organic, non-mechanical look that is still
      deterministic (the same goal text always lands at the same spot,
      so re-renders are stable for screenshots / comparison).
    - Hashed Y wobble: a small extra Y offset (capped at 30 % of the
      strip height) breaks the perfectly even spacing without letting
      neighbours collide.

    All offsets are bounded so labels stay safely inside their band
    (band half-width 0.8, label x ∈ cx ± 0.45 → 0.35 clearance).
    """
    pos: dict[str, tuple[float, float]] = {}

    # Hash each label into a deterministic [0,1) offset — gives every goal
    # an organic-looking position that's still reproducible across renders.
    import hashlib
    def _hu(s: str, salt: int) -> float:
        h = hashlib.md5(f"{salt}|{s}".encode("utf-8")).digest()
        return int.from_bytes(h[:4], "big") / float(1 << 32)

    # Half-width of the X scatter. Band is 1.6 wide, so ±0.45 leaves
    # plenty of clearance to band edges even with multi-char labels.
    _X_SCATTER = 0.45

    def _scatter(items: list, cx: float, y_max: float) -> None:
        n = len(items)
        if n == 0:
            return
        if n == 1:
            label = items[0]["label"]
            x = cx + (_hu(label, 0) - 0.5) * (_X_SCATTER * 0.6)
            pos[label] = (x, 0.0)
            return
        # Y-wobble capped at 30 % of one strip's height so adjacent labels
        # never overlap vertically even with maximum jitter.
        strip = (2 * y_max) / (n - 1)
        y_wobble = min(0.12, strip * 0.30)
        for i, it in enumerate(items):
            label = it["label"]
            # Stratified Y: preserve LLM importance order top-down...
            t = i / (n - 1)
            y_base = y_max - t * (2 * y_max)
            # ...add hashed wobble so the stripes don't read as rigid rows.
            y = y_base + (_hu(label, 1) - 0.5) * 2 * y_wobble
            # X is purely hashed — different x per label by design.
            x = cx + (_hu(label, 0) - 0.5) * 2 * _X_SCATTER
            pos[label] = (x, y)

    _scatter(answer_only, cx=_BAND_X["answer"], y_max=_BAND_Y_TOP * 0.92)
    _scatter(common,      cx=_BAND_X["common"], y_max=_BAND_Y_TOP * 0.92)
    _scatter(gt_only,     cx=_BAND_X["gt"],     y_max=_BAND_Y_TOP * 0.92)
    return pos


def _draw_venn_base(ax, title: str = ""):
    """Draw the 3 tinted columns + headers onto `ax`. Replaces the old
    overlapping-circle Venn background. `ax` is returned so callers can
    keep plotting on top."""
    import matplotlib.patches as _patches
    for key, cx in _BAND_X.items():
        color = _BAND_COLORS[key]
        ax.add_patch(_patches.Rectangle(
            (cx - _BAND_WIDTH / 2, -_BAND_Y_TOP),
            _BAND_WIDTH, 2 * _BAND_Y_TOP,
            facecolor=color, alpha=0.10,
            edgecolor=color, linewidth=1.2,
        ))
        ax.text(
            cx, _BAND_Y_TOP + 0.08, _BAND_LABELS[key],
            ha="center", va="bottom",
            fontsize=12, fontweight="bold", color=color,
            fontfamily="IPAexGothic",
        )
    ax.set_xlim(_BAND_X["answer"] - _BAND_WIDTH, _BAND_X["gt"] + _BAND_WIDTH)
    ax.set_ylim(-_BAND_Y_TOP - 0.30, _BAND_Y_TOP + 0.45)
    # Don't force equal aspect — the layout is intentionally wide-and-short.
    ax.set_axis_off()
    if title:
        ax.set_title(title, fontsize=12, fontfamily="IPAexGothic")
    return ax


def _venn_label_fontsize(answer_only: list, common: list, gt_only: list) -> int:
    """Pick a single label font size that keeps a region's vertical column
    from overlapping itself. The maximum-cardinality region drives the
    choice so all labels read at one uniform size in the figure."""
    n_max = max(len(answer_only), len(common), len(gt_only), 1)
    if n_max <= 4:  return 12
    if n_max <= 7:  return 11
    if n_max <= 10: return 10
    if n_max <= 14: return 9
    if n_max <= 18: return 8
    return 7


def _render_goals_venn(answer_only: list, common: list, gt_only: list):
    """Draw the 3-column Goals layout with labels placed inside each band.
    Returns `(fig, positions)`. The caller can reuse `positions` to draw
    connectors over the same coordinate system."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5.5))
    _draw_venn_base(ax, title="目標の分布")
    pos = _venn_positions(answer_only, common, gt_only)
    fs = _venn_label_fontsize(answer_only, common, gt_only)
    for label, (x, y) in pos.items():
        ax.text(x, y, label, ha="center", va="center", fontsize=fs,
                 fontfamily="IPAexGothic",
                 bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                            edgecolor="#666", alpha=0.92))
    plt.tight_layout()
    return fig, pos


def _render_goals_connectors(answer_only: list, common: list, gt_only: list,
                              edges_answer: list, edges_gt: list):
    """Draw the same Venn + connector lines between goals.

    Color encoding:
      - black: edge present in BOTH edges_answer and edges_gt
      - red:   edge present only in edges_answer
      - blue:  edge present only in edges_gt
    Line style:
      - solid:  synergy
      - dashed: tradeoff
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pos = _venn_positions(answer_only, common, gt_only)
    # Normalise an edge into a hashable key. Synergy is undirected, but we
    # keep direction info via the sorted-tuple for consistent dedup.
    def _key(e):
        return (tuple(sorted([e.get("from", ""), e.get("to", "")])),
                e.get("kind", "synergy"))
    set_a = {_key(e) for e in (edges_answer or [])}
    set_g = {_key(e) for e in (edges_gt or [])}

    fig, ax = plt.subplots(figsize=(10, 5.5))
    _draw_venn_base(ax, title="目標間のシナジー / トレードオフ")

    # Place labels exactly as in the base Venn so connectors line up.
    fs = _venn_label_fontsize(answer_only, common, gt_only)
    for label, (x, y) in pos.items():
        ax.text(x, y, label, ha="center", va="center", fontsize=fs,
                 fontfamily="IPAexGothic",
                 bbox=dict(boxstyle="round,pad=0.25", facecolor="white",
                            edgecolor="#666", alpha=0.92), zorder=3)

    # Edge drawing — use curved arcs (FancyArrowPatch) instead of straight
    # ax.plot lines so overlapping edges fan out and stay distinguishable:
    #   - each edge gets a unique curvature based on its sort-stable index
    #   - rad alternates sign so half the arcs bow upward, half downward
    #   - the magnitude grows with horizontal distance: edges that span
    #     all three columns curve harder than within-column edges
    from matplotlib.patches import FancyArrowPatch
    # Deterministic order so curvature assignment is stable across renders.
    all_keys = sorted(set_a | set_g)
    for idx, key in enumerate(all_keys):
        (a, b), kind = key
        if a not in pos or b not in pos:
            continue
        x1, y1 = pos[a]
        x2, y2 = pos[b]
        color = ("#222"   if key in set_a and key in set_g else
                 "#D32F2F" if key in set_a else
                 "#1565C0")
        ls = "-" if kind == "synergy" else "--"
        # Curvature: base ramps with span width so long arcs bow more.
        span = abs(x2 - x1)
        base_rad = 0.18 + 0.06 * span
        rad = base_rad * (1 if (idx % 2 == 0) else -1)
        # Small per-edge wiggle so even same-direction edges separate.
        rad += ((idx // 2) % 3 - 1) * 0.05
        arrow = FancyArrowPatch(
            (x1, y1), (x2, y2),
            connectionstyle=f"arc3,rad={rad:.3f}",
            arrowstyle="-",
            color=color, linestyle=ls,
            linewidth=1.6, alpha=0.78,
            zorder=2,
            shrinkA=18, shrinkB=18,   # leave clearance around label bboxes
        )
        ax.add_patch(arrow)

    # Legend
    from matplotlib.lines import Line2D
    legend_handles = [
        Line2D([0], [0], color="#222",    linewidth=1.6, linestyle="-",  label="A & GT 共通"),
        Line2D([0], [0], color="#D32F2F", linewidth=1.6, linestyle="-",  label="Answer(AI) のみ"),
        Line2D([0], [0], color="#1565C0", linewidth=1.6, linestyle="-",  label="Ground Truth のみ"),
        Line2D([0], [0], color="#666",    linewidth=1.6, linestyle="-",  label="シナジー"),
        Line2D([0], [0], color="#666",    linewidth=1.6, linestyle="--", label="トレードオフ"),
    ]
    ax.legend(handles=legend_handles, loc="lower center",
                bbox_to_anchor=(0.5, -0.05), ncol=5, frameon=False,
                prop={"family": "IPAexGothic", "size": 8})
    plt.tight_layout()
    return fig


def _render_goals_listing(common: list, answer_only: list, gt_only: list) -> None:
    """Render the 3-region goal listing with colored H/M/L badges.
    For `common` items, Answer and GT ratings are shown side-by-side."""
    import streamlit as st

    if common:
        st.markdown("#### 共通する目標")
        for g in common:
            st.markdown(
                f"**【{g.get('label', '?')}】**", unsafe_allow_html=False
            )
            ca, cg = st.columns(2)
            with ca:
                st.markdown("*Answer(AI)*")
                st.markdown(g.get("answer_text", "") or "_(原文なし)_")
                st.markdown(_ratings_inline(g, prefix="answer_"),
                              unsafe_allow_html=True)
            with cg:
                st.markdown("*Ground Truth*")
                st.markdown(g.get("gt_text", "") or "_(原文なし)_")
                st.markdown(_ratings_inline(g, prefix="gt_"),
                              unsafe_allow_html=True)
            st.markdown("---")

    if answer_only:
        st.markdown("#### Answer(AI) のみにある目標")
        for g in answer_only:
            st.markdown(f"**【{g.get('label','?')}】** {g.get('text', '')}")
            st.markdown(_ratings_inline(g), unsafe_allow_html=True)
            st.markdown("")

    if gt_only:
        st.markdown("#### Ground Truth のみにある目標")
        for g in gt_only:
            st.markdown(f"**【{g.get('label','?')}】** {g.get('text', '')}")
            st.markdown(_ratings_inline(g), unsafe_allow_html=True)
            st.markdown("")


def _render_goals_category(data: dict) -> None:
    """目標 (Goals) renderer: LLM-driven structured analysis with a Venn
    diagram, colored H/M/L listing, and a synergy/tradeoff connector graph.

    Triggered by a button so the LLM call only runs when the user asks for it;
    the result is cached in session state for the rest of the screen."""
    import streamlit as st

    items: list[dict] = data.get("narrative_items") or []
    # Gather G1/G2/G3 raw text from the narratives, keyed by Memo.
    by_memo = {it.get("memo", ""): it for it in items}
    g1 = by_memo.get("目標", {})
    g2 = by_memo.get("目標の評点", {})
    g3 = by_memo.get("目標のトレードオフ", {})

    _plugin = _PLUGIN_DIR.name
    _key = f"_pe_goals_struct_{_plugin}"
    _agent_state_key = f"eval_llm_agent_{_plugin}"

    cols = st.columns([2, 6])
    if cols[0].button("目標を構造化分析する (LLM)",
                       key="btn_pe_goals_struct",
                       help="Answer(AI) と Ground Truth の目標一覧を LLM で構造化し、ベン図 / 評点付き一覧 / シナジー・トレードオフ図を描画します"):
        _agent_file = st.session_state.get(_agent_state_key)
        if not _agent_file:
            cols[1].warning("先に LLM Evaluation セクションでエージェントを選択してください。")
        else:
            try:
                with st.spinner("LLM が目標を構造化中..."):
                    import DigiM_Evaluation as _de
                    parsed, _model = _de.llm_extract_goals_structured(
                        g1_answer=g1.get("answer", ""), g1_gt=g1.get("ground_truth", ""),
                        g2_answer=g2.get("answer", ""), g2_gt=g2.get("ground_truth", ""),
                        g3_answer=g3.get("answer", ""), g3_gt=g3.get("ground_truth", ""),
                        agent_file=_agent_file,
                        service_info=st.session_state.get("web_service", {}),
                        user_info=st.session_state.get("web_user", {}),
                    )
                    from datetime import datetime as _dt
                    st.session_state[_key] = {
                        "data": parsed, "model": _model, "agent": _agent_file,
                        "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
            except Exception as _e:
                st.error(f"目標分析に失敗しました: {_e}")
                return

    res = st.session_state.get(_key)
    if not res:
        st.info("「目標を構造化分析する (LLM)」を押すと、ベン図 / 評点付き一覧 / コネクタ図を表示します。")
        return

    d = res.get("data") or {}
    answer_only = d.get("answer_only") or []
    common      = d.get("common")      or []
    gt_only     = d.get("gt_only")     or []
    edges_a     = d.get("edges_answer") or []
    edges_g     = d.get("edges_gt")     or []

    st.caption(
        f"Agent: `{res.get('agent','')}`  /  Model: `{res.get('model','')}`  /  "
        f"Generated: {res.get('timestamp','')}  /  "
        f"Answer-only={len(answer_only)} / 共通={len(common)} / GT-only={len(gt_only)}  ・  "
        f"edges A={len(edges_a)} / GT={len(edges_g)}"
    )

    # ---- 1. Venn diagram (with 1-word labels in each region) ----
    if answer_only or common or gt_only:
        fig, _pos = _render_goals_venn(answer_only, common, gt_only)
        st.pyplot(fig)
        import matplotlib.pyplot as _plt
        _plt.close(fig)
    else:
        st.warning("目標が抽出できませんでした。LLM 出力が空、または JSON パースに失敗した可能性があります。")
        return

    # ---- 2. Listing with colored H/M/L per dimension ----
    _render_goals_listing(common, answer_only, gt_only)

    # ---- 3. Connector graph (synergy/tradeoff, color by source) ----
    if edges_a or edges_g:
        fig = _render_goals_connectors(answer_only, common, gt_only, edges_a, edges_g)
        st.pyplot(fig)
        import matplotlib.pyplot as _plt
        _plt.close(fig)
    else:
        st.caption("シナジー / トレードオフが抽出されなかったため、コネクタ図はスキップしました。")


def _render_section_llm_button(section_name: str, section_md: str) -> None:
    """Section-scoped LLM commentary button. Each section gets its own
    "🔍 LLMによる解説" button that asks the LLM to summarise commonalities and
    differences between Answer(AI) and Ground Truth for that section alone.

    Reads `_eval_PersonalEvaluation_llm_agent` from session state for the
    agent file (set by the WebUI agent picker). Result is cached under
    `_pe_section_llm_<plugin>_<section>` so subsequent reruns don't re-call
    the API.
    """
    import streamlit as st
    _plugin = _PLUGIN_DIR.name
    _key  = f"_pe_section_llm_{_plugin}_{section_name}"
    _btn_k = f"btn_{_key}"
    # Streamlit selectbox in the WebUI stores the chosen agent file under
    # `eval_llm_agent_<folder>` (selectbox key). Read that directly so the
    # button always sees the latest pick without an explicit re-save.
    _agent_state_key = f"eval_llm_agent_{_plugin}"

    cols = st.columns([2, 6])
    if cols[0].button(f"🔍 LLMによる解説", key=_btn_k,
                       help=f"{section_name} の Answer(AI) と Ground Truth の共通点・相違点を LLM で解説"):
        _agent_file = st.session_state.get(_agent_state_key)
        if not _agent_file:
            cols[1].warning("先に LLM Evaluation セクションでエージェントを選択してください。")
            return
        try:
            with st.spinner(f"LLM が「{section_name}」を解説中..."):
                import DigiM_Evaluation as _de
                from datetime import datetime as _dt
                text, model = _de.llm_compare_section(
                    section_name=section_name,
                    section_md=section_md,
                    agent_file=_agent_file,
                    service_info=st.session_state.get("web_service", {}),
                    user_info=st.session_state.get("web_user", {}),
                    plugin_name="Personal Evaluation",
                )
                st.session_state[_key] = {
                    "text": text, "model": model, "agent": _agent_file,
                    "timestamp": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
        except Exception as _e:
            st.error(f"LLM commentary failed: {_e}")
            return

    res = st.session_state.get(_key)
    if res:
        with st.expander(f"💬 LLM解説 - {section_name}", expanded=True):
            st.caption(
                f"Agent: `{res['agent']}`  /  Model: `{res['model']}`  /  "
                f"Generated: {res['timestamp']}"
            )
            st.markdown(res.get("text", ""))


# --------------------------------------------------------------------------
# Top-level cross-category summary
# --------------------------------------------------------------------------

def _summarize_category(cat: str, data: dict) -> dict:
    """Build a one-row summary for a single category. Returns:
        {
          "category": str,
          "type": "Likert" | "Narrative",
          "n": int,                  # rows in this category
          "scored": int, "scored_gt": int,
          "answer": float | None,    # mean axis score, Likert only
          "gt":     float | None,    # mean axis score (GT), Likert only
          "delta":  float | None,    # answer - gt
          "sim_seq": float | None,   # mean Seq Ratio, Narrative only
          "sim_f1":  float | None,   # mean Token F1, Narrative only
          "note":   str,
        }
    """
    n = len(data.get("narratives") or data.get("narrative_items") or [])
    out = {
        "category": cat, "n": n,
        "scored": data.get("scored", 0), "scored_gt": data.get("scored_gt", 0),
        "answer": None, "gt": None, "delta": None,
        "sim_seq": None, "sim_f1": None,
        "note": "",
    }
    if cat in _NARRATIVE_CATEGORIES:
        out["type"]    = "Narrative"
        out["sim_seq"] = data.get("narrative_overall_seq")
        out["sim_f1"]  = data.get("narrative_overall_f1")
        # Dimensional cats: note how many dimensions have data
        _dim_order = _NARRATIVE_DIM_ORDER.get(cat) or []
        if _dim_order:
            _present = [d for d in _dim_order if d in (data.get("dim_agg") or {})]
            out["note"] = f"{len(_present)}/{len(_dim_order)} 次元"
        else:
            out["note"] = f"{out['scored']} narrative answers"
        return out

    out["type"] = "Likert"
    # For 動機, the summary uses the union of BPNSFS + MWMS axes via axes_avg
    # (the analyzer already populates that with "MWMS_<code>"-prefixed keys
    # alongside the raw BPNSFS dimension names).
    axes = data.get("axes_avg") or {}
    axes_gt = data.get("axes_avg_gt") or {}
    if axes:
        out["answer"] = round(sum(axes.values()) / len(axes), 3)
    if axes_gt:
        out["gt"] = round(sum(axes_gt.values()) / len(axes_gt), 3)
    if out["answer"] is not None and out["gt"] is not None:
        out["delta"] = round(out["answer"] - out["gt"], 3)

    # Friendly note describing the underlying axis count
    if cat == "特性":
        out["note"] = f"Big Five 5軸"
    elif cat == "価値観":
        out["note"] = f"Schwartz 10値"
    elif cat == "動機":
        bp = len(data.get("bpnsfs_avg") or {})
        mw = len(data.get("mwms_avg")   or {})
        out["note"] = f"BPNSFS {bp}軸 + MWMS {mw}軸"
    else:
        out["note"] = f"{len(axes)}軸"
    return out


def _render_summary(result: dict) -> None:
    """Cross-category summary at the top of the screen."""
    import streamlit as st
    rows = [_summarize_category(cat, result["categories"][cat])
             for cat in result.get("category_order", [])]
    if not rows:
        return

    st.markdown("## サマリー (7カテゴリ横断)")

    # --- Compact summary table ---
    def _fmt(x):
        return f"{x:.2f}" if isinstance(x, (int, float)) else "-"

    def _delta_cell(d):
        if d is None: return "-"
        return f"{d:+.2f}"

    _df = pd.DataFrame([
        {
            "Category": r["category"],
            "Type":     r["type"],
            "n":        r["n"],
            "Answer(AI)":   _fmt(r["answer"])   if r["type"] == "Likert"    else "-",
            "GT":       _fmt(r["gt"])       if r["type"] == "Likert"    else "-",
            "Δ":        _delta_cell(r["delta"]) if r["type"] == "Likert" else "-",
            "Sim Seq":  _fmt(r["sim_seq"])  if r["type"] == "Narrative" else "-",
            "Sim F1":   _fmt(r["sim_f1"])   if r["type"] == "Narrative" else "-",
            "Note":     r["note"],
        } for r in rows
    ])
    st.dataframe(_df, hide_index=True, use_container_width=True)

    # --- Radar: per-category aggregate, one axis per category. Likert
    # categories show (Answer(AI), Ground Truth) axis means; narrative
    # categories show (Seq Ratio, Token F1) similarity. Both are on the same
    # 0–1 scale so they share the radar grid. ---
    cats = [r["category"] for r in rows]
    # Build labels with a type hint so the reader can tell which "metric" the
    # axis represents — keeps the radar honest about mixed semantics.
    labels = [
        f"{r['category']}\n({'軸平均' if r['type'] == 'Likert' else '類似度'})"
        for r in rows
    ]
    vals_a = [
        (r["answer"] if r["type"] == "Likert" else r["sim_seq"]) or 0.0
        for r in rows
    ]
    vals_b = [
        (r["gt"] if r["type"] == "Likert" else r["sim_f1"]) or 0.0
        for r in rows
    ]
    fig = _radar(labels, vals_a, "サマリー (7カテゴリ)", values_gt=vals_b)
    if fig is not None:
        # Override the dual-layer legend labels so the semantics are clear
        # for both Likert (Answer(AI) / Ground Truth) and Narrative
        # (Seq Ratio / Token F1) modes.
        _ax = fig.axes[0] if fig.axes else None
        if _ax and _ax.get_legend():
            for t, new in zip(_ax.get_legend().get_texts(),
                                ["Answer(AI) / Seq Ratio",
                                 "Ground Truth / Token F1"]):
                t.set_text(new)
        st.pyplot(fig)
        import matplotlib.pyplot as _plt
        _plt.close(fig)
    st.caption(
        "*Likert カテゴリ (特性 / 価値観 / 動機) は軸平均スコア (Answer(AI) / Ground Truth) を、"
        "Narrative カテゴリ (目標 / 人格形成 / 社会性 / 愛着) は A↔GT 比較類似度 "
        "(Seq Ratio / Token F1) を表示。両者を 0–1 の同一スケールに揃えています。*"
    )


def _summary_md(result: dict) -> list[str]:
    out: list[str] = ["", "## サマリー (7カテゴリ横断)", ""]
    rows = [_summarize_category(cat, result["categories"][cat])
             for cat in result.get("category_order", [])]
    if not rows:
        return out
    out.append("| Category | Type | n | Answer(AI) | GT | Δ | Sim Seq | Sim F1 | Note |")
    out.append("|------|------|---:|---:|---:|---:|---:|---:|------|")
    for r in rows:
        def _f(x): return f"{x:.2f}" if isinstance(x, (int, float)) else "-"
        _d = f"{r['delta']:+.2f}" if r["delta"] is not None else "-"
        out.append(
            f"| {r['category']} | {r['type']} | {r['n']} | "
            f"{_f(r['answer']) if r['type'] == 'Likert' else '-'} | "
            f"{_f(r['gt'])     if r['type'] == 'Likert' else '-'} | "
            f"{_d              if r['type'] == 'Likert' else '-'} | "
            f"{_f(r['sim_seq']) if r['type'] == 'Narrative' else '-'} | "
            f"{_f(r['sim_f1'])  if r['type'] == 'Narrative' else '-'} | "
            f"{r['note']} |"
        )
    return out


def _render_narrative_category(cat: str, data: dict) -> None:
    """Render a narrative category: A↔GT side-by-side text, per-row
    similarity bar, and (for 社会性 / 愛着) a per-dimension similarity radar."""
    import streamlit as st
    items: list[dict] = data.get("narrative_items") or []
    if not items:
        st.info(f"{cat} の Answer / Ground Truth がまだ入っていません。")
        return

    # ---- Header summary ----
    _pairs = data.get("narrative_pairs", 0)
    _seq   = data.get("narrative_overall_seq", 0.0)
    _f1    = data.get("narrative_overall_f1", 0.0)
    _cap   = (
        f"answers: **{data['scored']}**  /  GT: **{data['scored_gt']}**  /  "
        f"compared pairs: **{_pairs}**  /  "
        f"mean Seq Ratio: **{_seq:.2f}**  /  mean Token F1: **{_f1:.2f}**"
    )
    st.caption(_cap)

    # ---- Per-dimension similarity radar (社会性 / 愛着 only) ----
    dim_order = _NARRATIVE_DIM_ORDER.get(cat) or []
    dim_agg   = data.get("dim_agg") or {}
    if dim_order and dim_agg:
        # Drop dimensions that have no comparable pairs (no answer or no GT).
        present = [d for d in dim_order if d in dim_agg]
        if len(present) >= 3:
            st.markdown("#### 次元別 類似度レーダー (Answer(AI) ↔ Ground Truth)")
            c1, c2 = st.columns([3, 2])
            labels = present
            seq_vals = [dim_agg[d]["seq"] for d in labels]
            f1_vals  = [dim_agg[d]["f1"]  for d in labels]
            # Reuse the dual-layer radar: Seq Ratio in blue, Token F1 in green.
            # Labels are abbreviated for chart readability.
            short_labels = [re.split(r"[\(（]", d, maxsplit=1)[0] for d in labels]
            fig = _radar(short_labels, seq_vals, f"{cat} — similarity", values_gt=f1_vals)
            # Override the legend to match the overlay semantics here.
            if fig is not None:
                _ax = fig.axes[0] if fig.axes else None
                if _ax and _ax.get_legend():
                    for t, new in zip(_ax.get_legend().get_texts(), ["Seq Ratio", "Token F1"]):
                        t.set_text(new)
                with c1:
                    st.pyplot(fig)
                    import matplotlib.pyplot as _plt
                    _plt.close(fig)
            with c2:
                st.markdown("**次元別スコア:**")
                _df_dim = pd.DataFrame([
                    {"Dimension": d, "n": dim_agg[d]["n"],
                     "Seq Ratio": dim_agg[d]["seq"],
                     "Token F1":  dim_agg[d]["f1"]}
                    for d in labels
                ])
                st.dataframe(_df_dim, hide_index=True, use_container_width=True)

    # ---- Per-row similarity bar (overall, one bar per row) ----
    st.markdown("#### 質問別 類似度")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _row_ids = [it["no"] or f"#{i+1}" for i, it in enumerate(items)]
    _row_seq = [it["seq"] for it in items]
    _row_f1  = [it["f1"]  for it in items]
    fig, ax = plt.subplots(figsize=(max(6.0, len(items) * 0.6), 3.2))
    _x = list(range(len(items)))
    _w = 0.4
    ax.bar([x - _w/2 for x in _x], _row_seq, width=_w, color="#1565C0", alpha=0.85, label="Seq Ratio")
    ax.bar([x + _w/2 for x in _x], _row_f1,  width=_w, color="#2E7D32", alpha=0.85, label="Token F1")
    ax.set_xticks(_x)
    ax.set_xticklabels(_row_ids, rotation=0, fontsize=8.5)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Similarity")
    ax.legend(loc="upper right", fontsize=8, frameon=False)
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    st.pyplot(fig); plt.close(fig)

    # Length comparison (Answer vs GT char counts) — quick visual cue for
    # when GT is materially longer/shorter than Answer.
    _len_a = [it["len_a"] for it in items]
    _len_b = [it["len_b"] for it in items]
    if any(_len_a) or any(_len_b):
        st.markdown("#### 質問別 文字数 (Answer(AI) vs Ground Truth)")
        fig, ax = plt.subplots(figsize=(max(6.0, len(items) * 0.6), 2.8))
        ax.bar([x - _w/2 for x in _x], _len_a, width=_w, color="#1565C0", alpha=0.85, label="Answer(AI)")
        ax.bar([x + _w/2 for x in _x], _len_b, width=_w, color="#2E7D32", alpha=0.85, label="Ground Truth")
        ax.set_xticks(_x)
        ax.set_xticklabels(_row_ids, rotation=0, fontsize=8.5)
        ax.set_ylabel("char count")
        ax.legend(loc="upper right", fontsize=8, frameon=False)
        ax.grid(True, alpha=0.3, axis="y")
        plt.tight_layout()
        st.pyplot(fig); plt.close(fig)

    # ---- Side-by-side text comparison per row ----
    # Collapsed by default — the per-row Q/A/GT block can be 10+ rows of long
    # free-form text per category (e.g. 人格形成 has 8 rows). Keep the
    # summary stats + radar above visible, hide the verbose row-by-row body
    # behind an expander the user can pop open on demand.
    with st.expander(f"Answer(AI) / Ground Truth 比較 (個別 · {len(items)} 件)", expanded=False):
        for it in items:
            _head = f"**[{it['no']}] {it['axis'] or '(unmapped)'}**"
            _meta = f"  *(Seq={it['seq']:.2f} · F1={it['f1']:.2f} · A={it['len_a']}字 / GT={it['len_b']}字)*"
            st.markdown(_head + _meta)
            if it["question"]:
                st.markdown(f"**Q:** {it['question']}")
            ca, cb = st.columns(2)
            with ca:
                st.markdown("**Answer(AI)**")
                st.markdown(it["answer"] or "_(empty)_")
            with cb:
                st.markdown("**Ground Truth**")
                st.markdown(it["ground_truth"] or "_(empty)_")
            st.markdown("---")


def _category_to_md(cat: str, data: dict) -> str:
    lines = []
    meta = data.get("meta") or {}
    if meta.get("theory"):
        lines.append(f"- 理論: **{meta['theory']}**")
    if meta.get("items"):
        lines.append(f"- 評価項目: {meta['items'][:300]}")

    if cat == "価値観":
        lines.extend(_values_md(data))
    elif cat == "動機":
        lines.extend(_motivation_md(data))
    elif cat in _NARRATIVE_CATEGORIES:
        lines.extend(_narrative_md(cat, data))
    else:
        axes = data.get("axes_avg") or {}
        axes_gt = data.get("axes_avg_gt") or {}
        if axes:
            lines.append("")
            _hdr = f"**Scores ({data['scored']} scored / {data['unscored']} unscored"
            if data.get("scored_gt"):
                _hdr += f" / GT {data['scored_gt']} scored"
            lines.append(_hdr + "):**")
            lines.append("")
            if axes_gt:
                lines.append("| Axis | Answer(AI) | Ground Truth |")
                lines.append("|------|------:|------:|")
                for k in sorted(axes.keys(), key=lambda x: -axes[x]):
                    _gt = axes_gt.get(k)
                    lines.append(f"| {k} | {axes[k]:.2f} | {(_gt is not None) and f'{_gt:.2f}' or '-'} |")
            else:
                lines.append("| Axis | Answer(AI) |")
                lines.append("|------|------:|")
                for k, v in sorted(axes.items(), key=lambda x: -x[1]):
                    lines.append(f"| {k} | {v:.2f} |")

    lines.extend(_narratives_md(data))
    return "\n".join(lines)


def _values_md(data: dict) -> list[str]:
    out: list[str] = []
    axes = data.get("axes_avg") or {}
    axes_gt = data.get("axes_avg_gt") or {}
    if not axes:
        return out

    out.append("")
    out.append("### 10値スコア")
    out.append("")
    out.append("| Value | Answer(AI) | Ground Truth |")
    out.append("|------|------:|------:|")
    for v in _SCHWARTZ_10:
        _a = axes.get(v, 0.0)
        _g = axes_gt.get(v) if axes_gt else None
        _gs = f"{_g:.2f}" if _g is not None else "-"
        out.append(f"| {v} ({_SCHWARTZ_JP[v]}) | {_a:.2f} | {_gs} |")

    out.append("")
    out.append("### 4グループ集約 (Schwartz 高次構造)")
    # Order is fixed by _SCHWARTZ_GROUPS (NOT sorted by score).
    groups = []
    for label, members, desc in _SCHWARTZ_GROUPS:
        avg = sum(axes.get(m, 0.0) for m in members) / len(members)
        gts = [axes_gt.get(m) for m in members] if axes_gt else []
        gts = [g for g in gts if g is not None]
        avg_gt = (sum(gts) / len(gts)) if gts else None
        groups.append({"label": label, "members": members, "desc": desc,
                        "answer": avg, "gt": avg_gt})
    out.append("")
    out.append("| No | Group | Members | Answer(AI) | Ground Truth |")
    out.append("|---:|------|------|------:|------:|")
    for i, g in enumerate(groups):
        _gs = f"{g['gt']:.2f}" if g["gt"] is not None else "-"
        out.append(
            f"| {i+1} | {g['label']} | {' / '.join(g['members'])} | "
            f"{g['answer']:.2f} | {_gs} |"
        )
    out.append("")
    out.append("**各グループの解説:**")
    for i, g in enumerate(groups):
        line = f"{i+1}. **{g['label']}** (score={g['answer']:.2f})"
        if g["gt"] is not None and abs(g["answer"] - g["gt"]) >= 0.1:
            line += f" — GTとの差 {g['answer'] - g['gt']:+.2f}"
        line += f"  \n   {g['desc']}"
        out.append(line)
    return out


def _motivation_md(data: dict) -> list[str]:
    out: list[str] = []
    bp    = data.get("bpnsfs_avg") or {}
    bp_gt = data.get("bpnsfs_avg_gt") or {}
    mw    = data.get("mwms_avg") or {}
    mw_gt = data.get("mwms_avg_gt") or {}

    if bp:
        out.append("")
        out.append("### 基本的心理欲求 (BPNSFS)")
        out.append("")
        out.append("| Axis | Answer(AI) | Ground Truth |")
        out.append("|------|------:|------:|")
        for a in _BPNSFS_AXES:
            _a = bp.get(a, 0.0)
            _g = bp_gt.get(a) if bp_gt else None
            _gs = f"{_g:.2f}" if _g is not None else "-"
            out.append(f"| {a} ({_BPNSFS_JP.get(a, '')}) | {_a:.2f} | {_gs} |")
    if mw:
        out.append("")
        out.append("### 仕事の動機づけ (MWMS)")
        out.append("")
        out.append("| Axis | Answer(AI) | Ground Truth |")
        out.append("|------|------:|------:|")
        for a in _MWMS_AXES:
            _a = mw.get(a, 0.0)
            _g = mw_gt.get(a) if mw_gt else None
            _gs = f"{_g:.2f}" if _g is not None else "-"
            out.append(f"| {a} ({_MWMS_JP[a]}) | {_a:.2f} | {_gs} |")
    return out


def _narrative_md(cat: str, data: dict) -> list[str]:
    """Markdown for narrative categories: per-row similarity table + dim
    aggregate (社会性 / 愛着) + the side-by-side text in a collapsed details."""
    out: list[str] = []
    items: list[dict] = data.get("narrative_items") or []
    if not items:
        return out

    out.append("")
    out.append(
        f"answers: **{data['scored']}** / GT: **{data['scored_gt']}** / "
        f"compared pairs: **{data.get('narrative_pairs', 0)}** / "
        f"mean Seq Ratio: **{data.get('narrative_overall_seq', 0.0):.2f}** / "
        f"mean Token F1: **{data.get('narrative_overall_f1', 0.0):.2f}**"
    )

    # Per-dimension aggregate (社会性 / 愛着 only)
    dim_order = _NARRATIVE_DIM_ORDER.get(cat) or []
    dim_agg   = data.get("dim_agg") or {}
    present = [d for d in dim_order if d in dim_agg]
    if present:
        out.append("")
        out.append("### 次元別 類似度")
        out.append("")
        out.append("| Dimension | n | Seq Ratio | Token F1 |")
        out.append("|------|---:|---:|---:|")
        for d in present:
            x = dim_agg[d]
            out.append(f"| {d} | {x['n']} | {x['seq']:.2f} | {x['f1']:.2f} |")

    # Per-row similarity table
    out.append("")
    out.append("### 質問別 類似度")
    out.append("")
    out.append("| No | Memo | Seq Ratio | Token F1 | Answer(AI) 文字数 | GT 文字数 |")
    out.append("|----|------|---:|---:|---:|---:|")
    for it in items:
        out.append(
            f"| {it['no']} | {it['memo']} | {it['seq']:.2f} | {it['f1']:.2f} | "
            f"{it['len_a']} | {it['len_b']} |"
        )

    # Side-by-side text (collapsed)
    out.append("")
    out.append(f"<details><summary>Answer / Ground Truth 比較 ({len(items)} rows)</summary>")
    out.append("")
    for it in items:
        out.append(f"**[{it['no']}] {it['axis'] or '(unmapped)'}** — Seq={it['seq']:.2f} / F1={it['f1']:.2f}")
        if it["question"]:
            out.append(f"- Q: {it['question']}")
        out.append(f"- Answer(AI):\n  > {it['answer'][:1500]}".replace("\n", "\n  > "))
        out.append(f"- Ground Truth:\n  > {it['ground_truth'][:1500]}".replace("\n", "\n  > "))
    out.append("</details>")
    return out


def _narratives_md(data: dict) -> list[str]:
    out: list[str] = []
    if not data.get("narratives"):
        return out
    out.append("")
    out.append(f"<details><summary>Answers ({len(data['narratives'])})</summary>")
    out.append("")
    for n in data["narratives"]:
        tag = f"**[{n['no']}] {n['axis'] or n['memo']}**"
        if n.get("reverse"): tag += " _(reverse)_"
        out.append(f"- {tag}")
        if n["question"]:
            out.append(f"  - Q: {n['question']}")
        if n["answer"]:
            out.append(f"  - A: {n['answer']}")
        if n["ground_truth"]:
            out.append(f"  - GT: {n['ground_truth']}")
    out.append("</details>")
    return out
