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

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
user_folder_path = system_setting_dict["USER_FOLDER"]
session_folder_prefix = system_setting_dict["SESSION_FOLDER_PREFIX"]
temp_folder_path = system_setting_dict["TEMP_FOLDER"]
practice_folder_path = system_setting_dict["PRACTICE_FOLDER"]

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
timezone_setting = os.getenv("TIMEZONE")

# セッションロックエラー
class SessionLockedError(RuntimeError):
    pass

# B-2: 実行設定の共通パーサー
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

# B-3: USER_INPUT解決の共通関数
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

# B-3: コンテンツ解決の共通関数
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

# B-4: RAG検索用クエリ生成フェーズ（C-1での並列化フック）
def _build_intent_queries(service_info, user_info, session_id, session_name, support_agent,
                          user_query, memories_selected, situation_prompt, query_vec, RAG_query_gene, rag_query_hint=""):
    """RAG検索用クエリ(意図)を生成し、追加クエリ・ベクトル・ログを返す"""
    if not (RAG_query_gene and "RAG_QUERY_GENERATOR" in support_agent):
        return [], [], {}
    t_start = datetime.now()
    # Thinkingからのヒントがあればクエリに付加
    _query = user_query
    if rag_query_hint:
        _query = user_query + "\n\n【RAG検索のヒント】\n" + rag_query_hint
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

# B-4: メタデータ検索フェーズ（C-1での並列化フック）
def _build_meta_searches(service_info, user_info, session_id, session_name, support_agent,
                         user_query, memories_selected, situation_prompt, query_vec, meta_search):
    """クエリからメタデータ検索情報を取得する"""
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

# B-4: Thinking Agent実行（質問を分析し実行パラメータを判定）
def _run_thinking_agent(service_info, user_info, session_id, session_name,
                        support_agent, agent, user_query, digest_text, situation_prompt):
    """Thinking Agentを実行し、判定結果のJSONとログを返す"""
    import json as _json
    if "THINKING" not in support_agent:
        return {}, {}
    t_start = datetime.now()

    # Habit一覧を整形
    habit_info = ""
    for habit_key, habit_val in agent.habit.items():
        desc = ", ".join(habit_val.get("MAGIC_WORDS", []))
        habit_info += f"- {habit_key}: {desc}\n"

    # Book一覧を整形
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

    # レスポンスからJSONを抽出
    result = {}
    reasoning = response
    try:
        # ```json ... ``` ブロックがあればその中身を抽出
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

# Phase 6/7: chain.PERSONAS設定を実ペルソナdictリストに解決
# WEB_UI: in_personas（UIで選択中）をそのまま使う
# THINKING: 事前にPersonaSelectorで選定された結果を execution["_THINKING_RESULT"]["personas"] から取得
# list: persona_id列をDigiM_AgentPersonaから解決
def _resolve_step_personas(chain_personas, in_personas, in_agent_file, execution=None):
    if not chain_personas:
        return []
    if isinstance(chain_personas, str):
        upper = chain_personas.upper()
        if upper == "WEB_UI":
            return list(in_personas or [])
        if upper == "THINKING":
            # Practice先頭のpersona選定で確定したリストを参照
            thinking = (execution or {}).get("_THINKING_RESULT", {}) or {}
            picked = thinking.get("personas") or []
            if picked:
                return list(picked)
            # フォールバック: UI選択
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


# Phase 6: include_query形式（[前回の各ペルソナの回答] + [今回の質問]）でユーザー入力を整形
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


# Phase 6: PERSONA_MERGE戦略を適用してマージ済みテキストを返す
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
            _logging.getLogger(__name__).warning(f"persona_merge失敗（concatにフォールバック）: {e}")
            return "\n\n".join(
                f"【{r.get('persona_name','?')}】\n{r.get('text','')}"
                for r in persona_responses if r.get("text")
            )
    return ""


# ダイジェスト生成・保存・アンロックをバックグラウンドで実行
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
        logging.getLogger(__name__).error(f"バックグラウンドダイジェスト生成に失敗しました: {e}")
    finally:
        if unlock_on_complete:
            session.save_status("UNLOCKED")

# 単体実行用の関数
def DigiMatsuExecute(service_info, user_info, session_id, session_name, agent_file, model_type="LLM",
                     sub_seq=1, user_input="", contents=[], situation={}, overwrite_items={},
                     add_knowledge=[], prompt_temp_cd="", execution={}, seq_limit="", sub_seq_limit="",
                     persona=None, rag_query_text=""):
    export_files = []
    output_reference = {}
    timestamp_begin = str(datetime.now())
    timestamp_log = "[01.実行開始(セッション設定)]" + str(datetime.now()) + "<br>"

    # B-2: 実行設定の取得
    cfg = _parse_execution_settings(execution)

    # セッションの宣言
    _session_base_path = execution.get("_SESSION_BASE_PATH", "")
    session = dms.DigiMSession(session_id, session_name, base_path=_session_base_path)
    # seqはexecution["_SEQ_OVERRIDE"]があれば優先（マルチペルソナ並列時のレース回避）
    _seq_override = execution.get("_SEQ_OVERRIDE")
    if _seq_override is not None:
        seq = _seq_override
    else:
        seq = session.get_seq_history() + 1 if sub_seq == 1 else session.get_seq_history()

    # エージェントの宣言（personaが指定されていれば上書き適用）
    timestamp_log += "[02.エージェント設定開始]" + str(datetime.now()) + "<br>"
    agent = dma.DigiM_Agent(agent_file, persona=persona)
    if overwrite_items:
        dmu.update_dict(agent.agent, overwrite_items)
        agent.set_property(agent.agent)

    # コンテンツコンテキストを取得
    contents_context = ""
    contents_records = []
    image_files = {}
    if contents:
        timestamp_log += "[03.コンテンツコンテキスト読込開始]" + str(datetime.now()) + "<br>"
        contents_context, contents_records, image_files = agent.set_contents_context(seq, sub_seq, contents)

    user_query = user_input + contents_context
    digest_text = ""
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    query_tokens = dmu.count_token(tokenizer, model_name, user_query)
    system_tokens = dmu.count_token(tokenizer, model_name, agent.system_prompt)

    # シチュエーションの設定
    timestamp_log += "[04.シチュエーション設定]" + str(datetime.now()) + "<br>"
    situation_prompt = ""
    if situation:
        situation_setting = situation.get("SITUATION", "") + "\n" if "SITUATION" in situation else ""
        time_setting = situation.get("TIME", "")
        if time_setting:
            # 標準的な日時フォーマット以外（架空の日時設定）の場合は強い指示を付加
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

    # 会話のダイジェストを取得
    if cfg["memory_use"]:
        timestamp_log += "[05.会話ダイジェスト読込開始]" + str(datetime.now()) + "<br>"
        if session.chat_history_active_dict:
            if seq_limit or sub_seq_limit:
                _, _, chat_history_digest_dict = session.get_history_digest(seq_limit, sub_seq_limit)
            else:
                _, _, chat_history_digest_dict = session.get_history_max_digest()
            if chat_history_digest_dict:
                digest_text = "会話履歴のダイジェスト:\n" + chat_history_digest_dict["text"] + "\n---\n"

    # Thinkingログの取得（Practice経由で渡される場合）
    thinking_log = execution.get("_THINKING_LOG", {})

    # Web検索を実行
    web_context = ""
    web_search_log = {}
    if cfg["web_search"]:
        session.save_status_message("WEB検索を開始")
        yield service_info, user_info, "[STATUS]WEB検索を開始", [], []
        timestamp_log += "[06.WEB検索を開始]" + str(datetime.now()) + "<br>"
        # ThinkingのWeb検索クエリがあればそちらを優先
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
        timestamp_log += f"[06.WEB検索完了({web_engine}/{web_model}, {web_duration}s)]" + str(datetime.now()) + "<br>"
    output_reference["Web_search"] = web_search_log
    user_query += f"\n{web_context}"

    # クエリのベクトル化 (C-3: バッチ埋め込み)
    timestamp_log += "[07.クエリのベクトル化開始]" + str(datetime.now()) + "<br>"
    queries = [user_query]
    if digest_text or situation_prompt:
        user_query_ds = digest_text + user_query + situation_prompt
        queries.append(user_query_ds)
    query_vecs = dmu.embed_texts_batch([q.replace("\n", "") for q in queries])
    query_vec = query_vecs[0]

    # 会話メモリ・RAGクエリ生成・メタ検索を並列実行
    timestamp_log += "[08-10.会話メモリ/RAG検索用クエリ/メタ検索(並列)]" + str(datetime.now()) + "<br>"
    memory_limit_tokens = agent.agent["ENGINE"][model_type]["MEMORY"]["limit"]
    if model_type != "LLM":
        memory_limit_tokens -= (system_tokens + query_tokens)
    memory_role = agent.agent["ENGINE"][model_type]["MEMORY"]["role"]
    memory_priority = agent.agent["ENGINE"][model_type]["MEMORY"]["priority"]
    memory_similarity_logic = agent.agent["ENGINE"][model_type]["MEMORY"]["similarity_logic"]
    memory_digest = agent.agent["ENGINE"][model_type]["MEMORY"]["digest"]
    support_agent = agent.agent["SUPPORT_AGENT"]

    need_intent = cfg["RAG_query_gene"] and "RAG_QUERY_GENERATOR" in support_agent
    need_meta = cfg["meta_search"] and "EXTRACT_DATE" in support_agent
    if need_intent or need_meta:
        session.save_status_message("RAG検索クエリの作成を開始")
        yield service_info, user_info, "[STATUS]RAG検索クエリの作成を開始", [], []

    with ThreadPoolExecutor(max_workers=3) as executor:
        # メモリ取得を並列起動
        future_memory = None
        if cfg["memory_use"]:
            future_memory = executor.submit(
                session.get_memory, query_vec, model_name, tokenizer, memory_limit_tokens,
                memory_role, memory_priority, cfg["memory_similarity"],
                memory_similarity_logic, memory_digest, seq_limit, sub_seq_limit)
        # RAGクエリ生成を並列起動（Thinkingのヒントがあれば渡す）
        # Include Query等で user_input にペルソナ前回応答などのプレフィックスが付いている場合、
        # rag_query_text（=元のユーザー入力）が渡されていればRAG/メタ検索はそちらを使う。
        _rag_input_text = rag_query_text if rag_query_text else user_query
        _thinking_result = execution.get("_THINKING_RESULT", {})
        _rag_query_hint = _thinking_result.get("rag_query_hint", "")
        future_intent = executor.submit(
            _build_intent_queries, service_info, user_info, session_id, session_name,
            support_agent, _rag_input_text, [], situation_prompt, query_vec, cfg["RAG_query_gene"], _rag_query_hint)
        # メタ検索を並列起動
        future_meta = executor.submit(
            _build_meta_searches, service_info, user_info, session_id, session_name,
            support_agent, _rag_input_text, [], situation_prompt, query_vec, cfg["meta_search"])

        memories_selected = future_memory.result() if future_memory else []
        intent_queries, intent_vecs, RAG_query_gene_log = future_intent.result()
        meta_searches, meta_search_log = future_meta.result()

    # ユーザーメモリ層を「対話相手についての情報」コンテキストとして合成（後でクエリ先頭に挿入）
    # IMAGEGEN は画像プロンプトが3000文字制限で詰まるためスキップ
    # 優先順: execution["USER_MEMORY_LAYERS"] (UIの即時反映) > ユーザーマスタ > システムデフォルト
    user_memory_context = ""
    user_memory_used = []
    user_memory_meta = {"short_keywords": []}
    if cfg["memory_use"] and model_type == "LLM":
        try:
            _svc_id = (service_info or {}).get("SERVICE_ID", "")
            _usr_id = (user_info or {}).get("USER_ID", "")
            _override_layers = execution.get("USER_MEMORY_LAYERS")
            if _override_layers is not None:
                # UIから即時上書き（空リストでも尊重 = 全Off）
                import DigiM_UserMemory as _dmum_local
                _active_layers = [l for l in _override_layers if l in _dmum_local.LAYERS]
            else:
                _active_layers = dmus.resolve_active_layers(_usr_id)
            if _active_layers:
                user_memory_context, user_memory_used, user_memory_meta = dmumb.build_context_text(
                    _svc_id, _usr_id, _active_layers, query_text=user_query,
                )
        except Exception as _um_err:
            timestamp_log += f"[user_memory合成失敗: {_um_err}]" + str(datetime.now()) + "<br>"
    intent_dur = RAG_query_gene_log.get("duration_sec", "-") if RAG_query_gene_log else "-"
    meta_dur = meta_search_log.get("date", {}).get("duration_sec", "-") if meta_search_log else "-"
    timestamp_log += f"[08-10完了: メモリ/RAGクエリ({intent_dur}s)/メタ検索({meta_dur}s)]" + str(datetime.now()) + "<br>"
    queries += intent_queries
    query_vecs += intent_vecs
    output_reference["RAG_query_gene_log"] = RAG_query_gene_log
    output_reference["meta_search"] = meta_search_log

    # RAGコンテキストを取得
    timestamp_log += "[11.RAG開始]" + str(datetime.now()) + "<br>"
    session.save_status_message("RAGを開始")
    yield service_info, user_info, "[STATUS]RAGを開始", [], []
    if add_knowledge:
        agent.knowledge += add_knowledge
    exec_info = {"SERVICE_INFO": service_info, "USER_INFO": user_info}
    knowledge_context, knowledge_selected = agent.set_knowledge_context(
        user_query, query_vecs, exec_info, meta_searches, private_mode=cfg["private_mode"])

    # プロンプトテンプレート・クエリを設定
    timestamp_log += "[12.プロンプトテンプレート設定]" + str(datetime.now()) + "<br>"
    prompt_template = agent.set_prompt_template(prompt_temp_cd)
    if model_type == "LLM":
        # 順序: 対話相手についての情報 → Knowledge → Template → User Query → Situation
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

    # LLMの実行
    prompt = ""
    response = ""
    completion = []
    session.save_status_message("LLM実行中")
    timestamp_log += "[13.LLM実行開始]" + str(datetime.now()) + "<br>"
    response_service_info = {}
    response_user_info = {}
    _last_stream_flush = time.time()
    _STREAM_FLUSH_INTERVAL = 2  # 疑似ストリーミング書き出し間隔（秒）
    for prompt, response_chunk, completion in agent.generate_response(
            model_type, query, memories_selected, image_files, cfg["stream_mode"]):
        if response_chunk:
            response += response_chunk
            response_service_info = service_info
            response_user_info = user_info
            yield response_service_info, response_user_info, response_chunk, export_files, knowledge_selected
            # 疑似ストリーミング: 一定間隔でレスポンスをステータスに書き出し
            if cfg["stream_mode"] and time.time() - _last_stream_flush >= _STREAM_FLUSH_INTERVAL:
                session.save_status_message("LLM実行中", response=response)
                _last_stream_flush = time.time()
    timestamp_end = str(datetime.now())
    timestamp_log += "[14.LLM実行完了]" + str(datetime.now()) + "<br>"

    # レスポンステキストのサニタイズ（制御文字除去）
    response = dmu.sanitize_text(response)

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) if prompt else 0
    response_tokens = dmu.count_token(tokenizer, model_name, response) if response else 0

    # 類似度評価
    timestamp_log += "[15.結果の類似度算出開始]" + str(datetime.now()) + "<br>"
    response_vec = dmu.embed_text(response.replace("\n", "")[:8000])
    memory_ref = dmc.get_memory_reference(memories_selected, cfg["memory_similarity"], response_vec, memory_similarity_logic)
    knowledge_ref = dmc.get_knowledge_reference(response_vec, knowledge_selected)
    output_reference["memory_ref"] = memory_ref
    output_reference["knowledge_ref"] = knowledge_ref

    # コンテンツの保存
    contents_record_to = []
    if cfg["contents_save"]:
        timestamp_log += "[16.コンテンツの保存開始]" + str(datetime.now()) + "<br>"
        for rec in contents_records:
            session.save_contents_file(rec["from"], rec["to"]["file_name"])
            contents_record_to.append(rec["to"])

    # B-5: ログを一括保存
    if cfg["memory_save"]:
        timestamp_log += "[17.ログの保存開始]" + str(datetime.now()) + "<br>"

        # ベクトルファイルの保存（類似度評価用）
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
            "communication": agent.agent["COMMUNICATION"],
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

        # 画像ログ (IMAGEGEN)
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

        timestamp_log += "[完了]" + str(datetime.now()) + "<br>"

        # B-5: 一括書き込み（ダイジェストはバックグラウンドで別途追記）
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

        # レスポンス確定をステータスに反映（疑似ストリーミング用）
        session.save_status_message("ダイジェスト生成中", response=response)

        # ダイジェスト生成をバックグラウンドで起動（完了後にセッションをUNLOCK）
        if cfg["save_digest"]:
            _unlock_on_complete = execution.get("_UNLOCK_ON_DIGEST", True)
            timestamp_log += "[18.メモリダイジェストの作成をバックグラウンドで開始]" + str(datetime.now()) + "<br>"

            # インクリメンタル方式: 前回ダイジェスト + 今回1往復のみを入力にして高速化
            _slim_memories = []
            try:
                _, _, _prev_digest = session.get_history_digest(str(seq), str(sub_seq))
                if _prev_digest and _prev_digest.get("text"):
                    _slim_memories.append({"role": "assistant", "text": _prev_digest["text"]})
            except Exception:
                pass
            _slim_memories.append({"role": "user", "text": user_query})
            _slim_memories.append({"role": "assistant", "text": response})

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
                             f"ダイジェスト生成: {session_name}", session_id=session_id,
                             user_id=user_info.get("USER_ID") if isinstance(user_info, dict) else None)
            _digest_thread.start()
            output_reference["_digest_bg_started"] = True

    yield response_service_info, user_info, "", export_files, output_reference

# プラクティスで実行
def DigiMatsuExecute_Practice(service_info, user_info, session_id, session_name, in_agent_file, user_query, in_contents=[], in_situation={}, in_overwrite_items={}, in_add_knowledge=[], in_execution={}, in_persona=None, in_rag_query_text="", in_personas=None, in_org=None):

    # B-2: 実行設定の取得
    last_only = in_execution.get("LAST_ONLY", False)
    cfg = _parse_execution_settings(in_execution)

    session = dms.DigiMSession(session_id, session_name)
    # マルチペルソナ並列時はsub_seq_startで開始位置を指定（既定1）
    sub_seq = in_execution.get("_SUB_SEQ_START", 1)
    results = []
    response_service_info = service_info
    response_user_info = user_info
    _digest_bg_started = False  # バックグラウンドダイジェストが起動された場合はこちらでUNLOCKしない

    # セッションのロック（pre_locked=Trueの場合は呼び出し元で事前ロック済み）
    _pre_locked = in_execution.get("_PRE_LOCKED", False)
    if session.get_status() == "LOCKED" and not _pre_locked:
        raise Exception("Session is locked. Please unlock the session before executing the practice.")
    session.save_status("LOCKED")

    try:
        agent = dma.DigiM_Agent(in_agent_file)
        thinking_result = {}

        # Thinking Mode: AIが質問を分析して実行パラメータを判定
        if cfg["thinking_mode"] and "SUPPORT_AGENT" in agent.agent and "THINKING" in agent.agent["SUPPORT_AGENT"]:
            session.save_status_message("Thinking中...")
            yield service_info, user_info, "[STATUS]Thinking中...", {}

            # ダイジェスト取得（Thinkingの文脈理解用）
            _thinking_digest = ""
            if session.chat_history_active_dict:
                _, _, _digest_dict = session.get_history_max_digest()
                if _digest_dict:
                    _thinking_digest = _digest_dict["text"]

            # シチュエーション取得
            _thinking_situation = ""
            if in_situation:
                _thinking_situation = in_situation.get("SITUATION", "") + " " + in_situation.get("TIME", "")

            thinking_result, thinking_log = _run_thinking_agent(
                service_info, user_info, session_id, session_name,
                agent.agent["SUPPORT_AGENT"], agent, user_query,
                _thinking_digest, _thinking_situation)

            # Thinking結果を実行設定に反映（THINKING_TARGETSで有効な項目のみ）
            _targets = in_execution.get("THINKING_TARGETS", {})
            if thinking_result:
                if _targets.get("web_search", True) and "web_search" in thinking_result:
                    cfg["web_search"] = thinking_result["web_search"]
                    if "web_search_engine" in thinking_result:
                        cfg["web_search_engine"] = thinking_result["web_search_engine"]
                if _targets.get("rag_query_gene", True) and "rag_query_gene" in thinking_result:
                    cfg["RAG_query_gene"] = thinking_result["rag_query_gene"]

            # Thinkingログ・結果をチェイン実行のexecutionに渡す
            in_execution["_THINKING_LOG"] = thinking_log
            in_execution["_THINKING_RESULT"] = thinking_result
        else:
            in_execution["_THINKING_LOG"] = {}
            in_execution["_THINKING_RESULT"] = {}

        # Habit選択: Thinking結果があればそちらを優先、なければMagic Word判定
        _targets = in_execution.get("THINKING_TARGETS", {})
        habit = "DEFAULT"
        if thinking_result and _targets.get("habit", True) and "habit" in thinking_result and thinking_result["habit"] in agent.habit:
            habit = thinking_result["habit"]
        elif cfg["magic_word_use"]:
            habit = agent.set_practice_by_command(user_query)

        # Book選択: Thinking結果から自動追加
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

        # Phase 7: chain.PERSONAS="THINKING" がpracticeに含まれていれば、PersonaSelectorで自動選定
        # 候補プールは選択中ORG（in_org）配下、最大人数は execution["MAX_PERSONAS"] / setting.yaml
        # THINKING_TARGETS.personas が False の場合は選定をスキップ（_resolve_step_personasがUI選択にフォールバック）
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
            # PersonaSelectorで選定
            session.save_status_message(f"Persona選定中（最大{_max_p}人）")
            yield service_info, user_info, f"[STATUS]Persona選定中（最大{_max_p}人、候補{len(_candidates)}人）", {}
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
            # Thinking結果に保存（chain loopから _resolve_step_personas で参照）
            in_execution.setdefault("_THINKING_RESULT", {})
            in_execution["_THINKING_RESULT"]["personas"] = _thinking_personas
            in_execution["_THINKING_RESULT"]["personas_reason"] = _select_reason
            in_execution["_THINKING_RESULT"]["personas_selected_ids"] = _selected_ids
            yield service_info, user_info, f"[STATUS]Persona選定: {len(_thinking_personas)}人 ({', '.join(p.get('name','?') for p in _thinking_personas)})", {}
        for i, chain in enumerate(chains):
            # チェイン進捗をステータスに反映
            if len(chains) > 1:
                session.save_status_message(f"チェイン {i+1}/{len(chains)} ({chain['TYPE']}) 実行中")
                yield service_info, user_info, f"[STATUS]チェイン {i+1}/{len(chains)} ({chain['TYPE']}) 実行中", {}
            result = {}
            model_type = chain["TYPE"]
            input = ""
            output = ""
            import_contents = []
            export_contents = []
            # マルチペルソナ実行でも次stepからOUTPUT_<開始sub_seq>で参照できるよう、stepの開始sub_seqを記録
            _step_start_sub_seq = sub_seq

            # TYPE「LLM」の場合
            if model_type in ["LLM", "IMAGEGEN"]:
                setting = chain["SETTING"]
                agent_file = setting["AGENT_FILE"] if setting["AGENT_FILE"] != "USER" else in_agent_file
                if setting["OVERWRITE_ITEMS"] == "USER":
                    overwrite_items = in_overwrite_items
                else:
                    # in_overwrite_items（エンジン選択等）をベースにpractice設定をマージ（practice優先）
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

                # B-3: USER_INPUT解決
                user_input = _resolve_user_input(setting["USER_INPUT"], user_query, results)

                # B-3: コンテンツ解決
                import_contents = _resolve_contents(setting["CONTENTS"], in_contents, results)

                # シチュエーションの設定
                situation = {}
                if setting["SITUATION"] == "USER":
                    situation = in_situation
                else:
                    situation["TIME"] = in_situation["TIME"] if setting["SITUATION"]["TIME"] == "USER" else setting["SITUATION"]["TIME"]
                    situation["SITUATION"] = in_situation["SITUATION"] if setting["SITUATION"]["SITUATION"] == "USER" else setting["SITUATION"]["SITUATION"]

                seq_limit = chain.get("PreSEQ", "")
                sub_seq_limit = chain.get("PreSubSEQ", "")

                # 中間チェインのダイジェストBGスレッドはUNLOCKしない（最後のチェインのみUNLOCK）
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
                    # User Memory: UI即時上書きを下流へ伝播（None=未指定なら下流が user master / system default にフォールバック）
                    "USER_MEMORY_LAYERS": in_execution.get("USER_MEMORY_LAYERS"),
                    # マルチペルソナ並列実行用のフラグを下流のDigiMatsuExecuteへ伝播
                    "_SEQ_OVERRIDE":     in_execution.get("_SEQ_OVERRIDE"),
                    "_SUB_SEQ_START":    in_execution.get("_SUB_SEQ_START"),
                    "_SESSION_BASE_PATH": in_execution.get("_SESSION_BASE_PATH", ""),
                }

                # Phase 6/7: chain.PERSONAS による step 内マルチペルソナ並列実行を判定
                step_personas = _resolve_step_personas(chain.get("PERSONAS"), in_personas, in_agent_file, in_execution)

                response = ""
                # 最初のチェインステップでのみrag_query_textを使用
                _rag_query_text_for_step = in_rag_query_text if i == 0 else ""

                if len(step_personas) >= 2:
                    # ---- マルチペルソナ並列実行 ----
                    yield service_info, user_info, f"[STATUS]chain[{i}] {len(step_personas)}ペルソナで並列実行中...", {}
                    # seqを事前確定（_SEQ_OVERRIDE未設定時）
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
                            yield service_info, user_info, f"[STATUS]chain[{i}] {_p.get('name','?')}完了", {}

                    # sub_seq順でソート（保存順を安定化）
                    _persona_responses.sort(key=lambda r: r["sub_seq"])

                    # 各persona sub_seq に setting.memory_flg="N" / chain_index / chain_role を付与
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

                    # PERSONA_MERGEを適用（出力テキスト = 次stepへのoutput）
                    _merge_method = chain.get("PERSONA_MERGE", "summary")
                    _merge_level = chain.get("PERSONA_MERGE_LEVEL", "medium")
                    response = _apply_persona_merge(
                        _merge_method, _persona_responses, user_input, _merge_level,
                        service_info, user_info, session_id, session_name, agent.support_agent
                    )

                    # sub_seqをN分進める
                    sub_seq += len(step_personas) - 1   # 既存ループ末尾で +1 されるので合計 N

                else:
                    # ---- 既存パス: 単一ペルソナ実行（または in_persona）----
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

                # B-3: USER_INPUT解決
                user_input = _resolve_user_input(
                    setting["USER_INPUT"], user_query, results) if "USER_INPUT" in setting else ""
                input = user_input

                # B-3: コンテンツ解決
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

                # B-5: TOOL実行ログを一括保存
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

            # 結果のリストへの格納
            # マルチペルソナ実行時はstep開始時のsub_seqを使う（OUTPUT_<n>参照を安定化）
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

        # B-5: SEQレベルのログを一括保存
        seq = session.get_seq_history()
        session.save_history_batch(str(seq), seq_setting_data={
            "service_info": service_info,
            "user_info": user_info,
            "practice": practice
        })

        # セッションステータスの一括更新（7回→1回のYAML読み書き）
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
        # バックグラウンドダイジェストが起動済みの場合はそちらでUNLOCKされる
        # マルチペルソナ並列時は呼び出し元(MultiPersona)が一括UNLOCKするため、内側のPracticeはUNLOCKしない
        if not _digest_bg_started and not in_execution.get("_NO_UNLOCK"):
            session.save_status("UNLOCKED")


# 複数ペルソナの並列実行ラッパー（generator）。
# personasが空/1件 → DigiMatsuExecute_Practiceを単発呼び出し（既存挙動）。
# 2件以上 → ThreadPoolExecutorで並列実行。各ペルソナは同seq・別sub_seqで保存され、
#         完了後にseqのMEMORY_FLG="N"を立てる（次ターンの自動メモリ参照を抑制）。
#         ダイジェスト生成はスキップ（SAVE_DIGEST=False）。並列パスはストリーミング非対応で、
#         各ワーカー内でgeneratorをdrainし、完了したペルソナ単位で[STATUS]チャンクをyieldする。
def DigiMatsuExecute_MultiPersona(service_info, user_info, session_id, session_name,
                                   in_agent_file, user_query,
                                   in_contents=[], in_situation={}, in_overwrite_items={},
                                   in_add_knowledge=[], in_execution={}, in_personas=None,
                                   in_rag_query_text="", in_org=None):
    in_personas = list(in_personas or [])

    # 0/1ペルソナは既存パスへフォワード（既存挙動と完全一致）
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

    # Phase 6: practiceがchain.PERSONASを持つ場合、Practice内のchain単位並列に委譲
    # （MultiPersona側ではwhole-practice反復を行わない。in_personasをPracticeへ渡す）
    # マジックワードで起動された別habitのpracticeにもchain.PERSONASがあり得るので、
    # 全HABITのpracticeを走査してchain.PERSONASがあるか確認する。
    try:
        agent_for_inspect = dma.DigiM_Agent(in_agent_file)
        # マジックワードで実際に起動するhabitを判定。それを最優先にチェック
        candidate_habits = []
        try:
            magic_habit = agent_for_inspect.set_practice_by_command(user_query)
            if magic_habit:
                candidate_habits.append(magic_habit)
        except Exception:
            pass
        # フォールバックとして全habitのpracticeも走査
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

    # ---- 2人以上: 並列実行 ----
    max_workers_setting = system_setting_dict.get("MAX_PARALLEL_PERSONAS", 4)
    max_workers = min(len(in_personas), max(1, int(max_workers_setting)))

    # 事前にセッションロック＆seqを確定（並列ワーカ間のレース回避）
    _session_base_path = in_execution.get("_SESSION_BASE_PATH", "")
    session = dms.DigiMSession(session_id, session_name, base_path=_session_base_path)
    _pre_locked = in_execution.get("_PRE_LOCKED", False)
    if session.get_status() == "LOCKED" and not _pre_locked:
        raise Exception("Session is locked. Please unlock the session before executing.")
    session.save_status("LOCKED")
    seq = session.get_seq_history() + 1

    # 各ペルソナ用の実行設定を組み立て（直列処理を抑制）
    def _make_exec(idx):
        e = dict(in_execution)
        e["_PRE_LOCKED"] = True
        e["_SEQ_OVERRIDE"] = seq
        e["_SUB_SEQ_START"] = idx + 1   # ペルソナ毎にsub_seqを分ける
        e["SAVE_DIGEST"] = False         # マルチペルソナはダイジェスト生成をスキップ
        e["_NO_UNLOCK"] = True            # 各ペルソナのPracticeはUNLOCKしない（このラッパーが最後に1回UNLOCK）
        return e

    def _run_one(idx, persona):
        last_oref = {}
        try:
            # Practiceは4要素タプル(service_info, user_info, response_chunk, output_reference)をyieldする
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

    yield service_info, user_info, f"[STATUS]{len(in_personas)}ペルソナで並列実行中...", {}

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
                    yield service_info, user_info, f"[STATUS]{pid}({pname})エラー: {err}", {}
                else:
                    yield service_info, user_info, f"[STATUS]{pid}({pname})完了 ({done_count}/{len(in_personas)})", {}

        # 完了後: このseqをMEMORY_FLG="N"でマーク（複数ペルソナの応答を次ターンメモリから除外）
        try:
            session.chg_seq_memory_flg(str(seq), "N")
        except Exception as e:
            yield service_info, user_info, f"[STATUS]MEMORY_FLG更新失敗: {e}", {}
    finally:
        session.save_status("UNLOCKED")

    if errors:
        yield service_info, user_info, f"[STATUS]完了（エラー{len(errors)}件）", {"_persona_errors": errors}
    else:
        yield service_info, user_info, f"[STATUS]全ペルソナ完了", {}
