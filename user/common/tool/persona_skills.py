"""Persona-flavoured SKILL tools designed to fire only 'いざという時' —
never on every turn. Each registration below has a `description` phrased
so the Thinking Agent can judge WHEN the tool is relevant. Optional
MAGIC_WORDS live on the agent's `SKILL.TOOLS[<name>].MAGIC_WORDS` list
(the orchestrator auto-fires when a magic word appears in the user
query).

Layout mirrors `analysis.py` (import path + 6-tuple LLM return / 4-tuple
direct-action return; `_invoke_skill` in DigiM_Execute disambiguates).
"""
import json as _json
import os
from pathlib import Path

import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Context as dmc
import DigiM_ToolRegistry as dmtr


_settings = dmu.read_yaml_file("setting.yaml")

_INPUT_TEXT = {
    "type": "string",
    "description": "Free-form text — typically the user's query or the target sentence.",
}


# ---------------------------------------------------------------- LLM helper
def _run_lightweight_llm(agent_file, prompt, memories=None):
    """Load the tool's dedicated support agent (or fall back to the caller's
    agent_file) and run a single non-streaming LLM turn against `prompt`.
    Returns (response_text, model_name, prompt_tokens, response_tokens)."""
    if not agent_file:
        agent_file = "agent_50Thinking.json"
    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    response = ""
    for _p, chunk, _c in agent.generate_response(
            model_type, prompt, memories or [], stream_mode=False):
        if chunk:
            response += chunk
    return (response,
            model_name,
            dmu.count_token(tokenizer, model_name, prompt),
            dmu.count_token(tokenizer, model_name, response))


# ---------------------------------------------------------------- BEFORE-1
def recall_similar_experience(service_info, user_info, session_id, session_name,
                                agent_file, input, import_contents=[], add_info={}):
    """Search the parent agent's Vector KNOWLEDGE for chunks similar to the
    current query and surface the top match(es) as a short 'recall' note.
    Used as a BEFORE SKILL so the agent leaves a `SKILL(recall_similar_experience)`
    log in the transcript ('自分の過去の類似経験を思い出す'); the recalled
    context stays visible to later memory retrieval turns."""
    if not agent_file:
        return service_info, user_info, "", []
    agent = dma.DigiM_Agent(agent_file)
    query = input or ""
    if not query.strip():
        return service_info, user_info, "", []
    try:
        query_vec = dmu.embed_texts_batch([query.replace("\n", "")])[0]
    except Exception as _e:
        return service_info, user_info, f"[Error embedding query: {_e}]", []
    try:
        _kn_ctx, kn_selected = agent.set_knowledge_context(
            query, query_vecs=[query_vec], exec_info={},
            meta_searches=[], private_mode=True)
    except Exception as _e:
        return service_info, user_info, f"[Error retrieving RAG: {_e}]", []
    # Cherry-pick the top 3 chunks with the strongest similarity to the
    # query — vector RAG only. PageIndex / Graph results are formatted
    # strings and would need dedicated parsing, so skip them here.
    picked = []
    for c in kn_selected or []:
        if not isinstance(c, dict):
            continue
        title = c.get("title") or "(no title)"
        text = (c.get("value_text") or "")
        if isinstance(text, str) and text:
            text = text[:280].replace("\n", " ")
            picked.append((title, text, c.get("similarity_prompt", 0)))
        if len(picked) >= 3:
            break
    if not picked:
        return service_info, user_info, "[過去の類似経験は見つかりませんでした]", []
    lines = ["【想起した過去の類似経験】"]
    for title, snippet, sim in picked:
        lines.append(f"- {title}: {snippet}")
    return service_info, user_info, "\n".join(lines), []


# ---------------------------------------------------------------- BEFORE-2
def analyze_attachment(service_info, user_info, session_id, session_name,
                        agent_file, input, import_contents=[], add_info={}):
    """Read the turn's attached files (CSV / TXT / MD) and build a logical
    feature note: shape, top columns, distinct values, obvious outliers.
    BEFORE SKILL — the note lands in the transcript as
    `SKILL(analyze_attachment)`. No effect on the HABIT prompt unless the
    same content flows through CONTENTS resolution downstream."""
    if not import_contents:
        # Sometimes attachments arrive via add_info instead of the positional
        # arg (contents pipeline is chain-configurable).
        import_contents = add_info.get("contents") or add_info.get("attachments") or []
    if not import_contents:
        return service_info, user_info, "[添付ファイルが見つかりません]", []
    notes = ["【添付データのロジカル特徴】"]
    for _path in import_contents[:3]:
        _path = str(_path) if not isinstance(_path, str) else _path
        _name = os.path.basename(_path) or _path
        try:
            if _path.lower().endswith(".csv"):
                import pandas as _pd
                _df = _pd.read_csv(_path, nrows=1000)
                notes.append(f"- {_name}: 行数≈{len(_df)} / 列 {list(_df.columns)[:8]}")
                # Numeric column summary
                _num = _df.select_dtypes(include="number").columns[:3]
                for _col in _num:
                    _s = _df[_col].dropna()
                    if len(_s):
                        notes.append(f"    · {_col}: min={_s.min():.2f}, "
                                     f"max={_s.max():.2f}, mean={_s.mean():.2f}")
                # Top categorical values
                _obj = _df.select_dtypes(include="object").columns[:2]
                for _col in _obj:
                    _vc = _df[_col].value_counts().head(3)
                    if len(_vc):
                        notes.append(f"    · {_col} top: " + ", ".join(f"{k}({v})" for k, v in _vc.items()))
            elif _path.lower().endswith((".txt", ".md")):
                with open(_path, encoding="utf-8", errors="replace") as _f:
                    _txt = _f.read()
                _lines = _txt.splitlines()
                notes.append(f"- {_name}: {len(_lines)} 行 / {len(_txt)} 字")
                _head = _txt[:200].replace("\n", " ")
                notes.append(f"    · 冒頭: {_head}...")
            else:
                notes.append(f"- {_name}: (未対応の拡張子、要目視)")
        except Exception as _e:
            notes.append(f"- {_name}: (読み取りエラー: {_e})")
    return service_info, user_info, "\n".join(notes), []


# ---------------------------------------------------------------- AFTER-1
def mood_score(service_info, user_info, session_id, session_name,
                agent_file, input, import_contents=[], add_info={}):
    """Score conversation-level emotions for BOTH speakers on Plutchik's 8
    basic axes. AFTER SKILL — receives the HABIT response as `input` (the
    assistant's line). Digest / prior turns are best fetched via add_info
    to avoid a large re-load; this MVP scores just the two most recent
    lines (user query + assistant response)."""
    prev_user = add_info.get("last_user_query", "")
    response = input or ""
    _prompt = (
        "以下は最新の対話ターンです。ユーザーとアシスタントそれぞれについて、"
        "Plutchikの8基本感情 (joy, trust, fear, surprise, sadness, disgust, anger, "
        "anticipation) の強度を0.0〜1.0で推定し、以下のJSONだけを返してください。\n"
        '```json\n{"user": {"joy": 0.0, "trust": 0.0, "fear": 0.0, "surprise": 0.0, '
        '"sadness": 0.0, "disgust": 0.0, "anger": 0.0, "anticipation": 0.0},\n'
        '"assistant": {"joy": 0.0, ...}}\n```\n\n'
        f"【ユーザーの発言】\n{prev_user}\n\n"
        f"【アシスタントの発言】\n{response}\n"
    )
    _hint = add_info.get("model_agent") or "agent_50Thinking.json"
    text, model_name, ptok, rtok = _run_lightweight_llm(_hint, _prompt)
    parsed = ""
    try:
        import re as _re
        m = _re.search(r"\{.*\}", text, _re.S)
        if m:
            _obj = _json.loads(m.group(0))
            _u = _obj.get("user") or {}
            _a = _obj.get("assistant") or {}
            _fmt = lambda d: ", ".join(f"{k}:{v:.2f}" for k, v in d.items() if isinstance(v, (int, float)) and v > 0)
            parsed = f"【感情スコア】\n- ユーザー: {_fmt(_u) or 'flat'}\n- アシスタント: {_fmt(_a) or 'flat'}"
    except Exception:
        pass
    return (service_info, user_info,
            parsed or f"【感情スコア (raw)】\n{text}",
            model_name, ptok, rtok)


# ---------------------------------------------------------------- AFTER-2
def self_critique(service_info, user_info, session_id, session_name,
                    agent_file, input, import_contents=[], add_info={}):
    """Have a lightweight LLM look at the assistant's own response and list
    up to 3 devil's-advocate points (missing angles, unsupported claims,
    persona drift). AFTER SKILL — the critique is a self-check, not shown
    to the end user by default (they see it via Detail Info / transcript
    as `SKILL(self_critique)`)."""
    response = input or ""
    if not response.strip():
        return (service_info, user_info, "[批判対象の応答が空です]", "", 0, 0)
    _prompt = (
        "以下はあなた自身が直前に生成した回答です。ジャーナリストとして自分の主張に"
        "対して批判的に検討し、以下の3項目それぞれについて最大1つずつ短い箇条書きで"
        "指摘してください。該当なしは 'なし' と書いて構いません。丁寧語不要。\n"
        "- 反論・別視点\n"
        "- 断定的で出典が薄い箇所\n"
        "- 論点が外れている箇所\n\n"
        f"【あなたの回答】\n{response}\n"
    )
    _hint = add_info.get("model_agent") or "agent_50Thinking.json"
    text, model_name, ptok, rtok = _run_lightweight_llm(_hint, _prompt)
    return service_info, user_info, f"【セルフクリティーク】\n{text}", model_name, ptok, rtok


# ---------------------------------------------------------------- AFTER-4
def slide_deck_prompt(service_info, user_info, session_id, session_name,
                        agent_file, input, import_contents=[], add_info={}):
    """Build a ready-to-paste prompt for a slide-generation AI (Gamma /
    Beautiful.AI / Canva Magic Studio / etc.) that maps the assistant's
    latest response onto a coherent PowerPoint deck: cover, agenda,
    section slides with talking points + suggested visual, and a
    closing slide. AFTER SKILL — leaves the produced prompt in the
    transcript as `SKILL(slide_deck_prompt)` so the user can copy it
    into whichever slide-AI they prefer."""
    response = input or ""
    if not response.strip():
        return (service_info, user_info, "[スライド化対象の応答が空です]", "", 0, 0)
    slides = int(add_info.get("slide_count") or 6)
    aspect = str(add_info.get("aspect") or "16:9")
    style = str(add_info.get("style") or "クリーンで日本語ビジネス向け、写真・図表を効果的に")
    lang = str(add_info.get("prompt_lang") or "Japanese")
    _prompt = (
        f"以下の【元の応答文】を {slides} 枚程度の PowerPoint スライドに構成する"
        "ため、スライド生成AI（Gamma / Beautiful.AI / Canva Magic Studio 等）に"
        f"投入する **{lang} の指示プロンプト** を作成してください。プロンプトの形式は:\n"
        "1) 冒頭にデッキ全体のテーマ / 想定オーディエンス / ゴールを 1〜2 行で要約\n"
        "2) スライドごとに `## Slide N: <タイトル>` 見出し + 「箇条書きの本文3〜5点」+ "
        "「[Visual] 想定される図/写真/グラフの説明」 の 3 ブロックで記述\n"
        "3) 表紙 (Cover) と締め (Wrap-up / CTA) を含める\n"
        f"4) スライドアスペクト比 {aspect}、トーン: {style}\n"
        "5) 最後にスライド生成AIへの補足指示（フォント推奨・色数制限・データ可視化ヒント）を"
        "1〜2 行で追加\n\n"
        "元の応答文の主張・数値・固有名詞は忠実に反映し、スライド1枚あたりの情報量は"
        "過多にならないよう要点を絞ってください。プロンプトそのものだけを出力し、余分な"
        "前置き・後記は書かないでください。\n\n"
        f"---\n【元の応答文】\n{response}\n---\n"
    )
    _hint = add_info.get("model_agent") or "agent_50Thinking.json"
    text, model_name, ptok, rtok = _run_lightweight_llm(_hint, _prompt)
    return service_info, user_info, f"【スライド生成AIへのプロンプト】\n{text}", model_name, ptok, rtok


# ---------------------------------------------------------------- AFTER-3
def translate_response(service_info, user_info, session_id, session_name,
                        agent_file, input, import_contents=[], add_info={}):
    """Translate the assistant's response into a target language given in
    add_info['target_lang'] (default English). AFTER SKILL — leaves the
    translation in the transcript so the user sees the original response
    from the HABIT plus a following `SKILL(translate_response)` turn with
    the translated text."""
    response = input or ""
    lang = str(add_info.get("target_lang") or "English")
    if not response.strip():
        return (service_info, user_info, "[翻訳対象の応答が空です]", "", 0, 0)
    _prompt = (
        f"Translate the following text into {lang}. Keep proper nouns, "
        "numbers, and dates unchanged. Preserve the original tone. Return "
        "only the translated text, no preface.\n\n"
        f"---\n{response}\n---\n"
    )
    _hint = add_info.get("model_agent") or "agent_50Thinking.json"
    text, model_name, ptok, rtok = _run_lightweight_llm(_hint, _prompt)
    return service_info, user_info, f"【Translated to {lang}】\n{text}", model_name, ptok, rtok


# ---------------------------------------------------------------- registrations
dmtr.register_tool(
    "recall_similar_experience",
    description=(
        "Recall the agent's own past similar experience from their Vector "
        "KNOWLEDGE. Use ONLY when the user asks the agent to reflect on "
        "personal experience, remember a past event, or compare to "
        "something the agent has lived through. Do NOT use for factual "
        "queries about the outside world."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=recall_similar_experience,
    example="/recall_similar_experience 移民取材で似た話があった？",
)

dmtr.register_tool(
    "analyze_attachment",
    description=(
        "Extract logical features (shape, columns, top values, min/max, "
        "outlier hints) from files the user attached this turn (CSV / TXT "
        "/ MD). Use ONLY when the turn has attachments AND the user asks "
        "about their content, patterns, characteristics, or structure."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=analyze_attachment,
    example="/analyze_attachment この CSV の特徴を教えて",
)

dmtr.register_tool(
    "mood_score",
    description=(
        "Score the conversation's emotional state for BOTH the user and "
        "the assistant using Plutchik's 8 basic emotions (joy, trust, "
        "fear, surprise, sadness, disgust, anger, anticipation). Use ONLY "
        "in reflective / emotionally-charged conversations where reading "
        "the room helps, not for factual Q&A."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=mood_score,
    example="/mood_score",
)

dmtr.register_tool(
    "self_critique",
    description=(
        "Critically inspect the assistant's own most recent response for "
        "counter-arguments, unsupported claims, and off-topic drift (max "
        "3 points, journalist-style). Use ONLY on opinion-heavy or "
        "important claim-based responses; skip for casual chat."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=self_critique,
    example="/self_critique",
)

dmtr.register_tool(
    "translate_response",
    description=(
        "Translate the assistant's most recent response into a target "
        "language specified in ARGS_HINT.target_lang (default English). "
        "Use ONLY when the user explicitly asks for a translation or "
        "names a specific target language."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=translate_response,
    example="/translate_response ← 直前の応答を英訳",
)

dmtr.register_tool(
    "slide_deck_prompt",
    description=(
        "Turn the assistant's most recent response into a ready-to-paste "
        "prompt for a slide-generation AI (Gamma / Beautiful.AI / Canva "
        "Magic Studio / PowerPoint Copilot) — with cover / agenda / "
        "section slides (bullets + suggested visual) / closing. Use ONLY "
        "when the user asks to summarise the answer as slides / a deck / "
        "a presentation, or wants a paste-ready prompt for slide AI."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=slide_deck_prompt,
    example="/slide_deck_prompt ← 直前の応答をスライド化するAI向けプロンプトを作る",
)
