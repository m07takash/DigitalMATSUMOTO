import os
from dotenv import load_dotenv
import DigiM_Util as dmu
import DigiM_FoundationModel as dmfm
import DigiM_Context as dmc

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
charactor_folder_path = os.getenv("CHARACTOR_FOLDER")
mst_folder_path = os.getenv("MST_FOLDER")
agent_folder_path = os.getenv("AGENT_FOLDER")
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
            agents.append({"AGENT": agent_data["NAME"], "FILE": agent_file})
    return agents

# 通常LLMエージェントのプロパティを設定
def set_normal_agent(agent):
    overwrite_items = {}
    overwrite_items["NAME"] = "ノーマルLLM"
    overwrite_items["ACT"] = "通常のチャットアシスタント"
    overwrite_items["PERSONALITY"] = {}
    overwrite_items["HABIT"] = {}
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
        agent_data = dmu.read_json_file(agent_file)
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
        self.system_prompt = self.set_system_prompt()

    # システムプロンプトの設定
    def set_system_prompt(self):
        system_prompt = f"あなたの名前は「{self.name}」です。{self.act}として振る舞ってください。"
        
        # パーソナリティ
        if self.personality:
            system_prompt += f"\n性別:{self.personality['SEX']}" if self.personality['SEX'] else ""
            system_prompt += f"\n誕生日:{self.personality['BIRTHDAY']}" if self.personality['BIRTHDAY'] else ""
            system_prompt += "\n存命: " + "Yes" if self.personality['IS_ALIVE'] else "No"
            system_prompt += f"\n国籍:{self.personality['NATIONALITY']}" if self.personality['NATIONALITY'] else ""
            if self.personality['BIG5']:
                system_prompt += f"\nビックファイブ:[Openness:{self.personality['BIG5']['Openness']*100:.2f}%, Conscientiousness:{self.personality['BIG5']['Conscientiousness']*100:.2f}%, Extraversion:{self.personality['BIG5']['Extraversion']*100:.2f}%, Agreeableness:{self.personality['BIG5']['Agreeableness']*100:.2f}%, Neuroticism:{self.personality['BIG5']['Neuroticism']*100:.2f}%]"

            # 口調
            system_prompt += f"\n使用する言語: {self.personality['LANGUAGE']}" if self.personality['LANGUAGE'] else "" 
            if self.personality['SPEAKING_STYLE']:
                prompt_temps_json = dmu.read_json_file(prompt_temp_mst_path)
                speaking_style = prompt_temps_json['SPEAKING_STYLE'][self.personality['SPEAKING_STYLE']]
                system_prompt += f"\n口調:{speaking_style}"
    
            # キャラクター設定
            charactor = self.personality["CHARACTOR"]
            if charactor:
                if charactor.strip().endswith(".txt"):
                    charactor = dmu.read_text_file(charactor, charactor_folder_path)
                system_prompt = system_prompt + f"\n\nあなたのキャラクター設定:\n{charactor}"

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
    def set_knowledge_context(self, query):
        context, knowledge_selected, query_vec = dmc.create_rag_context(query, self.knowledge)
        return context, knowledge_selected, query_vec

    # LLMの実行
    def generate_response(self, type, query, memories=[], image_paths={}):
        response, completion, prompt_tokens, response_tokens = dmfm.call_function_by_name(self.agent["ENGINE"][type]["FUNC_NAME"], query, self.system_prompt, self.agent["ENGINE"][type], memories, image_paths, self.skill)
        return response, completion, prompt_tokens, response_tokens 

    # クエリに含まれているコマンド(MAGIC_WORD)でエージェントモードを変更【マジックワードはタスクに移行】
    def set_practice_by_command(self, query):
        habit = "DEFAULT"
        for k, v in self.agent["HABIT"].items():
            magic_words = v.get("MAGIC_WORDS", [])
            if any(word in query for word in magic_words if word):
                habit = k
        return habit

