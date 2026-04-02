import os
import re
import ast
import json
import datetime
from datetime import datetime
import pytz
from dotenv import load_dotenv
import streamlit as st
import pandas as pd
from dataclasses import dataclass
from typing import Any, Dict

import DigiM_Execute as dme
import DigiM_Session as dms
import DigiM_Agent as dma
import DigiM_Context as dmc
import DigiM_Util as dmu
import DigiM_Tool as dmt
import DigiM_GeneCommunication as dmgc
import DigiM_GeneUserDialog as dmgu
import DigiM_VAnalytics as dmva
import DigiM_DB_Export as dmdbe
import DigiM_SupportEval as dmse

@dataclass(frozen=True)
class AppConfig:
    # setting.yaml
    session_folder_prefix: str
    agent_folder_path: str
    temp_folder_path: str
    mst_folder_path: str

    # system.env
    web_title: str
    timezone: str
    login_enable_flg: str | None
    user_mst_file: str | None
    user_dialog_auto_save_flg: str | None
    web_default_service: Dict[str, Any]
    web_default_user: Dict[str, Any]
    web_default_agent_file: str | None

@st.cache_resource(show_spinner=False)
def load_config() -> AppConfig:
    # system.env は基本固定。ここで 1 回だけ読む
    if os.path.exists("system.env"):
        load_dotenv("system.env")

    system_setting_dict = dmu.read_yaml_file("setting.yaml")

    return AppConfig(
        session_folder_prefix=system_setting_dict["SESSION_FOLDER_PREFIX"],
        agent_folder_path=system_setting_dict["AGENT_FOLDER"],
        temp_folder_path=system_setting_dict["TEMP_FOLDER"],
        mst_folder_path=system_setting_dict["MST_FOLDER"],

        web_title=os.getenv("WEB_TITLE") or "Digital Twin",
        timezone=os.getenv("TIMEZONE") or "Asia/Tokyo",
        login_enable_flg=os.getenv("LOGIN_ENABLE_FLG"),
        user_mst_file=os.getenv("USER_MST_FILE"),
        user_dialog_auto_save_flg=os.getenv("USER_DIALOG_AUTO_SAVE_FLG"),
        web_default_service=json.loads(os.getenv("WEB_DEFAULT_SERVICE") or "{}"),
        web_default_user=json.loads(os.getenv("WEB_DEFAULT_USER") or "{}"),
        web_default_agent_file=os.getenv("WEB_DEFAULT_AGENT_FILE"),
    )

# 設定のキャッシュ
cfg = load_config()

# setting.yamlからフォルダパスなどを設定
session_folder_prefix = cfg.session_folder_prefix
agent_folder_path = cfg.agent_folder_path
temp_folder_path = cfg.temp_folder_path
mst_folder_path = cfg.mst_folder_path

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
web_title = cfg.web_title
login_enable_flg = cfg.login_enable_flg
user_mst_file = cfg.user_mst_file
web_default_service = cfg.web_default_service
web_default_service_id = web_default_service["SERVICE_ID"]
web_default_user = cfg.web_default_user
web_default_user_id = web_default_user["USER_ID"]

if 'default_agent' not in st.session_state:
    default_agent_data = dmu.read_json_file(cfg.web_default_agent_file, agent_folder_path)
    st.session_state.default_agent = default_agent_data["DISPLAY_NAME"]
if 'service_id' not in st.session_state:
    st.session_state.service_id = web_default_service_id
if 'user_id' not in st.session_state:
    st.session_state.user_id = web_default_user_id
if 'user_admin_flg' not in st.session_state:
    st.session_state.user_admin_flg = "Y"
if 'group_cd' not in st.session_state:
    st.session_state.group_cd = "All"
if 'allowed_rag_management' not in st.session_state:
    st.session_state.allowed_rag_management = True
if 'allowed_exec_setting' not in st.session_state:
    st.session_state.allowed_exec_setting = True
if 'allowed_rag_setting' not in st.session_state:
    st.session_state.allowed_rag_setting = True
if 'allowed_feedback' not in st.session_state:
    st.session_state.allowed_feedback = True
if 'allowed_details' not in st.session_state:
    st.session_state.allowed_details = True
if 'allowed_analytics_knowledge' not in st.session_state:
    st.session_state.allowed_analytics_knowledge = True
if 'allowed_analytics_compare' not in st.session_state:
    st.session_state.allowed_analytics_compare = True
if 'allowed_web_search' not in st.session_state:
    st.session_state.allowed_web_search = True
if 'allowed_book' not in st.session_state:
    st.session_state.allowed_book = True
if 'allowed_download_md' not in st.session_state:
    st.session_state.allowed_download_md = True
if 'allowed_session_archive' not in st.session_state:
    st.session_state.allowed_session_archive = True
if 'allowed_web_api' not in st.session_state:
    st.session_state.allowed_web_api = True
if 'allowed_support_eval' not in st.session_state:
    st.session_state.allowed_support_eval = True
if 'eval_results_excel' not in st.session_state:
    st.session_state.eval_results_excel = None
if 'eval_summary' not in st.session_state:
    st.session_state.eval_summary = None
if 'last_archive_zip' not in st.session_state:
    st.session_state.last_archive_zip = None
if '_bg_task' not in st.session_state:
    st.session_state._bg_task = None

# DB接続情報が設定されているか確認
_db_configured = all([
    os.getenv("POSTGRES_HOST"),
    os.getenv("POSTGRES_DB"),
    os.getenv("POSTGRES_USER"),
    os.getenv("POSTGRES_PASSWORD"),
])

# 時刻の設定
tz = pytz.timezone(cfg.timezone)
now_time = datetime.now(tz)

# Streamlitの設定
st.set_page_config(page_title=web_title, layout="wide")

# ユーザーログイン
def load_user_master():
    user_mst_path = mst_folder_path + user_mst_file
    try:
        with open(user_mst_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return {}

# ログインユーザー情報の保持
def save_user_master(users: dict):
    """ユーザーマスタを保存（PWは平文/ハッシュどちらも許容）"""
    user_mst_path = mst_folder_path + user_mst_file
    # mst_folder_path が存在しない場合に備える
    os.makedirs(os.path.dirname(user_mst_path), exist_ok=True)
    with open(user_mst_path, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

# パスワード変更
def change_password(user_id: str, current_pw: str, new_pw: str) -> tuple[bool, str]:
    """ログイン中ユーザーのパスワード変更。成功時はハッシュで保存する。"""
    users = load_user_master()
    user_info = users.get(user_id)
    if not user_info:
        return False, "ユーザーが見つかりませんでした。"
    stored_pw = user_info.get("PW", "")
    if not dmu.verify_password(current_pw, stored_pw):
        return False, "現在のパスワードが正しくありません。"

    # 新PWをハッシュ化して保存（UIからは必ずハッシュ保存）
    users[user_id]["PW"] = dmu.hash_password(new_pw)
    save_user_master(users)
    return True, "パスワードを変更しました。"

# ログインユーザー情報をセッションに設定
def set_login_user_to_session(user_id: str, user_info: dict):
    st.session_state.login_user = {
        "USER_ID": user_id,
        "Name": user_info.get("Name", ""),
        "Group": user_info.get("Group", ""),
        "Agent": user_info.get("Agent", ""),
        "Allowed": user_info.get("Allowed", {})
    }
    st.session_state.user_id = user_id
    st.session_state.session_user_id = st.session_state.user_id
    st.session_state.user_admin_flg = "Y" if st.session_state.login_user["Group"] == "Admin" else "N"
    if st.session_state.login_user["Group"]:
        st.session_state.group_cd = st.session_state.login_user["Group"]
    if st.session_state.login_user["Agent"] == "DEFAULT":
        default_agent_data = dmu.read_json_file(cfg.web_default_agent_file, agent_folder_path)
        st.session_state.default_agent = default_agent_data["DISPLAY_NAME"]
    else:
        default_agent_data = dmu.read_json_file(st.session_state.login_user["Agent"], agent_folder_path)
        st.session_state.default_agent = default_agent_data["DISPLAY_NAME"]
    if st.session_state.login_user["Allowed"]:
        user_allowed_parameter(st.session_state.login_user["Allowed"])

# ログイン処理
def ensure_login():
    # すでにログイン済みなら何もしない
    if "login_user" in st.session_state and st.session_state.login_user:
        return

    st.title(web_title)
    st.subheader("Login:")

    # ユーザーマスタの読み込み
    users = load_user_master()
    if not users:
        st.error("users.json が読めませんでした。")
        st.stop()

    tab_login, tab_change = st.tabs(["Login", "Change Password"])

    # ログインフォーム
    with tab_login:
        with st.form("login_form"):
            input_user_id = st.text_input("User ID")
            input_pw = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

        if submitted:
            user_info = users.get(input_user_id)
            stored_pw = (user_info or {}).get("PW", "")

            # PWは平文/ハッシュの両対応（DigiM_Util.verify_password が判定）
            if user_info and dmu.verify_password(input_pw, stored_pw):
                # 旧仕様（平文PW）のままログインできた場合は、次回以降のために自動でハッシュへ移行
                if stored_pw and not (isinstance(stored_pw, str) and stored_pw.startswith(("$2a$", "$2b$", "$2y$"))):
                    try:
                        users[input_user_id]["PW"] = dmu.hash_password(input_pw)
                        save_user_master(users)
                    except Exception:
                        # 移行に失敗してもログイン自体は継続
                        pass

                set_login_user_to_session(input_user_id, user_info)
                st.success("ログインしました")
                refresh_session_states()
                st.rerun()
            else:
                st.error("ユーザーID または パスワードが正しくありません")

    # --- Change Password (ログイン前に実施できる方式：User ID + 現在PWで本人確認) ---
    with tab_change:
        st.caption("User ID と現在のパスワードを入力して、パスワードを変更します。")
        with st.form("change_password_form"):
            cp_user_id = st.text_input("User ID", key="cp_user_id")
            cp_current_pw = st.text_input("Current Password", type="password", key="cp_current_pw")
            cp_new_pw = st.text_input("New Password", type="password", key="cp_new_pw")
            cp_new_pw2 = st.text_input("New Password (confirm)", type="password", key="cp_new_pw2")
            cp_submit = st.form_submit_button("Change Password")

        if cp_submit:
            user_info = users.get(cp_user_id)
            stored_pw = (user_info or {}).get("PW", "")

            if not user_info:
                st.error("ユーザーID が見つかりません")
            elif not dmu.verify_password(cp_current_pw, stored_pw):
                st.error("現在のパスワードが正しくありません")
            elif not cp_new_pw:
                st.error("新しいパスワードを入力してください")
            elif cp_new_pw != cp_new_pw2:
                st.error("新しいパスワード（確認）が一致しません")
            else:
                try:
                    users[cp_user_id]["PW"] = dmu.hash_password(cp_new_pw)
                    save_user_master(users)
                    st.success("パスワードを変更しました。Login タブからログインしてください。")
                except Exception as e:
                    st.error(f"保存に失敗しました: {e}")

    # ここで処理を止めて、ログイン画面以降を表示させない
    st.stop()

# ユーザーの利用可能な画面機能の設定
def user_allowed_parameter(allowded_dict):
    st.session_state.allowed_rag_management = allowded_dict.get("RAG Management", True)
    st.session_state.allowed_exec_setting = allowded_dict.get("Exec Setting", True)
    st.session_state.allowed_rag_setting = allowded_dict.get("RAG Setting", True)
    st.session_state.allowed_feedback = allowded_dict.get("Feedback", True)
    st.session_state.allowed_details = allowded_dict.get("Details", True)
    st.session_state.allowed_analytics_knowledge = allowded_dict.get("Analytics Knowledge", True)
    st.session_state.allowed_analytics_compare = allowded_dict.get("Analytics Compare", True)
    st.session_state.allowed_web_search = allowded_dict.get("WEB Search", True)
    st.session_state.allowed_book = allowded_dict.get("Book", True)
    st.session_state.allowed_download_md = allowded_dict.get("Download Md", True)
    st.session_state.allowed_session_archive = allowded_dict.get("Session Archive", True)
    st.session_state.allowed_web_api = allowded_dict.get("Web API", True)
    st.session_state.allowed_support_eval = allowded_dict.get("Support Eval", True)

# バックグラウンドタスク実行ヘルパー
import threading as _threading

import json as _json
_BG_TASK_FILE = "/tmp/digim_bg_task_{}.json"

def _bg_task_path():
    sid = st.session_state.get("user_id", "default")
    return _BG_TASK_FILE.format(sid)

def _read_bg_task_status():
    try:
        with open(_bg_task_path(), "r") as f:
            return _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        return {}

def _write_bg_task_status_to(path, data):
    with open(path, "w") as f:
        _json.dump(data, f)

def _clear_bg_task_status():
    import os as _os
    try:
        _os.remove(_bg_task_path())
    except FileNotFoundError:
        pass

def _run_bg_task(task_type, message, func, *args, **kwargs):
    """バックグラウンドでタスクを実行し、完了時にファイルフラグを立てる"""
    st.session_state._bg_task = {"type": task_type, "message": message}
    _task_file = _bg_task_path()
    _write_bg_task_status_to(_task_file, {"status": "running", "message": message, "error": ""})

    def _worker():
        import logging as _logging
        _log = _logging.getLogger("bg_task")
        try:
            _log.info(f"[BG_TASK] start: {task_type} - {message}")
            func(*args, **kwargs)
            _log.info(f"[BG_TASK] done: {task_type}")
            _write_bg_task_status_to(_task_file, {"status": "done", "message": message, "error": ""})
        except Exception as e:
            _log.error(f"[BG_TASK] error: {task_type} - {e}", exc_info=True)
            _write_bg_task_status_to(_task_file, {"status": "done", "message": message, "error": str(e)})

    _threading.Thread(target=_worker, daemon=True).start()

# セッションステートの初期宣言
def initialize_session_states():
    if 'web_service' not in st.session_state:
        st.session_state.web_service = dict(web_default_service)
        st.session_state.web_service["SERVICE_ID"] = st.session_state.service_id
    if 'web_user' not in st.session_state:
        st.session_state.web_user = dict(web_default_user)
        st.session_state.web_user["USER_ID"] = st.session_state.user_id
    if 'sidebar_message' not in st.session_state:
        st.session_state.sidebar_message = ""
    if 'is_processing' not in st.session_state:
        st.session_state.is_processing = False
    if 'pending_input' not in st.session_state:
        st.session_state.pending_input = ""
    if '_fragment_was_locked' not in st.session_state:
        st.session_state._fragment_was_locked = False
    if '_bg_user_input' not in st.session_state:
        st.session_state._bg_user_input = ""
    if 'display_name' not in st.session_state:
        st.session_state.display_name = st.session_state.default_agent
    if 'agents' not in st.session_state:
        st.session_state.agents = dma.get_display_agents(st.session_state.group_cd)
    if 'agent_list' not in st.session_state:
        st.session_state.agent_list = [a1["AGENT"] for a1 in st.session_state.agents]
    if 'agent_list_index' not in st.session_state:
        st.session_state.agent_list_index = st.session_state.agent_list.index(st.session_state.display_name)
    if 'agent_id' not in st.session_state:
        st.session_state.agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    if 'compare_agent_id' not in st.session_state:
        st.session_state.compare_agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    if 'compare_engine_name' not in st.session_state:
        st.session_state.compare_engine_name = ""
    if 'compare_imagegen_engine_name' not in st.session_state:
        st.session_state.compare_imagegen_engine_name = ""
    if 'agent_file' not in st.session_state:
        st.session_state.agent_file = st.session_state.agents[st.session_state.agent_list_index]["FILE"]
    if 'agent_data' not in st.session_state:
        st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
    if 'engine_name' not in st.session_state:
        st.session_state.engine_name = st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
    if 'imagegen_engine_name' not in st.session_state:
        st.session_state.imagegen_engine_name = st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")
    if 'rag_data_list' not in st.session_state:
        st.session_state.rag_data_list = dmc.get_rag_list()
    if 'rag_data_list_selected' not in st.session_state:
        st.session_state.rag_data_list_selected = []
    if 'session_list' not in st.session_state:
        st.session_state.session_list = dms.get_session_list_visible(st.session_state.service_id, st.session_state.user_id, "Y")
    if 'session_inactive_list' not in st.session_state:
        st.session_state.session_inactive_list = dms.get_session_list_inactive_visible(st.session_state.service_id, st.session_state.user_id, "Y")
    if 'session_inactive_list_selected' not in st.session_state:
        st.session_state.session_inactive_list_selected = []
    if 'session' not in st.session_state:
        st.session_state.session = dms.DigiMSession(dms.set_new_session_id(), "New Chat")
    if 'session_service_id' not in st.session_state:
        st.session_state.session_service_id = st.session_state.service_id
    if 'session_user_id' not in st.session_state:
        st.session_state.session_user_id = st.session_state.user_id
    if 'time_setting' not in st.session_state:
        st.session_state.time_setting = now_time.strftime("%Y/%m/%d %H:%M:%S")
    if 'time_mode' not in st.session_state:
        st.session_state.time_mode = "No Date"
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
    if 'private_mode' not in st.session_state:
        st.session_state.private_mode = False
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
    if 'analytics_dimension_mode' not in st.session_state:
        st.session_state.analytics_dimension_mode = {}
    if 'analytics_knowledge_mode_compare' not in st.session_state:
        st.session_state.analytics_knowledge_mode_compare = ""
    if 'analytics_dimension_mode_compare' not in st.session_state:
        st.session_state.analytics_dimension_mode_compare = {}

# セッション変数のリフレッシュ
def refresh_session_states():
    st.session_state.web_service = dict(web_default_service)
    st.session_state.web_service["SERVICE_ID"] = st.session_state.service_id
    st.session_state.web_user = dict(web_default_user)
    st.session_state.web_user["USER_ID"] = st.session_state.user_id
    st.session_state.sidebar_message = ""
    st.session_state.display_name = st.session_state.default_agent
    st.session_state.agents = dma.get_display_agents(st.session_state.group_cd)
    st.session_state.agent_list = [a1["AGENT"] for a1 in st.session_state.agents]
    st.session_state.agent_list_index = st.session_state.agent_list.index(st.session_state.display_name)
    st.session_state.agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    st.session_state.compare_agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    st.session_state.agent_file = st.session_state.agents[st.session_state.agent_list_index]["FILE"]
    st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
    st.session_state.rag_data_list = dmc.get_rag_list()
    st.session_state.rag_data_list_selected = []
    st.session_state.session_list = dms.get_session_list_visible(st.session_state.service_id, st.session_state.user_id, st.session_state.user_admin_flg)
    st.session_state.session_inactive_list = dms.get_session_list_inactive_visible(st.session_state.service_id, st.session_state.user_id, st.session_state.user_admin_flg)
    st.session_state.session_inactive_list_selected = []
    st.session_state.session = dms.DigiMSession(dms.set_new_session_id(), "New Chat")
#    st.session_state.session_service_id, st.session_state.session_user_id = dms.get_history_ids(dms.get_session_data(st.session_state.session.session_id))
    st.session_state.session_service_id, st.session_state.session_user_id = dms.get_ids(st.session_state.session.session_id)
    if st.session_state.session_service_id == "":
        st.session_state.session_service_id = st.session_state.service_id
    if st.session_state.session_user_id == "":
        st.session_state.session_user_id = st.session_state.user_id
    if st.session_state.time_mode == "Real Date":
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
    st.session_state.analytics_dimension_mode = {}
    st.session_state.analytics_knowledge_mode_compare = ""
    st.session_state.analytics_dimension_mode_compare = {}

# セッションのリフレッシュ（ヒストリーを更新するために、同一セッションIDで再度Sessionクラスを呼び出すこともある）
def refresh_session(session_id, session_name, situation, new_session_flg=False):
    st.session_state._bg_user_input = ""
    st.session_state.is_processing = False
    st.session_state.session = dms.DigiMSession(session_id, session_name)
#    st.session_state.session_service_id, st.session_state.session_user_id = dms.get_history_ids(dms.get_session_data(session_id))
    st.session_state.session_service_id, st.session_state.session_user_id = dms.get_ids(session_id)
    if st.session_state.session_service_id == "":
        st.session_state.session_service_id = st.session_state.service_id
    if st.session_state.session_user_id == "":
        st.session_state.session_user_id = st.session_state.user_id
    if new_session_flg:
        st.session_state.display_name = st.session_state.default_agent
    else:
        session_agent_file = dms.get_agent_file(st.session_state.session.session_id)
        if os.path.exists(agent_folder_path + session_agent_file):
            st.session_state.display_name = dma.get_agent_item(session_agent_file, "DISPLAY_NAME")
            # セッションの最後に使用されたエンジン名を復元
            last_engine = dms.get_last_engine_name(st.session_state.session.session_id)
            agent_data = dmu.read_json_file(session_agent_file, agent_folder_path)
            engine_list = dma.get_engine_list(agent_data, "LLM")
            if last_engine and last_engine in engine_list:
                st.session_state.engine_name = last_engine
            else:
                st.session_state.engine_name = agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
        else:
            st.session_state.display_name = st.session_state.default_agent
    st.session_state.time_setting = situation.get("TIME", "")
    st.session_state.time_mode = "Custom Date" if situation.get("TIME") else "No Date"
    st.session_state.situation_setting = situation["SITUATION"]
    st.session_state.seq_memory = []
    st.session_state.sidebar_message = ""
    st.session_state.overwrite_flg_persona = False
    st.session_state.overwrite_flg_prompt_temp = False
    st.session_state.overwrite_flg_rag = False
    #st.rerun()

# セッションリストのリフレッシュ
def refresh_session_list(service_id, user_id, user_admin_flg):
    st.session_state.session_list = dms.get_session_list_visible(service_id, user_id, user_admin_flg)
    st.session_state.session_inactive_list = dms.get_session_list_inactive_visible(service_id, user_id, user_admin_flg)
    st.session_state.session_inactive_list_selected = []

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

    # ログイン処理の実行
    if login_enable_flg == "Y":
        ensure_login()

    # サイドバーの設定
    with st.sidebar:
        st.title(web_title)

        # ログインユーザー情報の表示
        if login_enable_flg == "Y":
            if "login_user" in st.session_state and st.session_state.login_user:
                lu = st.session_state.login_user
                st.markdown(f"User: {lu.get('Name', '')}")
                if st.button("Logout"):
                    for key in ["login_user", "service_id", "user_id"]:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.rerun()

        # エージェントを選択（JSON)
        if agent_id_selected := st.selectbox("Select Agent:", st.session_state.agent_list, index=st.session_state.agent_list_index):
            st.session_state.agent_id = agent_id_selected
            st.session_state.agent_file = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.agent_id), None)
            st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
            st.session_state.engine_name = st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
            st.session_state.imagegen_engine_name = st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")

        side_col1, side_col2 = st.columns(2)

        # 新しいセッションを発番（IDを指定して、新規にセッションリフレッシュ）
        if side_col1.button("New Chat", key="new_chat"):
            session_id = dms.set_new_session_id()
            session_name = "New Chat"
            situation = {}
            situation["TIME"] = ""
            situation["SITUATION"] = ""
            refresh_session_states()
            refresh_session(session_id, session_name, situation, True)

        # 会話履歴の更新
        if side_col2.button("Refresh List", key="refresh_session_list"):
            refresh_session_list(st.session_state.service_id, st.session_state.user_id, st.session_state.user_admin_flg)

        # エージェントのエンジンを選択
        engines_expander = st.expander("Engines")
        with engines_expander:
            # LLMエンジン選択
            _engine_list = dma.get_engine_list(st.session_state.agent_data, model_type="LLM")
            if _engine_list:
                _engine_index = _engine_list.index(st.session_state.engine_name) if st.session_state.engine_name in _engine_list else 0
                st.session_state.engine_name = st.selectbox("Select Engine(LLM):", _engine_list, index=_engine_index)

            # IMAGEGENエンジン選択
            _imagegen_engine_list = dma.get_engine_list(st.session_state.agent_data, model_type="IMAGEGEN")
            if _imagegen_engine_list:
                _imagegen_index = _imagegen_engine_list.index(st.session_state.imagegen_engine_name) if st.session_state.imagegen_engine_name in _imagegen_engine_list else 0
                st.session_state.imagegen_engine_name = st.selectbox("Select Engine(IMAGEGEN):", _imagegen_engine_list, index=_imagegen_index)

        # セッションの管理
        sessions_expander = st.expander("Sessions")
        with sessions_expander:
            num_session_visible = st.number_input(label="Visible Sessions", value=5, step=1, format="%d")
            st.session_state.session_inactive_list = dms.get_session_list_inactive()
            st.session_state.session_inactive_list_selected = st.multiselect("Activate Sessions", [f"{item['id']}_{item['name']}" for item in st.session_state.session_inactive_list])
            if st.button("Activate", key="activate_sessions"):
                for session_list_selected in st.session_state.session_inactive_list_selected:
                    session_id_selected = session_list_selected.split("_")[0]
                    activate_session = dms.DigiMSession(session_id_selected)
                    activate_session.save_active_session("Y")
                    activate_session.save_user_dialog_session("UNSAVED")
                activate_sessions_str = ", ".join(st.session_state.session_inactive_list_selected)
                st.session_state.sidebar_message = f"セッションを再表示しました({activate_sessions_str})"
                st.rerun()

            # DB Export / Archive（Session Archiveが許可されたユーザーのみ表示）
            if st.session_state.allowed_session_archive:
                st.markdown("---")

                # DB Exportボタン（接続情報が設定されている場合のみ表示）
                if _db_configured:
                    if st.button("Export to DB", key="db_export"):
                        with st.spinner("DBへエクスポート中..."):
                            try:
                                dmdbe.main()
                                st.session_state.sidebar_message = "DBエクスポートが完了しました"
                            except Exception as e:
                                st.session_state.sidebar_message = f"DBエクスポートでエラーが発生しました: {e}"
                        with st.spinner("ベクトル化中..."):
                            try:
                                dmdbe.vectorize_dialogs()
                            except Exception as e:
                                st.session_state.sidebar_message += f" / ベクトル化でエラーが発生しました: {e}"
                        st.rerun()

                # Archiveボタン
                if st.button("Archive Old Sessions", key="archive_sessions"):
                    with st.spinner("アーカイブ中..."):
                        try:
                            result = dms.archive_old_sessions()
                            archived_count = len(result["archived"])
                            st.session_state.sidebar_message = f"アーカイブ完了: {archived_count}件を圧縮しました"
                            st.session_state.last_archive_zip = result["zip_path"]
                        except Exception as e:
                            st.session_state.sidebar_message = f"アーカイブでエラーが発生しました: {e}"
                            st.session_state.last_archive_zip = None
                    st.rerun()

                # アーカイブZipのダウンロード（常時表示）
                _archive_dir = dms.archive_folder
                _zip_files = sorted(
                    [f for f in os.listdir(_archive_dir) if f.endswith(".zip")],
                    reverse=True,
                ) if os.path.exists(_archive_dir) else []
                if _zip_files:
                    _selected_zip = st.selectbox("Archive ZIP", _zip_files, key="selected_archive_zip")
                    _selected_zip_path = os.path.join(_archive_dir, _selected_zip)
                    with open(_selected_zip_path, "rb") as f:
                        st.download_button(
                            label="Download ZIP",
                            data=f,
                            file_name=_selected_zip,
                            mime="application/zip",
                            key="download_archive_zip",
                        )
                else:
                    st.caption("アーカイブZIPはありません")

        # 知識更新の処理
        if st.session_state.allowed_rag_management:
            rag_expander = st.expander("RAG Management")
            with rag_expander:
                # RAGの更新処理
                if st.button("Update RAG Data", key="update_rag", disabled=bool(st.session_state._bg_task)):
                    def _rag_update():
                        dmc.generate_rag()
                        if cfg.user_dialog_auto_save_flg == "Y":
                            dmgu.save_user_dialogs(st.session_state.web_service, st.session_state.web_user)
                    _run_bg_task("rag", "RAGデータを更新中", _rag_update)
                    st.rerun()

                # RAGの削除処理(未選択は全削除)
                st.session_state.rag_data_list_selected = st.multiselect("RAG DB", st.session_state.rag_data_list)
                if st.button("Delete RAG DB", key="delete_rag_db"):
                    dmc.del_rag_db(st.session_state.rag_data_list_selected)
                    st.session_state.sidebar_message = "RAGを削除しました"
                    st.session_state.rag_data_list = dmc.get_rag_list()

                # セッションのユーザーダイアログ保存
                if cfg.user_dialog_auto_save_flg == "N":
                    if st.button("Save User Dialog", key="save_user_dialog"):
                        dmgu.save_user_dialogs(st.session_state.web_service, st.session_state.web_user)
                        st.session_state.sidebar_message = "ユーザーダイアログを保存しました"

        # Web API管理
        if st.session_state.allowed_web_api:
            api_expander = st.expander("Web API")
            with api_expander:
                import subprocess
                # FastAPIプロセスの状態確認
                _api_check = subprocess.run(
                    ["pgrep", "-f", "uvicorn DigiM_API:app"],
                    capture_output=True, text=True
                )
                _api_running = _api_check.returncode == 0

                if _api_running:
                    st.success("FastAPI: Running (port 8899)")
                    if st.button("Stop API Server", key="stop_api"):
                        subprocess.run(["pkill", "-f", "uvicorn DigiM_API:app"])
                        st.session_state.sidebar_message = "FastAPIを停止しました"
                        st.rerun()
                else:
                    st.warning("FastAPI: Stopped")
                    if st.button("Start API Server", key="start_api"):
                        subprocess.Popen(
                            ["uvicorn", "DigiM_API:app", "--host", "0.0.0.0", "--port", "8899"],
                            stdout=open("/var/log/digim_api.log", "a"),
                            stderr=subprocess.STDOUT,
                            start_new_session=True
                        )
                        import time
                        time.sleep(2)
                        st.session_state.sidebar_message = "FastAPIを起動しました"
                        st.rerun()

                # ヘルスチェック
                if _api_running:
                    if st.button("Health Check", key="api_health"):
                        try:
                            import urllib.request
                            with urllib.request.urlopen("http://localhost:8899/health", timeout=5) as resp:
                                _health = resp.read().decode()
                            st.code(_health)
                        except Exception as e:
                            st.error(f"Health Check Failed: {e}")

        # サポートエージェント評価
        if st.session_state.allowed_support_eval:
            eval_expander = st.expander("Support Eval")
            with eval_expander:
                # 現在のエージェントのサポートエージェント情報を取得
                _agent_file = st.session_state.get("agent_file", "")
                _eval_targets = {}
                if _agent_file:
                    try:
                        _eval_targets = dmse.get_support_targets(_agent_file)
                    except Exception:
                        pass

                if not _eval_targets:
                    st.info("サポートエージェント未設定")
                else:
                    # 評価対象の選択
                    _target_options = {v["label"]: k for k, v in _eval_targets.items()}
                    _target_options["両方"] = "both"
                    _selected_label = st.selectbox("対象", list(_target_options.keys()), key="eval_target_select")
                    _selected_target = _target_options[_selected_label]

                    # エンジン一覧の取得（選択対象に応じて）
                    _all_engines = []
                    for k, v in _eval_targets.items():
                        if _selected_target in ("both", k):
                            _all_engines.extend(v["engines"])
                    _all_engines = list(dict.fromkeys(_all_engines))
                    _selected_engines = st.multiselect("エンジン", _all_engines, default=_all_engines, key="eval_engines")

                    # 質問数
                    _num_questions = st.number_input("質問数", min_value=1, max_value=20, value=3, key="eval_num_q")

                    # 質問入力（テキストエリア）
                    _default_questions = "AIガバナンスについてどう思う？\n最近読んだ本で面白かったのは？\n自己紹介してください"
                    _questions_text = st.text_area("質問（改行区切り）", value=_default_questions,
                                                   height=80, key="eval_questions")
                    _questions = [q.strip() for q in _questions_text.strip().split("\n") if q.strip()][:_num_questions]

                    # 実行
                    if st.button("評価実行", key="run_support_eval"):
                        if not _selected_engines:
                            st.warning("エンジンを選択してください")
                        elif not _questions:
                            st.warning("質問を入力してください")
                        else:
                            _progress = st.progress(0, text="準備中...")
                            def _update_progress(ratio, text):
                                _progress.progress(ratio, text=text)
                            try:
                                _results, _summary, _excel = dmse.run_eval_for_ui(
                                    _agent_file, _selected_target, _selected_engines,
                                    _questions, progress_callback=_update_progress
                                )
                                st.session_state.eval_results_excel = _excel
                                st.session_state.eval_summary = _summary
                                _progress.progress(1.0, text="完了")
                            except Exception as e:
                                st.error(f"評価エラー: {e}")
                                _progress.empty()

                    # 結果サマリー表示
                    if st.session_state.eval_summary:
                        st.dataframe(pd.DataFrame(st.session_state.eval_summary), hide_index=True)

                    # Excelダウンロード
                    if st.session_state.eval_results_excel:
                        st.download_button(
                            label="結果Excel",
                            data=st.session_state.eval_results_excel,
                            file_name=f"support_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key="download_eval_excel"
                        )

        # バックグラウンドタスクモニター
        if st.session_state._bg_task:
            _task_status = _read_bg_task_status()
            if _task_status.get("status") == "done":
                if _task_status.get("error"):
                    st.error(f"エラー: {_task_status['error']}")
                else:
                    st.session_state.sidebar_message = f"{_task_status.get('message', '')}が完了しました"
                st.session_state._bg_task = None
                _clear_bg_task_status()
                st.rerun()
            else:
                @st.fragment(run_every=2)
                def _task_monitor():
                    _ts = _read_bg_task_status()
                    if _ts.get("status") == "done":
                        st.session_state._bg_task_refresh = True
                        st.rerun(scope="app")
                    st.info(f"⏳ {_ts.get('message', '実行中...')}")
                _task_monitor()

        st.write(st.session_state.sidebar_message)

        st.markdown("----")
        # セッションリストの表示
        num_sessions = 0
        for session_dict in st.session_state.session_list:
            try:
                if num_session_visible > num_sessions:
                    session_id_list = session_dict["id"]
                    session_key_list = session_folder_prefix + session_id_list
                    session_list = dms.DigiMSession(session_id_list)
                    session_name_list = session_list.session_name
                    session_active_flg = session_list.get_active_session()
                    if session_active_flg != "N":
                        if bool(re.fullmatch(r"[+-]?\d+(\.\d+)?", session_id_list)):
                            session_name_btn = session_id_list +"_"+ session_name_list
                        else:
                            session_name_btn = session_name_list
                        session_name_btn = session_name_btn[:15]
                        situation = dms.get_situation(session_id_list)                
                        if not situation:
                            situation["TIME"] = now_time.strftime("%Y/%m/%d %H:%M:%S")
                            situation["SITUATION"] = ""
                        if st.button(session_name_btn, key=session_key_list):
                            refresh_session_states()
                            refresh_session(session_id_list, session_name_list, situation)
#                        if st.button(f"Del:{session_id_list}", key=f"{session_key_list}_del_btn"):
                        if st.button(f"Del", key=f"{session_key_list}_del_btn"):
                            del_session = dms.DigiMSession(session_id_list, session_name_list)
                            del_session.save_active_session("N")
                            del_session.save_user_dialog_session("DISCARD")
                            st.session_state.sidebar_message = f"セッションを非表示にしました({session_id_list}_{session_name_list})"
                            st.rerun()
                        num_sessions += 1
            except Exception as e:
                sid = session_dict["id"]
                st.warning(f"セッション {sid} の描画でエラーのためスキップしました: {e}")
                continue

    # チャットセッション名の設定
    if session_name := st.text_input("Chat Name:", value=st.session_state.session.session_name):
        st.session_state.session = dms.DigiMSession(st.session_state.session.session_id, session_name)
        if session_name != dms.get_session_name(st.session_state.session.session_id) and dms.get_session_name(st.session_state.session.session_id) != "":
            if st.button("Change Session Name", key="chg_session_name"):
                st.session_state.session.chg_session_name(session_name)
                st.session_state.sidebar_message = "セッション名を変更しました"
                st.rerun()

    # Webパーツのレイアウト
    header_col1, header_col2, header_col3, header_col4 = st.columns(4)

    # 時刻の設定
    header_col1.markdown("Time Setting:")
    _time_modes = ["Real Date", "Custom Date", "No Date"]
    _time_mode_idx = _time_modes.index(st.session_state.time_mode) if st.session_state.time_mode in _time_modes else 0
    time_mode = header_col1.radio("Time Mode:", _time_modes, index=_time_mode_idx, label_visibility="collapsed", horizontal=True)
    st.session_state.time_mode = time_mode
    if time_mode == "Real Date":
        selected_time_setting = now_time.strftime("%Y/%m/%d %H:%M:%S")
    elif time_mode == "No Date":
        selected_time_setting = ""
    else:
        from datetime import date as _date
        _cd_tab1, _cd_tab2 = header_col1.tabs(["Calendar", "Free Text"])
        with _cd_tab1:
            _cd_date = st.date_input("Date:", value=now_time.date(), min_value=_date(1, 1, 1), max_value=_date(9999, 12, 31), key="custom_date_cal")
            _cd_time = st.time_input("Time:", value=now_time.time(), key="custom_time_cal")
            selected_time_setting = datetime.combine(_cd_date, _cd_time).strftime("%Y/%m/%d %H:%M:%S")
        with _cd_tab2:
            if "custom_time_input" not in st.session_state:
                st.session_state.custom_time_input = ""
            selected_time_setting = st.text_input("Situation Date:", key="custom_time_input", placeholder="例: BC500年, 天保3年 江戸, 西暦30000年")
            if not selected_time_setting:
                selected_time_setting = datetime.combine(_cd_date, _cd_time).strftime("%Y/%m/%d %H:%M:%S")
    time_setting = str(selected_time_setting)
    st.session_state.time_setting = time_setting

    # 実行の設定
    if st.session_state.allowed_exec_setting:
        header_col2.markdown("Exec Setting:")

        # Private Modeの設定
        if header_col2.checkbox("Private Mode", value=st.session_state.private_mode):
            st.session_state.private_mode = True
        else:
            st.session_state.private_mode = False

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

    #    # メモリ類似度の設定
    #    if header_col2.checkbox("Memory Similarity", value=st.session_state.memory_similarity):
    #        st.session_state.memory_similarity = True
    #    else:
    #        st.session_state.memory_similarity = False


    # 実行の設定
    if st.session_state.allowed_rag_setting:
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
                    prompt_role = v2["prompt"]["role"]
                    if v.get("SETTING", {}).get("user_info", {}).get("USER_ID") is not None:
                        prompt_role = v["SETTING"]["user_info"]["USER_ID"]
                    with st.chat_message("human"):
                        content_text = "**"+prompt_role+" ("+v2["prompt"]["timestamp"]+"):**\n\n"+v2["prompt"]["query"]["input"]
                        download_data.append({"role": v2["prompt"]["role"], "content": content_text})
#                        st.markdown(content_text.replace("\n", "<br>"), unsafe_allow_html=True)
                        st.markdown(content_text, unsafe_allow_html=True)
                        for uploaded_content in v2["prompt"]["query"]["contents"]:
                            download_data.append({"role": v2["prompt"]["role"], "image": st.session_state.session.session_folder_path +"contents/"+ uploaded_content["file_name"]})
                            show_uploaded_files_memory(seq_key, st.session_state.session.session_folder_path +"contents/", uploaded_content["file_name"], uploaded_content["file_type"])
                    with st.chat_message("ai"):
                        content_text = "**"+v2["setting"]["name"]+" ("+v2["response"]["timestamp"]+"):**\n\n"+v2["response"]["text"]
                        download_data.append({"role": v2["response"]["role"], "content": content_text})
#                        st.markdown(content_text.replace("\n", "<br>").replace("#", ""), unsafe_allow_html=True)
                        st.markdown(content_text, unsafe_allow_html=True)
                        if "image" in v2:
                            for gen_content in v2["image"].values():
                                download_data.append({"role": v2["response"]["role"], "image": st.session_state.session.session_folder_path +"contents/"+ gen_content["file_name"]})
                                show_uploaded_files_memory(seq_key, st.session_state.session.session_folder_path +"contents/", gen_content["file_name"], gen_content["file_type"])

                    if v2["setting"]["type"] in ["LLM","IMAGEGEN"]:
                        if st.session_state.allowed_feedback:
                            if "communication" in v2["setting"]:
                                agent_communication = v2["setting"]["communication"]

                                if agent_communication["ACTIVE"] == "Y":
                                    # カテゴリ選択肢を取得
                                    _cat_map = dmu.read_json_file("category_map.json", mst_folder_path)
                                    _cat_options = list(_cat_map.get("Category", {}).keys()) if _cat_map else ["未設定"]
                                    _default_cat = agent_communication.get("DEFAULT_CATEGORY") or _cat_options[0]

                                    with st.chat_message("Feedback"):
                                        feedback = {}
                                        feedback["name"] = "Feedback"

                                        for fb_item in agent_communication["FEEDBACK_ITEM_LIST"]:
                                            feedback[fb_item] = {}
                                            feedback[fb_item]["visible"] = False
                                            feedback[fb_item]["flg"] = False
                                            feedback[fb_item]["memo"] = ""
                                            feedback[fb_item]["category"] = _default_cat
                                            if "feedback" in v2:
                                                feedback[fb_item] = v2.get("feedback", {}).get(fb_item, feedback[fb_item])
                                            feedback[fb_item]["saved_memo"] = feedback[fb_item]["memo"]

                                            if st.checkbox(f"{fb_item}", key=f"feedback_{fb_item}_{k}_{k2}", value=feedback[fb_item]["visible"]):
                                                feedback[fb_item]["memo"] = st.text_input("Memo:", key=f"feedback_{fb_item}_memo{k}_{k2}", value=feedback[fb_item]["memo"], label_visibility="collapsed")
                                                _cat_idx = _cat_options.index(feedback[fb_item].get("category", _default_cat)) if feedback[fb_item].get("category", _default_cat) in _cat_options else 0
                                                feedback[fb_item]["category"] = st.selectbox("Category:", _cat_options, index=_cat_idx, key=f"feedback_{fb_item}_cat{k}_{k2}", label_visibility="collapsed")
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
                        if st.session_state.allowed_details:
                            with st.chat_message("detail"):
                                download_data.append({"role": "detail", "content": st.session_state.session.get_detail_info(k, k2)})
                                chat_expander = st.expander("Detail Information")
                                with chat_expander:
                                    st.markdown(st.session_state.session.get_detail_info(k, k2).replace("\n", "<br>"), unsafe_allow_html=True)

                        # Analytics
                        if st.session_state.allowed_analytics_knowledge or st.session_state.allowed_analytics_compare:
                            with st.chat_message("analytics"):
                                if "analytics" in v2:
                                    if "knowledge_utility" in v2["analytics"]:
                                        similarity_utility_dict = v2["analytics"]["knowledge_utility"]["similarity_utility"]
                                        download_data.append({"role": "analytics", "content": "**knowledge Utility:**"})
                                        if "image_files" in v2["analytics"]["knowledge_utility"]:
                                            for _, image_values in v2["analytics"]["knowledge_utility"]["image_files"].items():
                                                for image_value in image_values:
                                                    download_data.append({"role": "analytics", "image": st.session_state.session.session_analytics_folder_path + image_value})

                                chat_expander = st.expander("Analytics Results")
                                with chat_expander:
                                    ref_timestamp = v2["prompt"]["timestamp"]
                                    analytics_dict = {}
                                    if "analytics" in v2:
                                        analytics_dict = v2["analytics"]
                                    if "LLM" == v2["setting"]["type"]:
                                        if st.session_state.allowed_analytics_compare:
                                            if compare_agent_id_selected := st.selectbox("Select Compare Agent:", st.session_state.agent_list, index=st.session_state.agent_list_index, key=f"conpareAgent_list{k}_{k2}"):
                                                if compare_agent_id_selected != st.session_state.compare_agent_id:
                                                    st.session_state.compare_agent_id = compare_agent_id_selected
                                                    st.session_state.compare_engine_name = ""
#                                                    st.session_state.compare_imagegen_engine_name = ""
                                            _compare_agent_file_tmp = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.compare_agent_id), None)
                                            _compare_agent_data_tmp = dmu.read_json_file(_compare_agent_file_tmp, agent_folder_path) if _compare_agent_file_tmp else {}
                                            _cmp_llm_list = dma.get_engine_list(_compare_agent_data_tmp, model_type="LLM")
                                            if _cmp_llm_list:
                                                _cmp_llm_idx = _cmp_llm_list.index(st.session_state.compare_engine_name) if st.session_state.compare_engine_name in _cmp_llm_list else 0
                                                st.session_state.compare_engine_name = st.selectbox("Compare Engine(LLM):", _cmp_llm_list, index=_cmp_llm_idx, key=f"cmpEngine_llm{k}_{k2}")
#                                            _cmp_imagegen_list = dma.get_engine_list(_compare_agent_data_tmp, model_type="IMAGEGEN")
#                                            if _cmp_imagegen_list:
#                                                _cmp_img_idx = _cmp_imagegen_list.index(st.session_state.compare_imagegen_engine_name) if st.session_state.compare_imagegen_engine_name in _cmp_imagegen_list else 0
#                                                st.session_state.compare_imagegen_engine_name = st.selectbox("Compare Engine(IMAGEGEN):", _cmp_imagegen_list, index=_cmp_img_idx, key=f"cmpEngine_img{k}_{k2}")
                                            compare_col1, _ = st.columns(2)
                                            if compare_col1.button("Analytics Results - Compare Agents", key=f"conpareAgent_btn{k}_{k2}", disabled=bool(st.session_state._bg_task)):
                                                _cmp_seq = k
                                                _cmp_sub_seq = str(int(k2)-1)
                                                _cmp_agent_file = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.compare_agent_id), None)
                                                _cmp_agent_data = dmu.read_json_file(_cmp_agent_file, agent_folder_path) if _cmp_agent_file else {}
                                                _cmp_overwrite = {}
                                                if st.session_state.compare_engine_name and st.session_state.compare_engine_name in _cmp_agent_data.get("ENGINE", {}).get("LLM", {}):
                                                    _cmp_overwrite.setdefault("ENGINE", {})["LLM"] = _cmp_agent_data["ENGINE"]["LLM"][st.session_state.compare_engine_name]
                                                if st.session_state.compare_imagegen_engine_name and st.session_state.compare_imagegen_engine_name in _cmp_agent_data.get("ENGINE", {}).get("IMAGEGEN", {}):
                                                    _cmp_overwrite.setdefault("ENGINE", {})["IMAGEGEN"] = _cmp_agent_data["ENGINE"]["IMAGEGEN"][st.session_state.compare_imagegen_engine_name]
                                                _cmp_v2 = v2
                                                _cmp_svc = dict(st.session_state.web_service)
                                                _cmp_usr = dict(st.session_state.web_user)
                                                _cmp_agent_id = st.session_state.compare_agent_id
                                                _cmp_analytics_dict = analytics_dict
                                                _cmp_k, _cmp_k2 = k, k2
                                                _cmp_session = st.session_state.session
                                                def _run_compare():
                                                    _, _, cmp_resp, cmp_model, _, cmp_know_ref = dmva.genLLMAgentSimple(
                                                        _cmp_svc, _cmp_usr, _cmp_v2["setting"]["session_id"], _cmp_v2["setting"]["session_name"],
                                                        _cmp_agent_file, model_type="LLM", sub_seq=1, query=_cmp_v2["prompt"]["query"]["input"],
                                                        import_contents=[], situation=_cmp_v2["prompt"]["query"]["situation"],
                                                        overwrite_items=_cmp_overwrite, prompt_temp_cd=_cmp_v2["prompt"]["prompt_template"]["setting"],
                                                        seq_limit=_cmp_seq, sub_seq_limit=_cmp_sub_seq)
                                                    vec_resp = dmu.embed_text(_cmp_v2["response"]["text"])
                                                    vec_cmp = dmu.embed_text(cmp_resp)
                                                    cmp_diff = dmu.calculate_cosine_distance(vec_resp, vec_cmp)
                                                    exec_agent_name = dma.get_agent_item(_cmp_v2["setting"]["agent_file"], "DISPLAY_NAME")
                                                    _, _, cmp_text, cmp_text_model, _, _ = dmt.compare_texts(
                                                        _cmp_svc, _cmp_usr, exec_agent_name, _cmp_v2["response"]["text"], _cmp_agent_id, cmp_resp)
                                                    if "compare_agents" not in _cmp_analytics_dict:
                                                        _cmp_analytics_dict["compare_agents"] = []
                                                    _cmp_analytics_dict["compare_agents"].append({
                                                        "compare_agent": {"timestamp": str(datetime.now()), "agent_file": _cmp_agent_file, "model_name": cmp_model,
                                                                          "response": cmp_resp, "diff": cmp_diff, "knowledge_rag": cmp_know_ref},
                                                        "compare_text": {"compare_model_name": cmp_text_model, "text": cmp_text}})
                                                    _cmp_session.set_analytics_history(_cmp_k, _cmp_k2, _cmp_analytics_dict)
                                                _run_bg_task("compare", f"比較分析を実行中({_cmp_k}_{_cmp_k2})", _run_compare)
                                                st.rerun()
                                    if st.session_state.allowed_analytics_knowledge:
                                        if v2["response"]["reference"]["knowledge_rag"]:
                                            ak_col1, ak_col2, ak_col3 = st.columns(3)
                                            st.session_state.analytics_knowledge_mode = ak_col2.radio("Knowledge Utility:", ["Default", "Norm(All)", "Norm(Group)"], index=1, key=f"kumode_{k}_{k2}")
                                            st.session_state.analytics_dimension_mode["method"] = ak_col3.radio("Dimension Reduction:", ["PCA", "t-SNE"], index=0, key=f"drmode_{k}_{k2}")
                                            st.session_state.analytics_dimension_mode["params"] = {}
                                            if st.session_state.analytics_dimension_mode["method"] == "t-SNE":
                                                st.session_state.analytics_dimension_mode["params"]["perplexity"] = ak_col3.number_input(label="t-SNE Perplexity:", value=40, step=1, format="%d", key=f"tsne_perplexity_{k}_{k2}")
                                            if ak_col1.button("Analytics Results - Knowledge Utility", key=f"knowledgeUtil_btn{k}_{k2}", disabled=bool(st.session_state._bg_task)):
                                                _ak_agent_file = v2["setting"]["agent_file"]
                                                _ak_title = f"{k}-{k2}-{st.session_state.session.session_name}"
                                                _ak_refs = [dmu.parse_log_template(rd) for rd in v2["response"]["reference"]["knowledge_rag"]]
                                                _ak_folder = st.session_state.session.session_analytics_folder_path
                                                _ak_mode = st.session_state.analytics_knowledge_mode
                                                _ak_dim = dict(st.session_state.analytics_dimension_mode)
                                                _ak_k, _ak_k2 = k, k2
                                                _ak_analytics_dict = analytics_dict
                                                _ak_session = st.session_state.session
                                                def _run_ak():
                                                    result = dmva.analytics_knowledge(_ak_agent_file, ref_timestamp, _ak_title, _ak_refs, _ak_folder, _ak_mode, _ak_dim)
                                                    _ak_analytics_dict["knowledge_utility"] = result
                                                    _ak_session.set_analytics_history(_ak_k, _ak_k2, _ak_analytics_dict)
                                                _run_bg_task("knowledge", f"知識活用性を分析中({_ak_k}_{_ak_k2})", _run_ak)
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
                                            compare_timestamp = compare_agent_info["timestamp"] if "timestamp" in compare_agent_info else ref_timestamp
                                            compare_agent_file = compare_agent_info["agent_file"]
                                            st.markdown(f"Agent: {compare_agent_file}")
                                            st.markdown(f"Model: {compare_agent_info['model_name']}")
                                            st.markdown(f"Diff: {compare_agent_info['diff']}")
                                            if st.session_state.allowed_analytics_knowledge:
                                                if "knowledge_rag" in compare_agent_info:
                                                    if compare_agent_info["knowledge_rag"]: #and "knowledge_utility" not in compare_agent_info:
                                                        ak_compare_col1, ak_compare_col2, ak_compare_col3 = st.columns(3)
                                                        st.session_state.analytics_knowledge_mode_compare = ak_compare_col2.radio("Analytics Knowledge Mode:", ["Default", "Norm(All)", "Norm(Group)"], index=1, key=f"akmode_compare_{k}_{k2}")
                                                        st.session_state.analytics_dimension_mode_compare["method"] = ak_compare_col3.radio("Dimension Reduction:", ["PCA", "t-SNE"], index=0, key=f"drmode_compare_{k}_{k2}")
                                                        st.session_state.analytics_dimension_mode_compare["params"] = {}
                                                        if st.session_state.analytics_dimension_mode_compare["method"] == "t-SNE":
                                                            st.session_state.analytics_dimension_mode_compare["params"]["perplexity"] = ak_compare_col3.number_input(label="t-SNE Perplexity:", value=40, step=1, format="%d", key=f"tsne_perplexity_compare_{k}_{k2}")
                                                        if ak_compare_col1.button("Analytics Results - Knowledge Utility", key=f"knowledgeUtil_btn{k}_{k2}_compare{selected_compare_idx}", disabled=bool(st.session_state._bg_task)):
                                                            _cak_title = f"{k}-{k2}-{st.session_state.session.session_name}_compare{selected_compare_idx}"
                                                            _cak_refs = [dmu.parse_log_template(rd) for rd in compare_agent_info["knowledge_rag"]["knowledge_ref"]]
                                                            _cak_agent_file = compare_agent_file
                                                            _cak_timestamp = compare_timestamp
                                                            _cak_folder = st.session_state.session.session_analytics_folder_path
                                                            _cak_mode = st.session_state.analytics_knowledge_mode_compare
                                                            _cak_dim = dict(st.session_state.analytics_dimension_mode_compare)
                                                            _cak_idx = selected_compare_idx
                                                            _cak_analytics_dict = analytics_dict
                                                            _cak_k, _cak_k2 = k, k2
                                                            _cak_session = st.session_state.session
                                                            def _run_cak():
                                                                result = dmva.analytics_knowledge(_cak_agent_file, _cak_timestamp, _cak_title, _cak_refs, _cak_folder, _cak_mode, _cak_dim)
                                                                _cak_analytics_dict["compare_agents"][_cak_idx]["compare_agent"]["knowledge_utility"] = result
                                                                _cak_session.set_analytics_history(_cak_k, _cak_k2, _cak_analytics_dict)
                                                            _run_bg_task("knowledge", f"知識活用性を分析中({_cak_k}_{_cak_k2}_compare{_cak_idx})", _run_cak)
                                                            st.rerun()
                                            st.markdown("")
                                            st.markdown(compare_agent_info["response"].replace("\n", "<br>"), unsafe_allow_html=True)
                                            st.markdown("")
                                            st.markdown(f"**Compare Text:** {compare_agent['compare_text']['compare_model_name']}")
                                            st.markdown(compare_agent["compare_text"]["text"].replace("\n", "<br>"), unsafe_allow_html=True)
                                            st.markdown("")
                                            if st.session_state.allowed_analytics_knowledge:
                                                if "knowledge_utility" in compare_agent_info:
                                                    chat_expander_analytics_compare = st.expander("Analytics Results - Knowledge Utility")
                                                    with chat_expander_analytics_compare:
                                                        compare_similarity_utility_dict = compare_agent_info["knowledge_utility"]["similarity_utility"]
                                                        st.markdown("**knowledge Utility:**")
                                                        st.markdown(", ".join(f"{k}: {v}" for k, v in compare_similarity_utility_dict.items()))
                                                        if "image_files" in compare_agent_info["knowledge_utility"]:
                                                            image_files = compare_agent_info["knowledge_utility"]["image_files"]
                                                            ext_for = lambda k: "csv" if "csv" in k else "png"
                                                            rag_to_files = {
                                                                rag: {k: next((f for f in v if f.endswith(f"_{rag}.{ext_for(k)}")), None) for k, v in image_files.items()}
                                                                for rag in sorted({os.path.splitext(f)[0].rsplit("_", 1)[-1] for v in image_files.values() for f in v})
                                                            }
                                                            for rag_category, files in rag_to_files.items():
                                                                st_scatter01, st_scatter02 = st.columns(2)
                                                                if files.get("scatter_plot_file_ref"):
                                                                    st_scatter01.image(st.session_state.session.session_analytics_folder_path + files["scatter_plot_file_ref"])
                                                                if files.get("scatter_plot_file_category"):
                                                                    st_scatter02.image(st.session_state.session.session_analytics_folder_path + files["scatter_plot_file_category"])
                                                                with st.expander(f"Coordinate - {rag_category}"):
                                                                    rag_rank_df = pd.read_csv(st.session_state.session.session_analytics_folder_path + files["scatter_plot_file_csv"])
                                                                    if 'category_color' in rag_rank_df.columns:
                                                                        display_items = ["id", "title", "create_date", "X1", "X2", "category_color", "category_sum", "category", "db", "value_text"]
                                                                    else:
                                                                        display_items = ["id", "title", "create_date", "X1", "X2", "value_text"]
                                                                    rag_rank_df = rag_rank_df[display_items]
                                                                    st.dataframe(rag_rank_df)
                                                                if files.get("similarity_plot_file"):
                                                                    st.image(st.session_state.session.session_analytics_folder_path + files["similarity_plot_file"])
                                                                for ak_dict in compare_agent_info["knowledge_utility"]["similarity_rank"][rag_category]:
                                                                    st.markdown(ak_line(ak_dict))

                                    if st.session_state.allowed_analytics_knowledge:
                                        if "knowledge_utility" in analytics_dict:
                                            chat_expander_analytics = st.expander("Analytics Results - Knowledge Utility")
                                            with chat_expander_analytics:
                                                similarity_utility_dict = analytics_dict["knowledge_utility"]["similarity_utility"]
                                                st.markdown("**knowledge Utility:**")
                                                st.markdown(", ".join(f"{k}: {v}" for k, v in similarity_utility_dict.items()))
                                                if "image_files" in analytics_dict["knowledge_utility"]:
                                                    image_files = analytics_dict["knowledge_utility"]["image_files"]
                                                    ext_for = lambda k: "csv" if "csv" in k else "png"
                                                    rag_categories = sorted(similarity_utility_dict.keys())
                                                    rag_to_files = {
                                                        rag: {k: next((f for f in v if f.endswith(f"_{rag}.{ext_for(k)}")), None) for k, v in image_files.items()}
                                                        #for rag in sorted({os.path.splitext(f)[0].rsplit("_", 1)[-1] for v in image_files.values() for f in v})
                                                        for rag in rag_categories
                                                    }
                                                    for rag_category, files in rag_to_files.items():
                                                        st_scatter01, st_scatter02 = st.columns(2)
                                                        if files.get("scatter_plot_file_ref"):
                                                            st_scatter01.image(st.session_state.session.session_analytics_folder_path + files["scatter_plot_file_ref"])
                                                        if files.get("scatter_plot_file_category"):
                                                            st_scatter02.image(st.session_state.session.session_analytics_folder_path + files["scatter_plot_file_category"])
                                                        if files.get("scatter_plot_file_csv"):
                                                            with st.expander(f"Coordinate - {rag_category}"):
                                                                rag_rank_df = pd.read_csv(st.session_state.session.session_analytics_folder_path + files["scatter_plot_file_csv"])
                                                                if 'category_color' in rag_rank_df.columns:
                                                                    display_items = ["id", "title", "create_date", "X1", "X2", "category_color", "category_sum", "category", "db", "value_text"]
                                                                else:
                                                                    display_items = ["id", "title", "create_date", "X1", "X2", "value_text"]
                                                                rag_rank_df = rag_rank_df[display_items]
                                                                st.dataframe(rag_rank_df)
                                                        if files.get("similarity_plot_file"):
                                                            st.image(st.session_state.session.session_analytics_folder_path + files["similarity_plot_file"])
                                                        for ak_dict in analytics_dict["knowledge_utility"]["similarity_rank"][rag_category]:
                                                            st.markdown(ak_line(ak_dict))

            # 会話履歴の論理削除設定
            if st.checkbox(f"Delete(seq:{k})", key="del_chat_seq"+k):
                st.session_state.seq_memory.append(k)

    if st.session_state.session_user_id == st.session_state.user_id:
        # ファイルアップローダー
        uploaded_files = st.file_uploader("Attached Files:", type=["txt", "vtt", "csv", "json", "pdf", "jpg", "jpeg", "png", "mp3"], accept_multiple_files=True)
        st.session_state.uploaded_files = uploaded_files
        show_uploaded_files_widget(st.session_state.uploaded_files)

        # WEB検索の設定
        if st.session_state.allowed_web_search:
            _ws_col1, _ws_col2 = st.columns([1, 2])
            if _ws_col1.checkbox("WEB Search", value=st.session_state.web_search):
                st.session_state.web_search = True
                _ws_default = dmu.read_yaml_file("setting.yaml").get("WEB_SEARCH_DEFAULT", "Perplexity")
                _ws_engines = list(dmt.WEB_SEARCH_ENGINES.keys())
                _ws_idx = _ws_engines.index(_ws_default) if _ws_default in _ws_engines else 0
                st.session_state.web_search_engine = _ws_col2.selectbox("Engine:", _ws_engines, index=_ws_idx, label_visibility="collapsed")
            else:
                st.session_state.web_search = False

        # BOOKから選択
        if st.session_state.allowed_book:
            if "BOOK" in st.session_state.agent_data:
                st.session_state.book_selected = st.multiselect("BOOK", [item["RAG_NAME"] for item in st.session_state.agent_data["BOOK"]])

    # ファイルダウンローダー
    if st.session_state.allowed_download_md:
        footer_col1, footer_col2 = st.columns(2)
        st.session_state.dl_type = footer_col1.radio("Download Mode:", ("Chats Only", "ALL"))
        dl_file_id = st.session_state.session.session_id +"_"+ st.session_state.session.session_name[:20]
        dl_data, dl_file_name, dl_mime = set_dl_file(download_data, st.session_state.dl_type, file_id=dl_file_id)
        footer_col2.download_button(label="Download(.md)", data=dl_data, file_name=dl_file_name, mime=dl_mime)

    # ユーザーの問合せ入力
    if st.session_state.session_user_id == st.session_state.user_id:

        # チャット入力（ロック中 or バックグラウンド実行中はポーリングで監視）
        _status_locked = st.session_state.session.get_status() == "LOCKED"
        _bg_running = bool(st.session_state._bg_user_input)
        is_locked = _status_locked or _bg_running
        if is_locked:
            # 実行中のユーザー入力を表示
            if st.session_state._bg_user_input:
                with st.chat_message("user"):
                    st.markdown(st.session_state._bg_user_input.replace("\n", "<br>"), unsafe_allow_html=True)
            @st.fragment(run_every=2)
            def _lock_monitor():
                _still_locked = st.session_state.session.get_status() == "LOCKED"
                if not _still_locked:
                    # バックグラウンド完了: クリーンアップしてフルリロード
                    st.session_state._bg_user_input = ""
                    st.session_state.is_processing = False
                    refresh_session_list(st.session_state.service_id, st.session_state.user_id, st.session_state.user_admin_flg)
                    st.rerun(scope="app")
                _partial = st.session_state.session.get_status_response()
                if _partial:
                    st.markdown(_partial)
                _msg = st.session_state.session.get_status_message()
                st.info(f"⏳ {_msg}" if _msg else "⏳ 実行中です...")
            with st.chat_message("ai"):
                _lock_monitor()

        # バックグラウンド実行のエラー表示（status.yamlから読み取り、即クリア）
        if not is_locked:
            _bg_error = st.session_state.session.get_status_error()
            if _bg_error:
                st.session_state.session.save_status("UNLOCKED")
                st.error(f"実行中にエラーが発生しました: {_bg_error}")

        _chat_disabled = is_locked or st.session_state.is_processing
        if raw_input := st.chat_input("Your Message", disabled=_chat_disabled):
            st.session_state.pending_input = raw_input
            st.session_state.is_processing = True
            st.rerun()

        if st.session_state.is_processing and st.session_state.pending_input:
            user_input = st.session_state.pending_input
            st.session_state.pending_input = ""
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
            # エンジン切り替え（LLM）
            if st.session_state.engine_name and st.session_state.engine_name in st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}):
                overwrite_items.setdefault("ENGINE", {})["LLM"] = st.session_state.agent_data["ENGINE"]["LLM"][st.session_state.engine_name]
            # エンジン切り替え（IMAGEGEN）
            if st.session_state.imagegen_engine_name and st.session_state.imagegen_engine_name in st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}):
                overwrite_items.setdefault("ENGINE", {})["IMAGEGEN"] = st.session_state.agent_data["ENGINE"]["IMAGEGEN"][st.session_state.imagegen_engine_name]

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
            execution["WEB_SEARCH_ENGINE"] = st.session_state.get("web_search_engine", "")
            execution["PRIVATE_MODE"] = st.session_state.private_mode

            # バックグラウンドで実行開始（事前ロック）
            import threading
            st.session_state.session.save_status("LOCKED")
            execution["_PRE_LOCKED"] = True
            _bg_params = {
                "service_info": dict(st.session_state.web_service),
                "user_info": dict(st.session_state.web_user),
                "session_id": st.session_state.session.session_id,
                "session_name": st.session_state.session.session_name,
                "agent_file": st.session_state.agent_file,
                "user_input": user_input,
                "uploaded_contents": uploaded_contents,
                "situation": situation,
                "overwrite_items": overwrite_items,
                "add_knowledges": add_knowledges,
                "execution": execution,
            }
            st.session_state._bg_user_input = user_input

            def _run_bg(params):
                _exec_error = ""
                try:
                    for _ in dme.DigiMatsuExecute_Practice(
                        params["service_info"], params["user_info"],
                        params["session_id"], params["session_name"],
                        params["agent_file"], params["user_input"],
                        params["uploaded_contents"], params["situation"],
                        params["overwrite_items"], params["add_knowledges"],
                        params["execution"]
                    ):
                        pass  # チャンクを消費（結果はchat_memory.jsonに保存される）
                except Exception as e:
                    _exec_error = str(e)
                # セッション名の自動生成（エラー時もスキップしない）
                try:
                    _session = dms.DigiMSession(params["session_id"], params["session_name"])
                    if not _session.session_name or _session.session_name == "New Chat":
                        _, _, new_name, _, _, _ = dmt.gene_session_name(
                            params["service_info"], params["user_info"],
                            params["session_id"], _session.session_name, "", params["user_input"])
                        _session.chg_session_name(new_name)
                except Exception:
                    pass
                # エラーがあった場合のみステータスに記録（UNLOCKはDigiMatsuExecute_Practice内で処理済み）
                if _exec_error:
                    _session = dms.DigiMSession(params["session_id"])
                    # ダイジェストスレッドが動いている可能性があるので、UNLOCK完了を待ってからエラーを記録
                    import time as _time
                    for _ in range(30):
                        if _session.get_status() != "LOCKED":
                            break
                        _time.sleep(1)
                    _session.save_status("UNLOCKED", error=_exec_error)

            thread = threading.Thread(target=_run_bg, args=(_bg_params,), daemon=True)
            thread.start()
            st.rerun()

if __name__ == "__main__":
    main()
