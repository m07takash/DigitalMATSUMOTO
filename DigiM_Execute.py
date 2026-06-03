import os
import time
import threading
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

import inspect
import pytz
import DigiM_Util as dmu
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Session as dms
import DigiM_Tool as dmt
import DigiM_JobRegistry as djr
import DigiM_UserMemoryBuilder as dmumb
import DigiM_UserMemorySetting as dmus

# Load folder paths and other settings from setting.yaml
system_setting_dict = dmu.read_yaml_file("setting.yaml")
user_folder_path = system_setting_dict["USER_FOLDER"]
session_folder_prefix = system_setting_dict["SESSION_FOLDER_PREFIX"]
temp_folder_path = system_setting_dict["TEMP_FOLDER"]
practice_folder_path = system_setting_dict["PRACTICE_FOLDER"]

# Load system.env and set environment variables
if os.path.exists("system.env"):
    load_dotenv("system.env")
timezone_setting = os.getenv("TIMEZONE")

# Session lock error
class SessionLockedError(RuntimeError):
    pass

# B-2: Common parser for execution settings
def _parse_execution_settings(execution):
    return {
        "contents_save":     execution.get("CONTENTS_SAVE", True),
        "memory_use":        execution.get("MEMORY_USE", True),
        "memory_save":       execution.get("MEMORY_SAVE", True),
        "memory_similarity": execution.get("MEMORY_SIMILARITY", False),
        "magic_word_use":    execution.get("MAGIC_WORD_USE", True),
        "stream_mode":       execution.get("STREAM_MODE", True),
        "save_digest":       execution.get("SAVE_DIGEST", True),
        "meta_search":       execution.get("META_SEARCH", True),
        "RAG_query_gene":    execution.get("RAG_QUERY_GENE", True),
        "web_search":        execution.get("WEB_SEARCH", False),
        "web_search_engine": execution.get("WEB_SEARCH_ENGINE", ""),
        "private_mode":      execution.get("PRIVATE_MODE", False),
        "thinking_mode":     execution.get("THINKING_MODE", False),
    }

# B-3: Common USER_INPUT resolution
def _resolve_user_input(user_input_setting, user_query, results):
    inputs = user_input_setting if isinstance(user_input_setting, list) else [user_input_setting]
    user_input = ""
    for item in inputs:
        if item == "USER":
            user_input += user_query
        elif item.startswith("INPUT"):
            ref_subseq = int(item.replace("INPUT_", "").strip())
            user_input += next((r["INPUT"] for r in results if r["SubSEQ"] == ref_subseq), "")
        elif item.startswith("OUTPUT"):
            ref_subseq = int(item.replace("OUTPUT_", "").strip())
            user_input += next((r["OUTPUT"] for r in results if r["SubSEQ"] == ref_subseq), "")
        else:
            user_input += item
    return user_input

# B-3: Common content resolution
def _resolve_contents(contents_setting, in_contents, results):
    if contents_setting == "USER":
        return in_contents
    if isinstance(contents_setting, str) and contents_setting.startswith("IMPORT_"):
        ref_subseq = int(contents_setting.replace("IMPORT_", "").strip())
        return next((r["IMPORT_CONTENTS"] for r in results if r["SubSEQ"] == ref_subseq), [])
    if isinstance(contents_setting, str) and contents_setting.startswith("EXPORT_"):
        ref_subseq = int(contents_setting.replace("EXPORT_", "").strip())
        return next((r["EXPORT_CONTENTS"] for r in results if r["SubSEQ"] == ref_subseq), [])
    return contents_setting

# B-4: RAG search-query generation phase (parallelization hook in C-1)
def _build_intent_queries(service_info, user_info, session_id, session_name, support_agent,
                          user_query, memories_selected, situation_prompt, query_vec, RAG_query_gene,
                          rag_query_hint="", user_memory_context=""):
    """Generate the RAG search query (intent) and return extra queries, vectors, and logs."""
    if not (RAG_query_gene and "RAG_QUERY_GENERATOR" in support_agent):
        return [], [], {}
    t_start = datetime.now()
    # Append the hint from Thinking to the query, if any
    _query = user_query
    if rag_query_hint:
        _query = _query + "\n\n【RAG検索のヒント】\n" + rag_query_hint
    # If user memory is enabled, also include the partner's profile in the query-generation context
    if user_memory_context:
        _query = _query + "\n\n" + user_memory_context.strip()
    add_info = {"Memories_Selected": memories_selected, "Situation": situation_prompt, "QueryVecs": [query_vec]}
    agent_file = support_agent["RAG_QUERY_GENERATOR"]
    _, _, response, model_name, prompt_tokens, response_tokens = dmt.RAG_query_generator(
        service_info, user_info, session_id, session_name, agent_file, _query, [], add_info)
    vec = dmu.embed_text(response.replace("\n", ""))
    duration = round((datetime.now() - t_start).total_seconds(), 2)
    log = {"agent_file": agent_file, "model": model_name, "llm_response": response,
           "rag_query_hint": rag_query_hint,
           "prompt_token": prompt_tokens, "response_token": response_tokens, "duration_sec": duration}
    return [response], [vec], log

# B-4: Metadata search phase (parallelization hook in C-1)
def _build_meta_searches(service_info, user_info, session_id, session_name, support_agent,
                         user_query, memories_selected, situation_prompt, query_vec, meta_search):
    """Retrieve metadata search info from the query."""
    if not (meta_search and "EXTRACT_DATE" in support_agent):
        return [], {}
    t_start = datetime.now()
    add_info = {"Memories_Selected": memories_selected, "Situation": situation_prompt, "QueryVecs": [query_vec]}
    agent_file = support_agent["EXTRACT_DATE"]
    _, _, response, model_name, prompt_tokens, response_tokens = dmt.extract_date(
        service_info, user_info, session_id, session_name, agent_file, user_query, [], add_info)
    date_list = dmu.merge_periods(dmu.extract_list_pattern(response))
    duration = round((datetime.now() - t_start).total_seconds(), 2)
    log = {"date": {"agent_file": agent_file, "model": model_name, "condition_list": date_list,
                    "llm_response": response, "prompt_token": prompt_tokens, "response_token": response_tokens,
                    "duration_sec": duration}}
    return [{"DATE": date_list}], log

# B-4: Run Thinking Agent (analyze the question and decide execution parameters)
def _run_thinking_agent(service_info, user_info, session_id, session_name,
                        support_agent, agent, user_query, digest_text, situation_prompt):
    """Run Thinking Agent and return the decision JSON and logs."""
    import json as _json
    if "THINKING" not in support_agent:
        return {}, {}
    t_start = datetime.now()

    # Format the habit list
    habit_info = ""
    for habit_key, habit_val in agent.habit.items():
        desc = ", ".join(habit_val.get("MAGIC_WORDS", []))
        habit_info += f"- {habit_key}: {desc}\n"

    # Format the book list
    book_info = ""
    for book in agent.agent.get("BOOK", []):
        book_info += f"- {book['RAG_NAME']}\n"

    add_info = {
        "Situation": situation_prompt,
        "DigestText": digest_text,
        "HabitInfo": habit_info,
        "BookInfo": book_info,
    }
    agent_file = support_agent["THINKING"]
    _, _, response, model_name, prompt_tokens, response_tokens = dmt.thinking_agent(
        service_info, user_info, session_id, session_name, agent_file, user_query, [], add_info)

    # Extract JSON from the response
    result = {}
    reasoning = response
    try:
        # If a ```json ... ``` block exists, extract its content
        import re
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        json_str = json_match.group(1) if json_match else response
        result = _json.loads(json_str)
        reasoning = result.get("reasoning", response)
    except (_json.JSONDecodeError, AttributeError):
        pass

    duration = round((datetime.now() - t_start).total_seconds(), 2)
    log = {
        "agent_file": agent_file, "model": model_name,
        "reasoning": reasoning, "result": result,
        "prompt_token": prompt_tokens, "response_token": response_tokens,
        "duration_sec": duration
    }
    return result, log

# Phase 6/7: Resolve chain.PERSONAS into a list of real persona dicts
# WEB_UI: use in_personas (currently selected in the UI) as-is
# THINKING: read pre-selected results from execution["_THINKING_RESULT"]["personas"] (chosen by PersonaSelector)
# list: resolve the persona_id list via DigiM_AgentPersona
def _resolve_step_personas(chain_personas, in_personas, in_agent_file, execution=None):
    if not chain_personas:
        return []
    if isinstance(chain_personas, str):
        upper = chain_personas.upper()
        if upper == "WEB_UI":
            return list(in_personas or [])
        if upper == "THINKING":
            # Reference the list finalized by the persona selection at the Practice head
            thinking = (execution or {}).get("_THINKING_RESULT", {}) or {}
            picked = thinking.get("personas") or []
            if picked:
                return list(picked)
            # Fallback: UI selection
            return list(in_personas or [])
        return []
    if isinstance(chain_personas, list):
        try:
            import DigiM_AgentPersona as dap
        except Exception:
            return []
        try:
            all_p = dap.load_personas(template_agent=in_agent_file)
        except Exception:
            return []
        by_id = {p.get("persona_id"): p for p in all_p}
        return [by_id[pid] for pid in chain_personas if pid in by_id]
    return []


# Phase 6: build user input in include_query form ([Each persona's previous responses] + [Current question])
def _format_persona_responses_as_query(persona_responses, user_query):
    blobs = []
    for r in persona_responses:
        name = r.get("persona_name") or "?"
        text = r.get("text") or ""
        if text:
            blobs.append(f"- {name}:\n{text}")
    if not blobs:
        return user_query
    return ("[前回の各ペルソナの回答]\n" + "\n\n".join(blobs)
            + "\n\n[今回の質問]\n" + (user_query or ""))


# Phase 6: Apply the PERSONA_MERGE strategy and return the merged text
# methods: "summary" / "concat" / "first" / "include_query" / "none"
def _apply_persona_merge(merge_method, persona_responses, user_query, merge_level,
                        service_info, user_info, session_id, session_name, support_agent):
    method = (merge_method or "summary").lower()
    if method == "first":
        return persona_responses[0].get("text", "") if persona_responses else ""
    if method in ("concat", "none"):
        return "\n\n".join(
            f"【{r.get('persona_name','?')}】\n{r.get('text','')}"
            for r in persona_responses if r.get("text")
        )
    if method == "include_query":
        return _format_persona_responses_as_query(persona_responses, user_query)
    if method == "summary":
        merge_agent = (support_agent or {}).get("PERSONA_MERGE", "agent_50PersonaMerge.json")
        try:
            _, _, merged, _, _, _ = dmt.dialog_persona_merge(
                service_info, user_info, session_id, session_name,
                merge_agent, user_query, persona_responses, summary_level=merge_level,
            )
            return merged
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).warning(f"persona_merge failed (falling back to concat): {e}")
            return "\n\n".join(
                f"【{r.get('persona_name','?')}】\n{r.get('text','')}"
                for r in persona_responses if r.get("text")
            )
    return ""


# Run digest generation / save / unlock in the background
def _run_digest_background(session, service_info, user_info, session_id, session_name,
                            support_agent, memories_selected,
                            seq, sub_seq, cfg, unlock_on_complete=True):
    try:
        dialog_digest_agent_file = support_agent.get("DIALOG_DIGEST", "")
        add_info = {}
        add_info["Memories_Selected"] = memories_selected
        timestamp_digest_start = str(datetime.now())
        _, _, digest_response, digest_model_name, _, digest_response_tokens = dmt.dialog_digest(
            service_info, user_info, session_id, session_name, dialog_digest_agent_file, "", [], add_info)
        timestamp_digest = str(datetime.now())
        digest_vec_file = ""
        if cfg["memory_similarity"]:
            digest_vec = dmu.embed_text(digest_response.replace("\n", ""))
            digest_vec_file = session.save_vec_file(str(seq), str(sub_seq), "digest", digest_vec)
        digest_chat_dict = {
            "agent_file": dialog_digest_agent_file, "model": digest_model_name,
            "role": "assistant",
            "timestamp_start": timestamp_digest_start, "timestamp": timestamp_digest,
            "token": digest_response_tokens, "text": digest_response,
            "vec_file": digest_vec_file
        }
        session.save_history_batch(str(seq), {str(sub_seq): {"digest": digest_chat_dict}})
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Background digest generation failed: {e}")
    finally:
        if unlock_on_complete:
            session.save_status("UNLOCKED")

# Function for one-shot execution
def DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type="LLM",
                     sub_seq=1, user_input="", contents=[], situation={}, overwrite_items={},
                     add_knowledge=[], prompt_temp_cd="", execution={}, seq_limit="", sub_seq_limit="",
                     persona=None, rag_query_text=""):
    export_files = []
    output_reference = {}
    timestamp_begin = str(datetime.now())
    timestamp_log = "[01.Execution start (session setup)]" + str(datetime.now()) + "<br>"

    # B-2: Load execution settings
    cfg = _parse_execution_settings(execution)

    # Declare the session
    _session_base_path = execution.get("_SESSION_BASE_PATH", "")
    session = dms.DigiMSession(session_id, session_name, base_path=_session_base_path)
    # seq prefers execution["_SEQ_OVERRIDE"] when set (avoids races during multi-persona parallel execution)
    _seq_override = execution.get("_SEQ_OVERRIDE")
    if _seq_override is not None:
        seq = _seq_override
    else:
        seq = session.get_seq_history() + 1 if sub_seq == 1 else session.get_seq_history()

    # Declare the agent (apply persona override if specified)
    timestamp_log += "[02.Agent setup start]" + str(datetime.now()) + "<br>"
    agent = dma.DigiM_Agent(agent_file, persona=persona)
    if overwrite_items:
        dmu.update_dict(agent.agent, overwrite_items)
        agent.set_property(agent.agent)

    # Build content context
    contents_context = ""
    contents_records = []
    image_files = {}
    if contents:
        timestamp_log += "[03.Content-context loading start]" + str(datetime.now()) + "<br>"
        contents_context, contents_records, image_files = agent.set_contents_context(seq, sub_seq, contents)

    user_query = user_input + contents_context
    digest_text = ""
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    query_tokens = dmu.count_token(tokenizer, model_name, user_query)
    system_tokens = dmu.count_token(tokenizer, model_name, agent.system_prompt)

    # Set up the situation
    timestamp_log += "[04.Situation setup]" + str(datetime.now()) + "<br>"
    situation_prompt = ""
    if situation:
        situation_setting = situation.get("SITUATION", "") + "\n" if "SITUATION" in situation else ""
        time_setting = situation.get("TIME", "")
        if time_setting:
            # Add a stronger directive when the datetime form is non-standard (fictional setting)
            is_standard = False
            try:
                datetime.strptime(time_setting, "%Y/%m/%d %H:%M:%S")
                is_standard = True
            except (ValueError, TypeError):
                pass
            if is_standard:
                situation_prompt = f"\n【状況】\n{situation_setting}現在は「{time_setting}」です。"
            else:
                situation_prompt = f"\n【重要な状況設定】\n{situation_setting}この会話では、現在の日時は「{time_setting}」として設定されています。会話履歴やシステム上の実際の日時に関わらず、必ずこの設定に従ってください。実際の日時には一切言及しないでください。"
        elif situation_setting.strip():
            situation_prompt = f"\n【状況】\n{situation_setting}"

    # Read the conversation digest
    if cfg["memory_use"]:
        timestamp_log += "[05.Conversation-digest loading start]" + str(datetime.now()) + "<br>"
        if session.chat_history_active_dict:
            if seq_limit or sub_seq_limit:
                _, _, chat_history_digest_dict = session.get_history_digest(seq_limit, sub_seq_limit)
            else:
                _, _, chat_history_digest_dict = session.get_history_max_digest()
            if chat_history_digest_dict:
                digest_text = "会話履歴のダイジェスト:\n" + chat_history_digest_dict["text"] + "\n---\n"

    # Read the Thinking log (when passed through via Practice)
    thinking_log = execution.get("_THINKING_LOG", {})

    # Run web search
    web_context = ""
    web_search_log = {}
    if cfg["web_search"]:
        session.save_status_message("Starting web search")
        yield service_info, user_info, "[STATUS]Starting web search", [], []
        timestamp_log += "[06.Web search start]" + str(datetime.now()) + "<br>"
        # Prefer the Thinking-generated web search query, if any
        _thinking_result = execution.get("_THINKING_RESULT", {})
        _web_search_query = _thinking_result.get("web_search_query", "")
        if _web_search_query:
            search_text = "検索して欲しい内容:\n" + _web_search_query + "\n\n[参考]元の質問:\n" + user_query
        elif digest_text or situation_prompt:
            search_text = "検索して欲しい内容:\n" + user_query + "\n\n[参考]これまでの会話:\n" + digest_text + "\n\n[参考]今の状況:\n" + situation_prompt
        else:
            search_text = user_query
        _setting = system_setting_dict
        web_engine = cfg["web_search_engine"] or _setting.get("WEB_SEARCH_DEFAULT", "Perplexity")
        _web_model_map = {
            "Perplexity": _setting.get("PERPLEXITY_MODEL", "sonar"),
            "OpenAI": _setting.get("OPENAI_SEARCH_MODEL", "gpt-4.1-mini"),
            "Google": _setting.get("GOOGLE_SEARCH_MODEL", "gemini-2.5-flash"),
        }
        web_model = _web_model_map.get(web_engine, "")
        t_web_start = datetime.now()
        _, _, web_result_text, export_urls = dmt.WebSearch(
            service_info, user_info, session_id, session_name, agent_file, search_text, [], {}, engine=web_engine)
        web_duration = round((datetime.now() - t_web_start).total_seconds(), 2)
        web_context = "[参考]関連するWEBの検索結果:\n" + web_result_text
        web_search_log = {"engine": web_engine, "model": web_model, "duration_sec": web_duration, "search_text": search_text, "urls": export_urls, "web_context": web_context}
        timestamp_log += f"[06.Web search done ({web_engine}/{web_model}, {web_duration}s)]" + str(datetime.now()) + "<br>"
    output_reference["Web_search"] = web_search_log
    user_query += f"\n{web_context}"

    # Vectorize the query (C-3: batch embedding)
    timestamp_log += "[07.Query vectorization start]" + str(datetime.now()) + "<br>"
    queries = [user_query]
    if digest_text or situation_prompt:
        user_query_ds = digest_text + user_query + situation_prompt
        queries.append(user_query_ds)
    query_vecs = dmu.embed_texts_batch([q.replace("\n", "") for q in queries])
    query_vec = query_vecs[0]

    # Run conversation memory / RAG query generation / meta search in parallel
    timestamp_log += "[08-10.Conversation memory / RAG search query / meta search (parallel)]" + str(datetime.now()) + "<br>"
    memory_limit_tokens = agent.agent["ENGINE"][model_type]["MEMORY"]["limit"]
    if model_type != "LLM":
        memory_limit_tokens -= (system_tokens + query_tokens)
    memory_role = agent.agent["ENGINE"][model_type]["MEMORY"]["role"]
    memory_priority = agent.agent["ENGINE"][model_type]["MEMORY"]["priority"]
    memory_similarity_logic = agent.agent["ENGINE"][model_type]["MEMORY"]["similarity_logic"]
    memory_digest = agent.agent["ENGINE"][model_type]["MEMORY"]["digest"]
    support_agent = agent.agent["SUPPORT_AGENT"]

    # Compose user-memory layers into the "About the dialogue partner" context.
    # Built before RAG query generation so that user memory is included in the generator's input text.
    # Skipped for IMAGEGEN because the 3000-char image prompt limit otherwise saturates.
    # Priority: execution["USER_MEMORY_LAYERS"] (immediate UI override) > user master > system default
    user_memory_context = ""
    user_memory_used = []
    user_memory_meta = {"history_keywords": []}
    if cfg["memory_use"] and model_type == "LLM":
        try:
            _svc_id = (service_info or {}).get("SERVICE_ID", "")
            _usr_id = (user_info or {}).get("USER_ID", "")
            _override_layers = execution.get("USER_MEMORY_LAYERS")
            if _override_layers is not None:
                # Immediate UI override (empty list is also respected = all off)
                import DigiM_UserMemory as _dmum_local
                _active_layers = [l for l in _override_layers if l in _dmum_local.LAYERS]
            else:
                _active_layers = dmus.resolve_active_layers(_usr_id)
            if _active_layers:
                user_memory_context, user_memory_used, user_memory_meta = dmumb.build_context_text(
                    _svc_id, _usr_id, _active_layers, query_text=user_query,
                )
        except Exception as _um_err:
            timestamp_log += f"[user_memory composition failed: {_um_err}]" + str(datetime.now()) + "<br>"

    need_intent = cfg["RAG_query_gene"] and "RAG_QUERY_GENERATOR" in support_agent
    need_meta = cfg["meta_search"] and "EXTRACT_DATE" in support_agent
    if need_intent or need_meta:
        session.save_status_message("Starting RAG search-query generation")
        yield service_info, user_info, "[STATUS]Starting RAG search-query generation", [], []

    with ThreadPoolExecutor(max_workers=3) as executor:
        # Kick off memory retrieval in parallel
        future_memory = None
        if cfg["memory_use"]:
            future_memory = executor.submit(
                session.get_memory, query_vec, model_name, tokenizer, memory_limit_tokens,
                memory_role, memory_priority, cfg["memory_similarity"],
                memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
        # Kick off RAG query generation in parallel (pass the Thinking hint if any)
        # When include_query etc. has prefixed user_input with prior persona responses,
        # use rag_query_text (= original user input) for RAG / meta search when provided.
        _rag_input_text = rag_query_text if rag_query_text else user_query
        _thinking_result = execution.get("_THINKING_RESULT", {})
        _rag_query_hint = _thinking_result.get("rag_query_hint", "")
        future_intent = executor.submit(
            _build_intent_queries, service_info, user_info, session_id, session_name,
            support_agent, _rag_input_text, [], situation_prompt, query_vec, cfg["RAG_query_gene"],
            _rag_query_hint, user_memory_context)
        # Kick off meta search in parallel
        future_meta = executor.submit(
            _build_meta_searches, service_info, user_info, session_id, session_name,
            support_agent, _rag_input_text, [], situation_prompt, query_vec, cfg["meta_search"])

        memories_selected = future_memory.result() if future_memory else []
        intent_queries, intent_vecs, RAG_query_gene_log = future_intent.result()
        meta_searches, meta_search_log = future_meta.result()

    intent_dur = RAG_query_gene_log.get("duration_sec", "-") if RAG_query_gene_log else "-"
    meta_dur = meta_search_log.get("date", {}).get("duration_sec", "-") if meta_search_log else "-"
    timestamp_log += f"[08-10 done: memory / RAG query ({intent_dur}s) / meta search ({meta_dur}s)]" + str(datetime.now()) + "<br>"
    queries += intent_queries
    query_vecs += intent_vecs
    output_reference["RAG_query_gene_log"] = RAG_query_gene_log
    output_reference["meta_search"] = meta_search_log

    # Build the RAG context
    timestamp_log += "[11.RAG start]" + str(datetime.now()) + "<br>"
    session.save_status_message("Starting RAG")
    yield service_info, user_info, "[STATUS]Starting RAG", [], []
    if add_knowledge:
        agent.knowledge += add_knowledge
    exec_info = {"SERVICE_INFO": service_info, "USER_INFO": user_info}
    knowledge_context, knowledge_selected = agent.set_knowledge_context(
        user_query, query_vecs, exec_info, meta_searches, private_mode=cfg["private_mode"])

    # Set up the prompt template and query
    timestamp_log += "[12.Prompt template setup]" + str(datetime.now()) + "<br>"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)
    if model_type == "LLM":
        # Order: Dialogue partner info -> Knowledge -> Template -> User query -> Situation
        query = f'{user_memory_context}{knowledge_context}{prompt_template}{user_query}{situation_prompt}'
    else:
        query = f'{prompt_template}{user_query}{situation_prompt}'
    output_reference["prompt"] = {
        "query": query, "user_query": user_query, "contents_context": contents_context,
        "web_context": web_context, "knowledge_context": knowledge_context,
        "prompt_template": prompt_template, "situation_prompt": situation_prompt,
        "memories_selected": memories_selected,
        "user_memory_context": user_memory_context,
        "user_memory_used": user_memory_used,
        "user_memory_meta": user_memory_meta,
    }

    # Execute the LLM
    prompt = ""
    response = ""
    completion = []
    session.save_status_message("Running LLM")
    timestamp_log += "[13.LLM execution start]" + str(datetime.now()) + "<br>"
    response_service_info = {}
    response_user_info = {}
    _last_stream_flush = time.time()
    _STREAM_FLUSH_INTERVAL = 2  # Pseudo-streaming flush interval (seconds)
    for prompt, response_chunk, completion in agent.generate_response(
            model_type, query, memories_selected, image_files, cfg["stream_mode"]):
        if response_chunk:
            response += response_chunk
            response_service_info = service_info
            response_user_info = user_info
            yield response_service_info, response_user_info, response_chunk, export_files, knowledge_selected
            # Pseudo-streaming: periodically write the response into the status
            if cfg["stream_mode"] and time.time() - _last_stream_flush >= _STREAM_FLUSH_INTERVAL:
                session.save_status_message("Running LLM", response=response)
                _last_stream_flush = time.time()
    timestamp_end = str(datetime.now())
    timestamp_log += "[14.LLM execution done]" + str(datetime.now()) + "<br>"

    # Sanitize response text (strip control characters)
    response = dmu.sanitize_text(response)

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) if prompt else 0
    response_tokens = dmu.count_token(tokenizer, model_name, response) if response else 0

    # Similarity evaluation
    timestamp_log += "[15.Result similarity calculation start]" + str(datetime.now()) + "<br>"
    response_vec = dmu.embed_text(response.replace("\n", "")[:8000])
    memory_ref = dmc.get_memory_reference(memories_selected, cfg["memory_similarity"], response_vec, memory_similarity_logic)
    knowledge_ref = dmc.get_knowledge_reference(response_vec, knowledge_selected)
    output_reference["memory_ref"] = memory_ref
    output_reference["knowledge_ref"] = knowledge_ref

    # Save content
    contents_record_to = []
    if cfg["contents_save"]:
        timestamp_log += "[16.Content save start]" + str(datetime.now()) + "<br>"
        for rec in contents_records:
            session.save_contents_file(rec["from"], rec["to"]["file_name"])
            contents_record_to.append(rec["to"])

    # B-5: Bulk-save logs
    if cfg["memory_save"]:
        timestamp_log += "[17.Log save start]" + str(datetime.now()) + "<br>"

        # Save vector files (for similarity evaluation)
        query_vec_file = ""
        response_vec_file = ""
        if cfg["memory_similarity"]:
            query_vec_file = session.save_vec_file(str(seq), str(sub_seq), "query", query_vec)
            response_vec_file = session.save_vec_file(str(seq), str(sub_seq), "response", response_vec)

        setting_chat_dict = {
            "session_id": session.session_id,
            "session_name": session.session_name,
            "type": model_type,
            "agent_file": agent_file,
            "name": agent.name,
            "engine": agent.agent["ENGINE"][model_type],
            "feedback": agent.agent["FEEDBACK"],
            "persona_id": getattr(agent, "persona_id", "") or "",
            "persona_name": getattr(agent, "persona_name", "") or "",
        }
        prompt_chat_dict = {
            "role": "user",
            "timestamp": timestamp_begin,
            "token": prompt_tokens,
            "query": {
                "input": user_input, "token": query_tokens, "text": user_query,
                "contents": contents_record_to, "situation": situation,
                "tools": [], "vec_file": query_vec_file
            },
            "thinking": thinking_log,
            "web_search": web_search_log,
            "RAG_query_genetor": RAG_query_gene_log,
            "meta_search": meta_search_log,
            "knowledge_rag": {"setting": agent.agent["KNOWLEDGE"]},
            "prompt_template": {"setting": prompt_temp_cd},
            "user_memory_context": user_memory_context,
            "user_memory_meta": user_memory_meta,
            "text": prompt
        }
        response_chat_dict = {
            "role": "assistant",
            "timestamp": timestamp_end,
            "token": response_tokens,
            "text": response,
            "vec_file": response_vec_file,
            "reference": {"memory": memory_ref, "knowledge_rag": knowledge_ref,
                          "user_memory": user_memory_used}
        }

        # Image log (IMAGEGEN)
        img_dict = {}
        if model_type == "IMAGEGEN":
            for i, img_path in enumerate(completion):
                img_file_name = "[OUT]seq" + str(seq) + "-" + str(sub_seq) + "_" + os.path.basename(img_path)
                session.save_contents_file(img_path, img_file_name)
                _img_ext = os.path.splitext(img_file_name)[1].lstrip(".").lower()
                _img_mime = f"image/{_img_ext}" if _img_ext else "image/png"
                img_dict[i] = {"role": "image", "timestamp": timestamp_end,
                               "file_name": img_file_name, "file_type": _img_mime}
                export_files.append(str(Path(session.session_folder_path) / "contents" / img_file_name))

        timestamp_log += "[Done]" + str(datetime.now()) + "<br>"

        # B-5: Bulk write (digest is appended separately in the background)
        sub_seq_data = {
            str(sub_seq): {
                "setting": setting_chat_dict,
                "prompt": prompt_chat_dict,
                "response": response_chat_dict,
                "log": {"timestamp_log": timestamp_log}
            }
        }
        if model_type == "IMAGEGEN" and img_dict:
            sub_seq_data[str(sub_seq)]["image"] = img_dict
        session.save_history_batch(str(seq), sub_seq_data)
        session.save_user_dialog_session("UNSAVED")

        # Reflect the finalized response into the status (for pseudo-streaming)
        session.save_status_message("Generating digest", response=response)

        # Kick off digest generation in the background (UNLOCK the session after completion)
        if cfg["save_digest"]:
            _unlock_on_complete = execution.get("_UNLOCK_ON_DIGEST", True)
            timestamp_log += "[18.Memory digest generation started in background]" + str(datetime.now()) + "<br>"

            # Incremental form: feed only the previous digest + the current single turn for speed
            # Feed in with speaker names so the digest side can keep track of who said what
            _slim_memories = []
            try:
                _, _, _prev_digest = session.get_history_digest(str(seq), str(sub_seq))
                if _prev_digest and _prev_digest.get("text"):
                    _slim_memories.append({"role": "assistant", "text": _prev_digest["text"]})
            except Exception:
                pass
            # Use user_info.NAME for the speaker; fall back to USER_ID when absent (no master lookup)
            _udisp = (user_info or {}).get("NAME") or (user_info or {}).get("USER_ID") or "(unknown)"
            _aname = getattr(agent, "name", "") or "AI"
            _slim_memories.append({"role": "user", "text": f"[User: {_udisp}] {user_query}"})
            _slim_memories.append({"role": "assistant", "text": f"[Agent: {_aname}] {response}"})

            _digest_job_id = djr.new_job_id()
            _digest_args = (session, service_info, user_info, session_id, session_name,
                            support_agent, _slim_memories,
                            seq, sub_seq, cfg, _unlock_on_complete)

            def _digest_wrapper():
                try:
                    _run_digest_background(*_digest_args)
                except (SystemExit, KeyboardInterrupt):
                    try:
                        session.save_status("UNLOCKED", error="Cancelled by user")
                    except Exception:
                        pass
                finally:
                    djr.unregister_job(_digest_job_id)

            _digest_thread = threading.Thread(target=_digest_wrapper, daemon=True)
            djr.register_job(_digest_job_id, _digest_thread, "digest",
                             f"Digest generation: {session_name}", session_id=session_id,
                             user_id=user_info.get("USER_ID") if isinstance(user_info, dict) else None)
            _digest_thread.start()
            output_reference["_digest_bg_started"] = True

    yield response_service_info, user_info, "", export_files, output_reference

# Run via a practice
def DigiMatsuExecute_Practice(service_info, user_info, session_id, session_name, in_agent_file, user_query, in_contents=[], in_situation={}, in_overwrite_items={}, in_add_knowledge=[], in_execution={}, in_persona=None, in_rag_query_text="", in_personas=None, in_org=None):

    # Fill user_info.NAME once so the speaker name persists in SETTING (reflected in subsequent history).
    # Look up the master only once per request. Keep a copy so we don't mutate the caller's dict.
    user_info = dict(user_info or {})
    if user_info.get("USER_ID") and not user_info.get("NAME"):
        try:
            import DigiM_Auth as _dma_um
            _um = _dma_um.load_user_master() or {}
            _nm = (_um.get(user_info["USER_ID"]) or {}).get("Name")
            if _nm:
                user_info["NAME"] = _nm
        except Exception:
            pass

    # B-2: Load execution settings
    last_only = in_execution.get("LAST_ONLY", False)
    cfg = _parse_execution_settings(in_execution)

    session = dms.DigiMSession(session_id, session_name)
    # For multi-persona parallel execution, set the starting position via sub_seq_start (default 1)
    sub_seq = in_execution.get("_SUB_SEQ_START", 1)
    results = []
    response_service_info = service_info
    response_user_info = user_info
    _digest_bg_started = False  # If the background digest is launched, we do not UNLOCK here

    # Lock the session (pre_locked=True means the caller has already locked it)
    _pre_locked = in_execution.get("_PRE_LOCKED", False)
    if session.get_status() == "LOCKED" and not _pre_locked:
        raise Exception("Session is locked. Please unlock the session before executing the practice.")
    session.save_status("LOCKED")

    try:
        agent = dma.DigiM_Agent(in_agent_file)
        thinking_result = {}

        # Thinking Mode: AI analyzes the question and decides execution parameters
        if cfg["thinking_mode"] and "SUPPORT_AGENT" in agent.agent and "THINKING" in agent.agent["SUPPORT_AGENT"]:
            session.save_status_message("Thinking...")
            yield service_info, user_info, "[STATUS]Thinking...", {}

            # Read the digest (for context-understanding by Thinking)
            _thinking_digest = ""
            if session.chat_history_active_dict:
                _, _, _digest_dict = session.get_history_max_digest()
                if _digest_dict:
                    _thinking_digest = _digest_dict["text"]

            # Read the situation
            _thinking_situation = ""
            if in_situation:
                _thinking_situation = in_situation.get("SITUATION", "") + " " + in_situation.get("TIME", "")

            thinking_result, thinking_log = _run_thinking_agent(
                service_info, user_info, session_id, session_name,
                agent.agent["SUPPORT_AGENT"], agent, user_query,
                _thinking_digest, _thinking_situation)

            # Apply Thinking output to execution settings (only items enabled by THINKING_TARGETS)
            _targets = in_execution.get("THINKING_TARGETS", {})
            if thinking_result:
                if _targets.get("web_search", True) and "web_search" in thinking_result:
                    cfg["web_search"] = thinking_result["web_search"]
                    if "web_search_engine" in thinking_result:
                        cfg["web_search_engine"] = thinking_result["web_search_engine"]
                if _targets.get("rag_query_gene", True) and "rag_query_gene" in thinking_result:
                    cfg["RAG_query_gene"] = thinking_result["rag_query_gene"]

            # Pass the Thinking log/result to the chain-run execution
            in_execution["_THINKING_LOG"] = thinking_log
            in_execution["_THINKING_RESULT"] = thinking_result
        else:
            in_execution["_THINKING_LOG"] = {}
            in_execution["_THINKING_RESULT"] = {}

        # Habit selection: prefer the Thinking output if available; otherwise judge by Magic Word
        _targets = in_execution.get("THINKING_TARGETS", {})
        habit = "DEFAULT"
        if thinking_result and _targets.get("habit", True) and "habit" in thinking_result and thinking_result["habit"] in agent.habit:
            habit = thinking_result["habit"]
        elif cfg["magic_word_use"]:
            habit = agent.set_practice_by_command(user_query)

        # Book selection: auto-add based on Thinking output
        if thinking_result and _targets.get("books", True) and "books" in thinking_result:
            for book_data in agent.agent.get("BOOK", []):
                if book_data["RAG_NAME"] in thinking_result["books"]:
                    if book_data not in in_add_knowledge:
                        in_add_knowledge.append(book_data)

        practice_file = agent.habit[habit]["PRACTICE"]
        habit_add_knowledge = agent.habit[habit].get("ADD_KNOWLEDGE", [])
        practice = dmu.read_json_file(practice_folder_path + practice_file)

        chains = practice["CHAINS"]
        last_idx = len(chains) - 1

        # Phase 7: if chain.PERSONAS="THINKING" appears in the practice, auto-select via PersonaSelector
        # Candidate pool is under the selected ORG (in_org); max count is execution["MAX_PERSONAS"] / setting.yaml
        # When THINKING_TARGETS.personas is False, skip selection (_resolve_step_personas falls back to UI selection)
        _personas_target_on = _targets.get("personas", True) if isinstance(_targets, dict) else True
        if _personas_target_on and any(c.get("PERSONAS") == "THINKING" for c in chains):
            _max_p = int(in_execution.get("MAX_PERSONAS",
                                           system_setting_dict.get("MAX_PERSONAS", 3)))
            _candidates = []
            try:
                import DigiM_AgentPersona as dap
                if isinstance(in_org, dict) and in_org:
                    _persona_files = agent.agent.get("PERSONA_FILES") or None
                    _persona_source = agent.agent.get("PERSONA_SOURCE")
                    _candidates = dap.find_personas_by_org(in_org, template_agent=in_agent_file,
                                                           persona_files=_persona_files,
                                                           source=_persona_source)
                else:
                    _candidates = list(in_personas or [])
            except Exception as _e:
                _candidates = list(in_personas or [])
            # Select via PersonaSelector
            session.save_status_message(f"Selecting personas (up to {_max_p})")
            yield service_info, user_info, f"[STATUS]Selecting personas (up to {_max_p}, candidates: {len(_candidates)})", {}
            try:
                _selected_ids, _select_reason, _, _, _ = dmt.select_personas(
                    service_info, user_info, session_id, session_name,
                    agent.agent.get("SUPPORT_AGENT", {}).get("PERSONA_SELECTOR", "agent_54PersonaSelector.json"),
                    user_query, _candidates, max_personas=_max_p,
                )
            except Exception as _e:
                _selected_ids, _select_reason = [], f"selector error: {_e}"
            _by_id = {p.get("persona_id"): p for p in _candidates}
            _thinking_personas = [_by_id[pid] for pid in _selected_ids if pid in _by_id]
            # Save into the Thinking result (consumed by _resolve_step_personas in the chain loop)
            in_execution.setdefault("_THINKING_RESULT", {})
            in_execution["_THINKING_RESULT"]["personas"] = _thinking_personas
            in_execution["_THINKING_RESULT"]["personas_reason"] = _select_reason
            in_execution["_THINKING_RESULT"]["personas_selected_ids"] = _selected_ids
            yield service_info, user_info, f"[STATUS]Personas selected: {len(_thinking_personas)} ({', '.join(p.get('name','?') for p in _thinking_personas)})", {}
        for i, chain in enumerate(chains):
            # Reflect chain progress in the status
            if len(chains) > 1:
                session.save_status_message(f"Chain {i+1}/{len(chains)} ({chain['TYPE']}) running")
                yield service_info, user_info, f"[STATUS]Chain {i+1}/{len(chains)} ({chain['TYPE']}) running", {}
            result = {}
            model_type = chain["TYPE"]
            input = ""
            output = ""
            import_contents = []
            export_contents = []
            # Record the step's starting sub_seq so that even multi-persona runs can be referenced from the next step as OUTPUT_<starting sub_seq>
            _step_start_sub_seq = sub_seq

            # When TYPE is "LLM"
            if model_type in ["LLM", "IMAGEGEN"]:
                setting = chain["SETTING"]
                agent_file = setting["AGENT_FILE"] if setting["AGENT_FILE"] != "USER" else in_agent_file
                if setting["OVERWRITE_ITEMS"] == "USER":
                    overwrite_items = in_overwrite_items
                else:
                    # Merge practice settings on top of in_overwrite_items (engine selection etc.); practice wins
                    overwrite_items = dict(in_overwrite_items)
                    if setting["OVERWRITE_ITEMS"]:
                        dmu.update_dict(overwrite_items, setting["OVERWRITE_ITEMS"])
                add_knowledge = []
                for ak in setting["ADD_KNOWLEDGE"]:
                    if "USER" in setting["ADD_KNOWLEDGE"]:
                        add_knowledge.extend(habit_add_knowledge)
                    else:
                        add_knowledge.append(ak)
                for ak in in_add_knowledge:
                    add_knowledge.append(ak)

                prompt_temp_cd = setting["PROMPT_TEMPLATE"]

                # B-3: USER_INPUT resolution
                user_input = _resolve_user_input(setting["USER_INPUT"], user_query, results)

                # B-3: Content resolution
                import_contents = _resolve_contents(setting["CONTENTS"], in_contents, results)

                # Set up the situation
                situation = {}
                if setting["SITUATION"] == "USER":
                    situation = in_situation
                else:
                    situation["TIME"] = in_situation["TIME"] if setting["SITUATION"]["TIME"] == "USER" else setting["SITUATION"]["TIME"]
                    situation["SITUATION"] = in_situation["SITUATION"] if setting["SITUATION"]["SITUATION"] == "USER" else setting["SITUATION"]["SITUATION"]

                seq_limit = chain.get("PreSEQ", "")
                sub_seq_limit = chain.get("PreSubSEQ", "")

                # Mid-chain digest background threads do not UNLOCK (only the last chain UNLOCKs)
                _is_last_chain = (i == last_idx)
                execution = {
                    "CONTENTS_SAVE":     cfg["contents_save"],
                    "MEMORY_USE":        cfg["memory_use"] and setting.get("MEMORY_USE", True),
                    "MEMORY_SAVE":       cfg["memory_save"],
                    "MEMORY_SIMILARITY": cfg["memory_similarity"],
                    "MAGIC_WORD_USE":    cfg["magic_word_use"],
                    "STREAM_MODE":       cfg["stream_mode"],
                    "SAVE_DIGEST":       cfg["save_digest"],
                    "META_SEARCH":       cfg["meta_search"] and setting.get("META_SEARCH", True),
                    "RAG_QUERY_GENE":    cfg["RAG_query_gene"] and setting.get("RAG_QUERY_GENE", True),
                    "WEB_SEARCH":        setting.get("WEB_SEARCH", cfg["web_search"]),
                    "PRIVATE_MODE":      cfg["private_mode"],
                    "THINKING_MODE":     cfg["thinking_mode"],
                    "_THINKING_LOG":     in_execution.get("_THINKING_LOG", {}),
                    "_THINKING_RESULT":  in_execution.get("_THINKING_RESULT", {}),
                    "_UNLOCK_ON_DIGEST": _is_last_chain,
                    # User Memory: propagate the immediate UI override downstream (None=unspecified -> downstream falls back to user master / system default)
                    "USER_MEMORY_LAYERS": in_execution.get("USER_MEMORY_LAYERS"),
                    # Propagate the multi-persona parallel-execution flags to the downstream DigiMatsuExecute
                    "_SEQ_OVERRIDE":     in_execution.get("_SEQ_OVERRIDE"),
                    "_SUB_SEQ_START":    in_execution.get("_SUB_SEQ_START"),
                    "_SESSION_BASE_PATH": in_execution.get("_SESSION_BASE_PATH", ""),
                }

                # Phase 6/7: Decide multi-persona parallel execution within a step based on chain.PERSONAS
                step_personas = _resolve_step_personas(chain.get("PERSONAS"), in_personas, in_agent_file, in_execution)

                response = ""
                # Use rag_query_text only for the first chain step
                _rag_query_text_for_step = in_rag_query_text if i == 0 else ""

                if len(step_personas) >= 2:
                    # ---- Multi-persona parallel execution ----
                    yield service_info, user_info, f"[STATUS]chain[{i}] running {len(step_personas)} personas in parallel...", {}
                    # Lock in the seq up-front (when _SEQ_OVERRIDE is unset)
                    if execution.get("_SEQ_OVERRIDE") is None:
                        _step_seq = session.get_seq_history() + 1 if sub_seq == 1 else session.get_seq_history()
                        execution["_SEQ_OVERRIDE"] = _step_seq
                    _persona_responses = []
                    _max_workers = min(len(step_personas),
                                       max(1, int(system_setting_dict.get("MAX_PARALLEL_PERSONAS", 4))))

                    def _run_step_persona(p_idx, persona):
                        local_sub_seq = sub_seq + p_idx
                        local_resp = ""
                        try:
                            for _r_svc, _r_usr, _chunk, _exp, _oref in DigiMatsuExecute(
                                    service_info, user_info, session_id, session_name, agent_file, model_type,
                                    local_sub_seq, user_input, import_contents, situation, overwrite_items,
                                    add_knowledge, prompt_temp_cd, execution, seq_limit, sub_seq_limit,
                                    persona=persona, rag_query_text=_rag_query_text_for_step):
                                if _chunk and not _chunk.startswith("[STATUS]"):
                                    local_resp += _chunk
                        except Exception as _e:
                            local_resp = f"[ERROR] {_e}"
                        return persona, local_sub_seq, local_resp

                    with ThreadPoolExecutor(max_workers=_max_workers) as _ex:
                        _futures = [_ex.submit(_run_step_persona, _i, _p) for _i, _p in enumerate(step_personas)]
                        for _fut in as_completed(_futures):
                            _p, _ss, _resp = _fut.result()
                            _persona_responses.append({
                                "persona_id": _p.get("persona_id", ""),
                                "persona_name": _p.get("name", ""),
                                "sub_seq": _ss,
                                "text": _resp,
                            })
                            yield service_info, user_info, f"[STATUS]chain[{i}] {_p.get('name','?')} done", {}

                    # Sort by sub_seq (stabilize save order)
                    _persona_responses.sort(key=lambda r: r["sub_seq"])

                    # Attach setting.memory_flg="N" / chain_index / chain_role to each persona sub_seq
                    _seq_str = str(execution["_SEQ_OVERRIDE"])
                    for _r in _persona_responses:
                        try:
                            session.update_subseq_setting(_seq_str, str(_r["sub_seq"]), {
                                "memory_flg": "N",
                                "chain_index": i,
                                "chain_role": "persona",
                            })
                        except Exception:
                            pass

                    # Apply PERSONA_MERGE (output text = the output passed to the next step)
                    _merge_method = chain.get("PERSONA_MERGE", "summary")
                    _merge_level = chain.get("PERSONA_MERGE_LEVEL", "medium")
                    response = _apply_persona_merge(
                        _merge_method, _persona_responses, user_input, _merge_level,
                        service_info, user_info, session_id, session_name, agent.support_agent
                    )

                    # Advance sub_seq by N
                    sub_seq += len(step_personas) - 1   # The loop tail adds +1, so the total is N

                else:
                    # ---- Existing path: single-persona execution (or in_persona) ----
                    for response_service_info, response_user_info, response_chunk, export_contents, output_reference in DigiMatsuExecute(
                            service_info, user_info, session_id, session_name, agent_file, model_type,
                            sub_seq, user_input, import_contents, situation, overwrite_items,
                            add_knowledge, prompt_temp_cd, execution, seq_limit, sub_seq_limit,
                            persona=in_persona, rag_query_text=_rag_query_text_for_step):
                        if not last_only or i == last_idx:
                            yield response_service_info, response_user_info, response_chunk, output_reference
                        if response_chunk and not response_chunk.startswith("[STATUS]"):
                            response += response_chunk
                    if _is_last_chain and output_reference.get("_digest_bg_started", False):
                        _digest_bg_started = True

                input = user_input
                output = response

            elif model_type == "TOOL":
                seq = session.get_seq_history() + 1 if sub_seq == 1 else session.get_seq_history()
                setting = chain["SETTING"]

                # B-3: USER_INPUT resolution
                user_input = _resolve_user_input(
                    setting["USER_INPUT"], user_query, results) if "USER_INPUT" in setting else ""
                input = user_input

                # B-3: Content resolution
                import_contents = _resolve_contents(
                    setting["CONTENTS"], in_contents, results) if "CONTENTS" in setting else []

                agent_file = setting["AGENT_FILE"] if "AGENT_FILE" in setting and setting["AGENT_FILE"] != "USER" else in_agent_file
                add_info = setting.get("ADD_INFO", {})

                timestamp_begin = str(datetime.now())
                tool_result = dmt.call_function_by_name(
                    service_info, user_info, setting["FUNC_NAME"],
                    session_id, session_name, agent_file, input, import_contents, add_info)
                output = ""
                export_contents = []
                if inspect.isgenerator(tool_result):
                    for resp_svc, resp_usr, chunk, exp in tool_result:
                        output += dmu.sanitize_text(str(chunk)) if chunk else ""
                        if exp is not None:
                            export_contents = exp
                        if not last_only or i == last_idx:
                            yield resp_svc, resp_usr, chunk, {}
                    response_service_info = resp_svc
                    response_user_info = resp_usr
                else:
                    response_service_info, response_user_info, output, export_contents = tool_result
                    if not last_only or i == last_idx:
                        yield response_service_info, response_user_info, output, {}
                timestamp_end = str(datetime.now())

                # B-5: Bulk-save TOOL execution logs
                session.save_history_batch(str(seq), {
                    str(sub_seq): {
                        "setting": {
                            "response_service_info": response_service_info,
                            "response_user_info": response_user_info,
                            "session_name": session.session_name,
                            "situation": in_situation,
                            "type": model_type,
                            "agent_file": in_agent_file,
                            "name": practice["NAME"],
                            "tool": setting["FUNC_NAME"]
                        },
                        "prompt": {
                            "role": "neither",
                            "timestamp": timestamp_begin,
                            "text": input,
                            "query": {"token": 0, "input": input, "text": input,
                                      "contents": import_contents, "situation": {}}
                        },
                        "response": {
                            "role": "neither",
                            "timestamp": timestamp_end,
                            "token": 0,
                            "text": output,
                            "export_contents": export_contents
                        }
                    }
                })

            # Collect results into the list
            # For multi-persona execution, use the step's starting sub_seq (stabilizes OUTPUT_<n> references)
            result["SubSEQ"] = _step_start_sub_seq
            result["TYPE"] = model_type
            result["INPUT"] = input
            chat_history_dict = session.get_history()
            seq = session.get_seq_history()
            result["IMPORT_CONTENTS"] = [
                str(Path(session.session_folder_path) / "contents" / item["file_name"])
                for item in chat_history_dict[str(seq)][str(sub_seq)]["prompt"]["query"]["contents"]
            ]
            result["OUTPUT"] = output
            result["EXPORT_CONTENTS"] = export_contents
            results.append(result)
            sub_seq += 1

        # B-5: Bulk-save SEQ-level logs
        seq = session.get_seq_history()
        session.save_history_batch(str(seq), seq_setting_data={
            "service_info": service_info,
            "user_info": user_info,
            "practice": practice
        })

        # Bulk-update the session status (collapses 7 YAML read/write cycles into 1)
        session.save_session_metadata(
            id=session.session_id,
            name=session.session_name,
            service_id=service_info["SERVICE_ID"],
            user_id=user_info["USER_ID"],
            agent=in_agent_file,
            last_update_date=str(datetime.now()),
            active="Y",
        )

    except Exception as e:
        session.save_status("UNLOCKED")
        raise e

    finally:
        # If the background digest is already running, it will UNLOCK there
        # During multi-persona parallel execution, the caller (MultiPersona) UNLOCKs collectively, so the inner Practice does not
        if not _digest_bg_started and not in_execution.get("_NO_UNLOCK"):
            session.save_status("UNLOCKED")


# Wrapper generator for multi-persona parallel execution.
# personas empty / single -> single call to DigiMatsuExecute_Practice (existing behavior).
# 2+ -> parallel via ThreadPoolExecutor. Each persona is saved under the same seq with a different sub_seq;
#       after completion the seq's MEMORY_FLG="N" is set (to suppress automatic memory reference next turn).
#       Digest generation is skipped (SAVE_DIGEST=False). The parallel path does not stream;
#       each worker drains its generator and yields a [STATUS] chunk per finished persona.
def DigiMatsuExecute_MultiPersona(service_info, user_info, session_id, session_name,
                                   in_agent_file, user_query,
                                   in_contents=[], in_situation={}, in_overwrite_items={},
                                   in_add_knowledge=[], in_execution={}, in_personas=None,
                                   in_rag_query_text="", in_org=None):
    in_personas = list(in_personas or [])

    # 0/1 persona: forward to the existing path (fully matches legacy behavior)
    if len(in_personas) <= 1:
        single_persona = in_personas[0] if in_personas else None
        yield from DigiMatsuExecute_Practice(
            service_info, user_info, session_id, session_name,
            in_agent_file, user_query, in_contents, in_situation,
            in_overwrite_items, in_add_knowledge, in_execution,
            in_persona=single_persona, in_rag_query_text=in_rag_query_text,
            in_org=in_org,
        )
        return

    # Phase 6: if the practice has chain.PERSONAS, delegate to the chain-level parallelism inside Practice.
    # (MultiPersona does not loop over the whole practice; pass in_personas to Practice instead.)
    # Magic-word-triggered habits' practices can also have chain.PERSONAS, so we scan every habit's practice.
    try:
        agent_for_inspect = dma.DigiM_Agent(in_agent_file)
        # Determine the habit actually triggered by the magic word and check it first
        candidate_habits = []
        try:
            magic_habit = agent_for_inspect.set_practice_by_command(user_query)
            if magic_habit:
                candidate_habits.append(magic_habit)
        except Exception:
            pass
        # Also scan all habits' practices as a fallback
        for h_key in (agent_for_inspect.agent.get("HABIT") or {}):
            if h_key not in candidate_habits:
                candidate_habits.append(h_key)

        has_chain_personas = False
        for h_key in candidate_habits:
            habit_practice_file = (agent_for_inspect.agent.get("HABIT", {})
                                   .get(h_key, {}).get("PRACTICE"))
            if not habit_practice_file:
                continue
            try:
                practice_data = dmu.read_json_file(str(Path(practice_folder_path) / habit_practice_file))
            except Exception:
                continue
            if practice_data and any(c.get("PERSONAS") for c in practice_data.get("CHAINS", [])):
                has_chain_personas = True
                break

        if has_chain_personas:
            yield from DigiMatsuExecute_Practice(
                service_info, user_info, session_id, session_name,
                in_agent_file, user_query, in_contents, in_situation,
                in_overwrite_items, in_add_knowledge, in_execution,
                in_persona=None, in_rag_query_text=in_rag_query_text,
                in_personas=in_personas, in_org=in_org,
            )
            return
    except Exception:
        pass

    # ---- 2+ personas: parallel execution ----
    max_workers_setting = system_setting_dict.get("MAX_PARALLEL_PERSONAS", 4)
    max_workers = min(len(in_personas), max(1, int(max_workers_setting)))

    # Lock the session and fix the seq up-front (avoid races between parallel workers)
    _session_base_path = in_execution.get("_SESSION_BASE_PATH", "")
    session = dms.DigiMSession(session_id, session_name, base_path=_session_base_path)
    _pre_locked = in_execution.get("_PRE_LOCKED", False)
    if session.get_status() == "LOCKED" and not _pre_locked:
        raise Exception("Session is locked. Please unlock the session before executing.")
    session.save_status("LOCKED")
    seq = session.get_seq_history() + 1

    # Build per-persona execution settings (suppress serialized processing)
    def _make_exec(idx):
        e = dict(in_execution)
        e["_PRE_LOCKED"] = True
        e["_SEQ_OVERRIDE"] = seq
        e["_SUB_SEQ_START"] = idx + 1   # split sub_seq per persona
        e["SAVE_DIGEST"] = False         # multi-persona skips digest generation
        e["_NO_UNLOCK"] = True            # each persona's Practice does not UNLOCK (this wrapper does it once at the end)
        return e

    def _run_one(idx, persona):
        last_oref = {}
        try:
            # Practice yields a 4-tuple (service_info, user_info, response_chunk, output_reference)
            for _yielded in DigiMatsuExecute_Practice(
                    service_info, user_info, session_id, session_name,
                    in_agent_file, user_query, in_contents, in_situation,
                    in_overwrite_items, in_add_knowledge, _make_exec(idx),
                    in_persona=persona, in_rag_query_text=in_rag_query_text):
                if isinstance(_yielded, tuple) and len(_yielded) >= 4:
                    _oref = _yielded[3]
                    if _oref:
                        last_oref = _oref
        except Exception as e:
            return persona, str(e), last_oref
        return persona, None, last_oref

    yield service_info, user_info, f"[STATUS]Running {len(in_personas)} personas in parallel...", {}

    errors = []
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_run_one, i, p): (i, p) for i, p in enumerate(in_personas)}
            done_count = 0
            for fut in as_completed(futures):
                persona, err, _oref = fut.result()
                done_count += 1
                pid = persona.get("persona_id", "")
                pname = persona.get("name", "")
                if err:
                    errors.append((pid, err))
                    yield service_info, user_info, f"[STATUS]{pid}({pname}) error: {err}", {}
                else:
                    yield service_info, user_info, f"[STATUS]{pid}({pname}) done ({done_count}/{len(in_personas)})", {}

        # After completion: mark this seq with MEMORY_FLG="N" (so multi-persona responses are excluded from next-turn memory)
        try:
            session.chg_seq_memory_flg(str(seq), "N")
        except Exception as e:
            yield service_info, user_info, f"[STATUS]MEMORY_FLG update failed: {e}", {}
    finally:
        session.save_status("UNLOCKED")

    if errors:
        yield service_info, user_info, f"[STATUS]Done ({len(errors)} errors)", {"_persona_errors": errors}
    else:
        yield service_info, user_info, f"[STATUS]All personas done", {}
