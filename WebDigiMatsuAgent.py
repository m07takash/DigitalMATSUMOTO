import os
import ast
import json
import datetime
from datetime import datetime
import pytz
from dotenv import load_dotenv
import streamlit as st
import pandas as pd

import DigiM_Execute as dme
import DigiM_Session as dms
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Util as dmu
import DigiM_Tool as dmt
import DigiM_GeneCommunication as dmgc
import DigiM_VAnalytics as dmva

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
session_folder_prefix = system_setting_dict["SESSION_FOLDER_PREFIX"]
agent_folder_path = system_setting_dict["AGENT_FOLDER"]
temp_folder_path = system_setting_dict["TEMP_FOLDER"]

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
if 'web_title' not in st.session_state:
    st.session_state.web_title = os.getenv("WEB_TITLE")
if 'timezone_setting' not in st.session_state:
    st.session_state.timezone_setting = os.getenv("TIMEZONE")
if 'temp_move_flg' not in st.session_state:
    st.session_state.temp_move_flg = os.getenv("TEMP_MOVE_FLG")
if 'default_agent' not in st.session_state:
    default_agent_data = dmu.read_json_file(os.getenv("WEB_DEFAULT_AGENT_FILE"), agent_folder_path)
    st.session_state.default_agent = default_agent_data["DISPLAY_NAME"]
if 'web_default_service' not in st.session_state:
    st.session_state.web_default_service = json.loads(os.getenv("WEB_DEFAULT_SERVICE"))
if 'web_default_user' not in st.session_state:
    st.session_state.web_default_user = json.loads(os.getenv("WEB_DEFAULT_USER"))
if 'prompt_template_mst_file' not in st.session_state:
    st.session_state.prompt_template_mst_file = os.getenv("PROMPT_TEMPLATE_MST_FILE")

# 時刻の設定
tz = pytz.timezone(st.session_state.timezone_setting)
now_time = datetime.now(tz)

# Streamlitの設定
st.set_page_config(page_title=st.session_state.web_title, layout="wide")

# セッションステートの初期宣言
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
    if 'compare_agent_id' not in st.session_state:
        st.session_state.compare_agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    if 'agent_file' not in st.session_state:
        st.session_state.agent_file = st.session_state.agents[st.session_state.agent_list_index]["FILE"]
    if 'agent_data' not in st.session_state:
        st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
    if 'rag_data_list' not in st.session_state:
        st.session_state.rag_data_list = dmc.get_rag_list()
    if 'rag_data_list_selected' not in st.session_state:
        st.session_state.rag_data_list_selected = []
    if 'session_list' not in st.session_state:
        st.session_state.session_list = dms.get_session_list_visible()
    if 'session_inactive_list' not in st.session_state:
        st.session_state.session_inactive_list = dms.get_session_list_inactive()
    if 'session_inactive_list_selected' not in st.session_state:
        st.session_state.session_inactive_list_selected = []
    if 'session' not in st.session_state:
        st.session_state.session = dms.DigiMSession(dms.set_new_session_id(), "New Chat")
    if 'time_setting' not in st.session_state:
        st.session_state.time_setting = now_time.strftime("%Y/%m/%d %H:%M:%S")
    if 'situation_setting' not in st.session_state:
        st.session_state.situation_setting = ""
    if 'seq_memory' not in st.session_state:
        st.session_state.seq_memory = []
    if 'stream_mode' not in st.session_state:
        st.session_state.stream_mode = True
    if 'magic_word_use' not in st.session_state:
        st.session_state.magic_word_use = True
    if 'save_digest' not in st.session_state:
        st.session_state.save_digest = True
    if 'memory_use' not in st.session_state:
        st.session_state.memory_use = True
    if 'memory_save' not in st.session_state:
        st.session_state.memory_save = True
    if 'memory_similarity' not in st.session_state:
        st.session_state.memory_similarity = False
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
    if 'web_search' not in st.session_state:
        st.session_state.web_search = False
    if 'book_selected' in st.session_state:
        st.session_state.book_selected = []
    if 'dl_type' not in st.session_state:
        st.session_state.dl_type = "Chats Only"
    if 'analytics_knowledge_mode' not in st.session_state:
        st.session_state.analytics_knowledge_mode = ""
    if 'analytics_knowledge_mode_compare' not in st.session_state:
        st.session_state.analytics_knowledge_mode_compare = ""

# セッション変数のリフレッシュ
def refresh_session_states():
    st.session_state.sidebar_message = ""
    st.session_state.display_name = st.session_state.default_agent
    st.session_state.agents = dma.get_display_agents()
    st.session_state.agent_list = [a1["AGENT"] for a1 in st.session_state.agents]
    st.session_state.agent_list_index = st.session_state.agent_list.index(st.session_state.display_name)
    st.session_state.agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    st.session_state.compare_agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    st.session_state.agent_file = st.session_state.agents[st.session_state.agent_list_index]["FILE"]
    st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
    st.session_state.rag_data_list = dmc.get_rag_list()
    st.session_state.rag_data_list_selected = []
    st.session_state.session_list = dms.get_session_list_visible()
    st.session_state.session_inactive_list = dms.get_session_list_inactive()
    st.session_state.session_inactive_list_selected = []
    st.session_state.session = dms.DigiMSession(dms.set_new_session_id(), "New Chat")
    st.session_state.time_setting = now_time.strftime("%Y/%m/%d %H:%M:%S")
    st.session_state.situation_setting = ""
    st.session_state.seq_memory = []
    st.session_state.stream_mode = True
    st.session_state.magic_word_use = True
    st.session_state.save_digest = True
    st.session_state.memory_use = True
    st.session_state.memory_save = True
    st.session_state.memory_similarity = False
    st.session_state.meta_search = True
    st.session_state.RAG_query_gene = True
    st.session_state.uploaded_files = []
    st.session_state.file_uploader = st.file_uploader
    st.session_state.chat_history_visible_dict = {}
    st.session_state.seq_visible_set = True
    st.session_state.overwrite_flg_persona = False
    st.session_state.overwrite_flg_prompt_temp = False
    st.session_state.overwrite_flg_rag = False
    st.session_state.web_search = False
    st.session_state.book_selected = []
    st.session_state.dl_type = "Chats Only"
    st.session_state.analytics_knowledge_mode = ""
    st.session_state.analytics_knowledge_mode_compare = ""

# セッションのリフレッシュ（ヒストリーを更新するために、同一セッションIDで再度Sessionクラスを呼び出すこともある）
def refresh_session(session_id, session_name, situation, new_session_flg=False):
    st.session_state.session = dms.DigiMSession(session_id, session_name)
    if new_session_flg:
        st.session_state.display_name = st.session_state.default_agent
    else:
        session_agent_file = dms.get_agent_file(st.session_state.session.session_id)
        if os.path.exists(agent_folder_path + session_agent_file):
            st.session_state.display_name = dma.get_agent_item(session_agent_file, "DISPLAY_NAME")
        else:
            st.session_state.display_name = st.session_state.default_agent
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

# ダウンロード用ファイル形式の設定
def set_dl_file(chat_history, dl_type="Chats Only", file_id="Chat_History"):
    markdown_lines = []
    for msg in chat_history:
        if (dl_type=="Chats Only" and msg["role"] in ["user", "assistant"]) or dl_type == "ALL":
            if "content" in msg:
                markdown_lines.append(f"**{msg['role'].capitalize()}**\n {msg['content']}")
            if "image" in msg:
                b64 = dmu.encode_image_file(msg['image']).replace("\n","").replace("\r","")
                markdown_lines.append(f"![alt](data:image/png;base64,{b64})")
            markdown_lines.append("---")

    data = "\n\n".join(markdown_lines)
    file_name = f"{file_id}_{dl_type}.md"
    mime = "text/markdown"
    return data, file_name, mime

def seq_label(x: str) -> str:
    return {
        "0": "クエリ①「入力そのまま」",
        "1": "クエリ②「会話履歴付き入力」",
        "2": "クエリ③「入力の意図」",
    }.get(x, x)

def mode_label(x: str) -> str:
    if x == "NORMAL":
        return ""
    if isinstance(x, str) and x.startswith("(META_SEARCH:"):
        return "＋期間の絞込"
    return x

def ak_line(ak_dict):
    query_seq = seq_label(ak_dict.get("QUERY_SEQ", ""))
    query_mode = mode_label(ak_dict.get("QUERY_MODE", ""))
    title = ak_dict.get("title", "")
    sq = ak_dict.get("similarity_Q", "")
    sa = ak_dict.get("similarity_A", "")
    ku = ak_dict.get("knowledge_utility", "")

    # 数値は小数3桁に整形（数値でなければそのまま）
    fmt = lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else x
    line = (
        f'{title}（質問との近さ：{fmt(sq)}→回答との近さ：{fmt(sa)}'
        f'=知識活用性：{fmt(ku)}）{query_seq}{query_mode}'
    )
    return line

### Streamlit画面 ###
def main():
    # セッションステートを初期化
    initialize_session_states()

    # サイドバーの設定
    with st.sidebar:
        st.title(st.session_state.web_title)
        
        # エージェントを選択（JSON)
        if agent_id_selected := st.selectbox("Select Agent:", st.session_state.agent_list, index=st.session_state.agent_list_index):
            st.session_state.agent_id = agent_id_selected
            st.session_state.agent_file = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.agent_id), None)
            st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)

        side_col1, side_col2 = st.columns(2)
        
        # 新しいセッションを発番（IDを指定して、新規にセッションリフレッシュ）
        if side_col1.button("New Chat", key="new_chat"):
            session_id = dms.set_new_session_id()
            session_name = "New Chat"
            situation = {}
            situation["TIME"] = now_time.strftime("%Y/%m/%d %H:%M:%S")
            situation["SITUATION"] = ""
            refresh_session_states()
            refresh_session(session_id, session_name, situation, True)

        # 会話履歴の更新
        if side_col2.button("Refresh List", key="refresh_session_list"):
            st.session_state.session_list = dms.get_session_list_visible()

        # セッションの管理
        sessions_expander = st.expander("Sessions")
        with sessions_expander:
            num_session_visible = st.number_input(label="Visible Sessions", value=5, step=1, format="%d")
            st.session_state.session_inactive_list = dms.get_session_list_inactive()
            st.session_state.session_inactive_list_selected = st.multiselect("Activate Sessions", [f"{str(item[0])}_{item[1]}" for item in st.session_state.session_inactive_list])
            if st.button("Activate", key="activate_sessions"):
                for session_list_selected in st.session_state.session_inactive_list_selected:
                    session_id_selected = session_list_selected.split("_")[0]
                    activate_session = dms.DigiMSession(session_id_selected)
                    activate_session.save_active_session("Y")
                activate_sessions_str = ", ".join(st.session_state.session_inactive_list_selected)
                st.session_state.sidebar_message = f"セッションを再表示しました({activate_sessions_str})"
                st.rerun()
    
        # 知識更新の処理
        rag_expander = st.expander("RAG Management")
        with rag_expander:
            # RAGの更新処理
            if st.button("Update RAG Data", key="update_rag"):
                dmc.generate_rag()
                st.session_state.sidebar_message = "RAGの更新が完了しました"
            
            # RAGの削除処理(未選択は全削除)
            st.session_state.rag_data_list_selected = st.multiselect("RAG DB", st.session_state.rag_data_list)
            if st.button("Delete RAG DB", key="delete_rag_db"):
                dmc.del_rag_db(st.session_state.rag_data_list_selected)
                st.session_state.sidebar_message = "RAGを削除しました"
                st.session_state.rag_data_list = dmc.get_rag_list()
        
        st.write(st.session_state.sidebar_message)

        st.markdown("----")
        # セッションリストの表示
        num_sessions = 0
        for session_num, last_update_date in st.session_state.session_list:
            if num_session_visible > num_sessions:
                session_id_list = str(session_num)
                session_key_list = session_folder_prefix + session_id_list
                session_list = dms.DigiMSession(session_id_list)
                session_name_list = session_list.session_name
#                session_name_list = dms.get_session_name(session_id_list)
                session_active_flg = session_list.get_active_session()
                if session_active_flg != "N":
                    session_name_btn = session_id_list +"_"+ session_name_list[:10]
                    situation = dms.get_situation(session_id_list)                
                    if not situation:
                        situation["TIME"] = now_time.strftime("%Y/%m/%d %H:%M:%S")
                        situation["SITUATION"] = ""
                    if st.button(session_name_btn, key=session_key_list):
                        refresh_session_states()
                        refresh_session(session_id_list, session_name_list, situation)
                    if st.button(f"Del:{session_id_list}", key=f"{session_key_list}_del_btn"):
                        del_session = dms.DigiMSession(session_id_list, session_name_list)
                        del_session.save_active_session("N")
                        st.session_state.sidebar_message = f"セッションを非表示にしました({session_id_list}_{session_name_list})"
                        st.rerun()
                    num_sessions += 1

    # チャットセッション名の設定
    if session_name := st.text_input("Chat Name:", value=st.session_state.session.session_name):
        st.session_state.session = dms.DigiMSession(st.session_state.session.session_id, session_name)

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
        st.session_state.magic_word_use = True
    else:
        st.session_state.magic_word_use = False

#    # メモリ保存の設定
#    if header_col2.checkbox("Memory Save", value=st.session_state.memory_save):
#        st.session_state.memory_save = True
#    else:
#        st.session_state.memory_save = False
#
#    # メモリ類似度の設定
#    if header_col2.checkbox("Memory Similarity", value=st.session_state.memory_similarity):
#        st.session_state.memory_similarity = True
#    else:
#        st.session_state.memory_similarity = False
#
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
    download_data = []
    for k, v in st.session_state.chat_history_visible_dict.items():
        if int(k) >= seq_visible_key:
            st.markdown("----")
            for k2, v2 in v.items():
                if k2 != "SETTING":
                    seq_key = f"key_{k}_{k2}"
                    with st.chat_message(v2["prompt"]["role"]):
                        content_text = v2["prompt"]["query"]["input"]
                        download_data.append({"role": v2["prompt"]["role"], "content": content_text})
#                        st.markdown(content_text.replace("\n", "<br>"), unsafe_allow_html=True)
                        st.markdown(content_text, unsafe_allow_html=True)
                        for uploaded_content in v2["prompt"]["query"]["contents"]:
                            download_data.append({"role": v2["prompt"]["role"], "image": st.session_state.session.session_folder_path +"contents/"+ uploaded_content["file_name"]})
                            show_uploaded_files_memory(seq_key, st.session_state.session.session_folder_path +"contents/", uploaded_content["file_name"], uploaded_content["file_type"])
                    with st.chat_message(v2["response"]["role"]):
                        content_text = "**"+v2["setting"]["name"]+" ("+v2["response"]["timestamp"]+"):**\n\n"+v2["response"]["text"]
                        download_data.append({"role": v2["response"]["role"], "content": content_text})
#                        st.markdown(content_text.replace("\n", "<br>").replace("#", ""), unsafe_allow_html=True)
                        st.markdown(content_text, unsafe_allow_html=True)
                        if "image" in v2:
                            for gen_content in v2["image"].values():
                                download_data.append({"role": v2["response"]["role"], "image": st.session_state.session.session_folder_path +"contents/"+ gen_content["file_name"]})
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
                                            st.session_state.sidebar_message = f"フィードバックを保存しました({k}_{k2})"
                                            st.rerun()
                                        else:
                                            st.session_state.sidebar_message = f"フィードバックに変更はありません({k}_{k2})"
                        
                        # Detail
                        with st.chat_message("detail"):
                            download_data.append({"role": "detail", "content": st.session_state.session.get_detail_info(k, k2)})
                            chat_expander = st.expander("Detail Information")
                            with chat_expander:
                                st.markdown(st.session_state.session.get_detail_info(k, k2).replace("\n", "<br>"), unsafe_allow_html=True)

                        # Analytics
                        with st.chat_message("analytics"):
                            if "analytics" in v2:
                                if "knowledge_utility" in v2["analytics"]:
                                    similarity_utility_dict = v2["analytics"]["knowledge_utility"]["similarity_utility"]
                                    download_data.append({"role": "analytics", "content": "**knowledge Utility:**"})
                                    if "image_files" in v2["analytics"]["knowledge_utility"]:
                                        for image_key, image_values in v2["analytics"]["knowledge_utility"]["image_files"].items():
                                            for image_value in image_values:
                                                download_data.append({"role": "analytics", "image": st.session_state.session.session_analytics_folder_path + image_value})

                            chat_expander = st.expander("Analytics Results")
                            with chat_expander:
                                analytics_dict = {}
                                if "analytics" in v2:
                                    analytics_dict = v2["analytics"]
                                if "LLM" == v2["setting"]["type"]:
                                    if compare_agent_id_selected := st.selectbox("Select Compare Agent:", st.session_state.agent_list, index=st.session_state.agent_list_index, key=f"conpareAgent_list{k}_{k2}"):
                                        st.session_state.compare_agent_id = compare_agent_id_selected
                                    compare_col1, compare_col2 = st.columns(2)
                                    if compare_col1.button("Analytics Results - Compare Agents", key=f"conpareAgent_btn{k}_{k2}"):
                                        compare_seq = k
                                        compare_sub_seq = str(int(k2)-1)
                                        compare_agent_file = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.compare_agent_id), None)
                                        _, _, compare_response, compare_model_name, compare_export_contents, compare_knowledge_ref = dmva.genLLMAgentSimple(st.session_state.web_default_service, st.session_state.web_default_user, v2["setting"]["session_id"], v2["setting"]["session_name"], compare_agent_file, model_type="LLM", sub_seq=1, query=v2["prompt"]["query"]["input"], import_contents=[], situation=v2["prompt"]["query"]["situation"], prompt_temp_cd=v2["prompt"]["prompt_template"]["setting"], seq_limit=compare_seq, sub_seq_limit=compare_sub_seq)
                                        vec_response = dmu.embed_text(v2["response"]["text"])
                                        vec_compare_response = dmu.embed_text(compare_response)
                                        compare_diff = dmu.calculate_cosine_distance(vec_response, vec_compare_response)
                                        exec_agend_id = dma.get_agent_item(v2["setting"]["agent_file"], "DISPLAY_NAME")
                                        _, _, compare_text, compare_text_model_name, _, _ = dmt.compare_texts(st.session_state.web_default_service, st.session_state.web_default_user, exec_agend_id, v2["response"]["text"], st.session_state.compare_agent_id, compare_response)                                    
                                        if "compare_agents" not in analytics_dict:
                                            analytics_dict["compare_agents"] = []
                                        analytics_dict["compare_agents"].append({"compare_agent":{"agent_file": compare_agent_file, "model_name": compare_model_name, "response": compare_response, "diff": compare_diff, "knowledge_rag": compare_knowledge_ref}, "compare_text": {"compare_model_name": compare_text_model_name, "text": compare_text}})
                                        st.session_state.session.set_analytics_history(k, k2, analytics_dict)
                                        st.session_state.sidebar_message = f"比較分析を完了しました({k}_{k2})"
                                        st.rerun()
                                if v2["response"]["reference"]["knowledge_rag"]:
                                    ak_col1, ak_col2 = st.columns(2)
                                    st.session_state.analytics_knowledge_mode = ak_col2.radio("Analytics Knowledge Mode:", ["Default", "Norm(All)", "Norm(Group)"], index=1, key=f"akmode_{k}_{k2}")
                                    if ak_col1.button("Analytics Results - Knowledge Utility", key=f"knowledgeUtil_btn{k}_{k2}"):
                                        title = f"{k}-{k2}-{st.session_state.session.session_name}"
                                        references = []
                                        for reference_data in v2["response"]["reference"]["knowledge_rag"]:
                                            references.append(ast.literal_eval("{"+ reference_data.replace("\n", "").replace("$", "＄") + "}"))
                                        result = dmva.analytics_knowledge(title, references, st.session_state.session.session_analytics_folder_path, st.session_state.analytics_knowledge_mode)
                                        analytics_dict["knowledge_utility"] = result
                                        st.session_state.session.set_analytics_history(k, k2, analytics_dict)
                                        st.session_state.sidebar_message = f"知識活用性を分析しました({k}_{k2})"
                                        st.rerun()
                                if "compare_agents" in analytics_dict:
                                    chat_expander_compare = st.expander("Analytics Results - Compare Agents")
                                    with chat_expander_compare:
                                        compare_agents = analytics_dict["compare_agents"]
                                        compare_agent_labels = [
                                            f"{i+1}: {agent['compare_agent']['agent_file']} ({agent['compare_agent']['model_name']})"
                                            for i, agent in enumerate(compare_agents)
                                        ]
                                        selected_compare_idx = st.selectbox(
                                            "Select Compare Agent Result:",
                                            range(len(compare_agents)),
                                            format_func=lambda idx: compare_agent_labels[idx],
                                            key=f"compare_agent_select_{k}_{k2}"
                                        )
                                        compare_agent = compare_agents[selected_compare_idx]
                                        compare_agent_info = compare_agent["compare_agent"]
                                        st.markdown(f"Agent: {compare_agent_info['agent_file']}")
                                        st.markdown(f"Model: {compare_agent_info['model_name']}")
                                        st.markdown(f"Diff: {compare_agent_info['diff']}")
                                        if "knowledge_rag" in compare_agent_info:
                                            if compare_agent_info["knowledge_rag"]: #and "knowledge_utility" not in compare_agent_info:
                                                ak_compare_col1, ak_compare_col2 = st.columns(2)
                                                st.session_state.analytics_knowledge_mode_compare = ak_compare_col2.radio("Analytics Knowledge Mode:", ["Default", "Norm(All)", "Norm(Group)"], index=1, key=f"akmode_compare_{k}_{k2}")
                                                if ak_compare_col1.button("Analytics Results - Knowledge Utility", key=f"knowledgeUtil_btn{k}_{k2}_compare{selected_compare_idx}"):
                                                    compare_title = f"{k}-{k2}-{st.session_state.session.session_name}_compare{selected_compare_idx}"
                                                    compare_references = []
                                                    for compare_reference_data in compare_agent_info["knowledge_rag"]:
                                                        compare_references.append(ast.literal_eval("{"+ compare_reference_data.replace("\n", "").replace("$", "＄") + "}"))
                                                    compare_ref_result = dmva.analytics_knowledge(compare_title, compare_references, st.session_state.session.session_analytics_folder_path, st.session_state.analytics_knowledge_mode_compare)
                                                    analytics_dict["compare_agents"][selected_compare_idx]["compare_agent"]["knowledge_utility"] = compare_ref_result
                                                    st.session_state.session.set_analytics_history(k, k2, analytics_dict)
                                                    st.session_state.sidebar_message = f"知識活用性を分析しました({k}_{k2}_compare{selected_compare_idx})"
                                                    st.rerun()
                                        st.markdown("")
                                        st.markdown(compare_agent_info["response"].replace("\n", "<br>"), unsafe_allow_html=True)
                                        st.markdown("")
                                        st.markdown(f"**Compare Text:** {compare_agent['compare_text']['compare_model_name']}")
                                        st.markdown(compare_agent["compare_text"]["text"].replace("\n", "<br>"), unsafe_allow_html=True)
                                        st.markdown("")
                                        if "knowledge_utility" in compare_agent_info:
                                            chat_expander_analytics_compare = st.expander("Analytics Results - Knowledge Utility")
                                            with chat_expander_analytics_compare:
                                                compare_similarity_utility_dict = compare_agent_info["knowledge_utility"]["similarity_utility"]
                                                st.markdown("**knowledge Utility:**")
                                                st.markdown(", ".join(f"{k}: {v}" for k, v in compare_similarity_utility_dict.items()))
                                                if "image_files" in compare_agent_info["knowledge_utility"]:
                                                    for image_key, image_values in compare_agent_info["knowledge_utility"]["image_files"].items():
                                                        for image_value in image_values:
                                                            st.image(st.session_state.session.session_analytics_folder_path + image_value)
                                                            rag_category = os.path.splitext(image_value)[0].split("_")[-1]
                                                            for ak_dict in compare_agent_info["knowledge_utility"]["similarity_rank"][rag_category]:
                                                                st.markdown(ak_line(ak_dict))
                                if "knowledge_utility" in analytics_dict:
                                    chat_expander_analytics = st.expander("Analytics Results - Knowledge Utility")
                                    with chat_expander_analytics:
                                        similarity_utility_dict = analytics_dict["knowledge_utility"]["similarity_utility"]
                                        st.markdown("**knowledge Utility:**")
                                        st.markdown(", ".join(f"{k}: {v}" for k, v in similarity_utility_dict.items()))
                                        if "image_files" in analytics_dict["knowledge_utility"]:
                                            for image_key, image_values in analytics_dict["knowledge_utility"]["image_files"].items():
                                                for image_value in image_values:
                                                    st.image(st.session_state.session.session_analytics_folder_path + image_value)
                                                    rag_category = os.path.splitext(image_value)[0].split("_")[-1]
                                                    for ak_dict in analytics_dict["knowledge_utility"]["similarity_rank"][rag_category]:
                                                        st.markdown(ak_line(ak_dict))

            # 会話履歴の論理削除設定
            if st.checkbox(f"Delete(seq:{k})", key="del_chat_seq"+k):
                st.session_state.seq_memory.append(k)

    # ファイルアップローダー
    uploaded_files = st.file_uploader("Attached Files:", type=["txt", "csv", "json", "pdf", "jpg", "jpeg", "png", "mp3"], accept_multiple_files=True)
    st.session_state.uploaded_files = uploaded_files
    show_uploaded_files_widget(st.session_state.uploaded_files)

    # WEB検索の設定
    if st.checkbox("WEB Search", value=st.session_state.web_search):
        st.session_state.web_search = True
    else:
        st.session_state.web_search = False

    # BOOKから選択
    if "BOOK" in st.session_state.agent_data:
        st.session_state.book_selected = st.multiselect("BOOK", [item["RAG_NAME"] for item in st.session_state.agent_data["BOOK"]])

    # ファイルダウンローダー
    footer_col1, footer_col2 = st.columns(2)
    st.session_state.dl_type = footer_col1.radio("Download Mode:", ("Chats Only", "ALL"))
    dl_file_id = st.session_state.session.session_id +"_"+ st.session_state.session.session_name[:20]
    dl_data, dl_file_name, dl_mime = set_dl_file(download_data, st.session_state.dl_type, file_id=dl_file_id)
    footer_col2.download_button(label="Download(.md)", data=dl_data, file_name=dl_file_name, mime=dl_mime)
    
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

        # 知識の追加
        add_knowledges = []
        # BOOKの設定
        if st.session_state.book_selected:
            for book_data in st.session_state.agent_data["BOOK"]:
                if book_data["RAG_NAME"] in st.session_state.book_selected:
                    add_knowledges.append(book_data)

        # シチュエーションの設定
        situation = {}
        situation["TIME"] = time_setting
        situation["SITUATION"] = situation_setting

        # 実行の設定
        execution = {}
        execution["MEMORY_USE"] = st.session_state.memory_use
        execution["MEMORY_SAVE"] = st.session_state.memory_save
        execution["MEMORY_SIMILARITY"] = st.session_state.memory_similarity
        execution["MAGIC_WORD_USE"] = st.session_state.magic_word_use
        execution["STREAM_MODE"] = st.session_state.stream_mode
        execution["SAVE_DIGEST"] = st.session_state.save_digest
        execution["META_SEARCH"] = st.session_state.meta_search
        execution["RAG_QUERY_GENE"] = st.session_state.RAG_query_gene
        execution["WEB_SEARCH"] = st.session_state.web_search
        
        # ユーザー入力の一時表示
        with st.chat_message("User"):
            st.markdown(user_input.replace("\n", "<br>"), unsafe_allow_html=True)
        with st.chat_message(st.session_state.web_title):
            response_placeholder = st.empty()
            response = ""
            for response_service_info, response_user_info, response_chunk in dme.DigiMatsuExecute_Practice(st.session_state.web_default_service, st.session_state.web_default_user, st.session_state.session.session_id, st.session_state.session.session_name, st.session_state.agent_file, user_input, uploaded_contents, situation, overwrite_items, add_knowledges, execution):
                response += response_chunk
                response_placeholder.markdown(response)
            st.session_state.sidebar_message = ""
            st.rerun()

if __name__ == "__main__":
    main()