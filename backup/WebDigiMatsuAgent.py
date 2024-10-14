import os
import json
import math
import time
import tempfile
import unicodedata
import datetime
from datetime import datetime, timedelta
import streamlit as st
import DigiMatsuEngine as digim_eng
import DigiMatsuInsightNotion as digim_insight_notion

# 文字列の切り取り
def cut_string(s, limit):
    count = 0  # 文字数のカウント
    for i, char in enumerate(s):
        # 2バイト文字の場合は2を加算、そうでなければ1を加算
        count += 2 if unicodedata.east_asian_width(char) in ('F', 'W', 'A') else 1
        # カウントが達したら、その位置で文字列を切り取って返す
        if count > limit:
            return s[:i]
    # ループが終了してもカウントが達しない場合は、全文字列を返す
    return s

# 末尾スラッシュの切り取り（新規インスタンスフォルダ作成用）
def remove_slash_mkdir(s):
    return s[:-1] if s.endswith('/') else s

# 文字列がリスト内に存在するかの検証
def str_in_list(target, string_list, default_str=""):
    if default_str=="":
        default_str=string_list[0]
    if target in string_list:
        return target
    else:
        return default_str

# 環境設定を読み込む
def load_json_data(path, file):
    with open(path+file, 'r') as f:
        json_data = json.load(f)
    return json_data

# インスタンスのリストを取得（サイドバーへの表示用）
def get_instance_list(target_folder, chat_setting_file):
    instance_list = []
    for root, dirs, files in os.walk(target_folder):
        for file_name in files:
            if file_name == chat_setting_file:
                json_file_path = os.path.join(root, file_name)
                # JSONファイルを読み込む
                with open(json_file_path, 'r') as json_file:
                    data = json.load(json_file)
                    for key, value in data.items():
                        instance_list.append([key, value.get("instance_name"), value.get("last_update_date"), value.get("setting")])
    return sorted(instance_list, key=lambda x: x[2], reverse=True)

# 新しいインスタンスIDを設定
def new_instance_id(instance_list):
    if instance_list:
        instance_id = str(int(max(instance_list, key=lambda x: int(x[0]))[0])+1)
    else:
        instance_id = "0"
    return instance_id

# インスタンスIDを元に設定情報を更新
def set_instance_items(user_id, instance_id, chat_setting_file):
    instance_path = user_id+"/instance_id"+instance_id+"/"
    instance_setting_file = instance_path+chat_setting_file
    return instance_path, instance_setting_file

# デフォルト値の設定
def set_default_items(setting):
    personas = list(setting["PERSONAS"].keys())
    memory_formats = list(setting["MEMORY"]["FORMATS"].keys())
    memory_agents = setting["MEMORY"]["AGENTS"]
    memory_loaders = setting["MEMORY"]["LOADERS"]
    distance_logics = setting["DISTANCE_LOGICS"]
    chunk_setting = setting["NLP_CHUNK"]
    notion_setting = setting["NOTION"]    
    prompt_formats = list(setting["PROMPT_TEMPLATE"]["PROMPT_FORMAT"].keys())
    writing_styles = list(setting["PROMPT_TEMPLATE"]["WRITING_STYLE"].keys())
    rag_data_dict = setting["RAG"]["DATA"]
    rag_format_dict = setting["RAG"]["FORMAT"]
    rag_datasets = [key for key, value in rag_data_dict.items() if value.get('active') == 'Y']
    rag_formats = list(rag_format_dict.keys())
    models = list(setting["MODELS"].keys())
    st.session_state.default_instance_name = "New Chat"
    st.session_state.default_persona = personas[0] #"DigitalMATSUMOTO"
    st.session_state.default_memory_save = True
    st.session_state.default_memory_digest = True
    st.session_state.default_memory_use = True
    st.session_state.default_memory_format = memory_formats[0]
    st.session_state.default_memory_agent = memory_agents[0] #"BOTH"
    st.session_state.default_memory_loader = memory_loaders[0] #"LATEST"
    st.session_state.default_memory_text_limits = 7000
    st.session_state.default_memory_distance_logic = distance_logics[0] #"Cosine"
    st.session_state.default_overwrite = False
    st.session_state.default_prompt_format = prompt_formats[0]
    st.session_state.default_writing_style = writing_styles[0]
    st.session_state.default_model = models[0]
    st.session_state.default_rag_knowledge_datasets = rag_datasets
    st.session_state.default_rag_knowledge_format = rag_formats[0]
    st.session_state.default_rag_knowledge_text_limits = 10000
    st.session_state.default_rag_knowledge_distance_logic = distance_logics[0] #"Cosine"
    st.session_state.default_rag_policy_datasets = rag_datasets
    st.session_state.default_rag_policy_format = rag_formats[0]
    st.session_state.default_rag_policy_text_limits = 1000
    st.session_state.default_rag_policy_distance_logic = distance_logics[0] #"Cosine"

# セッションステートの初期化
def initialize_session_states():
    if 'sidebar_message' not in st.session_state:
        st.session_state.sidebar_message = ""
    if "instance_id" not in st.session_state:
        st.session_state.instance_id = ""
    if "instance_path" not in st.session_state:
        st.session_state.instance_path = ""
    if "instance_setting_file" not in st.session_state:
        st.session_state.instance_setting_file = ""
    if "instance_name" not in st.session_state:
        st.session_state.instance_name = st.session_state.default_instance_name
    if "persona" not in st.session_state:
        st.session_state.persona = st.session_state.default_persona
    if "memory_save" not in st.session_state:
        st.session_state.memory_save = st.session_state.default_memory_save
    if "memory_digest" not in st.session_state:
        st.session_state.memory_digest = st.session_state.default_memory_digest
    if "memory_use" not in st.session_state:
        st.session_state.memory_use = st.session_state.default_memory_use
    if "memory_format" not in st.session_state:
        st.session_state.memory_format = st.session_state.default_memory_format
    if "memory_agent" not in st.session_state:
        st.session_state.memory_agent = st.session_state.default_memory_agent
    if "memory_loader" not in st.session_state:
        st.session_state.memory_loader = st.session_state.default_memory_loader
    if "memory_text_limits" not in st.session_state:
        st.session_state.memory_text_limits = st.session_state.default_memory_text_limits
    if "memory_distance_logic" not in st.session_state:
        st.session_state.memory_distance_logic = st.session_state.default_memory_distance_logic
    if 'messages' not in st.session_state:
        st.session_state.messages = []
    if 'uploaded_files' not in st.session_state:
        st.session_state.uploaded_files = []
    if 'file_uploader' not in st.session_state:
        st.session_state.file_uploader = st.file_uploader
    if 'seq_memory' not in st.session_state:
        st.session_state.seq_memory = []
    if "overwrite" not in st.session_state:
        st.session_state.overwrite = st.session_state.default_overwrite
    if "prompt_format" not in st.session_state:
        st.session_state.prompt_format = st.session_state.default_prompt_format
    if "writing_style" not in st.session_state:
        st.session_state.writing_style = st.session_state.default_writing_style
    if "model" not in st.session_state:
        st.session_state.model = st.session_state.default_model
    if "rag_knowledge_datasets" not in st.session_state:
        st.session_state.rag_knowledge_datasets = st.session_state.default_rag_knowledge_datasets
    if "rag_knowledge_format" not in st.session_state:
        st.session_state.rag_knowledge_format = st.session_state.default_rag_knowledge_format
    if "rag_knowledge_text_limits" not in st.session_state:
        st.session_state.rag_knowledge_text_limits = st.session_state.default_rag_knowledge_text_limits
    if "rag_knowledge_distance_logic" not in st.session_state:
        st.session_state.rag_knowledge_distance_logic = st.session_state.default_rag_knowledge_distance_logic
    if "rag_policy_datasets" not in st.session_state:
        st.session_state.rag_policy_datasets = st.session_state.default_rag_policy_datasets
    if "rag_policy_format" not in st.session_state:
        st.session_state.rag_policy_format = st.session_state.default_rag_policy_format
    if "rag_policy_text_limits" not in st.session_state:
        st.session_state.rag_policy_text_limits = st.session_state.default_rag_policy_text_limits
    if "rag_policy_distance_logic" not in st.session_state:
        st.session_state.rag_policy_distance_logic = st.session_state.default_rag_policy_distance_logic
    if "seq" not in st.session_state:
        st.session_state.seq = 0

# インスタンス設定をJSONファイルに保存
def save_instance_sets(setting, instance_id, instance_setting_file, instance_name, persona, memory_save, memory_digest, memory_use, memory_format, memory_agent, memory_loader, memory_text_limits, memory_distance_logic, overwrite, prompt_format, writing_style, model, rag_knowledge_datasets, rag_knowledge_format, rag_knowledge_text_limits, rag_knowledge_distance_logic, rag_policy_datasets, rag_policy_format, rag_policy_text_limits, rag_policy_distance_logic):
    if os.path.exists(instance_setting_file):
        with open(instance_setting_file, 'r') as file:
            instance_sets_json = json.load(file)
            instance_create_date = instance_sets_json[instance_id]["create_date"]
    else:
        instance_sets_json = {}
        instance_create_date = str(datetime.now())

    instance_sets_json[instance_id] = {
        'instance_name': instance_name,
        'create_date': instance_create_date,
        'last_update_date': str(datetime.now()),
        'setting': {
            'persona': persona,
            'memory_save': memory_save,
            'memory_use': memory_use,
            'memory_digest': memory_digest,
            'memory_format': memory_format,
            'memory_agent': memory_agent,
            'memory_loader': memory_loader,
            'memory_text_limits': memory_text_limits,
            'memory_distance_logic': memory_distance_logic,
            'overwrite': overwrite,
            'prompt_format': prompt_format,
            'writing_style': writing_style,
            'model': model,
            'rag_knowledge_datasets': rag_knowledge_datasets,
            'rag_knowledge_format': rag_knowledge_format,
            'rag_knowledge_text_limits': rag_knowledge_text_limits,
            'rag_knowledge_distance_logic': rag_knowledge_distance_logic,
            'rag_policy_datasets': rag_policy_datasets,
            'rag_policy_format': rag_policy_format,
            'rag_policy_text_limits': rag_policy_text_limits,
            'rag_policy_distance_logic': rag_policy_distance_logic
        }
    }
    # JSONファイルにデータを保存（インスタンスIDが被っていれば上書き、被っていなければ追記）
    with open(instance_setting_file, "w") as json_file:
        json.dump(instance_sets_json, json_file, indent=4)

# アップロードしたファイルの表示
def show_uploaded_files_memory(file_path, file_name, file_type):
    uploaded_file = file_path+file_name
    if "text" in file_type:
        with open(uploaded_file, "r", encoding="utf-8") as f:
            text_content = f.read()
        st.text_area("TextFile:", text_content, height=20, key=file_name)
    elif "csv" in file_type:
        df = pd.read_csv(uploaded_file)
        st.dataframe(df)
    elif "excel" in file_type:
        df = pd.read_excel(uploaded_file)
        st.dataframe(df)
    elif "image" in file_type:
        st.image(uploaded_file)
    elif "video" in file_type:
        st.video(uploaded_file)
    elif "audio" in file_type:
        st.audio(uploaded_file)

# アップロードしたファイルの表示（複数でループ）
def show_uploaded_files_widget(uploaded_files):
    for uploaded_file in uploaded_files:
        file_type = uploaded_file.type
        if "text" in file_type:
            text_content = uploaded_file.read().decode("utf-8")
            st.text_area("TextFile:", text_content, height=20)
        elif "csv" in file_type:
            df = pd.read_csv(uploaded_file)
            st.dataframe(df)
        elif "excel" in file_type:
            df = pd.read_excel(uploaded_file)
            st.dataframe(df)
        elif "image" in file_type:
            st.image(uploaded_file)
        elif "video" in file_type:
            st.video(uploaded_file)
        elif "audio" in file_type:
            st.audio(uploaded_file)

# インスタンスをリフレッシュ
def instance_refresh(path, memory_file):
    st.session_state.messages = []
    with open(path+memory_file, 'r') as file:
        chat_history = json.load(file)
    for k, v_dict in chat_history.items():
        if v_dict["FLG"] == "Y":
            for key, value in v_dict.items():
                if key != "FLG":
                    if value["user"] in ["user","user_img","assistant","detail"]:
                        st.session_state.messages.append({"seq": k, "role": value["user"], "content": value["text"]}) 
                    elif value["user"] in ["uploaded_file","generate_file"]:
                        st.session_state.messages.append({"seq": k, "role": value["user"], "file_type": value["file_type"], "file_name": value["file_name"], "file_path": value["file_path"]}) 
    st.rerun()


### Streamlit画面 ###

#メイン処理
def main():
    user_id = "user"
    # 環境設定のファイルを読込
    common_path = f"{user_id}/common/env/"
    rag_file_path = f"{user_id}/common/rag/"
    setting_file = "setting_env.json"
    setting = load_json_data(common_path, setting_file)
    
    OPENAI_API_KEY = setting['LLM_API_KEYS']['OPENAI_API_KEY']
    GEMINI_API_KEY = setting['LLM_API_KEYS']['GEMINI_API_KEY']
    notion_setting = setting["NOTION"]
    chunk_setting = setting["NLP_CHUNK"]
    distance_logics = setting["DISTANCE_LOGICS"]
    memory_agents = setting["MEMORY"]["AGENTS"]
    memory_loaders = setting["MEMORY"]["LOADERS"]
    memory_formats = list(setting["MEMORY"]["FORMATS"].keys())

    models_dict = setting["MODELS"]
    models = list(models_dict.keys())
    AWS_KEY_dict = setting["AWS_KEYS"]
    
    personas = list(setting["PERSONAS"].keys())
    prompt_template_dict = setting["PROMPT_TEMPLATE"]
    prompt_formats = list(prompt_template_dict["PROMPT_FORMAT"].keys())
    writing_styles = list(prompt_template_dict["WRITING_STYLE"].keys())
    rag_data_dict = setting["RAG"]["DATA"]
    rag_format_dict = setting["RAG"]["FORMAT"]
    rag_datasets = [key for key, value in rag_data_dict.items() if value.get('active') == 'Y']
    rag_formats = list(rag_format_dict.keys())
    
    # デフォルト値の設定
    set_default_items(setting)

    # セッションステートを初期化
    initialize_session_states()
    
    # インスタンスのリストを取得
    chat_setting_file = "chat_settings.json"
    memory_file = "chat_memory.json"
    instance_list = get_instance_list(user_id, chat_setting_file)
    
    # サイドバーの設定
    with st.sidebar:
        st.title("Digital MATSUMOTO")
        st.markdown("")
        expander = st.expander("Connection Setting(API Key):")
        with expander:
            openai_api_key = st.text_input("OpenAI API Key", value=OPENAI_API_KEY, key="openai_api_key", type="password")
            st.markdown("[Get an OpenAI API key](https://platform.openai.com/account/api-keys)")
            gemini_api_key = st.text_input("Gemini API Key", value=GEMINI_API_KEY, key="gemini_api_key", type="password")
            st.markdown("[Get a Gemini API key](https://exchange.gemini.com/register)")
        if st.button("Create New Chat", key="create_chat"):
            st.session_state.instance_id = ""
            st.session_state.instance_path = ""
            st.session_state.instance_setting_file = ""
            st.session_state.instance_name = "New Chat Instance"
            st.session_state.persona = st.session_state.default_persona
            st.session_state.memory_save = st.session_state.default_memory_save
            st.session_state.memory_use = st.session_state.default_memory_use
            st.session_state.memory_digest = st.session_state.default_memory_digest
            st.session_state.memory_format = st.session_state.default_memory_format
            st.session_state.memory_agent = st.session_state.default_memory_agent
            st.session_state.memory_loader = st.session_state.default_memory_loader
            st.session_state.memory_text_limits = st.session_state.default_memory_text_limits
            st.session_state.memory_distance_logic = st.session_state.default_memory_distance_logic
            st.session_state.overwrite = st.session_state.default_overwrite
            st.session_state.prompt_format = st.session_state.default_prompt_format
            st.session_state.writing_style = st.session_state.default_writing_style
            st.session_state.model = st.session_state.default_model
            st.session_state.rag_knowledge_datasets = st.session_state.default_rag_knowledge_datasets
            st.session_state.rag_knowledge_format = st.session_state.default_rag_knowledge_format
            st.session_state.rag_knowledge_text_limits = st.session_state.default_rag_knowledge_text_limits
            st.session_state.rag_knowledge_distance_logic = st.session_state.default_rag_knowledge_distance_logic
            st.session_state.rag_policy_datasets = st.session_state.default_rag_policy_datasets
            st.session_state.rag_policy_format = st.session_state.default_rag_policy_format
            st.session_state.rag_policy_text_limits = st.session_state.default_rag_policy_text_limits
            st.session_state.rag_policy_distance_logic = st.session_state.default_rag_policy_distance_logic
            st.session_state.messages = []
            st.session_state.seq_memory = []
        if st.button("Update RAG JSON", key="update_json"):
            if rag_data_dict is not None:
                for rag_name, rag_items_dict in rag_data_dict.items():
                    result_file = digim_insight_notion.DigiMatsu_geneRAGJSON(openai_api_key, user_id, rag_file_path, rag_name, rag_items_dict, chunk_setting, notion_setting, rag_items_dict["mode"])
                    print(rag_name+"の知識情報ファイル(JSON)を作成しました")
            st.session_state.sidebar_message = "RAG用の知識情報(JSON)の更新が完了しました"
            st.rerun()
        st.write(st.session_state.sidebar_message)    
        st.markdown("---")
        st.markdown("Histories:")
    
    # インスタンス部分の表示
    st.session_state.para_instance_name = st.text_input("Chat Name:", value=st.session_state.instance_name)
    if os.path.exists(st.session_state.instance_setting_file):
        if st.button("Save Instance", key="save_instance"):
            save_instance_sets(setting, st.session_state.instance_id, st.session_state.instance_setting_file, st.session_state.para_instance_name, st.session_state.para_persona, st.session_state.para_memory_save, st.session_state.para_memory_digest, st.session_state.para_memory_use, st.session_state.para_memory_format, st.session_state.para_memory_agent, st.session_state.para_memory_loader, st.session_state.para_memory_text_limits, st.session_state.para_memory_distance_logic, st.session_state.para_overwrite, st.session_state.para_prompt_format, st.session_state.para_writing_style, st.session_state.para_model, st.session_state.para_rag_knowledge_datasets, st.session_state.para_rag_knowledge_format, st.session_state.para_rag_knowledge_text_limits, st.session_state.para_rag_knowledge_distance_logic, st.session_state.para_rag_policy_datasets, st.session_state.para_rag_policy_format, st.session_state.para_rag_policy_text_limits, st.session_state.para_rag_policy_distance_logic)
    
    # チャット履歴削除用のボタン
    if st.button("Delete Chat History(Chk)", key="delete_chat_history"):
        for seq in st.session_state.seq_memory:
            digim_eng.delete_memory_seq(memory_file, st.session_state.instance_path, seq, "FLG", "N")
        st.session_state.sidebar_message = "チャット履歴を削除しました"
        st.session_state.seq_memory = []
        instance_refresh(st.session_state.instance_path, memory_file)
    
    # インスタンス内の設定画面
    expander_instance_setting = st.expander("Instance Setting:")
    with expander_instance_setting:
        st.session_state.para_persona = st.selectbox("Persona:", personas, index=personas.index(st.session_state.persona))
        st.markdown("---")
        st.session_state.para_memory_save = "Y" if st.checkbox(": Memory Save", value=st.session_state.memory_save) else "N"
        st.session_state.para_memory_digest = "Y" if st.checkbox(": Memory Digest", value=st.session_state.memory_digest) else "N"
        st.session_state.para_memory_use = "Y" if st.checkbox(": Memory Use", value=st.session_state.memory_use) else "N"
        st.session_state.para_memory_format = st.selectbox("Memory Format:", memory_formats, index=memory_formats.index(st.session_state.memory_format))
        st.session_state.para_memory_agent = st.selectbox("Memory Agent:", memory_agents, index=memory_agents.index(st.session_state.memory_agent))
        st.session_state.para_memory_loader = st.selectbox("Memory Loader:", memory_loaders, index=memory_loaders.index(st.session_state.memory_loader))
        st.session_state.para_memory_text_limits = st.number_input("Memory Text Limits:", value=st.session_state.memory_text_limits) 
        st.session_state.para_memory_distance_logic = st.selectbox("Memory Distance Logics:", distance_logics, index=distance_logics.index(st.session_state.memory_distance_logic))
        st.markdown("---")
        st.session_state.para_overwrite = "Y" if st.checkbox(": Overwrite", value=st.session_state.overwrite) else "N"
        st.session_state.para_prompt_format = st.selectbox("Prompt Format:", prompt_formats, index=prompt_formats.index(st.session_state.prompt_format))
        st.session_state.para_writing_style = st.selectbox("Writing Style:", writing_styles, index=writing_styles.index(st.session_state.writing_style))
        st.session_state.para_model = st.selectbox("Model:", models, index=models.index(st.session_state.model))
        st.session_state.para_rag_knowledge_datasets = st.multiselect("RAG Data(Knowledge): ", rag_datasets)
        st.session_state.para_rag_knowledge_format = st.selectbox("RAG Format(Knowledge):", rag_formats, index=rag_formats.index(st.session_state.rag_knowledge_format))
        st.session_state.para_rag_knowledge_text_limits = st.number_input("RAG Text Limits(Knowledge):", value=st.session_state.rag_knowledge_text_limits) 
        st.session_state.para_rag_knowledge_distance_logic = st.selectbox("RAG Distance Logics(Knowledge):", distance_logics, index=distance_logics.index(st.session_state.rag_knowledge_distance_logic))
        st.session_state.para_rag_policy_datasets = st.multiselect("RAG Data(Policy): ", rag_datasets)
        st.session_state.para_rag_policy_format = st.selectbox("RAG Format(Policy):", rag_formats, index=rag_formats.index(st.session_state.rag_policy_format))
        st.session_state.para_rag_policy_text_limits = st.number_input("RAG Text Limits(Policy):", value=st.session_state.rag_policy_text_limits) 
        st.session_state.para_rag_policy_distance_logic = st.selectbox("RAG Distance Logics(Policy):", distance_logics, index=distance_logics.index(st.session_state.rag_policy_distance_logic))
    
    # チャット履歴を初期化する
    if "messages" not in st.session_state:
        st.session_state["messages"] = []   # 辞書形式で定義
        # st.session_state.messages = []   # 属性として定義
        st.session_state.seq_memory = []
    
    # サイドバーのボタンを表示し、ボタンでチャット履歴をインスタンスごとに変更
    for item in instance_list:
        if st.sidebar.button(cut_string(item[1], 30), key=str(item[0])):
            st.session_state.instance_id = str(item[0])
            st.session_state.instance_path, st.session_state.instance_setting_file = set_instance_items(user_id, st.session_state.instance_id, chat_setting_file)
            st.session_state.instance_name = item[1]
            st.session_state.persona = str_in_list(item[3]["persona"], personas, st.session_state.default_persona)
            st.session_state.memory_save = True if item[3]["memory_save"]=="Y" else False
            st.session_state.memory_digest = True if item[3]["memory_digest"]=="Y" else False
            st.session_state.memory_use = True if item[3]["memory_use"]=="Y" else False
            st.session_state.memory_format = str_in_list(item[3]["memory_format"], memory_formats, st.session_state.default_memory_format)
            st.session_state.memory_agent = str_in_list(item[3]["memory_agent"], memory_agents, st.session_state.default_memory_agent)
            st.session_state.memory_loader = str_in_list(item[3]["memory_loader"], memory_loaders, st.session_state.default_memory_loader)
            st.session_state.memory_text_limits = item[3]["memory_text_limits"]
            st.session_state.memory_distance_logic = str_in_list(item[3]["memory_distance_logic"], distance_logics, st.session_state.default_memory_distance_logic)
            st.session_state.overwrite = True if item[3]["overwrite"]=="Y" else False
            st.session_state.prompt_format = str_in_list(item[3]["prompt_format"], prompt_formats, st.session_state.default_prompt_format)
            st.session_state.writing_style = str_in_list(item[3]["writing_style"], writing_styles, st.session_state.default_writing_style)
            st.session_state.model = str_in_list(item[3]["model"], models, st.session_state.default_model)
            st.session_state.rag_knowledge_datasets = item[3]["rag_knowledge_datasets"]
            st.session_state.rag_knowledge_format = str_in_list(item[3]["rag_knowledge_format"], rag_formats, st.session_state.default_rag_knowledge_format)
            st.session_state.rag_knowledge_text_limits = item[3]["rag_knowledge_text_limits"]
            st.session_state.rag_knowledge_distance_logic = str_in_list(item[3]["rag_knowledge_distance_logic"], distance_logics, st.session_state.default_rag_knowledge_distance_logic)
            st.session_state.rag_policy_datasets = item[3]["rag_policy_datasets"]
            st.session_state.rag_policy_format = str_in_list(item[3]["rag_policy_format"], rag_formats, st.session_state.default_rag_policy_format)
            st.session_state.rag_policy_text_limits = item[3]["rag_policy_text_limits"]
            st.session_state.rag_policy_distance_logic = str_in_list(item[3]["rag_policy_distance_logic"], distance_logics, st.session_state.default_rag_policy_distance_logic)
            st.session_state.messages = []
            st.session_state.seq_memory = []
            
            # インスタンスをリフレッシュ
            instance_refresh(st.session_state.instance_path, memory_file)
            st.session_state.sidebar_message = ""
            st.session_state.uploaded_files = []
            st.session_state.file_uploader = st.file_uploader
     
    # チャット入力を行った際のチャット履歴の表示
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] in ["user","assistant","user_img"]:
                st.markdown(message["content"], unsafe_allow_html=True)
                if message["role"] in ["assistant"]:
                    if st.checkbox("Delete:", key="del_chat_seq"+str(message["seq"])):
                        st.session_state.seq_memory.append(str(message["seq"]))
            elif message["role"] in ["uploaded_file", "generate_file"]:
                show_uploaded_files_memory(message["file_path"], message["file_name"], message["file_type"])
            elif message["role"] in ["detail"]:
                chat_expander = st.expander("Detail Information")
                with chat_expander:
                    st.markdown(message["content"], unsafe_allow_html=True)
    
    # 問合せを入力
    if query := st.chat_input("Your Message"):
        query = query.replace("\n", "<br>")
        # ユーザの入力
        with st.chat_message("user"):
            st.markdown(query, unsafe_allow_html=True)
            st.session_state.sidebar_message = ""

        # 現在の会話の最大シーケンスの設定
        st.session_state.seq = digim_eng.get_memory_seq(memory_file, st.session_state.instance_path)

        st.session_state.messages.append({"seq": st.session_state.seq, "role": "user", "content": query}) #ユーザの入力をチャット履歴に追加
    
        if st.session_state.instance_id == "":
            st.session_state.instance_id = new_instance_id(instance_list)
        st.session_state.instance_path, st.session_state.instance_setting_file = set_instance_items(user_id, st.session_state.instance_id, chat_setting_file)
        os.makedirs(remove_slash_mkdir(st.session_state.instance_path), exist_ok=True)

        # メモリのフォーマットデータを取得
        st.session_state.para_memory_format_data = setting["MEMORY"]["FORMATS"][st.session_state.para_memory_format]
        
        # AGENTのJSONファイルを読み込み
        persona_path = f"{user_id}/common/env/persona/"
        st.session_state.para_persona_file = setting["PERSONAS"][st.session_state.para_persona]["AGENT_FILE"]
        st.session_state.para_persona_data = load_json_data(persona_path, st.session_state.para_persona_file)
        st.session_state.para_persona_default_mode = setting["PERSONAS"][st.session_state.para_persona]["DEFAULT_MODE"]

        # 問合せ用のパラメータ設定
        st.session_state.api_key = {"OPENAI_API_KEY": openai_api_key, "GEMINI_API_KEY": gemini_api_key}
        st.session_state.para_memory = {
            "memory_save": st.session_state.memory_save,
            "memory_digest": st.session_state.memory_digest,
            "memory_use": st.session_state.para_memory_use, 
            "memory_format": st.session_state.para_memory_format, 
            "memory_format_data": st.session_state.para_memory_format_data, 
            "memory_agent": st.session_state.para_memory_agent, 
            "memory_loader": st.session_state.para_memory_loader, 
            "memory_text_limits": st.session_state.para_memory_text_limits, 
            "memory_distance_logic": st.session_state.para_memory_distance_logic
        }
        st.session_state.para_overwrite = {
            "overwrite": st.session_state.para_overwrite,
            "prompt_format": st.session_state.para_prompt_format,
            "writing_style": st.session_state.para_writing_style,
            "model": st.session_state.para_model,
            "rag_knowledge_data": st.session_state.para_rag_knowledge_datasets,
            "rag_knowledge_format": st.session_state.para_rag_knowledge_format,
            "rag_knowledge_text_limits": st.session_state.para_rag_knowledge_text_limits,
            "rag_knowledge_distance_logic": st.session_state.para_rag_knowledge_distance_logic,
            "rag_policy_data": st.session_state.para_rag_policy_datasets,
            "rag_policy_format": st.session_state.para_rag_policy_format,
            "rag_policy_text_limits": st.session_state.para_rag_policy_text_limits,
            "rag_policy_distance_logic": st.session_state.para_rag_policy_distance_logic
        }
        
        # AIの回答(response仕様)： [response, prompt_tokens, response_tokens, completion, timestamp, memory_docs_text, retrival_docs_text, detail]
        response = digim_eng.DigiMatsu_dialog(query, st.session_state.instance_id, common_path, st.session_state.instance_path, memory_file, st.session_state.para_persona, st.session_state.para_persona_data, st.session_state.para_persona_default_mode, st.session_state.para_memory, st.session_state.para_overwrite, st.session_state.api_key, models_dict, prompt_template_dict, rag_file_path, rag_data_dict, rag_format_dict, st.session_state.uploaded_files, AWS_KEY_dict)
        with st.chat_message("assistant"):
            st.markdown(response[0])
        with st.chat_message("detail"):
            chat_expander = st.expander("Detail Information")
            with chat_expander:
                st.markdown(response[7], unsafe_allow_html=True)
        
        # AIの返答をチャット履歴に追加
        st.session_state.messages.append({"seq": st.session_state.seq, "role": "assistant", "content": response[0]})
        st.session_state.messages.append({"seq": st.session_state.seq, "role": "detail", "content": response[7]})
    
        # インスタンス設定ファイルを保存
        save_instance_sets(setting, st.session_state.instance_id, st.session_state.instance_setting_file, st.session_state.para_instance_name, st.session_state.para_persona, st.session_state.para_memory_save, st.session_state.para_memory_digest, st.session_state.para_memory_use, st.session_state.para_memory_format, st.session_state.para_memory_agent, st.session_state.para_memory_loader, st.session_state.para_memory_text_limits, st.session_state.para_memory_distance_logic, st.session_state.para_overwrite, st.session_state.para_prompt_format, st.session_state.para_writing_style, st.session_state.para_model, st.session_state.para_rag_knowledge_datasets, st.session_state.para_rag_knowledge_format, st.session_state.para_rag_knowledge_text_limits, st.session_state.para_rag_knowledge_distance_logic, st.session_state.para_rag_policy_datasets, st.session_state.para_rag_policy_format, st.session_state.para_rag_policy_text_limits, st.session_state.para_rag_policy_distance_logic)

        # インスタンスをリフレッシュ
        instance_refresh(st.session_state.instance_path, memory_file)
        st.session_state.sidebar_message = ""
        st.session_state.uploaded_files = []
        st.session_state.file_uploader = st.file_uploader

    # 添付ファイル用のアップローダー（常にチャット画面の下部に表示）
    #with st.form(key="chat_form"):
    st.session_state.uploaded_files = st.session_state.file_uploader("Attached Files:", type=["txt", "csv", "xlsx", "jpg", "jpeg", "png", "mp4", "mov", "avi", "mp3", "wav"], accept_multiple_files=True)

    # 添付ファイルをアップロードしたら画面表示
    if st.session_state.uploaded_files:
        show_uploaded_files_widget(st.session_state.uploaded_files)
    

if __name__ == "__main__":
    main()