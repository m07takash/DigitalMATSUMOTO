import os
import json
import math
import time
import datetime
from datetime import datetime, timedelta
from dotenv import load_dotenv
import streamlit as st

import DigiM_Execute as dme
import DigiM_Session as dms
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Util as dmu

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
web_title = os.getenv("WEB_TITLE")
session_folder_prefix = os.getenv("SESSION_FOLDER_PREFIX")
temp_folder_path = os.getenv("TEMP_FOLDER")
temp_move_flg = os.getenv("TEMP_MOVE_FLG")
mst_folder_path = os.getenv("MST_FOLDER")
agent_folder_path = os.getenv("AGENT_FOLDER")
default_agent = os.getenv("DEFAULT_AGENT")
charactor_folder_path = os.getenv("CHARACTOR_FOLDER")
prompt_template_mst_file = os.getenv("PROMPT_TEMPLATE_MST_FILE")

# Streamlitの設定
st.set_page_config(page_title=web_title, layout="wide")

# セッションステートの初期化
def initialize_session_states():
    if 'sidebar_message' not in st.session_state:
        st.session_state.sidebar_message = ""
    if 'session' not in st.session_state:
        st.session_state.session = dms.DigiMSession(dms.set_new_session_id(), "New Chat")
    if 'seq_memory' not in st.session_state:
        st.session_state.seq_memory = []
    if 'memory_use' not in st.session_state:
        st.session_state.memory_use = "Y"
    if 'magic_word_use' not in st.session_state:
        st.session_state.magic_word_use = "Y"
    if 'uploaded_files' not in st.session_state:
        st.session_state.uploaded_files = []
    if 'file_uploader' not in st.session_state:
        st.session_state.file_uploader = st.file_uploader
    if 'chat_history_visible_dict' not in st.session_state:
        st.session_state.chat_history_visible_dict = {}
    if 'overwrite_flg_persona' not in st.session_state:
        st.session_state.overwrite_flg_persona = False
    if 'overwrite_flg_prompt_temp' not in st.session_state:
        st.session_state.overwrite_flg_prompt_temp = False
    if 'overwrite_flg_rag' not in st.session_state:
        st.session_state.overwrite_flg_rag = False

# セッションのリフレッシュ（ヒストリーを更新するために、同一セッションIDで再度Sessionクラスを呼び出すこともある）
def refresh_session(session_id, session_name):
    st.session_state.session = dms.DigiMSession(session_id, session_name)
    st.session_state.seq_memory = []
    st.session_state.sidebar_message = ""
    st.session_state.overwrite_flg_persona = False
    st.session_state.overwrite_flg_prompt_temp = False
    st.session_state.overwrite_flg_rag = False

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

# ファイルアップローダー(Widget)で添付したファイルの表示
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

### Streamlit画面 ###
def main():
    # セッションステートを初期化
    initialize_session_states()

    # エージェントの初期値
    agents = dma.get_all_agents()
    agent_list = [a1["AGENT"] for a1 in agents]
    agent_list_index = agent_list.index(default_agent)
    agent_id = agents[agent_list_index]["AGENT"]
    agent_file = agents[agent_list_index]["FILE"]
    agent_data = dmu.read_json_file(agent_file, agent_folder_path)
    
    # プロンプトテンプレートの初期値
    prompt_temp_mst_path = mst_folder_path + prompt_template_mst_file
    prompt_temps_json = dmu.read_json_file(prompt_temp_mst_path)
    prompt_format_list = list(prompt_temps_json["PROMPT_TEMPLATE"].keys())
    writing_style_list = list(prompt_temps_json["SPEAKING_STYLE"].keys())

    # サイドバーの設定
    with st.sidebar:
        st.title("Digital MATSUMOTO")
        
        # エージェントを選択（JSON)
        if agent_id := st.selectbox("Select Agent:", agent_list, index=agent_list_index):
            agent_file = next((a2["FILE"] for a2 in agents if a2["AGENT"] == agent_id), None)
            agent_data = dmu.read_json_file(agent_file, agent_folder_path)
        
        # 新しいセッションを発番（IDを指定して、新規にセッションリフレッシュ）
        if st.button("Create New Chat", key="new_chat"):
            session_id = dms.set_new_session_id()
            session_name = "New Chat"
            refresh_session(session_id, session_name)
        if st.button("Update RAG JSON", key="update_json"):
            dmc.generate_rag_vec_json()
            st.session_state.sidebar_message = "RAG用の知識情報(JSON)の更新が完了しました"
        st.write(st.session_state.sidebar_message)
        st.markdown("----")
        session_nums = dms.get_session_list()
        for session_num in sorted(session_nums, reverse=True):
            session_id = str(session_num)
            session_key = session_folder_prefix + session_id
            session_file_dict = dms.get_session_data(session_id)
            session_name = dms.get_session_name(session_id)
            session_name_btn = session_name[:16]
            if st.button(session_name_btn, key=session_key):
                refresh_session(session_id, session_name)

    # チャットセッション名の設定
    if session_name := st.text_input("Chat Name:", value=st.session_state.session.session_name):
        #st.session_state.session = dms.DigiMSession(st.session_state.session.session_id, session_name)
        st.session_state.session.session_name = session_name

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
            charactor = agent_data["CHARACTOR"]
            if charactor.strip().endswith(".txt"):
                charactor_text = str(dmu.read_text_file(charactor, charactor_folder_path))
            else:
                charactor_text = charactor
            st.session_state.persona_charactor = st.text_area("Persona Charactor:", value=charactor_text, height=400)
            overwrite_persona["NAME"] = st.session_state.persona_name
            overwrite_persona["ACT"] = st.session_state.persona_act
            overwrite_persona["CHARACTOR"] = st.session_state.persona_charactor
        else:
            overwrite_persona = {}
        st.markdown("")
        st.markdown("***Agent Setting:***")
        st.markdown(overwrite_persona)
        
        # プロンプトテンプレート
        st.markdown("----")
        st.subheader("Prompt Template")
        if st.checkbox("Overwrite", key="overwrite_flg_prompt_temp"):
            st.session_state.prompt_format = st.selectbox("Prompt Format:", prompt_format_list, index=prompt_format_list.index(agent_data["PROMPT_TEMPLATE"]["PROMPT_FORMAT"]))
            st.session_state.speaking_style = st.selectbox("Speaking Style:", speaking_style_list, index=speaking_style_list.index(agent_data["PROMPT_TEMPLATE"]["SPEAKING_STYLE"]))
            overwrite_prompt_temp["PROMPT_TEMPLATE"] = {}
            overwrite_prompt_temp["PROMPT_TEMPLATE"]["PROMPT_FORMAT"] = st.session_state.prompt_format
            overwrite_prompt_temp["PROMPT_TEMPLATE"]["SPEAKING_STYLE"] = st.session_state.speaking_style
        else:
            overwrite_prompt_temp = {}
        st.markdown("")
        st.markdown("***Agent Setting:***")
        st.markdown(overwrite_prompt_temp)

        # RAG
        st.markdown("----")
        st.subheader("RAG")
        rag_datasets = dmc.get_rag_list()
        rag_distance_logics = ["Cosine", "Euclidean", "Manhattan", "Chebychev"]
        if st.checkbox("Overwrite", key="overwrite_flg_rag"):
            overwrite_rag_list = []
            overwrite_rag["RAG"] = overwrite_rag_list
            i = 0
            for rag_dict in agent_data["RAG"]:
                st.markdown(f"***RAG Dataset {i}:***")
                rag_selects = rag_dict["DATA"]
                rag_col1, rag_col2 = st.columns(2)
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
            overwrite_rag["RAG"] = overwrite_rag_list
        else:
            overwrite_rag = {}
        st.markdown("")
        st.markdown("***Agent Setting:***")
        st.markdown(overwrite_rag)
        
        # Tool
        st.markdown("----")
        st.subheader("TOOL")
        if st.checkbox("Overwrite", key="overwrite_flg_tool"):
            overwrite_tool_list = []
            overwrite_tool["TOOL"] = {}
            overwrite_tool["TOOL"]["TOOL_LIST"] = overwrite_tool_list
            # TOOL_LISTはマルチセレクト
            # CHOICEはシングルセレクト
#        overwrite_items = {
#            "TOOL": {
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
    header_col1, header_col2, header_col3 = st.columns(3)

    # 会話メモリ利用の設定
    if header_col1.checkbox(": Memory Use", value=st.session_state.memory_use):
        st.session_state.memory_use = "Y"
    else:
        st.session_state.memory_use = "N"

    # マジックワード利用の設定
    if header_col1.checkbox(": Magic Word", value=st.session_state.magic_word_use):
        st.session_state.magic_word_use = "Y"
    else:
        st.session_state.magic_word_use = "N"

    # 会話履歴の表示切替
    option = header_col2.radio("History Visible:", ("NORMAL", "ALL"))
    if option == "ALL":
        st.session_state.chat_history_visible_dict = st.session_state.session.chat_history_active_dict
    elif option == "NORMAL":
        st.session_state.chat_history_visible_dict = st.session_state.session.chat_history_active_omit_dict

    # 会話履歴の削除（ボタン）
    if header_col3.button("Delete Chat History(Chk)", key="delete_chat_history"):
        if st.session_state.seq_memory:
            for del_seq in st.session_state.seq_memory:
                st.session_state.session.del_seq_history(del_seq)
            st.session_state.sidebar_message = "会話履歴を削除しました"
            st.session_state.seq_memory = []
            st.rerun()

    # 会話履歴の表示
    for k, v in st.session_state.chat_history_visible_dict.items():
        st.markdown("----")
        for k2, v2 in v.items():
            if k2 != "FLG":
                with st.chat_message(v2["prompt"]["role"]):
                    st.markdown(v2["prompt"]["query"]["input"].replace("\n", "<br>"), unsafe_allow_html=True)
                    for uploaded_content in v2["prompt"]["query"]["contents"]:
                        show_uploaded_files_memory(st.session_state.session.session_folder_path +"contents/", uploaded_content["file_name"], uploaded_content["file_type"])
                with st.chat_message(v2["response"]["role"]):
                    st.markdown("**"+v2["setting"]["name"]+" ("+v2["response"]["timestamp"]+"):**\n\n"+v2["response"]["text"].replace("\n", "<br>"), unsafe_allow_html=True)
                    if "image" in v2:
                        for gen_content in v2["image"].values():
                           show_uploaded_files_memory(st.session_state.session.session_folder_path +"contents/", gen_content["file_name"], gen_content["file_type"])
                with st.chat_message("detail"):
                    chat_expander = st.expander("Detail Information")
                    with chat_expander:
                        st.markdown(st.session_state.session.get_detail_info(k, k2).replace("\n", "<br>"), unsafe_allow_html=True)
        if st.checkbox(f"Delete(seq:{k})", key="del_chat_seq" + k):
            st.session_state.seq_memory.append(k)

    # ファイルアップローダー
    st.session_state.uploaded_files = st.session_state.file_uploader("Attached Files:", type=["txt", "csv", "xlsx", "jpg", "jpeg", "png", "mp4", "mov", "avi", "mp3", "wav"], accept_multiple_files=True)
    if st.session_state.uploaded_files:
        show_uploaded_files_widget(st.session_state.uploaded_files)
    
    # ユーザーの問合せ入力
    if user_input := st.chat_input("Your Message"):
        # 添付ファイルの設定
        uploaded_contents = []
        if st.session_state.uploaded_files:
            for uploaded_file in st.session_state.uploaded_files:
                uploaded_file_path = temp_folder_path + uploaded_file.name
                with open(uploaded_file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                uploaded_contents.append(uploaded_file_path)
        # オーバーライト項目の設定
        overwrite_items = {}
        overwrite_items.update(overwrite_persona)
        overwrite_items.update(overwrite_prompt_temp)
        overwrite_items.update(overwrite_rag)
        # ユーザー入力の一時表示
        with st.chat_message("user"):
            st.markdown(user_input.replace("\n", "<br>"), unsafe_allow_html=True)
            chains=[{"USER_INPUT": user_input, "CONTENTS": uploaded_contents, "OVERWRITE_ITEMS": overwrite_items, "PreSEQ":"", "PreSubSEQ":""}]
            #【作成中】UI検討（チェイン部分）＋ボタンでプロンプト追加する or プロンプトテンプレを選択
            dme.DigiMatsuExecute_Chain(st.session_state.session.session_id, st.session_state.session.session_name, agent_folder_path+agent_file, chains, st.session_state.memory_use, st.session_state.magic_word_use)
            st.rerun()

if __name__ == "__main__":
    main()