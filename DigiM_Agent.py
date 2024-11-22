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

# エージェント一覧の取得
def get_all_agents():
    agent_files = dmu.get_files(agent_folder_path, ".json")
    agents = []
    for agent_file in agent_files:
        agent_data = dmu.read_json_file(agent_file, agent_folder_path)
        agents.append({"AGENT": agent_data["AGENT"], "FILE": agent_file})
    return agents

# Agent
class DigiM_Agent:
    def __init__(self, agent_data, mode):
        self.agent_data = agent_data
        self.agent_mode = mode
        self.agent = agent_data["MODE"][mode]
        self.name = self.agent["NAME"]
        self.act = self.agent["ACT"]
        self.charactor = self.agent["CHARACTOR"]
        self.system_prompt = self.set_system_prompt()

    # システムプロンプトの設定
    def set_system_prompt(self):
        if self.charactor.strip().endswith(".txt"):
            charactor_text = dmu.read_text_file(self.charactor, charactor_folder_path)
        else:
            charactor_text = self.charactor
        system_prompt = f"あなたの名前は「{self.name}」です。{self.act}として振る舞ってください。"
        if charactor_text:
            system_prompt = system_prompt + f"\n\n【あなたのキャラクター設定】\n{charactor_text}\n\n"
        return system_prompt

    # クエリに含まれているコマンド(MAGIC_WORD)でエージェントモードを変更
    def set_agent_mode_by_command(self, query):
        for mode, settings in self.agent_data["MODE"].items():
            magic_words = settings.get("MAGIC_WORDS", [])
            if any(word in query for word in magic_words if word):
                return mode
        return self.agent_mode
    
    # コンテンツコンテキストの生成
    def set_contents_context(self, seq, sub_seq, contents):
        context, records, image_files = dmc.create_contents_context(self.agent_data, contents, seq, sub_seq)
        return context, records, image_files
    
    # RAGコンテキストの生成
    def set_rag_context(self, query):
        rags = self.agent["RAG"]
        context, rag_selected, query_vec = dmc.create_rag_context(query, rags)
        return context, rag_selected, query_vec
        
    # プロンプトテンプレートの生成
    def set_prompt_template(self):
        # エージェントに設定されるプロンプトテンプレートを設定
        prompt_format_cd = self.agent["PROMPT_TEMPLATE"]["PROMPT_FORMAT"]
        writing_style_cd = self.agent["PROMPT_TEMPLATE"]["WRITING_STYLE"]

        # プロンプトテンプレートの取得
        prompt_temp_mst_path = mst_folder_path + prompt_template_mst_file
        prompt_temps_json = dmu.read_json_file(prompt_temp_mst_path)
        prompt_format = prompt_temps_json["PROMPT_FORMAT"][prompt_format_cd]
        writing_style = prompt_temps_json["WRITING_STYLE"][writing_style_cd]

        # プロンプトテンプレートの生成
        prompt_template = ""
        if prompt_format:
            prompt_template = prompt_template + prompt_format +"\n"
        if writing_style:
            prompt_template = prompt_template + writing_style +"\n"
        
        return prompt_template

    # LLMの実行
    def generate_response(self, query, memories=[], image_paths={}):
        response, completion, prompt_tokens, response_tokens = dmfm.call_function_by_name(self.agent["MODEL"]["FUNC_NAME"], query, self.system_prompt, self.agent["MODEL"], memories, image_paths, self.agent["TOOL"])
        return response, completion, prompt_tokens, response_tokens 
