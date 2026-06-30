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
                  service_info: dict, user_info: dict) -> tuple[str, str]:
    """Run an LLM critique of the plugin's result via `agent_file`.
    Returns (markdown_text, model_name).

    Default implementation: feed the plugin's `report_md()` to the agent
    with a Japanese critique prompt. Plugins can override by defining their
    own `llm_evaluate(result, agent_file, service_info, user_info)`."""
    if hasattr(plugin, "llm_evaluate"):
        return plugin.llm_evaluate(result, agent_file, service_info, user_info)

    import DigiM_Agent as dma
    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    engine = agent.agent.get("ENGINE", {}).get(model_type, {})
    model_name = engine.get("MODEL", "")

    md = plugin.report_md(result)
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
                                   user_info: dict) -> tuple[dict, str]:
    """Score a narrative category on a fixed axis list and produce a
    similarities / differences commentary.

    Used by PersonalEvaluation for 人格形成 / 社会性 / 愛着 — narrative
    categories where each axis isn't a Likert scoreable item but a
    higher-order construct that needs the LLM to read the whole narrative.

    `axes` is a list of (jp_label, en_label, description) tuples. Both
    Answer(AI) and Ground Truth are scored on every axis with a discrete
    5-step rubric (0.00 / 0.25 / 0.50 / 0.75 / 1.00) for repeatable scoring.

    Returns ({"answer_scores", "gt_scores", "similarities", "differences"}, model_name).
    On parse failure returns a skeleton with zeroed scores + empty strings.
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

    prompt = (
        f"あなたは「{category_name}」を評価する専門エージェントです。\n"
        f"被評価者の Answer(AI) と Ground Truth の自由記述回答を読み、以下の {len(axes)} 軸でそれぞれ独立に評価してください。\n\n"
        f"【評価軸】\n{axes_lines}\n\n"
        "【スコアリング基準 — 5段階の離散値のみ使用】\n"
        "スコアは必ず以下のいずれかに丸めること:\n"
        "  - 0.00: 記述に該当する性質が見られない / 完全に欠落\n"
        "  - 0.25: わずかに該当 / 限定的・断片的に触れている\n"
        "  - 0.50: 中程度 / 標準的な水準で見られる\n"
        "  - 0.75: 明確に該当 / 強く表れている\n"
        "  - 1.00: 非常に強く該当 / 典型例レベル\n\n"
        "【スコア安定化のための重要指示】\n"
        "- 必ず {0.00, 0.25, 0.50, 0.75, 1.00} のいずれかの値で出力すること (0.1 / 0.6 のような中間値は禁止)\n"
        "- 同じ入力テキストに対しては常に同じスコアを返すこと\n"
        "- 判断に迷う場合は中央値 (0.50) を選び、確信が無い場合に極端な値を避ける\n"
        "- 各軸を独立に評価する。他の軸のスコアに引きずられないこと\n"
        "- 「Answer(AI)」と「Ground Truth」は別々の文章として独立にスコアリングする\n\n"
        "【類似点 / 相違点の出力】\n"
        "- similarities: Answer(AI) と Ground Truth で共通する傾向を **300 文字以内** で記述\n"
        "- differences:  Answer(AI) と Ground Truth の違いを **300 文字以内** で記述\n"
        "- 軸の名前を引用しながら具体的に書く (例: 「物語的一貫性は両者とも高い (0.75)」)\n\n"
        "出力は **以下の JSON のみ**。コードフェンスや前後の説明は一切付けないこと。\n"
        "{\n"
        + _ans_line + "\n"
        + _gt_line + "\n"
        + '  "similarities": "300文字以内の共通点解説",\n'
        + '  "differences":  "300文字以内の相違点解説"\n'
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

    skeleton = {
        "answer_scores": {jp: 0.0 for jp in axes_jp_only},
        "gt_scores":     {jp: 0.0 for jp in axes_jp_only},
        "similarities": "",
        "differences":  "",
    }

    def _snap(v):
        """Snap any numeric the LLM returned to the nearest of {0, .25, .5, .75, 1}."""
        try:
            n = float(v)
        except Exception:
            return 0.0
        steps = [0.0, 0.25, 0.5, 0.75, 1.0]
        return min(steps, key=lambda s: abs(s - n))

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
            out[dst] = {jp: _snap(sc.get(jp, 0.0)) for jp in axes_jp_only}
        return out, model_name
    except Exception:
        return skeleton, model_name


def llm_extract_goals_structured(g1_answer: str, g1_gt: str,
                                   g2_answer: str, g2_gt: str,
                                   g3_answer: str, g3_gt: str,
                                   agent_file: str,
                                   service_info: dict, user_info: dict) -> tuple[dict, str]:
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
        "   - kind: \"synergy\" (相乗 / 同時進行) または \"tradeoff\" (一方を進めるともう一方が犠牲)\n"
        "   - from / to は手順1で決めた label\n"
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
    return data, model_name


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
