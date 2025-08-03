import os
import json
import math
import time
import datetime
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
import streamlit as st
import threading

import DigiM_Execute as dme
import DigiM_Session as dms
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Util as dmu
import DigiM_GeneCommunication as dmgc

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
agent_folder_path = os.getenv("AGENT_FOLDER")
if 'web_title' not in st.session_state:
    st.session_state.web_title = os.getenv("WEB_TITLE")
if 'timezone_setting' not in st.session_state:
    st.session_state.timezone_setting = os.getenv("TIMEZONE")
if 'session_folder_prefix' not in st.session_state:
    st.session_state.session_folder_prefix = os.getenv("SESSION_FOLDER_PREFIX")
if 'temp_folder_path' not in st.session_state:
    st.session_state.temp_folder_path = os.getenv("TEMP_FOLDER")
if 'temp_move_flg' not in st.session_state:
    st.session_state.temp_move_flg = os.getenv("TEMP_MOVE_FLG")
if 'mst_folder_path' not in st.session_state:
    st.session_state.mst_folder_path = os.getenv("MST_FOLDER")
if 'agent_folder_path' not in st.session_state:
    st.session_state.agent_folder_path = os.getenv("AGENT_FOLDER")
if 'default_agent' not in st.session_state:
    default_agent_data = dmu.read_json_file(os.getenv("DEFAULT_AGENT_FILE"), agent_folder_path)
    st.session_state.default_agent = default_agent_data["DISPLAY_NAME"]
if 'character_folder_path' not in st.session_state:
    st.session_state.character_folder_path = os.getenv("CHARACTER_FOLDER")
if 'prompt_template_mst_file' not in st.session_state:
    st.session_state.prompt_template_mst_file = os.getenv("PROMPT_TEMPLATE_MST_FILE")
#if 'feedback_item_list' not in st.session_state:
#    feedback_item_list = os.getenv("FEEDBACK_ITEM_LIST")
#    st.session_state.feedback_item_list = feedback_item_list.split(",") if feedback_item_list else []

# 時刻の設定
tz = pytz.timezone(st.session_state.timezone_setting)
now_time = datetime.now(tz)

# Streamlitの設定
st.set_page_config(page_title=st.session_state.web_title, layout="wide")

# セッションステートの初期化
def initialize_session_states():
    if 'sidebar_message' not in st.session_state:
        st.session_state.sidebar_message = ""
    if 'display_name' not in st.session_state:
        st.session_state.display_name = st.session_state.default_agent
    if 'agents' not in st.session_state:
        st.session_state.agents = dma.get_display_agents()
    if 'agent_list' not in st.session_state:
        st.session_state.agent_list = [a1["AGENT"] for a1 in st.session_state.agents]
    if 'agent_list_index' not in st.session_state:
        st.session_state.agent_list_index = st.session_state.agent_list.index(st.session_state.display_name)
    if 'agent_id' not in st.session_state:
        st.session_state.agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    if 'agent_file' not in st.session_state:
        st.session_state.agent_file = st.session_state.agents[st.session_state.agent_list_index]["FILE"]
    if 'agent_data' not in st.session_state:
        st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, st.session_state.agent_folder_path)
    if 'session_list' not in st.session_state:
        st.session_state.session_list = dms.get_session_list_visible()
    if 'session' not in st.session_state:
        st.session_state.session = dms.DigiMSession(dms.set_new_session_id(), "New Chat")
    if 'time_setting' not in st.session_state:
        st.session_state.time_setting = now_time.strftime("%Y/%m/%d %H:%M:%S")
    if 'situation_setting' not in st.session_state:
        st.session_state.situation_setting = ""
    if 'seq_memory' not in st.session_state:
        st.session_state.seq_memory = []
    if 'memory_use' not in st.session_state:
        st.session_state.memory_use = True
    if 'magic_word_use' not in st.session_state:
        st.session_state.magic_word_use = "Y"
    if 'stream_mode' not in st.session_state:
        st.session_state.stream_mode = True
    if 'save_digest' not in st.session_state:
        st.session_state.save_digest = True
    if 'meta_search' not in st.session_state:
        st.session_state.meta_search = True
    if 'RAG_query_gene' not in st.session_state:
        st.session_state.RAG_query_gene = True
    if 'uploaded_files' not in st.session_state:
        st.session_state.uploaded_files = []
    if 'file_uploader' not in st.session_state:
        st.session_state.file_uploader = st.file_uploader
    if 'chat_history_visible_dict' not in st.session_state:
        st.session_state.chat_history_visible_dict = {}
    if 'seq_visible_set' not in st.session_state:
        st.session_state.seq_visible_set = True
    if 'overwrite_flg_persona' not in st.session_state:
        st.session_state.overwrite_flg_persona = False
    if 'overwrite_flg_prompt_temp' not in st.session_state:
        st.session_state.overwrite_flg_prompt_temp = False
    if 'overwrite_flg_rag' not in st.session_state:
        st.session_state.overwrite_flg_rag = False
        
# セッションのリフレッシュ（ヒストリーを更新するために、同一セッションIDで再度Sessionクラスを呼び出すこともある）
def refresh_session(session_id, session_name, situation, new_session_flg=False):
    st.session_state.session = dms.DigiMSession(session_id, session_name)
    if new_session_flg:
        st.session_state.display_name = st.session_state.default_agent
    else:
        #st.session_state.display_name = st.session_state.session.get_history_max_agent()
        st.session_state.display_name = dma.get_agent_item(dms.get_agent_file(st.session_state.session.session_id), "DISPLAY_NAME")
    st.session_state.time_setting = situation["TIME"]
    st.session_state.situation_setting = situation["SITUATION"]
    st.session_state.seq_memory = []
    st.session_state.sidebar_message = ""
    st.session_state.overwrite_flg_persona = False
    st.session_state.overwrite_flg_prompt_temp = False
    st.session_state.overwrite_flg_rag = False
    #st.rerun()

# アップロードしたファイルの表示
def show_uploaded_files_memory(seq_key, file_path, file_name, file_type):
    uploaded_file = file_path+file_name
    if "text" in file_type:
        with open(uploaded_file, "r", encoding="utf-8") as f:
            text_content = f.read()
        st.text_area("TextFile:", text_content, height=100, key=seq_key+file_name)
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

# ファイルアップローダー(Widget)で添付したファイルの表示
def show_uploaded_files_widget(uploaded_files):
    for uploaded_file in uploaded_files:
        file_type = uploaded_file.type
        if "text" in file_type:
            text_content = uploaded_file.read().decode("utf-8")
            st.text_area("TextFile:", text_content, height=100)
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

### Streamlit画面 ###
def main():
    # セッションステートを初期化
    initialize_session_states()
    
    # プロンプトテンプレートの初期値
    prompt_temp_mst_path = st.session_state.mst_folder_path + st.session_state.prompt_template_mst_file
    prompt_temps_json = dmu.read_json_file(prompt_temp_mst_path)
    prompt_format_list = list(prompt_temps_json["PROMPT_TEMPLATE"].keys())
    speaking_style_list = list(prompt_temps_json["SPEAKING_STYLE"].keys())

    # サイドバーの設定
    with st.sidebar:
        st.title(st.session_state.web_title)
        
        # エージェントを選択（JSON)
        if agent_id_selected := st.selectbox("Select Agent:", st.session_state.agent_list, index=st.session_state.agent_list_index):
            st.session_state.agent_id = agent_id_selected
            st.session_state.agent_file = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.agent_id), None)
            st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, st.session_state.agent_folder_path)

        side_col1, side_col2 = st.columns(2)
        
        # 新しいセッションを発番（IDを指定して、新規にセッションリフレッシュ）
        if side_col1.button("New Chat", key="new_chat"):
            session_id = dms.set_new_session_id()
            session_name = "New Chat"
            situation = {}
            situation["TIME"] = now_time.strftime("%Y/%m/%d %H:%M:%S")
            situation["SITUATION"] = ""
            refresh_session(session_id, session_name, situation, True)

        # 会話履歴の更新
        if side_col2.button("Refresh List", key="refresh_session_list"):
            st.session_state.session_list = dms.get_session_list_visible()
        num_session_visible = st.number_input(label="Visible Sessions", value=5, step=1, format="%d")

        # 知識更新の処理
        rag_expander = st.expander("RAG Management")
        with rag_expander:
            if st.button("Update RAG Data", key="update_rag"):
                dmc.generate_rag()
                st.session_state.sidebar_message = "RAGの更新が完了しました"
            if st.button("Delete RAG DB", key="delete_rag_db"):
                dmc.del_rag_db()
                st.session_state.sidebar_message = "RAGを削除しました"
        
        st.write(st.session_state.sidebar_message)

        st.markdown("----")
        # セッションリストの表示
        #st.session_state.session_list = dms.get_session_list_visible()
        num_sessions = 0
        for session_num, last_update_date in st.session_state.session_list:
            if num_session_visible > num_sessions:
                session_id_list = str(session_num)
                session_key_list = st.session_state.session_folder_prefix + session_id_list
                session_name_list = dms.get_session_name(session_id_list)
                session_name_btn = session_name_list[:12]
                situation = dms.get_situation(session_id_list)
                if not situation:
                    situation["TIME"] = now_time.strftime("%Y/%m/%d %H:%M:%S")
                    situation["SITUATION"] = ""
                if st.button(session_name_btn, key=session_key_list):
                    refresh_session(session_id_list, session_name_list, situation)
                num_sessions += 1

    # チャットセッション名の設定
    if session_name := st.text_input("Chat Name:", value=st.session_state.session.session_name):
        st.session_state.session = dms.DigiMSession(st.session_state.session.session_id, session_name)

    # オーバーライトの設定
    overwrite_expander = st.expander("Overwrite Setting")
    overwrite_persona = {}
    overwrite_prompt_temp = {}
    overwrite_rag = {}
    overwrite_rag_list = []    
    overwrite_tool = {}
    with overwrite_expander:
        # ペルソナ
        st.subheader("Persona")
        if st.checkbox("Overwrite", key="overwrite_flg_persona"):
            st.session_state.persona_name = st.text_input("Persona Name:", value=agent_data["NAME"])
            st.session_state.persona_act = st.text_input("Persona Act:", value=agent_data["ACT"])
            persona_col1, persona_col2, persona_col3 = st.columns(3)
            persona_sex = agent_data["PERSONALITY"]["SEX"] if agent_data["PERSONALITY"] else ""
            st.session_state.persona_sex = persona_col1.text_input("Sex:", value=persona_sex)
            persona_birthday = agent_data["PERSONALITY"]["BIRTHDAY"] if agent_data["PERSONALITY"] else ""
            st.session_state.persona_birthday = persona_col1.text_input("Birthday:", value=persona_birthday)
            persona_is_alive = agent_data["PERSONALITY"]["IS_ALIVE"] if agent_data["PERSONALITY"] else True
            if persona_col1.checkbox("IS_ALIVE", value=persona_is_alive):
                st.session_state.persona_is_alive = True
            else:
                st.session_state.persona_is_alive = False
            persona_nationality = agent_data["PERSONALITY"]["NATIONALITY"] if agent_data["PERSONALITY"] else ""
            st.session_state.persona_nationality = persona_col2.text_input("Nationality:", value=persona_nationality)
            st.session_state.persona_big5 = {}
            if agent_data["PERSONALITY"]:
                persona_big5_openness = agent_data["PERSONALITY"]["BIG5"]["Openness"] if agent_data["PERSONALITY"]["BIG5"] else ""
                st.session_state.persona_big5["Openness"] = persona_col3.number_input("Big5 Openness:", value=persona_big5_openness, step=0.01, format="%.2f")
                persona_big5_conscientiousness = agent_data["PERSONALITY"]["BIG5"]["Conscientiousness"] if agent_data["PERSONALITY"]["BIG5"] else ""
                st.session_state.persona_big5["Conscientiousness"] = persona_col3.number_input("Big5 Conscientiousness:", value=persona_big5_conscientiousness, step=0.01, format="%.2f")
                persona_big5_extraversion = agent_data["PERSONALITY"]["BIG5"]["Extraversion"] if agent_data["PERSONALITY"]["BIG5"] else ""
                st.session_state.persona_big5["Extraversion"] = persona_col3.number_input("Big5 Extraversion:", value=persona_big5_extraversion, step=0.01, format="%.2f")
                persona_big5_agreeableness = agent_data["PERSONALITY"]["BIG5"]["Agreeableness"] if agent_data["PERSONALITY"]["BIG5"] else ""
                st.session_state.persona_big5["Agreeableness"] = persona_col3.number_input("Big5 Agreeableness:", value=persona_big5_agreeableness, step=0.01, format="%.2f")
                persona_big5_neuroticism = agent_data["PERSONALITY"]["BIG5"]["Neuroticism"] if agent_data["PERSONALITY"]["BIG5"] else ""               
                st.session_state.persona_big5["Neuroticism"] = persona_col3.number_input("Big5 Neuroticism:", value=persona_big5_neuroticism, step=0.01, format="%.2f")
            persona_language = agent_data["PERSONALITY"]["LANGUAGE"] if agent_data["PERSONALITY"] else ""
            st.session_state.persona_language = persona_col2.text_input("Language:", value=persona_language)
            persona_speaking_style = agent_data["PERSONALITY"]["SPEAKING_STYLE"] if agent_data["PERSONALITY"] else ""
            index_speaking_style = speaking_style_list.index(persona_speaking_style) if persona_speaking_style in speaking_style_list else 0
            st.session_state.persona_speaking_style = persona_col2.selectbox("Speaking Style:", speaking_style_list, index=index_speaking_style)
            persona_character = agent_data["PERSONALITY"]["CHARACTER"] if agent_data["PERSONALITY"] else ""
            if persona_character.strip().endswith(".txt"):
                persona_character_text = str(dmu.read_text_file(persona_character, st.session_state.character_folder_path))
            else:
                persona_character_text = persona_character
            st.session_state.persona_character = st.text_area("Persona Character:", value=persona_character_text, height=400)
            overwrite_persona["NAME"] = st.session_state.persona_name
            overwrite_persona["ACT"] = st.session_state.persona_act
            overwrite_persona["PERSONALITY"] = {}
            overwrite_persona["PERSONALITY"]["SEX"] = st.session_state.persona_sex
            overwrite_persona["PERSONALITY"]["BIRTHDAY"] = st.session_state.persona_birthday
            overwrite_persona["PERSONALITY"]["IS_ALIVE"] = st.session_state.persona_is_alive
            overwrite_persona["PERSONALITY"]["NATIONALITY"] = st.session_state.persona_nationality
            overwrite_persona["PERSONALITY"]["BIG5"] = st.session_state.persona_big5
            overwrite_persona["PERSONALITY"]["LANGUAGE"] = st.session_state.persona_language
            overwrite_persona["PERSONALITY"]["SPEAKING_STYLE"] = st.session_state.persona_speaking_style
            overwrite_persona["PERSONALITY"]["CHARACTER"] = st.session_state.persona_character
        else:
            overwrite_persona = {}
        st.markdown("")
        st.markdown("***Agent Setting:***")
        st.markdown(overwrite_persona)

        # RAG
        st.markdown("----")
        st.subheader("KNOWLEDGE(RAG)")
        rag_datasets = dmc.get_rag_list()
        rag_distance_logics = ["Cosine", "Euclidean", "Manhattan", "Chebychev"]
        if st.checkbox("Overwrite", key="overwrite_flg_rag"):
            overwrite_rag_list = []
            overwrite_rag["KNOWLEDGE"] = overwrite_rag_list
            i = 0
            for rag_dict in agent_data["KNOWLEDGE"]:
                st.markdown(f"***RAG Dataset {i}:***")
                rag_selects = rag_dict["DATA"]
                rag_col1, rag_col2 = st.columns(2)
                #【】
                st.session_state.rag_data = rag_col1.multiselect("RAG Data: ", rag_datasets, default=rag_selects)
                st.session_state.rag_text_limits = rag_col2.number_input("RAG Text Limits:", value=rag_dict["TEXT_LIMITS"], step=1)
                st.session_state.rag_distance_logic = rag_col2.selectbox(
                    "RAG Distance Logic:", rag_distance_logics, 
                    index=rag_distance_logics.index(rag_dict["DISTANCE_LOGIC"]), 
                    key=f"rag_distance_logic{i}"
                )
                st.session_state.rag_header_temp = st.text_area("RAG Prompt(Header):", value=rag_dict["HEADER_TEMPLATE"], height=100)
                st.session_state.rag_chunk_temp = st.text_area(
                    "RAG Prompt(Chunk):  [設定] {title}:タイトル, {days_difference}:タイムスタンプとの日数, {similarity}:質問との距離, {text}:チャンク本文",
                    value=rag_dict["CHUNK_TEMPLATE"], height=100
                )
                st.markdown("")        
                overwrite_rag_dict = {
                    "DATA": st.session_state.rag_data,
                    "HEADER_TEMPLATE": st.session_state.rag_header_temp,
                    "CHUNK_TEMPLATE": st.session_state.rag_chunk_temp,
                    "TEXT_LIMITS": st.session_state.rag_text_limits,
                    "DISTANCE_LOGIC": st.session_state.rag_distance_logic
                }
                overwrite_rag_list.append(overwrite_rag_dict)
                i += 1
            overwrite_rag["KNOWLEDGE"] = overwrite_rag_list
        else:
            overwrite_rag = {}
        st.markdown("")
        st.markdown("***Agent Setting:***")
        st.markdown(overwrite_rag)
        
        # Tool
        st.markdown("----")
        st.subheader("SKILL(TOOL)")
        if st.checkbox("Overwrite", key="overwrite_flg_tool"):
            overwrite_tool_list = []
            overwrite_tool["SKILL"] = {}
            overwrite_tool["SKILL"]["TOOL_LIST"] = overwrite_tool_list
           # TOOL_LISTはマルチセレクト
            # CHOICEはシングルセレクト
#        overwrite_items = {
#            "SKILL": {
#                "TOOL_LIST": [
#                    {"type": "function", "function": {"name": "default_tool"}}
#                ],
#                "CHOICE": "none"
#            }
#        }
        st.markdown("")
        st.markdown("***Agent Setting:***")
        st.markdown(overwrite_tool)

    # Webパーツのレイアウト
    header_col1, header_col2, header_col3, header_col4 = st.columns(4)

    # 時刻の設定
    header_col1.markdown("Time Setting:")
    selected_time_setting = now_time.strftime("%Y/%m/%d %H:%M:%S")
    if header_col1.checkbox("Real Date:", value=True):
        selected_time_setting = now_time.strftime("%Y/%m/%d %H:%M:%S")
    else:
        selected_date = header_col1.date_input("Situation Date", value=datetime.strptime(st.session_state.time_setting, "%Y/%m/%d %H:%M:%S").date())
        selected_time = header_col1.time_input("Situation Time", value=datetime.strptime(st.session_state.time_setting, "%Y/%m/%d %H:%M:%S").time())
        selected_time_setting = tz.localize(datetime.combine(selected_date, selected_time)).strftime('%Y/%m/%d %H:%M:%S')
    time_setting = str(selected_time_setting)

    # 実行の設定
    header_col2.markdown("Exec Setting:")

    # ストリーミングの設定
    if header_col2.checkbox("Streaming Mode", value=st.session_state.stream_mode):
        st.session_state.stream_mode = True
    else:
        st.session_state.stream_mode = False
    
    # 会話メモリ利用の設定
    if header_col2.checkbox("Memory Use", value=st.session_state.memory_use):
        st.session_state.memory_use = True
    else:
        st.session_state.memory_use = False

    # メモリダイジェスト保存の設定
    if header_col2.checkbox("Save Digest", value=st.session_state.save_digest):
        st.session_state.save_digest = True
    else:
        st.session_state.save_digest = False

    # マジックワード利用の設定
    if header_col2.checkbox("Magic Word", value=st.session_state.magic_word_use):
        st.session_state.magic_word_use = "Y"
    else:
        st.session_state.magic_word_use = "N"
    
    # 実行の設定
    header_col3.markdown("RAG Setting:")

    # RAG検索用クエリ生成の設定
    if header_col3.checkbox("RAG Query Gen", value=st.session_state.RAG_query_gene):
        st.session_state.RAG_query_gene = True
    else:
        st.session_state.RAG_query_gene = False

    # メタ検索の設定
    if header_col3.checkbox("Meta Search", value=st.session_state.meta_search):
        st.session_state.meta_search = True
    else:
        st.session_state.meta_search = False

    # 会話履歴の表示対象切替
    num_seq_visible = 10
    sub_header_col1, sub_header_col2 = header_col4.columns(2)
    option = sub_header_col1.radio("History Seq Visible:", ("LATEST", "FULL"))
    if option == "LATEST":
        st.session_state.seq_visible_set = True
        if num_seq_visible := sub_header_col2.number_input(label="Visible Seq", value=10, step=1, format="%d"):
            st.session_state.seq_visible_set = True
    elif option == "FULL":
        st.session_state.seq_visible_set = False

    # 会話履歴の表示件数
    option = header_col4.radio("History Detail Visible:", ("ALL", "SUMMARY"))
    if option == "ALL":
        st.session_state.chat_history_visible_dict = st.session_state.session.chat_history_active_dict
    elif option == "SUMMARY":
        st.session_state.chat_history_visible_dict = st.session_state.session.chat_history_active_omit_dict
    
    # 会話履歴の削除（ボタン）
    if header_col4.button("Delete Chat History(Chk)", key="delete_chat_history"):
        if st.session_state.seq_memory:
            for del_seq in st.session_state.seq_memory:
                st.session_state.session.chg_seq_history(del_seq, "N")
            st.session_state.sidebar_message = "会話履歴を削除しました"
            st.session_state.seq_memory = []
            st.rerun()

    # シチュエーションの設定
    situation_setting = st.text_input("Situation Setting:", value=st.session_state.situation_setting)


    # 会話履歴の表示件数の設定
    max_seq = dms.max_seq_dict(st.session_state.chat_history_visible_dict)
    seq_visible_key = 0
    if st.session_state.seq_visible_set:
        seq_visible_key = int(max_seq) - num_seq_visible
    else:
        seq_visible_key = 0
    
    # 会話履歴の表示
    for k, v in st.session_state.chat_history_visible_dict.items():
        if int(k) >= seq_visible_key:
            st.markdown("----")
            for k2, v2 in v.items():
                if k2 != "SETTING":
                    seq_key = f"key_{k}_{k2}"
                    with st.chat_message(v2["prompt"]["role"]):
                        st.markdown(v2["prompt"]["query"]["input"].replace("\n", "<br>"), unsafe_allow_html=True)
                        for uploaded_content in v2["prompt"]["query"]["contents"]:
                            show_uploaded_files_memory(seq_key, st.session_state.session.session_folder_path +"contents/", uploaded_content["file_name"], uploaded_content["file_type"])
                    with st.chat_message(v2["response"]["role"]):
                        st.markdown("**"+v2["setting"]["name"]+" ("+v2["response"]["timestamp"]+"):**\n\n"+v2["response"]["text"].replace("\n", "<br>").replace("#", ""), unsafe_allow_html=True)
                        if "image" in v2:
                            for gen_content in v2["image"].values():
                               show_uploaded_files_memory(seq_key, st.session_state.session.session_folder_path +"contents/", gen_content["file_name"], gen_content["file_type"])

                    if v2["setting"]["type"] in ["LLM","IMAGEGEN"]:
                        if "communication" in v2["setting"]:
                            agent_communication = v2["setting"]["communication"]

                            if agent_communication["ACTIVE"] == "Y":
                                with st.chat_message("Feedback"):
                                    feedback = {}
                                    feedback["name"] = "Chunk Title"
                                    if "feedback" in v2:
                                        feedback["name"] = v2.get("feedback", {}).get("name", feedback["name"])
                                    feedback["name"] = st.text_input("Feedback_Name:", key=f"feedback_name{k}_{k2}", value=feedback["name"], label_visibility="collapsed")
                                                                                    
                                    for fb_item in agent_communication["FEEDBACK_ITEM_LIST"]:
                                        feedback[fb_item] = {}
                                        feedback[fb_item]["visible"] = False
                                        feedback[fb_item]["flg"] = False
                                        feedback[fb_item]["memo"] = ""                           
                                        if "feedback" in v2:
                                            feedback[fb_item] = v2.get("feedback", {}).get(fb_item, feedback[fb_item])
                                        feedback[fb_item]["saved_memo"] = feedback[fb_item]["memo"]
                                
                                        if st.checkbox(f"{fb_item}", key=f"feedback_{fb_item}_{k}_{k2}", value=feedback[fb_item]["visible"]):
                                            feedback[fb_item]["memo"] = st.text_input("Memo:", key=f"feedback_{fb_item}_memo{k}_{k2}", value=feedback[fb_item]["memo"], label_visibility="collapsed")
                                            feedback[fb_item]["visible"] = True
                                        else:
                                            feedback[fb_item]["memo"] = ""
                                            feedback[fb_item]["visible"] = False

                                    if st.button("Feedback", key=f"feedback_btn{k}_{k2}"):
                                        for fb_item in agent_communication["FEEDBACK_ITEM_LIST"]:
                                            if feedback[fb_item]["memo"]!=feedback[fb_item]["saved_memo"] and feedback[fb_item]["memo"]!="":
                                                feedback[fb_item]["flg"] = True
                                            if feedback[fb_item]["memo"]=="":
                                                feedback[fb_item]["flg"] = False

                                        if any(k != "name" for k in fb_item):
                                            st.session_state.session.set_feedback_history(k, k2, feedback)
                                            dmgc.create_communication_data(st.session_state.session.session_id, v2["setting"]["agent_file"])
                                            st.session_state.sidebar_message = f"フィードバックを保存しました({k})"
                                            st.rerun()
                                        else:
                                            st.session_state.sidebar_message = f"フィードバックに変更はありません({k})"
                        
                        # Detail
                        with st.chat_message("detail"):
                            chat_expander = st.expander("Detail Information")
                            with chat_expander:
                                st.markdown(st.session_state.session.get_detail_info(k, k2).replace("\n", "<br>"), unsafe_allow_html=True)
            # 会話履歴の論理削除設定
            if st.checkbox(f"Delete(seq:{k})", key="del_chat_seq"+k):
                st.session_state.seq_memory.append(k)

    # ファイルアップローダー
#    st.session_state.uploaded_files = st.session_state.file_uploader("Attached Files:", type=["txt", "csv", "xlsx", "jpg", "jpeg", "png", "mp4", "mov", "avi", "mp3", "wav"], accept_multiple_files=True)
#    if st.session_state.uploaded_files:
#        show_uploaded_files_widget(st.session_state.uploaded_files)
#    uploaded_files = st.file_uploader("Attached Files:", type=["txt", "csv", "xlsx", "jpg", "jpeg", "png", "mp4", "mov", "avi", "mp3", "wav"], accept_multiple_files=True)
    uploaded_files = st.file_uploader("Attached Files:", type=["txt", "csv", "jpg", "jpeg", "png"], accept_multiple_files=True)
#    if uploaded_files:
    st.session_state.uploaded_files = uploaded_files
    show_uploaded_files_widget(st.session_state.uploaded_files)
    
    # ユーザーの問合せ入力
    if user_input := st.chat_input("Your Message"):
        # 添付ファイルの設定
        uploaded_contents = []
        if st.session_state.uploaded_files:
            for uploaded_file in st.session_state.uploaded_files:
                uploaded_file_path = st.session_state.temp_folder_path + uploaded_file.name
                with open(uploaded_file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                uploaded_contents.append(uploaded_file_path)
        # オーバーライト項目の設定
        overwrite_items = {}
#        overwrite_items.update(overwrite_persona)
#        overwrite_items.update(overwrite_prompt_temp)
#        overwrite_items.update(overwrite_rag)

        # シチュエーションの設定
        situation = {}
        situation["TIME"] = time_setting
        situation["SITUATION"] = situation_setting
        
        # ユーザー入力の一時表示
        with st.chat_message("User"):
            st.markdown(user_input.replace("\n", "<br>"), unsafe_allow_html=True)
        with st.chat_message(st.session_state.web_title):
            practice=st.session_state.agent_data["HABIT"]
            response_placeholder = st.empty()
            response = ""
            for response_chunk in dme.DigiMatsuExecute_Practice(st.session_state.session.session_id, st.session_state.session.session_name, st.session_state.agent_file, user_input, uploaded_contents, situation, overwrite_items, practice, st.session_state.memory_use, st.session_state.magic_word_use, st.session_state.stream_mode, st.session_state.save_digest, st.session_state.meta_search, st.session_state.RAG_query_gene):
                response += response_chunk
                response_placeholder.markdown(response)
            st.rerun()

if __name__ == "__main__":
    main()