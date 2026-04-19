import os
import re
import ast
import json
import hmac
import hashlib
import datetime
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv

# Streamlitインポート前にconfig.tomlを生成（アップロード上限の設定）
if os.path.exists("system.env"):
    load_dotenv("system.env", override=False)
_max_upload = os.getenv("WEB_MAX_UPLOAD_SIZE", "500")
os.makedirs(".streamlit", exist_ok=True)
with open(".streamlit/config.toml", "w") as _cf:
    _cf.write(f"[server]\nmaxUploadSize = {_max_upload}\nmaxMessageSize = {_max_upload}\n")

import streamlit as st
import pandas as pd
from dataclasses import dataclass
from typing import Any, Dict
import extra_streamlit_components as stx

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
if 'allowed_rag_explorer' not in st.session_state:
    st.session_state.allowed_rag_explorer = True
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
    st.session_state._bg_task = None  # {"type": "rag"|"knowledge"|"compare", "message": "..."}

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

# --- Cookie認証 ---
_COOKIE_NAME = "digim_auth"
_COOKIE_SECRET = os.getenv("COOKIE_SECRET", "digim_default_secret_key_2026")
_COOKIE_EXPIRY_DAYS = 7

def _get_cookie_manager():
    if "_cookie_manager" not in st.session_state:
        st.session_state._cookie_manager = stx.CookieManager()
    return st.session_state._cookie_manager

# user_idからHMACトークンを生成
def _make_auth_token(user_id: str) -> str:
    sig = hmac.new(_COOKIE_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    return f"{user_id}:{sig}"

# トークンを検証してuser_idを返す。不正ならNone
def _verify_auth_token(token: str):
    if not token or ":" not in token:
        return None
    user_id, sig = token.rsplit(":", 1)
    expected = hmac.new(_COOKIE_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return user_id
    return None

# ログイン成功時にCookieを設定
def _set_auth_cookie(cookie_manager, user_id: str):
    token = _make_auth_token(user_id)
    expires = datetime.now() + timedelta(days=_COOKIE_EXPIRY_DAYS)
    cookie_manager.set(_COOKIE_NAME, token, expires_at=expires)

# ログアウト時にCookieを削除
def _clear_auth_cookie(cookie_manager):
    cookie_manager.delete(_COOKIE_NAME)

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

    # Cookie認証: session_stateが消えてもCookieから復元
    cookie_manager = _get_cookie_manager()
    auth_token = cookie_manager.get(_COOKIE_NAME)
    if auth_token:
        cookie_user_id = _verify_auth_token(auth_token)
        if cookie_user_id:
            users = load_user_master()
            user_info = users.get(cookie_user_id)
            if user_info:
                set_login_user_to_session(cookie_user_id, user_info)
                refresh_session_states()
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
            remember_me = st.checkbox("Keep me logged in", value=True)
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
                if remember_me:
                    _set_auth_cookie(cookie_manager, input_user_id)
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
    st.session_state.allowed_rag_explorer = allowded_dict.get("RAG Explorer", True)
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

# バックグラウンドでタスクを実行し、完了時にファイルフラグを立てる
def _run_bg_task(task_type, message, func, *args, **kwargs):
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
        st.session_state.private_mode = True
    if 'thinking_mode' not in st.session_state:
        st.session_state.thinking_mode = False
    if 'thinking_targets' not in st.session_state:
        st.session_state.thinking_targets = ["Habit", "Web Search", "RAG Query", "Books"]
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
        _idx = st.session_state.agent_list.index(st.session_state.default_agent) if st.session_state.default_agent in st.session_state.agent_list else 0
        st.session_state.agent_list_index = _idx
        st.session_state.agent_file = st.session_state.agents[_idx]["FILE"]
        st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
        st.session_state.engine_name = st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
        st.session_state.imagegen_engine_name = st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")
    else:
        session_agent_file = dms.get_agent_file(st.session_state.session.session_id)
        _agent_display = dma.get_agent_item(session_agent_file, "DISPLAY_NAME") if os.path.exists(agent_folder_path + session_agent_file) else ""
        if _agent_display and _agent_display in st.session_state.agent_list:
            st.session_state.display_name = _agent_display
            _idx = st.session_state.agent_list.index(_agent_display)
            st.session_state.agent_list_index = _idx
            st.session_state.agent_file = session_agent_file
            st.session_state.agent_data = dmu.read_json_file(session_agent_file, agent_folder_path)
            last_engine = dms.get_last_engine_name(st.session_state.session.session_id)
            engine_list = dma.get_engine_list(st.session_state.agent_data, "LLM")
            if last_engine and last_engine in engine_list:
                st.session_state.engine_name = last_engine
            else:
                st.session_state.engine_name = st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
            st.session_state.imagegen_engine_name = st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")
        else:
            st.session_state.display_name = st.session_state.default_agent
            _idx = st.session_state.agent_list.index(st.session_state.default_agent) if st.session_state.default_agent in st.session_state.agent_list else 0
            st.session_state.agent_list_index = _idx
            st.session_state.agent_file = st.session_state.agents[_idx]["FILE"]
            st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
            st.session_state.engine_name = st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
            st.session_state.imagegen_engine_name = st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")
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

# AIレスポンスのクリップボードコピーボタン
def render_copy_button(text, key):
    import html as _html
    escaped = _html.escape(text).replace("`", "\\`").replace("$", "\\$")
    st.components.v1.html(f"""
    <button onclick="navigator.clipboard.writeText(`{escaped}`).then(()=>{{this.textContent='Copied!';setTimeout(()=>this.textContent='Copy',1500)}})"
    style="background:transparent;border:1px solid #888;border-radius:4px;padding:2px 10px;cursor:pointer;font-size:12px;color:#888;">Copy</button>
    """, height=32)

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

def set_dl_pdf(chat_history, dl_type="Chats Only", file_id="Chat_History"):
    """チャット履歴をPDFバイト列として返す"""
    from fpdf import FPDF
    import logging as _log
    _log.getLogger("pdf").info(f"set_dl_pdf: {len(chat_history)} messages, dl_type={dl_type}")
    _FONT_PATH = "/usr/share/fonts/opentype/ipaexfont-gothic/ipaexg.ttf"

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_font("IPAexG", "", _FONT_PATH, uni=True)
    pdf.add_page()
    pdf.set_font("IPAexG", size=10)

    _w = pdf.w - pdf.l_margin - pdf.r_margin
    for msg in chat_history:
        if (dl_type == "Chats Only" and msg["role"] in ["user", "assistant"]) or dl_type == "ALL":
            if "content" in msg:
                pdf.set_font("IPAexG", size=11)
                pdf.cell(_w, 8, msg["role"].capitalize(), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("IPAexG", size=10)
                for line in msg["content"].split("\n"):
                    line = line.replace("\r", "").replace("**", "")
                    if line.startswith("![") or len(line) > 5000:
                        continue
                    try:
                        pdf.multi_cell(_w, 6, line)
                    except Exception:
                        try:
                            pdf.multi_cell(_w, 6, line[:200] + "...")
                        except Exception:
                            pass
                pdf.ln(2)
            if "image" in msg:
                try:
                    pdf.image(msg["image"], w=100)
                    pdf.ln(3)
                except Exception:
                    pdf.cell(_w, 6, f"[画像]", new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)

    pdf_bytes = bytes(pdf.output())
    file_name = f"{file_id}_{dl_type}.pdf"
    return pdf_bytes, file_name

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

### RAG Explorer画面 ###
def _rag_explorer():
    import fnmatch

    _ANALYTICS_BASE = "user/common/analytics/rag_explorer/"

    # RAG Explorer用の全session_stateキー
    _RAG_STATE_KEYS = [
        "_rag_searched", "_rag_cached_data", "_rag_cached_type", "_rag_prev_collection",
        "_rag_scatter_cache", "_rag_cluster_cache", "_rag_cluster_explanation",
        "_rag_sensitivity", "_rag_sensitivity_explanation",
        "_rag_temporal", "_rag_temporal_explanation",
        "_rag_llm_response", "_rag_report",
        "_rag_ask_result", "_rag_ask_history",
        "_rag_ak_result", "_rag_cmp_result",
        "_rag_pi_ask_result", "_rag_pi_ask_history",
        "_rag_pi_ak_result", "_rag_pi_cmp_result",
        "_rag_pi_sensitivity",
        "_rag_loaded_collection", "_rag_loaded_type",
        "_rag_analytics_folder",
    ]

    def _save_analysis_session(collection_name):
        """全RAG Explorer状態をフォルダに保存する"""
        import pickle
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _folder = os.path.join(_ANALYTICS_BASE, f"analytics{_ts}")
        os.makedirs(_folder, exist_ok=True)

        # メタ情報
        _meta = {
            "collection": collection_name,
            "timestamp": _ts,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        dmu.save_json_file(_meta, os.path.join(_folder, "meta.json"))

        # 全状態をpickleで丸ごと保存
        _state = {}
        for _k in _RAG_STATE_KEYS:
            if _k in st.session_state:
                _state[_k] = st.session_state[_k]
        with open(os.path.join(_folder, "state.pkl"), "wb") as f:
            pickle.dump(_state, f)

        # 分析フォルダパスをsession_stateに保持
        st.session_state._rag_analytics_folder = _folder

        # レポートがあればmdでも保存（人間が読める形で）
        if st.session_state.get("_rag_report"):
            dmu.save_text_file(st.session_state._rag_report, os.path.join(_folder, "report.md"))

        return _folder

    def _load_analysis_session(folder_path):
        """保存された全状態をsession_stateに復元する"""
        import pickle
        _meta_path = os.path.join(folder_path, "meta.json")
        if not os.path.exists(_meta_path):
            return None
        _meta = dmu.read_json_file(_meta_path)

        # まず全RAGキーをクリア
        for _k in _RAG_STATE_KEYS:
            if _k in st.session_state:
                del st.session_state[_k]

        # pickleから復元
        _pkl_path = os.path.join(folder_path, "state.pkl")
        if os.path.exists(_pkl_path):
            with open(_pkl_path, "rb") as f:
                _state = pickle.load(f)
            for _k, _v in _state.items():
                st.session_state[_k] = _v

        # 読み込み済みフラグ
        st.session_state._rag_searched = True
        st.session_state._rag_loaded_collection = _meta.get("collection", "")

        return _meta

    def _list_saved_sessions():
        """保存済み分析セッションの一覧を返す"""
        if not os.path.exists(_ANALYTICS_BASE):
            return []
        sessions = []
        for folder in sorted(os.listdir(_ANALYTICS_BASE), reverse=True):
            _meta_path = os.path.join(_ANALYTICS_BASE, folder, "meta.json")
            if os.path.exists(_meta_path):
                _meta = dmu.read_json_file(_meta_path)
                sessions.append({
                    "folder": folder,
                    "path": os.path.join(_ANALYTICS_BASE, folder),
                    "collection": _meta.get("collection", ""),
                    "created_at": _meta.get("created_at", ""),
                })
        return sessions

    def _ask_agent_ui(context_text, key_prefix="rag"):
        """Ask Agent共通UI: 実行設定+質問入力+DigiMatsuExecute実行。結果をsession_stateに保存。"""
        st.markdown("---")
        st.subheader("Ask Agent")
        _llm_agent_list = st.session_state.agent_list
        _llm_agent_idx = 0
        if st.session_state.get("agent_id") in _llm_agent_list:
            _llm_agent_idx = _llm_agent_list.index(st.session_state.agent_id)
        _llm_agent = st.selectbox("Agent:", _llm_agent_list, index=_llm_agent_idx, key=f"{key_prefix}_llm_agent")

        # 実行設定
        _ask_exp = st.expander("Exec Settings")
        with _ask_exp:
            _ask_c1, _ask_c2, _ask_c3, _ask_c4 = st.columns(4)
            _ask_web = _ask_c1.checkbox("Web Search", value=False, key=f"{key_prefix}_ask_web")
            _ask_private = _ask_c2.checkbox("Private Mode", value=st.session_state.get("private_mode", True), key=f"{key_prefix}_ask_private")
            _ask_thinking = _ask_c3.checkbox("Thinking Mode", value=False, key=f"{key_prefix}_ask_thinking")
            _ask_book = _ask_c4.checkbox("Use Books", value=False, key=f"{key_prefix}_ask_book")

        _llm_query = st.text_area("Question:", placeholder="例: カテゴリごとの特徴を説明して", height=100, key=f"{key_prefix}_llm_query")

        if _llm_query and st.button("Ask", key=f"{key_prefix}_llm_ask"):
            _agent_file = next((a["FILE"] for a in st.session_state.agents if a["AGENT"] == _llm_agent), None)
            if _agent_file:
                _user_input = f"{context_text}\n\n【質問】\n{_llm_query}"
                _exec = {
                    "MEMORY_USE": False, "MEMORY_SAVE": True, "SAVE_DIGEST": False,
                    "CONTENTS_SAVE": False, "STREAM_MODE": False, "MAGIC_WORD_USE": False,
                    "META_SEARCH": False, "RAG_QUERY_GENE": True,
                    "WEB_SEARCH": _ask_web, "PRIVATE_MODE": _ask_private,
                    "THINKING_MODE": _ask_thinking,
                }
                _add_knowledge = []
                if _ask_book:
                    _agent_data = dmu.read_json_file(_agent_file, agent_folder_path)
                    _add_knowledge = _agent_data.get("BOOK", [])

                _session_id = "RAG_EXPLORER_" + dms.set_new_session_id()
                # analyticsフォルダ内にセッションを作成
                _analytics_folder = st.session_state.get("_rag_analytics_folder", "")
                if not _analytics_folder:
                    _analytics_folder = os.path.join(_ANALYTICS_BASE, f"analytics{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                    st.session_state._rag_analytics_folder = _analytics_folder
                _session_base = os.path.join(_analytics_folder, _session_id)
                _tmp_session = dms.DigiMSession(_session_id, "RAG Explorer", base_path=_session_base)
                _tmp_session.save_status("LOCKED")
                _exec["_SESSION_BASE_PATH"] = _session_base

                with st.spinner("エージェント実行中..."):
                    try:
                        _response = ""
                        _output_ref = {}
                        for _, _, chunk, _, _oref in dme.DigiMatsuExecute(
                                st.session_state.web_service, st.session_state.web_user,
                                _session_id, "RAG Explorer", _agent_file, "LLM",
                                1, _user_input, [], {}, {}, _add_knowledge, "No Template", _exec):
                            if chunk and not chunk.startswith("[STATUS]"):
                                _response += chunk
                            if _oref:
                                _output_ref = _oref
                        _new_result = {
                            "response": _response,
                            "query": _llm_query,
                            "session_id": _session_id,
                            "session_base_path": _session_base,
                            "agent_file": _agent_file,
                            "agent_name": _llm_agent,
                            "output_ref": _output_ref,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                        # 最新の結果（Detail/Analytics用）
                        st.session_state[f"_{key_prefix}_ask_result"] = _new_result
                        # 会話履歴に追加
                        if f"_{key_prefix}_ask_history" not in st.session_state:
                            st.session_state[f"_{key_prefix}_ask_history"] = []
                        st.session_state[f"_{key_prefix}_ask_history"].append(_new_result)
                    except Exception as e:
                        import traceback
                        st.error(f"エージェント実行エラー: {type(e).__name__}: {e}")
                        st.code(traceback.format_exc())
                    finally:
                        _tmp_session.save_status("UNLOCKED")

    def _show_ask_result(key_prefix="rag"):
        """Ask Agentの会話履歴 + 最新結果のDetail/Analytics を表示"""
        _history = st.session_state.get(f"_{key_prefix}_ask_history", [])
        _result = st.session_state.get(f"_{key_prefix}_ask_result")
        if not _history and not _result:
            return None

        # 過去の会話履歴を表示
        if len(_history) > 1:
            for _h in _history[:-1]:
                with st.chat_message("user"):
                    st.markdown(f"**[{_h.get('timestamp','')}] {_h.get('agent_name','')}**")
                    st.markdown(_h.get("query", ""))
                with st.chat_message("assistant"):
                    st.markdown(_h["response"])

        # 最新の回答
        if _result:
            with st.chat_message("user"):
                st.markdown(f"**[{_result.get('timestamp','')}] {_result.get('agent_name','')}**")
                st.markdown(_result.get("query", ""))
            with st.chat_message("assistant"):
                st.markdown(_result["response"])

        _sid = _result["session_id"]
        _agent_file = _result["agent_file"]
        _base_path = _result.get("session_base_path", "")

        # Detail Information
        _detail_exp = st.expander("Detail Information")
        with _detail_exp:
            try:
                _session = dms.DigiMSession(_sid, base_path=_base_path) if _base_path else dms.DigiMSession(_sid)
                _detail = _session.get_detail_info("1", "1")
                if _detail:
                    import re as _re
                    _blocks = _re.split(r'\n(?=【)', _detail)
                    for _block in _blocks:
                        _block = _block.strip()
                        if _block:
                            st.markdown(_block.replace("\n", "<br>"), unsafe_allow_html=True)
            except Exception as e:
                st.caption(f"Detail取得エラー: {e}")

        # Analytics Results（セッションデータが保存されている場合のみ表示）
        _session_check = dms.DigiMSession(_sid, base_path=_base_path) if _base_path else dms.DigiMSession(_sid)
        if not os.path.exists(_session_check.session_file_path):
            return _result["response"]
        _analytics_exp = st.expander("Analytics Results")
        with _analytics_exp:
            try:
                _session = dms.DigiMSession(_sid, base_path=_base_path) if _base_path else dms.DigiMSession(_sid)
                _history = _session.get_history()
                if _history and "1" in _history and "1" in _history["1"]:
                    _v2 = _history["1"]["1"]

                    # --- Compare Agents ---
                    if st.session_state.get("allowed_analytics_compare", True):
                        _cmp_agent = st.selectbox("Select Compare Agent:", st.session_state.agent_list,
                                                  index=st.session_state.agent_list_index, key=f"{key_prefix}_cmp_agent")
                        _cmp_file_tmp = next((a["FILE"] for a in st.session_state.agents if a["AGENT"] == _cmp_agent), None)
                        _cmp_data_tmp = dmu.read_json_file(_cmp_file_tmp, agent_folder_path) if _cmp_file_tmp else {}
                        _cmp_engine_list = dma.get_engine_list(_cmp_data_tmp, model_type="LLM")
                        _cmp_engine = ""
                        if _cmp_engine_list:
                            _cmp_engine = st.selectbox("Compare Engine(LLM):", _cmp_engine_list, key=f"{key_prefix}_cmp_engine")
                        compare_col1, _ = st.columns(2)
                        if compare_col1.button("Analytics Results - Compare Agents", key=f"{key_prefix}_cmp_run", disabled=bool(st.session_state._bg_task)):
                            _cmp_file = _cmp_file_tmp
                            if _cmp_file:
                                _cmp_overwrite = {}
                                if _cmp_engine and _cmp_engine in _cmp_data_tmp.get("ENGINE", {}).get("LLM", {}):
                                    _cmp_overwrite.setdefault("ENGINE", {})["LLM"] = _cmp_data_tmp["ENGINE"]["LLM"][_cmp_engine]
                                _orig_query = _v2["prompt"]["query"]["input"]
                                _orig_situation = _v2["prompt"]["query"].get("situation", {})
                                _orig_template = _v2["prompt"]["prompt_template"]["setting"]

                                import DigiM_VAnalytics as _dmva_cmp
                                def _run_cmp():
                                    _, _, cmp_resp, cmp_model, _, cmp_know_ref = _dmva_cmp.genLLMAgentSimple(
                                        st.session_state.web_service, st.session_state.web_user,
                                        _sid, "RAG Explorer", _cmp_file, model_type="LLM", sub_seq=1,
                                        query=_orig_query, import_contents=[], situation=_orig_situation,
                                        overwrite_items=_cmp_overwrite, prompt_temp_cd=_orig_template,
                                        seq_limit="1", sub_seq_limit="0")
                                    vec_resp = dmu.embed_text(_v2["response"]["text"])
                                    vec_cmp = dmu.embed_text(cmp_resp)
                                    cmp_diff = dmu.calculate_cosine_distance(vec_resp, vec_cmp)
                                    exec_agent_name = dma.get_agent_item(_v2["setting"]["agent_file"], "DISPLAY_NAME")
                                    _, _, cmp_text, cmp_text_model, _, _ = dmt.compare_texts(
                                        st.session_state.web_service, st.session_state.web_user,
                                        exec_agent_name, _v2["response"]["text"], _cmp_agent, cmp_resp)
                                    st.session_state[f"_{key_prefix}_cmp_result"] = {
                                        "agent_file": _cmp_file, "agent": _cmp_agent, "model_name": cmp_model,
                                        "response": cmp_resp, "diff": round(cmp_diff, 3),
                                        "compare_text": cmp_text, "compare_model": cmp_text_model,
                                        "knowledge_rag": cmp_know_ref}
                                _run_bg_task("compare", f"比較分析を実行中(RAG Explorer)", _run_cmp)
                                st.rerun()

                    # Compare結果表示
                    if st.session_state.get(f"_{key_prefix}_cmp_result"):
                        _cmp_r = st.session_state[f"_{key_prefix}_cmp_result"]
                        st.markdown(f"**Agent:** {_cmp_r.get('agent', '')} | **Model:** {_cmp_r.get('model_name', '')} | **Diff:** {_cmp_r.get('diff', '')}")
                        st.markdown("")
                        st.markdown(_cmp_r.get("response", "").replace("\n", "<br>"), unsafe_allow_html=True)
                        if _cmp_r.get("compare_text"):
                            st.markdown(f"**Compare Text ({_cmp_r.get('compare_model', '')}):**")
                            st.markdown(_cmp_r["compare_text"].replace("\n", "<br>"), unsafe_allow_html=True)

                    # --- Knowledge Utility ---
                    if st.session_state.get("allowed_analytics_knowledge", True):
                        _know_refs = _v2.get("response", {}).get("reference", {}).get("knowledge_rag", [])
                        _ak_refs = [dmu.parse_log_template(rd) for rd in _know_refs if "page_id" not in rd]
                        if _ak_refs:
                            st.markdown("---")
                            ak_col1, ak_col2, ak_col3 = st.columns(3)
                            _ak_mode = ak_col2.radio("Knowledge Utility:", ["Default", "Norm(All)", "Norm(Group)"], index=1, key=f"{key_prefix}_ak_mode")
                            _ak_dim_method = ak_col3.radio("Dimension Reduction:", ["PCA", "t-SNE"], index=0, key=f"{key_prefix}_ak_dim")
                            _ak_dim_params = {}
                            if _ak_dim_method == "t-SNE":
                                _ak_dim_params["perplexity"] = ak_col3.number_input("t-SNE Perplexity:", value=40, step=1, key=f"{key_prefix}_ak_perp")
                            _ak_dim = {"method": _ak_dim_method, "params": _ak_dim_params}

                            if ak_col1.button("Analytics Results - Knowledge Utility", key=f"{key_prefix}_ak_run", disabled=bool(st.session_state._bg_task)):
                                import DigiM_VAnalytics as _dmva_ak
                                _ref_ts = _v2.get("prompt", {}).get("timestamp", str(datetime.now()))
                                _ak_title = f"RAGExplorer_{_sid}"
                                # analytics個別フォルダに保存（なければ一時的に作成）
                                _ak_folder = st.session_state.get("_rag_analytics_folder", "")
                                if not _ak_folder:
                                    _ak_folder = os.path.join(_ANALYTICS_BASE, f"analytics{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                                    st.session_state._rag_analytics_folder = _ak_folder
                                os.makedirs(_ak_folder, exist_ok=True)
                                def _run_ak():
                                    _r = _dmva_ak.analytics_knowledge(_agent_file, _ref_ts, _ak_title, _ak_refs, _ak_folder, _ak_mode, _ak_dim)
                                    st.session_state[f"_{key_prefix}_ak_result"] = _r
                                _run_bg_task("knowledge", "知識活用性を分析中(RAG Explorer)", _run_ak)
                                st.rerun()

                            if st.session_state.get(f"_{key_prefix}_ak_result"):
                                _ak_r = st.session_state[f"_{key_prefix}_ak_result"]
                                _ak_img_folder = st.session_state.get("_rag_analytics_folder", temp_folder_path)
                                if "image_files" in _ak_r:
                                    for _, _imgs in _ak_r["image_files"].items():
                                        for _img in _imgs:
                                            _img_path = os.path.join(_ak_img_folder, _img)
                                            if os.path.exists(_img_path):
                                                st.image(_img_path)
                                if "similarity_utility" in _ak_r:
                                    st.json(_ak_r["similarity_utility"])

            except Exception as e:
                st.caption(f"Analytics取得エラー: {e}")

        return _result["response"]

    st.subheader("RAG Explorer")

    # サイドバーからの読み込みリクエストを処理
    if st.session_state.get("_rag_load_folder"):
        _load_path = st.session_state._rag_load_folder
        st.session_state._rag_load_folder = None
        _loaded = _load_analysis_session(_load_path)
        if _loaded:
            st.session_state._rag_searched = True
            st.session_state._rag_loaded_collection = _loaded.get("collection", "")
            st.session_state._rag_loaded_type = _loaded.get("data_type", "ChromaDB")
            st.info(f"分析セッションを読み込みました: {_loaded.get('created_at', '')} - {_loaded.get('collection', '')}")

    # 選択中エージェントのKNOWLEDGE/BOOKからデータソースを抽出
    _agent_data = st.session_state.get("agent_data", {})
    _agent_db_names = set()
    _agent_pi_names = set()
    for _k in _agent_data.get("KNOWLEDGE", []) + _agent_data.get("BOOK", []):
        if _k.get("RETRIEVER") == "PageIndex":
            for _d in _k.get("DATA", []):
                if _d.get("DATA_TYPE") == "PAGE_INDEX":
                    _agent_pi_names.add(_d["DATA_NAME"])
        else:
            for _d in _k.get("DATA", []):
                _agent_db_names.add(_d.get("DATA_NAME", ""))

    # データソース一覧をエージェントの設定で絞り込み
    _all_chroma = dmc.get_rag_list()
    _all_page_index = dmc.get_page_index_list()
    _chroma_list = [c for c in _all_chroma if c in _agent_db_names] if _agent_db_names else _all_chroma
    _page_index_names = [p for p in _all_page_index.keys() if p in _agent_pi_names] if _agent_pi_names else list(_all_page_index.keys())
    _page_index_dict = {k: v for k, v in _all_page_index.items() if k in _page_index_names} if _agent_pi_names else _all_page_index

    # データソースが両方あるかでラジオボタン表示を制御
    _has_vectordb = bool(_chroma_list)
    _has_pageindex = bool(_page_index_names)
    _source_options = []
    if _has_vectordb:
        _source_options.append("Collection (VectorDB)")
    if _has_pageindex:
        _source_options.append("PageIndex")
    if not _source_options:
        st.info("選択中のエージェントにRAGデータが設定されていません")
        return

    _source_type = st.radio("Data Source:", _source_options, horizontal=True, key="rag_source_type") if len(_source_options) > 1 else _source_options[0]
    _is_page_index = (_source_type == "PageIndex")

    if _is_page_index:
        _selected_pi = st.selectbox("PageIndex:", _page_index_names, key="rag_pi_select")
        _selected_list = [f"[PageIndex] {_selected_pi}"]
    else:
        _selected_list = st.multiselect("Collection:", _chroma_list, default=[], key="rag_collection_chromadb")

    # 選択をソートして文字列化（キャッシュキーに使う）
    _selected_key = str(sorted(_selected_list))

    # Collection変更時にキャッシュと検索状態をリセット
    # （空選択時、読み込み済みセッションがある場合、BGタスク実行中はスキップ）
    _has_loaded = st.session_state.get("_rag_loaded_collection", "")
    _is_bg_running = bool(st.session_state.get("_bg_task"))
    if (_selected_key and _selected_key != "[]"
        and _selected_key != st.session_state.get("_rag_prev_collection")
        and not _has_loaded and not _is_bg_running):
        st.session_state._rag_prev_collection = _selected_key
        st.session_state._rag_searched = False
        st.session_state._rag_cached_data = None
        st.session_state._rag_cached_type = None
        st.session_state._rag_scatter_cache = None
        st.session_state._rag_cluster_cache = None
        st.session_state._rag_cluster_explanation = None
        st.session_state._rag_sensitivity = None
        st.session_state._rag_sensitivity_explanation = None
        st.session_state._rag_temporal = None
        st.session_state._rag_temporal_explanation = None
        st.session_state._rag_llm_response = None
        st.session_state._rag_report = None

    # 読み込み済みセッションがある場合、Collection未選択でも続行
    if not _selected_list:
        _loaded_col = st.session_state.get("_rag_loaded_collection", "")
        if _loaded_col and st.session_state.get("_rag_cached_data") is not None:
            _selected_list = [_loaded_col] if isinstance(_loaded_col, str) else _loaded_col
            _selected_list = [s for s in ((_loaded_col.split(", ") if ", " in _loaded_col else [_loaded_col])) if s]
        else:
            return

    # 表示用の選択名（レポート等で使用）
    _selected = ", ".join(_selected_list)

    # ===== PageIndex専用画面 =====
    if _is_page_index:
        _pi_name = _selected_list[0].replace("[PageIndex] ", "")
        _pi_pages = _page_index_dict.get(_pi_name, [])
        _data_type = "PageIndex"

        if not _pi_pages:
            st.warning("ページデータが0件です")
            return

        df = pd.DataFrame(_pi_pages)
        total_count = len(df)

        # ツリー構造表示
        st.subheader("Page Tree")
        _categories = {}
        for p in _pi_pages:
            cat = p.get("category", "未分類")
            if cat not in _categories:
                _categories[cat] = []
            _categories[cat].append(p)

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig_tree, ax_tree = plt.subplots(figsize=(12, max(4, len(_pi_pages) * 0.35)))
        ax_tree.set_xlim(-0.5, 10)
        ax_tree.set_ylim(-0.5, len(_pi_pages) + len(_categories))
        ax_tree.axis("off")
        ax_tree.set_title(f"Page Index: {_pi_name} ({total_count} pages)", fontsize=14, fontweight="bold")

        # ハイライト対象のIDセット（感度分析後にセット）
        _highlight_ids = set()
        _pi_sens = st.session_state.get("_rag_pi_sensitivity")
        if _pi_sens and _pi_sens.get("pi_name") == _pi_name:
            _highlight_ids = set(_pi_sens.get("selected_ids", []))

        y_pos = len(_pi_pages) + len(_categories) - 1
        for cat, pages in _categories.items():
            # カテゴリヘッダー
            ax_tree.text(0.3, y_pos, f"[{cat}]", fontsize=11, fontweight="bold", va="center",
                        fontfamily="IPAexGothic")
            y_pos -= 1
            for p in pages:
                pid = p["id"]
                title = p.get("title", "")
                _color = "#1565C0" if pid in _highlight_ids else "#333333"
                _weight = "bold" if pid in _highlight_ids else "normal"
                _marker = ">>>" if pid in _highlight_ids else " - "
                ax_tree.text(1.0, y_pos, f"{_marker} [{pid}] {title}", fontsize=9, va="center",
                            color=_color, fontweight=_weight, fontfamily="IPAexGothic")
                y_pos -= 1

        st.pyplot(fig_tree)
        plt.close(fig_tree)

        # データ一覧
        _list_cols = [c for c in df.columns if c not in ("sort_order",)]
        st.dataframe(df[_list_cols], hide_index=True, use_container_width=True, height=300)

        # PageIndex感度分析
        st.markdown("---")
        st.subheader("Page Sensitivity")
        _pi_query = st.text_input("Query:", placeholder="キーワードや文章を入力してページ選択をシミュレート", key="rag_pi_sens_query")
        _pi_max = st.slider("Max Pages:", min_value=1, max_value=min(10, total_count), value=min(5, total_count), key="rag_pi_max")

        if _pi_query and st.button("Analyze", key="rag_pi_sens_run"):
            # PageIndex検索エージェントでページ選択をシミュレート
            import DigiM_Tool as _dmt_pi
            with st.spinner("ページ選択をシミュレート中..."):
                try:
                    _exec_info = {"SERVICE_INFO": st.session_state.web_service, "USER_INFO": st.session_state.web_user}
                    _support_agent = "agent_59PageIndexSearch.json"
                    _sel_ids = _dmt_pi.page_index_search(_exec_info, _support_agent, _pi_query, _pi_pages, _pi_max)
                    st.session_state._rag_pi_sensitivity = {
                        "pi_name": _pi_name,
                        "query": _pi_query,
                        "selected_ids": _sel_ids,
                    }
                    st.rerun()  # ツリーをハイライト付きで再描画
                except Exception as e:
                    st.warning(f"ページ選択シミュレートでエラー: {e}")

        # 感度分析結果表示
        if _pi_sens and _pi_sens.get("pi_name") == _pi_name:
            st.caption(f"Query: **{_pi_sens['query']}** → 選択ページ: **{', '.join(_pi_sens['selected_ids'])}**")
            _sel_pages = [p for p in _pi_pages if p["id"] in _pi_sens["selected_ids"]]
            if _sel_pages:
                st.dataframe(pd.DataFrame(_sel_pages), hide_index=True, use_container_width=True)

        # Ask Agent（PageIndex用）
        _pi_context = f"以下のページインデックスデータと分析結果を踏まえて質問に回答してください。\n\nPageIndex: {_pi_name} ({total_count}ページ)\n\nページ一覧:\n"
        for p in _pi_pages:
            _pi_context += f"- [{p['id']}] {p.get('title','')} ({p.get('category','')}) : {p.get('summary','')}\n"
        if _pi_sens and _pi_sens.get("pi_name") == _pi_name:
            _pi_context += f"\n感度分析結果 (Query: {_pi_sens['query']}):\n選択ページ: {', '.join(_pi_sens['selected_ids'])}\n"
        _ask_agent_ui(_pi_context, key_prefix="rag_pi")
        _show_ask_result(key_prefix="rag_pi")

        # Export Report（PageIndex用）
        st.markdown("---")
        st.subheader("Export Report")
        if st.button("Generate Report", key="rag_pi_gen_report"):
            _now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _report = f"# RAG Explorer {_now}\n\n"
            _report += f"**分析実施日:** {_now}\n\n"
            _report += f"**ページ数:** {total_count}\n\n"
            _report += "## Page Tree\n\n"
            for cat, pages in _categories.items():
                _report += f"### {cat}\n"
                for p in pages:
                    _report += f"- [{p['id']}] {p.get('title', '')}: {p.get('summary', '')}\n"
                _report += "\n"
            _pi_sens = st.session_state.get("_rag_pi_sensitivity")
            if _pi_sens and _pi_sens.get("pi_name") == _pi_name:
                _report += f"## Page Sensitivity\n\nQuery: {_pi_sens['query']}\n\n"
                _report += f"選択ページ: {', '.join(_pi_sens['selected_ids'])}\n\n"
            _pi_history = st.session_state.get("_rag_pi_ask_history", [])
            if _pi_history:
                _report += "## Ask Agent\n\n"
                for _h in _pi_history:
                    _report += f"**Q ({_h.get('timestamp','')}):** {_h.get('query','')}\n\n"
                    _report += f"**A ({_h.get('agent_name','')}):** {_h.get('response','')}\n\n---\n\n"
            _report += f"\n---\nGenerated: {_now}\n"
            st.session_state._rag_report = _report
            try:
                _saved_path = _save_analysis_session(f"[PageIndex] {_pi_name}")
                st.success(f"レポートを生成し、セッションを保存しました: {_saved_path}")
            except Exception as e:
                st.success("レポートを生成しました")
                st.warning(f"セッション保存エラー: {e}")

        if st.session_state.get("_rag_report"):
            _report_name = f"RAG_Explorer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            st.download_button("Download (.md)", data=st.session_state._rag_report.encode("utf-8"),
                              file_name=f"{_report_name}.md", mime="text/markdown", key="rag_pi_dl_md")

        return  # PageIndexはここで終了（以降のChromaDB用処理をスキップ）

    # ===== ChromaDB用画面（以降は既存ロジック） =====
    _data_type = "ChromaDB"

    # データ取得（キャッシュがあればそれを使う）
    if st.session_state.get("_rag_cached_data") is not None:
        df = st.session_state._rag_cached_data
        _data_type = st.session_state._rag_cached_type
    else:
        _all_raw_data = []
        for _sel in _selected_list:
            _col_data = dmc.get_rag_collection_data(_sel)
            for d in _col_data:
                d["_source"] = _sel
            _all_raw_data.extend(_col_data)

        if not _all_raw_data:
            st.warning("データが0件です")
            return

        # PageIndexとChromaDBが混在する場合はMixed
        _has_pi = any(s.startswith("[PageIndex]") for s in _selected_list)
        _has_db = any(not s.startswith("[PageIndex]") for s in _selected_list)
        if _has_pi and _has_db:
            _data_type = "Mixed"
        elif _has_pi:
            _data_type = "PageIndex"

        df = pd.DataFrame(_all_raw_data)
        st.session_state._rag_cached_data = df
        st.session_state._rag_cached_type = _data_type

    total_count = len(df)

    # ベクトルデータ列は表示から除外
    _exclude_cols = [c for c in df.columns if "vector_data" in c]
    df_display = df.drop(columns=_exclude_cols, errors="ignore")

    # リスト型カラムを文字列に変換（tags等）
    for c in df_display.columns:
        if df_display[c].apply(lambda x: isinstance(x, list)).any():
            df_display[c] = df_display[c].apply(lambda x: ", ".join(str(i) for i in x) if isinstance(x, list) else x)

    # フィルタ可能なカラムを事前計算
    _filterable_cols = [c for c in df_display.columns if df_display[c].dtype == "object" and df_display[c].nunique() < 100]

    # フィルタセクション
    _has_date = "create_date" in df_display.columns
    if _has_date:
        _filter_col1, _filter_col2, _filter_col3 = st.columns(3)
    else:
        _filter_col1, _filter_col2, _filter_col3 = st.columns(3)
    _filter_column = _filter_col1.selectbox("Filter Column:", ["(none)"] + _filterable_cols, key="rag_filter_col")
    _filter_values = []
    if _filter_column != "(none)":
        _unique_vals = sorted(df_display[_filter_column].dropna().unique().tolist())
        _filter_values = _filter_col2.multiselect("Filter Value:", _unique_vals, key="rag_filter_val")
    _search_text = _filter_col3.text_input("Text Search:", value="", placeholder="ワイルドカード * 対応", key="rag_search_text")

    # Privateフラグ除外
    _exclude_private = False
    if "private" in df_display.columns:
        _exclude_private = st.checkbox("Exclude Private Data", value=True, key="rag_exclude_private")

    # 日付範囲フィルタ（create_dateがある場合）
    _date_from = None
    _date_to = None
    if _has_date:
        from datetime import date as _date_type
        _dates_parsed = pd.to_datetime(df_display["create_date"], errors="coerce").dropna()
        if not _dates_parsed.empty:
            _min_date = _dates_parsed.min().date()
            _max_date = _dates_parsed.max().date()
            _date_col1, _date_col2 = st.columns(2)
            _date_from = _date_col1.date_input("Date From:", value=_min_date, min_value=_min_date, max_value=_max_date, key="rag_date_from")
            _date_to = _date_col2.date_input("Date To:", value=_max_date, min_value=_min_date, max_value=_max_date, key="rag_date_to")

    # グループ集計・検索ボタン
    _action_col1, _action_col2, _action_col3 = st.columns([1, 1, 1])
    _group_by = _action_col1.selectbox("Group By:", ["(none)"] + _filterable_cols, key="rag_group_by")
    _do_search = _action_col3.button("Search", key="rag_do_search", type="primary")

    # 検索実行時にフラグを保持
    if _do_search:
        st.session_state._rag_searched = True
    if not st.session_state.get("_rag_searched", False):
        st.caption(f"**{_data_type}** | Total: **{total_count}** 件 | 検索条件を指定して **Search** を押してください（指定なしで全件表示）")
        return

    # フィルタ適用
    df_filtered = df_display.copy()
    if _exclude_private and "private" in df_filtered.columns:
        df_filtered = df_filtered[df_filtered["private"] != True]
    if _filter_column != "(none)" and _filter_values:
        df_filtered = df_filtered[df_filtered[_filter_column].isin(_filter_values)]
    if _date_from is not None and _date_to is not None and _has_date:
        _df_dates = pd.to_datetime(df_filtered["create_date"], errors="coerce")
        _mask_date = (_df_dates >= pd.Timestamp(_date_from)) & (_df_dates <= pd.Timestamp(_date_to) + pd.Timedelta(days=1))
        df_filtered = df_filtered[_mask_date]
    if _search_text:
        _pattern = _search_text if "*" in _search_text else f"*{_search_text}*"
        _mask = df_filtered.apply(
            lambda row: any(fnmatch.fnmatch(str(v).lower(), _pattern.lower()) for v in row), axis=1)
        df_filtered = df_filtered[_mask]

    # カラム順序の整理
    _priority_cols = ["id", "db", "title", "create_date", "category", "X1", "X2", "key_text", "value_text"]
    _existing_priority = [c for c in _priority_cols if c in df_filtered.columns]
    _remaining = sorted([c for c in df_filtered.columns if c not in _priority_cols])
    df_filtered = df_filtered[_existing_priority + _remaining]

    filtered_count = len(df_filtered)
    st.caption(f"**{_data_type}** | Total: **{total_count}** 件 | Filtered: **{filtered_count}** 件")

    # グループ集計
    if _group_by != "(none)":
        _group_df = df_filtered.groupby(_group_by).size().reset_index(name="count").sort_values("count", ascending=False)
        _action_col2.dataframe(_group_df, hide_index=True, use_container_width=True)

    # データテーブル（散布図生成後は座標付きに差し替え）
    _df_with_coords = df_filtered
    _table_placeholder = st.empty()
    _table_placeholder.dataframe(df_filtered, hide_index=True, use_container_width=True, height=400)

    # CSVダウンロード（散布図生成後に座標付きCSVに差し替え）
    _csv_placeholder = st.empty()
    _csv_data = df_filtered.to_csv(index=False).encode("utf-8-sig")
    _csv_placeholder.download_button("CSV Download", data=_csv_data, file_name=f"rag_{_selected}.csv", mime="text/csv", key="rag_csv_dl")

    # 散布図セクション（ChromaDBでvector_data_value_textがある場合のみ）
    _has_vectors = "vector_data_value_text" in df.columns and _data_type in ("ChromaDB", "Mixed")
    if _has_vectors and filtered_count >= 3:
        st.markdown("---")
        st.subheader("Scatter Plot")
        _scatter_col1, _scatter_col2, _scatter_col3, _scatter_col4 = st.columns([1, 1, 1, 1])
        _dim_method = _scatter_col1.radio("Dimension Reduction:", ["PCA", "t-SNE"], index=0, horizontal=True, key="rag_dim_method")
        _dim_params = {}
        if _dim_method == "t-SNE":
            _dim_params["perplexity"] = _scatter_col2.number_input("Perplexity:", value=30, step=1, key="rag_tsne_perp")

        # 色分け用カラム選択（categoryがあればデフォルトに）
        _color_options = ["(none)"] + _filterable_cols
        _color_default = 0
        if "category" in _filterable_cols:
            _color_default = _color_options.index("category")
        _color_col = _scatter_col3.selectbox("Color By:", _color_options, index=_color_default, key="rag_color_by")

        # ドットサイズモード・生成ボタン
        _scatter_col5, _scatter_col6 = st.columns([1, 1])
        _size_mode = _scatter_col5.radio("Dot Size:", ["Uniform", "Newer=Larger"], index=0, horizontal=True, key="rag_dot_size")
        _gen_scatter = _scatter_col6.button("Generate Scatter", key="rag_gen_scatter")

        if _gen_scatter:
            import DigiM_VAnalytics as dmva

            # category_mapから色定義を読み込み
            _cat_color_map = {}
            try:
                _cat_map_json = dmu.read_json_file("category_map.json", mst_folder_path)
                if not _cat_map_json:
                    _cat_map_json = dmu.read_json_file("sample_category_map.json", mst_folder_path)
                _cat_color_map = _cat_map_json.get("CategoryColor", {})
            except Exception:
                pass

            # フィルタ済みデータ（ベクトル付き）
            _df_for_scatter = df[df["id"].isin(df_filtered["id"])].copy()

            with st.spinner("次元削減を実行中..."):
                try:
                    _df_reduced, _dim_info = dmva.reduce_dimensions(_df_for_scatter, method=_dim_method, params=_dim_params)

                    # 結果をキャッシュ
                    st.session_state._rag_scatter_cache = {
                        "df_reduced": _df_reduced,
                        "dim_info": _dim_info,
                        "dim_method": _dim_method,
                        "color_col": _color_col,
                        "size_mode": _size_mode,
                        "cat_color_map": _cat_color_map,
                        "selected": _selected,
                        "filtered_count": filtered_count,
                    }
                except Exception as e:
                    st.warning(f"散布図の生成でエラーが発生しました: {e}")
                    st.session_state._rag_scatter_cache = None

        # キャッシュがあれば散布図を表示
        _scatter_cache = st.session_state.get("_rag_scatter_cache")
        if _scatter_cache and _scatter_cache.get("selected") == _selected:
            _df_reduced = _scatter_cache["df_reduced"]
            _dim_info = _scatter_cache["dim_info"]
            _sc_method = _scatter_cache["dim_method"]
            _sc_color = _scatter_cache["color_col"]
            _sc_size = _scatter_cache["size_mode"]
            _sc_cat_map = _scatter_cache["cat_color_map"]
            _sc_count = _scatter_cache["filtered_count"]

            # ドットサイズ計算
            _dot_sizes = None
            if _sc_size == "Newer=Larger" and "create_date" in _df_reduced.columns:
                _dates = pd.to_datetime(_df_reduced["create_date"], errors="coerce")
                if _dates.notna().any():
                    _min_ts = _dates.min().timestamp()
                    _max_ts = _dates.max().timestamp()
                    _range = _max_ts - _min_ts if _max_ts > _min_ts else 1
                    _dot_sizes = _dates.apply(lambda d: 10 + 190 * ((d.timestamp() - _min_ts) / _range) if pd.notna(d) else 10).values

            # 散布図描画
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(10, 7))

            if _sc_color != "(none)" and _sc_color in _df_reduced.columns:
                _categories = sorted(_df_reduced[_sc_color].dropna().unique())
                for cat in _categories:
                    _mask = _df_reduced[_sc_color] == cat
                    _color = _sc_cat_map.get(cat, None)
                    _s = _dot_sizes[_mask] if _dot_sizes is not None else None
                    ax.scatter(_df_reduced.loc[_mask, "X1"], _df_reduced.loc[_mask, "X2"],
                              color=_color, s=_s, alpha=0.7, label=str(cat)[:20])
                ax.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
            else:
                ax.scatter(_df_reduced["X1"], _df_reduced["X2"], s=_dot_sizes, alpha=0.7)

            ax.set_title(f"{_sc_method} - {_selected} ({_sc_count}件)\n{_dim_info}")
            ax.grid(True)
            st.pyplot(fig)
            plt.close(fig)

            # 座標を一覧に追加して差し替え
            _coord_map = _df_reduced.set_index("id")[["X1", "X2"]]
            _df_with_coords = df_filtered.copy()
            _df_with_coords = _df_with_coords.merge(_coord_map, left_on="id", right_index=True, how="left")
            _existing_priority = [c for c in _priority_cols if c in _df_with_coords.columns]
            _remaining = sorted([c for c in _df_with_coords.columns if c not in _priority_cols])
            _df_with_coords = _df_with_coords[_existing_priority + _remaining]
            _table_placeholder.dataframe(_df_with_coords, hide_index=True, use_container_width=True, height=400)
            _csv_data = _df_with_coords.to_csv(index=False).encode("utf-8-sig")
            _csv_placeholder.download_button("CSV Download", data=_csv_data, file_name=f"rag_{_selected}.csv", mime="text/csv", key="rag_csv_dl_updated")

    # ===== 感度分析セクション（散布図キャッシュがある場合のみ） =====
    _scatter_cache = st.session_state.get("_rag_scatter_cache")
    if _scatter_cache and _scatter_cache.get("selected") == _selected:
        st.markdown("---")
        st.subheader("Sensitivity Analysis")
        _sens_query = st.text_input("Query:", placeholder="キーワードや文章を入力して知識の反応を分析", key="rag_sens_query")

        # 期間ボーナス設定
        _sens_has_date = "create_date" in df.columns
        _sens_date_from = None
        _sens_date_to = None
        _sens_bonus = 0.0
        if _sens_has_date:
            _dates_for_sens = pd.to_datetime(df_filtered["create_date"], errors="coerce").dropna()
            if not _dates_for_sens.empty:
                _s_min = _dates_for_sens.min().date()
                _s_max = _dates_for_sens.max().date()
                _sb_col1, _sb_col2, _sb_col3 = st.columns([1, 1, 1])
                _sens_date_from = _sb_col1.date_input("Bonus From:", value=_s_min, min_value=_s_min, max_value=_s_max, key="rag_sens_dfrom")
                _sens_date_to = _sb_col2.date_input("Bonus To:", value=_s_max, min_value=_s_min, max_value=_s_max, key="rag_sens_dto")
                _sens_bonus = _sb_col3.number_input("Bonus (0=off):", value=0.0, min_value=0.0, max_value=1.0, step=0.1, format="%.1f", key="rag_sens_bonus")

        _sens_top_n = st.slider("Top N:", min_value=5, max_value=50, value=20, key="rag_sens_topn")

        if _sens_query and st.button("Analyze Sensitivity", key="rag_run_sens"):
            import DigiM_VAnalytics as dmva
            _df_for_sens = df[df["id"].isin(df_filtered["id"])].copy()
            _df_reduced_sens = _scatter_cache["df_reduced"]
            _coord_sens = _df_reduced_sens.set_index("id")[["X1", "X2"]]
            _df_for_sens = _df_for_sens.merge(_coord_sens, left_on="id", right_index=True, how="left")
            _cl_cache = st.session_state.get("_rag_cluster_cache")
            if _cl_cache and _cl_cache.get("selected") == _selected and "Cluster" in _cl_cache["df_clustered"].columns:
                _cl_map = _cl_cache["df_clustered"].set_index("id")[["Cluster"]]
                _df_for_sens = _df_for_sens.merge(_cl_map, left_on="id", right_index=True, how="left")

            with st.spinner("類似度を計算中..."):
                try:
                    _sens_ranking, _sens_cluster_stats = dmva.sensitivity_analysis(
                        _df_for_sens, _sens_query, top_n=_sens_top_n,
                        date_from=_sens_date_from, date_to=_sens_date_to, date_bonus=_sens_bonus)
                    st.session_state._rag_sensitivity = {
                        "ranking": _sens_ranking,
                        "cluster_stats": _sens_cluster_stats,
                        "query": _sens_query,
                        "selected": _selected,
                    }
                except Exception as e:
                    st.warning(f"感度分析でエラーが発生しました: {e}")

        # キャッシュから感度分析結果を表示
        _sens_cache = st.session_state.get("_rag_sensitivity")
        if _sens_cache and _sens_cache.get("selected") == _selected:
            _sens = _sens_cache
            st.caption(f"Query: **{_sens['query']}** | Top {len(_sens['ranking'])}")

            # 感度分析対象のみの散布図
            _sr = _sens["ranking"]
            if "X1" in _sr.columns and "X2" in _sr.columns:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                from matplotlib.colors import LinearSegmentedColormap

                _df_all = _scatter_cache["df_reduced"]
                fig_sens_sc, ax_sens_sc = plt.subplots(figsize=(10, 7))
                ax_sens_sc.scatter(_df_all["X1"], _df_all["X2"], color="lightgray", alpha=0.3, s=15)

                # ボーナス未適用 → 青グラデ、ボーナス適用 → 緑グラデ
                _blue_cmap = LinearSegmentedColormap.from_list("blue_v", ["#E8F0FE", "#1565C0", "#0D47A1"])
                _green_cmap = LinearSegmentedColormap.from_list("green_v", ["#E8F5E9", "#2E7D32", "#1B5E20"])

                _sr_normal = _sr[~_sr["bonus_applied"]]
                _sr_bonus = _sr[_sr["bonus_applied"]]

                _score_max = _sr["score"].max() if not _sr["score"].empty else 1
                # 通常（青）
                if not _sr_normal.empty:
                    _inv_n = _score_max - _sr_normal["score"]
                    ax_sens_sc.scatter(_sr_normal["X1"], _sr_normal["X2"], c=_inv_n,
                                      cmap=_blue_cmap, alpha=0.9, s=60, edgecolors="black", linewidths=0.5,
                                      label="Normal")
                # ボーナス適用（緑）
                if not _sr_bonus.empty:
                    _inv_b = _score_max - _sr_bonus["score"]
                    ax_sens_sc.scatter(_sr_bonus["X1"], _sr_bonus["X2"], c=_inv_b,
                                      cmap=_green_cmap, alpha=0.9, s=60, edgecolors="black", linewidths=0.5,
                                      marker="D", label="Bonus Applied")
                ax_sens_sc.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
                ax_sens_sc.set_title(f"Sensitivity: \"{_sens['query']}\" (Top {len(_sr)})")
                ax_sens_sc.grid(True)
                st.pyplot(fig_sens_sc)
                plt.close(fig_sens_sc)

            # クラスター別平均スコア
            if _sens["cluster_stats"] is not None:
                st.markdown("**クラスター別 平均スコア:**")
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                _cs = _sens["cluster_stats"]
                fig_sens, ax_sens = plt.subplots(figsize=(8, 3))
                ax_sens.barh([f"Cluster {int(c)}" if c >= 0 else "Noise" for c in _cs["Cluster"]],
                             _cs["avg_score"], color="steelblue", alpha=0.8)
                ax_sens.set_xlabel("Avg Score (lower = more relevant)")
                ax_sens.invert_yaxis()
                ax_sens.grid(axis="x", alpha=0.3)
                st.pyplot(fig_sens)
                plt.close(fig_sens)

            # スコアランキング
            st.markdown("**スコアランキング:**")
            _display_cols = ["score", "cos_distance", "bonus_applied", "id", "title", "category", "value_text"]
            if "Cluster" in _sr.columns:
                _display_cols.insert(5, "Cluster")
            _display_cols = [c for c in _display_cols if c in _sr.columns]
            st.dataframe(_sr[_display_cols], hide_index=True, use_container_width=True, height=300)

            # LLMによる感度分析解説
            _sens_exp_col1, _sens_exp_col2 = st.columns([1, 1])
            _sens_engine_list = list(dmu.read_json_file("agent_23DataAnalyst.json", agent_folder_path).get("ENGINE", {}).get("LLM", {}).keys())
            _sens_engine_list = [e for e in _sens_engine_list if e != "DEFAULT"]
            _sens_engine = _sens_exp_col2.selectbox("Engine:", _sens_engine_list, key="rag_sens_engine") if _sens_engine_list else None

            if _sens_exp_col1.button("Explain Sensitivity", key="rag_explain_sens"):
                _sens_agent_file = "agent_23DataAnalyst.json"
                # 上位データのサマリー構築
                _sens_summary = f"クエリ: {_sens['query']}\n\n上位{len(_sr)}件のデータ:\n"
                for _, row in _sr.head(10).iterrows():
                    _bonus_mark = " [Bonus]" if row.get("bonus_applied") else ""
                    _title = row.get("title", "")
                    _cat = row.get("category", "")
                    _score = row.get("score", "")
                    _dist = row.get("cos_distance", "")
                    _text = str(row.get("value_text", ""))[:80]
                    _sens_summary += f"  score={_score}, cos_dist={_dist}{_bonus_mark} [{_cat}] {_title}: {_text}\n"
                with st.spinner("感度分析を解説中..."):
                    try:
                        _agent = dma.DigiM_Agent(_sens_agent_file)
                        if _sens_engine and _sens_engine in _agent.agent.get("ENGINE", {}).get("LLM", {}):
                            _agent.agent["ENGINE"]["LLM"]["DEFAULT"] = _sens_engine
                        _template = _agent.set_prompt_template("Sensitivity Analyst")
                        _prompt = f"{_template}\n{_sens_summary}"
                        _response = ""
                        for _, chunk, _ in _agent.generate_response("LLM", _prompt, [], stream_mode=False):
                            if chunk:
                                _response += chunk
                        st.session_state._rag_sensitivity_explanation = _response
                    except Exception as e:
                        st.error(f"感度分析解説エラー: {e}")

            if st.session_state.get("_rag_sensitivity_explanation"):
                st.markdown("**感度分析の解説:**")
                st.markdown(st.session_state._rag_sensitivity_explanation)

    # クラスタリングセクション（散布図キャッシュがある場合のみ）
    _scatter_cache = st.session_state.get("_rag_scatter_cache")
    if _scatter_cache and _scatter_cache.get("selected") == _selected:
        st.markdown("---")
        st.subheader("Clustering")
        _cl_col1, _cl_col2, _cl_col3 = st.columns([1, 1, 1])
        _cl_method = _cl_col1.selectbox("Method:", ["K-Means", "DBSCAN", "Hierarchical"], key="rag_cl_method")
        _cl_params = {}
        if _cl_method in ["K-Means", "Hierarchical"]:
            _cl_params["n_clusters"] = _cl_col2.number_input("Clusters:", value=5, min_value=2, max_value=20, step=1, key="rag_cl_k")
        elif _cl_method == "DBSCAN":
            # eps自動推定値をデフォルトに
            import DigiM_VAnalytics as _dmva_eps
            _default_min_samples = 5
            _df_for_eps = _scatter_cache["df_reduced"]
            _auto_eps = _dmva_eps.estimate_dbscan_eps(_df_for_eps, k=_default_min_samples)
            _cl_params["min_samples"] = _cl_col3.number_input("min_samples:", value=_default_min_samples, min_value=2, step=1, key="rag_cl_min")
            _cl_params["eps"] = _cl_col2.number_input(f"eps (auto={_auto_eps}):", value=_auto_eps, min_value=0.1, step=0.5, format="%.2f", key="rag_cl_eps")

        _run_cluster = st.button("Run Clustering", key="rag_run_cluster")

        if _run_cluster:
            import DigiM_VAnalytics as dmva
            _df_reduced = _scatter_cache["df_reduced"]
            try:
                _df_clustered, _cl_info = dmva.apply_clustering(_df_reduced, method=_cl_method, params=_cl_params)
                _cl_summary = dmva.build_cluster_summary(_df_clustered)
                st.session_state._rag_cluster_cache = {
                    "df_clustered": _df_clustered,
                    "cl_info": _cl_info,
                    "cl_summary": _cl_summary,
                    "selected": _selected,
                }
            except Exception as e:
                st.warning(f"クラスタリングでエラーが発生しました: {e}")
                st.session_state._rag_cluster_cache = None

        # キャッシュからクラスタリング結果を表示
        _cluster_cache = st.session_state.get("_rag_cluster_cache")
        if _cluster_cache and _cluster_cache.get("selected") == _selected:
            _df_clustered = _cluster_cache["df_clustered"]
            _cl_info = _cluster_cache["cl_info"]
            _cl_summary = _cluster_cache["cl_summary"]

            st.caption(f"**{_cl_info}**")

            # クラスター散布図
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig_cl, ax_cl = plt.subplots(figsize=(10, 7))
            _cl_labels = sorted(_df_clustered["Cluster"].unique())
            _cmap = plt.cm.get_cmap("tab10", len(_cl_labels))
            for i, cl in enumerate(_cl_labels):
                _mask = _df_clustered["Cluster"] == cl
                _label = f"Cluster {cl}" if cl >= 0 else "Noise"
                _color = "gray" if cl < 0 else _cmap(i)
                ax_cl.scatter(_df_clustered.loc[_mask, "X1"], _df_clustered.loc[_mask, "X2"],
                              color=_color, alpha=0.7, label=_label)
            ax_cl.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
            ax_cl.set_title(f"Clustering: {_cl_info}")
            ax_cl.grid(True)
            st.pyplot(fig_cl)
            plt.close(fig_cl)

            # クラスター分布テーブル
            _cl_dist = _df_clustered.groupby("Cluster").size().reset_index(name="count").sort_values("Cluster")
            st.dataframe(_cl_dist, hide_index=True, use_container_width=True)

            # 座標+Clusterを一覧に追加して差し替え
            _coord_cl_map = _df_clustered.set_index("id")[["X1", "X2", "Cluster"]]
            _df_with_coords = df_filtered.copy()
            _df_with_coords = _df_with_coords.merge(_coord_cl_map, left_on="id", right_index=True, how="left")
            _priority_with_cluster = ["id", "db", "title", "create_date", "category", "Cluster", "X1", "X2", "key_text", "value_text"]
            _existing_priority = [c for c in _priority_with_cluster if c in _df_with_coords.columns]
            _remaining = sorted([c for c in _df_with_coords.columns if c not in _priority_with_cluster])
            _df_with_coords = _df_with_coords[_existing_priority + _remaining]
            _table_placeholder.dataframe(_df_with_coords, hide_index=True, use_container_width=True, height=400)
            _csv_data = _df_with_coords.to_csv(index=False).encode("utf-8-sig")
            _csv_placeholder.download_button("CSV Download", data=_csv_data, file_name=f"rag_{_selected}_clustered.csv", mime="text/csv", key="rag_csv_dl_clustered")

            # LLMによるクラスター解説（散布図+一覧の下に表示）
            _explain_col1, _explain_col2 = st.columns([1, 1])
            _cl_engine_list = list(dmu.read_json_file("agent_23DataAnalyst.json", agent_folder_path).get("ENGINE", {}).get("LLM", {}).keys())
            _cl_engine_list = [e for e in _cl_engine_list if e != "DEFAULT"]
            _cl_engine = _explain_col2.selectbox("Explain Engine:", _cl_engine_list, key="rag_cl_engine") if _cl_engine_list else None

            if _explain_col1.button("Explain Clusters", key="rag_explain_cluster"):
                _cl_agent_file = "agent_23DataAnalyst.json"
                _cl_data = f"以下はRAGデータ「{_selected}」のクラスタリング結果です。\n\nクラスタリング手法: {_cl_info}\n{_cl_summary}"
                with st.spinner("クラスターを解説中..."):
                    try:
                        _agent = dma.DigiM_Agent(_cl_agent_file)
                        if _cl_engine and _cl_engine in _agent.agent.get("ENGINE", {}).get("LLM", {}):
                            _agent.agent["ENGINE"]["LLM"]["DEFAULT"] = _cl_engine
                        _template = _agent.set_prompt_template("Cluster Analyst")
                        _prompt = f"{_template}\n{_cl_data}"
                        _response = ""
                        for _, chunk, _ in _agent.generate_response("LLM", _prompt, [], stream_mode=False):
                            if chunk:
                                _response += chunk
                        st.session_state._rag_cluster_explanation = _response
                    except Exception as e:
                        st.error(f"クラスター解説エラー: {e}")

            # キャッシュからクラスター解説を表示
            if st.session_state.get("_rag_cluster_explanation"):
                st.markdown("**クラスター解説:**")
                st.markdown(st.session_state._rag_cluster_explanation)

    # ===== 時系列分析セクション（create_dateがある場合のみ） =====
    if _has_date and filtered_count >= 3:
        st.markdown("---")
        st.subheader("Temporal Analysis")
        _temp_col1, _temp_col2 = st.columns([1, 1])
        _temp_period = _temp_col1.selectbox("Period:", ["month", "quarter", "year"], key="rag_temp_period")
        _temp_topn = _temp_col2.slider("Keywords per period:", min_value=3, max_value=20, value=7, key="rag_temp_topn")

        if st.button("Analyze Temporal", key="rag_run_temporal"):
            import DigiM_VAnalytics as dmva
            with st.spinner("時系列分析を実行中..."):
                try:
                    _cat_pivot, _kw_df, _temp_summary = dmva.temporal_analysis(
                        df_filtered, period=_temp_period, top_n_keywords=_temp_topn)
                    st.session_state._rag_temporal = {
                        "cat_pivot": _cat_pivot,
                        "kw_df": _kw_df,
                        "summary": _temp_summary,
                        "period": _temp_period,
                    }
                except Exception as e:
                    st.warning(f"時系列分析でエラーが発生しました: {e}")

        # キャッシュから時系列分析結果を表示
        if st.session_state.get("_rag_temporal"):
            _temp = st.session_state._rag_temporal

            # カテゴリ推移グラフ
            if _temp["cat_pivot"] is not None and not _temp["cat_pivot"].empty:
                st.markdown("**カテゴリ構成の推移:**")
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                # category_mapの色を適用
                _cat_color_map_t = {}
                try:
                    _cat_map_json_t = dmu.read_json_file("category_map.json", mst_folder_path)
                    if not _cat_map_json_t:
                        _cat_map_json_t = dmu.read_json_file("sample_category_map.json", mst_folder_path)
                    _cat_color_map_t = _cat_map_json_t.get("CategoryColor", {})
                except Exception:
                    pass
                _cp = _temp["cat_pivot"]
                _colors = [_cat_color_map_t.get(c, None) for c in _cp.columns]
                fig_cat, ax_cat = plt.subplots(figsize=(12, 5))
                _cp.plot(kind="bar", stacked=True, ax=ax_cat, color=_colors if all(_colors) else None, alpha=0.8)
                ax_cat.set_title(f"Category Composition ({_temp['period']})")
                ax_cat.set_ylabel("Count")
                ax_cat.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=7)
                plt.xticks(rotation=45, ha="right")
                plt.tight_layout()
                st.pyplot(fig_cat)
                plt.close(fig_cat)

            # キーワード推移テーブル
            if _temp["kw_df"] is not None and not _temp["kw_df"].empty:
                st.markdown("**期間別キーワード:**")
                st.dataframe(_temp["kw_df"], hide_index=True, use_container_width=True, height=300)

            # LLMによる時系列解説
            _temp_explain_col1, _temp_explain_col2 = st.columns([1, 1])
            _temp_engine_list = list(dmu.read_json_file("agent_23DataAnalyst.json", agent_folder_path).get("ENGINE", {}).get("LLM", {}).keys())
            _temp_engine_list = [e for e in _temp_engine_list if e != "DEFAULT"]
            _temp_engine = _temp_explain_col2.selectbox("Engine:", _temp_engine_list, key="rag_temp_engine") if _temp_engine_list else None

            if _temp_explain_col1.button("Explain Trends", key="rag_explain_temporal"):
                _cl_agent_file = "agent_23DataAnalyst.json"
                _temp_prompt_data = f"以下はRAGデータ「{_selected}」の時系列分析結果です。\n各期間のキーワードから関心の変遷を読み取ってください。\n\n{_temp['summary']}"
                with st.spinner("時系列の変遷を解説中..."):
                    try:
                        _agent = dma.DigiM_Agent(_cl_agent_file)
                        if _temp_engine and _temp_engine in _agent.agent.get("ENGINE", {}).get("LLM", {}):
                            _agent.agent["ENGINE"]["LLM"]["DEFAULT"] = _temp_engine
                        _template = _agent.set_prompt_template("Temporal Analyst")
                        _prompt = f"{_template}\n{_temp_prompt_data}"
                        _response = ""
                        for _, chunk, _ in _agent.generate_response("LLM", _prompt, [], stream_mode=False):
                            if chunk:
                                _response += chunk
                        st.session_state._rag_temporal_explanation = _response
                    except Exception as e:
                        st.error(f"時系列解説エラー: {e}")

            if st.session_state.get("_rag_temporal_explanation"):
                st.markdown("**時系列の変遷:**")
                st.markdown(st.session_state._rag_temporal_explanation)

    # Ask Agent（ChromaDB用 - 全分析結果をコンテキストに含める）
    _summary_lines = [f"以下のRAGデータと分析結果を踏まえて質問に回答してください。\n\nRAGデータ: {_selected} (フィルタ後: {filtered_count}件 / 全体: {total_count}件)"]
    _df_for_llm = df_filtered.drop(columns=[c for c in df_filtered.columns if "vector" in c], errors="ignore")
    if _filterable_cols:
        for col in _filterable_cols[:5]:
            _val_counts = _df_for_llm[col].value_counts().head(10).to_dict() if col in _df_for_llm.columns else {}
            if _val_counts:
                _summary_lines.append(f"\n[{col}の分布]\n" + "\n".join(f"  {k}: {v}件" for k, v in _val_counts.items()))
    _sample_n = min(30, len(_df_for_llm))
    _summary_lines.append(f"\n[データ(先頭{_sample_n}件)]\n{_df_for_llm.head(_sample_n).to_csv(index=False)}")
    _sens_cache = st.session_state.get("_rag_sensitivity")
    if _sens_cache and _sens_cache.get("selected") == _selected:
        _summary_lines.append(f"\n[感度分析結果 (Query: {_sens_cache['query']})]\n")
        for _, r in _sens_cache["ranking"].head(10).iterrows():
            _summary_lines.append(f"  score={r.get('score','')}, [{r.get('category','')}] {r.get('title','')}: {str(r.get('value_text',''))[:60]}")
    if st.session_state.get("_rag_sensitivity_explanation"):
        _summary_lines.append(f"\n[感度分析の解説]\n{st.session_state._rag_sensitivity_explanation[:500]}")
    _cl_cache = st.session_state.get("_rag_cluster_cache")
    if _cl_cache and _cl_cache.get("selected") == _selected:
        _summary_lines.append(f"\n[クラスタリング結果: {_cl_cache['cl_info']}]\n{_cl_cache['cl_summary'][:500]}")
    if st.session_state.get("_rag_cluster_explanation"):
        _summary_lines.append(f"\n[クラスター解説]\n{st.session_state._rag_cluster_explanation[:500]}")
    _temp_cache = st.session_state.get("_rag_temporal")
    if _temp_cache:
        _summary_lines.append(f"\n[時系列分析]\n{_temp_cache.get('summary', '')[:500]}")
    if st.session_state.get("_rag_temporal_explanation"):
        _summary_lines.append(f"\n[時系列解説]\n{st.session_state._rag_temporal_explanation[:500]}")

    _chromadb_context = "\n".join(_summary_lines)
    _ask_agent_ui(_chromadb_context, key_prefix="rag")
    _chromadb_response = _show_ask_result(key_prefix="rag")
    if _chromadb_response:
        st.session_state._rag_llm_response = _chromadb_response

    # ===== 分析結果のダウンロード =====
    st.markdown("---")
    st.subheader("Export Report")
    if st.button("Generate Report", key="rag_gen_report"):
        import base64
        import io
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        def _fig_to_md(fig):
            """matplotlibのfigをBase64埋め込みMarkdown画像に変換"""
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)
            b64 = base64.b64encode(buf.read()).decode()
            plt.close(fig)
            return f"![chart](data:image/png;base64,{b64})"

        _now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _report = f"# RAG Explorer {_now}\n\n"
        _report += f"**対象データ:** {_selected}\n\n"
        _report += f"**データ件数:** フィルタ後 {filtered_count}件 / 全体 {total_count}件\n\n"

        # 散布図
        _sc_cache = st.session_state.get("_rag_scatter_cache")
        if _sc_cache and _sc_cache.get("selected") == _selected:
            _report += "## Scatter Plot\n\n"
            _dfr = _sc_cache["df_reduced"]
            _sc_m = _sc_cache["dim_method"]
            _sc_info = _sc_cache["dim_info"]
            _sc_color = _sc_cache["color_col"]
            _sc_cat_map = _sc_cache.get("cat_color_map", {})
            fig_r, ax_r = plt.subplots(figsize=(10, 7))
            if _sc_color != "(none)" and _sc_color in _dfr.columns:
                for cat in sorted(_dfr[_sc_color].dropna().unique()):
                    _m = _dfr[_sc_color] == cat
                    ax_r.scatter(_dfr.loc[_m, "X1"], _dfr.loc[_m, "X2"], color=_sc_cat_map.get(cat), alpha=0.7, label=str(cat)[:20])
                ax_r.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
            else:
                ax_r.scatter(_dfr["X1"], _dfr["X2"], alpha=0.7)
            ax_r.set_title(f"{_sc_m} ({_sc_info})")
            ax_r.grid(True)
            _report += _fig_to_md(fig_r) + "\n\n"

        # 感度分析
        _sens_c = st.session_state.get("_rag_sensitivity")
        if _sens_c and _sens_c.get("selected") == _selected:
            _report += f"## Sensitivity Analysis\n\nQuery: {_sens_c.get('query', '')}\n\n"
            _sr = _sens_c["ranking"]
            if "X1" in _sr.columns and _sc_cache:
                _df_all = _sc_cache["df_reduced"]
                from matplotlib.colors import LinearSegmentedColormap
                _blue_cm = LinearSegmentedColormap.from_list("bv", ["#E8F0FE", "#1565C0", "#0D47A1"])
                _green_cm = LinearSegmentedColormap.from_list("gv", ["#E8F5E9", "#2E7D32", "#1B5E20"])
                fig_s, ax_s = plt.subplots(figsize=(10, 7))
                ax_s.scatter(_df_all["X1"], _df_all["X2"], color="lightgray", alpha=0.3, s=15)
                _score_max = _sr["score"].max() if not _sr["score"].empty else 1
                _sr_n = _sr[~_sr["bonus_applied"]]
                _sr_b = _sr[_sr["bonus_applied"]]
                if not _sr_n.empty:
                    ax_s.scatter(_sr_n["X1"], _sr_n["X2"], c=_score_max - _sr_n["score"], cmap=_blue_cm, alpha=0.9, s=60, edgecolors="black", linewidths=0.5)
                if not _sr_b.empty:
                    ax_s.scatter(_sr_b["X1"], _sr_b["X2"], c=_score_max - _sr_b["score"], cmap=_green_cm, alpha=0.9, s=60, edgecolors="black", linewidths=0.5, marker="D")
                ax_s.set_title(f"Sensitivity: \"{_sens_c['query']}\"")
                ax_s.grid(True)
                _report += _fig_to_md(fig_s) + "\n\n"
            if st.session_state.get("_rag_sensitivity_explanation"):
                _report += st.session_state._rag_sensitivity_explanation + "\n\n"

        # クラスタリング
        _cl_c = st.session_state.get("_rag_cluster_cache")
        if _cl_c and _cl_c.get("selected") == _selected:
            _report += f"## Clustering\n\n{_cl_c.get('cl_info', '')}\n\n"
            _dfc = _cl_c["df_clustered"]
            fig_c, ax_c = plt.subplots(figsize=(10, 7))
            _cmap_c = plt.cm.get_cmap("tab10", len(_dfc["Cluster"].unique()))
            for i, cl in enumerate(sorted(_dfc["Cluster"].unique())):
                _m = _dfc["Cluster"] == cl
                ax_c.scatter(_dfc.loc[_m, "X1"], _dfc.loc[_m, "X2"], color="gray" if cl < 0 else _cmap_c(i), alpha=0.7, label=f"Cluster {cl}" if cl >= 0 else "Noise")
            ax_c.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
            ax_c.set_title(f"Clustering: {_cl_c['cl_info']}")
            ax_c.grid(True)
            _report += _fig_to_md(fig_c) + "\n\n"
            if st.session_state.get("_rag_cluster_explanation"):
                _report += st.session_state._rag_cluster_explanation + "\n\n"

        # 時系列分析
        _temp_c = st.session_state.get("_rag_temporal")
        if _temp_c:
            _report += "## Temporal Analysis\n\n"
            if _temp_c.get("cat_pivot") is not None and not _temp_c["cat_pivot"].empty:
                _cat_color_map_r = {}
                try:
                    _cm_j = dmu.read_json_file("category_map.json", mst_folder_path)
                    if not _cm_j:
                        _cm_j = dmu.read_json_file("sample_category_map.json", mst_folder_path)
                    _cat_color_map_r = _cm_j.get("CategoryColor", {})
                except Exception:
                    pass
                _cp = _temp_c["cat_pivot"]
                _colors_r = [_cat_color_map_r.get(c) for c in _cp.columns]
                fig_t, ax_t = plt.subplots(figsize=(12, 5))
                _cp.plot(kind="bar", stacked=True, ax=ax_t, color=_colors_r if all(_colors_r) else None, alpha=0.8)
                ax_t.set_title(f"Category Composition ({_temp_c.get('period', 'month')})")
                ax_t.set_ylabel("Count")
                ax_t.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=7)
                plt.xticks(rotation=45, ha="right")
                plt.tight_layout()
                _report += _fig_to_md(fig_t) + "\n\n"
            if _temp_c.get("kw_df") is not None:
                _report += _temp_c["kw_df"].to_markdown(index=False) + "\n\n"
            if st.session_state.get("_rag_temporal_explanation"):
                _report += st.session_state._rag_temporal_explanation + "\n\n"

        # Ask Agent
        if st.session_state.get("_rag_llm_response"):
            _report += "## Ask Agent\n\n"
            _report += st.session_state._rag_llm_response + "\n\n"

        _report += f"\n---\nGenerated: {_now}\n"

        st.session_state._rag_report = _report

        # レポート生成と同時に分析セッションを自動保存
        try:
            _saved_path = _save_analysis_session(_selected)
            st.success(f"レポートを生成し、セッションを保存しました: {_saved_path}")
        except Exception as e:
            st.success("レポートを生成しました")
            st.warning(f"セッション保存エラー: {e}")

    if st.session_state.get("_rag_report"):
        _report_name = f"RAG_Explorer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        st.download_button("Download (.md)", data=st.session_state._rag_report.encode("utf-8"),
                          file_name=f"{_report_name}.md", mime="text/markdown", key="rag_dl_md")

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
                    _clear_auth_cookie(_get_cookie_manager())
                    for key in ["login_user", "service_id", "user_id"]:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.rerun()

        # メインビュー切り替え
        if st.session_state.allowed_rag_explorer:
            _view_options = ["Chat", "RAG Explorer"]
            _view_index = _view_options.index(st.session_state.get("main_view", "Chat")) if st.session_state.get("main_view", "Chat") in _view_options else 0
            st.session_state.main_view = st.radio("View:", _view_options, index=_view_index, horizontal=True, label_visibility="collapsed")
        else:
            st.session_state.main_view = "Chat"

        # エージェントを選択（JSON)
        if agent_id_selected := st.selectbox("Select Agent:", st.session_state.agent_list, index=st.session_state.agent_list_index):
            st.session_state.agent_id = agent_id_selected
            st.session_state.agent_file = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.agent_id), None)
            st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
            st.session_state.engine_name = st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
            st.session_state.imagegen_engine_name = st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")

        side_col1, side_col2 = st.columns(2)

        # 新しいセッションを発番（IDを指定して、新規にセッションリフレッシュ）
        if st.session_state.get("main_view") == "RAG Explorer":
            if side_col1.button("New Analysis", key="new_analysis_sidebar"):
                for _k in list(st.session_state.keys()):
                    if _k.startswith("_rag_"):
                        del st.session_state[_k]
                st.rerun()
        else:
            if side_col1.button("New Chat", key="new_chat"):
                st.session_state.main_view = "Chat"
                session_id = dms.set_new_session_id()
                session_name = "New Chat"
                situation = {}
                situation["TIME"] = ""
                situation["SITUATION"] = ""
                refresh_session_states()
                refresh_session(session_id, session_name, situation, True)

        # 会話履歴の更新
        if side_col2.button("Refresh List", key="refresh_session_list"):
            st.session_state.sidebar_message = ""
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

                    # 実行（バックグラウンド）
                    if st.button("評価実行", key="run_support_eval", disabled=bool(st.session_state._bg_task)):
                        if not _selected_engines:
                            st.warning("エンジンを選択してください")
                        elif not _questions:
                            st.warning("質問を入力してください")
                        else:
                            _eval_af = _agent_file
                            _eval_tgt = _selected_target
                            _eval_eng = list(_selected_engines)
                            _eval_qs = list(_questions)
                            def _run_eval():
                                _results, _summary, _excel = dmse.run_eval_for_ui(
                                    _eval_af, _eval_tgt, _eval_eng, _eval_qs)
                                st.session_state.eval_results_excel = _excel
                                st.session_state.eval_summary = _summary
                            _run_bg_task("eval", "サポートエージェント評価を実行中", _run_eval)
                            st.rerun()

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

        # セッション一覧はChat画面でのみ表示
        if st.session_state.get("main_view", "Chat") == "Chat":
            st.markdown("----")
            # セッション名の検索フィルタ
            _session_filter = st.text_input("Session Name:", value="", placeholder="検索（ワイルドカード * 対応）", label_visibility="collapsed")

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
                            # セッション名フィルタ（ワイルドカード * 対応）
                            if _session_filter:
                                import fnmatch
                                _pattern = _session_filter if "*" in _session_filter else f"*{_session_filter}*"
                                if not fnmatch.fnmatch(session_name_list.lower(), _pattern.lower()):
                                    continue
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
                                st.session_state.main_view = "Chat"
                                refresh_session_states()
                                refresh_session(session_id_list, session_name_list, situation)
#                            if st.button(f"Del:{session_id_list}", key=f"{session_key_list}_del_btn"):
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

        # RAG Explorer用: 保存済み分析セッション一覧
        elif st.session_state.get("main_view", "Chat") == "RAG Explorer":
            st.markdown("----")
            _analytics_base = "user/common/analytics/rag_explorer/"
            if os.path.exists(_analytics_base):
                _saved_folders = sorted(
                    [f for f in os.listdir(_analytics_base) if os.path.isdir(os.path.join(_analytics_base, f)) and f != ".gitkeep"],
                    reverse=True)
                for _sf in _saved_folders[:10]:
                    _meta_p = os.path.join(_analytics_base, _sf, "meta.json")
                    if os.path.exists(_meta_p):
                        _m = dmu.read_json_file(_meta_p)
                        _label = f"{_m.get('created_at', '')[:10]} {_m.get('collection', '')}"[:20]
                        if st.button(_label, key=f"rag_load_{_sf}"):
                            st.session_state._rag_load_folder = os.path.join(_analytics_base, _sf)
                            st.rerun()

    # メインエリアの画面切り替え
    if st.session_state.get("main_view") == "RAG Explorer":
        _rag_explorer()
        return

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
                        render_copy_button(v2["response"]["text"], f"copy_{k}_{k2}")

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
                                                feedback[fb_item]["memo"] = st.text_area("Memo:", key=f"feedback_{fb_item}_memo{k}_{k2}", value=feedback[fb_item]["memo"], height=100, label_visibility="collapsed")
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
                                    _detail_info = st.session_state.session.get_detail_info(k, k2)
                                    # 【】ブロックごとに分割してコピーボタンを付与
                                    import re as _re
                                    _blocks = _re.split(r'\n(?=【)', _detail_info)
                                    for _bi, _block in enumerate(_blocks):
                                        _block_stripped = _block.strip()
                                        if _block_stripped:
                                            render_copy_button(_block_stripped, f"detail_copy_{k}_{k2}_{_bi}")
                                            st.markdown(_block_stripped.replace("\n", "<br>"), unsafe_allow_html=True)

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
                                                _ak_refs = [dmu.parse_log_template(rd) for rd in v2["response"]["reference"]["knowledge_rag"] if "page_id" not in rd]
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
                                                            _cak_refs = [dmu.parse_log_template(rd) for rd in compare_agent_info["knowledge_rag"]["knowledge_ref"] if "page_id" not in rd]
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
        uploaded_files = st.file_uploader("Attached Files:", type=["txt", "vtt", "csv", "json", "pdf", "md", "docx", "xlsx", "pptx", "jpg", "jpeg", "png", "mp3"], accept_multiple_files=True)
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

        # Private Mode / Thinking Mode
        _mode_col1, _mode_col2 = st.columns(2)
        if _mode_col1.checkbox("Private Mode", value=st.session_state.private_mode):
            st.session_state.private_mode = True
        else:
            st.session_state.private_mode = False
        if _mode_col2.checkbox("Thinking Mode", value=st.session_state.thinking_mode):
            st.session_state.thinking_mode = True
        else:
            st.session_state.thinking_mode = False
        if st.session_state.thinking_mode:
            _thinking_options = ["Habit", "Web Search", "RAG Query", "Books"]
            st.session_state.thinking_targets = st.multiselect("Thinking Targets", _thinking_options, default=st.session_state.thinking_targets, label_visibility="collapsed")

        # BOOKから選択
        if st.session_state.allowed_book:
            if "BOOK" in st.session_state.agent_data:
                st.session_state.book_selected = st.multiselect("BOOK", [item["RAG_NAME"] for item in st.session_state.agent_data["BOOK"]])

    # ファイルダウンローダー
    if st.session_state.allowed_download_md:
        footer_col1, footer_col2, footer_col3 = st.columns(3)
        st.session_state.dl_type = footer_col1.radio("Download Mode:", ("Chats Only", "ALL"))
        dl_file_id = st.session_state.session.session_id +"_"+ st.session_state.session.session_name[:20]
        dl_data, dl_file_name, dl_mime = set_dl_file(download_data, st.session_state.dl_type, file_id=dl_file_id)
        footer_col2.download_button(label="Download(.md)", data=dl_data, file_name=dl_file_name, mime=dl_mime)
        pdf_data, pdf_file_name = set_dl_pdf(download_data, st.session_state.dl_type, file_id=dl_file_id)
        footer_col3.download_button(label="Download(.pdf)", data=pdf_data, file_name=pdf_file_name, mime="application/pdf")

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
            execution["THINKING_MODE"] = st.session_state.thinking_mode
            _targets = st.session_state.thinking_targets if st.session_state.thinking_mode else []
            execution["THINKING_TARGETS"] = {
                "habit": "Habit" in _targets,
                "web_search": "Web Search" in _targets,
                "rag_query_gene": "RAG Query" in _targets,
                "books": "Books" in _targets,
            }

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
