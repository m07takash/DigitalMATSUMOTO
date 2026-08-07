"""Evaluation plugin loader.

Plugins live under `user/common/evaluation/<name>/main.py`. Each plugin
exposes a `Plugin` class with the following contract:

    class Plugin:
        name: str                  # internal id (typically the folder name)
        display_name: str          # human label for the picker
        description: str           # short blurb shown under the picker

        @staticmethod
        def sample_path() -> str | None:
            "Path to a sample input file (optional)."
            ...

        @staticmethod
        def run(input_path: str) -> dict:
            "Heavy lifting — read input, score / aggregate / etc., return"
            "a plain JSON-safe dict the renderer & report consume."
            ...

        @staticmethod
        def render(result: dict) -> None:
            "Streamlit render (st.markdown / st.pyplot / st.dataframe / ...)."
            ...

        @staticmethod
        def report_md(result: dict) -> str:
            "Markdown export for `Generate Report`."
            ...

A user can drop a fresh evaluation folder + main.py and it shows up in
the WebUI picker automatically.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EVAL_BASE = Path("user/common/evaluation")


def list_evaluations() -> list[dict[str, Any]]:
    """Return a list of `{folder, name, display_name, description, plugin}`
    dicts for every plugin found under `user/common/evaluation/`. Failures
    on individual plugins are logged and skipped — they never block others."""
    out: list[dict[str, Any]] = []
    if not EVAL_BASE.exists():
        return out
    for folder in sorted(p for p in EVAL_BASE.iterdir() if p.is_dir()):
        if folder.name.startswith(("_", ".")):
            continue
        main_py = folder / "main.py"
        if not main_py.exists():
            continue
        try:
            plugin = _load_plugin(folder, main_py)
        except Exception as e:
            logger.warning(f"[evaluation] failed to load {folder}: {e}")
            continue
        if plugin is None:
            continue
        out.append({
            "folder":       folder.name,
            "name":         getattr(plugin, "name", folder.name),
            "display_name": getattr(plugin, "display_name", folder.name),
            "description":  getattr(plugin, "description", ""),
            "plugin":       plugin,
        })
    return out


def _load_plugin(folder: Path, main_py: Path):
    mod_name = f"digim_eval_plugin__{folder.name}"
    spec = importlib.util.spec_from_file_location(mod_name, main_py)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, "Plugin", None)


def llm_evaluate(plugin, result: dict, agent_file: str,
                  service_info: dict, user_info: dict,
                  user_question: str = "") -> tuple[str, str]:
    """Run an LLM critique of the plugin's result via `agent_file`.
    Returns (markdown_text, model_name).

    Default implementation: feed the plugin's `report_md()` to the agent
    with a Japanese critique prompt.

    When `user_question` is provided (non-empty), the LLM answers that
    specific question WHILE grounding its answer in the analysis result
    — a free-form "ask about this evaluation" mode. Otherwise the default
    strengths/weaknesses/suggestions structure is emitted.

    Plugins can override by defining their own `llm_evaluate(...)` with a
    matching signature (they should accept the `user_question` kwarg to
    stay forward-compatible).
    """
    if hasattr(plugin, "llm_evaluate"):
        try:
            return plugin.llm_evaluate(result, agent_file,
                                         service_info, user_info,
                                         user_question=user_question)
        except TypeError:
            # Legacy plugin without the `user_question` kwarg — call it
            # the old way so nothing breaks; the question is dropped.
            return plugin.llm_evaluate(result, agent_file,
                                         service_info, user_info)

    import DigiM_Agent as dma
    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    engine = agent.agent.get("ENGINE", {}).get(model_type, {})
    model_name = engine.get("MODEL", "")

    md = plugin.report_md(result)
    _uq = (user_question or "").strip()
    if _uq:
        # Q&A mode: answer the operator's free-form question grounded in
        # the analysis result. Prevents hallucination by anchoring every
        # claim to the report body.
        prompt = (
            f"以下は **{getattr(plugin, 'display_name', plugin.name)}** の分析結果です。\n"
            f"この分析結果を踏まえて、下記の質問に Markdown で回答してください。\n"
            f"\n"
            f"【質問】\n{_uq}\n"
            f"\n"
            f"回答指示:\n"
            f"- 分析結果に書かれた事実・数値・傾向のみを根拠にする (推測は最小限)\n"
            f"- 具体的な軸名 / スコア / 目標を引用しながら書く\n"
            f"- 質問と関係ない一般論の講評は不要\n"
            f"- 分量: 300〜800 字を目安 (質問の性質に応じて調整可)\n"
            f"\n"
            f"---\n\n## 分析結果\n\n{md}"
        )
    else:
        prompt = (
            f"以下は **{getattr(plugin, 'display_name', plugin.name)}** の分析結果です。\n"
            f"被評価者の人物像・強み・弱み・改善ポイントを Markdown で講評してください。"
            f"出力は次の見出し構成で:\n"
            f"\n"
            f"### 全体評価\n"
            f"(2〜3行の総評)\n\n"
            f"### 強み\n"
            f"- 箇条書きで3〜5項目\n\n"
            f"### 弱み\n"
            f"- 箇条書きで3〜5項目\n\n"
            f"### 改善提案\n"
            f"- 具体的なアクション3〜5項目\n\n"
            f"---\n\n"
            f"## 分析結果\n\n{md}"
        )

    response = ""
    try:
        for _p, chunk, _comp in agent.generate_response(model_type, prompt):
            if chunk:
                response += chunk
    except Exception as e:
        response = f"[Evaluation error] {type(e).__name__}: {e}"
    return response, model_name


def llm_extract_narrative_scored(category_name: str,
                                   axes: list,
                                   answer_text: str,
                                   gt_text: str,
                                   agent_file: str,
                                   service_info: dict,
                                   user_info: dict) -> tuple[dict, str, str]:
    """Score a narrative category on a fixed axis list and produce a
    similarities / differences commentary.

    Used by PersonalEvaluation for 人格形成 / 社会性 / 愛着 — narrative
    categories where each axis isn't a Likert scoreable item but a
    higher-order construct that needs the LLM to read the whole narrative.

    `axes` is a list of (jp_label, en_label, description) tuples. Both
    Answer(AI) and Ground Truth are scored on every axis with a discrete
    5-step rubric (0.00 / 0.25 / 0.50 / 0.75 / 1.00) for repeatable scoring.

    Returns `({..scored dict..}, model_name, prompt)` — the prompt string
    is returned so the UI can surface it in an expander for transparency
    ("what instruction did we send the LLM?"). On parse failure returns a
    skeleton with zeroed scores + empty strings; the prompt is still returned.
    """
    import DigiM_Agent as dma
    import re as _re
    import json as _json

    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    engine = agent.agent.get("ENGINE", {}).get(model_type, {})
    model_name = engine.get("MODEL", "")

    axes_lines = "\n".join(
        f"- {jp} ({en}): {desc}" for jp, en, desc in axes
    )
    axes_jp_only = [jp for jp, _, _ in axes]
    # Pre-build the JSON skeleton outside the f-string — Python disallows
    # backslashes in f-string expression parts, so `\"...\"` interpolation
    # has to happen via plain string ops.
    _quote = '"'
    _skel_pair = ", ".join(_quote + jp + _quote + ": 0.00" for jp in axes_jp_only)
    _ans_line = '  "answer_scores": { ' + _skel_pair + ' },'
    _gt_line  = '  "gt_scores":     { ' + _skel_pair + ' },'
    # Per-axis notes skeleton — one nested object per axis carrying three
    # short prose summaries (Answer's take / GT's take / A vs GT comparison).
    _axis_note_block = ",\n".join(
        '    "' + jp + '": { '
        '"answer_note": "Answer(AI)の傾向を100〜200字", '
        '"gt_note": "Ground Truthの傾向を100〜200字", '
        '"comparison": "AとGTの比較を100〜200字" '
        '}'
        for jp in axes_jp_only
    )
    _notes_line = '  "per_axis_notes": {\n' + _axis_note_block + '\n  }'

    prompt = (
        f"あなたは「{category_name}」を評価する専門エージェントです。\n"
        f"被評価者の Answer(AI) と Ground Truth の自由記述回答を読み、以下の {len(axes)} 軸でそれぞれ独立に評価してください。\n\n"
        f"【評価軸】\n{axes_lines}\n\n"
        "【スコアリング基準 — 0.00〜1.00 の連続値で意味的に判定】\n"
        "以下の目安をアンカーとして参照し、テキストの意味内容から連続値で判定してください:\n"
        "  - 0.00: 記述に該当する性質が見られない / 完全に欠落\n"
        "  - 0.25: わずかに該当 / 限定的・断片的に触れている\n"
        "  - 0.50: 中程度 / 標準的な水準で見られる\n"
        "  - 0.75: 明確に該当 / 強く表れている\n"
        "  - 1.00: 非常に強く該当 / 典型例レベル\n\n"
        "【スコア安定化のための重要指示】\n"
        "- 0.00〜1.00 の任意の連続値 (小数第 2 位まで) で出力すること。上記アンカー値以外の中間値 (0.10 / 0.37 / 0.68 等) は積極的に活用してよい。\n"
        "- 判定は文字数や長さではなく **意味内容** で行うこと。冗長な文章に高得点、簡潔でも本質を突いた文章に低得点、というバイアスを避ける。\n"
        "- 同じ入力テキストに対しては常に同じスコアを返すこと (温度感の再現性を最優先)\n"
        "- 各軸を独立に評価する。他の軸のスコアに引きずられないこと\n"
        "- 「Answer(AI)」と「Ground Truth」は別々の文章として独立にスコアリングする\n\n"
        "【軸別の講評 — per_axis_notes】\n"
        "各軸について、以下の 3 項目を **それぞれ 100〜200 文字** で記述:\n"
        "- answer_note: **Answer(AI) の回答** がこの軸に関してどう表れているか (具体的な言及やトーンを引用しながら)\n"
        "- gt_note:      **Ground Truth の回答** がこの軸に関してどう表れているか (同上)\n"
        "- comparison:  **Answer(AI) と Ground Truth の比較** — 一致点・ズレ・強調の違いを対比的に\n"
        "- 各項目は独立に書く。answer_note に GT の話を混ぜない、gt_note に A の話を混ぜない。\n"
        "- 引用は要点のみ短く。300 字を超えないこと (100〜200 字が目安)。\n\n"
        "【全体の類似点 / 相違点 — similarities / differences】\n"
        "- similarities: 全体を通した共通する傾向を **200 文字以内** で記述\n"
        "- differences:  全体を通した違いを **200 文字以内** で記述\n"
        "- 軸別講評の総括として書き、per_axis_notes と重複しないよう俯瞰的にまとめる。\n\n"
        "出力は **以下の JSON のみ**。コードフェンスや前後の説明は一切付けないこと。\n"
        "{\n"
        + _ans_line + "\n"
        + _gt_line + "\n"
        + _notes_line + ",\n"
        + '  "similarities": "200文字以内の共通点解説",\n'
        + '  "differences":  "200文字以内の相違点解説"\n'
        + "}\n\n---\n\n"
        f"## Answer(AI)\n{answer_text}\n\n## Ground Truth\n{gt_text}\n"
    )

    raw = ""
    try:
        for _p, chunk, _comp in agent.generate_response(model_type, prompt):
            if chunk:
                raw += chunk
    except Exception:
        raw = ""

    txt = raw.strip()
    if txt.startswith("```"):
        txt = _re.sub(r"^```(?:json)?\s*", "", txt)
        txt = _re.sub(r"\s*```\s*$", "", txt)

    _empty_notes = {jp: {"answer_note": "", "gt_note": "", "comparison": ""}
                    for jp in axes_jp_only}
    skeleton = {
        "answer_scores": {jp: 0.0 for jp in axes_jp_only},
        "gt_scores":     {jp: 0.0 for jp in axes_jp_only},
        "per_axis_notes": _empty_notes,
        "similarities": "",
        "differences":  "",
    }

    def _clip01(v):
        """Coerce the LLM's numeric to a float in [0.0, 1.0] (2 decimals).
        No snapping to discrete steps — the LLM is asked to output continuous
        semantic scores, and we preserve that resolution."""
        try:
            n = float(v)
        except Exception:
            return 0.0
        n = max(0.0, min(1.0, n))
        return round(n, 2)

    try:
        data = _json.loads(txt)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        out = dict(skeleton)
        out["similarities"] = (data.get("similarities") or "")[:600]   # hard cap
        out["differences"]  = (data.get("differences")  or "")[:600]
        for src, dst in [("answer_scores", "answer_scores"),
                          ("gt_scores",     "gt_scores")]:
            sc = data.get(src) or {}
            if not isinstance(sc, dict):
                sc = {}
            out[dst] = {jp: _clip01(sc.get(jp, 0.0)) for jp in axes_jp_only}
        # Per-axis notes — hard-cap each of the three prose fields at 300 chars
        # so a runaway LLM response can't blow up the UI. Missing entries fall
        # back to empty strings (skeleton default).
        _notes_raw = data.get("per_axis_notes") or {}
        if not isinstance(_notes_raw, dict):
            _notes_raw = {}
        _notes_out = {}
        for jp in axes_jp_only:
            _n = _notes_raw.get(jp) or {}
            if not isinstance(_n, dict):
                _n = {}
            _notes_out[jp] = {
                "answer_note": (_n.get("answer_note") or "")[:300],
                "gt_note":     (_n.get("gt_note")     or "")[:300],
                "comparison":  (_n.get("comparison")  or "")[:300],
            }
        out["per_axis_notes"] = _notes_out
        return out, model_name, prompt
    except Exception:
        return skeleton, model_name, prompt


def llm_extract_goals_structured(g1_answer: str, g1_gt: str,
                                   g2_answer: str, g2_gt: str,
                                   g3_answer: str, g3_gt: str,
                                   agent_file: str,
                                   service_info: dict, user_info: dict) -> tuple[dict, str, str]:
    """Structured Goals analyzer for PersonalEvaluation.

    Reads G1 (goal list), G2 (per-goal self-evaluation), G3 (synergy /
    trade-off) from both Answer(AI) and Ground Truth, and asks the LLM to
    return a strict-JSON object the renderer can consume directly. The
    returned dict has this shape (all keys present; lists may be empty):

        {
          "answer_only": [{"label", "text", "importance", "commitment",
                            "feasibility", "achievement"}],
          "common":      [{"label", "answer_text", "gt_text",
                            "answer_importance", "answer_commitment", ...,
                            "gt_importance", "gt_commitment", ...}],
          "gt_only":     [{"label", "text", "importance", ...}],
          "edges_answer":[{"from": "label", "to": "label", "kind": "synergy"|"tradeoff"}],
          "edges_gt":    [...]
        }

    Returns (parsed_dict, model_name). On LLM/parse failure the dict has the
    schema above with empty lists, so the renderer never crashes.
    """
    import DigiM_Agent as dma
    import re as _re
    import json as _json
    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    engine = agent.agent.get("ENGINE", {}).get(model_type, {})
    model_name = engine.get("MODEL", "")

    prompt = (
        "あなたは目標分析エージェントです。被評価者が挙げた目標群を構造化して JSON だけを返してください。\n\n"
        "入力データ:\n"
        "- 「Answer(AI)」と「Ground Truth」それぞれに 3 種類の自由記述がある:\n"
        "  - G1: 目標一覧 (箇条書き)\n"
        "  - G2: 各目標の自己評価 (大切さ / 本気度 / 達成見込み / 達成度 についてのコメント)\n"
        "  - G3: 目標同士のシナジー / トレードオフ\n\n"
        "やってほしいこと:\n"
        "1. 各箇条書き目標を **1 〜 4 文字程度の日本語の単語** (label) に要約する。意味的に重複する場合は同じ label に揃える\n"
        "2. Answer / GT 双方の目標を比較し、`common` / `answer_only` / `gt_only` に分類\n"
        "3. G2 から各目標の評点 4 軸を抽出し、High / Medium / Low の 3 値に分類 (`H` / `M` / `L`)\n"
        "   - 「最重要」「かなり本気」「ほぼ確実」「ほぼ完了」など → H\n"
        "   - 「そこそこ」「半分」「五分五分」「途中」など → M\n"
        "   - 「あまり」「弱い」「難しい」「未達」など → L\n"
        "   - 記述がなければ M を入れる\n"
        "4. G3 から目標同士の関係を抽出し、Answer 由来は edges_answer に、GT 由来は edges_gt に。\n"
        "   - kind: \"synergy\" (相乗 / 同時進行 / ハーモニー / 一方を進めるともう一方も進む) "
        "または \"tradeoff\" (コンフリクト / 一方を進めるともう一方が犠牲になる)\n"
        "   - **同一 G3 内に synergy と tradeoff の両方が語られている場合、両方とも edges に含めること。**\n"
        "   - G3 の記述が抽象的でも、被評価者が「関係がある」と示唆したペアは必ずエッジ化する (無理でなければ synergy 側で入れる)。\n"
        "   - from / to は必ず手順1で決めた label (`common` / `answer_only` / `gt_only` のいずれかに登場する label と厳密に一致させる)。\n"
        "   - **edges_answer と edges_gt は 0 件でも許容されるが、G3 に関係の言及がある限り最低 1 本は抽出すること。**\n"
        "   - 例:\n"
        "     - 「健康維持と学習継続は同時に進められる」→ {\"from\":\"健康\",\"to\":\"学習\",\"kind\":\"synergy\"}\n"
        "     - 「起業に時間を割くと家族との時間が減る」→ {\"from\":\"起業\",\"to\":\"家族\",\"kind\":\"tradeoff\"}\n"
        "\n"
        "出力は **以下の JSON のみ** 。前後の説明文・コードフェンスは一切付けないこと。\n"
        '{\n'
        '  \"answer_only\": [{\"label\":\"...\",\"text\":\"原文\",\"importance\":\"H|M|L\",\"commitment\":\"H|M|L\",\"feasibility\":\"H|M|L\",\"achievement\":\"H|M|L\"}],\n'
        '  \"common\":      [{\"label\":\"...\",\"answer_text\":\"原文\",\"gt_text\":\"原文\",\"answer_importance\":\"H|M|L\",\"answer_commitment\":\"H|M|L\",\"answer_feasibility\":\"H|M|L\",\"answer_achievement\":\"H|M|L\",\"gt_importance\":\"H|M|L\",\"gt_commitment\":\"H|M|L\",\"gt_feasibility\":\"H|M|L\",\"gt_achievement\":\"H|M|L\"}],\n'
        '  \"gt_only\":     [{\"label\":\"...\",\"text\":\"原文\",\"importance\":\"H|M|L\",\"commitment\":\"H|M|L\",\"feasibility\":\"H|M|L\",\"achievement\":\"H|M|L\"}],\n'
        '  \"edges_answer\":[{\"from\":\"label\",\"to\":\"label\",\"kind\":\"synergy|tradeoff\"}],\n'
        '  \"edges_gt\":    [{\"from\":\"label\",\"to\":\"label\",\"kind\":\"synergy|tradeoff\"}]\n'
        '}\n'
        "\n---\n\n"
        f"## G1.Answer(AI)\n{g1_answer}\n\n## G1.Ground Truth\n{g1_gt}\n\n"
        f"## G2.Answer(AI)\n{g2_answer}\n\n## G2.Ground Truth\n{g2_gt}\n\n"
        f"## G3.Answer(AI)\n{g3_answer}\n\n## G3.Ground Truth\n{g3_gt}\n"
    )

    raw = ""
    try:
        for _p, chunk, _comp in agent.generate_response(model_type, prompt):
            if chunk:
                raw += chunk
    except Exception as e:
        raw = ""

    # Strip code fences if the LLM ignored the "no fences" instruction.
    txt = raw.strip()
    if txt.startswith("```"):
        txt = _re.sub(r"^```(?:json)?\s*", "", txt)
        txt = _re.sub(r"\s*```\s*$", "", txt)

    # Empty-skeleton fallback (renderer expects all 5 top-level keys).
    skeleton = {"answer_only": [], "common": [], "gt_only": [],
                 "edges_answer": [], "edges_gt": []}
    try:
        data = _json.loads(txt)
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        # Fill any missing keys
        for k, v in skeleton.items():
            if k not in data or not isinstance(data[k], list):
                data[k] = v
    except Exception:
        data = skeleton
    # Deterministic fallback: LLMs frequently drop edges (esp. Gemini/Haiku on
    # under-specified prompts). Parse the raw G3 text for "X and Y: synergy /
    # trade-off" patterns and merge with whatever the LLM produced so the
    # 2×2 harmony/conflict grid is not empty when the input clearly lists
    # relations. Never removes an LLM edge — only adds ones the LLM missed.
    try:
        _parsed_a = _parse_goal_relations_from_text(g3_answer, data)
        _parsed_g = _parse_goal_relations_from_text(g3_gt,     data)
        data["edges_answer"] = _merge_relation_edges(
            data.get("edges_answer") or [], _parsed_a)
        data["edges_gt"] = _merge_relation_edges(
            data.get("edges_gt")     or [], _parsed_g)
    except Exception:
        # Fallback parser is best-effort; never break the extractor.
        pass
    # Return the prompt too so the UI can surface it (transparency: operators
    # want to see exactly what instruction we sent the LLM).
    return data, model_name, prompt


# --- G3 deterministic parser ------------------------------------------------
# LLMs are inconsistent about extracting edges from the G3 relations question.
# When the operator's G3 text is a structured list like
#   "exercise and family: synergy / reading and study group: synergy / exercise and study group: trade-off"
# a regex parser can pull the pairs reliably and match them back to the LLM's
# goal labels (via substring). Used as a fallback after `llm_extract_goals_
# structured` returns to fill in edges the LLM missed.

_HARMONY_KEYWORDS = ("シナジー", "ハーモニー", "相乗", "同時進行",
                       "harmony", "synergy", "同時に", "両立")
_CONFLICT_KEYWORDS = ("コンフリクト", "トレードオフ", "犠牲", "conflict",
                        "tradeoff", "trade-off", "trade off",
                        "対立", "衝突")


def _match_goal_label(term: str, labels: list) -> str:
    """Find the goal label most similar to `term`. Two-way substring so a
    goal labelled '運動' matches a term '運動継続' and vice versa.
    Returns None when no plausible match."""
    if not term or not labels:
        return None
    _t = term.strip().lower()
    if not _t:
        return None
    for _lbl in labels:
        _l = (_lbl or "").strip().lower()
        if not _l:
            continue
        if _t == _l or _t in _l or _l in _t:
            return _lbl
    return None


def _parse_goal_relations_from_text(text: str, parsed_goals: dict) -> list:
    """Extract `[{from, to, kind}]` edges from a G3 free-text response.

    Recognised patterns per line/chunk:
      - `X と Y: シナジー`      → synergy edge
      - `X と Y: ハーモニー`
      - `X と Y: トレードオフ`  → tradeoff edge
      - `X と Y: コンフリクト`
    Chunks are split on newline / `/` / `・` / `、` / `,` so structured lists
    are handled naturally. Terms are matched to goal labels via `_match_goal_label`.
    """
    import re as _re
    if not text or not isinstance(text, str):
        return []
    _all_labels = list(dict.fromkeys(
        [(g or {}).get("label", "") for g in parsed_goals.get("common",      []) or []] +
        [(g or {}).get("label", "") for g in parsed_goals.get("answer_only", []) or []] +
        [(g or {}).get("label", "") for g in parsed_goals.get("gt_only",     []) or []]
    ))
    _all_labels = [_l for _l in _all_labels if _l]
    if not _all_labels:
        return []
    _out = []
    _seen = set()
    for _chunk in _re.split(r'[\n／/、,;・]+', text):
        _chunk = _chunk.strip()
        if not _chunk:
            continue
        # Loose "X と Y: kind" / "X ↔ Y: kind" / "X to Y: kind" pattern
        _m = _re.match(r'(.+?)\s*[とと＆&↔⇔と-]{1,2}\s*(.+?)\s*[:：\-]\s*(.+)',
                        _chunk)
        if not _m:
            continue
        _a_term, _b_term, _kind_str = _m.groups()
        _kind_low = (_kind_str or "").lower()
        _kind = None
        for _kw in _HARMONY_KEYWORDS:
            if _kw.lower() in _kind_low:
                _kind = "synergy"; break
        if _kind is None:
            for _kw in _CONFLICT_KEYWORDS:
                if _kw.lower() in _kind_low:
                    _kind = "tradeoff"; break
        if _kind is None:
            continue
        _from = _match_goal_label(_a_term, _all_labels)
        _to   = _match_goal_label(_b_term, _all_labels)
        if not _from or not _to or _from == _to:
            continue
        _key = (tuple(sorted([_from, _to])), _kind)
        if _key in _seen:
            continue
        _seen.add(_key)
        _out.append({"from": _from, "to": _to, "kind": _kind})
    return _out


def _merge_relation_edges(existing: list, extra: list) -> list:
    """Union of two edge lists, deduped by (canonical pair, kind).
    Existing entries win on collision (LLM output takes precedence when
    the same edge was inferred both by the LLM and the parser)."""
    def _key(e):
        return (tuple(sorted([(e or {}).get("from", ""),
                                (e or {}).get("to", "")])),
                (e or {}).get("kind", "synergy"))
    _out = list(existing or [])
    _seen = {_key(e) for e in _out}
    for _e in (extra or []):
        _k = _key(_e)
        if _k in _seen:
            continue
        _seen.add(_k)
        _out.append(_e)
    return _out


def llm_compare_overall(sections: list, agent_file: str,
                         service_info: dict, user_info: dict,
                         plugin_name: str = "") -> tuple[str, str]:
    """Unified commentary covering all sections in one LLM call.

    `sections` is a list of `{"name": str, "md": str}` — the サマリー entry
    first, then each category in the order they appear on screen. The
    prompt asks for ~1000 字, formatted as a short readable overview
    followed by per-category detail so the reader gets both the headline
    and the specifics from a single expander. Returns `(markdown, model)`.
    """
    import DigiM_Agent as dma
    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    engine = agent.agent.get("ENGINE", {}).get(model_type, {})
    model_name = engine.get("MODEL", "")

    _ctx = plugin_name or "評価結果"
    # Concatenate every section with a clear heading so the LLM can address
    # each one individually in the per-category detail block below.
    _bodies = "\n\n".join(
        f"## {s['name']}\n\n{s['md']}" for s in sections if s.get("md")
    )
    prompt = (
        f"以下は **{_ctx}** の評価結果です。「Answer(AI)」(被評価エージェント) と "
        f"「Ground Truth」(正解 / 期待値) を全カテゴリー横断で解説してください。\n"
        f"\n"
        f"出力構成 (Markdown, 全体で **約1000字** を目安):\n"
        f"\n"
        f"### サマリー\n"
        f"- 3〜5行の読みやすい総評。Answer(AI) と Ground Truth の全体的な近さ / 傾向 / 特に目立つ相違点を平易な文章で。\n"
        f"\n"
        f"### カテゴリー別解説\n"
        f"- 各カテゴリー (サマリー以外) について **見出し (`#### カテゴリー名`) + 2〜4文の解説**。\n"
        f"- 共通点と相違点の両方に触れ、代表的なスコアや軸名を具体的に引用する。\n"
        f"- ナラティブ (目標 / 人格形成) は志向 / トーン / 強調点で比較する。\n"
        f"\n"
        f"注意:\n"
        f"- 前置きや締めの決まり文句 (「以下解説します」等) は不要。\n"
        f"- 全体で 900〜1200 字程度に収めること。\n"
        f"- 冗長な繰り返しは避け、各カテゴリーは重複しない観点で書く。\n"
        f"\n"
        f"---\n\n{_bodies}"
    )

    response = ""
    try:
        for _p, chunk, _comp in agent.generate_response(model_type, prompt):
            if chunk:
                response += chunk
    except Exception as e:
        response = f"[Overall commentary error] {type(e).__name__}: {e}"
    return response, model_name


def llm_compare_section(section_name: str, section_md: str, agent_file: str,
                         service_info: dict, user_info: dict,
                         plugin_name: str = "") -> tuple[str, str]:
    """Per-section commentary: ask the LLM to highlight commonalities and
    differences between Answer(AI) and Ground Truth for one section only.

    The prompt is intentionally tighter than `llm_evaluate` so the response
    stays focused on a single category. Returns `(markdown_text, model_name)`.
    """
    import DigiM_Agent as dma
    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    engine = agent.agent.get("ENGINE", {}).get(model_type, {})
    model_name = engine.get("MODEL", "")

    _ctx = f"{plugin_name} - {section_name}" if plugin_name else section_name
    prompt = (
        f"以下は **{_ctx}** の評価結果です。\n"
        f"「Answer(AI)」(被評価エージェントの回答) と「Ground Truth」(正解 / 期待値) を比較し、"
        f"**共通点** と **相違点** を簡潔に解説してください。\n"
        f"\n"
        f"出力構成 (Markdown):\n"
        f"\n"
        f"### 共通点\n"
        f"- 箇条書きで 2〜5項目\n"
        f"\n"
        f"### 相違点\n"
        f"- 箇条書きで 2〜5項目\n"
        f"\n"
        f"注意:\n"
        f"- 各項目は1〜2文で簡潔に。冗長な前置きや総評は不要。\n"
        f"- 数値スコアや軸ラベルが含まれる場合は具体的に言及する。\n"
        f"- ナラティブテキストの場合は内容の方向性 (志向 / トーン / 強調点) で比較する。\n"
        f"\n"
        f"---\n\n"
        f"## 評価結果\n\n{section_md}"
    )

    response = ""
    try:
        for _p, chunk, _comp in agent.generate_response(model_type, prompt):
            if chunk:
                response += chunk
    except Exception as e:
        response = f"[Section commentary error] {type(e).__name__}: {e}"
    return response, model_name
