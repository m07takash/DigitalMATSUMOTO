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
from typing import Any

import pandas as pd


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
        return "test/PersonalTestQA.xlsx"

    @staticmethod
    def run(input_path: str) -> dict[str, Any]:
        try:
            df_cat = pd.read_excel(input_path, sheet_name="Category")
            df_qa  = pd.read_excel(input_path, sheet_name="PersonalTest")
        except Exception as e:
            return {"error": f"Failed to read Excel: {e}"}

        # Category meta lookup
        cat_meta = _build_category_meta(df_cat)
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
        st.markdown("---")
        for cat in result.get("category_order", []):
            data = result["categories"][cat]
            _render_category(cat, data)
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
            "",
        ]
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


def _score_answer(answer: Any) -> float | None:
    """Heuristic 0.0–1.0 score from an Answer cell, or None when unscorable."""
    if answer is None:
        return None
    a = _norm(answer)
    if not a:
        return None
    # Keyword scan (case-preserving but reasonable)
    for keys, score in _KEYWORD_SCORE:
        for k in keys:
            if k in a:
                return score
    # Bare number 1-5 or 1-7
    m = re.match(r"^\s*([1-7])\s*$", a)
    if m:
        n = int(m.group(1))
        return (n - 1) / 6.0 if n > 5 else (n - 1) / 4.0
    return None


def _analyze_category(cat: str, rows: list[dict]) -> dict:
    axes_raw: dict[str, list[float]] = {}
    narratives: list[dict] = []
    scored = unscored = 0
    for r in rows:
        memo = _norm(r.get("Memo"))
        answer = _norm(r.get("Answer"))
        gt = _norm(r.get("Ground Truth"))
        question = _norm(r.get("Question"))
        question_style = _norm(r.get("Question Style"))
        no = _norm(r.get("No"))
        axis, reverse = _parse_axis(memo)

        score = _score_answer(answer)
        if score is not None and axis:
            adj = (1.0 - score) if reverse else score
            axes_raw.setdefault(axis, []).append(adj)
            scored += 1
        elif answer:
            unscored += 1

        narratives.append({
            "no": no, "axis": axis, "memo": memo, "reverse": reverse,
            "question_style": question_style, "question": question,
            "answer": answer, "ground_truth": gt,
        })

    axes_avg = {k: round(sum(v) / len(v), 3) for k, v in axes_raw.items() if v}

    return {
        "axes_avg":   axes_avg,
        "axes_raw":   axes_raw,
        "narratives": narratives,
        "scored":     scored,
        "unscored":   unscored,
    }


def _radar(labels: list[str], values: list[float], title: str):
    """Polar radar chart (returns the matplotlib Figure)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from math import pi
    if not labels or not values:
        return None
    n = len(labels)
    angles = [i / n * 2 * pi for i in range(n)]
    angles += angles[:1]
    vv = list(values) + [values[0]]
    fig = plt.figure(figsize=(4.5, 4.5))
    ax = plt.subplot(111, polar=True)
    ax.set_theta_offset(pi / 2)
    ax.set_theta_direction(-1)
    plt.xticks(angles[:-1], labels, fontfamily="IPAexGothic", fontsize=9)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.25, 0.5, 0.75])
    ax.set_yticklabels(["0.25", "0.50", "0.75"], fontsize=7)
    ax.plot(angles, vv, linewidth=1.5, color="#1565C0")
    ax.fill(angles, vv, alpha=0.25, color="#1565C0")
    ax.grid(True, alpha=0.4)
    plt.title(title, fontfamily="IPAexGothic", fontsize=11)
    plt.tight_layout()
    return fig


def _render_category(cat: str, data: dict) -> None:
    import streamlit as st
    meta = data.get("meta") or {}
    st.markdown(f"### {cat}")
    if meta.get("theory"):
        st.caption(f"理論: **{meta['theory']}**")
    if meta.get("items"):
        st.caption(meta["items"][:300])

    axes = data.get("axes_avg") or {}
    if axes:
        col1, col2 = st.columns([3, 2])
        if len(axes) >= 3:
            fig = _radar(list(axes.keys()), list(axes.values()),
                          f"{cat} (n={data['scored']})")
            if fig is not None:
                with col1:
                    import streamlit as _st
                    _st.pyplot(fig)
                    import matplotlib.pyplot as _plt
                    _plt.close(fig)
        with col2:
            st.markdown("**Scores (0–1):**")
            df = pd.DataFrame(
                [{"Axis": k, "Score": v} for k, v in axes.items()]
            ).sort_values("Score", ascending=False)
            st.dataframe(df, hide_index=True, use_container_width=True)
        st.caption(f"scored: **{data['scored']}**  /  unscored: **{data['unscored']}**")
    elif data["narratives"]:
        st.caption(
            f"narrative-only category — {len(data['narratives'])} answers below"
            f" (use LLM evaluation for scoring)"
        )

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


def _category_to_md(cat: str, data: dict) -> str:
    lines = []
    meta = data.get("meta") or {}
    if meta.get("theory"):
        lines.append(f"- 理論: **{meta['theory']}**")
    if meta.get("items"):
        lines.append(f"- 評価項目: {meta['items'][:300]}")
    axes = data.get("axes_avg") or {}
    if axes:
        lines.append("")
        lines.append(f"**Scores ({data['scored']} scored / {data['unscored']} unscored):**")
        lines.append("")
        lines.append("| Axis | Score |")
        lines.append("|------|------:|")
        for k, v in sorted(axes.items(), key=lambda x: -x[1]):
            lines.append(f"| {k} | {v:.2f} |")
    if data["narratives"]:
        lines.append("")
        lines.append(f"<details><summary>Answers ({len(data['narratives'])})</summary>")
        lines.append("")
        for n in data["narratives"]:
            tag = f"**[{n['no']}] {n['axis'] or n['memo']}**"
            if n.get("reverse"): tag += " _(reverse)_"
            lines.append(f"- {tag}")
            if n["question"]:
                lines.append(f"  - Q: {n['question']}")
            if n["answer"]:
                lines.append(f"  - A: {n['answer']}")
            if n["ground_truth"]:
                lines.append(f"  - GT: {n['ground_truth']}")
        lines.append("</details>")
    return "\n".join(lines)
