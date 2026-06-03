"""
Support-Agent benchmark
Run _build_intent_queries / _build_meta_searches against each engine and
compare speed and output.

Usage:
  python3 DigiM_Benchmark.py input.xlsx                                          # Both
  python3 DigiM_Benchmark.py input.xlsx --target intent                          # RAG query generation only
  python3 DigiM_Benchmark.py input.xlsx --target meta                            # Meta search only
  python3 DigiM_Benchmark.py input.xlsx --agent agent_01DigitalMATSUMOTO.json    # Specify an agent

Input Excel format (sheet name: questions):
  | no | question                          |
  |----|-----------------------------------|
  | 1  | What do you think about AI governance?  |
  | 2  | What was a recent book you enjoyed?     |

  * If there is no header, the first column is treated as `question`.
"""
import os
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

SERVICE_INFO = {"SERVICE_ID": "Benchmark", "SERVICE_DATA": {}}
USER_INFO = {"USER_ID": "BenchmarkUser", "USER_DATA": {}}
SESSION_ID = f"BENCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

def load_questions(excel_path):
    """Load the list of questions from the Excel file."""
    df = pd.read_excel(excel_path, sheet_name=0)
    if "question" in df.columns:
        return df["question"].dropna().tolist()
    else:
        return df.iloc[:, 0].dropna().tolist()

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

def run_intent_benchmark(support_agent, engines, questions, question_vecs):
    """Benchmark _build_intent_queries."""
    agent_file = support_agent["RAG_QUERY_GENERATOR"]
    results = []

    for engine_name in engines:
        print(f"\n--- [Intent] {engine_name} ---")
        for i, question in enumerate(questions):
            override_engine(support_agent, "RAG_QUERY_GENERATOR", engine_name)
            try:
                intent_queries, intent_vecs, log = dme._build_intent_queries(
                    SERVICE_INFO, USER_INFO, SESSION_ID, "benchmark",
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
                "response": response.replace("\n", " "),
                "elapsed_sec": duration,
                "prompt_tokens": prompt_tokens,
                "response_tokens": response_tokens,
                "status": status,
            })
            print(f"  Q{i+1}: {duration}s ({status}) - {response[:60]}...")

    return results

def run_meta_benchmark(support_agent, engines, questions, question_vecs):
    """Benchmark _build_meta_searches."""
    agent_file = support_agent["EXTRACT_DATE"]
    results = []

    for engine_name in engines:
        print(f"\n--- [Meta] {engine_name} ---")
        for i, question in enumerate(questions):
            override_engine(support_agent, "EXTRACT_DATE", engine_name)
            try:
                meta_searches, log = dme._build_meta_searches(
                    SERVICE_INFO, USER_INFO, SESSION_ID, "benchmark",
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
                "response": response.replace("\n", " "),
                "condition": condition,
                "elapsed_sec": duration,
                "prompt_tokens": prompt_tokens,
                "response_tokens": response_tokens,
                "status": status,
            })
            print(f"  Q{i+1}: {duration}s ({status}) [{condition}] - {response[:50]}...")

    return results

def print_summary(results, label):
    """Display the summary."""
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

def save_excel(results, output_path, questions):
    """Save the results to Excel (sheets: summary, intent, meta)."""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Per-type result sheets
        for result_type in ["intent", "meta"]:
            type_results = [r for r in results if r["type"] == result_type]
            if not type_results:
                continue
            df = pd.DataFrame(type_results)
            df.to_excel(writer, sheet_name=result_type, index=False)

            # Comparison pivot table (responses indexed by question x engine)
            if type_results:
                pivot_resp = df.pivot_table(index="question_no", columns="engine", values="response", aggfunc="first")
                pivot_time = df.pivot_table(index="question_no", columns="engine", values="elapsed_sec", aggfunc="first")
                # Add the question text
                q_map = {i+1: q for i, q in enumerate(questions)}
                pivot_resp.insert(0, "question", pivot_resp.index.map(q_map))
                pivot_time.insert(0, "question", pivot_time.index.map(q_map))
                pivot_resp.to_excel(writer, sheet_name=f"{result_type}_response", index=True)
                pivot_time.to_excel(writer, sheet_name=f"{result_type}_time", index=True)

        # Summary sheet
        summary_rows = []
        for result_type in ["intent", "meta"]:
            type_results = [r for r in results if r["type"] == result_type]
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
                        "min_sec": min(times), "max_sec": max(times),
                        "success": len(ok_rows), "error": err,
                    })
                else:
                    summary_rows.append({
                        "type": result_type, "engine": engine,
                        "avg_sec": None, "min_sec": None, "max_sec": None,
                        "success": 0, "error": err,
                    })
        if summary_rows:
            pd.DataFrame(summary_rows).to_excel(writer, sheet_name="summary", index=False)

    print(f"\nResults saved to {output_path}.")

def main():
    # Argument parsing
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
        print("Usage: python3 DigiM_Benchmark.py input.xlsx [--target intent|meta|both] [--agent agent_file.json]")
        print(f"\nInput Excel directory: {test_folder_path}")
        print("Input Excel format: the `question` column in the first column (header: question)")
        sys.exit(1)

    # Load from test_folder_path (also supports a full path)
    excel_path = excel_file if os.path.isabs(excel_file) or os.path.exists(excel_file) else str(Path(test_folder_path) / excel_file)

    # Load questions
    questions = load_questions(excel_path)
    print(f"Question count: {len(questions)}")
    for i, q in enumerate(questions):
        print(f"  Q{i+1}: {q}")

    # Read support-agent info from the main agent
    print(f"\nAgent: {agent_file}")
    main_agent = dma.DigiM_Agent(agent_file)
    support_agent = main_agent.agent["SUPPORT_AGENT"]

    # Pre-compute embeddings for each question
    print("\nVectorizing questions...")
    question_vecs = dmu.embed_texts_batch([q.replace("\n", "") for q in questions])
    print("Vectorization complete")

    all_results = []

    if target in ("both", "intent"):
        rag_agent_file = support_agent["RAG_QUERY_GENERATOR"]
        engines = get_engines(rag_agent_file)
        print(f"\n[RAG query generation] Agent: {rag_agent_file}")
        print(f"Engines: {engines}")
        intent_results = run_intent_benchmark(support_agent, engines, questions, question_vecs)
        all_results.extend(intent_results)
        print_summary(intent_results, "RAG query generation")

    if target in ("both", "meta"):
        meta_agent_file = support_agent["EXTRACT_DATE"]
        engines = get_engines(meta_agent_file)
        print(f"\n[Meta search] Agent: {meta_agent_file}")
        print(f"Engines: {engines}")
        meta_results = run_meta_benchmark(support_agent, engines, questions, question_vecs)
        all_results.extend(meta_results)
        print_summary(meta_results, "Meta search")

    # Save results to Excel (output to test_folder_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    input_name = Path(excel_path).stem
    output_path = str(Path(test_folder_path) / f"{input_name}_result_{timestamp}.xlsx")
    save_excel(all_results, output_path, questions)

if __name__ == "__main__":
    main()
