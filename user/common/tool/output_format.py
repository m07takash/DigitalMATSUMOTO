"""Prompt text for the output-format flag skills (`diagram_mode`,
`emphasis_mode`).

These two SKILLs set an execution flag instead of calling a function, but the
wording they add to the main prompt is still tool content, so it lives here
rather than in the executor. `DigiM_Tool.__getattr__` resolves module-level
names in loaded plugins, so the executor reads them as `dmt.<NAME>`.

Nothing is registered: there is no function to dispatch. Editing the wording
takes effect on the next Streamlit restart, with no code change elsewhere.
"""

# Mermaid is fenced so the WebUI renderer can pick the blocks out of the
# Markdown body.
DIAGRAM_INSTRUCTION = (
    "\n\n【図解の指示】\n"
    "説明の理解を助ける箇所では、文章に加えて図解を用いてください。\n"
    "・比較・分類・一覧は Markdown の表にする\n"
    "・関係性/流れ/構造は Mermaid のコードブロック（```mermaid）で図示する\n"
    "　（flowchart, sequenceDiagram, graph TD などを用途に応じて使い分ける）\n"
    "・図解が不要な内容に無理に図を付けない。文章だけで足りる場合はそのままでよい\n"
)

# Bounded on purpose: emphasis only reads as emphasis while it stays rare, so
# the rules cap how much of the text may be marked up rather than just asking
# for "more emphasis".
EMPHASIS_INSTRUCTION = (
    "\n\n【強調の指示】\n"
    "読み手が要点を拾えるよう、本文中の重要箇所に Markdown の強調を用いてください。\n"
    "・結論・判断・数値・固有名詞など、その回答の核心となる語句を **太字** にする\n"
    "・特に注意すべき点や例外は **太字** に加えて簡潔な理由を添える\n"
    "・回答が長くなる場合は見出し（##／###）で区切り、箇条書きを併用する\n"
    "・強調は多用しない。1段落あたり1〜2箇所を目安とし、文全体を太字にしない\n"
    "・口調や人格設定は変えない。あくまで書式のみの指示\n"
)
