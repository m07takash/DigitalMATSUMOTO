"""Tool plugin: date / management analysis / text comparison.

Migrated from DigiM_Tool.py — see that file for the historical implementation.

`management_analysis` depends on `DigiM_Execute.DigiMatsuExecute_Practice`. At
plugin-load time DigiM_Execute is already fully imported by DigiM_Tool, so the
reference resolves correctly.
"""
import re as _re
import time
from pathlib import Path

import pandas as pd

import DigiM_Agent as dma
import DigiM_Execute as dme
import DigiM_Session as dms
import DigiM_Util as dmu
import DigiM_ToolRegistry as dmtr


_settings = dmu.read_yaml_file("setting.yaml")
practice_folder_path = _settings.get("PRACTICE_FOLDER", "user/common/practice/")
test_folder_path = "test/"  # historical hard-coded value, preserved verbatim

_INPUT_TEXT = {
    "type": "string",
    "description": "Free-form text — typically the user's query or relevant input for this tool.",
}


# Extract a date from text
def extract_date(service_info, user_info, session_id, session_name, agent_file,
                 input, import_contents=[], add_info={}):
    if not agent_file:
        agent_file = "agent_55ExtractDate.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    memories_selected = []
    if "Memories_Selected" in add_info:
        memories_selected = add_info["Memories_Selected"]
    if "Situation" in add_info:
        situation_prompt = add_info["Situation"]
    if "QueryVecs" in add_info:
        query_vecs = add_info["QueryVecs"]

    practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
    practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
    if practice["CHAINS"][0]["TYPE"] == "LLM":
        prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
    else:
        prompt_temp_cd = "Extract Date"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    user_query = input
    knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs)

    prompt = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'

    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, stream_mode=False):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# Business / management analysis
def management_analysis(service_info, user_info, session_id, session_name, agent_file,
                        input, import_contents=[], add_info={}):
    try:
        client_name = _re.search(r"Client:(.+)", input).group(1).strip()
        biz_name = _re.search(r"Biz:(.+)", input).group(1).strip()
        query = ""
        remaining_lines = []
        for line in input.splitlines():
            if not line.startswith("Client:") and not line.startswith("Biz:"):
                remaining_lines.append(line)
        if remaining_lines:
            query = "\n".join(remaining_lines).strip()
    except AttributeError:
        rule_text = "Include the following in your input.\nClient: <company name>\nBiz: <business name>"
        return service_info, user_info, rule_text, []

    test_file = "Tool_MgrAnalysis.xlsx"
    test_sheet_name = "Test"
    raw_name_Q = "Q"

    situation = {}
    overwrite_items = {}
    add_knowledges = []
    execution = {}
    execution["MEMORY_USE"] = True
    execution["MEMORY_SIMILARITY"] = False
    execution["MAGIC_WORD_USE"] = False
    execution["STREAM_MODE"] = False
    execution["SAVE_DIGEST"] = True
    execution["META_SEARCH"] = True
    execution["RAG_QUERY_GENE"] = True

    session = dms.DigiMSession(session_id, session_name)
    session.save_status("UNLOCKED")

    test_file_path = str(Path(test_folder_path) / test_file)
    test_sheet = pd.read_excel(test_file_path, sheet_name=test_sheet_name)
    Q_no = 0
    response_service_info = service_info
    response_user_info = user_info
    response = ""
    for index, row in test_sheet.iterrows():
        questionaire = str(row[raw_name_Q]).replace("{client}", client_name).replace("{biz}", biz_name)
        user_input = query + questionaire

        web_flg = str(row["WEB"])
        if web_flg == "Y":
            execution["WEB_SEARCH"] = True
        else:
            execution["WEB_SEARCH"] = False

        response = ""
        for response_service_info, response_user_info, response_chunk, output_reference in dme.DigiMatsuExecute_Practice(
                service_info, user_info, session_id, session_name, agent_file,
                user_input, import_contents, situation, overwrite_items, add_knowledges, execution):
            if response_chunk and not str(response_chunk).startswith("[STATUS]"):
                response += response_chunk

        Q_no += 1
        time.sleep(3)

    export_contents = []
    return response_service_info, response_user_info, response, export_contents


# Compare texts
# Non-uniform signature: (svc, usr, head1, text1, head2, text2, query_compare="")
def compare_texts(service_info, user_info, head1, text1, head2, text2, query_compare=""):
    agent_file = "agent_53CompareTexts.json"
    agent = dma.DigiM_Agent(agent_file)

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    if query_compare == "":
        prompt_temp_cd = "Compare Texts"
        prompt_template = agent.set_prompt_template(prompt_temp_cd)
    else:
        prompt_template = query_compare

    prompt = f'{prompt_template}\n\n[{head1}]\n{text1}\n\n[{head2}]\n{text2}'

    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return service_info, user_info, response, model_name, prompt_tokens, response_tokens


# ----- registrations ---------------------------------------------------------

dmtr.register_tool(
    "extract_date",
    description=(
        "Resolve relative date expressions (today / yesterday / next Monday / "
        "next month, etc.) in the user's text into absolute ISO dates. "
        "Use when the user's request depends on knowing the concrete calendar date."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=extract_date,
)

dmtr.register_tool(
    "management_analysis",
    description=(
        "Run a management / strategy analysis pass over the input text (e.g. "
        "SWOT-style framing, KPI breakdown). Input must include `Client:` and "
        "`Biz:` lines; an optional free-form question can follow."
    ),
    schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
    func=management_analysis,
    example="/management_analysis Client: ABC Inc.\nBiz: SaaS business\n成長戦略を教えて",
)

# Internal orchestration tool — non-uniform signature. Registered so
# legacy `dmt.compare_texts(...)` callers resolve via the shim.
# DO NOT include in Agent SKILL.TOOL_LIST — args do not fit the standard schema.
dmtr.register_tool(
    "compare_texts",
    description=(
        "Internal orchestration helper — compare two named texts via an LLM. "
        "Non-uniform signature: (svc, usr, head1, text1, head2, text2, query_compare). "
        "NOT safe for SKILL/Thinking dispatch."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    func=compare_texts,
)


# Answer vs Ground-Truth evaluation
# Used by BatchTest to score each row with a mix of deterministic metrics
# (exact-match / SequenceMatcher / token-F1) and an LLM-judged verdict.
# Non-uniform signature: (svc, usr, question, answer, ground_truth, agent_file="agent_53CompareTexts.json").
def eval_answer_vs_groundtruth(service_info, user_info, question, answer, ground_truth,
                                agent_file="agent_53CompareTexts.json"):
    import json as _json
    from collections import Counter as _Counter
    from difflib import SequenceMatcher as _SM

    ans = str(answer or "")
    gt = str(ground_truth or "")
    q = str(question or "")

    # ---- deterministic lexical metrics --------------------------------------
    def _norm(s):
        return _re.sub(r"\s+", "", s).lower()
    def _tokens(s):
        # word runs + single punctuation; CJK char split for languages w/o spaces
        out = []
        for chunk in _re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", s.lower()):
            if _re.fullmatch(r"[A-Za-z0-9_]+", chunk):
                out.append(chunk)
            else:
                # split per CJK char so 日本/日本人 share '日本' tokens
                out.extend(list(chunk))
        return [t for t in out if t.strip()]

    n_ans, n_gt = _norm(ans), _norm(gt)
    exact = bool(n_ans) and n_ans == n_gt
    seq_ratio = _SM(None, n_ans, n_gt).ratio() if (n_ans or n_gt) else 0.0

    a_tok, g_tok = _tokens(ans), _tokens(gt)
    common = _Counter(a_tok) & _Counter(g_tok)
    overlap = sum(common.values())
    prec = overlap / len(a_tok) if a_tok else 0.0
    rec = overlap / len(g_tok) if g_tok else 0.0
    f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) else 0.0

    # ---- LLM-judged verdict --------------------------------------------------
    agent = dma.DigiM_Agent(agent_file)
    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    judge_prompt = (
        "あなたは Q&A の評価AIです。Question に対する Answer が、Ground Truth と "
        "どれくらい一致しているかを評価してください。\n\n"
        f"[Question]\n{q}\n\n[Answer]\n{ans}\n\n[Ground Truth]\n{gt}\n\n"
        "次のJSONオブジェクト1つだけを、説明や前置きなしで出力してください。\n"
        "{\n"
        '  "verdict": "○" (一致) | "△" (部分一致) | "✕" (不一致),\n'
        '  "score": 0〜100の整数 (100=完全一致, 0=完全不一致),\n'
        '  "category": "完全一致" | "意味一致" | "部分一致" | "不一致",\n'
        '  "summary": "1行で日本語の評価コメント（どこが一致／不一致か）"\n'
        "}\n"
        "・Answer が Ground Truth と意味的に同じことを述べていれば ○ とする。\n"
        "・主旨は合うが細部が抜けている／追加されているなら △。\n"
        "・意味が異なる、または無回答／エラーなら ✕。"
    )

    response = ""
    try:
        for _p, chunk, _comp in agent.generate_response(model_type, judge_prompt):
            if chunk:
                response += chunk
    except Exception as e:
        response = f'{{"verdict":"","score":{int(round(seq_ratio*100))},"category":"","summary":"[Judge error] {type(e).__name__}: {e}"}}'

    # Parse defensively — strip ``` fences, grab the first {...} block.
    raw = response.strip()
    if raw.startswith("```"):
        raw = _re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = _re.sub(r"\s*```$", "", raw)
    m = _re.search(r"\{[\s\S]*\}", raw)
    data = {}
    if m:
        try:
            data = _json.loads(m.group(0))
        except Exception:
            data = {}

    verdict = str(data.get("verdict") or ("○" if exact else "")).strip()
    try:
        score = int(data.get("score"))
    except Exception:
        score = int(round(seq_ratio * 100))
    category = str(data.get("category") or "").strip()
    summary = str(data.get("summary") or "").strip()

    result = {
        "verdict": verdict,
        "score": max(0, min(100, score)),
        "category": category,
        "summary": summary,
        "exact_match": exact,
        "seq_ratio": round(seq_ratio, 3),
        "token_f1": round(f1, 3),
    }

    prompt_tokens = dmu.count_token(tokenizer, model_name, judge_prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    return service_info, user_info, result, model_name, prompt_tokens, response_tokens


dmtr.register_tool(
    "eval_answer_vs_groundtruth",
    description=(
        "Internal orchestration helper — evaluate how well an Answer matches a "
        "Ground Truth for a given Question. Returns dict with verdict (○/△/✕), "
        "score (0-100), category, summary, plus deterministic metrics "
        "(exact_match, seq_ratio, token_f1). Non-uniform signature; NOT safe "
        "for SKILL/Thinking dispatch."
    ),
    schema={"type": "object", "properties": {}, "required": []},
    func=eval_answer_vs_groundtruth,
)
