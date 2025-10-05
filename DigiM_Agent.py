import os
from dotenv import load_dotenv
import DigiM_Util as dmu
import DigiM_FoundationModel as dmfm
import DigiM_Context as dmc

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
character_folder_path = system_setting_dict["CHARACTER_FOLDER"]
mst_folder_path = system_setting_dict["MST_FOLDER"]
agent_folder_path = system_setting_dict["AGENT_FOLDER"]

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
prompt_template_mst_file = os.getenv("PROMPT_TEMPLATE_MST_FILE")
prompt_temp_mst_path = mst_folder_path + prompt_template_mst_file

# エージェント一覧の取得
def get_all_agents():
    agent_files = dmu.get_files(agent_folder_path, ".json")
    agents = []
    for agent_file in agent_files:
        agent_data = dmu.read_json_file(agent_file, agent_folder_path)
        agents.append({"AGENT": agent_data["NAME"], "FILE": agent_file})
    return agents

# 選択可能なエージェント一覧の取得
def get_display_agents():
    agent_files = dmu.get_files(agent_folder_path, ".json")
    agents = []
    for agent_file in agent_files:
        agent_data = dmu.read_json_file(agent_file, agent_folder_path)
        if agent_data["DISPLAY"]:
            agents.append({"AGENT": agent_data["DISPLAY_NAME"], "FILE": agent_file})
    return agents

# LLMエージェントのプロパティを設定
def get_agent_item(agent_file, item):
    agent_data = dmu.read_json_file(agent_folder_path+agent_file)
    item_value = agent_data[item]
    return item_value

# LLMエージェントのプロパティを設定
def set_normal_agent(agent):
    overwrite_items = {}
    overwrite_items["NAME"] = "ノーマルLLM"
    overwrite_items["ACT"] = "通常のチャットアシスタント"
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

# Agent
class DigiM_Agent:
    def __init__(self, agent_file):
        agent_data = dmu.read_json_file(agent_folder_path+agent_file)
        self.set_property(agent_data)

    # エージェントのプロパティの設定
    def set_property(self, agent_data):
        self.agent = agent_data
        self.name = self.agent['NAME']
        self.act = self.agent['ACT']
        self.personality = self.agent['PERSONALITY']
        self.habit = self.agent['HABIT']
        self.knowledge = self.agent["KNOWLEDGE"]
        self.skill = self.agent["SKILL"]
        self.communication = self.agent["COMMUNICATION"]
        self.support_agent = self.agent["SUPPORT_AGENT"]
        self.system_prompt = self.set_system_prompt()

    # システムプロンプトの設定
    def set_system_prompt(self):
        system_prompt = ""
        if self.name:
            system_prompt += f"あなたの名前は「{self.name}」です。"
        if self.act:
            system_prompt += f"{self.act}として振る舞ってください。"
        
        # パーソナリティ
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

            # 口調
            if 'LANGUAGE' in self.personality:
                system_prompt += f"\n使用する言語: {self.personality['LANGUAGE']}" if self.personality['LANGUAGE'] else "" 
            if 'SPEAKING_STYLE' in self.personality:
                if self.personality['SPEAKING_STYLE']:
                    prompt_temps_json = dmu.read_json_file(prompt_temp_mst_path)
                    speaking_style = prompt_temps_json['SPEAKING_STYLE'][self.personality['SPEAKING_STYLE']]
                    system_prompt += f"\n口調:{speaking_style}"
    
            # キャラクター設定
            if 'CHARACTER' in self.personality:
                character = self.personality["CHARACTER"]
                if character:
                    if character.strip().endswith(".txt"):
                        character = dmu.read_text_file(character, character_folder_path)
                    system_prompt += f"\n\nあなたのキャラクター設定:\n{character}"

        return system_prompt
    
    # コンテンツコンテキストの生成
    def set_contents_context(self, seq, sub_seq, contents):
        context, records, image_files = dmc.create_contents_context(self.agent, contents, seq, sub_seq)
        return context, records, image_files
        
    # プロンプトテンプレートの取得
    def set_prompt_template(self, prompt_temp_cd):
        prompt_template = dmc.set_prompt_template(prompt_temp_cd)
        return prompt_template
    
    # ナレッジコンテキスト(RAG)の生成
    def set_knowledge_context(self, query, query_vecs=[], exec_info={}, meta_searches=[]):
        knowledge_context, knowledge_selected = dmc.create_rag_context(query, query_vecs=query_vecs, rags=self.knowledge, exec_info=exec_info, meta_searches=meta_searches)
        return knowledge_context, knowledge_selected

    # LLMの実行
    def generate_response(self, model_type, query, memories=[], image_paths={}, stream_mode=True):
        for prompt, response, completion in dmfm.call_function_by_name(self.agent["ENGINE"][model_type]["FUNC_NAME"], query, self.system_prompt, self.agent["ENGINE"][model_type], memories, image_paths, self.skill, stream_mode):
            yield prompt, response, completion

    # クエリに含まれているコマンド(MAGIC_WORD)でエージェントモードを変更【マジックワードはタスクに移行】
    def set_practice_by_command(self, query):
        habit = "DEFAULT"
        for k, v in self.agent["HABIT"].items():
            magic_words = v.get("MAGIC_WORDS", [])
            if any(word in query for word in magic_words if word):
                habit = k
        return habit
