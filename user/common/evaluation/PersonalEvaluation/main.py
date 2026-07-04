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
    def default_agent() -> str:
        # Dedicated evaluation agent — replaces the free-form agent selectbox
        # so scoring stays reproducible run-to-run (the same input always
        # goes to the same model). Configure the model / provider inside the
        # agent JSON, not per-run in the UI.
        return "agent_66Evaluation.json"

    @staticmethod
    def list_categories() -> list[str]:
        """Return the expected category order for PersonalEvaluation.

        Optional plugin hook — read by the WebUI to render a category-
        selection checklist BEFORE `Run analysis`. Return the 7 theories in
        the fixed display order. When the operator's Excel omits a category
        the render layer silently skips it; the WebUI still uses this list
        for the pre-run checkboxes because those need to exist before we've
        seen the file.
        """
        return ["特性", "価値観", "動機", "目標", "人格形成", "社会性", "愛着"]

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
    def llm_augment(result: dict[str, Any], agent_file: str,
                     service_info: dict, user_info: dict,
                     categories: list[str] | None = None) -> dict[str, dict]:
        """Auto-run the structured LLM analyses (人格形成 rubric + 目標
        structure) as part of Run analysis so the operator doesn't need to
        click per-category "構造化分析" buttons.

        The two LLM calls fire in PARALLEL via ThreadPoolExecutor — since
        they're independent network-bound requests, running them
        concurrently roughly halves the wall-clock time of Run analysis
        (30-60s per call → 30-60s total instead of 60-120s).

        Returns a dict `{session_state_key: cache_entry}` that the WebUI
        writes into `st.session_state` — the exact same keys the render
        functions (`_render_narrative_scored_category`,
        `_render_goals_category`) already read from. Per-category exceptions
        are captured and re-surfaced under the special key
        `_llm_augment_errors` so the caller can display them (a bad key on
        one category doesn't kill the other).
        """
        import DigiM_Evaluation as _de
        from concurrent.futures import ThreadPoolExecutor, as_completed
        _plugin_name = _PLUGIN_DIR.name
        _out: dict[str, dict] = {}
        _errors: dict[str, str] = {}
        _cats_avail = result.get("categories") or {}
        _wanted = set(categories) if categories is not None else None
        _now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Prepare per-category work items — each is a `(cache_key, callable)`
        # pair the executor will dispatch. Callables must be self-contained
        # (capture all inputs by closure).
        _tasks: list[tuple[str, str, callable]] = []

        # --- 人格形成 (LLM 軸別ルーブリック) ---------------------------------
        if ("人格形成" in _cats_avail
                and (_wanted is None or "人格形成" in _wanted)):
            _data = _cats_avail["人格形成"]
            _items = _data.get("narrative_items") or []
            _axes_cfg = _NARRATIVE_SCORED_AXES.get("人格形成") or []
            if _items and _axes_cfg:
                _ans_block = "\n\n".join(
                    f"[{it.get('no','')}] {it.get('memo','')}\n"
                    f"Q: {it.get('question','')}\n"
                    f"A: {it.get('answer','')}"
                    for it in _items
                )
                _gt_block = "\n\n".join(
                    f"[{it.get('no','')}] {it.get('memo','')}\n"
                    f"Q: {it.get('question','')}\n"
                    f"GT: {it.get('ground_truth','')}"
                    for it in _items
                )
                def _run_narr(a=_ans_block, g=_gt_block, cfg=_axes_cfg):
                    return _de.llm_extract_narrative_scored(
                        category_name="人格形成",
                        axes=cfg,
                        answer_text=a, gt_text=g,
                        agent_file=agent_file,
                        service_info=service_info, user_info=user_info,
                    )
                _tasks.append(("人格形成",
                                f"_pe_narr_scored_{_plugin_name}_人格形成",
                                _run_narr))

        # --- 目標 (LLM 構造抽出: 目標一覧 + H/M/L 評点 + edges) --------------
        if ("目標" in _cats_avail
                and (_wanted is None or "目標" in _wanted)):
            _data = _cats_avail["目標"]
            _items = _data.get("narrative_items") or []
            _by_memo = {it.get("memo", ""): it for it in _items}
            _g1 = _by_memo.get("目標", {})
            _g2 = _by_memo.get("目標の評点", {})
            # G3 memo key was renamed from 目標のトレードオフ to 目標同士の関係.
            # Fall through to the legacy key so older xlsx templates still work.
            _g3 = (_by_memo.get("目標同士の関係")
                    or _by_memo.get("目標のトレードオフ")
                    or {})
            if any((_g1, _g2, _g3)):
                def _run_goals(g1=_g1, g2=_g2, g3=_g3):
                    return _de.llm_extract_goals_structured(
                        g1_answer=g1.get("answer", ""),
                        g1_gt=g1.get("ground_truth", ""),
                        g2_answer=g2.get("answer", ""),
                        g2_gt=g2.get("ground_truth", ""),
                        g3_answer=g3.get("answer", ""),
                        g3_gt=g3.get("ground_truth", ""),
                        agent_file=agent_file,
                        service_info=service_info, user_info=user_info,
                    )
                _tasks.append(("目標",
                                f"_pe_goals_struct_{_plugin_name}",
                                _run_goals))

        if _tasks:
            # Run both LLM calls concurrently. max_workers matches the task
            # count so both fire immediately; the executor context-manager
            # blocks until all futures resolve before returning.
            with ThreadPoolExecutor(max_workers=len(_tasks)) as _pool:
                _futs = {_pool.submit(_fn): (_cat, _key)
                          for (_cat, _key, _fn) in _tasks}
                for _fut in as_completed(_futs):
                    _cat, _key = _futs[_fut]
                    try:
                        _parsed, _model, _prompt = _fut.result()
                        _out[_key] = {
                            "data": _parsed, "model": _model,
                            "agent": agent_file, "prompt": _prompt,
                            "timestamp": _now,
                        }
                    except Exception as _e:
                        _errors[_cat] = f"{type(_e).__name__}: {_e}"

        if _errors:
            _out["_llm_augment_errors"] = _errors
        return _out

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
        st.markdown("---")
        for cat in result.get("category_order", []):
            data = result["categories"][cat]
            _render_category(cat, data)
            st.markdown("---")
        # Single unified LLM commentary covering all sections at the bottom.
        # ~1000 字: brief opening summary + per-category detail. Replaces the
        # per-section buttons that used to hang off every category.
        _render_overall_llm_commentary(result)

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
#
# 社会性 / 愛着 used to be here; they were converted to Likert 5-point selection
# style (Excel template now ships with declarative statements + a numeric-only
# answer scale, see `PersonalTestQA.xlsx`). They now go through the default
# Likert path (`_analyze_default` → `axes_avg` per dimension parsed from Memo).
_NARRATIVE_CATEGORIES = {"目標", "人格形成"}

# Dimensional structure — kept as documentation of the axis order these
# categories emit, but no longer consumed by the narrative-only pathway.
# `_analyze_default` builds `axes_avg` from the Memo column directly, so the
# order is derived from the Excel row order at analysis time.
_NARRATIVE_DIM_ORDER: dict[str, list[str]] = {}


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
        baseline = _norm(_get_cell(r, "Baseline", "BaseLine",
                                     "ベースライン", "BASELINE"))
        question = _norm(_get_cell(r, "Question", "質問"))
        no = _norm(_get_cell(r, "No", "no", "番号"))
        sim = _similarity(answer, gt)
        items.append({
            "no": no, "memo": memo, "axis": memo,
            "question": question, "answer": answer, "ground_truth": gt,
            "baseline": baseline,
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
            "baseline": it.get("baseline") or "",
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
    """Single-axis-per-row scoring. Also computes parallel GT / Baseline tracks
    so the renderer can overlay Answer / GT / Baseline on the same radar."""
    axes_raw: dict[str, list[float]] = {}
    axes_raw_gt: dict[str, list[float]] = {}
    axes_raw_bl: dict[str, list[float]] = {}
    narratives: list[dict] = []
    scored = unscored = scored_gt = scored_bl = 0
    for r in rows:
        memo = _norm(_get_cell(r, "Memo", "メモ", "MEMO"))
        answer = _norm(_get_cell(r, "Answer", "回答", "ANSWER"))
        gt = _norm(_get_cell(r, "Ground Truth", "GroundTruth", "GT"))
        baseline = _norm(_get_cell(r, "Baseline", "BaseLine",
                                     "ベースライン", "BASELINE"))
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

        bl_score = _score_answer(baseline)
        if bl_score is not None and axis:
            adj_bl = (1.0 - bl_score) if reverse else bl_score
            axes_raw_bl.setdefault(axis, []).append(adj_bl)
            scored_bl += 1

        narratives.append({
            "no": no, "axis": axis, "memo": memo, "reverse": reverse,
            "question_style": question_style, "question": question,
            "answer": answer, "ground_truth": gt, "baseline": baseline,
        })

    axes_avg    = {k: round(sum(v) / len(v), 3) for k, v in axes_raw.items() if v}
    axes_avg_gt = {k: round(sum(v) / len(v), 3) for k, v in axes_raw_gt.items() if v}
    axes_avg_bl = {k: round(sum(v) / len(v), 3) for k, v in axes_raw_bl.items() if v}

    return {
        "axes_avg":         axes_avg,
        "axes_avg_gt":      axes_avg_gt,
        "axes_avg_baseline": axes_avg_bl,
        "axes_raw":         axes_raw,
        "axes_raw_gt":      axes_raw_gt,
        "axes_raw_baseline": axes_raw_bl,
        "narratives":       narratives,
        "scored":           scored,
        "scored_gt":        scored_gt,
        "scored_baseline":  scored_bl,
        "unscored":         unscored,
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


# --------------------------------------------------------------------------
# 社会性 (Leach's Hierarchical Multicomponent Model of In-group Identification)
# --------------------------------------------------------------------------
# Leach et al. (2008) organises 5 first-order dimensions into 2 higher-order
# constructs:
#   - Self-Definition (認知面):  Self-stereotyping / In-group homogeneity
#   - Self-Investment (情動面):  Satisfaction / Solidarity / Centrality
#
# Order below drives the 2-group aggregation table + summary tile extras.
_SOCIABILITY_GROUPS = [
    ("自己定義 (Self-Definition)",
     ["Self-stereotyping", "In-group homogeneity"],
     "自分を集団の典型的なメンバーとしてどう位置付けるか (認知的な同定・集団の同質性知覚)。"),
    ("自己投資 (Self-Investment)",
     ["Satisfaction", "Solidarity", "Centrality"],
     "集団の一員であることへの情動・行動的コミットメント (満足・連帯・中心性)。"),
]

# JP names for the 5 first-order axes — used by the group-description
# "*<jp>(<en>) / ... が該当*" line (mirrors _SCHWARTZ_JP for 価値観).
_SOCIABILITY_JP = {
    "Self-stereotyping":    "自己カテゴリー化",
    "In-group homogeneity": "集団との類似性",
    "Satisfaction":         "満足感",
    "Solidarity":           "連帯感",
    "Centrality":           "中心性",
}


# --------------------------------------------------------------------------
# Category-specific axis display order for Likert categories
# --------------------------------------------------------------------------
# The default Likert renderer discovers axes from `axes_avg.keys()` which
# reflects Excel row order. When a category has a canonical ordering that
# should be honoured on the radar / score table regardless of Excel row
# order, register it here.
_CATEGORY_AXIS_ORDER: dict[str, list[str]] = {
    "特性": ["Openness", "Conscientiousness", "Extraversion",
              "Agreeableness", "Emotional Stability"],
    "社会性": [_m for _, _members, _ in _SOCIABILITY_GROUPS for _m in _members],
}


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
    `(1 - score)` to B. Same for Ground Truth and Baseline."""
    axes_raw    = {v: [] for v in _SCHWARTZ_10}
    axes_raw_gt = {v: [] for v in _SCHWARTZ_10}
    axes_raw_bl = {v: [] for v in _SCHWARTZ_10}
    narratives: list[dict] = []
    scored = unscored = scored_gt = scored_bl = 0
    for r in rows:
        memo = _norm(_get_cell(r, "Memo", "メモ", "MEMO"))
        answer = _norm(_get_cell(r, "Answer", "回答", "ANSWER"))
        gt = _norm(_get_cell(r, "Ground Truth", "GroundTruth", "GT"))
        baseline = _norm(_get_cell(r, "Baseline", "BaseLine",
                                     "ベースライン", "BASELINE"))
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

        bl_score = _score_answer(baseline)
        if bl_score is not None and pair:
            axes_raw_bl[pair[0]].append(bl_score)
            axes_raw_bl[pair[1]].append(1.0 - bl_score)
            scored_bl += 1

        narratives.append({
            "no": no, "axis": axis_label, "memo": memo, "reverse": False,
            "question_style": question_style, "question": question,
            "answer": answer, "ground_truth": gt, "baseline": baseline,
        })

    axes_avg    = {k: round(sum(v) / len(v), 3) for k, v in axes_raw.items() if v}
    axes_avg_gt = {k: round(sum(v) / len(v), 3) for k, v in axes_raw_gt.items() if v}
    axes_avg_bl = {k: round(sum(v) / len(v), 3) for k, v in axes_raw_bl.items() if v}
    return {
        "axes_avg":          axes_avg,
        "axes_avg_gt":       axes_avg_gt,
        "axes_avg_baseline": axes_avg_bl,
        "narratives":        narratives,
        "scored":            scored,
        "scored_gt":         scored_gt,
        "scored_baseline":   scored_bl,
        "unscored":          unscored,
        "_axis_order":       _SCHWARTZ_10,
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
    Frustration items reverse-contribute to BPNSFS net scores. Baseline is
    scored in parallel using the same reverse-code rules."""
    bpnsfs_raw    = {a: [] for a in _BPNSFS_AXES}
    bpnsfs_raw_gt = {a: [] for a in _BPNSFS_AXES}
    bpnsfs_raw_bl = {a: [] for a in _BPNSFS_AXES}
    mwms_raw      = {a: [] for a in _MWMS_AXES}
    mwms_raw_gt   = {a: [] for a in _MWMS_AXES}
    mwms_raw_bl   = {a: [] for a in _MWMS_AXES}
    narratives: list[dict] = []
    scored = unscored = scored_gt = scored_bl = 0
    for r in rows:
        memo = _norm(_get_cell(r, "Memo", "メモ", "MEMO"))
        answer = _norm(_get_cell(r, "Answer", "回答", "ANSWER"))
        gt = _norm(_get_cell(r, "Ground Truth", "GroundTruth", "GT"))
        baseline = _norm(_get_cell(r, "Baseline", "BaseLine",
                                     "ベースライン", "BASELINE"))
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

        bl_score = _score_answer(baseline)
        if bl_score is not None and bucket:
            grp, axis, rev = bucket
            adj_bl = (1.0 - bl_score) if rev else bl_score
            (bpnsfs_raw_bl if grp == "BPNSFS" else mwms_raw_bl)[axis].append(adj_bl)
            scored_bl += 1

        narratives.append({
            "no": no, "axis": axis_label, "memo": memo, "reverse": False,
            "question_style": question_style, "question": question,
            "answer": answer, "ground_truth": gt, "baseline": baseline,
        })

    def _avg(d):
        return {k: round(sum(v) / len(v), 3) for k, v in d.items() if v}
    return {
        # Flat fields keep `axes_avg` populated so the diagnostic fallback in
        # `_render_category` doesn't fire for narrative-rich-but-no-axes runs.
        "axes_avg":         {**_avg(bpnsfs_raw), **{f"MWMS_{k}": v for k, v in _avg(mwms_raw).items()}},
        "axes_avg_gt":      {**_avg(bpnsfs_raw_gt), **{f"MWMS_{k}": v for k, v in _avg(mwms_raw_gt).items()}},
        "axes_avg_baseline":{**_avg(bpnsfs_raw_bl), **{f"MWMS_{k}": v for k, v in _avg(mwms_raw_bl).items()}},
        "bpnsfs_avg":       _avg(bpnsfs_raw),
        "bpnsfs_avg_gt":    _avg(bpnsfs_raw_gt),
        "bpnsfs_avg_baseline": _avg(bpnsfs_raw_bl),
        "mwms_avg":         _avg(mwms_raw),
        "mwms_avg_gt":      _avg(mwms_raw_gt),
        "mwms_avg_baseline": _avg(mwms_raw_bl),
        "narratives":       narratives,
        "scored":           scored,
        "scored_gt":        scored_gt,
        "scored_baseline":  scored_bl,
        "unscored":         unscored,
    }


def _radar(labels: list[str], values: list[float], title: str,
            values_gt: list[float] | None = None,
            values_baseline: list[float] | None = None):
    """Polar radar chart (returns the matplotlib Figure).

    When `values_gt` is provided and non-empty, overlays a second layer in
    green (Ground Truth) on top of the Answer-in-blue base. When
    `values_baseline` is provided the benchmark model's answers are drawn
    in orange as a third layer (dashed) so the reader can see how far
    Answer / GT have drifted from the general-model baseline. All layers
    are aligned to the same `labels`; pass `0.0` for a missing axis on any
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

    _has_gt = bool(values_gt and any(v > 0 for v in values_gt))
    _has_bl = bool(values_baseline and any(v > 0 for v in values_baseline))

    # Ground Truth = green overlay (drawn second so it sits on top)
    if _has_gt:
        vg = list(values_gt) + [values_gt[0]]
        ax.plot(angles, vg, linewidth=1.6, color="#2E7D32", linestyle="-", label="Ground Truth")
        ax.fill(angles, vg, alpha=0.18, color="#2E7D32")

    # Baseline = orange overlay (drawn last so it sits on top)
    if _has_bl:
        vb = list(values_baseline) + [values_baseline[0]]
        ax.plot(angles, vb, linewidth=1.4, color="#EF6C00",
                 linestyle="--", label="Baseline")
        ax.fill(angles, vb, alpha=0.12, color="#EF6C00")

    if _has_gt or _has_bl:
        ax.legend(loc="upper right", bbox_to_anchor=(1.30, 1.10), fontsize=8, frameon=False)

    ax.grid(True, alpha=0.4)
    plt.title(title, fontfamily="IPAexGothic", fontsize=11)
    plt.tight_layout()
    return fig


def _score_table(axes: dict, axes_gt: dict, axis_order: list[str] | None = None,
                   axes_baseline: dict | None = None) -> pd.DataFrame:
    """Compose an Axis / Answer / Ground Truth / Diff / Baseline table.

    Handles missing sides gracefully so the operator sees whatever's available:
      - Any side (Answer / GT / Baseline) that is entirely empty is dropped.
      - Diff (A - GT), Diff (A - B), Diff (GT - B) are each dropped when the
        two sides needed to compute them aren't both present.
      - Order falls back to GT / Baseline keys when no `axis_order` is given
        and Answer is missing.
    """
    axes    = axes    or {}
    axes_gt = axes_gt or {}
    axes_bl = axes_baseline or {}
    if axis_order:
        order = axis_order
    elif axes:
        order = list(axes.keys())
    elif axes_gt:
        order = list(axes_gt.keys())
    else:
        order = list(axes_bl.keys())

    rows = []
    for a in order:
        _has_a = a in axes
        _has_g = a in axes_gt
        _has_b = a in axes_bl
        if not _has_a and not _has_g and not _has_b:
            continue
        _ans = axes.get(a)    if _has_a else None
        _gt  = axes_gt.get(a) if _has_g else None
        _bl  = axes_bl.get(a) if _has_b else None
        _diff_ag = (round(_ans - _gt, 3)
                     if isinstance(_ans, (int, float))
                     and isinstance(_gt,  (int, float)) else None)
        _diff_ab = (round(_ans - _bl, 3)
                     if isinstance(_ans, (int, float))
                     and isinstance(_bl,  (int, float)) else None)
        _diff_gb = (round(_gt - _bl, 3)
                     if isinstance(_gt,  (int, float))
                     and isinstance(_bl,  (int, float)) else None)
        rows.append({
            "Axis": a,
            "Answer(AI)": _ans,
            "Ground Truth": _gt,
            "Diff (A - GT)": _diff_ag,
            "Baseline":    _bl,
            "Diff (A - B)": _diff_ab,
            "Diff (GT - B)": _diff_gb,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Drop any column that is entirely empty. Diff columns require BOTH
    # constituent sides to have data on at least one axis.
    if df["Answer(AI)"].isna().all():
        df = df.drop(columns=["Answer(AI)"])
    if df["Ground Truth"].isna().all():
        df = df.drop(columns=["Ground Truth"])
    if df["Baseline"].isna().all():
        df = df.drop(columns=["Baseline"])
    def _drop_diff(col, need_a, need_b):
        if (need_a not in df.columns or need_b not in df.columns
                or df[col].isna().all()):
            df.drop(columns=[col], inplace=True)
    _drop_diff("Diff (A - GT)", "Answer(AI)",   "Ground Truth")
    _drop_diff("Diff (A - B)",  "Answer(AI)",   "Baseline")
    _drop_diff("Diff (GT - B)", "Ground Truth", "Baseline")
    # Sort by whichever side is available when no canonical axis order was set.
    if axis_order is None:
        for _preferred in ("Answer(AI)", "Ground Truth", "Baseline"):
            if _preferred in df.columns:
                df = df.sort_values(_preferred, ascending=False)
                break
    return df


# --------------------------------------------------------------------------
# 愛着 (Attachment) — 4-type classification (Secure / Preoccupied /
# Dismissing-avoidant / Fearful-avoidant) derived from the (Avoidance,
# Anxiety) 2-axis space.
#
# Following Bartholomew & Horowitz (1991) 4-category model:
#   Secure               = low avoidance + low anxiety   (自己肯定+他者肯定)
#   Preoccupied          = low avoidance + high anxiety  (他者志向+自己不信)
#   Dismissing-avoidant  = high avoidance + low anxiety  (自立志向+他者不信)
#   Fearful-avoidant     = high avoidance + high anxiety (両方不安)
#
# The four values form a probability-like distribution (they sum to 1) so the
# renderer can present them as compatible bars. Extreme scores yield a clear
# "pure type"; middle-of-scale scores spread across all four.
# --------------------------------------------------------------------------

_ATTACHMENT_TYPES = [
    ("Secure",              "安定型",         "自己肯定 + 他者肯定"),
    ("Preoccupied",         "とらわれ型",     "他者志向 + 自己不信"),
    ("Dismissing-avoidant", "軽視・回避型",   "自立志向 + 他者不信"),
    ("Fearful-avoidant",    "恐れ・回避型",   "両方不安"),
]


# --------------------------------------------------------------------------
# 愛着 — Categorical style classification (Bartholomew's 4-category model)
# --------------------------------------------------------------------------
# The Excel now scores 9 items on the 1-7 Likert scale:
#   Q1-Q6 → Avoidance (回避), Q7-Q9 → Anxiety (不安)
# From the raw 1-7 averages, we assign one of four styles using a hard
# threshold at 4 (the midpoint of the 1-7 scale):
#   Secure (安定型)               = av<4 & an<4
#   Anxious-Preoccupied (不安型)   = av<4 & an≥4
#   Dismissive-Avoidant (回避型)    = av≥4 & an<4
#   Fearful-Avoidant (恐れ回避型)   = av≥4 & an≥4
#
# Each style ships with a compact inline SVG illustration so the dashboard
# renders self-contained (no external assets to ship).

_ATTACHMENT_STYLES = {
    "secure": {
        "jp": "安定型",
        "en": "Secure",
        "bg":     "#e8f5e9",
        "border": "#4CAF50",
        "text":   "#1B5E20",
        "description":
            "親密さと自立のバランスが取れており、人に頼ることにも、"
            "頼られることにも抵抗が少ない。関係が安定しやすい。",
    },
    "anxious": {
        "jp": "不安型",
        "en": "Anxious-Preoccupied",
        "bg":     "#fff8e1",
        "border": "#FFA000",
        "text":   "#E65100",
        "description":
            "人との親密さを強く求める一方、見捨てられることへの不安が強い。"
            "相手の気持ちを頻繁に確認したくなったり、関係の変化に敏感になりやすい。",
    },
    "dismissive": {
        "jp": "回避型",
        "en": "Dismissive-Avoidant",
        "bg":     "#e3f2fd",
        "border": "#1976D2",
        "text":   "#0D47A1",
        "description":
            "自立や自己完結を重視し、人に頼ったり本音を見せたりすることに"
            "抵抗を感じやすい。表面的には安定して見えるが、親密さを避ける傾向がある。",
    },
    "fearful": {
        "jp": "恐れ回避型",
        "en": "Fearful-Avoidant",
        "bg":     "#f3e5f5",
        "border": "#7B1FA2",
        "text":   "#4A148C",
        "description":
            "親密さを求める気持ちと、傷つくことへの恐れの両方が強い。"
            "人に近づきたい気持ちと距離を取りたい気持ちの間で揺れ動きやすい。",
    },
}


# Inline SVG illustrations (one per style). ViewBox 200×140 so all four
# render at the same size. Content is intentionally minimal — abstract
# figures that convey the underlying relational dynamic at a glance.
_ATTACHMENT_STYLE_SVG = {
    "secure": (
        '<svg viewBox="0 0 200 140" xmlns="http://www.w3.org/2000/svg" '
        'style="width:200px;height:140px;">'
        # Two "people" (soft circles) balanced
        '<circle cx="60"  cy="80" r="28" fill="#4CAF50" opacity="0.25" '
        'stroke="#1B5E20" stroke-width="2"/>'
        '<circle cx="140" cy="80" r="28" fill="#4CAF50" opacity="0.25" '
        'stroke="#1B5E20" stroke-width="2"/>'
        # Heart connecting them
        '<path d="M100,55 C93,45 80,50 82,62 C84,72 100,82 100,82 C100,82 '
        '116,72 118,62 C120,50 107,45 100,55 Z" fill="#E91E63"/>'
        # Balance line
        '<line x1="88" y1="80" x2="112" y2="80" stroke="#1B5E20" '
        'stroke-width="2" stroke-dasharray="4,2"/>'
        '<text x="100" y="130" text-anchor="middle" fill="#1B5E20" '
        'font-size="13" font-weight="bold">親密 + 自立</text>'
        '</svg>'
    ),
    "anxious": (
        '<svg viewBox="0 0 200 140" xmlns="http://www.w3.org/2000/svg" '
        'style="width:200px;height:140px;">'
        # Reaching figure (warm color)
        '<circle cx="55" cy="80" r="28" fill="#FFA000" opacity="0.30" '
        'stroke="#E65100" stroke-width="2"/>'
        # Distant figure (neutral)
        '<circle cx="150" cy="80" r="24" fill="#BDBDBD" opacity="0.35" '
        'stroke="#616161" stroke-width="2"/>'
        # Reaching arrow toward the neutral figure
        '<line x1="82" y1="80" x2="118" y2="80" stroke="#E65100" '
        'stroke-width="3"/>'
        '<polygon points="116,74 126,80 116,86" fill="#E65100"/>'
        # Anxiety question marks
        '<text x="35" y="35" font-size="22" fill="#E65100" '
        'font-weight="bold">?</text>'
        '<text x="65" y="30" font-size="16" fill="#E65100">?</text>'
        '<text x="100" y="130" text-anchor="middle" fill="#E65100" '
        'font-size="13" font-weight="bold">求める · 不安</text>'
        '</svg>'
    ),
    "dismissive": (
        '<svg viewBox="0 0 200 140" xmlns="http://www.w3.org/2000/svg" '
        'style="width:200px;height:140px;">'
        # Wall around the self
        '<rect x="15" y="45" width="90" height="70" fill="#E3F2FD" '
        'stroke="#1976D2" stroke-width="3" stroke-dasharray="5,3"/>'
        # Self (inside the wall, self-contained)
        '<circle cx="60" cy="80" r="20" fill="#1976D2" opacity="0.35" '
        'stroke="#0D47A1" stroke-width="2"/>'
        # Distant other (small, outside)
        '<circle cx="165" cy="80" r="18" fill="#BDBDBD" opacity="0.35" '
        'stroke="#616161" stroke-width="2"/>'
        # Barrier line
        '<line x1="115" y1="45" x2="115" y2="115" stroke="#0D47A1" '
        'stroke-width="2" stroke-dasharray="3,2"/>'
        '<text x="100" y="130" text-anchor="middle" fill="#0D47A1" '
        'font-size="13" font-weight="bold">自立 · 距離</text>'
        '</svg>'
    ),
    "fearful": (
        '<svg viewBox="0 0 200 140" xmlns="http://www.w3.org/2000/svg" '
        'style="width:200px;height:140px;">'
        # Central figure (torn)
        '<circle cx="100" cy="75" r="28" fill="#7B1FA2" opacity="0.25" '
        'stroke="#4A148C" stroke-width="2"/>'
        # Two-way arrows (approach + retreat)
        '<line x1="30" y1="75" x2="65" y2="75" stroke="#4A148C" stroke-width="3"/>'
        '<polygon points="33,70 25,75 33,80" fill="#4A148C"/>'
        '<line x1="135" y1="75" x2="170" y2="75" stroke="#4A148C" stroke-width="3"/>'
        '<polygon points="167,70 175,75 167,80" fill="#4A148C"/>'
        # Question / worry marks above the figure
        '<text x="90" y="35" font-size="20" fill="#4A148C" '
        'font-weight="bold">?</text>'
        '<text x="105" y="35" font-size="20" fill="#4A148C" '
        'font-weight="bold">!</text>'
        '<text x="100" y="130" text-anchor="middle" fill="#4A148C" '
        'font-size="12" font-weight="bold">近づきたい · 距離を取りたい</text>'
        '</svg>'
    ),
}


def _classify_attachment_style(avoidance_raw: float | None,
                                 anxiety_raw: float | None) -> str | None:
    """Return one of {'secure','anxious','dismissive','fearful'} based on
    Bartholomew's 4-quadrant model, using threshold=4 on the 1-7 raw scale.
    Returns None when either input is missing (unable to classify)."""
    if avoidance_raw is None or anxiety_raw is None:
        return None
    _hi_av = avoidance_raw >= 4.0
    _hi_an = anxiety_raw   >= 4.0
    if not _hi_av and not _hi_an: return "secure"
    if not _hi_av and _hi_an:      return "anxious"
    if _hi_av and not _hi_an:      return "dismissive"
    return "fearful"


def _attachment_raw_scores(axes_avg: dict) -> tuple[float | None, float | None]:
    """Recover the raw 1-7 (Avoidance, Anxiety) averages from the
    n/7-normalized `axes_avg`. Returns (None, None) for missing axes."""
    _av = axes_avg.get("Avoidance") if axes_avg else None
    _an = axes_avg.get("Anxiety")   if axes_avg else None
    _av_raw = round(_av * 7.0, 2) if isinstance(_av, (int, float)) else None
    _an_raw = round(_an * 7.0, 2) if isinstance(_an, (int, float)) else None
    return _av_raw, _an_raw


def _compute_attachment_types(axes_avg: dict) -> dict:
    """Compute (Secure / Preoccupied / Dismissing-avoidant / Fearful-avoidant)
    fitness from a 6-dim `axes_avg` where axis keys use the English labels
    parsed from `Memo` (e.g. `Avoidance`, `Anxiety`).

    Returns None when either Avoidance or Anxiety is missing (no data)."""
    _av = axes_avg.get("Avoidance")
    _an = axes_avg.get("Anxiety")
    if _av is None or _an is None:
        return {}
    _av = max(0.0, min(1.0, float(_av)))
    _an = max(0.0, min(1.0, float(_an)))
    return {
        "Secure":              round((1.0 - _av) * (1.0 - _an), 3),
        "Preoccupied":         round((1.0 - _av) * _an,         3),
        "Dismissing-avoidant": round(_av * (1.0 - _an),         3),
        "Fearful-avoidant":    round(_av * _an,                 3),
    }


def _render_sociability_group_section(data: dict) -> None:
    """Render Leach's 2-group aggregation for 社会性 below the standard
    5-dim radar. Mirrors the Schwartz 4-group table structure (Group /
    Members / Answer(AI) / Ground Truth / Cos / MAE) so operators see both
    the raw dimensional profile and the higher-order construct summary.

    Skipped silently when no axes were scored — the standard radar's own
    empty-state hint already tells the operator what's missing.
    """
    import streamlit as st
    axes    = data.get("axes_avg")    or {}
    axes_gt = data.get("axes_avg_gt") or {}
    axes_bl = data.get("axes_avg_baseline") or {}
    if not axes and not axes_gt and not axes_bl:
        return
    _has_a  = bool(axes)
    _has_g  = bool(axes_gt)
    _has_b  = bool(axes_bl)

    st.markdown("#### 2グループ集約 (Leach's Hierarchical Multicomponent Model)")

    def _f(v):
        return f"{v:.3f}" if isinstance(v, (int, float)) else "-"

    def _diff(x, y):
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return round(x - y, 3)
        return None

    _rows = []
    for _label, _members, _desc in _SOCIABILITY_GROUPS:
        _vals_a = [axes.get(m)    for m in _members if m in axes]
        _vals_g = [axes_gt.get(m) for m in _members if m in axes_gt]
        _vals_b = [axes_bl.get(m) for m in _members if m in axes_bl]
        _avg_a = round(sum(_vals_a) / len(_vals_a), 3) if _vals_a else None
        _avg_g = round(sum(_vals_g) / len(_vals_g), 3) if _vals_g else None
        _avg_b = round(sum(_vals_b) / len(_vals_b), 3) if _vals_b else None
        _sub_a = {m: axes.get(m, 0.0)    for m in _members} if _has_a else {}
        _sub_g = {m: axes_gt.get(m, 0.0) for m in _members} if _has_g else {}
        _cos = _dict_cos(_sub_a, _sub_g) if _sub_a and _sub_g else None
        _mae = _mean_abs_err(_sub_a, _sub_g) if _sub_a and _sub_g else None
        _row = {
            "Group":    _label,
            "Members": " / ".join(_members),
        }
        if _has_a:
            _row["Answer(AI)"] = _avg_a
        if _has_g:
            _row["Ground Truth"] = _avg_g
        if _has_a and _has_g:
            _row["Diff (A - GT)"] = _diff(_avg_a, _avg_g)
            _row["Cos 類似度 (A↔GT)"] = _f(_cos)
            _row["MAE (各項目誤差)"]  = _f(_mae)
        if _has_b:
            _row["Baseline"] = _avg_b
            if _has_a:
                _row["Diff (A - B)"]  = _diff(_avg_a, _avg_b)
            if _has_g:
                _row["Diff (GT - B)"] = _diff(_avg_g, _avg_b)
        _rows.append(_row)

    _df = pd.DataFrame(_rows)
    st.dataframe(_df, hide_index=True, use_container_width=True)

    st.markdown("**各グループの解説:**")
    for i, (_label, _members, _desc) in enumerate(_SOCIABILITY_GROUPS):
        _row = _rows[i]
        _a_val = _row.get("Answer(AI)")
        _g_val = _row.get("Ground Truth")
        _delta = ""
        if isinstance(_a_val, (int, float)) and isinstance(_g_val, (int, float)):
            _d = _a_val - _g_val
            if abs(_d) >= 0.1:
                _delta = f"  *(GT との差: {_d:+.2f})*"
        # Prefer showing Answer's score; if Answer is missing, fall back to
        # GT so the header still carries a numeric summary.
        if isinstance(_a_val, (int, float)):
            _ans_s = f"score={_a_val:.2f}"
        elif isinstance(_g_val, (int, float)):
            _ans_s = f"GT score={_g_val:.2f}"
        else:
            _ans_s = ""
        # "自己カテゴリー化(Self-stereotyping) / 集団との類似性(In-group homogeneity) が該当"
        # 形式のメンバー軸行 (価値観の 4 グループ解説と同じパターン)。
        _member_line = " / ".join(
            f"{_SOCIABILITY_JP.get(m, m)}({m})" for m in _members
        )
        st.markdown(
            f"**{i+1}. {_label}**  *{_ans_s}*{_delta}  \n"
            f"  {_desc}  \n"
            f"  *{_member_line}が該当*"
        )


def _render_attachment_style_dashboard(data: dict) -> None:
    """Dedicated 愛着 renderer for the 2-axis (Avoidance, Anxiety) → 4-style
    workflow. Replaces the standard Likert radar for this category because
    the current questionnaire only has 2 dimensions (radar needs ≥3).

    Shows:
      1. Raw 1-7 score comparison (Avoidance / Anxiety) for Answer(AI) vs GT
      2. Classified Attachment Style with an inline SVG illustration
         side-by-side for A / GT so operators can see whether the style
         matches or diverges.
    """
    import streamlit as st
    _axes    = data.get("axes_avg")    or {}
    _axes_gt = data.get("axes_avg_gt") or {}
    _axes_bl = data.get("axes_avg_baseline") or {}

    _av_a, _an_a = _attachment_raw_scores(_axes)
    _av_g, _an_g = _attachment_raw_scores(_axes_gt)
    _av_b, _an_b = _attachment_raw_scores(_axes_bl)

    _style_a = _classify_attachment_style(_av_a, _an_a)
    _style_g = _classify_attachment_style(_av_g, _an_g)
    _style_b = _classify_attachment_style(_av_b, _an_b)

    # ---- Raw score comparison table ---------------------------------------
    st.markdown("#### 回避 / 不安 スコアと Attachment Style")

    def _fmt(v):
        return f"{v:.2f}" if isinstance(v, (int, float)) else "-"
    def _hilo(v):
        if not isinstance(v, (int, float)): return "-"
        return "高 (≥4)" if v >= 4.0 else "低 (<4)"
    def _style_label(s):
        if s is None: return "-"
        _m = _ATTACHMENT_STYLES[s]
        return f"{_m['jp']} ({_m['en']})"

    def _fmt_diff(a, g):
        if isinstance(a, (int, float)) and isinstance(g, (int, float)):
            return f"{a - g:+.2f}"
        return "-"

    _has_a = _av_a is not None or _an_a is not None
    _has_g = _av_g is not None or _an_g is not None
    _has_b = _av_b is not None or _an_b is not None

    def _row(who: str, av, an, style):
        return {"": who,
                "回避 (Avoidance)": _fmt(av),
                "回避 高低":        _hilo(av),
                "不安 (Anxiety)":   _fmt(an),
                "不安 高低":        _hilo(an),
                "Attachment Style": _style_label(style)}

    def _diff_row(who: str, av_x, an_x, av_y, an_y):
        return {"": who,
                "回避 (Avoidance)": _fmt_diff(av_x, av_y),
                "回避 高低":        "-",
                "不安 (Anxiety)":   _fmt_diff(an_x, an_y),
                "不安 高低":        "-",
                "Attachment Style": "-"}

    _rows = []
    if _has_a:
        _rows.append(_row("Answer(AI)",   _av_a, _an_a, _style_a))
    if _has_g:
        _rows.append(_row("Ground Truth", _av_g, _an_g, _style_g))
    if _has_a and _has_g:
        # Diff row: only 回避 / 不安 (per operator spec — style is categorical
        # so a numeric diff isn't meaningful, and 高低 is a discrete band).
        _rows.append(_diff_row("Diff (A - GT)", _av_a, _an_a, _av_g, _an_g))
    if _has_b:
        _rows.append(_row("Baseline",     _av_b, _an_b, _style_b))
        if _has_a:
            _rows.append(_diff_row("Diff (A - B)",  _av_a, _an_a, _av_b, _an_b))
        if _has_g:
            _rows.append(_diff_row("Diff (GT - B)", _av_g, _an_g, _av_b, _an_b))
    st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)
    st.caption(
        "回避 = Q1〜Q6 の平均 (1〜7)、不安 = Q7〜Q9 の平均 (1〜7)。"
        " 両得点それぞれ 4 未満 (低) か 4 以上 (高) かで 4 型に分類します。"
    )

    # ---- Style illustration cards side by side (A vs GT) ------------------
    _c1, _c2 = st.columns(2)
    for _col, _who, _style_id in [(_c1, "Answer(AI)", _style_a),
                                     (_c2, "Ground Truth", _style_g)]:
        if _style_id is None:
            _col.caption(f"**{_who}**: (未分類)")
            continue
        _meta = _ATTACHMENT_STYLES[_style_id]
        _svg  = _ATTACHMENT_STYLE_SVG[_style_id]
        _card = (
            f'<div style="background:{_meta["bg"]};'
            f'border:1px solid {_meta["border"]};padding:12px 14px;'
            f'border-radius:8px;">'
            f'<div style="font-size:0.8em;color:{_meta["text"]};'
            f'font-weight:600;margin-bottom:4px;">{_who}</div>'
            f'<div style="font-size:1.1em;color:{_meta["text"]};'
            f'font-weight:700;">{_meta["jp"]} '
            f'<span style="font-size:0.85em;font-weight:500;">'
            f'({_meta["en"]})</span></div>'
            f'<div style="text-align:center;margin:10px 0;">{_svg}</div>'
            f'<div style="font-size:0.85em;color:#333;line-height:1.5;">'
            f'{_meta["description"]}</div>'
            f'</div>'
        )
        _col.markdown(_card, unsafe_allow_html=True)

    # ---- Agreement summary (if GT present) --------------------------------
    # Only surface an affirmative match ("✓ ... いずれも 〜 に分類") — the
    # comparison table above already makes any style mismatch obvious via
    # the side-by-side illustration cards, and rendering a mismatch warning
    # here read like an error banner (per operator feedback).
    if (_axes_gt and _style_a is not None and _style_g is not None
            and _style_a == _style_g):
        st.success(
            f"✓ Answer(AI) と Ground Truth はいずれも "
            f"**{_ATTACHMENT_STYLES[_style_a]['jp']} "
            f"({_ATTACHMENT_STYLES[_style_a]['en']})** に分類されました。"
        )


def _render_attachment_type_section(data: dict) -> None:
    """Render the 4-type attachment classification below the standard 6-dim
    radar. Shows a bars-side-by-side comparison of Answer vs GT fitness for
    each of the four types.

    Skipped silently when neither Answer nor GT contributed Avoidance /
    Anxiety scores — the standard radar already communicated that."""
    import streamlit as st
    _axes_ans = data.get("axes_avg") or {}
    _axes_gt  = data.get("axes_avg_gt") or {}
    _types_ans = _compute_attachment_types(_axes_ans)
    _types_gt  = _compute_attachment_types(_axes_gt)
    if not _types_ans and not _types_gt:
        return

    st.markdown("#### 愛着の 4 型分類 (Secure / Preoccupied / Dismissing / Fearful)")
    st.caption(
        "回避 (Avoidance) × 不安 (Anxiety) の 2 軸から算出した 4 型の合致度 (合計 1.0)。"
        " 極端なスコアほど 1 つの型に集中し、中央付近のスコアほど分散します。"
    )

    _c1, _c2 = st.columns([3, 2])

    # ---- Bar chart ---------------------------------------------------------
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    import numpy as _np
    _labels = [_jp for _en, _jp, _ in _ATTACHMENT_TYPES]
    _vals_ans = [_types_ans.get(_en, 0.0) for _en, _, _ in _ATTACHMENT_TYPES]
    _vals_gt  = [_types_gt.get(_en, 0.0)  for _en, _, _ in _ATTACHMENT_TYPES]
    _has_ans = any(v > 0 for v in _vals_ans)
    _has_gt  = any(v > 0 for v in _vals_gt)

    _fig, _ax = _plt.subplots(figsize=(6, 3.2))
    _x = _np.arange(len(_labels))
    _w = 0.38 if _has_ans and _has_gt else 0.6
    if _has_ans:
        _off = -_w/2 if _has_gt else 0
        _ax.bar(_x + _off, _vals_ans, _w, color="#1565C0", alpha=0.85, label="Answer(AI)")
    if _has_gt:
        _off = _w/2 if _has_ans else 0
        _ax.bar(_x + _off, _vals_gt, _w, color="#2E7D32", alpha=0.85, label="Ground Truth")
    _ax.set_xticks(_x)
    try:
        _ax.set_xticklabels(_labels, fontfamily="IPAexGothic", fontsize=9)
    except Exception:
        _ax.set_xticklabels(_labels, fontsize=9)
    _ax.set_ylim(0, 1.0)
    _ax.set_ylabel("Fitness")
    _ax.grid(True, alpha=0.3, axis="y")
    if _has_ans and _has_gt:
        try:
            _ax.legend(loc="upper right", fontsize=8,
                        prop={"family": "IPAexGothic", "size": 8})
        except Exception:
            _ax.legend(loc="upper right", fontsize=8)
    _plt.tight_layout()
    with _c1:
        st.pyplot(_fig)
        _plt.close(_fig)

    # ---- Table -------------------------------------------------------------
    _rows = []
    for _en, _jp, _desc in _ATTACHMENT_TYPES:
        _row = {"型": f"{_jp} ({_en})", "説明": _desc}
        if _has_ans:
            _row["Answer(AI)"] = f"{_types_ans.get(_en, 0.0):.3f}"
        if _has_gt:
            _row["Ground Truth"] = f"{_types_gt.get(_en, 0.0):.3f}"
        _rows.append(_row)
    _df = pd.DataFrame(_rows)
    with _c2:
        st.markdown("**4 型合致度:**")
        st.dataframe(_df, hide_index=True, use_container_width=True)

    # Highlight the dominant type for both sides (helpful summary)
    if _has_ans:
        _dom_ans = max(_ATTACHMENT_TYPES,
                        key=lambda t: _types_ans.get(t[0], 0.0))
        st.caption(f"**Answer(AI) の優位型**: {_dom_ans[1]} ({_dom_ans[0]}) — {_dom_ans[2]}")
    if _has_gt:
        _dom_gt = max(_ATTACHMENT_TYPES,
                       key=lambda t: _types_gt.get(t[0], 0.0))
        st.caption(f"**Ground Truth の優位型**: {_dom_gt[1]} ({_dom_gt[0]}) — {_dom_gt[2]}")


def _render_category(cat: str, data: dict) -> None:
    import streamlit as st
    meta = data.get("meta") or {}
    st.markdown(f"### {cat}")
    if meta.get("theory"):
        st.caption(f"理論: **{meta['theory']}**")

    # Prominent Cos-similarity metric at the very top of the section
    # (same number that appears in the summary radar for this category).
    # For 動機 this also surfaces BPNSFS / MWMS sub-scores.
    _render_cos_metric_strip(cat, data)
    # meta["items"] (the Excel `評価項目` column) is intentionally NOT rendered
    # here — the axis enumeration duplicates what the radar / score table / group
    # aggregation panels already show. Hiding it keeps the section header clean.

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
    if cat == "愛着":
        # Dedicated: only 2 dimensions (Avoidance / Anxiety) so a radar isn't
        # useful; show raw 1-7 score comparison + classified style with an
        # inline illustration for each of Answer(AI) and Ground Truth.
        _render_attachment_style_dashboard(data)
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

    axes    = data.get("axes_avg")    or {}
    axes_gt = data.get("axes_avg_gt") or {}
    # Baseline participates only in categories where the group profile is
    # a Likert-style axis vector (特性 / 価値観 / 動機 / 社会性). 人格形成 /
    # 目標 compare specific episodes, so they don't take a Baseline trace.
    axes_bl = data.get("axes_avg_baseline") or {}
    if axes or axes_gt or axes_bl:
        # Prefer a canonical axis order when the category has one registered
        # (e.g. 特性 = OCEAN, 社会性 = Self-Definition then Self-Investment).
        # Unknown axes fall to the end so nothing is silently dropped —
        # including axes that appear only on the GT or Baseline side.
        _canonical_order = _CATEGORY_AXIS_ORDER.get(cat)
        _seen = set(axes.keys()) | set(axes_gt.keys()) | set(axes_bl.keys())
        if _canonical_order:
            labels_order = ([k for k in _canonical_order if k in _seen]
                              + [k for k in _seen if k not in _canonical_order])
        else:
            labels_order = (list(axes.keys())
                              + [k for k in axes_gt if k not in axes]
                              + [k for k in axes_bl
                                    if k not in axes and k not in axes_gt])

        col1, col2 = st.columns([3, 2])
        if len(labels_order) >= 3:
            # Radar uses whichever side has values; if only GT has data we
            # show it as the primary trace rather than an empty overlay.
            if axes:
                vals    = [axes.get(k, 0.0)    for k in labels_order]
                vals_gt = [axes_gt.get(k, 0.0) for k in labels_order] if axes_gt else None
                _n = data.get("scored", 0)
            elif axes_gt:
                vals    = [axes_gt.get(k, 0.0) for k in labels_order]
                vals_gt = None
                _n = data.get("scored_gt", 0)
            else:
                vals    = [axes_bl.get(k, 0.0) for k in labels_order]
                vals_gt = None
                _n = data.get("scored_baseline", 0)
            vals_bl = [axes_bl.get(k, 0.0) for k in labels_order] if axes_bl else None
            fig = _radar(labels_order, vals,
                          f"{cat} (n={_n})", values_gt=vals_gt,
                          values_baseline=vals_bl)
            if fig is not None:
                with col1:
                    import streamlit as _st
                    _st.pyplot(fig)
                    import matplotlib.pyplot as _plt
                    _plt.close(fig)
        with col2:
            st.markdown("**Scores (0–1):**")
            st.dataframe(
                _score_table(axes, axes_gt, axis_order=labels_order,
                              axes_baseline=axes_bl),
                hide_index=True, use_container_width=True,
            )
        _scored_caption = f"scored: **{data['scored']}**  /  unscored: **{data['unscored']}**"
        if data.get("scored_gt"):
            _scored_caption += f"  /  GT scored: **{data['scored_gt']}**"
        st.caption(_scored_caption)

        # 社会性 gets a Leach-style 2-group aggregation table below the
        # 5-dim radar (Self-Definition vs Self-Investment).
        if cat == "社会性":
            _render_sociability_group_section(data)

        # 愛着 is handled by its dedicated dashboard above; the standard
        # Likert path is intentionally never reached for it.
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
            if n.get("baseline"):
                st.markdown(f"- B: {n['baseline']}")


# --------------------------------------------------------------------------
# Category-specific renderers
# --------------------------------------------------------------------------

def _render_values_category(data: dict) -> None:
    """Schwartz Values: 10-axis dual-layer radar + 4-group aggregation with
    priority commentary."""
    import streamlit as st
    axes    = data.get("axes_avg") or {}
    axes_gt = data.get("axes_avg_gt") or {}
    axes_bl = data.get("axes_avg_baseline") or {}
    if not axes and not axes_gt and not axes_bl:
        st.info("価値観の Answer / Ground Truth がまだ採点できていません。Memo は `Self-Direction（自律）vs Conformity（順応）` の形式で、Answer 列に `はい/どちらでもない/いいえ` を入れてください。")
        return
    _has_a = bool(axes)
    _has_g = bool(axes_gt)
    _has_b = bool(axes_bl)

    # --- 10-axis radar + table ---
    labels = [f"{v}\n({_SCHWARTZ_JP[v]})" for v in _SCHWARTZ_10]
    # Radar: primary trace is whichever side has values. When both exist the
    # GT overlay is drawn on top of the Answer trace; Baseline is overlaid
    # in orange when a benchmark column was supplied.
    if _has_a:
        vals    = [axes.get(v, 0.0) for v in _SCHWARTZ_10]
        vals_gt = [axes_gt.get(v, 0.0) for v in _SCHWARTZ_10] if _has_g else None
    elif _has_g:
        vals    = [axes_gt.get(v, 0.0) for v in _SCHWARTZ_10]
        vals_gt = None
    else:
        vals    = [axes_bl.get(v, 0.0) for v in _SCHWARTZ_10]
        vals_gt = None
    vals_bl = [axes_bl.get(v, 0.0) for v in _SCHWARTZ_10] if _has_b else None
    col1, col2 = st.columns([3, 2])
    fig = _radar(labels, vals, f"価値観 (10値)", values_gt=vals_gt,
                  values_baseline=vals_bl)
    if fig is not None:
        with col1:
            st.pyplot(fig)
            import matplotlib.pyplot as _plt
            _plt.close(fig)
    with col2:
        st.markdown("**10値スコア (Answer(AI) / Ground Truth / Baseline):**")
        st.dataframe(
            _score_table(axes, axes_gt, axis_order=_SCHWARTZ_10,
                          axes_baseline=axes_bl),
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
        # Per-side aggregates are None when that side has no data at all for
        # this group's members — the table below hides such columns entirely.
        ms    = [axes.get(m)    for m in members if m in axes]
        ms_gt = [axes_gt.get(m) for m in members if m in axes_gt]
        ms_bl = [axes_bl.get(m) for m in members if m in axes_bl]
        avg    = round(sum(ms)    / len(ms),    3) if ms    else None
        avg_gt = round(sum(ms_gt) / len(ms_gt), 3) if ms_gt else None
        avg_bl = round(sum(ms_bl) / len(ms_bl), 3) if ms_bl else None
        # Group-restricted Cos / MAE — only when BOTH sides have data for
        # every member axis (any missing member breaks the comparison).
        _sub_ans = {m: axes.get(m, 0.0)    for m in members} if axes    else {}
        _sub_gt  = {m: axes_gt.get(m, 0.0) for m in members} if axes_gt else {}
        _cos = _dict_cos(_sub_ans, _sub_gt) if _sub_ans and _sub_gt else None
        _mae = _mean_abs_err(_sub_ans, _sub_gt) if _sub_ans and _sub_gt else None
        groups.append({"label": label, "members": members, "desc": desc,
                        "answer": avg, "gt": avg_gt, "baseline": avg_bl,
                        "cos": round(_cos, 3) if _cos is not None else None,
                        "mae": _mae})

    def _f(x): return f"{x:.3f}" if isinstance(x, (int, float)) else "-"

    def _diff(x, y):
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return round(x - y, 3)
        return None

    _rows = []
    for i, g in enumerate(groups):
        _row = {
            "No": i + 1,
            "Group": g["label"],
            "Members": " / ".join(g["members"]),
        }
        if _has_a:
            _row["Answer(AI)"] = g["answer"]
        if _has_g:
            _row["Ground Truth"] = g["gt"]
        if _has_a and _has_g:
            _row["Diff (A - GT)"] = _diff(g["answer"], g["gt"])
            _row["Cos 類似度 (A↔GT)"] = _f(g["cos"])
            _row["MAE (各項目誤差)"]  = _f(g["mae"])
        if _has_b:
            _row["Baseline"] = g["baseline"]
            if _has_a:
                _row["Diff (A - B)"]  = _diff(g["answer"], g["baseline"])
            if _has_g:
                _row["Diff (GT - B)"] = _diff(g["gt"],     g["baseline"])
        _rows.append(_row)
    st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)

    st.markdown("**各グループの解説:**")
    for i, g in enumerate(groups):
        _delta = ""
        if isinstance(g["answer"], (int, float)) and isinstance(g["gt"], (int, float)):
            _diff = g["answer"] - g["gt"]
            if abs(_diff) >= 0.1:
                _delta = f"  *(GT との差: {_diff:+.2f})*"
        # Score line shows whichever side is available (Answer preferred,
        # falls back to GT when Answer is missing).
        if isinstance(g["answer"], (int, float)):
            _score_s = f"score={g['answer']:.2f}"
        elif isinstance(g["gt"], (int, float)):
            _score_s = f"GT score={g['gt']:.2f}"
        else:
            _score_s = ""
        # "自律(Self-Direction) / 刺激(Stimulation)" 形式のメンバー軸行を
        # 各グループ解説の 3 行目に追加。10 値のどれがこのグループに属す
        # かをレーダー / 表を見なくても分かるようにするため。
        _member_line = " / ".join(
            f"{_SCHWARTZ_JP.get(m, m)}({m})" for m in g["members"]
        )
        st.markdown(
            f"**{i+1}. {g['label']}**  *{_score_s}*{_delta}  \n"
            f"  {g['desc']}  \n"
            f"  *{_member_line}が該当*"
        )


def _render_motivation_category(data: dict) -> None:
    """SDT-style Motivation: BPNSFS (3 net axes) + MWMS (6 subscales) — two
    side-by-side dual-layer radars with an optional Baseline overlay."""
    import streamlit as st
    bp    = data.get("bpnsfs_avg") or {}
    bp_gt = data.get("bpnsfs_avg_gt") or {}
    bp_bl = data.get("bpnsfs_avg_baseline") or {}
    mw    = data.get("mwms_avg") or {}
    mw_gt = data.get("mwms_avg_gt") or {}
    mw_bl = data.get("mwms_avg_baseline") or {}

    if not any([bp, bp_gt, bp_bl, mw, mw_gt, mw_bl]):
        st.info("動機の Answer / Ground Truth がまだ採点できていません。Memo は `BPNSFS：自律性・充足（Autonomy Satisfaction）` のような形式で、Answer 列に `はい/どちらでもない/いいえ` を入れてください。")
        return

    def _draw(section: str, axes_list: list[str], jp_map: dict,
              d_a: dict, d_g: dict, d_b: dict, title: str,
              c_left, c_right, empty_caption: str) -> None:
        if not (d_a or d_g or d_b):
            st.caption(empty_caption)
            return
        labels = [f"{a}\n({jp_map.get(a, '')})" for a in axes_list]
        if d_a:
            vals    = [d_a.get(a, 0.0) for a in axes_list]
            vals_gt = [d_g.get(a, 0.0) for a in axes_list] if d_g else None
        elif d_g:
            vals    = [d_g.get(a, 0.0) for a in axes_list]
            vals_gt = None
        else:
            vals    = [d_b.get(a, 0.0) for a in axes_list]
            vals_gt = None
        vals_bl = [d_b.get(a, 0.0) for a in axes_list] if d_b else None
        fig = _radar(labels, vals, title, values_gt=vals_gt,
                      values_baseline=vals_bl)
        if fig is not None:
            with c_left:
                st.pyplot(fig)
                import matplotlib.pyplot as _plt
                _plt.close(fig)
        with c_right:
            st.markdown("**スコア:**")
            st.dataframe(
                _score_table(d_a, d_g, axis_order=axes_list,
                              axes_baseline=d_b),
                hide_index=True, use_container_width=True,
            )

    # --- BPNSFS (3 axes — needs ≥3 for radar to be informative, 3 is OK) ---
    st.markdown("#### 基本的心理欲求 (BPNSFS)")
    c1, c2 = st.columns([3, 2])
    _draw("BPNSFS", _BPNSFS_AXES, _BPNSFS_JP, bp, bp_gt, bp_bl,
          "BPNSFS", c1, c2, "BPNSFS 軸の採点行がありません。")

    # --- MWMS (6 subscales) ---
    st.markdown("#### 仕事の動機づけ (MWMS)")
    c3, c4 = st.columns([3, 2])
    _draw("MWMS", _MWMS_AXES, _MWMS_JP, mw, mw_gt, mw_bl,
          "MWMS", c3, c4, "MWMS 軸の採点行がありません。")

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
    # 社会性 / 愛着 are now Likert 5-point selection style (Excel template
    # rewrite, 2026-07-02) — their axes come from `axes_avg` in the default
    # analyzer, so the LLM-rubric radar isn't needed here anymore.
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

    # The per-category "構造化分析 (LLM)" button was removed — Run analysis
    # auto-fires `Plugin.llm_augment()` which populates `_key` when an agent
    # is selected above Run analysis. Here we just consume the cached result.

    res = st.session_state.get(_key)
    if not res:
        st.caption(
            f"💡 {cat} の LLM 構造化分析はまだ実行されていません。"
            f" Run analysis の上でエージェントを選択してから *Run analysis* を再実行してください。"
            f" ({len(axes_config)} 軸の LLM スコア + 軸別講評が表示されます)"
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
        st.markdown("**軸別スコア (Answer(AI) / Ground Truth / 差分):**")
        # Per-axis is a scalar-per-side comparison, so Cos ≡ 1 - |Δ| and
        # MAE ≡ |Δ| — both redundant with Diff. We show A / GT / Diff only
        # here; the overall Cos + MAE stays on the top metric strip.
        _df = pd.DataFrame([
            {
                "Axis":         lbl,
                "Answer(AI)":   round(vals_a[i], 2),
                "Ground Truth": round(vals_gt[i], 2),
                "Diff (A - GT)": round(vals_a[i] - vals_gt[i], 2),
            }
            for i, lbl in enumerate(labels)
        ])
        st.dataframe(_df, hide_index=True, use_container_width=True)
        _mean_abs = round(sum(abs(vals_a[i] - vals_gt[i])
                                for i in range(len(labels))) / max(1, len(labels)), 3)
        st.caption(f"**軸別 |Diff| 平均: {_mean_abs:.3f}**  · "
                     "LLM が 0.00〜1.00 の連続値で意味的に採点")

    # ---- Per-axis narrative breakdown (Answer / GT / Comparison) ----
    # Each axis gets its own three-column card: what Answer(AI) says on this
    # axis, what Ground Truth says, and the head-to-head comparison. Each
    # cell is 100-200 chars per the LLM prompt contract.
    _notes = d.get("per_axis_notes") or {}
    if _notes and any(
        (n or {}).get("answer_note") or (n or {}).get("gt_note")
        or (n or {}).get("comparison") for n in _notes.values()
    ):
        st.markdown("#### 軸別の講評 (Answer(AI) / Ground Truth / 比較)")
        for jp, en, _desc in axes_config:
            _n = _notes.get(jp) or {}
            _ans_note = (_n.get("answer_note") or "").strip() or "_(講評なし)_"
            _gt_note  = (_n.get("gt_note")     or "").strip() or "_(講評なし)_"
            _cmp_note = (_n.get("comparison")  or "").strip() or "_(講評なし)_"
            # Header shows A / GT / signed diff — the semantically meaningful
            # trio for a scalar-per-axis LLM rubric. (Cos / MAE per axis is
            # redundant with |diff|; they belong on the section-level metric
            # strip, not here.)
            _av = float(ans_scores.get(jp, 0.0))
            _gv = float(gt_scores.get(jp, 0.0))
            _diff = _av - _gv
            st.markdown(
                f"##### {jp} ({en})  "
                f"*A={_av:.2f} / GT={_gv:.2f} · Diff (A - GT)={_diff:+.2f}*"
            )
            _c1, _c2, _c3 = st.columns(3)
            with _c1:
                st.markdown("**Answer(AI) の回答**")
                st.markdown(_ans_note)
            with _c2:
                st.markdown("**Ground Truth の回答**")
                st.markdown(_gt_note)
            with _c3:
                st.markdown("**比較**")
                st.markdown(_cmp_note)
            st.markdown("---")
    else:
        # Legacy fallback: LLM output didn't populate per_axis_notes (e.g. old
        # cached run). Show the aggregate similarities / differences instead
        # so the operator isn't stuck with a blank section.
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
    _prompt = res.get("prompt")
    if _prompt:
        with st.expander(
            f"🔎 LLM に与えたスコアリング指示 (prompt) — {cat}",
            expanded=False,
        ):
            st.caption(
                f"prompt length: {len(_prompt):,} 文字 · "
                "5 段階離散ルーブリック + 軸別独立採点を強制"
            )
            st.code(_prompt, language="markdown")
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


# --------------------------------------------------------------------------
# 目標 — new bird's-eye view + 2x2 grids (redesigned per operator spec)
# --------------------------------------------------------------------------

def _goal_row_html(g: dict, side: str) -> str:
    """Render a single goal as a bullet row with 4 colored H/M/L badges.

    Body text uses the ORIGINAL sentence from the Excel input:
      - side="answer" on a common goal → `answer_text`  (Answer's phrasing)
      - side="gt"     on a common goal → `gt_text`      (Ground Truth's phrasing)
      - side=either   on an own-only goal → plain `text` field
    The LLM-generated 1〜4 character `label` is kept as a small subtitle
    so relations in the harmony/conflict grid (which reference labels) can
    still be cross-checked visually.

    `side` also picks the rating field prefix: "answer" reads `answer_*` (or
    plain keys as fallback for answer_only), "gt" reads `gt_*`. Kept
    compact so several rows fit inside a 2x2 grid cell.
    """
    axes = [("importance", "大"), ("commitment", "本"),
            ("feasibility", "見"), ("achievement", "達")]
    _prefix_keys = [f"{side}_{k}" for k, _ in axes]
    _use_prefix = any(k in g for k in _prefix_keys)
    _badges = []
    for k, jp_short in axes:
        _val = g.get(f"{side}_{k}" if _use_prefix else k, "M")
        _lv = (_val or "M").upper()
        _col = _HML_COLORS.get(_lv, "#666")
        _lbl = _HML_LABEL.get(_lv, "?")
        _badges.append(
            f'<span style="display:inline-block;padding:0 4px;margin:0 2px 2px 0;'
            f'border-radius:3px;background:{_col};color:white;'
            f'font-size:0.7em;font-weight:600;line-height:1.4;">'
            f'{jp_short}: {_lbl}</span>'
        )
    _label = g.get("label", "?")
    # Body = original sentence. Fall back through the possible slots so a
    # common-goal-shape dict works with side="answer"/"gt", and an
    # own-only-shape dict (plain `text`) works with either side.
    _body = (g.get(f"{side}_text")
              or g.get("text")
              or g.get("answer_text")
              or g.get("gt_text")
              or "").strip() or "_(原文なし)_"
    return (
        f'<li style="margin-bottom:6px;line-height:1.4;">'
        f'<span style="font-weight:500;color:#111;">{_body}</span>'
        f' <span style="font-size:0.72em;color:#888;">(#{_label})</span>'
        f'<br/><span>{"".join(_badges)}</span>'
        f'</li>'
    )


def _goal_text_preview(g: dict, side: str, n: int = 20) -> str:
    """Shortened preview of a goal's original sentence for use in widget
    labels. Falls back through side-appropriate slots so it works for
    common (with `answer_text`/`gt_text`) and own-only (with plain `text`)
    entries. Truncated to `n` chars with an ellipsis when needed."""
    _body = (g.get(f"{side}_text")
              or g.get("text")
              or g.get("answer_text")
              or g.get("gt_text")
              or "").strip()
    if not _body:
        return "_(原文なし)_"
    _short = _body if len(_body) <= n else _body[:n] + "…"
    return _short


def _goals_effective_data(raw_llm_data: dict) -> dict:
    """Return the goals data with the operator's manual overrides applied.

    Reads the current overrides (split_common / promote_pairs) from
    session_state (same key `_render_goals_grid` writes to) and folds them
    into the raw LLM structure. Used by `_cat_cos_similarity` and the
    summary-tile extras so downstream scores always match what the
    per-category grid displays after the user clicks "変更を適用".
    Falls back to the raw data when session_state / streamlit isn't
    available (e.g. from `report_md`).
    """
    try:
        import streamlit as _st
        _ovkey = f"_pe_goals_overrides_{_PLUGIN_DIR.name}"
        _ov = _st.session_state.get(_ovkey)
    except Exception:
        _ov = None
    if not isinstance(_ov, dict):
        return raw_llm_data
    return _apply_goal_overrides(raw_llm_data, _ov)


def _normalise_promote_pairs(raw_pairs) -> list:
    """Coerce override pairs into 3-tuples `(a_idx, gt_kind, gt_idx)`.

    Backward-compat: legacy 2-tuples `(a, g)` are treated as
    `(a, "gt_only", g)`.  gt_kind ∈ {"gt_only", "common"} — the latter is
    a cross-pair where Answer#a matches the GT side of an LLM-common goal
    (supports N:N: the GT-common's GT weight is only counted once when
    scoring, via a `_shared_gt_with_common` marker on the new entry).
    """
    _out = []
    for _t in raw_pairs or []:
        if isinstance(_t, (list, tuple)) and len(_t) == 2:
            _a, _g = _t
            if isinstance(_a, int) and isinstance(_g, int):
                _out.append((_a, "gt_only", _g))
        elif isinstance(_t, (list, tuple)) and len(_t) == 3:
            _a, _k, _g = _t
            if (isinstance(_a, int) and isinstance(_g, int)
                    and _k in ("gt_only", "common")):
                _out.append((_a, _k, _g))
    return _out


def _apply_goal_overrides(raw: dict, overrides: dict) -> dict:
    """Apply user reclassification overrides to a raw goals-struct and
    return a NEW dict with the buckets rebalanced. Silently ignores
    stale/out-of-range indices so overrides carried over from a previous
    Run analysis don't crash the render.

    Override shape:
      - `split_common`:  set/list of raw['common'] indices to break back
        into individual (answer_only + gt_only) entries.
      - `promote_pairs`: list of `(a_idx, gt_kind, gt_idx)` (2-tuples of
        `(a, g)` are accepted for backward-compat and treated as
        `("gt_only", g)`).  gt_kind = "common" enables N:N: multiple
        Answer goals can share the same GT-common as their match target.
    """
    _split_idxs = set(overrides.get("split_common") or [])
    _promote = _normalise_promote_pairs(overrides.get("promote_pairs") or [])

    raw_common = list(raw.get("common")      or [])
    raw_answer = list(raw.get("answer_only") or [])
    raw_gt     = list(raw.get("gt_only")     or [])

    # Drop cross-pairs referencing a split common (would be inconsistent).
    _promote = [(a, k, g) for (a, k, g) in _promote
                 if not (k == "common" and g in _split_idxs)]
    _promoted_a = {a for a, _, _ in _promote if 0 <= a < len(raw_answer)}
    _promoted_g_only = {g for a, k, g in _promote
                           if k == "gt_only" and 0 <= g < len(raw_gt)}

    new_common = []
    _split_answers, _split_gts = [], []
    for i, g in enumerate(raw_common):
        if i in _split_idxs:
            _split_answers.append({
                "label": g.get("label", "?"),
                "text":  g.get("answer_text", ""),
                "importance":  g.get("answer_importance",  "M"),
                "commitment":  g.get("answer_commitment",  "M"),
                "feasibility": g.get("answer_feasibility", "M"),
                "achievement": g.get("answer_achievement", "M"),
                # Provenance so the render can offer an "undo" button.
                "_from_split_common_idx": i,
            })
            _split_gts.append({
                "label": g.get("label", "?"),
                "text":  g.get("gt_text", ""),
                "importance":  g.get("gt_importance",  "M"),
                "commitment":  g.get("gt_commitment",  "M"),
                "feasibility": g.get("gt_feasibility", "M"),
                "achievement": g.get("gt_achievement", "M"),
                "_from_split_common_idx": i,
            })
        else:
            new_common.append(g)

    for a_i, gt_kind, g_i in _promote:
        if not (0 <= a_i < len(raw_answer)):
            continue
        _a = raw_answer[a_i]
        if gt_kind == "gt_only":
            if not (0 <= g_i < len(raw_gt)):
                continue
            _g = raw_gt[g_i]
            new_common.append({
                "label": f"{_a.get('label','?')}+{_g.get('label','?')}",
                "answer_text": _a.get("text", ""),
                "gt_text":     _g.get("text", ""),
                "answer_importance":  _a.get("importance",  "M"),
                "answer_commitment":  _a.get("commitment",  "M"),
                "answer_feasibility": _a.get("feasibility", "M"),
                "answer_achievement": _a.get("achievement", "M"),
                "gt_importance":  _g.get("importance",  "M"),
                "gt_commitment":  _g.get("commitment",  "M"),
                "gt_feasibility": _g.get("feasibility", "M"),
                "gt_achievement": _g.get("achievement", "M"),
                "_from_promote_pair": (a_i, "gt_only", g_i),
            })
        elif gt_kind == "common":
            if not (0 <= g_i < len(raw_common)):
                continue
            _g = raw_common[g_i]
            new_common.append({
                "label": f"{_a.get('label','?')}+{_g.get('label','?')}",
                "answer_text": _a.get("text", ""),
                "gt_text":     _g.get("gt_text", ""),
                "answer_importance":  _a.get("importance",  "M"),
                "answer_commitment":  _a.get("commitment",  "M"),
                "answer_feasibility": _a.get("feasibility", "M"),
                "answer_achievement": _a.get("achievement", "M"),
                "gt_importance":  _g.get("gt_importance",  "M"),
                "gt_commitment":  _g.get("gt_commitment",  "M"),
                "gt_feasibility": _g.get("gt_feasibility", "M"),
                "gt_achievement": _g.get("gt_achievement", "M"),
                "_from_promote_pair":       (a_i, "common", g_i),
                # Dedup marker: same GT origin already counted via the
                # original common[g_i]. Scoring skips this entry's GT
                # weight to avoid double-counting.
                "_shared_gt_with_common": g_i,
            })

    new_answer = [g for i, g in enumerate(raw_answer) if i not in _promoted_a] \
                    + _split_answers
    new_gt     = [g for i, g in enumerate(raw_gt)     if i not in _promoted_g_only] \
                    + _split_gts

    return {
        "common":       new_common,
        "answer_only":  new_answer,
        "gt_only":      new_gt,
        "edges_answer": raw.get("edges_answer") or [],
        "edges_gt":     raw.get("edges_gt")     or [],
    }


def _render_goals_grid(raw: dict, adj: dict, overrides_key: str) -> None:
    """2×2 grid with manual reclassification controls.

    - `raw` is the LLM's original goals-struct (source of truth for indices).
    - `adj` is `_apply_goal_overrides(raw, current_overrides)` — what the
      user actually sees.
    - `overrides_key` is the session_state key whose value we mutate.

    Controls:
      - Common goal → checkbox「共通しない」 (splits into A + GT own-only)
      - Answer-only goal → selectbox「GT と共通ペアを指定」 (promotes to common)
      - Split-generated own-only entries → 「共通に戻す」 button (undo split)
      - Merged-pair common entries → 「ペアを解除」 button (undo pairing)
    F/P/R below the grid recomputes automatically off `adj`.
    """
    import streamlit as st

    st.markdown("#### 目標の 2×2 マトリクス (共通 / 共通しない × Answer(AI) / Ground Truth)")
    st.caption(
        "各目標の分類は LLM の推定です。共通/共通しないの判断が違う場合は、"
        "各目標のコントロールから手動で修正できます。修正内容は「変更を適用」で下部の F/P/R に反映されます。"
    )

    _ov = st.session_state[overrides_key]
    _split_set = _ov["split_common"] if isinstance(_ov["split_common"], set) else set(_ov["split_common"])
    # Normalise pairs on read so legacy 2-tuples are upgraded to 3-tuples;
    # this keeps every downstream comparison consistent.
    _pairs = _normalise_promote_pairs(_ov.get("promote_pairs") or [])
    _ov["split_common"], _ov["promote_pairs"] = _split_set, _pairs

    # Apply / Reset controls sit at the top so the user sees them alongside
    # every editable widget below. Widgets no longer trigger st.rerun() on
    # each interaction — pending selections are collected on "変更を適用".
    _apply_c, _reset_c, _stat_c = st.columns([1, 1, 5])
    _apply_clicked = _apply_c.button("✓ 変更を適用", key="btn_pe_goals_apply_ov",
                                       type="primary")
    if _reset_c.button("🔄 分類をリセット", key="btn_pe_goals_reset_ov"):
        # Also wipe pending widget states so nothing is silently reapplied.
        for _k in list(st.session_state.keys()):
            if isinstance(_k, str) and (
                _k.startswith("pe_goals_split_cb_")
                or _k.startswith("pe_goals_pair_a")
                or _k.startswith("pe_goals_unpair_cb_")
            ):
                del st.session_state[_k]
        st.session_state[overrides_key] = {"split_common": set(), "promote_pairs": []}
        st.rerun()
    if _split_set or _pairs:
        _stat_c.caption(
            f"🖊 適用済み: 分割 {len(_split_set)} 件 / 手動ペア {len(_pairs)} 件"
        )
    else:
        _stat_c.caption(
            "🖊 変更なし (widget を操作後、「✓ 変更を適用」で反映)"
        )

    raw_common = raw.get("common") or []
    raw_a      = raw.get("answer_only") or []
    raw_g      = raw.get("gt_only")     or []
    # Pairs may be legacy 2-tuples or new 3-tuples. Normalise then split by
    # gt_kind so the render knows which GT goals are still "available".
    _pairs_norm    = _normalise_promote_pairs(_pairs)
    _paired_a      = {a for a, _, _ in _pairs_norm}
    _paired_g_only = {g for _, k, g in _pairs_norm if k == "gt_only"}

    def _rating_legend():
        st.caption(
            "評点: **大**=大切さ · **本**=本気度 · **見**=達成見込 · **達**=達成度 "
            "／ 色: <span style='color:#D32F2F;font-weight:700;'>High=赤</span> · "
            "<span style='color:#2E7D32;font-weight:700;'>Medium=緑</span> · "
            "<span style='color:#1565C0;font-weight:700;'>Low=青</span>",
            unsafe_allow_html=True,
        )

    def _cell_open(header, header_color, bg, border):
        return (
            f'<div style="background:{bg};border:1px solid {border};'
            f'border-radius:6px;padding:8px 12px;min-height:80px;'
            f'margin-bottom:8px;">'
            f'<div style="font-weight:700;color:{header_color};'
            f'margin-bottom:6px;">{header}</div>'
        )
    _cell_close = "</div>"

    # ===================================================================
    # Row 1: Common goals (LLM's + manual pairs). N:N safe — no duplicates
    # on either side, counts reflect UNIQUE goals per side.
    # Display is ALWAYS visible; edit controls sit inside an expander so
    # the 2×2 stays compact when collapsed.
    # ===================================================================
    _common_orig_kept = [(i, g) for i, g in enumerate(raw_common) if i not in _split_set]
    _pair_merged     = [g for g in adj.get("common", []) if "_from_promote_pair" in g]

    # De-duplicate BOTH sides for display: LLM may emit N:M common entries
    # (same Answer sentence matched with different GT sentences → the same
    # Answer text repeats). The GT side additionally dedupes cross-pair
    # entries (`_shared_gt_with_common: c`) that share raw_common[c]'s GT.
    def _dedup_by(entries, text_key):
        _seen = set()
        _out = []
        for _e in entries:
            _txt = ((_e.get(text_key) or _e.get("text") or "")).strip()
            if _txt and _txt in _seen:
                continue
            if _txt:
                _seen.add(_txt)
            _out.append(_e)
        return _out

    _all_common = [g for _, g in _common_orig_kept] + _pair_merged
    _display_common_a = _dedup_by(_all_common, "answer_text")

    _pair_merged_gt_new = [g for g in _pair_merged
                              if "_shared_gt_with_common" not in g]
    _all_common_gt_side = [g for _, g in _common_orig_kept] + _pair_merged_gt_new
    _display_common_g = _dedup_by(_all_common_gt_side, "gt_text")

    _n_common_a = len(_display_common_a)
    _n_common_g = len(_display_common_g)

    st.markdown(
        f"##### 共通する目標  (Answer: {_n_common_a} 件 / GT: {_n_common_g} 件)"
    )
    _c1, _c2 = st.columns(2)
    with _c1:
        st.markdown(_cell_open(
            f"Answer(AI) 視点 ({_n_common_a})", "#1565C0",
            "#EBF4FF", "#B8D0EA") + "<ul style='margin:0;padding-left:18px;'>"
            + "".join(_goal_row_html(g, "answer") for g in _display_common_a)
            + "</ul>" + _cell_close, unsafe_allow_html=True)
    with _c2:
        st.markdown(_cell_open(
            f"Ground Truth 視点 ({_n_common_g})", "#2E7D32",
            "#EBFBEE", "#B0DAB8") + "<ul style='margin:0;padding-left:18px;'>"
            + "".join(_goal_row_html(g, "gt") for g in _display_common_g)
            + "</ul>" + _cell_close, unsafe_allow_html=True)
        if _n_common_a != _n_common_g:
            st.caption(
                f"※ N:N: Answer(AI) 側 {_n_common_a} 件が Ground Truth 側 "
                f"{_n_common_g} 件に対応 (重複はまとめて 1 件で表示)"
            )

    # Edit controls — folded away by default; collapsed reveals only the
    # 2×2 above so a large goal list stays scannable.
    with st.expander("✏️ 共通する目標の分類を編集", expanded=False):
        # Per-goal split controls — pending until "変更を適用" is clicked.
        # Widget state persists via `key`; the apply handler below reads it.
        for i, g in _common_orig_kept:
            _prev = _goal_text_preview(g, "answer", 20)
            st.checkbox(f"共通していない — {_prev}",
                          key=f"pe_goals_split_cb_{i}", value=False,
                          help=(g.get("answer_text") or ""))
        # Manual-pair unpair controls — same "共通していない" checkbox
        # semantics as the split checkbox above, but writes to
        # `promote_pairs` instead of `split_common`. Batch-applied.
        for g in _pair_merged:
            _p = g.get("_from_promote_pair")   # 3-tuple (a_idx, gt_kind, gt_idx)
            _prev = _goal_text_preview(g, "answer", 20)
            _key = f"pe_goals_unpair_cb_{_p[0]}_{_p[1]}_{_p[2]}"
            st.checkbox(f"共通していない — {_prev}",
                          key=_key, value=False,
                          help=(g.get("answer_text") or ""))
        if not _common_orig_kept and not _pair_merged:
            st.caption("_(編集対象の共通目標がありません)_")

    # ===================================================================
    # Row 2: Individual (own-only) goals. Display always visible; edit
    # controls (pair selectboxes + revert buttons) inside a collapsible
    # expander below.
    # ===================================================================
    _adj_a = adj.get("answer_only") or []
    _adj_g = adj.get("gt_only")     or []
    _adj_a_split = [g for g in _adj_a if "_from_split_common_idx" in g]
    _adj_a_orig  = [g for g in _adj_a if "_from_split_common_idx" not in g]
    _adj_g_split = [g for g in _adj_g if "_from_split_common_idx" in g]
    _adj_g_orig  = [g for g in _adj_g if "_from_split_common_idx" not in g]

    st.markdown(
        f"##### 共通しない目標  (Answer: {len(_adj_a)} 件 / GT: {len(_adj_g)} 件)"
    )
    _c3, _c4 = st.columns(2)
    with _c3:
        st.markdown(_cell_open(
            f"Answer(AI) のみ ({len(_adj_a)})", "#1565C0",
            "#FFF3E0", "#EFC48A") + "<ul style='margin:0;padding-left:18px;'>"
            + "".join(_goal_row_html(g, "answer") for g in _adj_a_orig)
            + "".join(_goal_row_html(g, "answer") for g in _adj_a_split)
            + "</ul>" + _cell_close, unsafe_allow_html=True)
    with _c4:
        st.markdown(_cell_open(
            f"Ground Truth のみ ({len(_adj_g)})", "#2E7D32",
            "#FFF3E0", "#EFC48A") + "<ul style='margin:0;padding-left:18px;'>"
            + "".join(_goal_row_html(g, "gt") for g in _adj_g_orig)
            + "".join(_goal_row_html(g, "gt") for g in _adj_g_split)
            + "</ul>" + _cell_close, unsafe_allow_html=True)

    with st.expander("✏️ 共通しない目標の分類を編集 (統合 / 分割を戻す)", expanded=False):
        # Per-goal pair-with-GT selectbox (only for LLM's original own-only).
        # First option is 「共通していない (このまま)」 — the explicit "leave
        # as answer-only" choice. Following options are ALL GT goals so the
        # operator can support N:N: an Answer goal may match a GT-common
        # goal (which is already paired with a different Answer) — scoring
        # dedupes the GT weight via `_shared_gt_with_common`.
        _NOT_COMMON  = "共通していない (このまま)"
        # Kept GT-common goals (those not split back to individual).
        _common_gt_options = [
            (i, c) for i, c in enumerate(raw_common) if i not in _split_set
        ]
        # Unpaired GT-only goals (already-consumed gt_only ones can't be
        # re-picked because doing so would empty the own-only bucket twice).
        _unpaired_gt = [(j, gt) for j, gt in enumerate(raw_g) if j not in _paired_g_only]
        _pair_opts = [_NOT_COMMON] + [
            f"GT-only#{j} — {_goal_text_preview(gt, 'gt', 20)}"
            for j, gt in _unpaired_gt
        ] + [
            f"GT-共通#{i} — {_goal_text_preview(c, 'gt', 20)}"
            for i, c in _common_gt_options
        ]
        _any_edit_row = False
        for i, g in enumerate(raw_a):
            if i in _paired_a:
                continue
            _any_edit_row = True
            _prev_a = _goal_text_preview(g, "answer", 20)
            # Pending until "変更を適用" is clicked; state persists via `key`.
            st.selectbox(
                # Line break in the label so a long goal-text preview
                # doesn't get pushed off-screen.
                f"分類  \n{_prev_a}",
                _pair_opts, index=0, key=f"pe_goals_pair_a{i}",
                help=(g.get("text") or ""),
            )
        # Undo-split buttons — split-generated own-only entries (A + GT)
        # get symmetric 「共通に戻す」 buttons.
        for g in _adj_a_split:
            _i = g.get("_from_split_common_idx")
            _any_edit_row = True
            if st.button(f"共通に戻す [Answer#{_i}: {g.get('label','?')}]",
                          key=f"pe_goals_unsplit_a_{_i}"):
                _split_set.discard(_i)
                _ov["split_common"] = _split_set
                st.rerun()
        for g in _adj_g_split:
            _i = g.get("_from_split_common_idx")
            _any_edit_row = True
            if st.button(f"共通に戻す [GT#{_i}: {g.get('label','?')}]",
                          key=f"pe_goals_unsplit_g_{_i}"):
                _split_set.discard(_i)
                _ov["split_common"] = _split_set
                st.rerun()
        if not _any_edit_row:
            st.caption("_(編集対象の共通しない目標がありません)_")

    # -----------------------------------------------------------------
    # Batch apply — collect every pending selectbox / checkbox state and
    # rewrite the overrides in one pass. Widgets above don't trigger
    # st.rerun() themselves, so pending changes accumulate silently and
    # F/P/R below reflects the last-applied state until the button is
    # clicked. Only fired for the top "変更を適用" button (revert buttons
    # above already ran their own st.rerun() before we got here).
    # -----------------------------------------------------------------
    if _apply_clicked:
        _new_split = set(_split_set)
        for i, _g in _common_orig_kept:
            if st.session_state.get(f"pe_goals_split_cb_{i}", False):
                _new_split.add(i)
        # Start from the current pairs, then filter out any pair whose
        # "共通していない" unpair checkbox was checked (batch unpair).
        _pairs_kept = list(_pairs)
        for g in _pair_merged:
            _p = g.get("_from_promote_pair")
            _key = f"pe_goals_unpair_cb_{_p[0]}_{_p[1]}_{_p[2]}"
            if st.session_state.get(_key, False):
                _pairs_kept = [x for x in _pairs_kept if x != _p]
        _new_pairs = _pairs_kept
        for i, _g in enumerate(raw_a):
            if i in _paired_a:
                continue
            _pick = st.session_state.get(f"pe_goals_pair_a{i}", _NOT_COMMON)
            if not isinstance(_pick, str) or _pick == _NOT_COMMON:
                continue
            if _pick.startswith("GT-only#"):
                _gt_idx = int(_pick.split("#")[1].split(" ")[0])
                _new_pairs.append((i, "gt_only", _gt_idx))
            elif _pick.startswith("GT-共通#"):
                _gt_idx = int(_pick.split("#")[1].split(" ")[0])
                _new_pairs.append((i, "common", _gt_idx))
        _ov["split_common"]  = _new_split
        _ov["promote_pairs"] = _new_pairs
        # Wipe the pending widget states so the next render starts clean
        # (paired items disappear from the loops, so their keys become
        # stale garbage otherwise).
        for i, _g in _common_orig_kept:
            _k = f"pe_goals_split_cb_{i}"
            if _k in st.session_state:
                del st.session_state[_k]
        for i in range(len(raw_a)):
            _k = f"pe_goals_pair_a{i}"
            if _k in st.session_state:
                del st.session_state[_k]
        # Also wipe the unpair checkboxes so applied unpair actions don't
        # linger with checked state.
        for _k in list(st.session_state.keys()):
            if isinstance(_k, str) and _k.startswith("pe_goals_unpair_cb_"):
                del st.session_state[_k]
        st.rerun()

    _rating_legend()


def _relation_row_html(e: dict, is_common: bool) -> str:
    """Render a single (from → to) relation row. Common relations are
    colored blue per operator spec so they stand out visually."""
    _from = e.get("from", "?")
    _to   = e.get("to", "?")
    _color = "#1565C0" if is_common else "#333"
    _mark  = " ✓" if is_common else ""
    return (
        f'<li style="line-height:1.5;color:{_color};'
        f'{"font-weight:600;" if is_common else ""}">'
        f'{_from} ↔ {_to}{_mark}</li>'
    )


def _render_goals_relations_grid(edges_a: list, edges_g: list) -> None:
    """2×2 grid of relation buckets:
        top-left  = Answer(AI) が認識したハーモニー (synergy)
        top-right = Ground Truth が認識したハーモニー
        bot-left  = Answer(AI) が認識したコンフリクト (tradeoff)
        bot-right = Ground Truth が認識したコンフリクト
    Common relations (identified by both sides) are colored blue.
    """
    import streamlit as st
    st.markdown("#### 関係の 2×2 マトリクス (ハーモニー / コンフリクト × Answer(AI) / Ground Truth)")

    def _key(e):
        return (tuple(sorted([e.get("from", ""), e.get("to", "")])),
                e.get("kind", "synergy"))
    _set_a = {_key(e) for e in edges_a}
    _set_g = {_key(e) for e in edges_g}
    _common = _set_a & _set_g

    def _split_by_kind(edges: list, kind: str) -> list:
        return [e for e in edges if e.get("kind", "synergy") == kind]

    def _cell(header: str, header_color: str, bg: str, border: str,
              edges: list) -> str:
        _rows = "".join(
            _relation_row_html(e, _key(e) in _common) for e in edges
        ) or '<li><i>(該当なし)</i></li>'
        return (
            f'<div style="background:{bg};border:1px solid {border};'
            f'border-radius:6px;padding:8px 12px;min-height:100px;">'
            f'<div style="font-weight:700;color:{header_color};'
            f'margin-bottom:6px;">{header}</div>'
            f'<ul style="margin:0;padding-left:18px;">{_rows}</ul>'
            f'</div>'
        )

    _syn_a = _split_by_kind(edges_a, "synergy")
    _syn_g = _split_by_kind(edges_g, "synergy")
    _con_a = _split_by_kind(edges_a, "tradeoff")
    _con_g = _split_by_kind(edges_g, "tradeoff")

    # --- Row 1: Harmony -----------------------------------------------------
    _c1, _c2 = st.columns(2)
    _c1.markdown(_cell(
        f"Harmony (シナジー) · Answer(AI) ({len(_syn_a)})", "#1565C0",
        "#F0F7FF", "#B8D0EA", _syn_a,
    ), unsafe_allow_html=True)
    _c2.markdown(_cell(
        f"Harmony (シナジー) · Ground Truth ({len(_syn_g)})", "#2E7D32",
        "#F0F7FF", "#B8D0EA", _syn_g,
    ), unsafe_allow_html=True)

    # --- Row 2: Conflict ----------------------------------------------------
    _c3, _c4 = st.columns(2)
    _c3.markdown(_cell(
        f"Conflict (トレードオフ) · Answer(AI) ({len(_con_a)})", "#1565C0",
        "#FFF5F5", "#E7B0B0", _con_a,
    ), unsafe_allow_html=True)
    _c4.markdown(_cell(
        f"Conflict (トレードオフ) · Ground Truth ({len(_con_g)})", "#2E7D32",
        "#FFF5F5", "#E7B0B0", _con_g,
    ), unsafe_allow_html=True)
    st.caption(
        "**青字 + ✓** = Answer(AI) と Ground Truth の両方が同じ関係を識別しているペア"
    )


def _render_goals_prf_panel(sc: dict) -> None:
    """Show the weighted F/Precision/Recall for goals (primary score) and
    the edge P/R/F for relations (reference indicator)."""
    import streamlit as st
    st.markdown("#### スコアリング (目標 F / P / R + 関係 F)")

    def _fmt(v):
        return f"{v:.3f}" if isinstance(v, (int, float)) else "-"

    _prf = sc.get("prf") or {}
    _eprf = sc.get("edge_prf") or {}

    _cols = st.columns(6)
    _cols[0].metric("F1 (目標)",           _fmt(_prf.get("f1")))
    _cols[1].metric("Precision (GT基準)",   _fmt(_prf.get("precision")))
    _cols[2].metric("Recall (Answer基準)",  _fmt(_prf.get("recall")))
    _cols[3].metric("関係 F1",              _fmt(_eprf.get("f1")))
    _cols[4].metric("関係 Precision",       _fmt(_eprf.get("precision")))
    _cols[5].metric("関係 Recall",          _fmt(_eprf.get("recall")))

    with st.expander("スコアの内訳 (重み計算)", expanded=False):
        _sums = _prf.get("sums") or {}
        _cnts = _prf.get("counts") or {}
        st.markdown(
            f"- 目標の重み: 4 軸 (大切さ / 本気度 / 達成見込 / 達成度) の "
            f"**H(1.0)/M(0.5)/L(0.0)** 平均を各目標の重みとする\n"
            f"- **Precision = 共通目標(GT重み) / 全 GT 目標重み** = "
            f"{_sums.get('common_gt_weight', 0):.2f} / "
            f"{_sums.get('total_gt_weight', 0):.2f}\n"
            f"- **Recall = 共通目標(Answer重み) / 全 Answer 目標重み** = "
            f"{_sums.get('common_answer_weight', 0):.2f} / "
            f"{_sums.get('total_answer_weight', 0):.2f}\n"
            f"- **F1 = 2·P·R / (P + R)**\n"
            f"- 件数: 共通 = **{_cnts.get('common', 0)}** / "
            f"Answer-only = **{_cnts.get('answer_only', 0)}** / "
            f"GT-only = **{_cnts.get('gt_only', 0)}**"
        )
        _ec = _eprf.get("counts") or {}
        _bk = _eprf.get("by_kind") or {}
        st.markdown(
            f"---\n"
            f"- 関係 (シナジー / トレードオフ) の F/P/R は edge 集合ベース "
            f"(重みなし、参考値):\n"
            f"  - Answer が識別: **{_ec.get('a', 0)}** 本 / "
            f"GT が識別: **{_ec.get('g', 0)}** 本 / "
            f"共通: **{_ec.get('common', 0)}** 本\n"
            f"  - シナジーだけで: A={_bk.get('synergy',{}).get('a',0)} / "
            f"GT={_bk.get('synergy',{}).get('g',0)} / "
            f"共通={_bk.get('synergy',{}).get('common',0)}\n"
            f"  - トレードオフだけで: A={_bk.get('tradeoff',{}).get('a',0)} / "
            f"GT={_bk.get('tradeoff',{}).get('g',0)} / "
            f"共通={_bk.get('tradeoff',{}).get('common',0)}"
        )


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
    # G3 memo key was renamed from 目標のトレードオフ to 目標同士の関係.
    # Fall through to the legacy key so older xlsx templates still work.
    g3 = (by_memo.get("目標同士の関係")
            or by_memo.get("目標のトレードオフ")
            or {})

    _plugin = _PLUGIN_DIR.name
    _key = f"_pe_goals_struct_{_plugin}"

    # The "目標を構造化分析する (LLM)" button was removed — Run analysis
    # auto-fires `Plugin.llm_augment()` which populates `_key` when an agent
    # is selected above Run analysis. Here we just consume the cached result.

    res = st.session_state.get(_key)
    if not res:
        st.info(
            "目標の LLM 構造化分析はまだ実行されていません。"
            " Run analysis の上でエージェントを選択してから *Run analysis* を再実行してください。"
            " (ベン図 / 評点付き一覧 / コネクタ図が表示されます)"
        )
        return

    d = res.get("data") or {}
    answer_only = d.get("answer_only") or []
    common      = d.get("common")      or []
    gt_only     = d.get("gt_only")     or []
    edges_a     = d.get("edges_answer") or []
    edges_g     = d.get("edges_gt")     or []

    st.caption(
        f"Agent: `{res.get('agent','')}`  /  Model: `{res.get('model','')}`  /  "
        f"Generated: {res.get('timestamp','')}"
    )
    _prompt = res.get("prompt")
    if _prompt:
        with st.expander(
            "🔎 LLM に与えたスコアリング指示 (prompt) — 目標", expanded=False,
        ):
            st.caption(
                f"prompt length: {len(_prompt):,} 文字 · "
                "目標のラベル化 → 共通/片側分類 → H/M/L 評点抽出 → 関係エッジ抽出まで一括指示"
            )
            st.code(_prompt, language="markdown")

    if not (answer_only or common or gt_only):
        st.warning("目標が抽出できませんでした。LLM 出力が空、または JSON パースに失敗した可能性があります。")
        return

    # ================================================================
    # 1. 2x2 goals grid with MANUAL RECLASSIFICATION per goal
    #    LLM's common/individual judgment isn't always right — the
    #    operator can split a common goal back into individual, or
    #    pair an individual goal with the other side's unpaired goal.
    #    Overrides live in session_state; F/P/R below recompute live.
    # ================================================================
    _overrides_key = f"_pe_goals_overrides_{_PLUGIN_DIR.name}"
    _overrides = st.session_state.setdefault(
        _overrides_key,
        {"split_common": set(), "promote_pairs": []},
    )
    # Session state can serialise sets → lists on rerun, coerce back.
    if not isinstance(_overrides.get("split_common"), set):
        _overrides["split_common"] = set(_overrides.get("split_common") or [])
    _adj = _apply_goal_overrides(d, _overrides)
    _render_goals_grid(d, _adj, _overrides_key)

    # ================================================================
    # 2. 2x2 relations grid — hidden per operator request. Edges are
    #    still fed to `_cat_cos_similarity` via `_apply_goal_overrides`
    #    so the reference edge F/P/R remains on the top metric strip.
    # ================================================================
    # _render_goals_relations_grid(edges_a, edges_g)

    # ================================================================
    # 3. Weighted F / Precision / Recall panel — hidden per operator
    #    request. The same F1 / Precision / Recall / edge F1 already
    #    appear on the metric strip at the top of the section via
    #    `_render_cos_metric_strip`, so a second panel below is redundant.
    # ================================================================
    # _sc = _score_goals_all(_adj)
    # _render_goals_prf_panel(_sc)


def _render_overall_llm_commentary(result: dict) -> None:
    """Single bottom-of-report LLM commentary. Replaces the per-section
    buttons — one button, one call, ~1000 字 covering the summary radar
    plus each category. Cached under `_pe_overall_llm_<plugin>` so reruns
    don't re-hit the API.

    Reads the same `eval_llm_agent_<plugin>` selectbox key the per-section
    button used, so the WebUI agent picker keeps working as before.
    """
    import streamlit as st
    _plugin = _PLUGIN_DIR.name
    _key   = f"_pe_overall_llm_{_plugin}"
    _btn_k = f"btn_{_key}"
    _agent_state_key = f"eval_llm_agent_{_plugin}"

    st.markdown("### LLMによる解説")
    st.caption(
        "サマリーと各カテゴリーを **1000字程度** で総括します。"
        " 冒頭に読みやすい総評、続いてカテゴリー別の詳細解説を出力します。"
    )
    cols = st.columns([2, 6])
    if cols[0].button("🔍 LLMによる解説", key=_btn_k,
                       help="全カテゴリーをまとめて LLM が解説します"):
        _agent_file = st.session_state.get(_agent_state_key)
        if not _agent_file:
            cols[1].warning("先に LLM Evaluation セクションでエージェントを選択してください。")
            return
        try:
            with st.spinner("LLM が評価結果を解説中..."):
                import DigiM_Evaluation as _de
                from datetime import datetime as _dt
                # Assemble sections in the order they appear on screen:
                # summary first, then every category.
                _sections = [{"name": "サマリー",
                                "md": "\n".join(_summary_md(result))}]
                for _cat in result.get("category_order", []):
                    _sections.append({
                        "name": _cat,
                        "md":   _category_to_md(_cat, result["categories"][_cat]),
                    })
                text, model = _de.llm_compare_overall(
                    sections=_sections,
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
        with st.expander("💬 LLM解説 (全カテゴリー)", expanded=True):
            st.caption(
                f"Agent: `{res['agent']}`  /  Model: `{res['model']}`  /  "
                f"Generated: {res['timestamp']}"
            )
            st.markdown(res.get("text", ""))


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
# Cosine-similarity primitives
# ---------------------------------------------------------------------------
# Every category is reduced to a single number in [0, 1] that measures how
# close Answer(AI) is to Ground Truth. Ground Truth is the fixed reference
# (=1.0 by construction); the reported score is `cos(Answer, GT)`.
#
#   Likert (特性 / 価値観 / 動機):
#       cosine of `axes_avg` and `axes_avg_gt` numeric vectors, with the
#       axis-key union filled with 0.0 for missing entries. For 動機 we
#       ALSO surface BPNSFS-only and MWMS-only sub-scores.
#
#   Narrative (目標 / 人格形成 / 社会性 / 愛着):
#       cosine of OpenAI embeddings of the concatenated Answer / GT texts.
#       We embed once per category and cache the result under
#       `data["_cos_cache"]` so re-renders (Streamlit reruns) don't burn
#       API calls. Fallback: aggregate Token F1 (already computed by the
#       analyzer) — this is a bag-of-tokens proxy for cosine that we can
#       always evaluate offline. `source` in the return dict signals which
#       path was taken so the UI can label it appropriately.


def _vec_cos(vec_a: list, vec_b: list) -> float:
    """Standard cosine of two equal-length numeric vectors. Zero vectors
    return 0.0 so callers don't have to guard for the pathological case."""
    import math
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    na  = math.sqrt(sum(a * a for a in vec_a))
    nb  = math.sqrt(sum(b * b for b in vec_b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return dot / (na * nb)


def _dict_cos(d_a: dict, d_b: dict) -> float | None:
    """Cosine sim of two axis dicts (Likert). Returns None when either is
    empty — the caller distinguishes 'no data' from 'orthogonal 0.0'."""
    if not d_a or not d_b:
        return None
    keys = sorted(set(d_a.keys()) | set(d_b.keys()))
    va = [float(d_a.get(k, 0.0)) for k in keys]
    vb = [float(d_b.get(k, 0.0)) for k in keys]
    return _vec_cos(va, vb)


def _text_embedding_cos(text_a: str, text_b: str) -> float | None:
    """Cosine sim via OpenAI embeddings. Returns None if the embed client
    is unavailable, texts are empty, or any exception fires — callers fall
    back to Token F1 in that case."""
    if not text_a.strip() or not text_b.strip():
        return None
    try:
        import DigiM_Util as _dmu
        embs = _dmu.embed_texts_batch([text_a, text_b])
        if not embs or embs[0] is None or embs[1] is None:
            return None
        return _vec_cos(list(embs[0]), list(embs[1]))
    except Exception:
        return None


def _mean_abs_err(d_a: dict, d_b: dict) -> float | None:
    """Mean absolute error over the union of keys — used for per-axis /
    per-item MAE. Returns None when both dicts are empty."""
    if not d_a and not d_b:
        return None
    keys = sorted(set(d_a.keys()) | set(d_b.keys()))
    if not keys:
        return None
    errs = [abs(float(d_a.get(k, 0.0)) - float(d_b.get(k, 0.0))) for k in keys]
    return round(sum(errs) / len(errs), 3)


def _cat_cos_similarity(cat: str, data: dict) -> dict:
    """Compute per-category similarity between Answer(AI) and Ground Truth.

    Preference order (most-semantic first):
        1. **LLM-based individual scoring** — reads session_state for the
           user's already-run structured analysis. For 目標 this is the
           lineup/score/edges hybrid; for 人格形成/社会性/愛着 it's the
           per-axis LLM rubric average.
        2. **Embedding cosine** — OpenAI embeddings for narrative text.
        3. **Axes cosine** — for Likert categories.

    Returns:
        {
          "overall": float | None,       # Cos similarity in [0, 1]
          "mae":     float | None,       # Per-item MAE in [0, 1] (0 = ideal)
          "source":  "llm_goals" | "llm_axes" | "axes" | "embed"
                     | "f1_fallback" | "none",
          "extra":   {
              "lineup"/"score"/"edges":  goals sub-scores,
              "bpnsfs" (cos), "bpnsfs_mae", "mwms" (cos), "mwms_mae": 動機,
              "per_axis": {axis: cos_sim},
              "score_per_axis" / "edge_counts": goals detail,
          },
        }
    """
    import streamlit as st
    _plugin = _PLUGIN_DIR.name

    # ── Priority 1: LLM-based individual scoring (semantic, structured) ──
    if cat == "目標":
        _llm = st.session_state.get(f"_pe_goals_struct_{_plugin}")
        _llm_data = (_llm or {}).get("data") or {}
        if _llm_data:
            # Cache is invalidated whenever the operator's manual overrides
            # change — otherwise the summary radar / MAE would show stale
            # values after "変更を適用". We fingerprint the overrides and
            # bake it into the cache key.
            _ovkey = f"_pe_goals_overrides_{_plugin}"
            _ov = st.session_state.get(_ovkey) or {"split_common": set(),
                                                     "promote_pairs": []}
            _ov_fp = (
                tuple(sorted(_ov.get("split_common") or [])),
                tuple(_normalise_promote_pairs(_ov.get("promote_pairs") or [])),
            )
            _cache_key = "_cos_cache_llm_goals"
            _cached = data.get(_cache_key)
            if _cached and data.get("_cos_cache_llm_goals_fp") == _ov_fp:
                return _cached
            # Fold manual overrides into the LLM data before scoring so the
            # summary tile / radar reflect the same F/P/R the per-category
            # grid shows.
            _eff = _apply_goal_overrides(_llm_data, _ov)
            scores = _score_goals_all(_eff)
            # Headline metric is now the weighted F1 (goals). Falls back to
            # the legacy sub-score mean if F1 can't be computed (no goals).
            _prf   = scores.get("prf")   or {}
            _eprf  = scores.get("edge_prf") or {}
            _f1    = _prf.get("f1")
            if _f1 is None:
                _valid = [v for v in (scores.get("lineup"),
                                        scores.get("score"),
                                        scores.get("edges")) if v is not None]
                _f1 = round(sum(_valid) / len(_valid), 3) if _valid else None
            if _f1 is not None:
                # MAE = 1 - F1 so the summary radar's "close to 0 is good"
                # semantics stay consistent across categories.
                _mae = round(max(0.0, 1.0 - _f1), 3)
                _out = {
                    "overall": _f1,
                    "mae":     _mae,
                    "source":  "llm_goals",
                    "extra":   {
                        # New: F/P/R for goals + F/P/R for relations.
                        "f1":            _prf.get("f1"),
                        "precision":     _prf.get("precision"),
                        "recall":        _prf.get("recall"),
                        "edge_f1":       _eprf.get("f1"),
                        "edge_precision":_eprf.get("precision"),
                        "edge_recall":   _eprf.get("recall"),
                        # Legacy sub-scores kept for backward compat (metric
                        # strip / report_md still reference them).
                        "lineup": scores.get("lineup"),
                        "score":  scores.get("score"),
                        "edges":  scores.get("edges"),
                        "score_per_axis": scores.get("score_per_axis"),
                        "edge_counts":    scores.get("edge_counts"),
                    },
                }
                data[_cache_key] = _out
                data["_cos_cache_llm_goals_fp"] = _ov_fp
                return _out
    elif cat in _NARRATIVE_CATEGORIES:
        _llm = st.session_state.get(f"_pe_narr_scored_{_plugin}_{cat}")
        _llm_data = (_llm or {}).get("data") or {}
        if _llm_data:
            _cache_key = f"_cos_cache_llm_axes_{cat}"
            _cached = data.get(_cache_key)
            if _cached:
                return _cached
            _overall, _per_axis = _score_narrative_axes(_llm_data)
            if _overall is not None:
                _ans_scores = _llm_data.get("answer_scores") or {}
                _gt_scores  = _llm_data.get("gt_scores")     or {}
                _mae = _mean_abs_err(_ans_scores, _gt_scores)
                # Per-axis Cos/MAE — scalar-per-axis, so Cos ≡ 1 - |Δ| and
                # MAE ≡ |Δ|. Surfaced so the summary tile can show a break-
                # down of the four narrative axes below the overall pair.
                _per_axis_cos_mae = {}
                _axes_cfg = _NARRATIVE_SCORED_AXES.get(cat) or []
                for _jp, _en, _ in _axes_cfg:
                    if _jp not in _ans_scores and _jp not in _gt_scores:
                        continue
                    _av = float(_ans_scores.get(_jp, 0.0))
                    _gv = float(_gt_scores.get(_jp,  0.0))
                    _d  = abs(_av - _gv)
                    _per_axis_cos_mae[_jp] = {
                        "en":  _en,
                        "cos": round(1.0 - _d, 3),
                        "mae": round(_d, 3),
                    }
                _out = {
                    "overall": _overall,
                    "mae":     _mae,
                    "source":  "llm_axes",
                    "extra":   {"per_axis": _per_axis,
                                 "per_axis_cos_mae": _per_axis_cos_mae},
                }
                data[_cache_key] = _out
                return _out

    # ── Priority 2/3: embedding cosine (narrative) or axes cosine (Likert) ──
    _cache = data.get("_cos_cache")
    if isinstance(_cache, dict) and "overall" in _cache:
        return _cache

    if cat in _NARRATIVE_CATEGORIES:
        items = data.get("narrative_items") or data.get("narratives") or []
        ans_text = "\n\n".join(str(it.get("answer") or "").strip()
                                 for it in items if it.get("answer"))
        gt_text  = "\n\n".join(str(it.get("ground_truth") or "").strip()
                                 for it in items if it.get("ground_truth"))
        _cos = _text_embedding_cos(ans_text, gt_text)
        # Without LLM structured / rubric data there's no per-axis vector
        # to compute MAE on directly. Derive it from the overall Cos as
        # `1 - cos` so the UI always shows a number rather than "-" — the
        # operator can still see the ranking. Clicking the "LLM 構造化分析"
        # button upgrades both Cos and MAE to LLM-based per-axis values.
        if _cos is not None:
            _cos_r = round(_cos, 3)
            _mae   = round(max(0.0, 1.0 - _cos_r), 3)
            _out = {"overall": _cos_r, "mae": _mae,
                    "source": "embed", "extra": {}}
        else:
            _f1 = data.get("narrative_overall_f1")
            if _f1 is not None:
                _cos_r = round(float(_f1), 3)
                _out = {"overall": _cos_r,
                        "mae": round(max(0.0, 1.0 - _cos_r), 3),
                        "source": "f1_fallback", "extra": {}}
            else:
                _out = {"overall": None, "mae": None,
                        "source": "none", "extra": {}}
        data["_cos_cache"] = _out
        return _out

    # Likert path — axes_avg dicts
    axes    = data.get("axes_avg") or {}
    axes_gt = data.get("axes_avg_gt") or {}
    axes_bl = data.get("axes_avg_baseline") or {}
    _overall = _dict_cos(axes, axes_gt)
    _mae     = _mean_abs_err(axes, axes_gt)
    _out = {
        "overall": round(_overall, 3) if _overall is not None else None,
        "mae":     _mae,
        "source":  "axes" if _overall is not None else "none",
        "extra":   {},
    }
    # Baseline pair scores (Answer ↔ Baseline, GT ↔ Baseline) — surfaced so
    # the tile can show how far each side has drifted from the benchmark.
    if axes_bl:
        _ab_cos = _dict_cos(axes, axes_bl) if axes else None
        _ab_mae = _mean_abs_err(axes, axes_bl) if axes else None
        _gb_cos = _dict_cos(axes_gt, axes_bl) if axes_gt else None
        _gb_mae = _mean_abs_err(axes_gt, axes_bl) if axes_gt else None
        if _ab_cos is not None:
            _out["extra"]["ab_cos"] = round(_ab_cos, 3)
        if _ab_mae is not None:
            _out["extra"]["ab_mae"] = _ab_mae
        if _gb_cos is not None:
            _out["extra"]["gb_cos"] = round(_gb_cos, 3)
        if _gb_mae is not None:
            _out["extra"]["gb_mae"] = _gb_mae
    # For 動機, expose BPNSFS-only and MWMS-only sub-scores as requested.
    # BOTH cosine AND MAE per sub-theory so the operator can see whether
    # a low overall cos is driven by direction or magnitude.
    if cat == "動機":
        _bp, _bp_gt = data.get("bpnsfs_avg") or {}, data.get("bpnsfs_avg_gt") or {}
        _bp_cos = _dict_cos(_bp, _bp_gt)
        _bp_mae = _mean_abs_err(_bp, _bp_gt)
        if _bp_cos is not None:
            _out["extra"]["bpnsfs"]     = round(_bp_cos, 3)
        if _bp_mae is not None:
            _out["extra"]["bpnsfs_mae"] = _bp_mae
        _mw, _mw_gt = data.get("mwms_avg") or {}, data.get("mwms_avg_gt") or {}
        _mw_cos = _dict_cos(_mw, _mw_gt)
        _mw_mae = _mean_abs_err(_mw, _mw_gt)
        if _mw_cos is not None:
            _out["extra"]["mwms"]     = round(_mw_cos, 3)
        if _mw_mae is not None:
            _out["extra"]["mwms_mae"] = _mw_mae
    data["_cos_cache"] = _out
    return _out


# --------------------------------------------------------------------------
# Individual (semantic) scoring — LLM-driven, not surface-text
# ---------------------------------------------------------------------------
# These build on the LLM's structured output rather than character/token
# overlap: `llm_extract_goals_structured` (semantic goal matching + H/M/L
# ratings + relation edges) and `llm_extract_narrative_scored` (per-axis
# 5-step rubric). All sub-scores land in [0, 1] where 1.0 means "Answer(AI)
# agrees perfectly with Ground Truth on this facet".

_HML_NUM = {"H": 1.0, "M": 0.5, "L": 0.0}


def _hml_to_num(v) -> float:
    return _HML_NUM.get(str(v or "M").upper().strip(), 0.5)


def _score_goals_lineup(goals_struct: dict) -> float | None:
    """Jaccard on goal-set membership — the LLM already classified goals
    into common / answer_only / gt_only using semantic matching, so this
    is a pure set-similarity calculation on top of a semantic partition."""
    a_only = len(goals_struct.get("answer_only") or [])
    common = len(goals_struct.get("common")      or [])
    g_only = len(goals_struct.get("gt_only")     or [])
    total  = a_only + common + g_only
    if total == 0:
        return None
    return round(common / total, 3)


def _score_goals_ratings(goals_struct: dict) -> tuple[float | None, dict]:
    """Mean per-axis agreement across all common goals × 4 H/M/L axes.
    Returns (overall_mean, {axis_key: per_axis_mean}). Only common goals
    contribute — side-only goals have no counterpart to compare against."""
    common = goals_struct.get("common") or []
    if not common:
        return None, {}
    axes = ["importance", "commitment", "feasibility", "achievement"]
    per_axis: dict[str, float] = {}
    for ax in axes:
        _agree = []
        for g in common:
            _av = _hml_to_num(g.get("answer_" + ax))
            _gv = _hml_to_num(g.get("gt_"     + ax))
            _agree.append(1.0 - abs(_av - _gv))
        per_axis[ax] = round(sum(_agree) / len(_agree), 3) if _agree else None
    _v = [x for x in per_axis.values() if x is not None]
    overall = round(sum(_v) / len(_v), 3) if _v else None
    return overall, per_axis


def _score_goals_edges(goals_struct: dict) -> tuple[float | None, dict]:
    """Jaccard on the (from, to, kind) edge sets between the two graphs.
    Returns (jaccard, counts_dict)."""
    ea = goals_struct.get("edges_answer") or []
    eg = goals_struct.get("edges_gt")     or []

    def _key(e):
        return (tuple(sorted([e.get("from", ""), e.get("to", "")])),
                e.get("kind", "synergy"))

    set_a = {_key(e) for e in ea}
    set_g = {_key(e) for e in eg}
    union = set_a | set_g
    inter = set_a & set_g
    counts = {"a": len(set_a), "g": len(set_g),
               "inter": len(inter), "union": len(union)}
    if not union:
        return None, counts
    return round(len(inter) / len(union), 3), counts


def _goal_weight(g: dict, side: str) -> float:
    """Compute a scalar weight in [0, 1] for a goal from its 4 H/M/L ratings.

    Each of 大切さ / 本気度 / 達成見込 / 達成度 contributes equally
    (mean of `_hml_to_num` applied to each). `side` picks which fields to
    read:
      - "answer" → answer_importance / answer_commitment / ... (from a
        common goal) or the plain field names (from answer_only, gt_only)
      - "gt"     → gt_importance / gt_commitment / ...  (same fallback)
    Missing fields default to "M" (0.5) so a goal without ratings still
    contributes a meaningful signal.
    """
    axes = ["importance", "commitment", "feasibility", "achievement"]
    _prefix_keys = [f"{side}_{ax}" for ax in axes]
    _plain_keys  = axes
    # Prefer the side-prefixed keys (common goals); fall back to plain
    # keys (answer_only / gt_only records).
    if any(k in g for k in _prefix_keys):
        vals = [_hml_to_num(g.get(k, "M")) for k in _prefix_keys]
    else:
        vals = [_hml_to_num(g.get(k, "M")) for k in _plain_keys]
    return sum(vals) / len(vals)


def _score_goals_prf(goals_struct: dict) -> dict:
    """Weighted Precision / Recall / F1 for the 目標 category.

    Definition (per operator spec — inverse of the traditional IR direction):
      Precision = Σ(common goals' GT-weight) / Σ(all GT goals' weights)
      Recall    = Σ(common goals' Answer-weight) / Σ(all Answer goals' weights)
      F1        = 2·P·R / (P + R)

    A common goal has BOTH answer_* and gt_* ratings; each side is
    weighted independently so Precision (measured from the GT side) and
    Recall (measured from the Answer side) get consistent numerators.

    Returns a dict with `f1`, `precision`, `recall`, and diagnostic sums.
    """
    common      = goals_struct.get("common")      or []
    answer_only = goals_struct.get("answer_only") or []
    gt_only     = goals_struct.get("gt_only")     or []

    # Sums separately for Answer and GT sides. Common entries carrying a
    # `_shared_gt_with_common` marker come from a cross-pair — their GT
    # weight was already counted via the original LLM-common entry, so
    # we skip it here to avoid double-counting in N:N scenarios.
    _w_common_a = sum(_goal_weight(g, "answer") for g in common)
    _w_common_g = sum(_goal_weight(g, "gt")     for g in common
                        if "_shared_gt_with_common" not in g)
    _w_a_only   = sum(_goal_weight(g, "answer") for g in answer_only)
    _w_g_only   = sum(_goal_weight(g, "gt")     for g in gt_only)

    _total_a = _w_common_a + _w_a_only
    _total_g = _w_common_g + _w_g_only

    _p = _w_common_g / _total_g if _total_g > 0 else None
    _r = _w_common_a / _total_a if _total_a > 0 else None
    if _p is not None and _r is not None and (_p + _r) > 0:
        _f = 2 * _p * _r / (_p + _r)
    else:
        _f = None
    return {
        "f1":        round(_f, 3) if _f is not None else None,
        "precision": round(_p, 3) if _p is not None else None,
        "recall":    round(_r, 3) if _r is not None else None,
        "sums": {
            "common_answer_weight": round(_w_common_a, 3),
            "common_gt_weight":     round(_w_common_g, 3),
            "answer_only_weight":   round(_w_a_only,   3),
            "gt_only_weight":       round(_w_g_only,   3),
            "total_answer_weight":  round(_total_a,    3),
            "total_gt_weight":      round(_total_g,    3),
        },
        "counts": {
            "common":      len(common),
            "answer_only": len(answer_only),
            "gt_only":     len(gt_only),
        },
    }


def _score_goals_edges_prf(goals_struct: dict) -> dict:
    """P / R / F for the relation graph (harmony ⇔ conflict).

    Reference indicator — an edge is "common" when both A and GT emit the
    same (canonical from/to pair, kind). Since edges don't carry per-side
    ratings, weights are the plain edge count.
    """
    ea = goals_struct.get("edges_answer") or []
    eg = goals_struct.get("edges_gt")     or []

    def _key(e):
        return (tuple(sorted([e.get("from", ""), e.get("to", "")])),
                e.get("kind", "synergy"))

    set_a = {_key(e) for e in ea}
    set_g = {_key(e) for e in eg}
    _inter = set_a & set_g
    _n_a  = len(set_a)
    _n_g  = len(set_g)
    _n_c  = len(_inter)

    _p = _n_c / _n_g if _n_g > 0 else None
    _r = _n_c / _n_a if _n_a > 0 else None
    if _p is not None and _r is not None and (_p + _r) > 0:
        _f = 2 * _p * _r / (_p + _r)
    else:
        _f = None
    # Per-kind counts help the reader see whether the shortfall is on
    # synergy or tradeoff.
    _by_kind = {"synergy": {"a": 0, "g": 0, "common": 0},
                "tradeoff": {"a": 0, "g": 0, "common": 0}}
    for (pair, kind) in set_a:
        _by_kind.setdefault(kind, {"a": 0, "g": 0, "common": 0})["a"] += 1
    for (pair, kind) in set_g:
        _by_kind.setdefault(kind, {"a": 0, "g": 0, "common": 0})["g"] += 1
    for (pair, kind) in _inter:
        _by_kind.setdefault(kind, {"a": 0, "g": 0, "common": 0})["common"] += 1
    return {
        "f1":        round(_f, 3) if _f is not None else None,
        "precision": round(_p, 3) if _p is not None else None,
        "recall":    round(_r, 3) if _r is not None else None,
        "counts":    {"a": _n_a, "g": _n_g, "common": _n_c},
        "by_kind":   _by_kind,
        "common_edges": list(_inter),
    }


def _score_goals_all(goals_struct: dict) -> dict:
    """Bundle the sub-scores for the 目標 category into a single dict.

    F/P/R (weighted per operator spec) is the headline metric. The legacy
    lineup / rating-agreement / edge-Jaccard sub-scores are kept for the
    metric strip and existing summary paths.
    """
    lineup = _score_goals_lineup(goals_struct)
    rating_overall, rating_per_axis = _score_goals_ratings(goals_struct)
    edge_jaccard, edge_counts = _score_goals_edges(goals_struct)
    _prf   = _score_goals_prf(goals_struct)
    _e_prf = _score_goals_edges_prf(goals_struct)
    return {
        "lineup":         lineup,
        "score":          rating_overall,
        "score_per_axis": rating_per_axis,
        "edges":          edge_jaccard,
        "edge_counts":    edge_counts,
        "prf":            _prf,
        "edge_prf":       _e_prf,
    }


def _score_narrative_axes(scored: dict) -> tuple[float | None, dict]:
    """Per-axis similarity from an `llm_extract_narrative_scored` result.
    Each axis contributes `1 - |A - GT|` (both operands live in [0, 1] by
    the LLM's discrete 5-step rubric). Overall = mean over axes."""
    ans = scored.get("answer_scores") or {}
    gt  = scored.get("gt_scores")     or {}
    if not ans and not gt:
        return None, {}
    axes = list(dict.fromkeys(list(ans.keys()) + list(gt.keys())))
    per_axis: dict[str, float] = {}
    for ax in axes:
        _a = float(ans.get(ax, 0.0) or 0.0)
        _g = float(gt.get(ax, 0.0)  or 0.0)
        per_axis[ax] = round(1.0 - abs(_a - _g), 3)
    _v = list(per_axis.values())
    overall = round(sum(_v) / len(_v), 3) if _v else None
    return overall, per_axis


def _cat_memo(cat: str, data: dict) -> str:
    """Short human-readable summary of per-item errors, shown in the
    summary table's Memo column. Category-specific formatting:

      - **特性 / 価値観**: axis with the largest |Δ|
      - **動機**: BPNSFS + MWMS cos/MAE breakdown
      - **人格形成 / 社会性 / 愛着**: axis with the largest |Δ| (if LLM-scored)
      - **目標**: per-axis MAE across the 4 H/M/L ratings (if LLM-analyzed)

    Returns "-" when there's nothing to summarise so the table row still
    renders cleanly.
    """
    import streamlit as st
    _plugin = _PLUGIN_DIR.name
    cos = _cat_cos_similarity(cat, data)
    _extra = cos.get("extra") or {}

    # 動機 — BPNSFS + MWMS breakdown
    if cat == "動機":
        _bits = []
        if _extra.get("bpnsfs") is not None:
            _bits.append(
                f"BPNSFS cos={_extra['bpnsfs']:.2f}"
                + (f" MAE={_extra['bpnsfs_mae']:.2f}"
                    if _extra.get("bpnsfs_mae") is not None else "")
            )
        if _extra.get("mwms") is not None:
            _bits.append(
                f"MWMS cos={_extra['mwms']:.2f}"
                + (f" MAE={_extra['mwms_mae']:.2f}"
                    if _extra.get("mwms_mae") is not None else "")
            )
        return "  /  ".join(_bits) if _bits else "-"

    # 目標 — per-axis MAE breakdown (LLM structured)
    if cat == "目標":
        _llm = st.session_state.get(f"_pe_goals_struct_{_plugin}")
        _llm_data = (_llm or {}).get("data") or {}
        _common = _llm_data.get("common") or []
        if not _common:
            return "LLM 未実行 (構造化分析ボタンを押下)"
        axes = [("importance", "大切さ"), ("commitment", "本気度"),
                 ("feasibility", "達成見込"), ("achievement", "達成度")]
        _bits = []
        for _ak, _al in axes:
            errs = [abs(_hml_to_num(g.get("answer_" + _ak))
                          - _hml_to_num(g.get("gt_"     + _ak)))
                     for g in _common]
            if errs:
                _bits.append(f"{_al}={sum(errs)/len(errs):.2f}")
        return " / ".join(_bits) if _bits else "-"

    # 人格形成 / 社会性 / 愛着 — max |Δ| axis
    if cat in _NARRATIVE_CATEGORIES:
        _llm = st.session_state.get(f"_pe_narr_scored_{_plugin}_{cat}")
        _llm_data = (_llm or {}).get("data") or {}
        _ans = _llm_data.get("answer_scores") or {}
        _gt  = _llm_data.get("gt_scores")     or {}
        if not _ans and not _gt:
            return "LLM 未実行 (構造化分析ボタンを押下)"
        _diffs = [(abs(float(_ans.get(k, 0.0)) - float(_gt.get(k, 0.0))), k)
                   for k in (set(_ans) | set(_gt))]
        if not _diffs:
            return "-"
        _max_d, _max_k = max(_diffs)
        _short = re.split(r"[ \(（]", _max_k, maxsplit=1)[0][:16]
        return f"最大差: {_short} |Δ|={_max_d:.2f}"

    # Likert 特性 / 価値観 — max |Δ| axis
    _axes    = data.get("axes_avg")    or {}
    _axes_gt = data.get("axes_avg_gt") or {}
    _diffs = [(abs(float(_axes.get(k, 0.0)) - float(_axes_gt.get(k, 0.0))), k)
               for k in (set(_axes) | set(_axes_gt))]
    if not _diffs:
        return "-"
    _max_d, _max_k = max(_diffs)
    _short = _max_k[:16]
    return f"最大差: {_short} |Δ|={_max_d:.2f}"


def _render_cos_metric_strip(cat: str, data: dict) -> None:
    """Big metric row shown at the top of every category section.

    Displays:
      - **overall similarity** (single number) — same as the summary radar
      - **sub-scores** appropriate to the source:
          * `llm_goals`  → ラインナップ / スコア / 関係 (the 3 the user asked for)
          * `llm_axes`   → per-axis breakdown is deferred to the detail table
          * `axes` (動機) → BPNSFS / MWMS sub-scores
      - **source note** so the operator knows how the number was computed
    """
    import streamlit as st
    cos = _cat_cos_similarity(cat, data)
    if cos["overall"] is None:
        return
    _src   = cos.get("source", "")
    _extra = cos.get("extra") or {}
    _mae   = cos.get("mae")

    def _fmt(v):
        return f"{v:.3f}" if isinstance(v, (int, float)) else "-"

    # Layout depends on the source. Every source shows the headline metric +
    # MAE side-by-side as the primary pair; additional sub-scores follow:
    #   llm_goals       → + F1 / P / R (goals, weighted) + F1 (relations)
    #   axes (動機)     → + BPNSFS cos / BPNSFS MAE / MWMS cos / MWMS MAE
    #   others          → nothing extra
    if _src == "llm_goals":
        _cols = st.columns([2, 2, 1, 1, 1, 1])
        _cols[0].metric("F1 (目標)",           _fmt(cos["overall"]))
        _cols[1].metric("MAE",                _fmt(_mae))
        _cols[2].metric("Precision",           _fmt(_extra.get("precision")))
        _cols[3].metric("Recall",              _fmt(_extra.get("recall")))
        _cols[4].metric("関係 F1",             _fmt(_extra.get("edge_f1")))
        _cols[5].metric("関係 P/R",
                          f"{_fmt(_extra.get('edge_precision'))} / "
                          f"{_fmt(_extra.get('edge_recall'))}")
    elif _src == "axes" and cat == "動機":
        # 動機 shows overall + BPNSFS cos/MAE + MWMS cos/MAE (6 metrics)
        _cols = st.columns([2, 2, 1, 1, 1, 1])
        _cols[0].metric("Cos 類似度 (A↔GT)",  _fmt(cos["overall"]))
        _cols[1].metric("MAE",                _fmt(_mae))
        _cols[2].metric("BPNSFS cos",         _fmt(_extra.get("bpnsfs")))
        _cols[3].metric("BPNSFS MAE",         _fmt(_extra.get("bpnsfs_mae")))
        _cols[4].metric("MWMS cos",           _fmt(_extra.get("mwms")))
        _cols[5].metric("MWMS MAE",           _fmt(_extra.get("mwms_mae")))
    else:
        _cols = st.columns([1, 1, 3])
        _cols[0].metric("Cos 類似度 (A↔GT)", _fmt(cos["overall"]))
        _cols[1].metric("MAE",                _fmt(_mae))

    _src_note = {
        "llm_goals":   "LLM 構造抽出 (F1: 評点重み付き Precision/Recall の調和平均 · MAE: 1-F1)",
        "llm_axes":    "LLM 軸別ルーブリック (Cos: 1-|Δ| 軸平均 · MAE: |Δ| 軸平均)",
        "axes":        "軸スコアベクトル (Cos: cosine · MAE: 軸別 |Δ| 平均)",
        "embed":       "OpenAI Embedding (Cos: 意味類似度 · MAE: 1-Cos で暫定, LLM 分析で軸別 MAE に切替)",
        "f1_fallback": "Token F1 fallback (embedding 失敗時)",
    }.get(_src, "")
    if _src_note:
        st.caption(f"↑ 基準: {_src_note} · Ground Truth = 1.0")
    if _src in ("embed", "f1_fallback") and cat in _NARRATIVE_CATEGORIES:
        st.caption(
            "💡 「LLM 構造化分析」ボタンを押すと Cos は LLM ベースに切り替わり、"
            "MAE も算出されます。"
        )


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


# --------------------------------------------------------------------------
# Summary grid — 3-group / 7-category layout per the Personal Evaluation
# reference model. Each category has:
#   - a grid position (row, col) that mirrors the reference diagram
#   - a group tag (inside / flow / outside) driving background tint
#   - a subtitle question ("どんなヒトなのか？ -Who-" etc.)
# The rendering emits a 3-column × 4-row grid using st.columns; each cell
# either shows a category card (name + subtitle + Cos + MAE) or is empty.
# --------------------------------------------------------------------------

# (row, col, group, jp_subtitle, en_subtitle) — position in a 4-row × 3-col grid.
# Groups: "inside" (light blue), "flow" (medium blue), "outside" (dark blue).
_SUMMARY_GRID = {
    "特性":     (0, 1, "inside",  "どんなヒトなのか？",   "Who"),
    "人格形成":  (1, 0, "flow",    "どこから来たのか？",    "Where from"),
    "価値観":   (1, 1, "inside",  "何を好むのか？",       "What / Which"),
    "目標":     (1, 2, "flow",    "どこへ向かうのか？",   "Where to"),
    "動機":     (2, 1, "inside",  "何故そうしたいのか？",  "Why"),
    "社会性":   (3, 0, "outside", "どこにいるのか？",      "Where"),
    "愛着":     (3, 2, "outside", "どう感じているのか？",  "How"),
}

# Radar-chart axis order (clockwise from 12 o'clock).
# This defines both the summary table row order and the radar tick order.
_SUMMARY_CATEGORY_ORDER = [
    "特性", "価値観", "動機", "目標", "人格形成", "社会性", "愛着",
]


def _summary_tile_extras(cat: str, cat_data: dict) -> str:
    """Return an extra HTML block appended below the Cos/MAE line inside a
    summary tile. Currently three categories carry breakdowns:

      - 特性: Big Five per-axis scores (Answer(AI) / Ground Truth) in 2 rows
      - 価値観: Schwartz 4-group Cos + MAE in 4 rows
      - 動機: BPNSFS + MWMS Cos + MAE in 2 rows

    Returns '' for categories without extras so callers can concatenate
    unconditionally.
    """
    def _fmt(v):
        return f"{v:.3f}" if isinstance(v, (int, float)) else "-"
    if cat == "特性":
        _axes    = cat_data.get("axes_avg") or {}
        _axes_gt = cat_data.get("axes_avg_gt") or {}
        # OCEAN canonical order with unambiguous 1-2 letter shorthand
        # (E for Extraversion and ES for Emotional Stability don't collide).
        _BIG5_SHORT = {
            "Openness":            "O",
            "Conscientiousness":   "C",
            "Extraversion":        "E",
            "Agreeableness":       "A",
            "Neuroticism":         "N",
            "Emotional Stability": "ES",
        }
        _canonical = ["Openness", "Conscientiousness", "Extraversion",
                       "Agreeableness", "Neuroticism", "Emotional Stability"]
        _order = [k for k in _canonical if k in _axes or k in _axes_gt]
        # Fall through: catch any custom axis that snuck in via Memo.
        _order += [k for k in (_axes.keys() | _axes_gt.keys())
                    if k not in _order]
        if not _order:
            return ''
        def _row(prefix, src):
            _parts = [f"{_BIG5_SHORT.get(k, k[:2])} {src.get(k, 0.0):.2f}"
                       for k in _order]
            return f'<div><span style="color:#666;">{prefix}:</span> ' + " / ".join(_parts) + '</div>'
        return (
            '<div style="font-size:0.68em;margin-top:6px;padding-top:4px;'
            'border-top:1px solid rgba(255,255,255,0.5);line-height:1.5;">'
            + _row("Big5 A", _axes)
            + _row("Big5 GT", _axes_gt)
            + '</div>'
        )
    if cat == "価値観":
        _axes    = cat_data.get("axes_avg") or {}
        _axes_gt = cat_data.get("axes_avg_gt") or {}
        if not _axes:
            return ''
        _lines = []
        for _label, _members, _desc in _SCHWARTZ_GROUPS:
            _sub_ans = {m: _axes.get(m, 0.0) for m in _members}
            _sub_gt  = {m: _axes_gt.get(m, 0.0) for m in _members} if _axes_gt else {}
            _c = _dict_cos(_sub_ans, _sub_gt) if _sub_gt else None
            _m = _mean_abs_err(_sub_ans, _sub_gt) if _sub_gt else None
            _short = _label.split(" (")[0]     # e.g. "変化への開放"
            _lines.append(
                f'<div>{_short}: '
                f'<span style="color:#666;">Cos</span> {_fmt(_c)} · '
                f'<span style="color:#666;">MAE</span> {_fmt(_m)}</div>'
            )
        return (
            '<div style="font-size:0.68em;margin-top:6px;padding-top:4px;'
            'border-top:1px solid rgba(255,255,255,0.5);line-height:1.55;">'
            + "".join(_lines)
            + '</div>'
        )
    if cat == "人格形成":
        # 4 axes from _NARRATIVE_SCORED_AXES["人格形成"]. Per-axis is a scalar-
        # per-side comparison so we show A / GT / Diff directly (Cos and MAE
        # per axis are just 1-|Δ| and |Δ| — redundant with Diff). Overall
        # Cos + MAE still appears on the main tile row above.
        import streamlit as _st
        _plugin = _PLUGIN_DIR.name
        _llm = _st.session_state.get(f"_pe_narr_scored_{_plugin}_{cat}")
        _llm_data = (_llm or {}).get("data") or {}
        if not _llm_data:
            return ''
        _ans_scores = _llm_data.get("answer_scores") or {}
        _gt_scores  = _llm_data.get("gt_scores")     or {}
        _axes_cfg = _NARRATIVE_SCORED_AXES.get(cat) or []
        def _fmt2(v):
            return f"{v:.2f}" if isinstance(v, (int, float)) else "-"
        def _fmt2s(v):  # signed
            return f"{v:+.2f}" if isinstance(v, (int, float)) else "-"
        _lines = []
        for _jp, _en, _ in _axes_cfg:
            if _jp not in _ans_scores and _jp not in _gt_scores:
                continue
            _av = float(_ans_scores.get(_jp, 0.0))
            _gv = float(_gt_scores.get(_jp,  0.0))
            _d  = _av - _gv
            _lines.append(
                f'<div>{_jp}: '
                f'<span style="color:#666;">A</span> {_fmt2(_av)} · '
                f'<span style="color:#666;">GT</span> {_fmt2(_gv)} · '
                f'<span style="color:#666;">Diff</span> {_fmt2s(_d)}</div>'
            )
        if not _lines:
            return ''
        return (
            '<div style="font-size:0.68em;margin-top:6px;padding-top:4px;'
            'border-top:1px solid rgba(255,255,255,0.5);line-height:1.55;">'
            + "".join(_lines)
            + '</div>'
        )
    if cat == "動機":
        _bp    = cat_data.get("bpnsfs_avg")    or {}
        _bp_gt = cat_data.get("bpnsfs_avg_gt") or {}
        _mw    = cat_data.get("mwms_avg")      or {}
        _mw_gt = cat_data.get("mwms_avg_gt")   or {}
        _bp_c = _dict_cos(_bp, _bp_gt) if _bp and _bp_gt else None
        _bp_m = _mean_abs_err(_bp, _bp_gt) if _bp and _bp_gt else None
        _mw_c = _dict_cos(_mw, _mw_gt) if _mw and _mw_gt else None
        _mw_m = _mean_abs_err(_mw, _mw_gt) if _mw and _mw_gt else None
        if not _bp and not _mw:
            return ''
        return (
            '<div style="font-size:0.68em;margin-top:6px;padding-top:4px;'
            'border-top:1px solid rgba(255,255,255,0.5);line-height:1.55;">'
            f'<div>BPNSFS: <span style="color:#666;">Cos</span> {_fmt(_bp_c)} · '
            f'<span style="color:#666;">MAE</span> {_fmt(_bp_m)}</div>'
            f'<div>MWMS: <span style="color:#666;">Cos</span> {_fmt(_mw_c)} · '
            f'<span style="color:#666;">MAE</span> {_fmt(_mw_m)}</div>'
            '</div>'
        )
    if cat == "社会性":
        _axes    = cat_data.get("axes_avg") or {}
        _axes_gt = cat_data.get("axes_avg_gt") or {}
        if not _axes:
            return ''
        _lines = []
        for _label, _members, _desc in _SOCIABILITY_GROUPS:
            _sub_ans = {m: _axes.get(m, 0.0) for m in _members}
            _sub_gt  = {m: _axes_gt.get(m, 0.0) for m in _members} if _axes_gt else {}
            _c = _dict_cos(_sub_ans, _sub_gt) if _sub_gt else None
            _m = _mean_abs_err(_sub_ans, _sub_gt) if _sub_gt else None
            _short = _label.split(" (")[0]     # e.g. "自己定義"
            _lines.append(
                f'<div>{_short}: '
                f'<span style="color:#666;">Cos</span> {_fmt(_c)} · '
                f'<span style="color:#666;">MAE</span> {_fmt(_m)}</div>'
            )
        return (
            '<div style="font-size:0.68em;margin-top:6px;padding-top:4px;'
            'border-top:1px solid rgba(255,255,255,0.5);line-height:1.55;">'
            + "".join(_lines)
            + '</div>'
        )
    if cat == "愛着":
        # Show raw 1-7 (Avoidance, Anxiety) + classified style for A and GT.
        _axes    = cat_data.get("axes_avg") or {}
        _axes_gt = cat_data.get("axes_avg_gt") or {}
        _av_a, _an_a = _attachment_raw_scores(_axes)
        _av_g, _an_g = _attachment_raw_scores(_axes_gt)
        _style_a = _classify_attachment_style(_av_a, _an_a)
        _style_g = _classify_attachment_style(_av_g, _an_g)
        if _av_a is None and _av_g is None:
            return ''

        def _fmt_r(v):
            return f"{v:.2f}" if isinstance(v, (int, float)) else "-"
        def _style_short(s):
            return _ATTACHMENT_STYLES[s]["jp"] if s else "-"

        _lines = [
            f'<div>A: <span style="color:#666;">回避</span> {_fmt_r(_av_a)} · '
            f'<span style="color:#666;">不安</span> {_fmt_r(_an_a)} · '
            f'<b>{_style_short(_style_a)}</b></div>',
        ]
        if _axes_gt:
            _lines.append(
                f'<div>GT: <span style="color:#666;">回避</span> {_fmt_r(_av_g)} · '
                f'<span style="color:#666;">不安</span> {_fmt_r(_an_g)} · '
                f'<b>{_style_short(_style_g)}</b></div>'
            )
        return (
            '<div style="font-size:0.68em;margin-top:6px;padding-top:4px;'
            'border-top:1px solid rgba(255,255,255,0.5);line-height:1.55;">'
            + "".join(_lines)
            + '</div>'
        )
    if cat == "目標":
        # F/P/R breakdown for goals + edges. The overall F1 is already shown
        # on the main tile row (`Cos` slot). Here we add the diagnostic P/R
        # pair and the reference edge F1 so the operator can see whether a
        # low F1 came from Precision (GT-only overweight) or Recall
        # (Answer-only overweight), and whether relations tracked.
        import streamlit as _st
        _plugin = _PLUGIN_DIR.name
        _llm = _st.session_state.get(f"_pe_goals_struct_{_plugin}")
        _llm_data = (_llm or {}).get("data") or {}
        if not _llm_data:
            return ''
        # Apply the operator's manual overrides so the summary tile matches
        # what the per-category grid shows after "変更を適用".
        _eff = _goals_effective_data(_llm_data)
        _sc = _score_goals_all(_eff)
        _prf  = _sc.get("prf")     or {}
        _eprf = _sc.get("edge_prf") or {}
        _lines = [
            f'<div>目標: '
            f'<span style="color:#666;">P</span> {_fmt(_prf.get("precision"))} · '
            f'<span style="color:#666;">R</span> {_fmt(_prf.get("recall"))} · '
            f'<span style="color:#666;">F1</span> {_fmt(_prf.get("f1"))}</div>',
            f'<div>関係: '
            f'<span style="color:#666;">P</span> {_fmt(_eprf.get("precision"))} · '
            f'<span style="color:#666;">R</span> {_fmt(_eprf.get("recall"))} · '
            f'<span style="color:#666;">F1</span> {_fmt(_eprf.get("f1"))}</div>',
        ]
        return (
            '<div style="font-size:0.68em;margin-top:6px;padding-top:4px;'
            'border-top:1px solid rgba(255,255,255,0.5);line-height:1.55;">'
            + "".join(_lines)
            + '</div>'
        )
    return ''

# Group visual style — colors sampled from the reference diagram (light /
# medium / dark blue) with muted text so numbers read cleanly on the tint.
_GROUP_STYLE = {
    "inside":  {"bg": "#e0f0fa", "border": "#7fb8e0", "chip": "Inside"},
    "flow":    {"bg": "#c9dcf0", "border": "#5f97c8", "chip": "Flow"},
    "outside": {"bg": "#a9c1de", "border": "#4a7fb0", "chip": "Outside"},
}


def _render_summary_grid(rows: list[dict], result: dict | None = None) -> None:
    """Render the 7 categories in the reference 3-group grid layout.

    Each row/col of a 4×3 grid is either a category card (name + subtitle +
    Cos + MAE) or an empty placeholder that preserves spacing. Group tint
    tells the reader which of the three larger themes the category belongs to.

    The 特性 / 価値観 / 動機 tiles receive an appended breakdown block:
    per-axis Big5 scores, Schwartz 4-group Cos+MAE, and BPNSFS/MWMS Cos+MAE
    respectively. See `_summary_tile_extras`.
    """
    import streamlit as st
    # Index rows by category for O(1) lookup by grid position.
    _by_cat = {r["category"]: r for r in rows}
    _cats_data = (result or {}).get("categories") or {}

    def _fmt(v):
        return f"{v:.3f}" if isinstance(v, (int, float)) else "-"

    # 3 group-legend chips shown ABOVE the grid so the reader knows what the
    # tints mean (matches the top-right corner of the reference diagram).
    _legend_cols = st.columns(3)
    _legend_cols[0].markdown(
        f'<div style="background:{_GROUP_STYLE["inside"]["bg"]};'
        f'border:1px solid {_GROUP_STYLE["inside"]["border"]};'
        f'padding:6px 12px;border-radius:6px;font-size:0.9em;">'
        f'<b>Inside</b> — ジブンの内側を形づくるモノ'
        f'</div>', unsafe_allow_html=True)
    _legend_cols[1].markdown(
        f'<div style="background:{_GROUP_STYLE["flow"]["bg"]};'
        f'border:1px solid {_GROUP_STYLE["flow"]["border"]};'
        f'padding:6px 12px;border-radius:6px;font-size:0.9em;">'
        f'<b>Flow</b> — ジブンの過去から未来の流れ'
        f'</div>', unsafe_allow_html=True)
    _legend_cols[2].markdown(
        f'<div style="background:{_GROUP_STYLE["outside"]["bg"]};'
        f'border:1px solid {_GROUP_STYLE["outside"]["border"]};'
        f'padding:6px 12px;border-radius:6px;font-size:0.9em;">'
        f'<b>Outside</b> — ジブンの外側との関わり方'
        f'</div>', unsafe_allow_html=True)

    st.markdown("")  # spacer

    # Reverse-index: (row, col) → (cat_name, meta)
    _grid_map = {(r, c): (cat, meta) for cat, meta in _SUMMARY_GRID.items()
                  for r, c, *_ in [meta]}

    # 4 rows × 3 cols. Card height is `min-height:110px` so tiles with
    # breakdown blocks (特性/価値観/動機) can grow while others stay compact;
    # Streamlit's flex layout aligns row heights automatically.
    for _r in range(4):
        _cols = st.columns(3)
        for _c in range(3):
            _cell = _grid_map.get((_r, _c))
            if _cell is None:
                _cols[_c].markdown(
                    '<div style="min-height:110px;"></div>',
                    unsafe_allow_html=True,
                )
                continue
            _cat_name, _meta = _cell
            _row_idx, _col_idx, _group, _sub_jp, _sub_en = _meta
            _style = _GROUP_STYLE[_group]
            _row_data = _by_cat.get(_cat_name)
            if _row_data is None:
                _cols[_c].markdown(
                    f'<div style="background:#f2f2f2;border:1px dashed #bbb;'
                    f'padding:10px;border-radius:8px;min-height:110px;'
                    f'display:flex;flex-direction:column;justify-content:center;'
                    f'align-items:center;color:#888;">'
                    f'<b>{_cat_name}</b><br><i style="font-size:0.8em;">(データなし)</i>'
                    f'</div>', unsafe_allow_html=True)
                continue
            _cos = _row_data.get("cos")
            _mae = _row_data.get("mae")
            _cos_str = _fmt(_cos)
            _mae_str = _fmt(_mae)
            # Color the Cos value by strength (green ≥ 0.9, orange ≥ 0.7, red < 0.7)
            if isinstance(_cos, (int, float)):
                _cos_color = ("#2E7D32" if _cos >= 0.9
                                else "#EF6C00" if _cos >= 0.7 else "#C62828")
            else:
                _cos_color = "#888"

            _extras = _summary_tile_extras(_cat_name, _cats_data.get(_cat_name, {}))
            # Baseline pair scores (half-size lines shown just under the primary
            # A↔GT Cos/MAE row when the operator supplied a Baseline column).
            # Skipped for 人格形成 / 目標 — those categories compare specific
            # episodes rather than aggregate axis profiles.
            _ex = _row_data.get("extra") or {}
            _bl_html = ""
            if _cat_name not in ("人格形成", "目標") and (
                    _ex.get("ab_cos") is not None or _ex.get("ab_mae") is not None
                    or _ex.get("gb_cos") is not None or _ex.get("gb_mae") is not None):
                _lines = []
                if _ex.get("ab_cos") is not None or _ex.get("ab_mae") is not None:
                    _lines.append(
                        f'<div>A↔B: <span style="color:#666;">Cos</span> '
                        f'{_fmt(_ex.get("ab_cos"))} · '
                        f'<span style="color:#666;">MAE</span> '
                        f'{_fmt(_ex.get("ab_mae"))}</div>'
                    )
                if _ex.get("gb_cos") is not None or _ex.get("gb_mae") is not None:
                    _lines.append(
                        f'<div>GT↔B: <span style="color:#666;">Cos</span> '
                        f'{_fmt(_ex.get("gb_cos"))} · '
                        f'<span style="color:#666;">MAE</span> '
                        f'{_fmt(_ex.get("gb_mae"))}</div>'
                    )
                _bl_html = (
                    '<div style="font-size:0.55em;color:#555;margin-top:2px;'
                    'line-height:1.4;">' + "".join(_lines) + '</div>'
                )

            _card_html = (
                f'<div style="background:{_style["bg"]};'
                f'border:1px solid {_style["border"]};'
                f'padding:10px 12px;border-radius:8px;min-height:110px;'
                f'display:flex;flex-direction:column;">'
                f'<div>'
                f'  <div style="font-size:1.05em;font-weight:700;">{_cat_name}</div>'
                f'  <div style="font-size:0.72em;color:#555;font-style:italic;'
                f'margin-top:2px;">{_sub_jp} <span style="color:#888;">-{_sub_en}-</span></div>'
                f'</div>'
                f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:8px;">'
                f'  <span style="font-size:0.75em;color:#666;">Cos</span>'
                f'  <span style="font-size:1.35em;font-weight:700;color:{_cos_color};">'
                f'{_cos_str}</span>'
                f'  <span style="font-size:0.75em;color:#666;">MAE</span>'
                f'  <span style="font-size:1.05em;color:#333;">{_mae_str}</span>'
                f'</div>'
                f'{_bl_html}'
                f'{_extras}'
                f'</div>'
            )
            _cols[_c].markdown(_card_html, unsafe_allow_html=True)


def _render_summary(result: dict) -> None:
    """Cross-category summary at the top of the screen.

    Two panels shown top-to-bottom:
      1. **Grid** — 3-group (Inside / Flow / Outside) × 7-category layout
         mirroring the Personal Evaluation reference diagram. Each card
         carries the sub-question ("どんなヒトなのか？ -Who-" etc.) and the
         two headline scores (Cos + MAE).
      2. **Radar** — same 7 categories with Cos (blue solid) and MAE
         (red dashed) overlaid on a 0-1 axis.

    Below both, a compact summary table with a per-category Memo string.
    """
    import streamlit as st
    # Fixed canonical order (clockwise from top: 特性 → 価値観 → 動機 → 目標 →
    # 人格形成 → 社会性 → 愛着). Any category present in `result` but not in
    # the canonical list falls to the end so nothing is silently dropped.
    _present = set((result.get("categories") or {}).keys())
    _cats = [c for c in _SUMMARY_CATEGORY_ORDER if c in _present]
    _cats += [c for c in (result.get("category_order") or [])
                if c in _present and c not in _cats]

    rows: list[dict] = []
    for cat in _cats:
        _d   = result["categories"].get(cat) or {}
        _cos = _cat_cos_similarity(cat, _d)
        rows.append({
            "category": cat,
            "type":     "Narrative" if cat in _NARRATIVE_CATEGORIES else "Likert",
            "n":        len(_d.get("narratives") or _d.get("narrative_items")
                             or _d.get("items") or []),
            "cos":      _cos["overall"],
            "mae":      _cos.get("mae"),
            "memo":     _cat_memo(cat, _d),
            "source":   _cos.get("source", ""),
            # Extras carry A↔B / GT↔B Cos & MAE surfaced by _cat_cos_similarity
            # (populated only when a Baseline column was in the Excel).
            "extra":    _cos.get("extra") or {},
        })
    if not rows:
        return

    st.markdown("## サマリー (7カテゴリ横断)")

    # --- 1. Grid layout (Inside / Flow / Outside groups) ---
    _render_summary_grid(rows, result)

    st.markdown("")   # spacer between grid and radar
    st.markdown("---")

    # --- 2. Compact summary table ---
    def _f(x): return f"{x:.3f}" if isinstance(x, (int, float)) else "-"
    _df = pd.DataFrame([
        {
            "Category":         r["category"],
            "Type":              r["type"],
            "n":                r["n"],
            "Cos 類似度 (A↔GT)": _f(r["cos"]),
            "MAE (各項目誤差)":   _f(r["mae"]),
            "Memo":              r["memo"] or "-",
        }
        for r in rows
    ])
    st.dataframe(_df, hide_index=True, use_container_width=True)

    # --- 3. Two radars side-by-side: Cos (left) and MAE (right) ---
    # Each panel overlays up to three comparison pairs so the reader can see
    # both how close Answer(AI) tracks Ground Truth AND how far each side has
    # drifted from the Baseline benchmark model.
    #   - Blue  (solid) : Answer(AI) ↔ Ground Truth  (primary)
    #   - Orange (dashed): Answer(AI) ↔ Baseline
    #   - Brown (dashdot): Ground Truth ↔ Baseline
    labels    = [r["category"] for r in rows]
    _vals_ag_cos = [r["cos"] if r["cos"] is not None else 0.0 for r in rows]
    _vals_ag_mae = [r["mae"] if r["mae"] is not None else 0.0 for r in rows]
    _vals_ab_cos = [(r.get("extra") or {}).get("ab_cos") for r in rows]
    _vals_ab_mae = [(r.get("extra") or {}).get("ab_mae") for r in rows]
    _vals_gb_cos = [(r.get("extra") or {}).get("gb_cos") for r in rows]
    _vals_gb_mae = [(r.get("extra") or {}).get("gb_mae") for r in rows]

    _has_ab = any(v is not None for v in _vals_ab_cos + _vals_ab_mae)
    _has_gb = any(v is not None for v in _vals_gb_cos + _vals_gb_mae)

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    import numpy as _np

    def _sanitize(vs):
        # Replace None with 0.0 so matplotlib can plot; the value 0 lands at
        # the centre which is a natural "no data" position for both metrics.
        return [float(v) if isinstance(v, (int, float)) else 0.0 for v in vs]

    def _draw_panel(ax, title, ag_vals, ab_vals, gb_vals, metric_name):
        ax.set_theta_offset(_np.pi / 2)
        ax.set_theta_direction(-1)
        _angles = _np.linspace(0, 2 * _np.pi, len(labels) + 1)
        _ag = _sanitize(ag_vals) + [_sanitize(ag_vals)[0]]
        # Primary: Answer(AI) ↔ Ground Truth — blue
        ax.plot(_angles, _ag, color="#1565C0", linewidth=2.0,
                 label="Answer(AI) ↔ Ground Truth")
        ax.fill(_angles, _ag, color="#1565C0", alpha=0.18)
        # Secondary: Answer(AI) ↔ Baseline — orange
        if _has_ab:
            _ab = _sanitize(ab_vals) + [_sanitize(ab_vals)[0]]
            ax.plot(_angles, _ab, color="#EF6C00", linewidth=1.6,
                     linestyle="--", label="Answer(AI) ↔ Baseline")
            ax.fill(_angles, _ab, color="#EF6C00", alpha=0.10)
        # Tertiary: Ground Truth ↔ Baseline — brown
        if _has_gb:
            _gb = _sanitize(gb_vals) + [_sanitize(gb_vals)[0]]
            ax.plot(_angles, _gb, color="#6D4C41", linewidth=1.6,
                     linestyle="-.", label="Ground Truth ↔ Baseline")
            ax.fill(_angles, _gb, color="#6D4C41", alpha=0.08)
        # Reference ring — Cos 1.0 = perfect, MAE 1.0 = worst-case
        ax.plot(_angles, [1.0] * len(_angles), color="#888888",
                 linestyle=":", linewidth=1.0, alpha=0.6)
        ax.set_xticks(_angles[:-1])
        try:
            ax.set_xticklabels(labels, fontfamily="IPAexGothic", fontsize=8.5)
        except Exception:
            ax.set_xticklabels(labels, fontsize=8.5)
        ax.set_ylim(0, 1.0)
        ax.set_yticks([0.25, 0.5, 0.75])
        try:
            ax.set_title(title, fontfamily="IPAexGothic", fontsize=11, pad=14)
        except Exception:
            ax.set_title(title, fontsize=11, pad=14)
        try:
            ax.legend(loc="upper right", bbox_to_anchor=(1.32, 1.14),
                       fontsize=7.5,
                       prop={"family": "IPAexGothic", "size": 7.5},
                       frameon=False)
        except Exception:
            pass

    _fig = _plt.figure(figsize=(13, 5.5))
    _ax_cos = _fig.add_subplot(121, projection="polar")
    _ax_mae = _fig.add_subplot(122, projection="polar")
    _draw_panel(_ax_cos, "Cos 類似度 (高いほど良)",
                 _vals_ag_cos, _vals_ab_cos, _vals_gb_cos, "Cos")
    _draw_panel(_ax_mae, "MAE (低いほど良)",
                 _vals_ag_mae, _vals_ab_mae, _vals_gb_mae, "MAE")
    _plt.tight_layout()
    st.pyplot(_fig)
    _plt.close(_fig)

    _caption = (
        "**Cos 類似度**: ベクトル方向の一致 (1.0 = 完全一致)。"
        " **MAE**: 各項目の絶対誤差の平均 (0.0 = 完全一致)。 "
        "左右パネルは同じ 3 種の比較を Cos / MAE で描き分け: "
        "**青**=Answer(AI)↔GT · "
    )
    if _has_ab:
        _caption += "**橙**=Answer(AI)↔Baseline · "
    if _has_gb:
        _caption += "**茶**=GT↔Baseline · "
    _caption += "**灰点線** = 1.0 基準線。"
    st.caption(_caption)


def _summary_md(result: dict) -> list[str]:
    """Markdown mirror of `_render_summary` — used by report_md."""
    out: list[str] = ["", "## サマリー (7カテゴリ横断)", ""]
    _cats = list(result.get("category_order") or [])
    if not _cats:
        return out
    out.append("| Category | Type | n | Cos 類似度 (A↔GT) | MAE (各項目誤差) | Memo |")
    out.append("|------|------|---:|---:|---:|------|")
    for cat in _cats:
        _d   = result["categories"].get(cat) or {}
        _cos = _cat_cos_similarity(cat, _d)
        _n   = len(_d.get("narratives") or _d.get("narrative_items")
                    or _d.get("items") or [])
        _typ = "Narrative" if cat in _NARRATIVE_CATEGORIES else "Likert"
        def _f(x): return f"{x:.3f}" if isinstance(x, (int, float)) else "-"
        _memo = _cat_memo(cat, _d) or "-"
        out.append(
            f"| {cat} | {_typ} | {_n} | {_f(_cos['overall'])} | "
            f"{_f(_cos.get('mae'))} | {_memo} |"
        )
    out.append("")
    out.append("_Ground Truth = 1.0 基準_ · Cos: ベクトル方向の一致 / MAE: 各項目の絶対誤差の平均")
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

    # The per-row similarity bar (Seq Ratio / Token F1) and per-row length
    # comparison were removed — the aggregate dimension table above already
    # summarises what those bars showed, and the LLM-scored radar covers
    # the qualitative side.

    # ---- Side-by-side text comparison per row ----
    # Collapsed by default — the per-row Q/A/GT block can be 10+ rows of long
    # free-form text per category (e.g. 人格形成 has 8 rows). Keep the
    # summary stats + radar above visible, hide the verbose row-by-row body
    # behind an expander the user can pop open on demand.
    # Include a Baseline column in the row layout only if any of the items
    # actually carries baseline text — keeps the two-column layout when the
    # Excel didn't supply a Baseline column.
    _row_has_baseline = any((it.get("baseline") or "").strip() for it in items)
    with st.expander(f"Answer(AI) / Ground Truth 比較 (個別 · {len(items)} 件)", expanded=False):
        for it in items:
            _head = f"**[{it['no']}] {it['axis'] or '(unmapped)'}**"
            _meta = f"  *(Seq={it['seq']:.2f} · F1={it['f1']:.2f} · A={it['len_a']}字 / GT={it['len_b']}字)*"
            st.markdown(_head + _meta)
            if it["question"]:
                st.markdown(f"**Q:** {it['question']}")
            if _row_has_baseline:
                ca, cb, cc = st.columns(3)
            else:
                ca, cb = st.columns(2)
                cc = None
            with ca:
                st.markdown("**Answer(AI)**")
                st.markdown(it["answer"] or "_(empty)_")
            with cb:
                st.markdown("**Ground Truth**")
                st.markdown(it["ground_truth"] or "_(empty)_")
            if cc is not None:
                with cc:
                    st.markdown("**Baseline**")
                    st.markdown(it.get("baseline") or "_(empty)_")
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
        _member_line = " / ".join(
            f"{_SCHWARTZ_JP.get(m, m)}({m})" for m in g["members"]
        )
        line += f"  \n   {g['desc']}"
        line += f"  \n   *{_member_line}が該当*"
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
