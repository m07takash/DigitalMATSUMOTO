"""動物占い (Animal Fortune) Evaluation plugin — 60-subtype questionnaire.

Structure mirrors PersonalEvaluation, scaled up to two scoring axes:

  - **Animal axis** (12 categories): determines the base animal type.
  - **Color  axis** ( 5 categories): determines the color/flavor modifier
    (レッド / イエロー / グリーン / ブルー / ブラック).

A combined `<color> の <animal>` label produces one of **60 subtypes**.

Excel layout (single sheet, `AnimalTest`):

    | No | Category | Question Style | Question | Memo | Answer | ... |

`Memo` carries one of:
  - a base animal name (`チータ`, `たぬき`, ... 12 total) → adds to animal axis
  - a color name (`レッド`, `イエロー`, ... 5 total)     → adds to color axis

Answer keyword → 0–1 score is identical to PersonalEvaluation
(はい=1.0 / どちらでもない=0.5 / いいえ=0.0, plus 1-5 / 1-7 scales).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path as _Path
from typing import Any

import pandas as pd


_PLUGIN_DIR = _Path(__file__).resolve().parent

# --- Axis 1: 12 base animals -------------------------------------------------

_ANIMALS_12 = [
    "チータ", "たぬき", "猿", "コアラ", "黒ひょう", "虎",
    "ライオン", "ペガサス", "狼", "子鹿", "羊", "ゾウ",
]

_ANIMAL_TRAITS = {
    "チータ":   "瞬発力と決断力。スピード感のある行動派。せっかちで結論を急ぐ傾向あり。",
    "たぬき":   "親しみやすく安定志向。経験値で勝負するベテラン気質。古風な価値観を持つ。",
    "猿":       "明るく機敏。短期集中型でゲーム感覚で物事を進める。注目を浴びるのが好き。",
    "コアラ":   "マイペース・癒し系。穏やかでロマンチスト。ストレスに弱い面も。",
    "黒ひょう": "スマートで新しい物好き。プライドが高く流行に敏感。プレッシャーには弱め。",
    "虎":       "正義感と責任感に厚く、リーダーシップ抜群。義理人情に厚いマイペース。",
    "ライオン": "堂々として威厳あり。リーダー気質、プライド高め、完璧主義。",
    "ペガサス": "自由奔放な直感型。気分屋で芸術的センス。束縛を嫌う。",
    "狼":       "個性的な一匹狼。独自の世界観と芸術肌。協調より独立を選ぶ。",
    "子鹿":     "警戒心が強く繊細。きめ細やかで気配り上手。慎重派。",
    "羊":       "平和主義で人間関係重視。優しく親切なグループ志向。",
    "ゾウ":     "努力家・着実派。目標達成へコツコツ進む負けず嫌い。",
}

# --- Axis 2: 5 colors --------------------------------------------------------

_COLORS_5 = ["レッド", "イエロー", "グリーン", "ブルー", "ブラック"]

_COLOR_TRAITS = {
    "レッド":   "情熱・行動力・リーダー気質。エネルギッシュで突破力に長ける。",
    "イエロー": "明るく社交的・楽天的。場を明るくするユーモアと前向きさが武器。",
    "グリーン": "穏やかで調和的・癒し系。共感力が高く、人間関係をまろやかにする。",
    "ブルー":   "知的・冷静・分析的。論理と精度を重視し、感情に流されにくい。",
    "ブラック": "個性的・神秘的・独自路線。流行や常識に流されず独自の世界観を持つ。",
}

# Plot colors for the bar chart of the color axis (best-effort hex).
_COLOR_HEX = {
    "レッド":   "#D9534F",
    "イエロー": "#F0AD4E",
    "グリーン": "#5CB85C",
    "ブルー":   "#4A90D9",
    "ブラック": "#444444",
}

# Answer keyword → 0..1 score (same heuristic as PersonalEvaluation).
_KEYWORD_SCORE = [
    (("どちらでもない",), 0.5),
    (("はい", "yes", "Yes", "YES"), 1.0),
    (("いいえ", "no ", "No", "NO", "いえ"), 0.0),
    (("そう思う", "Agree", "agree"), 1.0),
    (("そう思わない", "Disagree", "disagree"), 0.0),
    (("中立", "Neutral", "neutral"), 0.5),
    (("非常に当てはまる", "Strongly Agree"), 1.0),
    (("全く当てはまらない", "Strongly Disagree"), 0.0),
]


def _norm(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float) and pd.isna(x):
        return ""
    return str(x).strip()


def _score_answer(answer: Any) -> float | None:
    if answer is None:
        return None
    a = _norm(answer)
    if not a:
        return None
    for keys, score in _KEYWORD_SCORE:
        for k in keys:
            if k in a:
                return score
    m = re.match(r"^\s*([1-7])\s*$", a)
    if m:
        n = int(m.group(1))
        return (n - 1) / 6.0 if n > 5 else (n - 1) / 4.0
    return None


def _subtype_label(animal: str, color: str) -> str:
    if not animal or not color:
        return animal or color or ""
    return f"{color}の{animal}"


def _subtype_description(animal: str, color: str) -> str:
    a = _ANIMAL_TRAITS.get(animal, "")
    c = _COLOR_TRAITS.get(color, "")
    if not a and not c:
        return ""
    return f"【動物軸: {animal}】 {a}\n\n【色軸: {color}】 {c}"


class Plugin:
    name         = "AnimalFortune"
    display_name = "動物占い (Animal Fortune)"
    description  = (
        "44問のアンケートに答えると、**12種の動物 × 5色 = 60サブタイプ** から"
        "あなたに最も近いタイプを判定します。"
        "Memo 列が動物名 (`チータ`/`たぬき` 等) の質問は動物軸、"
        "色名 (`レッド`/`イエロー` 等) の質問は色軸に集計されます。"
    )

    @staticmethod
    def sample_path() -> str:
        return str(_PLUGIN_DIR / "AnimalFortuneTemplate.xlsx")

    @staticmethod
    def run(input_path: str) -> dict[str, Any]:
        try:
            df_cat = pd.read_excel(input_path, sheet_name="Category")
            df_qa  = pd.read_excel(input_path, sheet_name="AnimalTest")
        except Exception as e:
            return {"error": f"Failed to read Excel: {e}"}

        # Per-axis score buckets.
        animal_scores: dict[str, list[float]] = {a: [] for a in _ANIMALS_12}
        color_scores:  dict[str, list[float]] = {c: [] for c in _COLORS_5}
        narratives: list[dict] = []
        scored_animal = scored_color = unscored = 0

        for _, r in df_qa.iterrows():
            memo = _norm(r.get("Memo"))
            answer = _norm(r.get("Answer"))
            question = _norm(r.get("Question"))
            no = _norm(r.get("No"))
            score = _score_answer(answer)
            axis = ""
            if memo in animal_scores and score is not None:
                animal_scores[memo].append(score); scored_animal += 1; axis = "animal"
            elif memo in color_scores and score is not None:
                color_scores[memo].append(score);  scored_color += 1;  axis = "color"
            elif answer:
                unscored += 1
            narratives.append({
                "no": no,
                "axis": axis,
                "label": memo if memo in animal_scores or memo in color_scores else "",
                "question": question,
                "answer": answer,
            })

        # Aggregate per axis (mean over the bucket).
        animal_avg = {a: round(sum(vs) / len(vs), 3) if vs else 0.0
                       for a, vs in animal_scores.items()}
        color_avg  = {c: round(sum(vs) / len(vs), 3) if vs else 0.0
                       for c, vs in color_scores.items()}

        animal_rank = sorted(animal_avg.items(), key=lambda kv: -kv[1])
        color_rank  = sorted(color_avg.items(),  key=lambda kv: -kv[1])

        top_animal = animal_rank[0][0] if animal_rank and animal_rank[0][1] > 0 else ""
        top_color  = color_rank[0][0]  if color_rank  and color_rank[0][1]  > 0 else ""

        # Category meta
        cat_meta = {}
        if not df_cat.empty:
            row0 = df_cat.iloc[0].to_dict()
            cat_meta = {
                "header":  _norm(row0.get("カテゴリー")),
                "items":   _norm(row0.get("評価項目")),
                "theory":  _norm(row0.get("理論")),
                "method":  _norm(row0.get("分析方法")),
            }

        return {
            "input_path":   input_path,
            "row_count":    int(len(df_qa)),
            "scored_animal": scored_animal,
            "scored_color":  scored_color,
            "unscored":     unscored,
            "animal_scores": animal_avg,
            "color_scores":  color_avg,
            "animal_rank":   animal_rank,
            "color_rank":    color_rank,
            "top_animal":    top_animal,
            "top_color":     top_color,
            "subtype":       _subtype_label(top_animal, top_color),
            "subtype_desc":  _subtype_description(top_animal, top_color),
            "narratives":    narratives,
            "category":      cat_meta,
            "generated_at":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    @staticmethod
    def render(result: dict[str, Any]) -> None:
        import streamlit as st
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if "error" in result:
            st.error(result["error"])
            return

        st.caption(
            f"Questions: **{result['row_count']}**  /  "
            f"animal-scored: **{result['scored_animal']}**  /  "
            f"color-scored: **{result['scored_color']}**  /  "
            f"unscored: **{result['unscored']}**  /  "
            f"Generated: {result.get('generated_at','')}"
        )
        if (result.get("category") or {}).get("theory"):
            st.caption(f"理論: **{result['category']['theory']}**")

        # 60-subtype banner
        st.markdown(f"## あなたのタイプ: **{result.get('subtype') or '(判定不可)'}**")
        desc = result.get("subtype_desc", "")
        if desc:
            st.markdown(desc)
        if not result.get("top_animal") or not result.get("top_color"):
            st.warning(
                "動物軸・色軸のいずれかで採点可能な Answer が見つかりませんでした。"
                "両方の質問に回答していただくと、60サブタイプの判定結果が出ます。"
            )

        # === Animal axis ====
        st.markdown("#### 動物軸 (12タイプ) スコア")
        a_ord = {a: result["animal_scores"].get(a, 0.0) for a in _ANIMALS_12}
        fig, ax = plt.subplots(figsize=(9, 3.4))
        top_a = result.get("top_animal")
        colors_a = ["#1565C0" if a == top_a else "#9AA8C0" for a in a_ord]
        ax.bar(a_ord.keys(), a_ord.values(), color=colors_a, alpha=0.9)
        ax.set_xticklabels(a_ord.keys(), rotation=30, ha="right",
                            fontfamily="IPAexGothic", fontsize=9)
        ax.set_ylim(0, 1); ax.set_ylabel("Score (0–1)")
        ax.grid(True, alpha=0.3, axis="y")
        plt.tight_layout()
        st.pyplot(fig); plt.close(fig)

        # === Color axis ====
        st.markdown("#### 色軸 (5タイプ) スコア")
        c_ord = {c: result["color_scores"].get(c, 0.0) for c in _COLORS_5}
        fig, ax = plt.subplots(figsize=(6, 3.0))
        top_c = result.get("top_color")
        colors_c = [_COLOR_HEX.get(c, "#9AA8C0") for c in c_ord]
        alphas   = [1.0 if c == top_c else 0.45 for c in c_ord]
        bars = ax.bar(c_ord.keys(), c_ord.values(), color=colors_c)
        for b, al in zip(bars, alphas):
            b.set_alpha(al)
        ax.set_xticklabels(c_ord.keys(), fontfamily="IPAexGothic", fontsize=9)
        ax.set_ylim(0, 1); ax.set_ylabel("Score (0–1)")
        ax.grid(True, alpha=0.3, axis="y")
        plt.tight_layout()
        st.pyplot(fig); plt.close(fig)

        # Ranking tables
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("##### 動物軸ランキング")
            st.dataframe(
                pd.DataFrame([
                    {"Rank": i + 1, "Animal": a, "Score": v,
                     "Trait": _ANIMAL_TRAITS.get(a, "")[:60]}
                    for i, (a, v) in enumerate(result["animal_rank"])
                ]),
                hide_index=True, use_container_width=True,
            )
        with col2:
            st.markdown("##### 色軸ランキング")
            st.dataframe(
                pd.DataFrame([
                    {"Rank": i + 1, "Color": c, "Score": v,
                     "Trait": _COLOR_TRAITS.get(c, "")[:60]}
                    for i, (c, v) in enumerate(result["color_rank"])
                ]),
                hide_index=True, use_container_width=True,
            )

        # Question / Answer detail
        if result.get("narratives"):
            with st.expander(
                f"質問と回答 ({len(result['narratives'])})", expanded=False
            ):
                for n in result["narratives"]:
                    head = f"**[{n['no']}] {n['label'] or '(unmapped)'}** ({n['axis'] or '-'})"
                    st.markdown(head)
                    if n["question"]:
                        st.markdown(f"- Q: {n['question']}")
                    if n["answer"]:
                        st.markdown(f"- A: {n['answer']}")

    @staticmethod
    def report_md(result: dict[str, Any]) -> str:
        if "error" in result:
            return f"# Animal Fortune\n\nError: {result['error']}\n"
        lines = [
            "# Animal Fortune Report", "",
            f"- **Generated**: {result.get('generated_at','')}",
            f"- **Questions**: {result['row_count']}  /  "
            f"animal-scored: {result['scored_animal']}  /  "
            f"color-scored: {result['scored_color']}  /  "
            f"unscored: {result['unscored']}",
        ]
        if (result.get("category") or {}).get("theory"):
            lines.append(f"- **理論**: {result['category']['theory']}")
        lines.append("")

        subtype = result.get("subtype", "")
        if subtype:
            lines.append(f"## あなたのタイプ: **{subtype}**")
            if result.get("subtype_desc"):
                lines.append(result["subtype_desc"])
            lines.append("")

        lines += ["## 動物軸ランキング (12タイプ)", ""]
        lines.append("| Rank | Animal | Score | Trait |")
        lines.append("|---:|------|---:|------|")
        for i, (a, v) in enumerate(result.get("animal_rank", []), start=1):
            lines.append(f"| {i} | {a} | {v:.2f} | {_ANIMAL_TRAITS.get(a, '')} |")
        lines.append("")
        lines += ["## 色軸ランキング (5タイプ)", ""]
        lines.append("| Rank | Color | Score | Trait |")
        lines.append("|---:|------|---:|------|")
        for i, (c, v) in enumerate(result.get("color_rank", []), start=1):
            lines.append(f"| {i} | {c} | {v:.2f} | {_COLOR_TRAITS.get(c, '')} |")
        lines.append("")

        if result.get("narratives"):
            lines.append("<details><summary>質問と回答</summary>")
            lines.append("")
            for n in result["narratives"]:
                tag = f"**[{n['no']}] {n['label'] or '(unmapped)'}** ({n['axis'] or '-'})"
                lines.append(f"- {tag}")
                if n["question"]:
                    lines.append(f"  - Q: {n['question']}")
                if n["answer"]:
                    lines.append(f"  - A: {n['answer']}")
            lines.append("</details>")
        return "\n".join(lines)
