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
