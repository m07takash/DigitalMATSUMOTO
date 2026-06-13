import os
import json
from pathlib import Path
from dotenv import load_dotenv
import re
import time
import pandas as pd
import requests
import DigiM_Agent as dma
import DigiM_Util as dmu
import DigiM_Session as dms
import DigiM_Execute as dme
import DigiM_ToolRegistry as dmtr

# Load folder paths and other settings from setting.yaml
system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]
character_folder_path = system_setting_dict["CHARACTER_FOLDER"]
practice_folder_path = system_setting_dict["PRACTICE_FOLDER"]
tool_folder_path = system_setting_dict.get("TOOL_FOLDER", "user/common/tool/")

# Resolve a function by its string name.
# Lookup order: tool registry (declarative source of truth) -> module globals (legacy).
def call_function_by_name(service_info, user_info, func_name, *args, **kwargs):
    entry = dmtr.get_tool(func_name)
    if entry and entry.get("func"):
        return entry["func"](service_info, user_info, *args, **kwargs)
    if func_name in globals():
        return globals()[func_name](service_info, user_info, *args, **kwargs)
    response = f"Error: Tool function '{func_name}' not found."
    export_contents = []
    return service_info, user_info, response, export_contents


# ============================================================================
# MIGRATED: Tool implementations below have been moved to plugin files under
# user/common/tool/ (loaded by _load_tool_plugins at module bottom).
# Kept as comments for rollback only — see:
#   user/common/tool/{history,dialog,thinking,analysis,persona,art_critic,web_search}.py
# ============================================================================
# # Reply with a fixed message
# def fixed_message(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     session = dms.DigiMSession(session_id)
#     chat_history_dict = session.get_history()
# 
#     response = input
#     export_contents = []
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, export_contents
# 
# # Delete the session's chat history
# def forget_history(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     session = dms.DigiMSession(session_id)
#     chat_history_dict = session.get_history()
# 
#     for seq in chat_history_dict.keys():
#         session.chg_seq_history(seq, "N")
# 
#     response = "All conversation history has been forgotten."
#     export_contents = []
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, export_contents
# 
# # Restore the session's chat history
# def remember_history(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     session = dms.DigiMSession(session_id)
#     chat_history_dict = session.get_history()
# 
#     for seq in chat_history_dict.keys():
#         session.chg_seq_history(seq, "Y")
# 
#     response = "All conversation history has been restored."
#     export_contents = []
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, export_contents
# 
# # Extract a date from text
# def extract_date(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     if not agent_file:
#         agent_file = "agent_55ExtractDate.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     memories_selected = []
#     if "Memories_Selected" in add_info:
#         memories_selected = add_info["Memories_Selected"]
#     if "Situation" in add_info:
#         situation_prompt = add_info["Situation"]
#     if "QueryVecs" in add_info:
#         query_vecs = add_info["QueryVecs"]
# 
#     # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "Extract Date"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
# 
#     # Execute RAG
#     user_query = input
#     knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs)
# 
#     # Build the prompt
#     prompt = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'
# 
#     # Execute the LLM
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, stream_mode=False):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt) 
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens
# 
# # PageIndex search: have the LLM select page IDs relevant to the query
# def page_index_search(exec_info, agent_file, query, pages, max_pages=5):
#     import json as _json
#     if not agent_file:
#         agent_file = "agent_59PageIndexSearch.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
# 
#     # Format the page list
#     page_list_text = ""
#     for p in pages:
#         tags = ", ".join(p.get("tags", [])) if p.get("tags") else ""
#         page_list_text += f"- {p['id']}: {p['title']} — {p.get('summary', '')} [{tags}]\n"
# 
#     # Fetch the prompt template
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "Page Index Search"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
# 
#     # Assemble the prompt
#     prompt = f"{prompt_template}\n\n【Page list】\n{page_list_text}\nMax selections: {max_pages}\n\n【User question】\n{query}"
# 
#     # Run the LLM
#     response = ""
#     for _, response_chunk, _ in agent.generate_response(model_type, prompt, [], stream_mode=False):
#         if response_chunk:
#             response += response_chunk
# 
#     # Extract the ID list from the response
#     selected_ids = []
#     try:
#         import re
#         json_match = re.search(r'\[.*?\]', response, re.DOTALL)
#         if json_match:
#             selected_ids = _json.loads(json_match.group(0))
#     except (_json.JSONDecodeError, AttributeError):
#         pass
# 
#     # Filter to valid IDs only
#     valid_ids = {p["id"] for p in pages}
#     selected_ids = [pid for pid in selected_ids if pid in valid_ids][:max_pages]
# 
#     return selected_ids
# 
# # Thinking Agent: analyze the user's question and return execution parameters as JSON
# def thinking_agent(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
#     if not agent_file:
#         agent_file = "agent_70DigiMThinking.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     situation_prompt = add_info.get("Situation", "")
#     digest_text = add_info.get("DigestText", "")
#     habit_info = add_info.get("HabitInfo", "")
#     book_info = add_info.get("BookInfo", "")
# 
#     # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "Thinking"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
# 
#     # Insert additional info into the prompt
#     context = ""
#     if habit_info:
#         context += f"\n【Available habits】\n{habit_info}\n"
#     if book_info:
#         context += f"\n【Available books】\n{book_info}\n"
#     if digest_text:
#         context += f"\n【Conversation digest】\n{digest_text}\n"
# 
#     prompt = f'{context}{prompt_template}{user_query}{situation_prompt}'
# 
#     # Execute the LLM
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, [], stream_mode=False):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     return service_info, user_info, response, model_name, prompt_tokens, response_tokens
# 
# # Generate the RAG query from text
# def RAG_query_generator(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
#     if not agent_file:
#         agent_file = "agent_56RAGQueryGenerator.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     memories_selected = []
#     if "Memories_Selected" in add_info:
#         memories_selected = add_info["Memories_Selected"]
#     if "Situation" in add_info:
#         situation_prompt = add_info["Situation"]
#     if "QueryVecs" in add_info:
#         query_vecs = add_info["QueryVecs"]
# 
#     # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "RAG Query Generator"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
# 
#     # Execute RAG
#     knowledge_context, knowledge_selected = agent.set_knowledge_context(user_query, query_vecs)
# 
#     # Build the prompt
#     prompt = f'{knowledge_context}{prompt_template}{user_query}{situation_prompt}'
# 
#     # Execute the LLM
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, stream_mode=False):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens
# 
# # Generate the conversation digest
# def dialog_digest(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
#     if not agent_file:
#         agent_file = "agent_51DialogDigest.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     memories_selected = []
#     if "Memories_Selected" in add_info:
#         memories_selected = add_info["Memories_Selected"]
# 
#     # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "Dialog Digest"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
# 
#     # Convert memory to text
#     digest_memories_text = ", ".join(
#         f'{{"role": "{item["role"]}", "content": "{item["text"]}"}}'
#         for item in memories_selected
#     )
# 
#     # Build the prompt
#     query = f'{prompt_template}{user_query}\n{digest_memories_text}'
# 
#     # Execute the LLM
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     # Output format
#     response = "【Conversation digest so far】\n" + response
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens
# 
# # Fair integration / summary across multiple persona responses.
# # persona_responses: [{"persona_name": "...", "text": "..."}, ...]
# # summary_level: "light"/"medium"/"heavy" or a free-form string (e.g. "around 300 chars")
# def dialog_persona_merge(service_info, user_info, session_id, session_name, agent_file,
#                           user_query, persona_responses, summary_level="medium"):
#     if not agent_file:
#         agent_file = "agent_50PersonaMerge.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     # Mapping of summary-level keyword -> description (free-form strings are passed through)
#     level_map = {
#         "light":  "簡潔（200字程度）",  # concise, ~200 chars
#         "medium": "標準（500字程度）",  # standard, ~500 chars
#         "heavy":  "詳細（1000字程度）",  # detailed, ~1000 chars
#     }
#     summary_level_text = level_map.get(summary_level, summary_level)
# 
#     # Fetch the prompt template and substitute {summary_level}
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "Persona Merge"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
#     prompt_template = prompt_template.replace("{summary_level}", summary_level_text)
# 
#     # Convert persona responses to text
#     responses_text = "\n\n".join(
#         f"【{(r.get('persona_name') or '?')}】\n{r.get('text', '')}"
#         for r in persona_responses
#     )
# 
#     query = (
#         f"{prompt_template}\n\n"
#         f"【Original question】\n{user_query}\n\n"
#         f"【Each persona's response】\n{responses_text}"
#     )
# 
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     return service_info, user_info, response, model_name, prompt_tokens, response_tokens
# 
# 
# # Phase 7: Select up to N optimal personas based on the question content
# # candidate_personas: [{"persona_id": "P0001", "name": "...", "act": "...", "character_text": "..."}, ...]
# # Returns: (selected_persona_ids, reasoning, model_name, prompt_tokens, response_tokens)
# def select_personas(service_info, user_info, session_id, session_name, agent_file,
#                     user_query, candidate_personas, max_personas=3):
#     if not candidate_personas:
#         return [], "no candidates", "", 0, 0
#     if not agent_file:
#         agent_file = "agent_54PersonaSelector.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     # Fetch the prompt template
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "Persona Selector"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
# 
#     # Compact-serialize candidate personas to JSON (id / name / act / leading excerpt of character_text)
#     candidates_json = json.dumps([
#         {
#             "id": p.get("persona_id", ""),
#             "name": p.get("name", ""),
#             "act": p.get("act", ""),
#             "character": (p.get("character_text") or "")[:120],
#         }
#         for p in candidate_personas
#     ], ensure_ascii=False, indent=2)
# 
#     # Substitute placeholders
#     prompt_template = (prompt_template
#                        .replace("{max_personas}", str(max_personas))
#                        .replace("{candidate_personas}", candidates_json))
# 
#     query = f'{prompt_template}{user_query}'
# 
#     # Execute the LLM (non-streaming)
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     # Extract JSON
#     selected_ids = []
#     reasoning = ""
#     try:
#         json_str = response.strip()
#         # Remove ```json ... ``` fences
#         if json_str.startswith("```"):
#             json_str = re.sub(r"^```(?:json)?\s*", "", json_str)
#             json_str = re.sub(r"\s*```$", "", json_str)
#         # Extract the JSON block
#         m = re.search(r"\{.*\}", json_str, re.DOTALL)
#         if m:
#             parsed = json.loads(m.group(0))
#             ids_raw = parsed.get("personas") or []
#             if isinstance(ids_raw, list):
#                 # Keep only IDs that exist in the candidate pool
#                 candidate_ids = {p.get("persona_id") for p in candidate_personas}
#                 selected_ids = [str(pid) for pid in ids_raw if str(pid) in candidate_ids]
#                 # Trim from the front when exceeding the cap
#                 if max_personas and len(selected_ids) > max_personas:
#                     selected_ids = selected_ids[:max_personas]
#             reasoning = parsed.get("reasoning", "")
#     except Exception as e:
#         import logging
#         logging.getLogger(__name__).warning(f"persona selector JSON parse failed: {e}, raw={response[:200]!r}")
# 
#     return selected_ids, reasoning, model_name, prompt_tokens, response_tokens
# 
# 
# # Generate the session name
# def gene_session_name(service_info, user_info, session_id, session_name, agent_file, user_query, import_contents=[], add_info={}):
#     if not agent_file:
#         agent_file = "agent_57SessionName.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     memories_selected = []
#     if "Memories_Selected" in add_info:
#         memories_selected = add_info["Memories_Selected"]
# 
#     # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "Session Name"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
# 
#     # Convert memory to text
#     digest_memories_text = ", ".join(
#         f'{{"role": "{item["role"]}", "content": "{item["text"]}"}}'
#         for item in memories_selected
#     )
# 
#     # Build the prompt
#     query = f'{prompt_template}\n{digest_memories_text}\n{user_query}'
# 
#     # Execute the LLM
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, query, stream_mode=False):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens
# 
# # Web search (Perplexity AI)
# def WebSearch_PerplexityAI(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     if os.path.exists("system.env"):
#         load_dotenv("system.env")
#     api_key = os.getenv("PERPLEXITY_API_KEY")
# 
#     system_setting_dict = dmu.read_yaml_file("setting.yaml")
#     url = system_setting_dict["PERPLEXITY_URL"]
#     model = system_setting_dict["PERPLEXITY_MODEL"]
#     system_prompt = system_setting_dict["PERPLEXITY_SYSTEM_PROMPT"]
#     user_prompt = system_setting_dict["PERPLEXITY_USER_PROMPT"]
#     max_tokens = system_setting_dict["PERPLEXITY_MAX_TOKENS"]
#     reasoning_effort = system_setting_dict["PERPLEXITY_REASONING_EFFORT"]
# 
#     headers = {
#         "Authorization": f"Bearer {api_key}",
#         "Content-Type": "application/json"
#     }
# 
#     payload = {
#         "model": model,
#         "messages": [
#             {
#                 "role": "system",
#                 "content": system_prompt
#             },
#             {
#                 "role": "user",
#                 "content": user_prompt +"\n"+ input,
#                 "max_tokens": max_tokens,
#                 "reasoning_effort": reasoning_effort
#             }
#         ]
#     }
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     results = requests.post(url, json=payload, headers=headers)
# 
#     response = results.json()["choices"][0]["message"]["content"]
#     export_contents = results.json()["search_results"]
# 
#     return response_service_info, response_user_info, response, export_contents
# 
# # Web search (OpenAI web_search)
# def WebSearch_OpenAI(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     from openai import OpenAI
#     if os.path.exists("system.env"):
#         load_dotenv("system.env")
#     api_key = os.getenv("OPENAI_API_KEY")
# 
#     system_setting_dict = dmu.read_yaml_file("setting.yaml")
#     system_prompt = system_setting_dict.get("OPENAI_SEARCH_SYSTEM_PROMPT", "Be precise and concise.")
#     user_prompt = system_setting_dict.get("OPENAI_SEARCH_USER_PROMPT", "以下の入力に基づいて、関連する情報を提供してください。")
#     model = system_setting_dict.get("OPENAI_SEARCH_MODEL", "gpt-4.1-mini")
# 
#     client = OpenAI(api_key=api_key)
#     response = client.responses.create(
#         model=model,
#         tools=[{"type": "web_search_preview"}],
#         input=user_prompt + "\n" + input,
#         instructions=system_prompt,
#     )
# 
#     # Extract text and URLs from the response
#     response_text = ""
#     export_urls = []
#     for item in response.output:
#         if item.type == "message":
#             for content in item.content:
#                 if hasattr(content, "text"):
#                     response_text += content.text
#                     # Extract URLs from annotations
#                     if hasattr(content, "annotations"):
#                         for ann in content.annotations:
#                             if hasattr(ann, "url"):
#                                 export_urls.append({"url": ann.url, "title": getattr(ann, "title", "")})
# 
#     return service_info, user_info, response_text, export_urls
# 
# # Web search (Google Grounding Search)
# def WebSearch_Google(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     from google import genai
#     from google.genai import types
#     if os.path.exists("system.env"):
#         load_dotenv("system.env")
#     api_key = os.getenv("GEMINI_API_KEY")
# 
#     system_setting_dict = dmu.read_yaml_file("setting.yaml")
#     user_prompt = system_setting_dict.get("GOOGLE_SEARCH_USER_PROMPT", "以下の入力に基づいて、関連する情報を提供してください。")
#     model = system_setting_dict.get("GOOGLE_SEARCH_MODEL", "gemini-2.5-flash-preview-05-20")
# 
#     client = genai.Client(api_key=api_key)
#     response = client.models.generate_content(
#         model=model,
#         contents=user_prompt + "\n" + input,
#         config=types.GenerateContentConfig(
#             tools=[types.Tool(google_search=types.GoogleSearch())],
#         ),
#     )
# 
#     # Extract text and URLs from the response
#     response_text = response.text if response.text else ""
#     export_urls = []
#     if response.candidates and response.candidates[0].grounding_metadata:
#         gm = response.candidates[0].grounding_metadata
#         if gm.grounding_chunks:
#             for chunk in gm.grounding_chunks:
#                 if hasattr(chunk, "web") and chunk.web:
#                     export_urls.append({"url": chunk.web.uri, "title": chunk.web.title or ""})
# 
#     return service_info, user_info, response_text, export_urls
# 
# # Web search (Anthropic Claude server-side web_search tool)
# def WebSearch_Claude(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     import anthropic
#     if os.path.exists("system.env"):
#         load_dotenv("system.env")
#     api_key = os.getenv("ANTHROPIC_API_KEY")
# 
#     system_setting_dict = dmu.read_yaml_file("setting.yaml")
#     model = system_setting_dict.get("CLAUDE_SEARCH_MODEL", "claude-sonnet-4-6")
#     user_prompt = system_setting_dict.get("CLAUDE_SEARCH_USER_PROMPT", "以下の入力に基づいて、関連する情報を提供してください。")
#     system_prompt = system_setting_dict.get("CLAUDE_SEARCH_SYSTEM_PROMPT", "Be precise and concise.")
#     max_tokens = system_setting_dict.get("CLAUDE_SEARCH_MAX_TOKENS", 4096)
# 
#     client = anthropic.Anthropic(api_key=api_key)
#     response = client.messages.create(
#         model=model,
#         max_tokens=max_tokens,
#         system=system_prompt,
#         tools=[{"type": "web_search_20260209", "name": "web_search"}],
#         messages=[{"role": "user", "content": user_prompt + "\n" + input}],
#     )
# 
#     # Aggregate text blocks; collect unique citation URLs across all text blocks
#     response_text = ""
#     export_urls = []
#     seen_urls = set()
#     for block in response.content:
#         if getattr(block, "type", None) == "text":
#             response_text += getattr(block, "text", "") or ""
#             for citation in (getattr(block, "citations", None) or []):
#                 url = getattr(citation, "url", None)
#                 title = getattr(citation, "title", "") or ""
#                 if url and url not in seen_urls:
#                     seen_urls.add(url)
#                     export_urls.append({"url": url, "title": title})
# 
#     return service_info, user_info, response_text, export_urls
# 
# # Dispatch web search (switch function by engine name)
# WEB_SEARCH_ENGINES = {
#     "Perplexity": WebSearch_PerplexityAI,
#     "OpenAI": WebSearch_OpenAI,
#     "Google": WebSearch_Google,
#     "Claude": WebSearch_Claude,
# }
# 
# def WebSearch(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}, engine="Perplexity"):
#     func = WEB_SEARCH_ENGINES.get(engine, WebSearch_PerplexityAI)
#     return func(service_info, user_info, session_id, session_name, agent_file, input, import_contents, add_info)
# 
# # Business analysis
# def management_analysis(service_info, user_info, session_id, session_name, agent_file, input, import_contents=[], add_info={}):
#     try:
#         client_name = re.search(r"Client:(.+)", input).group(1).strip()
#         biz_name = re.search(r"Biz:(.+)", input).group(1).strip()
#         query = ""
#         remaining_lines = []
#         for line in input.splitlines():
#             if not line.startswith("Client:") and not line.startswith("Biz:"):
#                 remaining_lines.append(line)
#         if remaining_lines:
#             query = "\n".join(remaining_lines).strip()
#     except AttributeError:
#         rule_text = "Include the following in your input.\nClient: <company name>\nBiz: <business name>"
#         return service_info, user_info, rule_text, []
# 
#     test_folder_path = "test/"
#     test_file = "Tool_MgrAnalysis.xlsx"
#     test_sheet_name = "Test"
#     raw_name_Q = "Q"
# 
#     # Execution settings
#     situation = {}
#     overwrite_items = {}
#     add_knowledges = []
#     execution = {}
#     execution["MEMORY_USE"] = True
#     execution["MEMORY_SIMILARITY"] = False
#     execution["MAGIC_WORD_USE"] = False
#     execution["STREAM_MODE"] = False
#     execution["SAVE_DIGEST"] = True
#     execution["META_SEARCH"] = True
#     execution["RAG_QUERY_GENE"] = True
# 
#     # Unlock the session once
#     session = dms.DigiMSession(session_id, session_name)
#     session.save_status("UNLOCKED")
# 
#     # Load the test file and loop
#     test_file_path = str(Path(test_folder_path) / test_file)
#     test_sheet = pd.read_excel(test_file_path, sheet_name=test_sheet_name)
#     Q_no = 0
#     for index, row in test_sheet.iterrows():
#         questionaire = str(row[raw_name_Q]).replace("{client}", client_name).replace("{biz}", biz_name)
#         user_input = query + questionaire
# 
#         web_flg = str(row["WEB"])
#         if web_flg == "Y":
#             execution["WEB_SEARCH"] = True
#         else:
#             execution["WEB_SEARCH"] = False
# 
#         response = ""
#         for response_service_info, response_user_info, response_chunk, output_reference in dme.DigiMatsuExecute_Practice(service_info, user_info, session_id, session_name, agent_file, user_input, import_contents, situation, overwrite_items, add_knowledges, execution):
#             if response_chunk and not str(response_chunk).startswith("[STATUS]"):
#                 response += response_chunk
# 
#         Q_no += 1
#         time.sleep(3)
# 
#     export_contents = []
# 
#     return response_service_info, response_user_info, response, export_contents
# 
# # Compare texts
# def compare_texts(service_info, user_info, head1, text1, head2, text2, query_compare=""):
#     agent_file = "agent_53CompareTexts.json"
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     # Resolve the prompt template assigned to the agent
#     if query_compare == "":
#         prompt_temp_cd = "Compare Texts"
#         prompt_template = agent.set_prompt_template(prompt_temp_cd)
#     else:
#         prompt_template = query_compare
# 
#     # Build the prompt
#     prompt = f'{prompt_template}\n\n[{head1}]\n{text1}\n\n[{head2}]\n{text2}'
# 
#     # Execute the LLM
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, prompt):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens
# 
# # Generate critique on image data
# def art_critics(service_info, user_info, memories_selected=[], image_paths=[], agent_file="agent_52ArtCritic.json"):
#     agent = dma.DigiM_Agent(agent_file)
# 
#     model_type = "LLM"
#     model_name = agent.agent["ENGINE"][model_type]["MODEL"]
#     tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
# 
#     # Read the prompt template from the first PRACTICE entry defined as the agent's DEFAULT
#     practice_file = agent.agent["HABIT"]["DEFAULT"]["PRACTICE"]
#     practice = dmu.read_json_file(str(Path(practice_folder_path) / practice_file))
#     if practice["CHAINS"][0]["TYPE"] == "LLM":
#         prompt_temp_cd = practice["CHAINS"][0]["SETTING"]["PROMPT_TEMPLATE"]
#     else:
#         prompt_temp_cd = "Art Critic"
#     prompt_template = agent.set_prompt_template(prompt_temp_cd)
# 
#     # Build the prompt
#     prompt = f'{prompt_template}'
# 
#     # Execute the LLM
#     response = ""
#     for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected, image_paths):
#         if response_chunk:
#             response += response_chunk
# 
#     prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
#     response_tokens = dmu.count_token(tokenizer, model_name, response)
# 
#     response_service_info = service_info
#     response_user_info = user_info
# 
#     return response_service_info, response_user_info, response, model_name, prompt_tokens, response_tokens
# 
# 
# # ---------------------------------------------------------------------------
# # Engine-agnostic SKILL / Thinking-mode tool dispatch
# # ---------------------------------------------------------------------------
# # Tools registered here can be picked by any LLM (GPT/Gemini/Claude/Grok) via
# # a plain JSON reply — no provider-specific tools=[] wiring required. See
# # DigiM_ToolRegistry for the registry and prompt-rendering helpers.
# #
# # All registered tools share the uniform signature
# #   func(service_info, user_info, session_id, session_name,
# #        agent_file, input, import_contents=[], add_info={})
# # so call_function_by_name can dispatch them uniformly. The LLM-visible "args"
# # are flat dicts; `input` becomes the positional `input` argument, all other
# # keys flow into `add_info` (see DigiM_ToolRegistry.split_args_to_uniform_signature).
# 
# # Web search dispatch wrapper: lets the LLM specify the engine via args.engine,
# # and accepts an explicit engine= kwarg for code-driven callers (e.g. cfg-driven path).
# def _websearch_dispatch(service_info, user_info, session_id, session_name,
#                         agent_file, input, import_contents=[], add_info={}, engine=None):
#     if engine is None:
#         engine = (add_info or {}).get("engine", "Perplexity")
#     return WebSearch(service_info, user_info, session_id, session_name,
#                      agent_file, input, import_contents, add_info, engine=engine)
# 
# 
# _INPUT_TEXT = {
#     "type": "string",
#     "description": "Free-form text — typically the user's query or relevant input for this tool.",
# }
# 
# # --- Session history control --------------------------------------------------
# dmtr.register_tool(
#     "fixed_message",
#     description=(
#         "Return the supplied text verbatim as the assistant's response. "
#         "Use for canned replies where no LLM generation is needed."
#     ),
#     schema={
#         "type": "object",
#         "properties": {"input": _INPUT_TEXT},
#         "required": ["input"],
#     },
#     func=fixed_message,
# )
# 
# dmtr.register_tool(
#     "forget_history",
#     description=(
#         "Mark the current session's entire chat history as 'forgotten' so it is "
#         "excluded from future memory context. Use when the user explicitly asks "
#         "to erase or ignore prior turns in this session."
#     ),
#     schema={"type": "object", "properties": {}, "required": []},
#     func=forget_history,
# )
# 
# dmtr.register_tool(
#     "remember_history",
#     description=(
#         "Restore (un-forget) the current session's chat history so previously "
#         "hidden turns are visible to memory again. Inverse of forget_history."
#     ),
#     schema={"type": "object", "properties": {}, "required": []},
#     func=remember_history,
# )
# 
# # --- LLM-backed helpers -------------------------------------------------------
# dmtr.register_tool(
#     "extract_date",
#     description=(
#         "Resolve relative date expressions (today / yesterday / next Monday / "
#         "next month, etc.) in the user's text into absolute ISO dates. "
#         "Use when the user's request depends on knowing the concrete calendar date."
#     ),
#     schema={
#         "type": "object",
#         "properties": {"input": _INPUT_TEXT},
#         "required": ["input"],
#     },
#     func=extract_date,
# )
# 
# dmtr.register_tool(
#     "thinking_agent",
#     description=(
#         "Run the meta-cognitive 'Thinking' agent which analyses the user's "
#         "question and decides downstream execution parameters (which habit / "
#         "book / RAG / web search to engage). Returns structured decision text. "
#         "Typically used by the orchestrator rather than picked by another LLM."
#     ),
#     schema={
#         "type": "object",
#         "properties": {"input": _INPUT_TEXT},
#         "required": ["input"],
#     },
#     func=thinking_agent,
# )
# 
# dmtr.register_tool(
#     "RAG_query_generator",
#     description=(
#         "Generate a refined query string optimized for retrieval against the "
#         "agent's RAG knowledge base. Use when the raw user text needs to be "
#         "reformulated into a search-friendly query."
#     ),
#     schema={
#         "type": "object",
#         "properties": {"input": _INPUT_TEXT},
#         "required": ["input"],
#     },
#     func=RAG_query_generator,
# )
# 
# dmtr.register_tool(
#     "dialog_digest",
#     description=(
#         "Summarize the recent conversation memory of the current session into a "
#         "short digest. Use when downstream steps need compressed context rather "
#         "than the full history."
#     ),
#     schema={
#         "type": "object",
#         "properties": {"input": _INPUT_TEXT},
#         "required": [],
#     },
#     func=dialog_digest,
# )
# 
# dmtr.register_tool(
#     "gene_session_name",
#     description=(
#         "Generate a short, descriptive session name from the user's first query "
#         "(or short conversation digest). Typically called automatically when a "
#         "new session is started without an explicit name."
#     ),
#     schema={
#         "type": "object",
#         "properties": {"input": _INPUT_TEXT},
#         "required": ["input"],
#     },
#     func=gene_session_name,
# )
# 
# dmtr.register_tool(
#     "management_analysis",
#     description=(
#         "Run a management / strategy analysis pass over the input text (e.g. "
#         "SWOT-style framing, KPI breakdown). Use for business-oriented requests "
#         "that benefit from a structured analytical lens."
#     ),
#     schema={
#         "type": "object",
#         "properties": {"input": _INPUT_TEXT},
#         "required": ["input"],
#     },
#     func=management_analysis,
# )
# 
# # --- Web search ---------------------------------------------------------------
# dmtr.register_tool(
#     "WebSearch",
#     description=(
#         "Run a web search via the engine specified in args.engine "
#         "('Perplexity' | 'OpenAI' | 'Google' | 'Claude'; default Perplexity). "
#         "Use when the question requires up-to-date information from the open web."
#     ),
#     schema={
#         "type": "object",
#         "properties": {
#             "input": _INPUT_TEXT,
#             "engine": {
#                 "type": "string",
#                 "enum": ["Perplexity", "OpenAI", "Google", "Claude"],
#                 "description": "Which web-search backend to use.",
#                 "default": "Perplexity",
#             },
#         },
#         "required": ["input"],
#     },
#     func=_websearch_dispatch,
# )
# 
# dmtr.register_tool(
#     "WebSearch_PerplexityAI",
#     description="Web search via Perplexity AI. Prefer the generic 'WebSearch' tool unless a specific engine is required.",
#     schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
#     func=WebSearch_PerplexityAI,
# )
# 
# dmtr.register_tool(
#     "WebSearch_OpenAI",
#     description="Web search via the OpenAI web_search tool. Prefer the generic 'WebSearch' tool unless a specific engine is required.",
#     schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
#     func=WebSearch_OpenAI,
# )
# 
# dmtr.register_tool(
#     "WebSearch_Google",
#     description="Web search via Google Grounding Search (Gemini). Prefer the generic 'WebSearch' tool unless a specific engine is required.",
#     schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
#     func=WebSearch_Google,
# )
# 
# dmtr.register_tool(
#     "WebSearch_Claude",
#     description="Web search via the Anthropic Claude server-side web_search tool. Prefer the generic 'WebSearch' tool unless a specific engine is required.",
#     schema={"type": "object", "properties": {"input": _INPUT_TEXT}, "required": ["input"]},
#     func=WebSearch_Claude,
# )


def pick_tools(agent, user_query, allowed_names=None, situation_prompt="", memories=None):
    """Engine-agnostic tool picker.

    Builds a single LLM call (via the agent's own ENGINE.LLM) whose system prompt
    advertises the available tools as JSON Schema. The LLM replies with a
    `{"tool_calls":[...]}` JSON object, which is parsed back into a list of
    {name, args} dicts. Works on any provider supported by DigiM_FoundationModel.

    Returns: (tool_calls, raw_response, model_name, prompt_tokens, response_tokens)
    """
    if memories is None:
        memories = []

    # 1. Resolve the candidate tool list (Agent SKILL.TOOL_LIST narrows the registry)
    if allowed_names is None:
        skill = getattr(agent, "skill", {}) or {}
        allowed_names = skill.get("TOOL_LIST")
    tools = dmtr.list_tools(allowed_names)

    # 2. Compose the prompt: tools advert + user query
    tools_block = dmtr.render_tools_for_prompt(tools)
    prompt = f"{tools_block}\n\n[User query]\n{user_query}\n{situation_prompt}".strip()

    # 3. Run the agent's LLM (whatever provider it's configured with)
    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]
    response = ""
    for _prompt, response_chunk, _completion in agent.generate_response(
        model_type, prompt, memories, stream_mode=False
    ):
        if response_chunk:
            response += response_chunk

    # 4. Parse and return
    tool_calls = dmtr.parse_tool_calls(response)
    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)
    return tool_calls, response, model_name, prompt_tokens, response_tokens


# ---------------------------------------------------------------------------
# Tool plugin auto-loader
# ---------------------------------------------------------------------------
# Every *.py file under TOOL_FOLDER (default: user/common/tool/) is loaded as
# an independent plugin at import time. Plugins are expected to call
# `DigiM_ToolRegistry.register_tool(...)` at module level to expose their
# tools. One bad plugin only loses itself — others continue to load.
#
# Files starting with '_' (e.g. _helpers.py) are skipped, so plugins can
# share private helper modules without exposing them as tools.

def _load_tool_plugins(folder_path=None):
    """Discover and load tool plugin .py files from `folder_path` and its
    `local/` subfolder.

    Two scan locations:
      1. `<folder>/*.py`        — the standard plugins shipped with the repo
                                  (tracked in git)
      2. `<folder>/local/*.py`  — user-authored / site-local plugins
                                  (ignored by git via .gitignore so they are
                                  never accidentally pushed). Loaded AFTER the
                                  standard plugins, so a local plugin can
                                  override a same-named standard tool simply
                                  by registering it again — the registry
                                  treats re-registration as an update.

    Returns a list of (filename, status, error?) tuples — status is
    'loaded' on success or 'failed' on error. The folders are created if
    they don't exist so a fresh checkout works on first run.

    Plugins are also registered in sys.modules under
    'digim_tool_plugin__<stem>' (or 'digim_tool_plugin__local__<stem>' for
    local plugins) so the __getattr__ shim below can resolve module-level
    names (e.g. WEB_SEARCH_ENGINES) that legacy callers reference via
    `dmt.<name>`.
    """
    import importlib.util
    import logging
    import sys
    from pathlib import Path

    log = logging.getLogger(__name__)
    folder = Path(folder_path or tool_folder_path)
    folder.mkdir(parents=True, exist_ok=True)
    local_folder = folder / "local"
    local_folder.mkdir(parents=True, exist_ok=True)

    def _load_one(py_file, mod_name):
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module  # register before exec so the plugin can import itself
            spec.loader.exec_module(module)
            log.info(f"Loaded tool plugin: {py_file.name}")
            return (py_file.name, "loaded", None)
        except Exception as e:
            sys.modules.pop(mod_name, None)  # clean up the partially-initialised module
            log.exception(f"Failed to load tool plugin {py_file.name}: {e}")
            return (py_file.name, "failed", str(e))

    results = []
    # 1) Standard plugins (top-level files only; subfolders handled below).
    for py_file in sorted(folder.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        results.append(_load_one(py_file, f"digim_tool_plugin__{py_file.stem}"))
    # 2) Local plugins — loaded LAST so they win on registry name collision.
    for py_file in sorted(local_folder.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        results.append(_load_one(py_file, f"digim_tool_plugin__local__{py_file.stem}"))
    return results


# Run the loader at import time. Stored on the module so callers can
# inspect what loaded (DigiM_Tool._LOADED_PLUGINS).
_LOADED_PLUGINS = _load_tool_plugins()


# ---------------------------------------------------------------------------
# Backward-compat: PEP 562 module-level __getattr__
# ---------------------------------------------------------------------------
# When a tool definition moves out of this file into a user/common/tool/
# plugin, legacy callers that still do `import DigiM_Tool as dmt` and then
# `dmt.<tool_name>(...)` would normally break with AttributeError. This
# shim resolves any unknown attribute against the tool registry so those
# callers keep working without edits during the migration.
#
# Note: Python only consults __getattr__ when the name is NOT already in
# the module's __dict__, so existing module-level defs in this file still
# take precedence and shadow the registry lookup — the shim only activates
# once the original def is removed/commented out.
def __getattr__(name):
    # 1. Tool registry — covers `dmt.<tool_name>` for migrated tools.
    entry = dmtr.get_tool(name)
    if entry and entry.get("func"):
        return entry["func"]
    # 2. Plugin module namespaces — covers module-level constants/dicts
    #    (e.g. WEB_SEARCH_ENGINES) that legacy callers reference via
    #    `dmt.<name>`. Walks plugins in load order (alphabetical) and
    #    returns the first match.
    import sys as _sys
    for plugin_filename, status, _ in _LOADED_PLUGINS:
        if status != "loaded":
            continue
        mod_name = f"digim_tool_plugin__{plugin_filename.rsplit('.', 1)[0]}"
        mod = _sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, name):
            return getattr(mod, name)
    raise AttributeError(f"module 'DigiM_Tool' has no attribute {name!r}")

