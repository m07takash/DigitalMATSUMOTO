"""
Support-Agent performance evaluation.
Run _build_intent_queries / _build_meta_searches against each engine and
compare speed and output.

CLI:
  python3 DigiM_SupportEval.py input.xlsx                                          # Both
  python3 DigiM_SupportEval.py input.xlsx --target intent                          # RAG query generation only
  python3 DigiM_SupportEval.py input.xlsx --target meta                            # Meta search only
  python3 DigiM_SupportEval.py input.xlsx --agent agent_01DigitalMATSUMOTO.json    # Specify an agent

Input Excel format (sheet name: questions):
  | no | question                          |
  |----|-----------------------------------|
  | 1  | What do you think about AI governance? |
  | 2  | What was a recent book you enjoyed?    |

  * If there is no header, the first column is treated as `question`.
"""
import os
import io
import sys
import copy
from datetime import datetime
from pathlib import Path

import pandas as pd
import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Execute as dme

# Set folder paths from setting.yaml
system_setting_dict = dmu.read_yaml_file("setting.yaml")
test_folder_path = system_setting_dict["TEST_FOLDER"]

# Default main agent
DEFAULT_AGENT_FILE = "agent_X0Sample.json"

SERVICE_INFO = {"SERVICE_ID": "SupportEval", "SERVICE_DATA": {}}
USER_INFO = {"USER_ID": "EvalUser", "USER_DATA": {}}

def _new_session_id():
    return f"EVAL_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

def load_questions(excel_path):
    """Load the list of questions from the Excel file."""
    df = pd.read_excel(excel_path, sheet_name=0)
    if "question" in df.columns:
        return df["question"].dropna().tolist()
    else:
        return df.iloc[:, 0].dropna().tolist()

def get_support_targets(agent_file):
    """Return support-agent info that can be evaluated for this agent."""
    agent = dma.DigiM_Agent(agent_file)
    support_agent = agent.agent.get("SUPPORT_AGENT", {})
    targets = {}
    if "RAG_QUERY_GENERATOR" in support_agent:
        sa_file = support_agent["RAG_QUERY_GENERATOR"]
        engines = get_engines(sa_file)
        targets["intent"] = {"agent_file": sa_file, "engines": engines, "label": "RAG query generation"}
    if "EXTRACT_DATE" in support_agent:
        sa_file = support_agent["EXTRACT_DATE"]
        engines = get_engines(sa_file)
        targets["meta"] = {"agent_file": sa_file, "engines": engines, "label": "Meta search"}
    return targets

def get_engines(agent_file):
    """Return the list of engines defined for an agent."""
    agent_data = dmu.read_json_file(agent_file, dma.agent_folder_path)
    return [k for k in agent_data["ENGINE"]["LLM"] if k != "DEFAULT"]

def override_engine(support_agent, key, engine_name):
    """Temporarily override the DEFAULT engine of the support agent's JSON."""
    agent_file = support_agent[key]
    agent_data = dmu.read_json_file(agent_file, dma.agent_folder_path)
    agent_data["ENGINE"]["LLM"]["DEFAULT"] = engine_name
    dma._agent_cache[agent_file] = (0, copy.deepcopy(agent_data))

def restore_cache(agent_file):
    """Clear the cache to revert the override."""
    dma._agent_cache.pop(agent_file, None)

def run_intent_eval(support_agent, engines, questions, question_vecs, progress_callback=None):
    """Evaluate RAG query generation."""
    agent_file = support_agent["RAG_QUERY_GENERATOR"]
    session_id = _new_session_id()
    results = []
    total = len(engines) * len(questions)
    done = 0

    for engine_name in engines:
        for i, question in enumerate(questions):
            override_engine(support_agent, "RAG_QUERY_GENERATOR", engine_name)
            try:
                intent_queries, intent_vecs, log = dme._build_intent_queries(
                    SERVICE_INFO, USER_INFO, session_id, "eval",
                    support_agent, question, [], "", question_vecs[i], True
                )
                response = log.get("llm_response", "")
                duration = log.get("duration_sec", 0)
                model = log.get("model", engine_name)
                prompt_tokens = log.get("prompt_token", 0)
                response_tokens = log.get("response_token", 0)
                status = "OK"
            except Exception as e:
                response = str(e)
                duration = 0
                model = engine_name
                prompt_tokens = 0
                response_tokens = 0
                status = "ERROR"
            finally:
                restore_cache(agent_file)

            results.append({
                "type": "intent",
                "engine": engine_name,
                "model": model,
                "question_no": i + 1,
                "question": question,
                "response": response,
                "elapsed_sec": duration,
                "prompt_tokens": prompt_tokens,
                "response_tokens": response_tokens,
                "status": status,
            })
            done += 1
            if progress_callback:
                progress_callback(done / total, f"[Intent] {engine_name} Q{i+1}/{len(questions)}")

    return results

def run_meta_eval(support_agent, engines, questions, question_vecs, progress_callback=None):
    """Evaluate meta search."""
    agent_file = support_agent["EXTRACT_DATE"]
    session_id = _new_session_id()
    results = []
    total = len(engines) * len(questions)
    done = 0

    for engine_name in engines:
        for i, question in enumerate(questions):
            override_engine(support_agent, "EXTRACT_DATE", engine_name)
            try:
                meta_searches, log = dme._build_meta_searches(
                    SERVICE_INFO, USER_INFO, session_id, "eval",
                    support_agent, question, [], "", question_vecs[i], True
                )
                date_log = log.get("date", {})
                response = date_log.get("llm_response", "")
                duration = date_log.get("duration_sec", 0)
                model = date_log.get("model", engine_name)
                prompt_tokens = date_log.get("prompt_token", 0)
                response_tokens = date_log.get("response_token", 0)
                condition = str(date_log.get("condition_list", []))
                status = "OK"
            except Exception as e:
                response = str(e)
                duration = 0
                model = engine_name
                prompt_tokens = 0
                response_tokens = 0
                condition = ""
                status = "ERROR"
            finally:
                restore_cache(agent_file)

            results.append({
                "type": "meta",
                "engine": engine_name,
                "model": model,
                "question_no": i + 1,
                "question": question,
                "response": response,
                "condition": condition,
                "elapsed_sec": duration,
                "prompt_tokens": prompt_tokens,
                "response_tokens": response_tokens,
                "status": status,
            })
            done += 1
            if progress_callback:
                progress_callback(done / total, f"[Meta] {engine_name} Q{i+1}/{len(questions)}")

    return results

def build_summary(results):
    """Build the summary rows."""
    summary_rows = []
    for result_type in ["intent", "meta"]:
        type_results = [r for r in results if r["type"] == result_type]
        if not type_results:
            continue
        engines = list(dict.fromkeys(r["engine"] for r in type_results))
        for engine in engines:
            rows = [r for r in type_results if r["engine"] == engine]
            ok_rows = [r for r in rows if r["status"] == "OK"]
            err = len(rows) - len(ok_rows)
            if ok_rows:
                times = [r["elapsed_sec"] for r in ok_rows]
                summary_rows.append({
                    "type": result_type, "engine": engine,
                    "avg_sec": round(sum(times)/len(times), 2),
                    "min_sec": round(min(times), 2), "max_sec": round(max(times), 2),
                    "success": len(ok_rows), "error": err,
                })
            else:
                summary_rows.append({
                    "type": result_type, "engine": engine,
                    "avg_sec": None, "min_sec": None, "max_sec": None,
                    "success": 0, "error": err,
                })
    return summary_rows

def save_excel_bytes(results, questions):
    """Return the result Excel as raw bytes (for WebUI downloads)."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        _write_excel_sheets(writer, results, questions)
    buf.seek(0)
    return buf.getvalue()

def save_excel_file(results, output_path, questions):
    """Save the results to an Excel file (CLI)."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        _write_excel_sheets(writer, results, questions)
    print(f"\nResults saved to {output_path}.")

def _apply_wrap_format(writer, sheet_name):
    """Enable text wrapping."""
    from openpyxl.styles import Alignment
    ws = writer.sheets[sheet_name]
    wrap_align = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, str) and "\n" in cell.value:
                cell.alignment = wrap_align

def _write_excel_sheets(writer, results, questions):
    """Shared Excel-writing logic."""
    for result_type in ["intent", "meta"]:
        type_results = [r for r in results if r["type"] == result_type]
        if not type_results:
            continue
        df = pd.DataFrame(type_results)
        df.to_excel(writer, sheet_name=result_type, index=False)
        _apply_wrap_format(writer, result_type)

        pivot_resp = df.pivot_table(index="question_no", columns="engine", values="response", aggfunc="first")
        pivot_time = df.pivot_table(index="question_no", columns="engine", values="elapsed_sec", aggfunc="first")
        q_map = {i+1: q for i, q in enumerate(questions)}
        pivot_resp.insert(0, "question", pivot_resp.index.map(q_map))
        pivot_time.insert(0, "question", pivot_time.index.map(q_map))
        pivot_resp.to_excel(writer, sheet_name=f"{result_type}_response", index=True)
        _apply_wrap_format(writer, f"{result_type}_response")
        pivot_time.to_excel(writer, sheet_name=f"{result_type}_time", index=True)

    summary_rows = build_summary(results)
    if summary_rows:
        pd.DataFrame(summary_rows).to_excel(writer, sheet_name="summary", index=False)

def print_summary(results, label):
    """Print the summary to the console."""
    engines = list(dict.fromkeys(r["engine"] for r in results))
    print(f"\n{'=' * 90}")
    print(f"Summary: {label}")
    print(f"{'=' * 90}")
    print(f"{'engine':<30} {'avg(s)':<10} {'min(s)':<10} {'max(s)':<10} {'OK':<6} {'err':<6}")
    print("-" * 90)
    for engine in engines:
        rows = [r for r in results if r["engine"] == engine]
        ok_rows = [r for r in rows if r["status"] == "OK"]
        err = len(rows) - len(ok_rows)
        if ok_rows:
            times = [r["elapsed_sec"] for r in ok_rows]
            print(f"{engine:<30} {sum(times)/len(times):<10.2f} {min(times):<10.2f} {max(times):<10.2f} {len(ok_rows):<6} {err:<6}")
        else:
            print(f"{engine:<30} {'N/A':<10} {'N/A':<10} {'N/A':<10} {0:<6} {err:<6}")

# ---------- Entry point for the WebUI ----------
def run_eval_for_ui(agent_file, target, engines, questions, progress_callback=None):
    """Evaluation entry point called from the WebUI.
    Args:
        agent_file: Main agent file.
        target: "intent" / "meta" / "both"
        engines: List of engine names to evaluate.
        questions: List of questions.
        progress_callback: Callback of the form progress_callback(ratio, text).
    Returns:
        (results, summary, excel_bytes)
    """
    agent = dma.DigiM_Agent(agent_file)
    support_agent = agent.agent["SUPPORT_AGENT"]

    # Vectorize the questions
    question_vecs = dmu.embed_texts_batch([q.replace("\n", "") for q in questions])

    all_results = []

    if target in ("both", "intent") and "RAG_QUERY_GENERATOR" in support_agent:
        intent_results = run_intent_eval(support_agent, engines, questions, question_vecs, progress_callback)
        all_results.extend(intent_results)

    if target in ("both", "meta") and "EXTRACT_DATE" in support_agent:
        meta_results = run_meta_eval(support_agent, engines, questions, question_vecs, progress_callback)
        all_results.extend(meta_results)

    summary = build_summary(all_results)
    excel_bytes = save_excel_bytes(all_results, questions)
    return all_results, summary, excel_bytes

# ---------- CLI ----------
def main():
    args = sys.argv[1:]
    excel_file = None
    target = "both"
    agent_file = DEFAULT_AGENT_FILE

    for i, arg in enumerate(args):
        if arg == "--target" and i + 1 < len(args):
            target = args[i + 1]
        elif arg == "--agent" and i + 1 < len(args):
            agent_file = args[i + 1]
        elif not arg.startswith("--") and arg.endswith(".xlsx"):
            excel_file = arg

    if not excel_file:
        print("Usage: python3 DigiM_SupportEval.py input.xlsx [--target intent|meta|both] [--agent agent_file.json]")
        print(f"\nInput Excel directory: {test_folder_path}")
        print("Input Excel format: the `question` column in the first column (header: question)")
        sys.exit(1)

    excel_path = excel_file if os.path.isabs(excel_file) or os.path.exists(excel_file) else str(Path(test_folder_path) / excel_file)

    questions = load_questions(excel_path)
    print(f"Question count: {len(questions)}")
    for i, q in enumerate(questions):
        print(f"  Q{i+1}: {q}")

    print(f"\nAgent: {agent_file}")
    agent = dma.DigiM_Agent(agent_file)
    support_agent = agent.agent["SUPPORT_AGENT"]

    print("\nVectorizing questions...")
    question_vecs = dmu.embed_texts_batch([q.replace("\n", "") for q in questions])
    print("Vectorization complete")

    all_results = []

    if target in ("both", "intent"):
        rag_agent_file = support_agent["RAG_QUERY_GENERATOR"]
        engines = get_engines(rag_agent_file)
        print(f"\n[RAG query generation] Agent: {rag_agent_file}")
        print(f"Engines: {engines}")
        intent_results = run_intent_eval(support_agent, engines, questions, question_vecs)
        all_results.extend(intent_results)
        print_summary(intent_results, "RAG query generation")

    if target in ("both", "meta"):
        meta_agent_file = support_agent["EXTRACT_DATE"]
        engines = get_engines(meta_agent_file)
        print(f"\n[Meta search] Agent: {meta_agent_file}")
        print(f"Engines: {engines}")
        meta_results = run_meta_eval(support_agent, engines, questions, question_vecs)
        all_results.extend(meta_results)
        print_summary(meta_results, "Meta search")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    input_name = Path(excel_path).stem
    output_path = str(Path(test_folder_path) / f"{input_name}_result_{timestamp}.xlsx")
    save_excel_file(all_results, output_path, questions)

if __name__ == "__main__":
    main()
