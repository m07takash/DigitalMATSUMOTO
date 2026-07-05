import os
import copy
from pathlib import Path
from dotenv import load_dotenv
import DigiM_Util as dmu
import DigiM_FoundationModel as dmfm
import DigiM_Context as dmc

# Load folder paths and other settings from setting.yaml
system_setting_dict = dmu.read_yaml_file("setting.yaml")
character_folder_path = system_setting_dict["CHARACTER_FOLDER"]
mst_folder_path = system_setting_dict["MST_FOLDER"]
agent_folder_path = system_setting_dict["AGENT_FOLDER"]

# Load system.env and set environment variables
if os.path.exists("system.env"):
    load_dotenv("system.env")
prompt_template_mst_file = os.getenv("PROMPT_TEMPLATE_MST_FILE")
prompt_temp_mst_path = str(Path(mst_folder_path) / prompt_template_mst_file)

# Agent JSON cache (file path -> data)
_agent_cache = {}

def _read_agent_json(agent_file):
    """Load the agent JSON with caching (return a deep copy so caller mutations do not pollute the cache)."""
    # Guard against empty / whitespace-only agent_file: `Path(folder) / ""`
    # yields the folder path itself, which passes `os.path.exists` (it's a
    # real directory) — but subsequent open() would raise IsADirectoryError.
    # Convert that to a clean FileNotFoundError so callers can handle it
    # uniformly.
    if not agent_file or not str(agent_file).strip():
        raise FileNotFoundError("Agent file name is empty")
    path = str(Path(agent_folder_path) / agent_file)
    if not os.path.exists(path) or os.path.isdir(path):
        raise FileNotFoundError(f"Agent file not found: {path}")
    mtime = os.path.getmtime(path)
    cached = _agent_cache.get(agent_file)
    if cached and cached[0] == mtime:
        return copy.deepcopy(cached[1])
    data = dmu.read_json_file(agent_file, agent_folder_path)
    _agent_cache[agent_file] = (mtime, data)
    return copy.deepcopy(data)

# Get the list of all agents
def get_all_agents():
    agent_files = dmu.get_files(agent_folder_path, ".json")
    agents = []
    for agent_file in agent_files:
        agent_data = _read_agent_json(agent_file)
        agents.append({"AGENT": agent_data["NAME"], "FILE": agent_file})
    return agents

# Get the list of agents the user can select.
# group_cd is one string or a list of strings; when a list, agents are matched by OR.
def get_display_agents(group_cd="All"):
    if isinstance(group_cd, str):
        user_groups = [group_cd] if group_cd else []
    else:
        user_groups = [g for g in (group_cd or []) if g]
    has_all_or_admin = any(g in ("All", "Admin") for g in user_groups)

    agent_files = dmu.get_files(agent_folder_path, ".json")
    agents = []
    for agent_file in agent_files:
        agent_data = _read_agent_json(agent_file)
        if not agent_data.get("DISPLAY"):
            continue
        if "GROUP" not in agent_data:
            agents.append({"AGENT": agent_data["DISPLAY_NAME"], "FILE": agent_file})
            continue
        if has_all_or_admin:
            agents.append({"AGENT": agent_data["DISPLAY_NAME"], "FILE": agent_file})
            continue
        # OR match: any of the user's groups being in the agent's GROUP makes it selectable
        if any(g in agent_data["GROUP"] for g in user_groups):
            agents.append({"AGENT": agent_data["DISPLAY_NAME"], "FILE": agent_file})
    return agents

# Get the list of engines an agent has (model names under LLM; takes raw JSON data)
def get_engine_list(agent_data, model_type="LLM"):
    engine_config = agent_data.get("ENGINE", {}).get(model_type, {})
    return [k for k in engine_config if k != "DEFAULT" and isinstance(engine_config.get(k), dict)]

# Set the properties of the LLM agent
def get_agent_item(agent_file, item):
    agent_data = _read_agent_json(agent_file)
    return agent_data[item]

# Set the properties of the LLM agent
def set_normal_agent(agent):
    overwrite_items = {}
    overwrite_items["NAME"] = "AI"
    overwrite_items["ACT"] = "Chat with User"
    overwrite_items["PERSONALITY"] = ""
    overwrite_items["HABIT"] = ""
    overwrite_items["KNOWLEDGE"] = []
    overwrite_items["SKILL"] = {
        "TOOL_LIST": [
            {"type": "function", "function": {"name": "default_tool"}}
        ],
        "CHOICE": "none"
    }
    dmu.update_dict(agent.agent, overwrite_items)
    agent.set_property(agent.agent)

# Execute the vanilla LLM
def generate_pureLLM(base_agent, query, memories_selected=[], prompt_temp_cd="No Template"):
    agent = base_agent

    model_type = "LLM"
    model_name = agent.agent["ENGINE"][model_type]["MODEL"]
    tokenizer = agent.agent["ENGINE"][model_type]["TOKENIZER"]

    # Apply normal-LLM configuration
    set_normal_agent(agent)

    # Resolve the prompt template assigned to the agent
    prompt_template = agent.set_prompt_template(prompt_temp_cd)

    # Set up the prompt
    prompt = f'{prompt_template}{query}'

    # Execute the LLM
    response = ""
    for prompt, response_chunk, completion in agent.generate_response(model_type, prompt, memories_selected):
        if response_chunk:
            response += response_chunk

    prompt_tokens = dmu.count_token(tokenizer, model_name, prompt)
    response_tokens = dmu.count_token(tokenizer, model_name, response)

    return response, model_name, prompt_tokens, response_tokens

# Execute the vanilla LLM (external call)
def ext_generate_pureLLM(agent_file, query, memories_selected=[], prompt_temp_cd="No Template"):
    base_agent = DigiM_Agent(agent_file)
    response, model_name, prompt_tokens, response_tokens = generate_pureLLM(base_agent, query, memories_selected=[], prompt_temp_cd=prompt_temp_cd)
    return response, model_name, prompt_tokens, response_tokens

# Override agent data from a persona dict (returned by DigiM_AgentPersona.load_personas).
# Overridden: NAME / ACT / PERSONALITY (including character_text/character_file) / HABIT (filter) / KNOWLEDGE (filter) / DEFINE_CODE
# Immutable:  ENGINE / SUPPORT_AGENT / BOOK / SKILL / FEEDBACK / GROUP / ORG / PERSONA_FILES
def _apply_persona(agent_data, persona):
    if not persona:
        return agent_data

    if persona.get("name"):
        agent_data["NAME"] = persona["name"]
    if persona.get("act"):
        agent_data["ACT"] = persona["act"]

    # PERSONALITY: replace entirely with persona.personality. CHARACTER priority is character_file > character_text > CHARACTER inside personality
    if persona.get("personality"):
        new_personality = dict(persona["personality"])
    else:
        new_personality = dict(agent_data.get("PERSONALITY") or {})
    if persona.get("character_file"):
        new_personality["CHARACTER"] = persona["character_file"]
    elif persona.get("character_text"):
        new_personality["CHARACTER"] = persona["character_text"]
    agent_data["PERSONALITY"] = new_personality

    # HABIT: pass through when ["ALL"]; otherwise treat as a whitelist
    habits_filter = persona.get("habits") or ["ALL"]
    if "ALL" not in habits_filter:
        habit_dict = agent_data.get("HABIT") or {}
        agent_data["HABIT"] = {k: v for k, v in habit_dict.items() if k in habits_filter}

    # KNOWLEDGE: pass through when ["ALL"]; otherwise filter by RAG_NAME
    knowledge_filter = persona.get("knowledge") or ["ALL"]
    if "ALL" not in knowledge_filter:
        knowledge_list = agent_data.get("KNOWLEDGE") or []
        agent_data["KNOWLEDGE"] = [k for k in knowledge_list
                                    if k.get("RAG_NAME") in knowledge_filter]

    # DEFINE_CODE: full replacement (an explicit empty dict on the persona side is allowed)
    if persona.get("define_code") is not None:
        agent_data["DEFINE_CODE"] = persona["define_code"]

    return agent_data


# Agent
class DigiM_Agent:
    def __init__(self, agent_file, persona=None):
        agent_data = _read_agent_json(agent_file)
        if persona:
            agent_data = _apply_persona(agent_data, persona)
            self.persona_id = persona.get("persona_id", "")
            self.persona_name = persona.get("name", "")
        else:
            self.persona_id = ""
            self.persona_name = ""
        self.set_property(agent_data)

    # Configure the agent properties
    def set_property(self, agent_data):
        self.agent = agent_data
        # Resolve the nested ENGINE structure: ENGINE.LLM.DEFAULT="GPT" -> ENGINE.LLM = the flat GPT config (clean)
        # Named model configs are kept separately in self._engine_named_configs (so chat_memory.json stays clean)
        self._engine_named_configs = {}
        for model_type in list(self.agent.get("ENGINE", {}).keys()):
            config = self.agent["ENGINE"][model_type]
            if not isinstance(config, dict):
                continue
            # If FUNC_NAME is present directly, the config is already flat (avoid double resolution)
            if "FUNC_NAME" in config:
                continue
            named_configs = {k: v for k, v in config.items() if k != "DEFAULT" and isinstance(v, dict)}
            if not named_configs:
                continue
            # Use the DEFAULT-specified model if provided; otherwise pick the first one
            default_name = config.get("DEFAULT") if isinstance(config.get("DEFAULT"), str) else next(iter(named_configs))
            if default_name in named_configs:
                self.agent["ENGINE"][model_type] = dict(named_configs[default_name])
                self._engine_named_configs[model_type] = named_configs
        self.name = self.agent['NAME']
        self.act = self.agent['ACT']
        self.personality = self.agent['PERSONALITY']
        self.habit = self.agent['HABIT']
        self.knowledge = self.agent["KNOWLEDGE"]
        self.skill = self.agent["SKILL"]
        self.feedback = self.agent["FEEDBACK"]
        self.support_agent = self.agent["SUPPORT_AGENT"]
        self.define_code = self.agent["DEFINE_CODE"] if "DEFINE_CODE" in self.agent else {}
        self.book = self.agent["BOOK"] if "BOOK" in self.agent else []
        self.system_prompt = self.set_system_prompt()

    # Build the system prompt
    def set_system_prompt(self):
        system_prompt = ""
        if self.name:
            system_prompt += f"あなたの名前は「{self.name}」です。"
        if self.act:
            system_prompt += f"{self.act}として振る舞ってください。"

        # Personality
        if self.personality:
            if 'SEX' in self.personality:
                system_prompt += f"\n性別:{self.personality['SEX']}" if self.personality['SEX'] else ""
            if 'BIRTHDAY' in self.personality:
                system_prompt += f"\n誕生日:{self.personality['BIRTHDAY']}" if self.personality['BIRTHDAY'] else ""
            if 'IS_ALIVE' in self.personality:
                system_prompt += "\n存命: " + "Yes" if self.personality['IS_ALIVE'] else "No"
            if 'NATIONALITY' in self.personality:
                system_prompt += f"\n国籍:{self.personality['NATIONALITY']}" if self.personality['NATIONALITY'] else ""
            if 'BIG5' in self.personality:
                if self.personality['BIG5']:
                    system_prompt += f"\nビックファイブ:[Openness:{self.personality['BIG5']['Openness']*100:.2f}%, Conscientiousness:{self.personality['BIG5']['Conscientiousness']*100:.2f}%, Extraversion:{self.personality['BIG5']['Extraversion']*100:.2f}%, Agreeableness:{self.personality['BIG5']['Agreeableness']*100:.2f}%, Neuroticism:{self.personality['BIG5']['Neuroticism']*100:.2f}%]"

            # Speaking style
            if 'LANGUAGE' in self.personality:
                system_prompt += f"\n使用する言語: {self.personality['LANGUAGE']}" if self.personality['LANGUAGE'] else ""
            if 'SPEAKING_STYLE' in self.personality:
                if self.personality['SPEAKING_STYLE']:
                    prompt_temps_json = dmu.read_json_file(prompt_temp_mst_path)
                    speaking_style = prompt_temps_json['SPEAKING_STYLE'][self.personality['SPEAKING_STYLE']]
                    system_prompt += f"\n口調:{speaking_style}"

            # Character profile
            if 'CHARACTER' in self.personality:
                character = self.personality["CHARACTER"]
                if character:
                    _ch = character.strip().lower()
                    if _ch.endswith(".txt") or _ch.endswith(".md"):
                        character = dmu.read_text_file(character.strip(), character_folder_path)
                    system_prompt += f"\n\nあなたのキャラクター設定:\n{character}"

        return system_prompt

    # Build the contents context
    def set_contents_context(self, seq, sub_seq, contents):
        context, records, image_files = dmc.create_contents_context(self.agent, contents, seq, sub_seq)
        return context, records, image_files

    # Fetch the prompt template
    def set_prompt_template(self, prompt_temp_cd):
        prompt_template = dmc.set_prompt_template(prompt_temp_cd)
        return prompt_template

    # Build the knowledge (RAG) context
    def set_knowledge_context(self, query, query_vecs=[], exec_info={}, meta_searches=[], private_mode=False):
        knowledge_context, knowledge_selected = dmc.create_rag_context(query, query_vecs=query_vecs, rags=self.knowledge, exec_info=exec_info, meta_searches=meta_searches, define_code=self.define_code, private_mode=private_mode)
        return knowledge_context, knowledge_selected

    # Execute the LLM
    def generate_response(self, model_type, query, memories=[], image_paths={}, stream_mode=True):
        for prompt, response, completion in dmfm.call_function_by_name(self.agent["ENGINE"][model_type]["FUNC_NAME"], query, self.system_prompt, self.agent["ENGINE"][model_type], memories, image_paths, self.skill, stream_mode):
            yield prompt, response, completion

    # Execute the vanilla LLM (no persona)
    def generate_pureLLM(self, query, memories=[], prompt_temp_cd="No Template"):
        response, model_name, prompt_tokens, response_tokens = generate_pureLLM(self.agent, query, memories, prompt_temp_cd)
        return response, model_name, prompt_tokens, response_tokens

    # Switch the agent's mode based on commands (MAGIC_WORD) in the query [magic words are migrating to tasks]
    def set_practice_by_command(self, query):
        habit = "DEFAULT"
        for k, v in self.agent["HABIT"].items():
            magic_words = v.get("MAGIC_WORDS", [])
            if any(word in query for word in magic_words if word):
                habit = k
        return habit
