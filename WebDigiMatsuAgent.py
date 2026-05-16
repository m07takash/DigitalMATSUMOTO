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
import DigiM_GeneFeedback as dmgf
import DigiM_GeneUserDialog as dmgu
import DigiM_VAnalytics as dmva
import DigiM_DB_Export as dmdbe
import DigiM_AgentPersona as dap
import DigiM_Scheduler as dmsch

# バックグラウンドスケジューラ起動（setting.yaml の SCHEDULES に従う / "off" のみならスキップ）
try:
    dmsch.start_all()
except Exception:
    pass
import DigiM_SupportEval as dmse
import DigiM_UrlFetch as dmuf

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
if 'allowed_knowledge_explorer' not in st.session_state:
    st.session_state.allowed_knowledge_explorer = True
if 'allowed_user_memory_explorer' not in st.session_state:
    st.session_state.allowed_user_memory_explorer = False
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
if 'allowed_user_memory' not in st.session_state:
    st.session_state.allowed_user_memory = True
if 'allowed_support_eval' not in st.session_state:
    st.session_state.allowed_support_eval = True
if 'allowed_scheduler' not in st.session_state:
    st.session_state.allowed_scheduler = False
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

# ログアウト時にCookieを削除（KeyError回避のため期限切れで上書き）
def _clear_auth_cookie(cookie_manager):
    try:
        expires = datetime.now() - timedelta(days=1)
        cookie_manager.set(_COOKIE_NAME, "", expires_at=expires)
    except Exception:
        # 念のためのフォールバック（内部キャッシュに存在しない場合のKeyError等）
        try:
            cookie_manager.delete(_COOKIE_NAME)
        except Exception:
            pass

# ユーザーログイン（JSON / RDB は LOGIN_AUTH_METHOD で切替。詳細は DigiM_Auth.py 参照）
import DigiM_Auth as dma_auth


def load_user_master():
    return dma_auth.load_user_master()


# ログインユーザー情報の保持
def save_user_master(users: dict):
    """ユーザーマスタを保存（PWは平文/ハッシュどちらも許容）"""
    dma_auth.save_user_master(users)

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
    # Groupは文字列・リストの両方を受け付け、内部的にはリストに正規化
    raw_group = user_info.get("Group", "")
    if isinstance(raw_group, list):
        groups = [g for g in raw_group if g]
    elif raw_group:
        groups = [raw_group]
    else:
        groups = []

    st.session_state.login_user = {
        "USER_ID": user_id,
        "Name": user_info.get("Name", ""),
        "Group": groups,
        "Agent": user_info.get("Agent", ""),
        "Allowed": user_info.get("Allowed", {})
    }
    st.session_state.user_id = user_id
    st.session_state.session_user_id = st.session_state.user_id
    st.session_state.user_admin_flg = "Y" if "Admin" in groups else "N"
    if groups:
        st.session_state.group_cd = groups
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
    # 直前にLogoutした場合は、Cookie削除がブラウザ側に反映される前の再描画で
    # 自動再ログインしてしまわないよう、この1回はCookie復元をスキップする
    if st.session_state.pop("_just_logged_out", False):
        auth_token = None
    else:
        auth_token = cookie_manager.get(_COOKIE_NAME)
    if auth_token:
        cookie_user_id = _verify_auth_token(auth_token)
        if cookie_user_id:
            try:
                users = load_user_master()
            except Exception:
                # cookie復元時のロード失敗はログインフォームでもう一度ハンドリングする
                users = {}
            user_info = users.get(cookie_user_id)
            if user_info:
                set_login_user_to_session(cookie_user_id, user_info)
                refresh_session_states()
                return

    st.title(web_title)
    st.subheader("Login:")

    # ユーザーマスタの読み込み（LOGIN_AUTH_METHOD: JSON / RDB）
    try:
        users = load_user_master()
    except Exception as e:
        st.error(f"ユーザーマスタの読み込みに失敗しました（LOGIN_AUTH_METHOD={dma_auth.get_method()}）: {e}")
        st.stop()
    if not users:
        st.error(f"ユーザーマスタが空です（LOGIN_AUTH_METHOD={dma_auth.get_method()}）。マスタを設定してください。")
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
    st.session_state.allowed_knowledge_explorer = allowded_dict.get("Knowledge Explorer", True)
    st.session_state.allowed_user_memory_explorer = allowded_dict.get("User Memory Explorer", False)
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
    st.session_state.allowed_user_memory = allowded_dict.get("User Memory", True)
    st.session_state.allowed_scheduler = allowded_dict.get("Scheduler", False)

# バックグラウンドタスク実行ヘルパー
import threading as _threading

import json as _json
import DigiM_JobRegistry as djr
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

    _user_id = st.session_state.get("user_id")
    _job_id = djr.new_job_id()

    def _worker():
        import logging as _logging
        _log = _logging.getLogger("bg_task")
        try:
            _log.info(f"[BG_TASK] start: {task_type} - {message}")
            func(*args, **kwargs)
            _log.info(f"[BG_TASK] done: {task_type}")
            _write_bg_task_status_to(_task_file, {"status": "done", "message": message, "error": ""})
        except (SystemExit, KeyboardInterrupt):
            _log.warning(f"[BG_TASK] cancelled: {task_type}")
            _write_bg_task_status_to(_task_file, {"status": "done", "message": message, "error": "cancelled"})
        except Exception as e:
            _log.error(f"[BG_TASK] error: {task_type} - {e}", exc_info=True)
            _write_bg_task_status_to(_task_file, {"status": "done", "message": message, "error": str(e)})
        finally:
            djr.unregister_job(_job_id)

    _thread = _threading.Thread(target=_worker, daemon=True)
    djr.register_job(_job_id, _thread, task_type, message, user_id=_user_id)
    _thread.start()

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
        # default_agent がユーザのGroupで非表示の場合は先頭エージェントにフォールバック
        if st.session_state.display_name in st.session_state.agent_list:
            st.session_state.agent_list_index = st.session_state.agent_list.index(st.session_state.display_name)
        else:
            st.session_state.agent_list_index = 0
            if st.session_state.agent_list:
                st.session_state.display_name = st.session_state.agent_list[0]
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
    if 'selected_org' not in st.session_state:
        st.session_state.selected_org = None     # dict or None
    if 'selected_persona_ids' not in st.session_state:
        st.session_state.selected_persona_ids = []
    if 'include_query' not in st.session_state:
        st.session_state.include_query = False
    if 'max_personas' not in st.session_state:
        try:
            _yaml = dmu.read_yaml_file("setting.yaml")
            st.session_state.max_personas = int(_yaml.get("MAX_PERSONAS", 3))
        except Exception:
            st.session_state.max_personas = 3
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
    if 'file_uploader_key' not in st.session_state:
        # ファイルアップローダーのkeyに使うカウンター。実行完了時にインクリメントして
        # ウィジェットを「新しいインスタンス」として扱わせ、添付ファイルをクリアする
        st.session_state.file_uploader_key = 0
    if 'url_fetch_subpages' not in st.session_state:
        st.session_state.url_fetch_subpages = False
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
    # User Memory のセッション内一時状態をリセット
    # - 層チェックボックスは「マスタ保存値」に強制リセット（del だけだと Streamlit のウィジェット記憶で戻らないため）
    try:
        import DigiM_UserMemorySetting as _dmus_reset
        _master_layers = _dmus_reset.load_user_setting(st.session_state.user_id).get("layers", [])
    except Exception:
        _master_layers = []
    for _l in ("persona", "nowaday", "history"):
        st.session_state[f"um_layer_{_l}"] = (_l in _master_layers)
    st.session_state.user_memory_layers_now = list(_master_layers)
    st.session_state.display_name = st.session_state.default_agent
    st.session_state.agents = dma.get_display_agents(st.session_state.group_cd)
    st.session_state.agent_list = [a1["AGENT"] for a1 in st.session_state.agents]
    # default_agent がユーザのGroupで非表示の場合は先頭エージェントにフォールバック
    if st.session_state.display_name in st.session_state.agent_list:
        st.session_state.agent_list_index = st.session_state.agent_list.index(st.session_state.display_name)
    else:
        st.session_state.agent_list_index = 0
        if st.session_state.agent_list:
            st.session_state.display_name = st.session_state.agent_list[0]
    st.session_state.agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    st.session_state.compare_agent_id = st.session_state.agents[st.session_state.agent_list_index]["AGENT"]
    st.session_state.agent_file = st.session_state.agents[st.session_state.agent_list_index]["FILE"]
    st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
    st.session_state.selected_org = None
    st.session_state.selected_persona_ids = []
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
    st.session_state.url_fetch_subpages = False
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

### Knowledge Explorer画面 ###
def _knowledge_explorer():
    import fnmatch

    _ANALYTICS_BASE = "user/common/analytics/knowledge_explorer/"

    # Knowledge Explorer用の全session_stateキー
    _RAG_STATE_KEYS = [
        "_rag_searched", "_rag_cached_data", "_rag_cached_type", "_rag_prev_collection",
        "_rag_scatter_cache", "_rag_cluster_cache", "_rag_cluster_explanation", "_rag_cluster_names",
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
        # 再構成(Overall/Trend/Topic)で追加。既存キーはリネーム不可(pkl復元互換)
        "_rag_cluster_expl_history", "_rag_cluster_expl_sel",
        "_rag_trend", "_rag_trend_expl_history", "_rag_trend_expl_sel",
        "_rag_topic", "_rag_topic_expl_history", "_rag_topic_expl_sel",
    ]

    def _save_analysis_session(collection_name):
        """全Knowledge Explorer状態をフォルダに保存する"""
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

                _session_id = "KNOWLEDGE_EXPLORER_" + dms.set_new_session_id()
                # analyticsフォルダ内にセッションを作成
                _analytics_folder = st.session_state.get("_rag_analytics_folder", "")
                if not _analytics_folder:
                    _analytics_folder = os.path.join(_ANALYTICS_BASE, f"analytics{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                    st.session_state._rag_analytics_folder = _analytics_folder
                _session_base = os.path.join(_analytics_folder, _session_id)
                _tmp_session = dms.DigiMSession(_session_id, "Knowledge Explorer", base_path=_session_base)
                _tmp_session.save_status("LOCKED")
                _exec["_SESSION_BASE_PATH"] = _session_base

                with st.spinner("エージェント実行中..."):
                    try:
                        _response = ""
                        _output_ref = {}
                        for _, _, chunk, _, _oref in dme.DigiMatsuExecute(
                                st.session_state.web_service, st.session_state.web_user,
                                _session_id, "Knowledge Explorer", _agent_file, "LLM",
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
                                        _sid, "Knowledge Explorer", _cmp_file, model_type="LLM", sub_seq=1,
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
                                _run_bg_task("compare", f"比較分析を実行中(Knowledge Explorer)", _run_cmp)
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
                                _ak_title = f"KnowledgeExplorer_{_sid}"
                                # analytics個別フォルダに保存（なければ一時的に作成）
                                _ak_folder = st.session_state.get("_rag_analytics_folder", "")
                                if not _ak_folder:
                                    _ak_folder = os.path.join(_ANALYTICS_BASE, f"analytics{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                                    st.session_state._rag_analytics_folder = _ak_folder
                                os.makedirs(_ak_folder, exist_ok=True)
                                def _run_ak():
                                    _r = _dmva_ak.analytics_knowledge(_agent_file, _ref_ts, _ak_title, _ak_refs, _ak_folder, _ak_mode, _ak_dim)
                                    st.session_state[f"_{key_prefix}_ak_result"] = _r
                                _run_bg_task("knowledge", "知識活用性を分析中(Knowledge Explorer)", _run_ak)
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

    st.subheader("Knowledge Explorer")

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
        st.session_state._rag_cluster_names = None
        st.session_state._rag_sensitivity = None
        st.session_state._rag_sensitivity_explanation = None
        st.session_state._rag_temporal = None
        st.session_state._rag_temporal_explanation = None
        st.session_state._rag_llm_response = None
        st.session_state._rag_report = None
        st.session_state._rag_cluster_expl_history = None
        st.session_state._rag_cluster_expl_sel = None
        st.session_state._rag_trend = None
        st.session_state._rag_trend_expl_history = None
        st.session_state._rag_trend_expl_sel = None
        st.session_state._rag_topic = None
        st.session_state._rag_topic_expl_history = None
        st.session_state._rag_topic_expl_sel = None
        st.session_state._rag_df_display = None
        st.session_state._rag_filterable_cols = None
        st.session_state._rag_disp_sig = None

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
            _report = f"# Knowledge Explorer {_now}\n\n"
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
            _report_name = f"Knowledge_Explorer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            st.download_button("Download (.md)", data=st.session_state._rag_report.encode("utf-8"),
                              file_name=f"{_report_name}.md", mime="text/markdown", key="rag_pi_dl_md")

        return  # PageIndexはここで終了（以降のChromaDB用処理をスキップ）

    # ===== ChromaDB用画面（Overall / Trend / Topic / Ask Agent 構成） =====
    import DigiM_VAnalytics as dmva
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D as _L2D
    import base64 as _b64
    import io as _io
    import json as _json
    import re as _re

    _data_type = "ChromaDB"
    _MARKER_CHOICES = ["o", "s", "D", "^", "*", "P", "X", "v", "p", "h", "<", ">"]

    # コレクション(DATA_NAME) → RAG_NAME のマップ（エージェントのKNOWLEDGE/BOOK由来）
    _col_to_rag_name = {}
    for _k in _agent_data.get("KNOWLEDGE", []) + _agent_data.get("BOOK", []):
        _rag_name_v = _k.get("RAG_NAME", "")
        if not _rag_name_v:
            continue
        for _d in _k.get("DATA", []):
            _dn = _d.get("DATA_NAME", "")
            if _dn:
                _col_to_rag_name[_dn] = _rag_name_v

    # データ取得（キャッシュがあればそれを使う）
    if st.session_state.get("_rag_cached_data") is not None:
        df = st.session_state._rag_cached_data
        _data_type = st.session_state._rag_cached_type
        if "rag_name" not in df.columns and "_source" in df.columns:
            df = df.copy()
            df["rag_name"] = df["_source"].map(lambda s: _col_to_rag_name.get(s, s))
            st.session_state._rag_cached_data = df
    else:
        _all_raw_data = []
        for _sel in _selected_list:
            _col_data = dmc.get_rag_collection_data(_sel)
            _rn = _col_to_rag_name.get(_sel, _sel)
            for d in _col_data:
                d["_source"] = _sel
                d["rag_name"] = _rn
            _all_raw_data.extend(_col_data)
        if not _all_raw_data:
            st.warning("データが0件です")
            return
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

    # df_display / filterable をキャッシュ（毎回のlist→str変換コストを回避: 操作性改善）
    _disp_sig = (id(df), len(df), tuple(df.columns))
    if st.session_state.get("_rag_disp_sig") == _disp_sig and st.session_state.get("_rag_df_display") is not None:
        df_display = st.session_state._rag_df_display
        _filterable_cols = st.session_state._rag_filterable_cols
    else:
        _exclude_cols = [c for c in df.columns if "vector_data" in c]
        df_display = df.drop(columns=_exclude_cols, errors="ignore")
        for c in df_display.columns:
            if df_display[c].apply(lambda x: isinstance(x, list)).any():
                df_display[c] = df_display[c].apply(lambda x: ", ".join(str(i) for i in x) if isinstance(x, list) else x)
        _filterable_cols = [c for c in df_display.columns if df_display[c].dtype == "object" and df_display[c].nunique() < 100]
        st.session_state._rag_df_display = df_display
        st.session_state._rag_filterable_cols = _filterable_cols
        st.session_state._rag_disp_sig = _disp_sig

    _has_date = "create_date" in df_display.columns
    _has_vectors = "vector_data_value_text" in df.columns and _data_type in ("ChromaDB", "Mixed")
    _has_rag = "rag_name" in df_display.columns
    _priority_cols = ["id", "db", "rag_name", "title", "create_date", "category", "Cluster", "X1", "X2", "key_text", "value_text"]
    _cat_color_map = {}
    try:
        _cmj = dmu.read_json_file("category_map.json", mst_folder_path) or dmu.read_json_file("sample_category_map.json", mst_folder_path)
        _cat_color_map = (_cmj or {}).get("CategoryColor", {})
    except Exception:
        _cat_color_map = {}

    def _order_cols(_dfx):
        _ep = [c for c in _priority_cols if c in _dfx.columns]
        _rm = sorted([c for c in _dfx.columns if c not in _priority_cols])
        return _dfx[_ep + _rm]

    def _png(fig):
        """figをPNGバイト列にして閉じる（再描画コスト回避のため計算時に1度だけ生成）"""
        buf = _io.BytesIO()
        fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()

    def _b64img(_pb):
        return f"![chart](data:image/png;base64,{_b64.b64encode(_pb).decode()})"

    def _rag_list(_dfx):
        if "rag_name" in _dfx.columns:
            return sorted(_dfx["rag_name"].dropna().astype(str).unique().tolist())
        return []

    def _scatter_png(_dfx, _color_col, _marker_col, _size_mode, _title):
        _dot = None
        if _size_mode == "Newer=Larger" and "create_date" in _dfx.columns:
            _d = pd.to_datetime(_dfx["create_date"], errors="coerce")
            if _d.notna().any():
                _mn = _d.min().timestamp()
                _mx = _d.max().timestamp()
                _rg = _mx - _mn if _mx > _mn else 1
                _dot = _d.apply(lambda x: 10 + 190 * ((x.timestamp() - _mn) / _rg) if pd.notna(x) else 10).values
        fig, ax = plt.subplots(figsize=(9, 6))
        _mk = {}
        if _marker_col != "(none)" and _marker_col in _dfx.columns:
            _mv = sorted(_dfx[_marker_col].dropna().unique())
            _mk = {v: _MARKER_CHOICES[i % len(_MARKER_CHOICES)] for i, v in enumerate(_mv)}
        _cm = {}
        if _color_col != "(none)" and _color_col in _dfx.columns:
            _cs = sorted(_dfx[_color_col].dropna().unique())
            _dc = plt.cm.get_cmap("tab10", max(len(_cs), 1))
            for i, c in enumerate(_cs):
                _cm[c] = _cat_color_map.get(c) or _dc(i)
        if _cm and _mk:
            for c in _cm:
                for mv, ms in _mk.items():
                    _m = (_dfx[_color_col] == c) & (_dfx[_marker_col] == mv)
                    if not _m.any():
                        continue
                    _s = _dot[_m.values] if _dot is not None else None
                    ax.scatter(_dfx.loc[_m, "X1"], _dfx.loc[_m, "X2"], color=_cm[c], s=_s, alpha=0.7, marker=ms)
        elif _cm:
            for c, col in _cm.items():
                _m = _dfx[_color_col] == c
                _s = _dot[_m.values] if _dot is not None else None
                ax.scatter(_dfx.loc[_m, "X1"], _dfx.loc[_m, "X2"], color=col, s=_s, alpha=0.7)
        elif _mk:
            for mv, ms in _mk.items():
                _m = _dfx[_marker_col] == mv
                _s = _dot[_m.values] if _dot is not None else None
                ax.scatter(_dfx.loc[_m, "X1"], _dfx.loc[_m, "X2"], s=_s, alpha=0.7, marker=ms)
        else:
            ax.scatter(_dfx["X1"], _dfx["X2"], s=_dot, alpha=0.7)
        _lh = []
        if _cm:
            _lh.append(_L2D([0], [0], linestyle="", label=f"〔{_color_col}〕"))
            for c, col in _cm.items():
                _lh.append(_L2D([0], [0], marker="o", linestyle="", color=col, markersize=8, label=str(c)[:20]))
        if _mk:
            _lh.append(_L2D([0], [0], linestyle="", label=f"〔{_marker_col}〕"))
            for mv, ms in _mk.items():
                _lh.append(_L2D([0], [0], marker=ms, linestyle="", color="dimgray", markersize=8, label=str(mv)[:20]))
        if _lh:
            ax.legend(handles=_lh, loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
        ax.set_title(_title)
        ax.grid(True)
        return _png(fig)

    def _build_cluster_cmap(_labels):
        _l = sorted(_labels)
        _cm = plt.cm.get_cmap("tab10", max(len(_l), 1))
        return {cl: ("gray" if cl < 0 else _cm(i)) for i, cl in enumerate(_l)}

    def _cluster_png(_dfc, _names_map, _title, _cmap_fixed=None):
        """_cmap_fixed を渡すと（Total基準の）固定色でプロット（RAG NAME間で色を統一）"""
        fig, ax = plt.subplots(figsize=(8, 6))
        _present = sorted(_dfc["Cluster"].unique())
        _cc = _cmap_fixed if _cmap_fixed else _build_cluster_cmap(_present)

        def _lab(cl):
            if cl < 0:
                return "Noise"
            _nm = (_names_map or {}).get(str(int(cl))) or (_names_map or {}).get(int(cl))
            return f"C{int(cl)}: {str(_nm)[:10]}" if _nm else f"Cluster {int(cl)}"
        for cl in _present:
            _m = _dfc["Cluster"] == cl
            ax.scatter(_dfc.loc[_m, "X1"], _dfc.loc[_m, "X2"], color=_cc.get(cl, "gray"), alpha=0.7)
        _lh = [_L2D([0], [0], linestyle="", label="〔Cluster〕")]
        for cl in _present:
            _lh.append(_L2D([0], [0], marker="o", linestyle="", color=_cc.get(cl, "gray"), markersize=8, label=_lab(cl)))
        ax.legend(handles=_lh, loc="upper left", bbox_to_anchor=(1, 1), fontsize=8)
        ax.set_title(_title)
        ax.grid(True)
        return _png(fig)

    def _agent_engine_selectors(label, kp):
        _c1, _c2 = st.columns([1, 1])
        _al = st.session_state.agent_list
        _ai = 0
        _da = next((a for a in _al if "Analyst" in a), None)
        if _da:
            _ai = _al.index(_da)
        elif st.session_state.get("agent_id") in _al:
            _ai = _al.index(st.session_state.agent_id)
        _ag = _c1.selectbox(f"{label} Agent:", _al, index=_ai, key=f"{kp}_expl_agent")
        _af = next((a["FILE"] for a in st.session_state.agents if a["AGENT"] == _ag), None)
        _el = []
        if _af:
            try:
                _aj = dmu.read_json_file(_af, agent_folder_path)
                _el = [e for e in _aj.get("ENGINE", {}).get("LLM", {}).keys() if e != "DEFAULT"]
            except Exception:
                _el = []
        _eng = _c2.selectbox(f"{label} Engine:", _el, key=f"{kp}_expl_engine") if _el else None
        return _af, _ag, _eng

    def _explanation_block(state_base, template_name, fallback_agent, ctx_builder, label, kp, postprocess=None):
        """解説: エージェント+エンジン選択→複数回実行→ドロップダウンで1件表示。表示中テキストを返す。"""
        _hk = f"{state_base}_history"
        _sk = f"{state_base}_sel"
        st.markdown(f"**{label}の解説:**")
        _af, _ag, _eng = _agent_engine_selectors(label, kp)
        if st.button(f"Explain {label}", key=f"{kp}_expl_run"):
            _ctx = ctx_builder()
            if not _ctx:
                st.warning("解説対象のデータがありません。先に分析を実行してください。")
            else:
                _use_af = _af or fallback_agent
                with st.spinner(f"{label}を解説中..."):
                    try:
                        _agent = dma.DigiM_Agent(_use_af)
                        if _eng and _eng in _agent.agent.get("ENGINE", {}).get("LLM", {}):
                            _agent.agent["ENGINE"]["LLM"]["DEFAULT"] = _eng
                        try:
                            _tmpl = _agent.set_prompt_template(template_name)
                        except Exception:
                            _tmpl = ""
                        _resp = ""
                        for _, _ch, _ in _agent.generate_response("LLM", f"{_tmpl}\n{_ctx}", [], stream_mode=False):
                            if _ch:
                                _resp += _ch
                        _disp = _resp
                        if postprocess:
                            try:
                                _disp = postprocess(_resp)
                            except Exception:
                                _disp = _resp
                        _entry = {
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "agent": _ag, "engine": _eng or "(default)", "response": _disp,
                        }
                        _h = (st.session_state.get(_hk) or []) + [_entry]
                        st.session_state[_hk] = _h
                        st.session_state[_sk] = len(_h) - 1
                    except Exception as e:
                        st.error(f"{label}解説エラー: {e}")
        _h = st.session_state.get(_hk) or []
        if not _h:
            return ""
        _sel = st.session_state.get(_sk)
        if _sel is None or _sel >= len(_h) or _sel < 0:
            _sel = len(_h) - 1
        _sel = st.selectbox(
            f"{label} 解説履歴:", list(range(len(_h))), index=_sel,
            format_func=lambda i: f"[{i+1}/{len(_h)}] {_h[i]['timestamp']} / {_h[i]['agent']} / {_h[i]['engine']}",
            key=f"{kp}_expl_sel")
        st.session_state[_sk] = _sel
        st.markdown(_h[_sel]["response"])
        return _h[_sel]["response"]

    def _extra_filter_ui(_base_df, kp, with_period=True):
        """Overall範囲内での追加絞り込み: RAG NAME / Collection / 期間。(df_sub, 説明文)を返す"""
        _sub = _base_df.copy()
        _desc = []
        _c1, _c2, _c3 = st.columns([1, 1, 1])
        if "rag_name" in _sub.columns:
            _ro = sorted(_sub["rag_name"].dropna().astype(str).unique().tolist())
            _rs = _c1.multiselect("RAG NAME:", _ro, default=[], key=f"{kp}_f_rag")
            if _rs:
                _sub = _sub[_sub["rag_name"].astype(str).isin(_rs)]
                _desc.append(f"RAG={','.join(_rs)}")
        _cf = "db" if "db" in _sub.columns else ("_source" if "_source" in _sub.columns else None)
        if _cf:
            _co = sorted(_sub[_cf].dropna().astype(str).unique().tolist())
            _cs2 = _c2.multiselect("Collection:", _co, default=[], key=f"{kp}_f_col")
            if _cs2:
                _sub = _sub[_sub[_cf].astype(str).isin(_cs2)]
                _desc.append(f"Col={','.join(_cs2)}")
        if with_period and "create_date" in _sub.columns:
            _dp = pd.to_datetime(_sub["create_date"], errors="coerce").dropna()
            if not _dp.empty:
                _mn = _dp.min().date()
                _mx = _dp.max().date()
                _pv = _c3.date_input("Period From/To:", value=(_mn, _mx), min_value=_mn, max_value=_mx, key=f"{kp}_f_period")
                if isinstance(_pv, (list, tuple)) and len(_pv) == 2:
                    _pf, _pt = _pv
                    _dd = pd.to_datetime(_sub["create_date"], errors="coerce")
                    _sub = _sub[(_dd >= pd.Timestamp(_pf)) & (_dd <= pd.Timestamp(_pt) + pd.Timedelta(days=1))]
                    _desc.append(f"{_pf}〜{_pt}")
        return _sub, (" / ".join(_desc) if _desc else "絞り込みなし")

    # =========================================================
    # 1. Overall
    # =========================================================
    st.markdown("---")
    st.subheader("Overall")

    _fc1, _fc2, _fc3 = st.columns(3)
    _filter_column = _fc1.selectbox("Filter Column:", ["(none)"] + _filterable_cols, key="rag_filter_col")
    _filter_values = []
    if _filter_column != "(none)":
        _uv = sorted(df_display[_filter_column].dropna().unique().tolist())
        _filter_values = _fc2.multiselect("Filter Value:", _uv, key="rag_filter_val")
    _search_text = _fc3.text_input("Text Search:", value="", placeholder="ワイルドカード * 対応", key="rag_search_text")

    _exclude_private = False
    if "private" in df_display.columns:
        _exclude_private = st.checkbox("Exclude Private Data", value=True, key="rag_exclude_private")

    _date_from = None
    _date_to = None
    if _has_date:
        _dpall = pd.to_datetime(df_display["create_date"], errors="coerce").dropna()
        if not _dpall.empty:
            _mind = _dpall.min().date()
            _maxd = _dpall.max().date()
            _dc1, _dc2 = st.columns(2)
            _date_from = _dc1.date_input("Date From:", value=_mind, min_value=_mind, max_value=_maxd, key="rag_date_from")
            _date_to = _dc2.date_input("Date To:", value=_maxd, min_value=_mind, max_value=_maxd, key="rag_date_to")

    _s1, _s2, _s3, _s4 = st.columns([1, 1, 1, 1])
    _dim_method = _s1.radio("Dimension Reduction:", ["PCA", "t-SNE"], index=0, horizontal=True, key="rag_dim_method")
    _dim_params = {}
    if _dim_method == "t-SNE":
        _dim_params["perplexity"] = _s2.number_input("Perplexity:", value=30, step=1, key="rag_tsne_perp")
    _color_options = (["rag_name"] if "rag_name" in _filterable_cols else []) + ["(none)"] + [c for c in _filterable_cols if c != "rag_name"]
    if "rag_name" in _color_options:
        _cdef = _color_options.index("rag_name")
    elif "category" in _color_options:
        _cdef = _color_options.index("category")
    else:
        _cdef = _color_options.index("(none)")
    _color_col = _s3.selectbox("Color By:", _color_options, index=_cdef, key="rag_color_by")
    _marker_col = _s4.selectbox("Marker By:", ["(none)"] + [c for c in _filterable_cols if c != _color_col], index=0, key="rag_marker_by")
    _s5, _s6 = st.columns([1, 1])
    _size_mode = _s5.radio("Dot Size:", ["Uniform", "Newer=Larger"], index=0, horizontal=True, key="rag_dot_size")
    _do_search = _s6.button("Search & Plot", key="rag_do_search", type="primary")

    if _do_search:
        st.session_state._rag_searched = True
        st.session_state._rag_scatter_cache = None
    if not st.session_state.get("_rag_searched", False):
        st.caption(f"**{_data_type}** | Total: **{total_count}** 件 | 条件を指定して **Search & Plot** を押してください（指定なしで全件）")
        return

    df_filtered = df_display.copy()
    if _exclude_private and "private" in df_filtered.columns:
        df_filtered = df_filtered[df_filtered["private"] != True]
    if _filter_column != "(none)" and _filter_values:
        df_filtered = df_filtered[df_filtered[_filter_column].isin(_filter_values)]
    if _date_from is not None and _date_to is not None and _has_date:
        _dd = pd.to_datetime(df_filtered["create_date"], errors="coerce")
        df_filtered = df_filtered[(_dd >= pd.Timestamp(_date_from)) & (_dd <= pd.Timestamp(_date_to) + pd.Timedelta(days=1))]
    if _search_text:
        _pat = _search_text if "*" in _search_text else f"*{_search_text}*"
        df_filtered = df_filtered[df_filtered.apply(
            lambda r: any(fnmatch.fnmatch(str(v).lower(), _pat.lower()) for v in r), axis=1)]
    df_filtered = _order_cols(df_filtered)
    filtered_count = len(df_filtered)
    st.caption(f"**{_data_type}** | Total: **{total_count}** 件 | Filtered: **{filtered_count}** 件")

    if _do_search and _has_vectors and filtered_count >= 3:
        _dfs = df[df["id"].isin(df_filtered["id"])].copy()
        with st.spinner("次元削減＋散布図を生成中..."):
            try:
                _dfr, _dinfo = dmva.reduce_dimensions(_dfs, method=_dim_method, params=_dim_params)
                if _marker_col != "(none)" and _marker_col not in _dfr.columns and _marker_col in _dfs.columns:
                    _dfr[_marker_col] = _dfr["id"].map(_dfs.set_index("id")[_marker_col])
                _ttl = f"{_dim_method} - {_selected} ({filtered_count}件)\n{_dinfo}"
                _png_total = _scatter_png(_dfr, _color_col, _marker_col, _size_mode, _ttl)
                _png_rag = {}
                for _rn in _rag_list(_dfr):
                    _sr = _dfr[_dfr["rag_name"].astype(str) == _rn]
                    if len(_sr) >= 1:
                        _png_rag[_rn] = _scatter_png(_sr, _color_col, _marker_col, _size_mode, f"{_dim_method} - {_rn} ({len(_sr)}件)")
                st.session_state._rag_scatter_cache = {
                    "df_reduced": _dfr, "dim_info": _dinfo, "dim_method": _dim_method,
                    "color_col": _color_col, "marker_col": _marker_col, "size_mode": _size_mode,
                    "selected": _selected, "filtered_count": filtered_count,
                    "png_total": _png_total, "png_rag": _png_rag,
                }
            except Exception as e:
                st.warning(f"散布図の生成でエラー: {e}")
                st.session_state._rag_scatter_cache = None

    _scc = st.session_state.get("_rag_scatter_cache")
    _has_scatter = bool(_scc and _scc.get("selected") == _selected)

    if _has_scatter:
        st.markdown("**Scatter Plot (Total):**")
        st.image(_scc["png_total"])
        if _scc.get("png_rag"):
            st.markdown("**Scatter Plot (RAG NAMEごと):**")
            for _rn, _pb in _scc["png_rag"].items():
                st.image(_pb)
        _dfr = _scc["df_reduced"]
        _df_show = _order_cols(df_filtered.merge(_dfr.set_index("id")[["X1", "X2"]], left_on="id", right_index=True, how="left"))
    else:
        if _has_vectors and filtered_count < 3:
            st.info("散布図にはフィルタ後3件以上が必要です")
        elif not _has_vectors:
            st.info("ベクトルデータが無いため散布図はスキップしました")
        _df_show = df_filtered

    st.markdown("**Data 一覧（座標はTotal基準）:**")
    st.dataframe(_df_show, hide_index=True, use_container_width=True, height=380)
    st.download_button("CSV Download", data=_df_show.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"rag_{_selected}.csv", mime="text/csv", key="rag_csv_dl")

    # ---- Clustering（Totalで定義したクラスターをRAG NAMEへ適用） ----
    if _has_scatter:
        st.markdown("####  Clustering")
        _cl1, _cl2, _cl3 = st.columns([1, 1, 1])
        _cl_method = _cl1.selectbox("Method:", ["K-Means", "DBSCAN", "Hierarchical"], key="rag_cl_method")
        _cl_params = {}
        if _cl_method in ["K-Means", "Hierarchical"]:
            _cl_params["n_clusters"] = _cl2.number_input("Clusters:", value=5, min_value=2, max_value=20, step=1, key="rag_cl_k")
        elif _cl_method == "DBSCAN":
            _aeps = dmva.estimate_dbscan_eps(_scc["df_reduced"], k=5)
            _cl_params["min_samples"] = _cl3.number_input("min_samples:", value=5, min_value=2, step=1, key="rag_cl_min")
            _cl_params["eps"] = _cl2.number_input(f"eps (auto={_aeps}):", value=_aeps, min_value=0.1, step=0.5, format="%.2f", key="rag_cl_eps")

        if st.button("Run Clustering", key="rag_run_cluster"):
            _dfr = _scc["df_reduced"]
            _scope = _dfr[_dfr["id"].isin(df_filtered["id"])].copy()
            with st.spinner("クラスタリング中..."):
                try:
                    # Totalのみクラスタリング。RAG NAMEはTotalのクラスター割当をそのまま流用
                    _dft, _info = dmva.apply_clustering(_scope, method=_cl_method, params=_cl_params)
                    _cmap_fixed = _build_cluster_cmap(_dft["Cluster"].unique())
                    _png_t = _cluster_png(_dft, None, f"Clustering (Total): {_info}", _cmap_fixed)
                    _png_by = {}
                    _rag_dist = {}
                    if "rag_name" in _dft.columns:
                        for _rn in sorted(_dft["rag_name"].dropna().astype(str).unique()):
                            _sub = _dft[_dft["rag_name"].astype(str) == _rn]
                            if _sub.empty:
                                continue
                            _png_by[_rn] = _cluster_png(_sub, None, f"Clustering [RAG: {_rn}]（Total基準色）", _cmap_fixed)
                            _rag_dist[_rn] = {str(int(k)): int(v) for k, v in
                                              _sub["Cluster"].value_counts().sort_index().items()}
                    st.session_state._rag_cluster_cache = {
                        "results": True, "selected": _selected, "method": _cl_method, "info": _info,
                        "total_df": _dft[["id", "Cluster", "X1", "X2"]].copy(),
                        "total_summary": dmva.build_cluster_summary(_dft),
                        "labels": sorted([int(c) for c in _dft["Cluster"].unique()]),
                        "rag_dist": _rag_dist, "png_total": _png_t, "png_by_rag": _png_by,
                    }
                    st.session_state._rag_cluster_names = None
                except Exception as e:
                    st.warning(f"クラスタリングでエラー: {e}")
                    st.session_state._rag_cluster_cache = None

        _clc = st.session_state.get("_rag_cluster_cache")
        if _clc and _clc.get("selected") == _selected and _clc.get("results"):
            _names = st.session_state.get("_rag_cluster_names") or {}
            _tdf = _clc.get("total_df")
            st.caption(f"**Total: {_clc.get('info','')}**")
            _pt = _clc.get("png_total")
            if _names and _tdf is not None:
                _pt = _cluster_png(_tdf, _names, f"Clustering (Total): {_clc.get('info','')}",
                                   _build_cluster_cmap(_clc.get("labels") or _tdf["Cluster"].unique()))
            if _pt is not None:
                st.image(_pt)
            if _tdf is not None:
                _cd = _tdf.groupby("Cluster").size().reset_index(name="count").sort_values("Cluster")
                st.dataframe(_cd, hide_index=True, use_container_width=True)
                _dfm = df_filtered.merge(_tdf.set_index("id")[["X1", "X2", "Cluster"]], left_on="id", right_index=True, how="left")
                st.dataframe(_order_cols(_dfm), hide_index=True, use_container_width=True, height=280)
            _by = _clc.get("png_by_rag") or {}
            if _by:
                st.markdown("**RAG NAMEごと（Totalで定義したクラスター色を適用・横2列）:**")
                _items = list(_by.items())
                for _i in range(0, len(_items), 2):
                    _row = _items[_i:_i + 2]
                    _cols = st.columns(len(_row))
                    for _j, (_cv, _pb) in enumerate(_row):
                        _cols[_j].image(_pb, caption=f"RAG: {_cv}")

            def _cl_ctx():
                _cc = st.session_state.get("_rag_cluster_cache")
                if not _cc or not _cc.get("results"):
                    return ""
                _txt = ("RAGデータ「" + _selected + "」のクラスタリング結果です。\n"
                        f"[Total クラスタリング: {_cc.get('info','')}]\n{_cc.get('total_summary','')}\n")
                _rd = _cc.get("rag_dist") or {}
                if _rd:
                    _txt += "\n[RAG_NAMEごとに含まれるクラスター（クラスタ番号=件数）]\n"
                    for _rn, _dist in _rd.items():
                        _txt += f"  {_rn}: " + ", ".join(f"C{k}={v}" for k, v in _dist.items()) + "\n"
                _ids = [c for c in (_cc.get("labels") or []) if c >= 0]
                _txt += (f"\n対象クラスター番号: {_ids}\n"
                         "まずTotalで定義された各クラスターの特徴を解説し、"
                         "続いて各RAG_NAMEがどのクラスターを含むかを踏まえて解説してください。")
                return _txt

            def _cl_post(resp):
                _m = _re.search(r"```json\s*(\{.*?\})\s*```", resp, _re.DOTALL) or _re.search(r"(\{[^{}]*\})", resp, _re.DOTALL)
                if _m:
                    try:
                        _raw = _json.loads(_m.group(1))
                        st.session_state._rag_cluster_names = {str(k): str(v)[:10] for k, v in _raw.items()}
                    except Exception:
                        pass
                return _re.sub(r"```json\s*\{.*?\}\s*```\s*", "", resp, count=1, flags=_re.DOTALL).strip()

            _cl_disp = _explanation_block("_rag_cluster_expl", "Cluster Analyst KE", "agent_23DataAnalyst.json",
                                          _cl_ctx, "Clustering", "rag_cl", postprocess=_cl_post)
            st.session_state._rag_cluster_explanation = _cl_disp

    # =========================================================
    # 2. Trend
    # =========================================================
    st.markdown("---")
    st.subheader("Trend")
    if not _has_date:
        st.info("create_date が無いため Trend は利用できません")
    else:
        _df_trend, _trend_desc = _extra_filter_ui(df_filtered, "rag_trend")
        st.caption(f"対象: {_trend_desc} | {len(_df_trend)}件")
        _t1, _t2, _t3 = st.columns([1, 1, 1])
        _tr_period = _t1.selectbox("Period:", ["month", "quarter", "year"], index=0, key="rag_trend_period")
        _tr_topn = _t2.slider("Keywords/period:", min_value=3, max_value=20, value=7, key="rag_trend_topn")
        _tr_cat_opts = _filterable_cols or ["(none)"]
        _tr_cat_def = _tr_cat_opts.index("category") if "category" in _tr_cat_opts else 0
        _tr_cat_col = _t3.selectbox("Category Column (棒グラフ内訳のみ):", _tr_cat_opts, index=_tr_cat_def, key="rag_trend_cat")

        if st.button("Analyze Trend", key="rag_run_trend"):
            with st.spinner("Trend分析中..."):
                try:
                    _groups = [("Total", _df_trend)]
                    for _rn in _rag_list(_df_trend):
                        _groups.append((_rn, _df_trend[_df_trend["rag_name"].astype(str) == _rn]))
                    _gres = []
                    _no_period = {}
                    for _gn, _gd in _groups:
                        _cp, _kw, _sm = dmva.temporal_analysis(_gd, period=_tr_period,
                                                               top_n_keywords=_tr_topn, category_col=_tr_cat_col)
                        _per, _bck, _nop = dmva.temporal_keywords_by_category(
                            _gd, category_col=None, period=_tr_period, top_n=30)
                        if _nop:
                            for _k2, _v2 in _nop.items():
                                _no_period[f"{_gn}:{_k2}" if _gn != "Total" else _k2] = _v2
                        _wcmap = _bck.get("(all)", {})
                        # 棒グラフ(構成推移)
                        _bar_png = None
                        if _cp is not None and not _cp.empty:
                            _cols = [_cat_color_map.get(c) for c in _cp.columns]
                            figb, axb = plt.subplots(figsize=(11, 4))
                            _cp.plot(kind="bar", stacked=True, ax=axb,
                                     color=_cols if all(_cols) else None, alpha=0.85)
                            axb.set_title(f"{_tr_cat_col} 構成推移 ({_tr_period}) - {_gn}")
                            axb.set_ylabel("Count")
                            axb.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=7)
                            plt.xticks(rotation=45, ha="right")
                            plt.tight_layout()
                            _bar_png = _png(figb)
                        # ワードクラウド(Period降順)
                        _wc_list = []
                        for _p in sorted(_per, reverse=True):
                            _fr = _wcmap.get(_p)
                            if not _fr:
                                continue
                            _wf = dmva.make_wordcloud_figure(_fr, title=str(_p), width=320, height=220)
                            if _wf is not None:
                                _wc_list.append((str(_p), _png(_wf)))
                        # キーワード表(Period降順)
                        _kw_rows = []
                        if _kw is not None and not _kw.empty:
                            _kw_rows = _kw.sort_values("period", ascending=False).to_dict(orient="records")
                        _gres.append({"name": _gn, "bar_png": _bar_png, "wc": _wc_list,
                                      "kw_rows": _kw_rows, "summary": _sm or ""})
                    st.session_state._rag_trend = {
                        "groups": _gres, "no_period": _no_period, "period": _tr_period,
                        "category_col": _tr_cat_col, "desc": _trend_desc,
                    }
                except Exception as e:
                    st.warning(f"Trend分析でエラー: {e}")

        _tr = st.session_state.get("_rag_trend")
        if _tr and _tr.get("groups"):
            if _tr.get("no_period"):
                st.warning("期間情報(create_date)が無いRAGデータ: "
                           + ", ".join(f"{k}: {v}件" for k, v in _tr["no_period"].items())
                           + "（時間に関わる情報がありません）")
            for _g in _tr["groups"]:
                st.markdown(f"##### [{_g['name']}]")
                if _g.get("bar_png") is not None:
                    st.image(_g["bar_png"])
                if _g.get("kw_rows"):
                    st.dataframe(pd.DataFrame(_g["kw_rows"]), hide_index=True, use_container_width=True, height=180)
                _wc = _g.get("wc") or []
                if _wc:
                    for _i in range(0, len(_wc), 4):
                        _chunk = _wc[_i:_i + 4]
                        _cols = st.columns(4)
                        for _j, (_pl, _pb) in enumerate(_chunk):
                            _cols[_j].image(_pb, caption=_pl)

            def _tr_ctx():
                _t = st.session_state.get("_rag_trend")
                if not _t or not _t.get("groups"):
                    return ""
                _x = f"RAGデータ「{_selected}」の期間別キーワード集計です（Total と各RAG_NAME）。\n"
                for _g in _t["groups"]:
                    if _g.get("summary"):
                        _x += f"\n[{_g['name']}]\n{_g['summary']}\n"
                return _x

            _tr_disp = _explanation_block("_rag_trend_expl", "Trend Analyst", "agent_23DataAnalyst.json",
                                          _tr_ctx, "Trend", "rag_trend")
            st.session_state._rag_temporal_explanation = _tr_disp

    # =========================================================
    # 3. Topic
    # =========================================================
    st.markdown("---")
    st.subheader("Topic")
    if not _has_scatter:
        st.info("先に Overall で Search & Plot（散布図生成）を実行してください")
    else:
        _df_topic, _topic_desc = _extra_filter_ui(df_filtered, "rag_topic")
        st.caption(f"対象: {_topic_desc} | {len(_df_topic)}件")
        _topic_query = st.text_input("Query:", placeholder="キーワードや文章を入力して知識の反応を分析", key="rag_topic_query")
        _p1, _p2, _p3 = st.columns([1, 1, 1])
        _tp_period = _p1.selectbox("Period:", ["month", "quarter", "year"], index=0, key="rag_topic_period")
        _tp_topn = _p2.slider("Top N:", min_value=5, max_value=100, value=30, key="rag_topic_topn")
        _tp_bonus = _p3.number_input("Date Bonus (0=off):", value=0.0, min_value=0.0, max_value=1.0,
                                     step=0.1, format="%.1f", key="rag_topic_bonus")
        _tp_bf = _tp_bt = None
        if _tp_bonus > 0 and "create_date" in _df_topic.columns:
            _bdp = pd.to_datetime(_df_topic["create_date"], errors="coerce").dropna()
            if not _bdp.empty:
                _bmin = _bdp.min().date()
                _bmax = _bdp.max().date()
                _bv = st.date_input("Bonus Period From/To:", value=(_bmin, _bmax),
                                    min_value=_bmin, max_value=_bmax, key="rag_topic_bonus_period")
                if isinstance(_bv, (list, tuple)) and len(_bv) == 2:
                    _tp_bf, _tp_bt = _bv

        if _topic_query and st.button("Analyze Topic", key="rag_run_topic"):
            _dfr = _scc["df_reduced"]
            _dfsens = df[df["id"].isin(_df_topic["id"])].copy()
            _dfsens = _dfsens.merge(_dfr.set_index("id")[["X1", "X2"]], left_on="id", right_index=True, how="left")
            with st.spinner("類似度を計算中..."):
                try:
                    _rank, _ = dmva.sensitivity_analysis(
                        _dfsens, _topic_query, top_n=max(_tp_topn, len(_dfsens)),
                        date_from=_tp_bf, date_to=_tp_bt, date_bonus=_tp_bonus)
                    _grp = [("Total", _rank)]
                    for _rn in _rag_list(_rank):
                        _grp.append((_rn, _rank[_rank["rag_name"].astype(str) == _rn]))
                    _tgres = []
                    for _gn, _gr in _grp:
                        _gr_top = _gr.head(_tp_topn)
                        # 件数(棒)+スコア(折れ線: sum/avg/max) by Period
                        _pst = dmva.topic_period_stats(_gr, period=_tp_period)
                        _chart_png = None
                        if _pst is not None and not _pst.empty:
                            _xs = _pst["period"].astype(str).tolist()
                            figc, axc = plt.subplots(figsize=(11, 4))
                            axc.bar(_xs, _pst["count"], color="steelblue", alpha=0.75, label="count")
                            axc.set_ylabel("Count")
                            axc.set_xticks(range(len(_xs)))
                            axc.set_xticklabels(_xs, rotation=45, ha="right")
                            ax2 = axc.twinx()
                            ax2.plot(_xs, _pst["score_sum"], color="crimson", marker="o", label="score sum")
                            ax2.plot(_xs, _pst["score_avg"], color="darkorange", marker="s", label="score avg")
                            ax2.plot(_xs, _pst["score_max"], color="green", marker="^", label="score max")
                            ax2.set_ylabel("Score (小さいほど関連強)")
                            _l1, _b1 = axc.get_legend_handles_labels()
                            _l2, _b2 = ax2.get_legend_handles_labels()
                            axc.legend(_l1 + _l2, _b1 + _b2, loc="upper left", bbox_to_anchor=(1.07, 1), fontsize=8)
                            axc.set_title(f"件数 & 類似スコア ({_tp_period}) - {_gn}")
                            plt.tight_layout()
                            _chart_png = _png(figc)
                        # 散布図: その母集団(gray) + 選択(スコアで濃淡)
                        _pop = _dfr[_dfr["id"].isin(_gr["id"])] if _gn != "Total" else _dfr[_dfr["id"].isin(_rank["id"])]
                        _sc_png = None
                        if "X1" in _gr.columns:
                            figt, axt = plt.subplots(figsize=(9, 6))
                            axt.scatter(_pop["X1"], _pop["X2"], color="lightgray", alpha=0.3, s=12)
                            _smin = _gr_top["score"].min() if not _gr_top.empty else 0
                            _smax = _gr_top["score"].max() if not _gr_top.empty else 1
                            _srng = (_smax - _smin) if _smax > _smin else 1.0
                            for _, _rw in _gr_top.iterrows():
                                if pd.isna(_rw.get("X1")) or pd.isna(_rw.get("X2")):
                                    continue
                                _a = float(0.95 - 0.55 * ((_rw["score"] - _smin) / _srng))
                                _mk = "D" if _rw.get("bonus_applied") else "o"
                                axt.scatter([_rw["X1"]], [_rw["X2"]], color="#1565C0", alpha=_a, s=70,
                                            edgecolors="black", linewidths=0.5, marker=_mk)
                            axt.set_title(f"Topic: \"{_topic_query}\" [{_gn}] (Top {len(_gr_top)})")
                            axt.grid(True)
                            _sc_png = _png(figt)
                        _cols_t = [c for c in ["score", "cos_distance", "bonus_applied", "id", "rag_name",
                                               "title", "create_date", "X1", "X2", "value_text"] if c in _gr_top.columns]
                        _tgres.append({"name": _gn, "chart_png": _chart_png, "scatter_png": _sc_png,
                                       "rows": _gr_top[_cols_t].to_dict(orient="records"),
                                       "cols": _cols_t, "n": len(_gr)})
                    st.session_state._rag_topic = {
                        "groups": _tgres, "query": _topic_query, "selected": _selected,
                        "desc": _topic_desc, "period": _tp_period,
                    }
                except Exception as e:
                    st.warning(f"Topic分析でエラー: {e}")

        _tp = st.session_state.get("_rag_topic")
        if _tp and _tp.get("selected") == _selected and _tp.get("groups"):
            st.caption(f"Query: **{_tp['query']}** | {_tp.get('desc','')}")
            for _g in _tp["groups"]:
                st.markdown(f"##### [{_g['name']}] （{_g['n']}件中 上位{len(_g['rows'])}）")
                if _g.get("chart_png") is not None:
                    st.image(_g["chart_png"])
                if _g.get("scatter_png") is not None:
                    st.image(_g["scatter_png"])
                if _g.get("rows"):
                    st.dataframe(pd.DataFrame(_g["rows"]), hide_index=True, use_container_width=True, height=240)

            def _tp_ctx():
                _t = st.session_state.get("_rag_topic")
                if not _t or not _t.get("groups"):
                    return ""
                _x = (f"クエリ「{_t['query']}」に対する知識の反応(類似度)分析です。\n"
                      "Total全体と各RAG_NAMEそれぞれについて、この入力に反応しそうな知識の特徴・傾向を"
                      "分かりやすく語ってください。\n")
                for _g in _t["groups"]:
                    _x += f"\n\n[{_g['name']}] 上位{len(_g['rows'])}件:\n"
                    for _r in _g["rows"][:12]:
                        _x += f"  score={_r.get('score','')} {_r.get('title','')}: {str(_r.get('value_text',''))[:80]}\n"
                return _x

            _tp_disp = _explanation_block("_rag_topic_expl", "Sensitivity Analyst", "agent_23DataAnalyst.json",
                                          _tp_ctx, "Topic", "rag_topic")
            st.session_state._rag_sensitivity_explanation = _tp_disp

    # =========================================================
    # 4. Ask Agent
    # =========================================================
    st.markdown("---")
    _summary_lines = [f"以下のRAGデータと分析結果を踏まえて質問に回答してください。\n\nRAGデータ: {_selected} (フィルタ後: {filtered_count}件 / 全体: {total_count}件)"]
    _df_for_llm = df_filtered.drop(columns=[c for c in df_filtered.columns if "vector" in c], errors="ignore")
    for col in _filterable_cols[:5]:
        if col in _df_for_llm.columns:
            _vc = _df_for_llm[col].value_counts().head(10).to_dict()
            if _vc:
                _summary_lines.append(f"\n[{col}の分布]\n" + "\n".join(f"  {k}: {v}件" for k, v in _vc.items()))
    _sample_n = min(30, len(_df_for_llm))
    _summary_lines.append(f"\n[データ(先頭{_sample_n}件)]\n{_df_for_llm.head(_sample_n).to_csv(index=False)}")
    if st.session_state.get("_rag_cluster_explanation"):
        _summary_lines.append(f"\n[Clustering解説]\n{st.session_state._rag_cluster_explanation[:600]}")
    if st.session_state.get("_rag_temporal_explanation"):
        _summary_lines.append(f"\n[Trend解説]\n{st.session_state._rag_temporal_explanation[:600]}")
    if st.session_state.get("_rag_sensitivity_explanation"):
        _summary_lines.append(f"\n[Topic解説]\n{st.session_state._rag_sensitivity_explanation[:600]}")
    _chromadb_context = "\n".join(_summary_lines)
    _ask_agent_ui(_chromadb_context, key_prefix="rag")
    _chromadb_response = _show_ask_result(key_prefix="rag")
    if _chromadb_response:
        st.session_state._rag_llm_response = _chromadb_response

    # =========================================================
    # Export Report
    # =========================================================
    st.markdown("---")
    st.subheader("Export Report")
    if st.button("Generate Report", key="rag_gen_report"):
        _now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _report = f"# Knowledge Explorer {_now}\n\n"
        _report += f"**対象データ:** {_selected}\n\n"
        _report += f"**データ件数:** フィルタ後 {filtered_count}件 / 全体 {total_count}件\n\n"

        _scc = st.session_state.get("_rag_scatter_cache")
        if _scc and _scc.get("selected") == _selected:
            _report += "## Overall - Scatter Plot\n\n### Total\n\n" + _b64img(_scc["png_total"]) + "\n\n"
            for _rn, _pb in (_scc.get("png_rag") or {}).items():
                _report += f"### RAG: {_rn}\n\n" + _b64img(_pb) + "\n\n"
        _clc = st.session_state.get("_rag_cluster_cache")
        if _clc and _clc.get("selected") == _selected and _clc.get("results"):
            _report += "## Overall - Clustering\n\n"
            if _clc.get("png_total") is not None:
                _report += "### Total\n\n" + _b64img(_clc["png_total"]) + "\n\n"
            for _cv, _pb in (_clc.get("png_by_rag") or {}).items():
                _report += f"### RAG: {_cv}\n\n" + _b64img(_pb) + "\n\n"
        _ch = st.session_state.get("_rag_cluster_expl_history") or []
        _cs = st.session_state.get("_rag_cluster_expl_sel")
        if _ch:
            _ci = _cs if (_cs is not None and 0 <= _cs < len(_ch)) else len(_ch) - 1
            _report += f"### Clustering解説 ({_ch[_ci]['timestamp']} / {_ch[_ci]['agent']})\n\n{_ch[_ci]['response']}\n\n"
        _trr = st.session_state.get("_rag_trend")
        if _trr and _trr.get("groups"):
            _report += "## Trend\n\n"
            if _trr.get("no_period"):
                _report += "**期間情報なし:** " + ", ".join(f"{k}:{v}件" for k, v in _trr["no_period"].items()) + "\n\n"
            for _g in _trr["groups"]:
                _report += f"### {_g['name']}\n\n"
                if _g.get("bar_png") is not None:
                    _report += _b64img(_g["bar_png"]) + "\n\n"
                for _pl, _pb in (_g.get("wc") or []):
                    _report += f"*{_pl}* " + _b64img(_pb) + "\n\n"
        _th = st.session_state.get("_rag_trend_expl_history") or []
        _ts = st.session_state.get("_rag_trend_expl_sel")
        if _th:
            _ti = _ts if (_ts is not None and 0 <= _ts < len(_th)) else len(_th) - 1
            _report += f"### Trend解説 ({_th[_ti]['timestamp']} / {_th[_ti]['agent']})\n\n{_th[_ti]['response']}\n\n"
        _tpr2 = st.session_state.get("_rag_topic")
        if _tpr2 and _tpr2.get("selected") == _selected and _tpr2.get("groups"):
            _report += f"## Topic\n\nQuery: {_tpr2.get('query','')}\n\n"
            for _g in _tpr2["groups"]:
                _report += f"### {_g['name']}\n\n"
                if _g.get("chart_png") is not None:
                    _report += _b64img(_g["chart_png"]) + "\n\n"
                if _g.get("scatter_png") is not None:
                    _report += _b64img(_g["scatter_png"]) + "\n\n"
        _ph = st.session_state.get("_rag_topic_expl_history") or []
        _ps = st.session_state.get("_rag_topic_expl_sel")
        if _ph:
            _pi = _ps if (_ps is not None and 0 <= _ps < len(_ph)) else len(_ph) - 1
            _report += f"### Topic解説 ({_ph[_pi]['timestamp']} / {_ph[_pi]['agent']})\n\n{_ph[_pi]['response']}\n\n"
        if st.session_state.get("_rag_llm_response"):
            _report += "## Ask Agent\n\n" + st.session_state._rag_llm_response + "\n\n"
        _report += f"\n---\nGenerated: {_now}\n"
        st.session_state._rag_report = _report
        try:
            _saved_path = _save_analysis_session(_selected)
            st.success(f"レポートを生成し、セッションを保存しました: {_saved_path}")
        except Exception as e:
            st.success("レポートを生成しました")
            st.warning(f"セッション保存エラー: {e}")

    if st.session_state.get("_rag_report"):
        _report_name = f"Knowledge_Explorer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        st.download_button("Download (.md)", data=st.session_state._rag_report.encode("utf-8"),
                          file_name=f"{_report_name}.md", mime="text/markdown", key="rag_dl_md")

### Scheduler画面 ###
def _scheduler_view():
    """汎用スケジュール管理画面。ジョブ一覧 + 追加/編集 + Run Now + Reload。"""
    import DigiM_Scheduler as _dmsch
    import DigiM_ScheduledJobs as _dmsj

    st.subheader("Scheduler")
    st.caption("バックグラウンドジョブの登録・編集・即時実行。設定変更後は **Reload Schedulers** で反映してください。")

    # 制御行
    _ctl1, _ctl2, _ctl3 = st.columns([1, 1, 4])
    if _ctl1.button("Reload Schedulers", key="sch_reload"):
        try:
            _r = _dmsch.reload()
            st.session_state.sidebar_message = f"Reloaded. started={_r.get('started')}"
        except Exception as e:
            st.session_state.sidebar_message = f"Reload failed: {e}"
        st.rerun()
    if _ctl2.button("Add New Job", key="sch_add_new"):
        st.session_state._sch_edit_id = "__new__"
        st.rerun()

    _status = _dmsch.get_status()
    _ctl3.caption(f"scheduler running: **{_status.get('running')}** / active job_ids: {_status.get('active_job_ids')}")

    st.markdown("---")

    # 一覧
    _jobs = _dmsj.load_all()
    if not _jobs:
        st.info("ジョブはまだ登録されていません。**Add New Job** から追加してください。")
    for _j in _jobs:
        _jid = _j.get("job_id")
        _label = f"**{_j.get('name') or '(no name)'}** — `{_j.get('kind')}` / cron=`{_j.get('cron')}` / enabled={_j.get('enabled')}"
        with st.expander(_label, expanded=False):
            _col1, _col2 = st.columns(2)
            _col1.write(f"job_id: `{_jid}`")
            _col1.write(f"owner: `{_j.get('owner_user_id')}`")
            _col1.write(f"last_run: `{_j.get('last_run') or '-'}`")
            _status_val = _j.get("last_status") or "-"
            _col2.write(f"last_status: **{_status_val}**")
            if _j.get("last_session_id"):
                _col2.write(f"last_session_id: `{_j.get('last_session_id')}`")
            if _j.get("kind") == "agent_run":
                _p = _j.get("params") or {}
                _col2.write(f"agent: `{_p.get('agent_file')}` / engine=`{_p.get('engine') or '(default)'}`")
                if _p.get("user_input"):
                    st.text_area("user_input", value=_p.get("user_input"), height=80, disabled=True, key=f"sch_view_ui_{_jid}")

            if _j.get("last_status") == "error" and _j.get("last_error"):
                with st.expander("Error log", expanded=False):
                    st.code(_j.get("last_error"))

            _ba, _bb, _bc, _bd = st.columns(4)
            if _ba.button("Edit", key=f"sch_edit_{_jid}"):
                st.session_state._sch_edit_id = _jid
                st.rerun()
            if _bb.button("Run Now", key=f"sch_run_{_jid}"):
                _res = _dmsch.run_now(_jid)
                if _res.get("ok"):
                    st.session_state.sidebar_message = f"Run completed: {_jid}"
                else:
                    st.session_state.sidebar_message = f"Run failed: {_res.get('error')}"
                st.rerun()
            if _bc.button(("Disable" if _j.get("enabled") else "Enable"), key=f"sch_toggle_{_jid}"):
                _new = dict(_j); _new["enabled"] = not _j.get("enabled")
                _dmsj.upsert(_new)
                st.session_state.sidebar_message = "Updated (Reloadで反映)"
                st.rerun()
            if _bd.button("Delete", key=f"sch_del_{_jid}"):
                _dmsj.delete(_jid)
                st.session_state.sidebar_message = f"Deleted: {_jid}"
                st.rerun()

    # 編集フォーム
    _edit_id = st.session_state.get("_sch_edit_id")
    if _edit_id:
        st.markdown("---")
        _is_new = (_edit_id == "__new__")
        _existing = {} if _is_new else (_dmsj.get(_edit_id) or {})
        st.markdown("### " + ("Add New Job" if _is_new else f"Edit Job: `{_edit_id}`"))

        _name = st.text_input("Name", value=_existing.get("name", ""), key="sch_f_name")
        _kinds = ["rag_update", "user_memory_nowaday", "agent_run"]
        _kind_idx = _kinds.index(_existing.get("kind", "rag_update")) if _existing.get("kind") in _kinds else 0
        _kind = st.selectbox("Kind", _kinds, index=_kind_idx, key="sch_f_kind")
        _cron = st.text_input(
            "Cron",
            value=_existing.get("cron", "off"),
            help='"off" / "daily"(03:00) / "weekly"(月03:00) / "monthly"(1日03:00) / 5フィールドcron(例: "0 3 1 * *")',
            key="sch_f_cron",
        )
        _enabled = st.checkbox("Enabled", value=bool(_existing.get("enabled", False)), key="sch_f_enabled")

        # agent_run の追加パラメータ
        _params = dict(_existing.get("params") or {})
        if _kind == "agent_run":
            st.markdown("**Agent Run Params**")
            _agent_files = [a["FILE"] for a in (st.session_state.get("agents") or [])]
            _cur_agent = _params.get("agent_file") or (_agent_files[0] if _agent_files else "")
            if _agent_files:
                _idx = _agent_files.index(_cur_agent) if _cur_agent in _agent_files else 0
                _agent_file = st.selectbox("Agent File", _agent_files, index=_idx, key="sch_f_agent")
            else:
                _agent_file = st.text_input("Agent File", value=_cur_agent, key="sch_f_agent_txt")
            _engine = st.text_input("Engine (LLM key in agent JSON, empty=default)", value=_params.get("engine", ""), key="sch_f_engine")
            _user_input = st.text_area("Prompt (user_input)", value=_params.get("user_input", ""), height=120, key="sch_f_userinput")

            _exec = dict(_params.get("execution") or {})
            st.markdown("**Execution flags**")
            _ec1, _ec2, _ec3 = st.columns(3)
            _exec["MEMORY_USE"]      = _ec1.checkbox("MEMORY_USE", value=bool(_exec.get("MEMORY_USE", True)), key="sch_f_e_memuse")
            _exec["MEMORY_SAVE"]     = _ec1.checkbox("MEMORY_SAVE", value=bool(_exec.get("MEMORY_SAVE", True)), key="sch_f_e_memsave")
            _exec["RAG_QUERY_GENE"]  = _ec1.checkbox("RAG_QUERY_GENE", value=bool(_exec.get("RAG_QUERY_GENE", True)), key="sch_f_e_rag")
            _exec["WEB_SEARCH"]      = _ec2.checkbox("WEB_SEARCH", value=bool(_exec.get("WEB_SEARCH", False)), key="sch_f_e_web")
            _exec["META_SEARCH"]     = _ec2.checkbox("META_SEARCH", value=bool(_exec.get("META_SEARCH", True)), key="sch_f_e_meta")
            _exec["THINKING_MODE"]   = _ec2.checkbox("THINKING_MODE", value=bool(_exec.get("THINKING_MODE", False)), key="sch_f_e_think")
            _exec["MAGIC_WORD_USE"]  = _ec3.checkbox("MAGIC_WORD_USE", value=bool(_exec.get("MAGIC_WORD_USE", False)), key="sch_f_e_magic")
            _exec["PRIVATE_MODE"]    = _ec3.checkbox("PRIVATE_MODE", value=bool(_exec.get("PRIVATE_MODE", False)), key="sch_f_e_priv")
            _exec["SAVE_DIGEST"]     = _ec3.checkbox("SAVE_DIGEST", value=bool(_exec.get("SAVE_DIGEST", True)), key="sch_f_e_dig")

            _params = {
                "agent_file": _agent_file,
                "engine": _engine,
                "user_input": _user_input,
                "execution": _exec,
            }
        else:
            _params = {}

        _bs, _bc = st.columns(2)
        if _bs.button("Save", key="sch_f_save"):
            _doc = {
                "job_id": "" if _is_new else _edit_id,
                "name": _name,
                "kind": _kind,
                "cron": _cron,
                "enabled": _enabled,
                "owner_user_id": st.session_state.get("web_user", {}).get("USER_ID", ""),
                "params": _params,
            }
            try:
                _saved = _dmsj.upsert(_doc)
                st.session_state._sch_edit_id = None
                st.session_state.sidebar_message = f"Saved: {_saved.get('job_id')} (Reloadで反映)"
            except Exception as e:
                st.session_state.sidebar_message = f"Save failed: {e}"
            st.rerun()
        if _bc.button("Cancel", key="sch_f_cancel"):
            st.session_state._sch_edit_id = None
            st.rerun()


### User Memory Explorer画面 ###
def _user_memory_explorer():
    """ユーザー理解のための分析。タブ②深掘り(個人) / タブ①横断(集団)。各タブにメモリ接地対話。"""
    import DigiM_UserMemoryExplorer as ux
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from math import pi
    import pandas as pd

    _UME_BASE = "user/common/analytics/user_memory_explorer/"
    st.subheader("User Memory Explorer")

    _all_users = ux.list_users("")
    if not _all_users:
        st.info("ユーザーメモリのレコードがまだありません。チャットを重ねるか Update User Memory を実行してください。")
        return

    def _radar(labels, values, title, vmax=1.0):
        n = len(labels)
        ang = [i / float(n) * 2 * pi for i in range(n)]
        ang += ang[:1]
        v = list(values) + list(values)[:1]
        fig = plt.figure(figsize=(4.0, 4.0))
        ax = plt.subplot(111, polar=True)
        ax.set_theta_offset(pi / 2)
        ax.set_theta_direction(-1)
        plt.xticks(ang[:-1], labels, fontfamily="IPAexGothic", fontsize=9)
        ax.set_ylim(0, vmax)
        ax.plot(ang, v, linewidth=1.5, color="#1f77b4")
        ax.fill(ang, v, alpha=0.25, color="#1f77b4")
        plt.title(title, fontfamily="IPAexGothic", fontsize=11)
        return fig

    def _radar3(labels, series, title, vmax=1.0):
        """series=[(name,color,values), ...] を1つのレーダーに重ねる（max/mean/min用）。"""
        n = len(labels)
        ang = [i / float(n) * 2 * pi for i in range(n)]
        ang += ang[:1]
        fig = plt.figure(figsize=(4.2, 4.2))
        ax = plt.subplot(111, polar=True)
        ax.set_theta_offset(pi / 2)
        ax.set_theta_direction(-1)
        plt.xticks(ang[:-1], labels, fontfamily="IPAexGothic", fontsize=9)
        ax.set_ylim(0, vmax)
        for _nm, _cl, _vs in series:
            _vv = list(_vs) + list(_vs)[:1]
            ax.plot(ang, _vv, linewidth=1.4, color=_cl, label=_nm)
            ax.fill(ang, _vv, alpha=0.12, color=_cl)
        ax.legend(loc="upper right", bbox_to_anchor=(1.15, 1.12), fontsize=8,
                  prop={"family": "IPAexGothic"})
        plt.title(title, fontfamily="IPAexGothic", fontsize=11)
        return fig

    def _um_ask(context_text, key_prefix):
        """メモリ接地エージェントとの対話。専用セッションに保存。"""
        st.markdown("---")
        st.subheader("メモリ接地エージェントと対話")
        if not context_text:
            st.caption("対象データが空のため対話できません。")
            return
        with st.expander("接地コンテキスト（エージェントに渡す文脈）"):
            st.text(context_text[:4000])

        _agent_list = st.session_state.agent_list
        _aidx = _agent_list.index(st.session_state.agent_id) if st.session_state.get("agent_id") in _agent_list else 0
        _agent = st.selectbox("Agent:", _agent_list, index=_aidx, key=f"{key_prefix}_agent")
        _q = st.text_area("質問:", placeholder="例: この人/この層の関心の変遷と背景を説明して",
                          height=90, key=f"{key_prefix}_q")
        if _q and st.button("Ask", key=f"{key_prefix}_ask"):
            _af = next((a["FILE"] for a in st.session_state.agents if a["AGENT"] == _agent), None)
            if _af:
                _ui = f"{context_text}\n\n【質問】\n{_q}"
                _exec = {
                    "MEMORY_USE": False, "MEMORY_SAVE": True, "SAVE_DIGEST": False,
                    "CONTENTS_SAVE": False, "STREAM_MODE": False, "MAGIC_WORD_USE": False,
                    "META_SEARCH": False, "RAG_QUERY_GENE": False,
                    "WEB_SEARCH": False, "PRIVATE_MODE": True, "THINKING_MODE": False,
                    "USER_MEMORY_LAYERS": [],
                }
                _sid = "UME_" + dms.set_new_session_id()
                _folder = os.path.join(_UME_BASE, f"analytics{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                _sbase = os.path.join(_folder, _sid)
                _tmp = dms.DigiMSession(_sid, "User Memory Explorer", base_path=_sbase)
                _tmp.save_status("LOCKED")
                _exec["_SESSION_BASE_PATH"] = _sbase
                with st.spinner("エージェント実行中..."):
                    try:
                        _resp = ""
                        for _, _, chunk, _, _oref in dme.DigiMatsuExecute(
                                st.session_state.web_service, st.session_state.web_user,
                                _sid, "User Memory Explorer", _af, "LLM",
                                1, _ui, [], {}, {}, [], "No Template", _exec):
                            if chunk and not str(chunk).startswith("[STATUS]"):
                                _resp += chunk
                        st.session_state.setdefault(f"_{key_prefix}_hist", [])
                        st.session_state[f"_{key_prefix}_hist"].append({
                            "agent": _agent, "query": _q, "response": _resp,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                    except Exception as e:
                        st.error(f"実行エラー: {type(e).__name__}: {e}")
                    finally:
                        _tmp.save_status("UNLOCKED")
        for _h in st.session_state.get(f"_{key_prefix}_hist", []):
            with st.chat_message("user"):
                st.markdown(f"**[{_h['timestamp']}] {_h['agent']}**")
                st.markdown(_h["query"])
            with st.chat_message("assistant"):
                st.markdown(_h["response"])

    def _um_twin_chat(user_id, key_prefix="ume_deep"):
        """選択ユーザーのメモリだけを持つAI（=そのユーザーのデジタルツイン）と対話。

        - サイドバーで選択中のエージェントに搭載されたLLMエンジンのみ選択
        - サイドバーのエージェントのペルソナ/知識/システムプロンプトは一切使わない
        - Persona/Nowaday/History を「ユーザーメモリのコンテキスト注入方式」で合成
          （Historyは質問文のキーワードでスコアリングして選定）
        - LLM単体で応答。AIの名前は選択ユーザー名
        """
        import DigiM_UserMemory as _dmum_t
        import DigiM_UserMemoryBuilder as _dmumb_t
        import DigiM_FoundationModel as _dmfm_t

        st.markdown("---")
        st.subheader("Chat with this User Twin")
        st.caption(
            f"「{user_id}」のユーザーメモリ(Persona/Nowaday/History)だけを文脈に持つLLMと対話します。"
            "サイドバーのエージェント設定（人格・知識・システムプロンプト）は使用しません。"
        )

        # 対象ユーザーの実 service_id を解決
        _bd = ux.load_bundle(user_id, "")
        _svc = ""
        for _r in [_bd.get("persona") or {}] + (_bd.get("nowaday") or []) + (_bd.get("history") or []):
            if _r.get("service_id"):
                _svc = _r["service_id"]
                break

        # サイドバー選択中エージェントのLLMエンジン一覧（エンジンのみ選択）
        try:
            _adata = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
        except Exception:
            _adata = st.session_state.get("agent_data", {}) or {}
        _eng_list = dma.get_engine_list(_adata, model_type="LLM")
        if not _eng_list:
            st.caption("選択中エージェントにLLMエンジンが定義されていません。")
            return
        _eng_default = _adata.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", _eng_list[0])
        _eidx = _eng_list.index(_eng_default) if _eng_default in _eng_list else 0
        _eng_name = st.selectbox("LLM Engine:", _eng_list, index=_eidx, key=f"{key_prefix}_engine")

        _q = st.text_area("質問:", placeholder=f"例: 最近のあなた（{user_id}）の関心と、その背景を教えて",
                          height=90, key=f"{key_prefix}_q")
        if _q and st.button("Ask", key=f"{key_prefix}_ask"):
            with st.spinner("応答生成中..."):
                try:
                    # 質問文でHistoryをスコアリングして文脈合成（ユーザーメモリ注入方式）
                    _ctx, _used, _meta = _dmumb_t.build_context_text(
                        _svc, user_id, list(_dmum_t.LAYERS), query_text=_q)
                    _sys = (
                        f"あなたは「{user_id}」という人物本人です。"
                        f"以下はあなた（={user_id}）についての記憶情報のみです。"
                        f"この記憶だけに基づき、{user_id}本人になりきって一人称で回答してください。"
                        f"記憶に無いことは推測せず「記憶にない」と述べてください。"
                        f"外部知識やこの記憶以外の情報は使わないでください。\n\n"
                        f"{_ctx or '（記憶情報がありません）'}"
                    )
                    _eng = _adata["ENGINE"]["LLM"][_eng_name]
                    _resp = ""
                    for _p, _r, _c in _dmfm_t.call_function_by_name(
                            _eng["FUNC_NAME"], _q, _sys, _eng, [], [], {}, False):
                        if _r:
                            _resp += _r
                    st.session_state.setdefault(f"_{key_prefix}_hist", [])
                    st.session_state[f"_{key_prefix}_hist"].append({
                        "agent": f"{user_id} (User Twin / {_eng_name})",
                        "query": _q, "response": _resp,
                        "context": _ctx or "",
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except Exception as e:
                    st.error(f"実行エラー: {type(e).__name__}: {e}")
        _hist = st.session_state.get(f"_{key_prefix}_hist", [])
        if _hist and _hist[-1].get("context"):
            with st.expander("Context (User Twin)"):
                st.text(_hist[-1]["context"][:4000])
        for _h in _hist:
            with st.chat_message("user"):
                st.markdown(f"**[{_h['timestamp']}] {_h['agent']}**")
                st.markdown(_h["query"])
            with st.chat_message("assistant"):
                st.markdown(_h["response"])

    def _um_group_twin(user_ids, key_prefix="ume_cross"):
        """対象集団の代表AI（Group Twin）と対話。

        - 対象データ(Persona+Nowaday)からシステムプロンプトをLLM生成→手動修正可
        - Big5/基本感情の平均 + 二次感情Top5 を統計ブロックとして付与
        - サイドバー選択中エージェントのLLMエンジンのみ選択して対話（LLM単体）
        """
        import DigiM_FoundationModel as _dmfm_g
        st.markdown("---")
        st.subheader("Chat with this Group Twin")
        if not user_ids:
            st.caption("対象ユーザーを選択してください。")
            return
        try:
            _adata = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
        except Exception:
            _adata = st.session_state.get("agent_data", {}) or {}
        _el = dma.get_engine_list(_adata, model_type="LLM")
        if not _el:
            st.caption("選択中エージェントにLLMエンジンが定義されていません。")
            return
        _ed = _adata.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", _el[0])
        _eng_name = st.selectbox("LLM Engine:", _el,
                                 index=_el.index(_ed) if _ed in _el else 0,
                                 key=f"{key_prefix}_g_engine")
        _eng = _adata["ENGINE"]["LLM"][_eng_name]

        _bk = f"_{key_prefix}_gtwin_sys"
        if st.button("システムプロンプト生成/再生成（Persona+Nowaday）", key=f"{key_prefix}_g_gen"):
            with st.spinner("生成中..."):
                st.session_state[_bk] = ux.build_group_twin_prompt(user_ids, "", _eng)
        _base = st.text_area("システムプロンプト（手動修正可）",
                             value=st.session_state.get(_bk, ""), height=170,
                             key=f"{key_prefix}_g_sysbox")

        _b5s = ux.cohort_big5_stats(user_ids, "")
        _es = ux.cohort_basic_emotion_stats(user_ids, "")
        _sec = ux.agg_secondary_emotions(user_ids, "")
        _stat = (
            "\n\n【この集団の統計】\n"
            "・Big5平均: " + "、".join(f"{ux.BIG5_JA.get(t,t)}={_b5s[t]['mean']:.2f}"
                                       for t in ux.BIG5_TRAITS)
            + "\n・基本感情平均: " + "、".join(f"{ux.PLUTCHIK_JA.get(e,e)}={_es[e]['mean']:.2f}"
                                              for e in ux.PLUTCHIK_PRIMARY)
            + "\n・二次感情Top5: " + ("、".join(f"{ux.PLUTCHIK_JA.get(k,k)}({c})"
                                               for k, c in _sec.most_common(5)) or "なし")
        )
        with st.expander("付与される統計ブロック"):
            st.text(_stat)

        _q = st.text_area("質問:", height=90, key=f"{key_prefix}_g_q",
                          placeholder="例: この集団が最も重視している価値観は？")
        if _q and st.button("Ask", key=f"{key_prefix}_g_ask"):
            with st.spinner("応答生成中..."):
                try:
                    _sys = (_base or "あなたはこのユーザー集団を代表する人物です。") + _stat
                    _resp = ""
                    for _p, _r, _c in _dmfm_g.call_function_by_name(
                            _eng["FUNC_NAME"], _q, _sys, _eng, [], [], {}, False):
                        if _r:
                            _resp += _r
                    st.session_state.setdefault(f"_{key_prefix}_g_hist", [])
                    st.session_state[f"_{key_prefix}_g_hist"].append({
                        "agent": f"Group Twin ({len(user_ids)}人 / {_eng_name})",
                        "query": _q, "response": _resp,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except Exception as e:
                    st.error(f"実行エラー: {type(e).__name__}: {e}")
        for _h in st.session_state.get(f"_{key_prefix}_g_hist", []):
            with st.chat_message("user"):
                st.markdown(f"**[{_h['timestamp']}] {_h['agent']}**")
                st.markdown(_h["query"])
            with st.chat_message("assistant"):
                st.markdown(_h["response"])

    _tab_edit, _tab_deep, _tab_cross = st.tabs(
        ["マイメモリ", "ユーザー理解(個人)", "グループ理解"])

    # ===== タブ: ユーザー理解(個人) =====
    with _tab_deep:
        _uid = st.selectbox("ユーザー:", _all_users, key="ume_deep_user")
        _b = ux.load_bundle(_uid, "")
        _p = _b["persona"] or {}

        st.markdown("#### Persona（長期像）")
        if _p:
            if _p.get("role"):
                st.markdown(f"**役割:** {_p.get('role')}")
            if _p.get("summary_text"):
                st.caption(_p.get("summary_text"))
            _b5 = _p.get("big5") or {}
            _appr = []  # (label, score) for radar
            _b5rows = []  # for table (特性/スコアのみ)
            for t in ux.BIG5_TRAITS:
                _it = _b5.get(t)
                if not isinstance(_it, dict):
                    continue
                _stt = (_it.get("status") or "").strip().lower()
                if _stt == "deleted":
                    continue
                _sc = float(_it.get("score", 0.5) or 0.5)
                _appr.append((ux.BIG5_JA.get(t, t), _sc))
                _b5rows.append({"特性": ux.BIG5_JA.get(t, t), "スコア": _sc})
            if _appr:
                _c1, _c2 = st.columns([1, 1])
                with _c1:
                    st.pyplot(_radar([l for l, _ in _appr], [v for _, v in _appr],
                                     "Big5 (approved+pending)"))
                with _c2:
                    st.dataframe(pd.DataFrame(_b5rows), hide_index=True)
            else:
                st.caption("Big5はまだありません（下の要レビュー参照）")
        else:
            st.caption("Persona未生成")

        st.markdown("#### Nowaday（最近の傾向）")
        if _b["nowaday"]:
            _nw = _b["nowaday"][0]
            st.markdown(f"**期間:** {_nw.get('period','')}")
            if _nw.get("summary_text"):
                st.caption(_nw["summary_text"])
            _be = _nw.get("basic_emotions") or {}
            _vals = [float(_be.get(e, 0) or 0) for e in ux.PLUTCHIK_PRIMARY]
            if any(v > 0 for v in _vals):
                _ec1, _ec2 = st.columns([1, 1])
                with _ec1:
                    st.pyplot(_radar([ux.PLUTCHIK_JA.get(e, e) for e in ux.PLUTCHIK_PRIMARY],
                                     _vals, "基本感情（強度）"))
                with _ec2:
                    st.dataframe(pd.DataFrame(
                        [{"特性": ux.PLUTCHIK_JA.get(e, e),
                          "スコア": round(float(_be.get(e, 0) or 0), 2)}
                         for e in ux.PLUTCHIK_PRIMARY]), hide_index=True)
            if _nw.get("secondary_emotions"):
                st.markdown("**二次感情:** " + "、".join(
                    ux.PLUTCHIK_JA.get(s, s) for s in _nw["secondary_emotions"]))
            for _lbl, _k in (("継続", "recurring_topics"), ("新規", "emerging"),
                             ("減退", "declining"), ("変化", "shifts")):
                if _nw.get(_k):
                    st.markdown(f"**{_lbl}:** " + "、".join(str(x) for x in _nw[_k]))
        else:
            st.caption("Nowaday未生成")

        st.markdown("#### History 感情トラジェクトリ")
        _traj_all = ux.user_emotion_trajectory(_uid, "")
        if _traj_all:
            _def_end = now_time.date()
            _def_start = (now_time - timedelta(days=30)).date()
            _rng = st.date_input(
                "期間（このユーザーのHistory日付で絞り込み）",
                value=(_def_start, _def_end), key="ume_deep_traj_period",
            )
            if isinstance(_rng, (list, tuple)) and len(_rng) == 2:
                _s, _e = _rng[0].isoformat(), _rng[1].isoformat()
            elif isinstance(_rng, (list, tuple)) and len(_rng) == 1:
                _s, _e = _rng[0].isoformat(), _def_end.isoformat()
            else:
                _s, _e = _rng.isoformat(), _def_end.isoformat()
            _traj = [(d, t, es) for d, t, es in _traj_all if _s <= d <= _e]
            st.caption(f"対象 {_s} 〜 {_e}: {len(_traj)}件 / 全{len(_traj_all)}件")
            if _traj:
                _rows = []
                for _d, _t, _emos in _traj:
                    _row = {"date": _d}
                    for _e2 in _emos:
                        _row[ux.PLUTCHIK_JA.get(_e2, _e2)] = _row.get(ux.PLUTCHIK_JA.get(_e2, _e2), 0) + 1
                    _rows.append(_row)
                _df = pd.DataFrame(_rows).fillna(0)
                if not _df.empty and len(_df.columns) > 1:
                    _agg = _df.groupby("date").sum(numeric_only=True)
                    st.area_chart(_agg)
                with st.expander(f"セッション別 感情ログ（{len(_traj)}件）"):
                    st.dataframe(pd.DataFrame(
                        [{"date": d, "topic": t, "emotions": "、".join(ux.PLUTCHIK_JA.get(e, e) for e in es)}
                         for d, t, es in reversed(_traj)], ), hide_index=True)
            else:
                st.caption("指定期間にHistoryがありません")
        else:
            st.caption("History未生成")

        _rev = ux.persona_review_items(_uid, "")
        if _rev["big5"] or _rev["lists"]:
            with st.expander("要レビュー（pending）項目"):
                if _rev["big5"]:
                    st.markdown("**Big5:** " + "、".join(
                        f"{ux.BIG5_JA.get(t,t)}(score={s},conf={c})" for t, s, c in _rev["big5"]))
                for _f, _items in _rev["lists"].items():
                    st.markdown(f"**{_f}:** " + "、".join(_items))

        _um_twin_chat(_uid, "ume_deep")

    # ===== タブ: グループ理解 =====
    with _tab_cross:
        import DigiM_VAnalytics as _dmva_g
        st.markdown("#### 対象ユーザー選択")
        _cohort = st.multiselect("対象ユーザー", _all_users,
                                  default=list(_all_users), key="ume_cross_users")
        st.caption(f"{len(_cohort)}人 選択中")
        if not _cohort:
            st.info("対象ユーザーを1人以上選択してください。")
        else:
            _b5L = [ux.BIG5_JA.get(t, t) for t in ux.BIG5_TRAITS]
            _emL = [ux.PLUTCHIK_JA.get(e, e) for e in ux.PLUTCHIK_PRIMARY]

            # ---------- Persona ----------
            st.markdown("### Persona")
            _b5s = ux.cohort_big5_stats(_cohort, "")
            _pc1, _pc2 = st.columns([1, 1])
            with _pc1:
                st.pyplot(_radar3(_b5L, [
                    ("最大", "#d62728", [_b5s[t]["max"] for t in ux.BIG5_TRAITS]),
                    ("平均", "#1f77b4", [_b5s[t]["mean"] for t in ux.BIG5_TRAITS]),
                    ("最小", "#2ca02c", [_b5s[t]["min"] for t in ux.BIG5_TRAITS]),
                ], "Big5 (max / mean / min)"))
            with _pc2:
                st.dataframe(pd.DataFrame([
                    {"特性": ux.BIG5_JA.get(t, t), "最大": _b5s[t]["max"],
                     "平均": _b5s[t]["mean"], "最小": _b5s[t]["min"]}
                    for t in ux.BIG5_TRAITS]), hide_index=True)

            _ptext = "\n".join(ux.persona_text(u, "") for u in _cohort)
            _pf = ux.word_freq(_ptext)
            if _pf:
                _wcf = _dmva_g.make_wordcloud_figure(_pf, title="Persona", width=560, height=300)
                if _wcf is not None:
                    st.pyplot(_wcf)

            _pkmax = max(2, len(_cohort))
            _pk = st.number_input("Personaクラスタ数", 2, _pkmax,
                                  min(3, _pkmax), key="ume_cross_pk")
            if st.button("Personaクラスタリング実行", key="ume_cross_pcl"):
                st.session_state["_ume_pcluster"] = ux.cluster_users(
                    [(u, ux.persona_text(u, "")) for u in _cohort], int(_pk), "")
                st.session_state["_ume_pexp"] = None
            _pcl = st.session_state.get("_ume_pcluster")
            if _pcl:
                if _pcl.get("error"):
                    st.warning(_pcl["error"])
                else:
                    st.caption(_pcl["info"])
                    st.dataframe(_pcl["df"], hide_index=True)
                    if st.button("クラスタを解説（Persona）", key="ume_cross_pexp_btn"):
                        with st.spinner("解説生成中..."):
                            st.session_state["_ume_pexp"] = ux.explain_clusters(_pcl["summary"])
                    if st.session_state.get("_ume_pexp"):
                        st.markdown(st.session_state["_ume_pexp"])

            # ---------- Nowaday ----------
            st.markdown("### Nowaday")
            _es = ux.cohort_basic_emotion_stats(_cohort, "")
            _nc1, _nc2 = st.columns([1, 1])
            with _nc1:
                st.pyplot(_radar3(_emL, [
                    ("最大", "#d62728", [_es[e]["max"] for e in ux.PLUTCHIK_PRIMARY]),
                    ("平均", "#1f77b4", [_es[e]["mean"] for e in ux.PLUTCHIK_PRIMARY]),
                    ("最小", "#2ca02c", [_es[e]["min"] for e in ux.PLUTCHIK_PRIMARY]),
                ], "基本感情 (max / mean / min)"))
            with _nc2:
                st.dataframe(pd.DataFrame([
                    {"感情": ux.PLUTCHIK_JA.get(e, e), "最大": _es[e]["max"],
                     "平均": _es[e]["mean"], "最小": _es[e]["min"]}
                    for e in ux.PLUTCHIK_PRIMARY]), hide_index=True)

            _sec = ux.agg_secondary_emotions(_cohort, "")
            if _sec:
                st.markdown("**二次感情ランキング（合計件数）**")
                st.dataframe(pd.DataFrame([
                    {"二次感情": ux.PLUTCHIK_JA.get(k, k), "件数": c}
                    for k, c in _sec.most_common()]), hide_index=True)

            _nfc = ux.nowaday_field_corpus(_cohort, "")
            st.markdown("**Nowadayワードクラウド**")
            _wcc = st.columns(2)
            for _i, (_fk, _fl) in enumerate(
                    [("summary", "サマリー"), ("recurring", "継続"),
                     ("emerging", "新規"), ("declining", "減退"), ("shifts", "変化")]):
                _fr = ux.word_freq(_nfc.get(_fk, ""))
                if _fr:
                    _wf = _dmva_g.make_wordcloud_figure(_fr, title=_fl, width=360, height=220)
                    if _wf is not None:
                        _wcc[_i % 2].pyplot(_wf)
                else:
                    _wcc[_i % 2].caption(f"{_fl}: データなし")

            _nkmax = max(2, len(_cohort))
            _nk = st.number_input("Nowadayクラスタ数", 2, _nkmax,
                                  min(3, _nkmax), key="ume_cross_nk")
            if st.button("Nowadayクラスタリング実行", key="ume_cross_ncl"):
                st.session_state["_ume_ncluster"] = ux.cluster_users(
                    [(u, ux.nowaday_text(u, "")) for u in _cohort], int(_nk), "")
                st.session_state["_ume_nexp"] = None
            _ncl = st.session_state.get("_ume_ncluster")
            if _ncl:
                if _ncl.get("error"):
                    st.warning(_ncl["error"])
                else:
                    st.caption(_ncl["info"])
                    st.dataframe(_ncl["df"], hide_index=True)
                    if st.button("クラスタを解説（Nowaday）", key="ume_cross_nexp_btn"):
                        with st.spinner("解説生成中..."):
                            st.session_state["_ume_nexp"] = ux.explain_clusters(_ncl["summary"])
                    if st.session_state.get("_ume_nexp"):
                        st.markdown(st.session_state["_ume_nexp"])

            # ---------- History 感情トラジェクトリ（合計） ----------
            st.markdown("### History 感情トラジェクトリ（合計）")
            _ht = ux.cohort_history_emotion_totals(_cohort, "")
            if _ht:
                st.bar_chart(pd.Series(
                    {ux.PLUTCHIK_JA.get(k, k): v for k, v in _ht.items()}, name="件数"))
                st.caption(f"対象 {len(_cohort)}人の全History合計: "
                           + "、".join(f"{ux.PLUTCHIK_JA.get(k,k)}={v}"
                                       for k, v in list(_ht.items())[:8]))
            else:
                st.caption("History未生成")

            # ---------- Chat with this Group Twin ----------
            _um_group_twin(_cohort, "ume_cross")

    # ===== タブ: マイメモリ（自分のメモリのみ確認・修正） =====
    with _tab_edit:
        import DigiM_UserMemory as _dmum_e
        _me = st.session_state.get("user_id", "")
        st.caption(f"対象: **{_me}**（自分のユーザーメモリのみ編集できます）")
        if not _me:
            st.info("ログインユーザーが特定できません。")
        else:
            _mb = ux.load_bundle(_me, "")
            _emo_all = list(ux.PLUTCHIK_PRIMARY) + list(ux.PLUTCHIK_SECONDARY)
            _stat_opts = ["approved", "pending", "deleted"]

            # ---- Persona ----
            with st.expander("Persona（長期像）を編集", expanded=True):
                _pr = _mb["persona"] or {}
                if not _pr:
                    st.caption("Persona未生成")
                else:
                    _role = st.text_input("役割(role)", value=_pr.get("role", ""), key="ume_e_role")
                    _summary = st.text_area("要約(summary_text)", value=_pr.get("summary_text", ""),
                                            height=120, key="ume_e_summary")
                    _flds = {
                        "expertise": "専門", "recurring_interests": "関心",
                        "values_principles": "価値観", "constraints": "制約",
                        "communication_style": "口調/説明の好み", "avoid_topics": "避けたい話題",
                    }
                    for _f, _jl in _flds.items():
                        _items = _pr.get(_f) or []
                        if not _items:
                            continue
                        st.markdown(f"**{_jl}**")
                        for _i, _it in enumerate(_items):
                            if not isinstance(_it, dict):
                                continue
                            _cc1, _cc2, _cc3 = st.columns([6, 2, 1])
                            _cc1.text_input(f"l_{_f}_{_i}", value=_it.get("label", ""),
                                            key=f"ume_e_lbl_{_f}_{_i}", label_visibility="collapsed")
                            _cs = (_it.get("status") or "pending").lower()
                            _cs = _cs if _cs in _stat_opts else "pending"
                            _cc2.selectbox(f"s_{_f}_{_i}", _stat_opts,
                                           index=_stat_opts.index(_cs),
                                           key=f"ume_e_st_{_f}_{_i}", label_visibility="collapsed")
                            _cc3.markdown(
                                f"<div style='padding-top:.4em;color:#888;font-size:.8em'>conf {float(_it.get('confidence') or 0):.2f}</div>",
                                unsafe_allow_html=True)
                    # Big5
                    _b5 = _pr.get("big5") or {}
                    if _b5:
                        st.markdown("**Big5**")
                        for _t in ux.BIG5_TRAITS:
                            _bi = _b5.get(_t) or {}
                            _bc1, _bc2, _bc3 = st.columns([3, 3, 2])
                            _bc1.markdown(f"{ux.BIG5_JA.get(_t,_t)}")
                            _bc2.number_input(f"score_{_t}", min_value=0.0, max_value=1.0,
                                              value=float(_bi.get("score", 0.5) or 0.5), step=0.05,
                                              key=f"ume_e_b5sc_{_t}", label_visibility="collapsed")
                            _bs = (_bi.get("status") or "pending").lower()
                            _bs = _bs if _bs in _stat_opts else "pending"
                            _bc3.selectbox(f"b5st_{_t}", _stat_opts,
                                           index=_stat_opts.index(_bs),
                                           key=f"ume_e_b5st_{_t}", label_visibility="collapsed")
                    if st.button("Persona を保存", key="ume_e_save_persona"):
                        _upd = dict(_pr)
                        _upd["role"] = st.session_state.get("ume_e_role", _upd.get("role", ""))
                        _upd["summary_text"] = st.session_state.get("ume_e_summary", _upd.get("summary_text", ""))
                        for _f in _flds:
                            _items = _pr.get(_f) or []
                            _ni = []
                            for _i, _it in enumerate(_items):
                                if not isinstance(_it, dict):
                                    continue
                                _ni.append({
                                    "label": st.session_state.get(f"ume_e_lbl_{_f}_{_i}", _it.get("label", "")),
                                    "confidence": float(_it.get("confidence") or 0.0),
                                    "status": st.session_state.get(f"ume_e_st_{_f}_{_i}", _it.get("status") or "pending"),
                                    "evidence": _it.get("evidence") or [],
                                })
                            _upd[_f] = _ni
                        if _b5:
                            _nb5 = dict(_b5)
                            for _t in ux.BIG5_TRAITS:
                                _src = dict(_b5.get(_t) or {})
                                _src["score"] = float(st.session_state.get(f"ume_e_b5sc_{_t}", _src.get("score", 0.5)))
                                _src["status"] = st.session_state.get(f"ume_e_b5st_{_t}", _src.get("status") or "pending")
                                _src.setdefault("confidence", 0.0)
                                _nb5[_t] = _src
                            _upd["big5"] = _nb5
                        _upd["last_reviewed"] = _dmum_e.now_ts()
                        _dmum_e.upsert("persona", _upd)
                        st.session_state.sidebar_message = "Persona を保存しました"
                        st.rerun()

            # ---- Nowaday ----
            with st.expander("Nowaday（最近の傾向）を編集"):
                _nws = _mb["nowaday"]
                if not _nws:
                    st.caption("Nowaday未生成")
                else:
                    # _nws は generated_at 降順。スナップショット履歴のため period@生成時刻で一意表示
                    _nw_opts = {
                        f"{m.get('period','')} @ {m.get('generated_at','')}": m for m in _nws
                    }
                    _osel = st.selectbox("スナップショット（period @ 生成時刻、上が最新）",
                                         list(_nw_opts.keys()), key="ume_e_nw_period")
                    _nw = _nw_opts[_osel]
                    _psel = _nw.get("period", "")
                    _k = "".join(ch for ch in str(_nw.get("id", _osel)) if ch.isalnum() or ch == "_")
                    _nw_sum = st.text_area("要約(summary_text)", value=_nw.get("summary_text", ""),
                                           height=110, key=f"ume_e_nw_sum_{_k}")
                    _listflds = {"recurring_topics": "継続トピック", "emerging": "新規関心",
                                 "declining": "減退話題", "shifts": "変化"}
                    for _lf, _lj in _listflds.items():
                        st.text_area(f"{_lj}（1行1項目）",
                                     value="\n".join(str(x) for x in (_nw.get(_lf) or [])),
                                     height=80, key=f"ume_e_nw_{_lf}_{_k}")
                    st.markdown("**基本感情（強度0-1）**")
                    _be = _nw.get("basic_emotions") or {}
                    _bcols = st.columns(4)
                    for _ei, _e in enumerate(ux.PLUTCHIK_PRIMARY):
                        _bcols[_ei % 4].number_input(
                            f"{ux.PLUTCHIK_JA.get(_e,_e)}", min_value=0.0, max_value=1.0,
                            value=float(_be.get(_e, 0) or 0), step=0.05,
                            key=f"ume_e_nw_be_{_e}_{_k}")
                    _sec_cur = [s for s in (_nw.get("secondary_emotions") or []) if s in ux.PLUTCHIK_SECONDARY]
                    st.multiselect("二次感情", list(ux.PLUTCHIK_SECONDARY), default=_sec_cur,
                                   format_func=lambda s: ux.PLUTCHIK_JA.get(s, s),
                                   key=f"ume_e_nw_sec_{_k}")
                    if st.button("Nowaday を保存", key=f"ume_e_save_nw_{_k}"):
                        _u = dict(_nw)
                        _u["summary_text"] = st.session_state.get(f"ume_e_nw_sum_{_k}", _u.get("summary_text", ""))
                        for _lf in _listflds:
                            _txt = st.session_state.get(f"ume_e_nw_{_lf}_{_k}", "")
                            _u[_lf] = [ln.strip() for ln in _txt.split("\n") if ln.strip()]
                        _u["basic_emotions"] = {
                            _e: float(st.session_state.get(f"ume_e_nw_be_{_e}_{_k}", 0) or 0)
                            for _e in ux.PLUTCHIK_PRIMARY}
                        _u["secondary_emotions"] = list(st.session_state.get(f"ume_e_nw_sec_{_k}", []))
                        _dmum_e.upsert("nowaday", _u)
                        st.session_state.sidebar_message = f"Nowaday({_psel}) を保存しました"
                        st.rerun()

            # ---- History ----
            with st.expander("History（セッション要点）を編集"):
                _hs = _mb["history"]
                if not _hs:
                    st.caption("History未生成")
                else:
                    _hopts = {
                        f"{str(h.get('create_date') or '')[:16]} | {str(h.get('topic') or '')[:30]} | {h.get('session_id','')}": h
                        for h in _hs}
                    _hsel = st.selectbox("セッション", list(_hopts.keys()), key="ume_e_h_sel")
                    _h = _hopts[_hsel]
                    _hk = _h.get("session_id", "x")
                    st.text_input("トピック", value=_h.get("topic", ""), key=f"ume_e_h_topic_{_hk}")
                    st.text_area("抜粋(excerpt)", value=_h.get("excerpt", ""), height=110,
                                 key=f"ume_e_h_exc_{_hk}")
                    _hemo = [e for e in (_h.get("emotions") or []) if e in _emo_all]
                    st.multiselect("感情(プルチック)", _emo_all, default=_hemo,
                                   format_func=lambda s: ux.PLUTCHIK_JA.get(s, s),
                                   key=f"ume_e_h_emo_{_hk}")
                    st.number_input("confidence", min_value=0.0, max_value=1.0,
                                    value=float(_h.get("confidence") or 0.0), step=0.05,
                                    key=f"ume_e_h_conf_{_hk}")
                    st.checkbox("有効(active) — オフで一覧/コンテキストから除外",
                                value=((_h.get("active") or "Y") == "Y"),
                                key=f"ume_e_h_act_{_hk}")
                    if st.button("History を保存", key=f"ume_e_save_h_{_hk}"):
                        _u = dict(_h)
                        _u["topic"] = st.session_state.get(f"ume_e_h_topic_{_hk}", _u.get("topic", ""))
                        _u["excerpt"] = st.session_state.get(f"ume_e_h_exc_{_hk}", _u.get("excerpt", ""))
                        _u["emotions"] = list(st.session_state.get(f"ume_e_h_emo_{_hk}", []))
                        _u["confidence"] = float(st.session_state.get(f"ume_e_h_conf_{_hk}", 0.0))
                        _u["active"] = "Y" if st.session_state.get(f"ume_e_h_act_{_hk}", True) else "N"
                        _dmum_e.upsert("history", _u)
                        st.session_state.sidebar_message = "History を保存しました"
                        st.rerun()


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
                    # UIキャッシュ（session_state）を全クリア。
                    # 別ユーザーで再ログインしたときに前ユーザーの
                    # セッション一覧・エージェント設定・権限フラグ等が残らないようにする。
                    _preserved = {"_cookie_manager"}
                    for key in list(st.session_state.keys()):
                        if key in _preserved:
                            continue
                        del st.session_state[key]
                    st.session_state._just_logged_out = True
                    st.rerun()

        # メインビュー切り替え
        _view_options = ["Chat"]
        if st.session_state.allowed_knowledge_explorer:
            _view_options.append("Knowledge Explorer")
        if st.session_state.allowed_user_memory_explorer:
            _view_options.append("User Memory Explorer")
        if st.session_state.allowed_scheduler:
            _view_options.append("Scheduler")
        if len(_view_options) > 1:
            _current = st.session_state.get("main_view", "Chat")
            _view_index = _view_options.index(_current) if _current in _view_options else 0
            st.session_state.main_view = st.radio("View:", _view_options, index=_view_index, horizontal=True, label_visibility="collapsed")
        else:
            st.session_state.main_view = "Chat"

        # エージェントを選択（JSON)
        if agent_id_selected := st.selectbox("Select Agent:", st.session_state.agent_list, index=st.session_state.agent_list_index):
            if st.session_state.agent_id != agent_id_selected:
                # エージェント切替時はORG/Persona選択をリセット
                st.session_state.selected_org = None
                st.session_state.selected_persona_ids = []
            st.session_state.agent_id = agent_id_selected
            st.session_state.agent_file = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.agent_id), None)
            st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
            st.session_state.engine_name = st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
            st.session_state.imagegen_engine_name = st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")

        # ORG / Persona 選択（エージェントに ORG が定義されている場合のみ表示）
        _agent_orgs = st.session_state.agent_data.get("ORG") or []
        if isinstance(_agent_orgs, list) and _agent_orgs:
            def _format_org(org_dict):
                if not isinstance(org_dict, dict) or not org_dict:
                    return "(empty)"
                return ", ".join(f"{k}={v}" for k, v in org_dict.items())

            _org_labels = [_format_org(o) for o in _agent_orgs]
            _label_to_org = dict(zip(_org_labels, _agent_orgs))

            # 既存選択があれば対応するindexを復元、無ければ先頭
            _current_idx = 0
            if st.session_state.selected_org in _agent_orgs:
                _current_idx = _agent_orgs.index(st.session_state.selected_org)
            _selected_label = st.selectbox("ORG:", _org_labels, index=_current_idx, key="org_select")
            _selected_org = _label_to_org[_selected_label]
            if st.session_state.selected_org != _selected_org:
                st.session_state.selected_org = _selected_org
                st.session_state.selected_persona_ids = []  # ORG切替時はPersona選択をリセット

            # ORGに合致するペルソナを取得
            _persona_files = st.session_state.agent_data.get("PERSONA_FILES") or None
            _persona_source = st.session_state.agent_data.get("PERSONA_SOURCE")
            try:
                _candidate_personas = dap.find_personas_by_org(
                    _selected_org,
                    template_agent=st.session_state.agent_file,
                    persona_files=_persona_files,
                    source=_persona_source,
                )
            except Exception as _e:
                _candidate_personas = []
                st.warning(f"ペルソナ取得失敗: {_e}")

            if _candidate_personas:
                _persona_labels = [f"{p['persona_id']}: {p['name']}" for p in _candidate_personas]
                _label_to_pid = {lbl: p["persona_id"] for lbl, p in zip(_persona_labels, _candidate_personas)}
                _pid_to_label = {p["persona_id"]: lbl for lbl, p in zip(_persona_labels, _candidate_personas)}
                _default_labels = [_pid_to_label[pid] for pid in st.session_state.selected_persona_ids if pid in _pid_to_label]
                _selected_labels = st.multiselect("Personas:", _persona_labels, default=_default_labels, key="persona_select")
                st.session_state.selected_persona_ids = [_label_to_pid[lbl] for lbl in _selected_labels]
                if len(st.session_state.selected_persona_ids) >= 2:
                    st.caption(f"複数ペルソナ並列実行モード ({len(st.session_state.selected_persona_ids)}人)")
            else:
                st.caption("該当するペルソナがありません")
                st.session_state.selected_persona_ids = []

        side_col1, side_col2 = st.columns(2)

        # 新しいセッションを発番（IDを指定して、新規にセッションリフレッシュ）
        if st.session_state.get("main_view") == "Knowledge Explorer":
            if side_col1.button("New Analysis", key="new_analysis_sidebar"):
                for _k in list(st.session_state.keys()):
                    if _k.startswith("_rag_"):
                        del st.session_state[_k]
                st.rerun()
        elif st.session_state.get("main_view") == "User Memory Explorer":
            if side_col1.button("Clear Dialogue", key="ume_clear_dialogue"):
                for _k in list(st.session_state.keys()):
                    if _k.startswith("_ume_") and _k.endswith("_hist"):
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
            # 実行中バックグラウンドジョブの管理
            _running_jobs = djr.list_jobs(user_id=st.session_state.get("user_id")) if st.session_state.get("user_admin_flg") != "Y" else djr.list_jobs()
            st.markdown("**Background Jobs**")
            if not _running_jobs:
                st.caption("実行中のジョブはありません")
            else:
                _job_labels = []
                _label_to_id = {}
                for j in _running_jobs:
                    _elapsed = (datetime.now() - j["start_time"]).total_seconds()
                    _sid = f" [{j['session_id']}]" if j.get("session_id") else ""
                    _label = f"{j['type']}{_sid} | {j['message']} ({int(_elapsed)}s){' [cancelling]' if j['cancel_requested'] else ''}"
                    _job_labels.append(_label)
                    _label_to_id[_label] = j["job_id"]
                _selected_job_labels = st.multiselect("Running Jobs", _job_labels, key="running_jobs_selected")
                if st.button("Cancel Selected Jobs", key="cancel_bg_jobs"):
                    _cancelled = 0
                    for _lbl in _selected_job_labels:
                        _jid = _label_to_id.get(_lbl)
                        if _jid and djr.cancel_job(_jid):
                            _cancelled += 1
                    st.session_state.sidebar_message = f"{_cancelled}件のバックグラウンドジョブにキャンセルを要求しました"
                    st.rerun()
            st.markdown("---")

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
                    # 接続テスト: psycopg2で軽くSELECT 1（タイムアウト5秒）
                    if st.button("Check DB Connection", key="db_check"):
                        with st.spinner("DB接続を確認中..."):
                            try:
                                import psycopg2
                                _cfg = dict(dmdbe.DB_CONFIG)
                                _cfg["connect_timeout"] = 5
                                with psycopg2.connect(**_cfg) as _conn:
                                    with _conn.cursor() as _cur:
                                        _cur.execute("SELECT version()")
                                        _ver = _cur.fetchone()[0]
                                st.session_state.sidebar_message = f"DB接続OK: {_ver}"
                            except Exception as _e:
                                st.session_state.sidebar_message = f"DB接続失敗: {_e}"
                        st.rerun()

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
                _archive_days = st.number_input(
                    "Archive Older Than (days)", min_value=1, value=30, step=1,
                    key="archive_days_input",
                    help="この日数より古い（最終更新日基準）セッションをZIPに圧縮します",
                )
                if st.button("Archive Old Sessions", key="archive_sessions"):
                    with st.spinner("アーカイブ中..."):
                        try:
                            result = dms.archive_old_sessions(days=int(_archive_days))
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
                        # 旧UserDialog自動保存（互換維持）。auto_save_flg=Yで起動。
                        if cfg.user_dialog_auto_save_flg == "Y":
                            try:
                                dmgu.save_user_dialogs(st.session_state.web_service, st.session_state.web_user)
                            except Exception:
                                pass
                        # 新UserMemory短期: 未保存セッションを自動処理
                        if (os.getenv("USER_MEMORY_HISTORY_AUTO_SAVE_FLG") or "N") == "Y":
                            import DigiM_GeneUserMemory as _dmgum_rag
                            try:
                                _dmgum_rag.save_history_for_unsaved_sessions()
                            except Exception:
                                pass
                    _run_bg_task("rag", "RAGデータを更新中", _rag_update)
                    st.rerun()

                # RAGの削除処理(未選択は全削除)
                st.session_state.rag_data_list_selected = st.multiselect("RAG DB", st.session_state.rag_data_list)
                if st.button("Delete RAG DB", key="delete_rag_db"):
                    dmc.del_rag_db(st.session_state.rag_data_list_selected)
                    st.session_state.sidebar_message = "RAGを削除しました"
                    st.session_state.rag_data_list = dmc.get_rag_list()

                # PageIndex Export: 選択したPageIndexをExcel+個別ファイルのZIPでローカル保存
                _pi_dict = dmc.get_page_index_list()
                _pi_names = list(_pi_dict.keys())
                if _pi_names:
                    st.markdown("---")
                    st.markdown("**Page Index Export**")
                    _pi_export = st.selectbox("Page Index", _pi_names, key="pi_export_select")
                    if _pi_export:
                        try:
                            _pi_zip = dmc.export_pageindex_as_excel_bundle(_pi_export)
                        except Exception as _pi_err:
                            _pi_zip = None
                            st.error(f"エクスポート失敗: {_pi_err}")
                        if _pi_zip:
                            st.download_button(
                                "Download (Excel + Files)", data=_pi_zip,
                                file_name=f"{_pi_export}.zip", mime="application/zip",
                                key=f"pi_dl_{_pi_export}",
                            )

                # セッションのユーザーダイアログ保存
                if cfg.user_dialog_auto_save_flg == "N":
                    st.markdown("---")
                    st.markdown("**User Dialog**")
                    if st.button("Save User Dialog", key="save_user_dialog"):
                        dmgu.save_user_dialogs(st.session_state.web_service, st.session_state.web_user)
                        st.session_state.sidebar_message = "ユーザーダイアログを保存しました"

                # User Memory (backend display, manual update)
                if st.session_state.allowed_user_memory:
                    import DigiM_UserMemory as _dmum_admin
                    import DigiM_UserMemorySetting as _dmus_admin
                    import DigiM_GeneUserMemory as _dmgum_admin
                    st.markdown("---")
                    st.markdown("**User Memory (Admin)**")
                    st.caption(
                        f"backends: history={_dmum_admin.get_backend('history')} / "
                        f"nowaday={_dmum_admin.get_backend('nowaday')} / "
                        f"persona={_dmum_admin.get_backend('persona')}"
                    )
                    st.caption(
                        f"system default layers: {', '.join(_dmum_admin.get_default_layers())}"
                    )

                    # Pick targets from user master (empty = all users)
                    try:
                        _user_master_for_um = load_user_master()
                    except Exception:
                        _user_master_for_um = {}
                    _um_target_options = sorted(_user_master_for_um.keys())
                    _um_target_users = st.multiselect(
                        "Target User IDs (empty = all users)",
                        _um_target_options, default=[], key="um_admin_target_users",
                    )

                    # Period: start date (calendar). Off = all periods
                    _um_period_use = st.checkbox("Filter by start date", value=False, key="um_admin_period_use")
                    _um_period_value = "all"
                    if _um_period_use:
                        _um_default_start = (now_time - timedelta(days=30)).date()
                        _um_period_date = st.date_input(
                            "Period (aggregate sessions on/after this date)",
                            value=_um_default_start,
                            key="um_admin_period_date",
                        )
                        _um_period_value = f"since_{_um_period_date.strftime('%Y-%m-%d')}"
                    st.caption(f"period={_um_period_value}")

                    # Unified update button: run History → Nowaday → Persona sequentially
                    if st.button("Update User Memory (History → Nowaday → Persona)", key="um_update_all", disabled=bool(st.session_state._bg_task)):
                        _per = _um_period_value
                        _tgt_users = list(_um_target_users) if _um_target_users else None
                        _svc = st.session_state.service_id
                        def _um_pipeline():
                            _dmgum_admin.update_user_memory_pipeline(
                                target_user_ids=_tgt_users, period=_per, service_id=_svc,
                            )
                        _label = f"Updating User Memory (users={'all' if not _tgt_users else len(_tgt_users)} period={_per})"
                        _run_bg_task("um_pipeline", _label, _um_pipeline)
                        st.rerun()

        # スケジュール管理は別メニュー(Scheduler)に移管。RAG Management からは触れません。

        # User Memory expander moved to the main area (below BOOK).

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

        # Knowledge Explorer用: 保存済み分析セッション一覧
        elif st.session_state.get("main_view", "Chat") == "Knowledge Explorer":
            st.markdown("----")
            _analytics_base = "user/common/analytics/knowledge_explorer/"
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
    if st.session_state.get("main_view") == "Knowledge Explorer":
        _knowledge_explorer()
        return
    if st.session_state.get("main_view") == "User Memory Explorer":
        _user_memory_explorer()
        return
    if st.session_state.get("main_view") == "Scheduler":
        _scheduler_view()
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
                            if "feedback" in v2["setting"]:
                                agent_feedback = v2["setting"]["feedback"]

                                if agent_feedback["ACTIVE"] == "Y":
                                    # カテゴリ選択肢を取得
                                    _cat_map = dmu.read_json_file("category_map.json", mst_folder_path)
                                    _cat_options = list(_cat_map.get("Category", {}).keys()) if _cat_map else ["未設定"]
                                    _default_cat = agent_feedback.get("DEFAULT_CATEGORY") or _cat_options[0]

                                    # セッション切替時に同じ(seq, sub_seq)で前セッションの下書きが残らないよう、
                                    # ウィジェットキーに session_id を含める
                                    _sid = st.session_state.session.session_id

                                    with st.chat_message("Feedback"):
                                        feedback = {}
                                        feedback["name"] = "Feedback"

                                        for fb_item in agent_feedback["FEEDBACK_ITEM_LIST"]:
                                            feedback[fb_item] = {}
                                            feedback[fb_item]["visible"] = False
                                            feedback[fb_item]["flg"] = False
                                            feedback[fb_item]["memo"] = ""
                                            feedback[fb_item]["category"] = _default_cat
                                            if "feedback" in v2:
                                                feedback[fb_item] = v2.get("feedback", {}).get(fb_item, feedback[fb_item])
                                            feedback[fb_item]["saved_memo"] = feedback[fb_item]["memo"]

                                            if st.checkbox(f"{fb_item}", key=f"feedback_{_sid}_{fb_item}_{k}_{k2}", value=feedback[fb_item]["visible"]):
                                                feedback[fb_item]["memo"] = st.text_area("Memo:", key=f"feedback_{_sid}_{fb_item}_memo{k}_{k2}", value=feedback[fb_item]["memo"], height=100, label_visibility="collapsed")
                                                _cat_idx = _cat_options.index(feedback[fb_item].get("category", _default_cat)) if feedback[fb_item].get("category", _default_cat) in _cat_options else 0
                                                feedback[fb_item]["category"] = st.selectbox("Category:", _cat_options, index=_cat_idx, key=f"feedback_{_sid}_{fb_item}_cat{k}_{k2}", label_visibility="collapsed")
                                                feedback[fb_item]["visible"] = True
                                            else:
                                                feedback[fb_item]["memo"] = ""
                                                feedback[fb_item]["visible"] = False

                                        if st.button("Feedback", key=f"feedback_btn_{_sid}_{k}_{k2}"):
                                            for fb_item in agent_feedback["FEEDBACK_ITEM_LIST"]:
                                                if feedback[fb_item]["memo"]!=feedback[fb_item]["saved_memo"] and feedback[fb_item]["memo"]!="":
                                                    feedback[fb_item]["flg"] = True
                                                if feedback[fb_item]["memo"]=="":
                                                    feedback[fb_item]["flg"] = False

                                            if any(k != "name" for k in fb_item):
                                                st.session_state.session.set_feedback_history(k, k2, feedback)
                                                dmgf.create_feedback_data(st.session_state.session.session_id, v2["setting"]["agent_file"])
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
                                                                        display_items = [c for c in display_items if c in rag_rank_df.columns]
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
                                                                    display_items = [c for c in display_items if c in rag_rank_df.columns]
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

            # メモリ参照のみ除外（表示は残す）。トグル変更時にその場で永続化
            _seq_setting = v.get("SETTING", {})
            _mem_off_now = (_seq_setting.get("MEMORY_FLG", "Y") == "N")
            _mem_off_new = st.checkbox(f"Memory Off(seq:{k})", value=_mem_off_now,
                                       key="mem_off_chat_seq"+k,
                                       help="ONにするとこのseqは画面には残るがLLMの会話メモリには含まれなくなります")
            if _mem_off_new != _mem_off_now:
                st.session_state.session.chg_seq_memory_flg(k, "N" if _mem_off_new else "Y")
                st.rerun()

    if st.session_state.session_user_id == st.session_state.user_id:
        # ファイルアップローダー（実行完了後にkeyをincrementしてウィジェットを再生成→添付クリア）
        uploaded_files = st.file_uploader(
            "Attached Files:",
            type=["txt", "vtt", "csv", "json", "pdf", "md", "docx", "xlsx", "pptx", "jpg", "jpeg", "png", "mp3"],
            accept_multiple_files=True,
            key=f"file_upload_{st.session_state.file_uploader_key}",
        )
        st.session_state.uploaded_files = uploaded_files
        show_uploaded_files_widget(st.session_state.uploaded_files)

        # WEB検索の設定
        if st.session_state.allowed_web_search:
            _ws_col1, _ws_col2 = st.columns([1, 2])
            if _ws_col1.checkbox("WEB Search", value=st.session_state.web_search):
                st.session_state.web_search = True
                _ws_default = dmu.read_yaml_file("setting.yaml").get("WEB_SEARCH_DEFAULT", "Perplexity")
                _ws_engines = list(dmt.WEB_SEARCH_ENGINES.keys())
                if "web_search_engine" not in st.session_state or st.session_state.web_search_engine not in _ws_engines:
                    st.session_state.web_search_engine = _ws_default if _ws_default in _ws_engines else _ws_engines[0]
                _ws_col2.selectbox("Engine:", _ws_engines, key="web_search_engine", label_visibility="collapsed")
            else:
                st.session_state.web_search = False

        # URL取得: 入力中のhttp(s)リンクは自動でフェッチして添付扱い。
        # サブページの追加クロールは任意（デフォルトOFF）。
        st.session_state.url_fetch_subpages = st.checkbox(
            "Include URL Subpages", value=st.session_state.url_fetch_subpages,
            help="入力にURLが含まれていれば自動で取得します。ONにすると同一ドメイン内のリンク先も可能な範囲で追加取得します（上限はsetting.yamlのURL_FETCH）。",
        )

        # Include Query: 直前seqが複数ペルソナ実行だった場合のみ表示
        def _prev_seq_is_multi_persona():
            try:
                _hist = st.session_state.session.chat_history_active_dict or {}
                if not _hist:
                    return False
                _max_seq = max(_hist.keys(), key=int)
                _seq_block = _hist.get(_max_seq, {})
                # seq単位のMEMORY_FLG=N（Phase 4: whole-practice並列）
                if _seq_block.get("SETTING", {}).get("MEMORY_FLG") == "N":
                    return True
                # 2つ以上のsub_seqで persona_id が設定されている（Phase 6: chain.PERSONAS）
                _sub_seqs = [k for k in _seq_block.keys() if k != "SETTING"]
                if len(_sub_seqs) >= 2:
                    _persona_count = sum(
                        1 for k in _sub_seqs
                        if _seq_block.get(k, {}).get("setting", {}).get("persona_id")
                    )
                    if _persona_count >= 2:
                        return True
                return False
            except Exception:
                return False

        if _prev_seq_is_multi_persona():
            st.session_state.include_query = st.checkbox(
                "Include Query (前回ペルソナ応答を入力に含める)",
                value=st.session_state.get("include_query", False),
                help="ONにすると、直前seqの各ペルソナ応答全文を次ターン入力の先頭に埋め込みます。RAGクエリ生成には影響しません。",
            )
        else:
            st.session_state.include_query = False

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
            # Personasオプションは ORG が定義されているエージェントのみ追加
            _agent_orgs = st.session_state.agent_data.get("ORG") or []
            if isinstance(_agent_orgs, list) and _agent_orgs:
                _thinking_options.append("Personas")
            # 既存の選択値からエージェントが対応していない項目を除外
            _saved_targets = [t for t in st.session_state.thinking_targets if t in _thinking_options]
            st.session_state.thinking_targets = st.multiselect(
                "Thinking Targets", _thinking_options,
                default=_saved_targets, label_visibility="collapsed",
            )

            # Max Personas: Thinking Mode ON かつ Personas が選択されているときのみ表示
            if "Personas" in st.session_state.thinking_targets:
                try:
                    _yaml = dmu.read_yaml_file("setting.yaml")
                    _default_max_p = int(_yaml.get("MAX_PERSONAS", 3))
                except Exception:
                    _default_max_p = 3
                st.session_state.max_personas = st.number_input(
                    "Max Personas (Thinking時の上限)",
                    min_value=1, max_value=20,
                    value=int(st.session_state.get("max_personas", _default_max_p)),
                    step=1,
                    help="chain.PERSONAS=\"THINKING\" のステップでPersonaSelectorが選定する上限。手動選択(multiselect)には影響しません。",
                )

        # BOOKから選択（エージェントに1つ以上のBookが設定されているときだけ表示）
        if st.session_state.allowed_book:
            _book_list = st.session_state.agent_data.get("BOOK") or []
            if isinstance(_book_list, list) and len(_book_list) > 0:
                st.session_state.book_selected = st.multiselect(
                    "BOOK", [item["RAG_NAME"] for item in _book_list]
                )

        # User Memory（メイン画面・BOOKの直下に配置。Allowed.User Memory=True で表示）
        if st.session_state.allowed_user_memory:
            import DigiM_UserMemorySetting as _dmus
            _uid_for_um = st.session_state.user_id

            with st.expander("User Memory", expanded=False):
                _user_setting = _dmus.load_user_setting(_uid_for_um)
                _active_layers = _dmus.resolve_active_layers(_uid_for_um)
                st.caption(f"Active layers: {', '.join(_active_layers) if _active_layers else '(all off)'}")

                # Layer On/Off (3列横並び) + Save Layer Setting
                _checked_layers = _user_setting.get("layers", [])
                _layer_cols = st.columns(3)
                _new_layers = []
                for _i, _l in enumerate(("persona", "nowaday", "history")):
                    _val = _layer_cols[_i].checkbox(_l, value=(_l in _checked_layers), key=f"um_layer_{_l}")
                    if _val:
                        _new_layers.append(_l)
                # Save しなくてもこのセッション(次回チャット)では現在のチェック状態を即時反映
                st.session_state.user_memory_layers_now = _new_layers
                if st.button("Save Layer Setting", key="um_save_layers"):
                    _dmus.save_user_setting(_uid_for_um, _new_layers)
                    st.session_state.sidebar_message = "Layer setting saved."
                    st.rerun()

                # Persona/Nowaday/History の確認・修正は
                # User Memory Explorer の「③ マイメモリ編集」タブへ移管。

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
                # 実行に取り込んだら WebUI 上の添付はリリース（次レンダーで空のアップローダーを再描画）
                st.session_state.uploaded_files = []
                st.session_state.file_uploader_key += 1

            # URL取得（入力中のhttp(s)リンクを自動検出しフェッチ）
            if dmuf.extract_urls(user_input):
                with st.spinner("URLの内容を取得しています..."):
                    try:
                        _uf_result = dmuf.fetch_urls_from_text(
                            user_input,
                            temp_folder_path,
                            include_subpages=st.session_state.url_fetch_subpages,
                        )
                    except Exception as _uf_err:
                        _uf_result = {"saved_paths": [], "summaries": [], "blocked": [],
                                      "error": str(_uf_err)}
                        st.error(f"URL取得で例外が発生しました: {_uf_err}")
                for _p in _uf_result.get("saved_paths", []):
                    uploaded_contents.append(_p)
                for _s in _uf_result.get("summaries", []):
                    st.info(f"取得: {_s.get('title') or _s['url']}（{_s['pages']}ページ） → {_s['file']}")
                for _b in _uf_result.get("blocked", []):
                    st.warning(f"ブロック/取得失敗: {_b.get('url')} — {_b.get('reason')}")

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
            # User Memory: 現在のチェック状態を最優先（Save押下に関わらず即時反映）
            if "user_memory_layers_now" in st.session_state:
                execution["USER_MEMORY_LAYERS"] = list(st.session_state.user_memory_layers_now or [])
            _targets = st.session_state.thinking_targets if st.session_state.thinking_mode else []
            execution["THINKING_TARGETS"] = {
                "habit": "Habit" in _targets,
                "web_search": "Web Search" in _targets,
                "rag_query_gene": "RAG Query" in _targets,
                "books": "Books" in _targets,
                "personas": "Personas" in _targets,
            }

            # バックグラウンドで実行開始（事前ロック）
            import threading
            st.session_state.session.save_status("LOCKED")
            execution["_PRE_LOCKED"] = True
            # Phase 7: PersonaSelectorの上限をexecutionに注入
            execution["MAX_PERSONAS"] = int(st.session_state.get("max_personas", 3))
            # 選択中のペルソナIDを実ペルソナdictに解決
            _resolved_personas = []
            _selected_pids = list(st.session_state.get("selected_persona_ids") or [])
            if _selected_pids and st.session_state.get("selected_org"):
                _persona_files = st.session_state.agent_data.get("PERSONA_FILES") or None
                _persona_source = st.session_state.agent_data.get("PERSONA_SOURCE")
                try:
                    _candidates = dap.find_personas_by_org(
                        st.session_state.selected_org,
                        template_agent=st.session_state.agent_file,
                        persona_files=_persona_files,
                        source=_persona_source,
                    )
                    _by_id = {p["persona_id"]: p for p in _candidates}
                    _resolved_personas = [_by_id[pid] for pid in _selected_pids if pid in _by_id]
                except Exception:
                    _resolved_personas = []

            # Include Query: 直前seqがMEMORY_FLG=N（マルチペルソナ等）なら、その全sub_seq応答を
            # ユーザー入力の先頭に埋め込み。RAGクエリには元の入力（rag_query_text）を使う。
            _enriched_input = user_input
            _rag_query_text = ""
            if st.session_state.get("include_query"):
                try:
                    _hist = st.session_state.session.chat_history_active_dict or {}
                    if _hist:
                        _max_seq = max(_hist.keys(), key=int)
                        _seq_block = _hist.get(_max_seq, {})
                        _setting = _seq_block.get("SETTING", {})
                        if _setting.get("MEMORY_FLG", "Y") == "N":
                            _persona_blobs = []
                            for _ssk in sorted([k for k in _seq_block.keys() if k != "SETTING"], key=int):
                                _sub = _seq_block[_ssk]
                                _resp = (_sub.get("response") or {}).get("text") or ""
                                _pname = (_sub.get("setting") or {}).get("persona_name") or (_sub.get("setting") or {}).get("name") or ""
                                if _resp:
                                    _persona_blobs.append(f"- {_pname}:\n{_resp}")
                            if _persona_blobs:
                                _enriched_input = (
                                    "[前回の各ペルソナの回答]\n" + "\n\n".join(_persona_blobs)
                                    + "\n\n[今回の質問]\n" + user_input
                                )
                                _rag_query_text = user_input
                except Exception:
                    pass

            _bg_params = {
                "service_info": dict(st.session_state.web_service),
                "user_info": dict(st.session_state.web_user),
                "session_id": st.session_state.session.session_id,
                "session_name": st.session_state.session.session_name,
                "agent_file": st.session_state.agent_file,
                "user_input": _enriched_input,
                "rag_query_text": _rag_query_text,
                "uploaded_contents": uploaded_contents,
                "situation": situation,
                "overwrite_items": overwrite_items,
                "add_knowledges": add_knowledges,
                "execution": execution,
                "personas": _resolved_personas,
                "org": st.session_state.get("selected_org"),
            }
            st.session_state._bg_user_input = user_input

            def _run_bg(params):
                _exec_error = ""
                try:
                    for _ in dme.DigiMatsuExecute_MultiPersona(
                        params["service_info"], params["user_info"],
                        params["session_id"], params["session_name"],
                        params["agent_file"], params["user_input"],
                        params["uploaded_contents"], params["situation"],
                        params["overwrite_items"], params["add_knowledges"],
                        params["execution"], params.get("personas") or [],
                        in_rag_query_text=params.get("rag_query_text") or "",
                        in_org=params.get("org"),
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
