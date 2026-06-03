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

# Generate config.toml before importing Streamlit (configures upload size limit)
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

# Start the background scheduler (follows SCHEDULES in setting.yaml; skips when only "off")
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
    # system.env is essentially fixed; read it just once here
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

# Cached settings
cfg = load_config()

# Load folder paths and other settings from setting.yaml
session_folder_prefix = cfg.session_folder_prefix
agent_folder_path = cfg.agent_folder_path
temp_folder_path = cfg.temp_folder_path
mst_folder_path = cfg.mst_folder_path

# Load system.env and set environment variables
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

# Check whether DB connection info is configured
_db_configured = all([
    os.getenv("POSTGRES_HOST"),
    os.getenv("POSTGRES_DB"),
    os.getenv("POSTGRES_USER"),
    os.getenv("POSTGRES_PASSWORD"),
])

# Time setup
tz = pytz.timezone(cfg.timezone)
now_time = datetime.now(tz)

# Streamlit settings
st.set_page_config(page_title=web_title, layout="wide")

# --- Cookie authentication ---
_COOKIE_NAME = "digim_auth"
_COOKIE_SECRET = os.getenv("COOKIE_SECRET", "digim_default_secret_key_2026")
_COOKIE_EXPIRY_DAYS = 7

def _get_cookie_manager():
    if "_cookie_manager" not in st.session_state:
        st.session_state._cookie_manager = stx.CookieManager()
    return st.session_state._cookie_manager

# Generate an HMAC token from user_id
def _make_auth_token(user_id: str) -> str:
    sig = hmac.new(_COOKIE_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    return f"{user_id}:{sig}"

# Verify the token and return user_id; None when invalid
def _verify_auth_token(token: str):
    if not token or ":" not in token:
        return None
    user_id, sig = token.rsplit(":", 1)
    expected = hmac.new(_COOKIE_SECRET.encode(), user_id.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected):
        return user_id
    return None

# Set the cookie on successful login
def _set_auth_cookie(cookie_manager, user_id: str):
    token = _make_auth_token(user_id)
    expires = datetime.now() + timedelta(days=_COOKIE_EXPIRY_DAYS)
    cookie_manager.set(_COOKIE_NAME, token, expires_at=expires)

# Delete the cookie on logout (overwrite with an expired value to avoid KeyError)
def _clear_auth_cookie(cookie_manager):
    try:
        expires = datetime.now() - timedelta(days=1)
        cookie_manager.set(_COOKIE_NAME, "", expires_at=expires)
    except Exception:
        # Safety fallback (KeyError etc. when not in the internal cache)
        try:
            cookie_manager.delete(_COOKIE_NAME)
        except Exception:
            pass

# User login (JSON / RDB switched by LOGIN_AUTH_METHOD; see DigiM_Auth.py for details)
import DigiM_Auth as dma_auth


def load_user_master():
    return dma_auth.load_user_master()


# Hold logged-in user info
def save_user_master(users: dict):
    """Save the user master (PW accepts both plaintext and hash)."""
    dma_auth.save_user_master(users)

# Change password
def change_password(user_id: str, current_pw: str, new_pw: str) -> tuple[bool, str]:
    """Change the logged-in user's password. On success, save as a hash."""
    users = load_user_master()
    user_info = users.get(user_id)
    if not user_info:
        return False, "User not found."
    stored_pw = user_info.get("PW", "")
    if not dmu.verify_password(current_pw, stored_pw):
        return False, "Current password is incorrect."

    # Hash and save the new password (always store as a hash from the UI)
    users[user_id]["PW"] = dmu.hash_password(new_pw)
    save_user_master(users)
    return True, "Password changed."

# Set logged-in user info into the session state
def set_login_user_to_session(user_id: str, user_info: dict):
    # Group accepts both string and list; normalized to a list internally
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

# Login flow
def ensure_login():
    # If already logged in, do nothing
    if "login_user" in st.session_state and st.session_state.login_user:
        return

    # Cookie auth: restore from cookie even if session_state is lost
    cookie_manager = _get_cookie_manager()
    # If we just logged out, skip the cookie restore once so the rerender that fires
    # before the browser-side cookie deletion takes effect does not auto re-login
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
                # Load failures during cookie restore are re-handled in the login form
                users = {}
            user_info = users.get(cookie_user_id)
            if user_info:
                set_login_user_to_session(cookie_user_id, user_info)
                refresh_session_states()
                return

    st.title(web_title)
    st.subheader("Login:")

    # Load the user master (LOGIN_AUTH_METHOD: JSON / RDB)
    try:
        users = load_user_master()
    except Exception as e:
        st.error(f"Failed to load the user master (LOGIN_AUTH_METHOD={dma_auth.get_method()}): {e}")
        st.stop()
    if not users:
        st.error(f"User master is empty (LOGIN_AUTH_METHOD={dma_auth.get_method()}). Please configure the master.")
        st.stop()

    tab_login, tab_change = st.tabs(["Login", "Change Password"])

    # Login form
    with tab_login:
        with st.form("login_form"):
            input_user_id = st.text_input("User ID")
            input_pw = st.text_input("Password", type="password")
            remember_me = st.checkbox("Keep me logged in", value=True)
            submitted = st.form_submit_button("Login")

        if submitted:
            user_info = users.get(input_user_id)
            stored_pw = (user_info or {}).get("PW", "")

            # PW accepts both plaintext and hash (DigiM_Util.verify_password decides)
            if user_info and dmu.verify_password(input_pw, stored_pw):
                # If login succeeded with the legacy plaintext PW, auto-migrate to a hash for next time
                if stored_pw and not (isinstance(stored_pw, str) and stored_pw.startswith(("$2a$", "$2b$", "$2y$"))):
                    try:
                        users[input_user_id]["PW"] = dmu.hash_password(input_pw)
                        save_user_master(users)
                    except Exception:
                        # Even if the migration fails, allow login to proceed
                        pass

                set_login_user_to_session(input_user_id, user_info)
                if remember_me:
                    _set_auth_cookie(cookie_manager, input_user_id)
                st.success("Logged in")
                refresh_session_states()
                st.rerun()
            else:
                st.error("User ID or password is incorrect")

    # --- Change Password (executable before login: identify by User ID + current PW) ---
    with tab_change:
        st.caption("Enter your User ID and current password to change it.")
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
                st.error("User ID not found")
            elif not dmu.verify_password(cp_current_pw, stored_pw):
                st.error("Current password is incorrect")
            elif not cp_new_pw:
                st.error("Please enter the new password")
            elif cp_new_pw != cp_new_pw2:
                st.error("The new password confirmation does not match")
            else:
                try:
                    users[cp_user_id]["PW"] = dmu.hash_password(cp_new_pw)
                    save_user_master(users)
                    st.success("Password changed. Please log in from the Login tab.")
                except Exception as e:
                    st.error(f"Save failed: {e}")

    # Stop here so nothing after the login screen is rendered
    st.stop()

# Configure which UI features are available to the user
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

# Background task execution helper
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

# Execute the task in the background and set a file-flag on completion
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

# Initial declarations of the session state
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
        # If default_agent is hidden for the user's Group, fall back to the first agent
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
        # Counter used as the file uploader key. Incrementing on completion makes Streamlit
        # treat the widget as a fresh instance, which clears the attachment.
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

# Refresh session variables
def refresh_session_states():
    st.session_state.web_service = dict(web_default_service)
    st.session_state.web_service["SERVICE_ID"] = st.session_state.service_id
    st.session_state.web_user = dict(web_default_user)
    st.session_state.web_user["USER_ID"] = st.session_state.user_id
    st.session_state.sidebar_message = ""
    # Reset transient session state for User Memory
    # - Layer checkboxes are force-reset to the persisted master value (a plain del does not work because Streamlit remembers the widget state)
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
    # If default_agent is hidden for the user's Group, fall back to the first agent
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

# Refresh the session (sometimes the Session class is re-instantiated with the same session ID to refresh history)
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

# Refresh the session list
def refresh_session_list(service_id, user_id, user_admin_flg):
    st.session_state.session_list = dms.get_session_list_visible(service_id, user_id, user_admin_flg)
    st.session_state.session_inactive_list = dms.get_session_list_inactive_visible(service_id, user_id, user_admin_flg)
    st.session_state.session_inactive_list_selected = []

# Copy-to-clipboard button for the AI response
def render_copy_button(text, key):
    import html as _html
    escaped = _html.escape(text).replace("`", "\\`").replace("$", "\\$")
    st.components.v1.html(f"""
    <button onclick="navigator.clipboard.writeText(`{escaped}`).then(()=>{{this.textContent='Copied!';setTimeout(()=>this.textContent='Copy',1500)}})"
    style="background:transparent;border:1px solid #888;border-radius:4px;padding:2px 10px;cursor:pointer;font-size:12px;color:#888;">Copy</button>
    """, height=32)

# Display the uploaded file
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
        # st.image(path) infers MIME from the extension, so it fails to display when the
        # extension and the actual format mismatch (e.g. JPEG bytes inside a .png file).
        # Pass bytes and let Streamlit auto-detect the format.
        try:
            with open(uploaded_file, "rb") as _f:
                st.image(_f.read())
        except Exception:
            st.image(uploaded_file)
    elif "video" in file_type:
        st.video(uploaded_file)
    elif "audio" in file_type:
        st.audio(uploaded_file)

# Display files attached via the file-uploader widget
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

# Configure file formats for download
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
    """Return chat history as PDF bytes."""
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
                    pdf.cell(_w, 6, f"[image]", new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(4)

    pdf_bytes = bytes(pdf.output())
    file_name = f"{file_id}_{dl_type}.pdf"
    return pdf_bytes, file_name

def seq_label(x: str) -> str:
    return {
        "0": "Query 1 (raw input)",
        "1": "Query 2 (input + chat history)",
        "2": "Query 3 (intent of the input)",
    }.get(x, x)

def mode_label(x: str) -> str:
    if x == "NORMAL":
        return ""
    if isinstance(x, str) and x.startswith("(META_SEARCH:"):
        return " + period filter"
    return x

def _resolve_ku_file(_folder, _seq, _sub, _candidates, _logical_key, _rag):
    """Resolve the actual file name for a Knowledge Utility image.
    1) If a saved candidate exists, use it.
    2) Otherwise, glob-fallback to {seq}-{sub}-*<kind>*_{rag}.{ext} (session-name independent),
    so the file is not lost when the session name changes mid-session.
    """
    _ext = "csv" if "csv" in str(_logical_key) else "png"
    for _f in (_candidates or []):
        if _f and str(_f).endswith(f"_{_rag}.{_ext}") and os.path.exists(os.path.join(_folder, _f)):
            return _f
    _tok = {
        "scatter_plot_file_ref": "ScatterRefPlot",
        "scatter_plot_file_category": "ScatterCategoryPlot",
        "scatter_plot_file_csv": "ScatterData",
        "similarity_plot_file": "KUtilPlot",
    }.get(_logical_key, "")
    try:
        for _fn in sorted(os.listdir(_folder)):
            if _fn.startswith(f"{_seq}-{_sub}-") and (_tok in _fn if _tok else True) and _fn.endswith(f"_{_rag}.{_ext}"):
                return _fn
    except (FileNotFoundError, NotADirectoryError):
        pass
    return None


def ak_line(ak_dict):
    query_seq = seq_label(ak_dict.get("QUERY_SEQ", ""))
    query_mode = mode_label(ak_dict.get("QUERY_MODE", ""))
    title = ak_dict.get("title", "")
    sq = ak_dict.get("similarity_Q", "")
    sa = ak_dict.get("similarity_A", "")
    ku = ak_dict.get("knowledge_utility", "")

    # Format numeric values to 3 decimal places (non-numeric passes through)
    fmt = lambda x: f"{x:.3f}" if isinstance(x, (int, float)) else x
    line = (
        f'{title} (Q similarity: {fmt(sq)} -> A similarity: {fmt(sa)}'
        f' = knowledge utility: {fmt(ku)}) {query_seq}{query_mode}'
    )
    return line

### Knowledge Explorer screen ###
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
    _aj = {}
    if _af:
        try:
            _aj = dmu.read_json_file(_af, agent_folder_path) or {}
        except Exception:
            _aj = {}
    _el = [e for e in _aj.get("ENGINE", {}).get("LLM", {}).keys() if e != "DEFAULT"]
    _eng = _c2.selectbox(f"{label} Engine:", _el, key=f"{kp}_expl_engine") if _el else None
    # If this agent has personas, allow selecting one (optional; "(none)" means no override)
    _persona = None
    _pfiles = _aj.get("PERSONA_FILES")
    if _af and _pfiles:
        try:
            _plist = dap.load_personas(template_agent=_af, persona_files=_pfiles, source=_aj.get("PERSONA_SOURCE"))
        except Exception:
            _plist = []
        if _plist:
            _popts = ["(none)"] + [f"{p.get('persona_id')}: {p.get('name')}" for p in _plist]
            _psel = st.selectbox(f"{label} Persona:", _popts, index=0, key=f"{kp}_expl_persona")
            if _psel != "(none)":
                _pid = _psel.split(":", 1)[0].strip()
                _persona = next((p for p in _plist if str(p.get("persona_id")) == _pid), None)
    return _af, _ag, _eng, _persona

def _explanation_block(state_base, template_name, fallback_agent, ctx_builder, label, kp, postprocess=None):
    """Explanation: pick agent + engine, run multiple times, show one via a dropdown. Returns the currently displayed text."""
    _hk = f"{state_base}_history"
    _sk = f"{state_base}_sel"
    st.markdown(f"**{label} explanation:**")
    _af, _ag, _eng, _persona = _agent_engine_selectors(label, kp)
    if st.button(f"Explain {label}", key=f"{kp}_expl_run"):
        _ctx = ctx_builder()
        if not _ctx:
            st.warning("No data to explain. Please run the analysis first.")
        else:
            _use_af = _af or fallback_agent
            with st.spinner(f"Explaining {label}..."):
                try:
                    _agent = dma.DigiM_Agent(_use_af, persona=_persona) if _persona else dma.DigiM_Agent(_use_af)
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
                        "persona": (_persona.get("name") if _persona else ""),
                    }
                    _h = (st.session_state.get(_hk) or []) + [_entry]
                    st.session_state[_hk] = _h
                    st.session_state[_sk] = len(_h) - 1
                except Exception as e:
                    st.error(f"{label} explanation error: {e}")
    _h = st.session_state.get(_hk) or []
    if not _h:
        return ""
    _sel = st.session_state.get(_sk)
    if _sel is None or _sel >= len(_h) or _sel < 0:
        _sel = len(_h) - 1
    _sel = st.selectbox(
        f"{label} explanation history:", list(range(len(_h))), index=_sel,
        format_func=lambda i: f"[{i+1}/{len(_h)}] {_h[i]['timestamp']} / {_h[i]['agent']}{('・'+_h[i]['persona']) if _h[i].get('persona') else ''} / {_h[i]['engine']}",
        key=f"{kp}_expl_sel")
    st.session_state[_sk] = _sel
    st.markdown(_h[_sel]["response"])
    return _h[_sel]["response"]


def _knowledge_explorer():
    import fnmatch

    _ANALYTICS_BASE = "user/common/analytics/knowledge_explorer/"

    # All session_state keys for Knowledge Explorer
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
        # Added by the (Overall/Trend/Topic) rebuild. Existing keys must not be renamed (pkl-restore compatibility)
        "_rag_cluster_expl_history", "_rag_cluster_expl_sel",
        "_rag_trend", "_rag_trend_expl_history", "_rag_trend_expl_sel",
        "_rag_topic", "_rag_topic_expl_history", "_rag_topic_expl_sel",
    ]

    def _save_analysis_session(collection_name):
        """Save all Knowledge Explorer state to a folder."""
        import pickle
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _folder = os.path.join(_ANALYTICS_BASE, f"analytics{_ts}")
        os.makedirs(_folder, exist_ok=True)

        # Metadata
        _meta = {
            "collection": collection_name,
            "timestamp": _ts,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        dmu.save_json_file(_meta, os.path.join(_folder, "meta.json"))

        # Save all state as one pickle
        _state = {}
        for _k in _RAG_STATE_KEYS:
            if _k in st.session_state:
                _state[_k] = st.session_state[_k]
        with open(os.path.join(_folder, "state.pkl"), "wb") as f:
            pickle.dump(_state, f)

        # Keep the analytics folder path in session_state
        st.session_state._rag_analytics_folder = _folder

        # If a report exists, also save it as .md (human-readable form)
        if st.session_state.get("_rag_report"):
            dmu.save_text_file(st.session_state._rag_report, os.path.join(_folder, "report.md"))

        return _folder

    def _load_analysis_session(folder_path):
        """Restore the saved full state into session_state."""
        import pickle
        _meta_path = os.path.join(folder_path, "meta.json")
        if not os.path.exists(_meta_path):
            return None
        _meta = dmu.read_json_file(_meta_path)

        # First clear all RAG keys
        for _k in _RAG_STATE_KEYS:
            if _k in st.session_state:
                del st.session_state[_k]

        # Restore from pickle
        _pkl_path = os.path.join(folder_path, "state.pkl")
        if os.path.exists(_pkl_path):
            with open(_pkl_path, "rb") as f:
                _state = pickle.load(f)
            for _k, _v in _state.items():
                st.session_state[_k] = _v

        # Loaded-flag
        st.session_state._rag_searched = True
        st.session_state._rag_loaded_collection = _meta.get("collection", "")

        return _meta

    def _list_saved_sessions():
        """Return the list of saved analysis sessions."""
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
        """Shared Ask-Agent UI: exec settings + question input + DigiMatsuExecute run. Result is stored in session_state."""
        st.markdown("---")
        st.subheader("Ask Agent")
        _llm_agent_list = st.session_state.agent_list
        _llm_agent_idx = 0
        if st.session_state.get("agent_id") in _llm_agent_list:
            _llm_agent_idx = _llm_agent_list.index(st.session_state.agent_id)
        _llm_agent = st.selectbox("Agent:", _llm_agent_list, index=_llm_agent_idx, key=f"{key_prefix}_llm_agent")

        # Execution settings
        _ask_exp = st.expander("Exec Settings")
        with _ask_exp:
            _ask_c1, _ask_c2, _ask_c3, _ask_c4 = st.columns(4)
            _ask_web = _ask_c1.checkbox("Web Search", value=False, key=f"{key_prefix}_ask_web")
            _ask_private = _ask_c2.checkbox("Private Mode", value=st.session_state.get("private_mode", True), key=f"{key_prefix}_ask_private")
            _ask_thinking = _ask_c3.checkbox("Thinking Mode", value=False, key=f"{key_prefix}_ask_thinking")
            _ask_book = _ask_c4.checkbox("Use Books", value=False, key=f"{key_prefix}_ask_book")

        _llm_query = st.text_area("Question:", placeholder="e.g. Describe the characteristics per category", height=100, key=f"{key_prefix}_llm_query")

        if _llm_query and st.button("Ask", key=f"{key_prefix}_llm_ask"):
            _agent_file = next((a["FILE"] for a in st.session_state.agents if a["AGENT"] == _llm_agent), None)
            if _agent_file:
                _user_input = f"{context_text}\n\n[Question]\n{_llm_query}"
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
                # Create the session inside the analytics folder
                _analytics_folder = st.session_state.get("_rag_analytics_folder", "")
                if not _analytics_folder:
                    _analytics_folder = os.path.join(_ANALYTICS_BASE, f"analytics{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                    st.session_state._rag_analytics_folder = _analytics_folder
                _session_base = os.path.join(_analytics_folder, _session_id)
                _tmp_session = dms.DigiMSession(_session_id, "Knowledge Explorer", base_path=_session_base)
                _tmp_session.save_status("LOCKED")
                _exec["_SESSION_BASE_PATH"] = _session_base

                with st.spinner("Running the agent..."):
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
                        # Latest result (for Detail/Analytics)
                        st.session_state[f"_{key_prefix}_ask_result"] = _new_result
                        # Append to chat history
                        if f"_{key_prefix}_ask_history" not in st.session_state:
                            st.session_state[f"_{key_prefix}_ask_history"] = []
                        st.session_state[f"_{key_prefix}_ask_history"].append(_new_result)
                    except Exception as e:
                        import traceback
                        st.error(f"Agent execution error: {type(e).__name__}: {e}")
                        st.code(traceback.format_exc())
                    finally:
                        _tmp_session.save_status("UNLOCKED")

    def _show_ask_result(key_prefix="rag"):
        """Display Ask-Agent chat history + latest result Detail/Analytics."""
        _history = st.session_state.get(f"_{key_prefix}_ask_history", [])
        _result = st.session_state.get(f"_{key_prefix}_ask_result")
        if not _history and not _result:
            return None

        # Show past chat history
        if len(_history) > 1:
            for _h in _history[:-1]:
                with st.chat_message("user"):
                    st.markdown(f"**[{_h.get('timestamp','')}] {_h.get('agent_name','')}**")
                    st.markdown(_h.get("query", ""))
                with st.chat_message("assistant"):
                    st.markdown(_h["response"])

        # Latest answer
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
                st.caption(f"Failed to fetch Detail: {e}")

        # Analytics Results (shown only when session data has been saved)
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
                                _run_bg_task("compare", f"Running comparative analysis (Knowledge Explorer)", _run_cmp)
                                st.rerun()

                    # Compare results display
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
                                # Save into the analytics per-session folder (create one temporarily if missing)
                                _ak_folder = st.session_state.get("_rag_analytics_folder", "")
                                if not _ak_folder:
                                    _ak_folder = os.path.join(_ANALYTICS_BASE, f"analytics{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                                    st.session_state._rag_analytics_folder = _ak_folder
                                os.makedirs(_ak_folder, exist_ok=True)
                                def _run_ak():
                                    _r = _dmva_ak.analytics_knowledge(_agent_file, _ref_ts, _ak_title, _ak_refs, _ak_folder, _ak_mode, _ak_dim)
                                    st.session_state[f"_{key_prefix}_ak_result"] = _r
                                _run_bg_task("knowledge", "Analyzing knowledge utility (Knowledge Explorer)", _run_ak)
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
                st.caption(f"Failed to fetch Analytics: {e}")

        return _result["response"]

    st.subheader("Knowledge Explorer")

    # Handle the load request from the sidebar
    if st.session_state.get("_rag_load_folder"):
        _load_path = st.session_state._rag_load_folder
        st.session_state._rag_load_folder = None
        _loaded = _load_analysis_session(_load_path)
        if _loaded:
            st.session_state._rag_searched = True
            st.session_state._rag_loaded_collection = _loaded.get("collection", "")
            st.session_state._rag_loaded_type = _loaded.get("data_type", "ChromaDB")
            st.info(f"Loaded analysis session: {_loaded.get('created_at', '')} - {_loaded.get('collection', '')}")

    # Extract data sources from the selected agent's KNOWLEDGE/BOOK
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

    # Filter the data-source list by the agent's settings
    _all_chroma = dmc.get_rag_list()
    _all_page_index = dmc.get_page_index_list()
    _chroma_list = [c for c in _all_chroma if c in _agent_db_names] if _agent_db_names else _all_chroma
    _page_index_names = [p for p in _all_page_index.keys() if p in _agent_pi_names] if _agent_pi_names else list(_all_page_index.keys())
    _page_index_dict = {k: v for k, v in _all_page_index.items() if k in _page_index_names} if _agent_pi_names else _all_page_index

    # Toggle radio-button display based on whether both data-source types are present
    _has_vectordb = bool(_chroma_list)
    _has_pageindex = bool(_page_index_names)
    _source_options = []
    if _has_vectordb:
        _source_options.append("Collection (VectorDB)")
    if _has_pageindex:
        _source_options.append("PageIndex")
    if not _source_options:
        st.info("The selected agent has no RAG data configured")
        return

    _source_type = st.radio("Data Source:", _source_options, horizontal=True, key="rag_source_type") if len(_source_options) > 1 else _source_options[0]
    _is_page_index = (_source_type == "PageIndex")

    if _is_page_index:
        _selected_pi = st.selectbox("PageIndex:", _page_index_names, key="rag_pi_select")
        _selected_list = [f"[PageIndex] {_selected_pi}"]
    else:
        _selected_list = st.multiselect("Collection:", _chroma_list, default=[], key="rag_collection_chromadb")

    # Sort and stringify the selection (used as cache key). Persona selection is also part of the key so it re-fetches on change
    _persona_sig = str(sorted(st.session_state.get("selected_persona_ids") or []))
    _selected_key = str(sorted(_selected_list)) + "|persona:" + _persona_sig

    # Reset cache and search state when the Collection changes
    # (skipped when nothing is selected, a saved session is loaded, or a background task is running)
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

    # If a loaded session exists, proceed even without a Collection selection
    if not _selected_list:
        _loaded_col = st.session_state.get("_rag_loaded_collection", "")
        if _loaded_col and st.session_state.get("_rag_cached_data") is not None:
            _selected_list = [_loaded_col] if isinstance(_loaded_col, str) else _loaded_col
            _selected_list = [s for s in ((_loaded_col.split(", ") if ", " in _loaded_col else [_loaded_col])) if s]
        else:
            return

    # Display name for the selection (used by reports etc.)
    _selected = ", ".join(_selected_list)

    # ===== PageIndex-only screen =====
    if _is_page_index:
        _pi_name = _selected_list[0].replace("[PageIndex] ", "")
        _pi_pages = _page_index_dict.get(_pi_name, [])
        _data_type = "PageIndex"

        if not _pi_pages:
            st.warning("There are 0 page entries.")
            return

        df = pd.DataFrame(_pi_pages)
        total_count = len(df)

        # Tree-structure display
        st.subheader("Page Tree")
        _categories = {}
        for p in _pi_pages:
            cat = p.get("category", "Uncategorized")
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

        # Set of IDs to highlight (set after sensitivity analysis)
        _highlight_ids = set()
        _pi_sens = st.session_state.get("_rag_pi_sensitivity")
        if _pi_sens and _pi_sens.get("pi_name") == _pi_name:
            _highlight_ids = set(_pi_sens.get("selected_ids", []))

        y_pos = len(_pi_pages) + len(_categories) - 1
        for cat, pages in _categories.items():
            # Category header
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

        # Data list
        _list_cols = [c for c in df.columns if c not in ("sort_order",)]
        st.dataframe(df[_list_cols], hide_index=True, use_container_width=True, height=300)

        # PageIndex sensitivity analysis
        st.markdown("---")
        st.subheader("Page Sensitivity")
        _pi_query = st.text_input("Query:", placeholder="Enter a keyword or sentence to simulate page selection", key="rag_pi_sens_query")
        _pi_max = st.slider("Max Pages:", min_value=1, max_value=min(10, total_count), value=min(5, total_count), key="rag_pi_max")

        if _pi_query and st.button("Analyze", key="rag_pi_sens_run"):
            # Simulate page selection using the PageIndex search agent
            import DigiM_Tool as _dmt_pi
            with st.spinner("Simulating page selection..."):
                try:
                    _exec_info = {"SERVICE_INFO": st.session_state.web_service, "USER_INFO": st.session_state.web_user}
                    _support_agent = "agent_59PageIndexSearch.json"
                    _sel_ids = _dmt_pi.page_index_search(_exec_info, _support_agent, _pi_query, _pi_pages, _pi_max)
                    st.session_state._rag_pi_sensitivity = {
                        "pi_name": _pi_name,
                        "query": _pi_query,
                        "selected_ids": _sel_ids,
                    }
                    st.rerun()  # Re-render the tree with highlights
                except Exception as e:
                    st.warning(f"Error simulating page selection: {e}")

        # Sensitivity analysis result display
        if _pi_sens and _pi_sens.get("pi_name") == _pi_name:
            st.caption(f"Query: **{_pi_sens['query']}** -> Selected pages: **{', '.join(_pi_sens['selected_ids'])}**")
            _sel_pages = [p for p in _pi_pages if p["id"] in _pi_sens["selected_ids"]]
            if _sel_pages:
                st.dataframe(pd.DataFrame(_sel_pages), hide_index=True, use_container_width=True)

        # Ask Agent (for PageIndex)
        _pi_context = f"Answer the question using the following PageIndex data and analysis results.\n\nPageIndex: {_pi_name} ({total_count} pages)\n\nPage list:\n"
        for p in _pi_pages:
            _pi_context += f"- [{p['id']}] {p.get('title','')} ({p.get('category','')}) : {p.get('summary','')}\n"
        if _pi_sens and _pi_sens.get("pi_name") == _pi_name:
            _pi_context += f"\nSensitivity analysis result (Query: {_pi_sens['query']}):\nSelected pages: {', '.join(_pi_sens['selected_ids'])}\n"
        _ask_agent_ui(_pi_context, key_prefix="rag_pi")
        _show_ask_result(key_prefix="rag_pi")

        # Export Report (for PageIndex)
        st.markdown("---")
        st.subheader("Export Report")
        if st.button("Generate Report", key="rag_pi_gen_report"):
            _now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            _report = f"# Knowledge Explorer {_now}\n\n"
            _report += f"**Analysis date:** {_now}\n\n"
            _report += f"**Page count:** {total_count}\n\n"
            _report += "## Page Tree\n\n"
            for cat, pages in _categories.items():
                _report += f"### {cat}\n"
                for p in pages:
                    _report += f"- [{p['id']}] {p.get('title', '')}: {p.get('summary', '')}\n"
                _report += "\n"
            _pi_sens = st.session_state.get("_rag_pi_sensitivity")
            if _pi_sens and _pi_sens.get("pi_name") == _pi_name:
                _report += f"## Page Sensitivity\n\nQuery: {_pi_sens['query']}\n\n"
                _report += f"Selected pages: {', '.join(_pi_sens['selected_ids'])}\n\n"
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
                st.success(f"Generated report and saved the session: {_saved_path}")
            except Exception as e:
                st.success("Report generated")
                st.warning(f"Failed to save the session: {e}")

        if st.session_state.get("_rag_report"):
            _report_name = f"Knowledge_Explorer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            st.download_button("Download (.md)", data=st.session_state._rag_report.encode("utf-8"),
                              file_name=f"{_report_name}.md", mime="text/markdown", key="rag_pi_dl_md")

        return  # PageIndex ends here (skip the ChromaDB code below)

    # ===== ChromaDB screen (Overall / Trend / Topic / Ask Agent layout) =====
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
    _FAR_FUTURE = datetime(2099, 12, 31).date()  # Upper cap for allowing future-dated inputs

    # Collection (DATA_NAME) -> RAG_NAME map (from the agent's KNOWLEDGE/BOOK)
    _col_to_rag_name = {}
    for _k in _agent_data.get("KNOWLEDGE", []) + _agent_data.get("BOOK", []):
        _rag_name_v = _k.get("RAG_NAME", "")
        if not _rag_name_v:
            continue
        for _d in _k.get("DATA", []):
            _dn = _d.get("DATA_NAME", "")
            if _dn:
                _col_to_rag_name[_dn] = _rag_name_v

    # Fetch data (use cache if present)
    # Compose the union of define_code from the selected personas (used by per-DATA FILTER in KNOWLEDGE)
    _persona_define_code = {}
    try:
        _sel_pids = list(st.session_state.get("selected_persona_ids") or [])
        if _sel_pids and st.session_state.get("selected_org"):
            _cands = dap.find_personas_by_org(
                st.session_state.selected_org,
                template_agent=st.session_state.get("agent_file"),
                persona_files=_agent_data.get("PERSONA_FILES") or None,
                source=_agent_data.get("PERSONA_SOURCE"),
            )
            _pid_map = {p["persona_id"]: p for p in _cands}
            for _pid in _sel_pids:
                _p = _pid_map.get(_pid)
                if not _p:
                    continue
                for _ck, _cv in (_p.get("define_code") or {}).items():
                    _vals = _cv if isinstance(_cv, list) else [_cv]
                    _cur = _persona_define_code.setdefault(_ck, [])
                    for _x in _vals:
                        if _x not in ("", None) and _x not in _cur:
                            _cur.append(_x)
    except Exception:
        _persona_define_code = {}

    # Collection (DATA_NAME) -> DATA entry (with FILTER) map
    _data_entry_map = {}
    for _kn_entry in _agent_data.get("KNOWLEDGE", []) + _agent_data.get("BOOK", []):
        for _dt_entry in _kn_entry.get("DATA", []):
            if _dt_entry.get("DATA_NAME"):
                _data_entry_map[_dt_entry["DATA_NAME"]] = _dt_entry
    _exec_info_ke = {"SERVICE_INFO": st.session_state.web_service, "USER_INFO": st.session_state.web_user}

    def _persona_where(_collection):
        """When a persona is selected, return the filtering where dict from that collection's DATA-FILTER (None if absent)."""
        if not _persona_define_code:
            return None
        _de = _data_entry_map.get(_collection)
        if not _de or "FILTER" not in _de:
            return None
        try:
            _wl = dmc._build_where_limitation(_de, _exec_info_ke, _persona_define_code)
        except Exception:
            return None
        if not _wl:
            return None
        return _wl[0] if len(_wl) == 1 else {"$and": _wl}

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
            _col_data = dmc.get_rag_collection_data(_sel, where=_persona_where(_sel))
            _rn = _col_to_rag_name.get(_sel, _sel)
            for d in _col_data:
                d["_source"] = _sel
                d["rag_name"] = _rn
            _all_raw_data.extend(_col_data)
        if not _all_raw_data:
            st.warning("There are 0 data entries")
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

    # Cache df_display / filterable (avoids re-running list->str conversion every time; better UX)
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
        """Convert a fig to PNG bytes and close it (built once during compute to avoid re-render cost)."""
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

    def _scatter_png(_dfx, _color_col, _marker_col, _size_mode, _title, _period_from=None, _period_to=None):
        _dot = None
        if _size_mode == "Newer=Larger" and "create_date" in _dfx.columns:
            _d = pd.to_datetime(_dfx["create_date"], errors="coerce")
            if _d.notna().any():
                _mn = _d.min().timestamp()
                _mx = _d.max().timestamp()
                _rg = _mx - _mn if _mx > _mn else 1
                _dot = _d.apply(lambda x: 10 + 190 * ((x.timestamp() - _mn) / _rg) if pd.notna(x) else 10).values
        elif _size_mode == "Highlight Period" and "create_date" in _dfx.columns and _period_from is not None and _period_to is not None:
            _d = pd.to_datetime(_dfx["create_date"], errors="coerce")
            _in = (_d >= pd.Timestamp(_period_from)) & (_d <= pd.Timestamp(_period_to) + pd.Timedelta(days=1))
            _dot = _in.apply(lambda b: 200 if bool(b) else 20).values
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
        """Pass _cmap_fixed to plot with fixed colors (Total-based) so RAG NAMEs share colors."""
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

    def _extra_filter_ui(_base_df, kp, with_period=True):
        """Additional filter within the Overall scope: RAG NAME / Collection / period. Returns (df_sub, description text)."""
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
                _pv = _c3.date_input("Period From/To:", value=(_mn, _mx), min_value=_mn, max_value=_FAR_FUTURE, key=f"{kp}_f_period")
                if isinstance(_pv, (list, tuple)) and len(_pv) == 2:
                    _pf, _pt = _pv
                    _dd = pd.to_datetime(_sub["create_date"], errors="coerce")
                    _sub = _sub[(_dd >= pd.Timestamp(_pf)) & (_dd <= pd.Timestamp(_pt) + pd.Timedelta(days=1))]
                    _desc.append(f"{_pf}〜{_pt}")
        return _sub, (" / ".join(_desc) if _desc else "no filter")

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
    _search_text = _fc3.text_input("Text Search:", value="", placeholder="Supports wildcard *", key="rag_search_text")

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
            _date_from = _dc1.date_input("Date From:", value=_mind, min_value=_mind, max_value=_FAR_FUTURE, key="rag_date_from")
            _date_to = _dc2.date_input("Date To:", value=_maxd, min_value=_mind, max_value=_FAR_FUTURE, key="rag_date_to")

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
    _size_mode = _s5.radio("Dot Size:", ["Uniform", "Newer=Larger", "Highlight Period"], index=0, horizontal=True, key="rag_dot_size")
    _do_search = _s6.button("Search & Plot", key="rag_do_search", type="primary")
    # Sub-period for Highlight Period mode (specified within Date From-To). Only matching dots are drawn larger
    _hl_from = None
    _hl_to = None
    if _size_mode == "Highlight Period" and _has_date and _date_from is not None and _date_to is not None:
        _h1, _h2 = st.columns(2)
        _hl_from = _h1.date_input("Highlight Period From:", value=_date_from, min_value=_date_from, max_value=_date_to, key="rag_hl_from")
        _hl_to = _h2.date_input("Highlight Period To:", value=_date_to, min_value=_date_from, max_value=_date_to, key="rag_hl_to")

    if _do_search:
        st.session_state._rag_searched = True
        st.session_state._rag_scatter_cache = None
    if not st.session_state.get("_rag_searched", False):
        st.caption(f"**{_data_type}** | Total: **{total_count}** entries | Set conditions and press **Search & Plot** (no conditions = all entries)")
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
    st.caption(f"**{_data_type}** | Total: **{total_count}** entries | Filtered: **{filtered_count}** entries")

    if _do_search and _has_vectors and filtered_count >= 3:
        _dfs = df[df["id"].isin(df_filtered["id"])].copy()
        with st.spinner("Reducing dimensions + generating scatter plot..."):
            try:
                _dfr, _dinfo = dmva.reduce_dimensions(_dfs, method=_dim_method, params=_dim_params)
                if _marker_col != "(none)" and _marker_col not in _dfr.columns and _marker_col in _dfs.columns:
                    _dfr[_marker_col] = _dfr["id"].map(_dfs.set_index("id")[_marker_col])
                _ttl = f"{_dim_method} - {_selected} ({filtered_count} entries)\n{_dinfo}"
                _png_total = _scatter_png(_dfr, _color_col, _marker_col, _size_mode, _ttl, _hl_from, _hl_to)
                _png_rag = {}
                for _rn in _rag_list(_dfr):
                    _sr = _dfr[_dfr["rag_name"].astype(str) == _rn]
                    if len(_sr) >= 1:
                        _png_rag[_rn] = _scatter_png(_sr, _color_col, _marker_col, _size_mode, f"{_dim_method} - {_rn} ({len(_sr)} entries)", _hl_from, _hl_to)
                st.session_state._rag_scatter_cache = {
                    "df_reduced": _dfr, "dim_info": _dinfo, "dim_method": _dim_method,
                    "color_col": _color_col, "marker_col": _marker_col, "size_mode": _size_mode,
                    "hl_from": _hl_from, "hl_to": _hl_to,
                    "selected": _selected, "filtered_count": filtered_count,
                    "png_total": _png_total, "png_rag": _png_rag,
                }
            except Exception as e:
                st.warning(f"Failed to generate scatter plot: {e}")
                st.session_state._rag_scatter_cache = None

    _scc = st.session_state.get("_rag_scatter_cache")
    _has_scatter = bool(_scc and _scc.get("selected") == _selected)

    if _has_scatter:
        st.markdown("**Scatter Plot (Total):**")
        st.image(_scc["png_total"])
        if _scc.get("png_rag"):
            st.markdown("**Scatter Plot (per RAG NAME):**")
            for _rn, _pb in _scc["png_rag"].items():
                st.image(_pb)
        _dfr = _scc["df_reduced"]
        _df_show = _order_cols(df_filtered.merge(_dfr.set_index("id")[["X1", "X2"]], left_on="id", right_index=True, how="left"))
    else:
        if _has_vectors and filtered_count < 3:
            st.info("Scatter plot requires at least 3 rows after filtering")
        elif not _has_vectors:
            st.info("Vector data is unavailable; scatter plot was skipped")
        _df_show = df_filtered

    st.markdown("**Data list (coordinates are based on Total):**")
    st.dataframe(_df_show, hide_index=True, use_container_width=True, height=380)
    st.download_button("CSV Download", data=_df_show.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"rag_{_selected}.csv", mime="text/csv", key="rag_csv_dl")

    # ---- Clustering (apply the Total-defined clusters to each RAG NAME) ----
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
        # Target period for clustering (further filter within Overall's Date From-To)
        _cl_period_from = None
        _cl_period_to = None
        if _has_date and _date_from is not None and _date_to is not None:
            _cp1, _cp2 = st.columns(2)
            _cl_period_from = _cp1.date_input("Cluster Period From:", value=_date_from, min_value=_date_from, max_value=_date_to, key="rag_cl_period_from")
            _cl_period_to = _cp2.date_input("Cluster Period To:", value=_date_to, min_value=_date_from, max_value=_date_to, key="rag_cl_period_to")

        if st.button("Run Clustering", key="rag_run_cluster"):
            _dfr = _scc["df_reduced"]
            _scope = _dfr[_dfr["id"].isin(df_filtered["id"])].copy()
            if _cl_period_from is not None and _cl_period_to is not None and "create_date" in _scope.columns:
                _dd = pd.to_datetime(_scope["create_date"], errors="coerce")
                _scope = _scope[(_dd >= pd.Timestamp(_cl_period_from)) & (_dd <= pd.Timestamp(_cl_period_to) + pd.Timedelta(days=1))]
            with st.spinner("Clustering..."):
                try:
                    # Cluster only on Total; each RAG NAME inherits Total's cluster assignment
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
                            _png_by[_rn] = _cluster_png(_sub, None, f"Clustering [RAG: {_rn}] (Total-based colors)", _cmap_fixed)
                            _rag_dist[_rn] = {str(int(k)): int(v) for k, v in
                                              _sub["Cluster"].value_counts().sort_index().items()}
                    st.session_state._rag_cluster_cache = {
                        "results": True, "selected": _selected, "method": _cl_method, "info": _info,
                        "total_df": _dft[["id", "Cluster", "X1", "X2"]].copy(),
                        "total_summary": dmva.build_cluster_summary(_dft),
                        "labels": sorted([int(c) for c in _dft["Cluster"].unique()]),
                        "rag_dist": _rag_dist, "png_total": _png_t, "png_by_rag": _png_by,
                        "period_from": _cl_period_from, "period_to": _cl_period_to,
                        "scope_count": int(len(_scope)),
                    }
                    st.session_state._rag_cluster_names = None
                except Exception as e:
                    st.warning(f"Clustering error: {e}")
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
                st.markdown("**Per RAG NAME (Total-defined cluster colors applied, 2 columns):**")
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
                _txt = ("Clustering result for RAG data \"" + _selected + "\".\n"
                        f"[Total clustering: {_cc.get('info','')}]\n{_cc.get('total_summary','')}\n")
                _rd = _cc.get("rag_dist") or {}
                if _rd:
                    _txt += "\n[Clusters contained per RAG_NAME (cluster number = count)]\n"
                    for _rn, _dist in _rd.items():
                        _txt += f"  {_rn}: " + ", ".join(f"C{k}={v}" for k, v in _dist.items()) + "\n"
                _ids = [c for c in (_cc.get("labels") or []) if c >= 0]
                _txt += (f"\nTarget cluster numbers: {_ids}\n"
                         "まずTotalで定義された各クラスターの特徴を解説し、"
                         "続いて各RAG_NAMEがどのクラスターを含むかを踏まえて解説してください。")  # the trailing JP block is the LLM prompt content (kept JP)
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
        st.info("Trend is unavailable because create_date is missing")
    else:
        _df_trend, _trend_desc = _extra_filter_ui(df_filtered, "rag_trend")
        st.caption(f"Target: {_trend_desc} | {len(_df_trend)} entries")
        _t1, _t2, _t3 = st.columns([1, 1, 1])
        _tr_period = _t1.selectbox("Period:", ["month", "quarter", "year"], index=0, key="rag_trend_period")
        _tr_topn = _t2.slider("Keywords/period:", min_value=3, max_value=20, value=7, key="rag_trend_topn")
        _tr_cat_opts = _filterable_cols or ["(none)"]
        _tr_cat_def = _tr_cat_opts.index("category") if "category" in _tr_cat_opts else 0
        _tr_cat_col = _t3.selectbox("Category Column (bar-chart breakdown only):", _tr_cat_opts, index=_tr_cat_def, key="rag_trend_cat")

        if st.button("Analyze Trend", key="rag_run_trend"):
            with st.spinner("Running Trend analysis..."):
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
                        # Bar chart (composition over time)
                        _bar_png = None
                        if _cp is not None and not _cp.empty:
                            _cols = [_cat_color_map.get(c) for c in _cp.columns]
                            figb, axb = plt.subplots(figsize=(11, 4))
                            _cp.plot(kind="bar", stacked=True, ax=axb,
                                     color=_cols if all(_cols) else None, alpha=0.85)
                            axb.set_title(f"{_tr_cat_col} composition over time ({_tr_period}) - {_gn}")
                            axb.set_ylabel("Count")
                            axb.legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=7)
                            plt.xticks(rotation=45, ha="right")
                            plt.tight_layout()
                            _bar_png = _png(figb)
                        # Word cloud (Period descending)
                        _wc_list = []
                        for _p in sorted(_per, reverse=True):
                            _fr = _wcmap.get(_p)
                            if not _fr:
                                continue
                            _wf = dmva.make_wordcloud_figure(_fr, title=str(_p), width=320, height=220)
                            if _wf is not None:
                                _wc_list.append((str(_p), _png(_wf)))
                        # Keyword table (Period descending)
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
                    st.warning(f"Trend analysis error: {e}")

        _tr = st.session_state.get("_rag_trend")
        if _tr and _tr.get("groups"):
            if _tr.get("no_period"):
                st.warning("RAG data without period info (create_date): "
                           + ", ".join(f"{k}: {v}" for k, v in _tr["no_period"].items())
                           + " (no time-related info)")
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

            # Optional focus period for the Trend explanation: when set, focuses the narrative on that sub-period
            _tr_focus_on = st.checkbox("Specify a focus period (off = full-range narrative + future-topic estimation)", value=False, key="rag_trend_focus_on")
            _tr_focus_from = None
            _tr_focus_to = None
            if _tr_focus_on and _has_date and _date_from is not None and _date_to is not None:
                _fc1, _fc2 = st.columns(2)
                _tr_focus_from = _fc1.date_input("Focus Period From:", value=_date_from, min_value=_date_from, max_value=_FAR_FUTURE, key="rag_trend_focus_from")
                _tr_focus_to = _fc2.date_input("Focus Period To:", value=_date_to, min_value=_date_from, max_value=_FAR_FUTURE, key="rag_trend_focus_to")

            def _tr_ctx():
                _t = st.session_state.get("_rag_trend")
                if not _t or not _t.get("groups"):
                    return ""
                _x = f"Per-period keyword aggregation for RAG data \"{_selected}\" (Total and per RAG_NAME).\n"
                for _g in _t["groups"]:
                    if _g.get("summary"):
                        _x += f"\n[{_g['name']}]\n{_g['summary']}\n"
                if _tr_focus_from is not None and _tr_focus_to is not None:
                    _x += (f"\n【解説の対象期間】 {_tr_focus_from} - {_tr_focus_to}\n"
                           "上記の全体期間データを背景としつつ、特に「解説の対象期間」に該当する期間の"
                           "特徴・話題・変化を中心に【概要】を記述してください。"
                           "【今後のトピック推定】は対象期間以降の見通しとして提示してください。\n")  # LLM prompt content (kept JP)
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
        st.info("Please run Search & Plot (scatter generation) in Overall first")
    else:
        _df_topic, _topic_desc = _extra_filter_ui(df_filtered, "rag_topic")
        st.caption(f"Target: {_topic_desc} | {len(_df_topic)} entries")
        _topic_query = st.text_input("Query:", placeholder="Enter a keyword or sentence to analyze knowledge response", key="rag_topic_query")
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
                                    min_value=_bmin, max_value=_FAR_FUTURE, key="rag_topic_bonus_period")
                if isinstance(_bv, (list, tuple)) and len(_bv) == 2:
                    _tp_bf, _tp_bt = _bv

        if _topic_query and st.button("Analyze Topic", key="rag_run_topic"):
            _dfr = _scc["df_reduced"]
            _dfsens = df[df["id"].isin(_df_topic["id"])].copy()
            _dfsens = _dfsens.merge(_dfr.set_index("id")[["X1", "X2"]], left_on="id", right_index=True, how="left")
            with st.spinner("Computing similarity..."):
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
                        # Count (bars) + score (line: sum/avg/max) by Period
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
                            ax2.set_ylabel("Score (smaller = stronger relevance)")
                            _l1, _b1 = axc.get_legend_handles_labels()
                            _l2, _b2 = ax2.get_legend_handles_labels()
                            axc.legend(_l1 + _l2, _b1 + _b2, loc="upper left", bbox_to_anchor=(1.07, 1), fontsize=8)
                            axc.set_title(f"Count & similarity score ({_tp_period}) - {_gn}")
                            plt.tight_layout()
                            _chart_png = _png(figc)
                        # Scatter: full population in gray + selected (shaded by score)
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
                    st.warning(f"Topic analysis error: {e}")

        _tp = st.session_state.get("_rag_topic")
        if _tp and _tp.get("selected") == _selected and _tp.get("groups"):
            st.caption(f"Query: **{_tp['query']}** | {_tp.get('desc','')}")
            for _g in _tp["groups"]:
                st.markdown(f"##### [{_g['name']}] (top {len(_g['rows'])} of {_g['n']})")
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
                _x = (f"Knowledge-response (similarity) analysis for query \"{_t['query']}\".\n"
                      "Total全体と各RAG_NAMEそれぞれについて、この入力に反応しそうな知識の特徴・傾向を"
                      "分かりやすく語ってください。\n")  # LLM prompt content (kept JP)
                for _g in _t["groups"]:
                    _x += f"\n\n[{_g['name']}] top {len(_g['rows'])}:\n"
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
    _summary_lines = [f"以下のRAGデータと分析結果を踏まえて質問に回答してください。\n\nRAGデータ: {_selected} (filtered: {filtered_count} / total: {total_count})"]  # LLM prompt prefix (kept JP)
    _df_for_llm = df_filtered.drop(columns=[c for c in df_filtered.columns if "vector" in c], errors="ignore")
    for col in _filterable_cols[:5]:
        if col in _df_for_llm.columns:
            _vc = _df_for_llm[col].value_counts().head(10).to_dict()
            if _vc:
                _summary_lines.append(f"\n[Distribution of {col}]\n" + "\n".join(f"  {k}: {v}" for k, v in _vc.items()))
    _sample_n = min(30, len(_df_for_llm))
    _summary_lines.append(f"\n[Data (first {_sample_n} rows)]\n{_df_for_llm.head(_sample_n).to_csv(index=False)}")
    if st.session_state.get("_rag_cluster_explanation"):
        _summary_lines.append(f"\n[Clustering explanation]\n{st.session_state._rag_cluster_explanation[:600]}")
    if st.session_state.get("_rag_temporal_explanation"):
        _summary_lines.append(f"\n[Trend explanation]\n{st.session_state._rag_temporal_explanation[:600]}")
    if st.session_state.get("_rag_sensitivity_explanation"):
        _summary_lines.append(f"\n[Topic explanation]\n{st.session_state._rag_sensitivity_explanation[:600]}")
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
        _report += f"**Target data:** {_selected}\n\n"
        _report += f"**Row count:** filtered {filtered_count} / total {total_count}\n\n"

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
            _report += f"### Clustering explanation ({_ch[_ci]['timestamp']} / {_ch[_ci]['agent']})\n\n{_ch[_ci]['response']}\n\n"
        _trr = st.session_state.get("_rag_trend")
        if _trr and _trr.get("groups"):
            _report += "## Trend\n\n"
            if _trr.get("no_period"):
                _report += "**Without period info:** " + ", ".join(f"{k}:{v}" for k, v in _trr["no_period"].items()) + "\n\n"
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
            _report += f"### Trend explanation ({_th[_ti]['timestamp']} / {_th[_ti]['agent']})\n\n{_th[_ti]['response']}\n\n"
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
            _report += f"### Topic explanation ({_ph[_pi]['timestamp']} / {_ph[_pi]['agent']})\n\n{_ph[_pi]['response']}\n\n"
        if st.session_state.get("_rag_llm_response"):
            _report += "## Ask Agent\n\n" + st.session_state._rag_llm_response + "\n\n"
        _report += f"\n---\nGenerated: {_now}\n"
        st.session_state._rag_report = _report
        try:
            _saved_path = _save_analysis_session(_selected)
            st.success(f"Generated report and saved the session: {_saved_path}")
        except Exception as e:
            st.success("Report generated")
            st.warning(f"Failed to save the session: {e}")

    if st.session_state.get("_rag_report"):
        _report_name = f"Knowledge_Explorer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        st.download_button("Download (.md)", data=st.session_state._rag_report.encode("utf-8"),
                          file_name=f"{_report_name}.md", mime="text/markdown", key="rag_dl_md")

### Scheduler screen ###
def _scheduler_view():
    """General scheduler management screen. Job list + add/edit + Run Now + Reload."""
    import DigiM_Scheduler as _dmsch
    import DigiM_ScheduledJobs as _dmsj

    st.subheader("Scheduler")
    st.caption("Register, edit, and immediately run background jobs. Press **Reload Schedulers** after changes to apply them.")

    # Control row
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

    # List
    _jobs = _dmsj.load_all()
    if not _jobs:
        st.info("No jobs registered yet. Add one from **Add New Job**.")
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
                st.session_state.sidebar_message = "Updated (apply via Reload)"
                st.rerun()
            if _bd.button("Delete", key=f"sch_del_{_jid}"):
                _dmsj.delete(_jid)
                st.session_state.sidebar_message = f"Deleted: {_jid}"
                st.rerun()

    # Edit form
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
            help='"off" / "daily" (03:00) / "weekly" (Mon 03:00) / "monthly" (1st of month 03:00) / 5-field cron (e.g., "0 3 1 * *")',
            key="sch_f_cron",
        )
        _enabled = st.checkbox("Enabled", value=bool(_existing.get("enabled", False)), key="sch_f_enabled")

        # Extra parameters for agent_run
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
                st.session_state.sidebar_message = f"Saved: {_saved.get('job_id')} (apply via Reload)"
            except Exception as e:
                st.session_state.sidebar_message = f"Save failed: {e}"
            st.rerun()
        if _bc.button("Cancel", key="sch_f_cancel"):
            st.session_state._sch_edit_id = None
            st.rerun()


### User Memory Explorer screen ###
def _user_memory_explorer():
    """User-understanding analytics. Tab 2: deep dive (individual) / Tab 1: cross cohort (group). Each tab includes memory-grounded chat."""
    import DigiM_UserMemoryExplorer as ux
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from math import pi
    import pandas as pd

    _UME_BASE = "user/common/analytics/user_memory_explorer/"

    # session_state keys to save (analysis cache, selections, chat history, report)
    _UME_STATE_KEYS = [
        # Common
        "_ume_report",
        # User understanding (individual)
        "ume_deep_user", "ume_deep_traj_period",
        "_ume_deep_hist",
        # Group understanding
        "ume_cross_users", "ume_cross_pk", "ume_cross_nk",
        "_ume_pcluster", "_ume_ncluster", "_ume_pexp", "_ume_nexp",
        "_ume_cross_gtwin_sys", "_ume_cross_g_hist",
    ]

    def _ume_save_session(label):
        """Save all UME analysis state to a folder."""
        import pickle
        _ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _folder = os.path.join(_UME_BASE, f"analytics{_ts}")
        os.makedirs(_folder, exist_ok=True)
        _meta = {
            "label": label,
            "timestamp": _ts,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        dmu.save_json_file(_meta, os.path.join(_folder, "meta.json"))
        _state = {}
        for _k in _UME_STATE_KEYS:
            if _k in st.session_state:
                _state[_k] = st.session_state[_k]
        try:
            with open(os.path.join(_folder, "state.pkl"), "wb") as f:
                pickle.dump(_state, f)
        except Exception as e:
            # If unpicklable objects are mixed in, save only the text-form data
            _safe = {k: v for k, v in _state.items()
                     if isinstance(v, (str, int, float, list, dict, tuple, bool, type(None)))}
            with open(os.path.join(_folder, "state.pkl"), "wb") as f:
                pickle.dump(_safe, f)
        if st.session_state.get("_ume_report"):
            dmu.save_text_file(st.session_state._ume_report,
                               os.path.join(_folder, "report.md"))
        return _folder

    def _ume_load_session(folder_path):
        """Restore from a saved folder into session_state."""
        import pickle
        _meta_path = os.path.join(folder_path, "meta.json")
        if not os.path.exists(_meta_path):
            return None
        _meta = dmu.read_json_file(_meta_path)
        for _k in _UME_STATE_KEYS:
            if _k in st.session_state:
                del st.session_state[_k]
        _pkl_path = os.path.join(folder_path, "state.pkl")
        if os.path.exists(_pkl_path):
            try:
                with open(_pkl_path, "rb") as f:
                    _state = pickle.load(f)
                for _k, _v in _state.items():
                    st.session_state[_k] = _v
            except Exception:
                pass
        return _meta

    # Handle the sidebar's load request
    if st.session_state.get("_ume_load_folder"):
        _lp = st.session_state._ume_load_folder
        st.session_state._ume_load_folder = None
        _lm = _ume_load_session(_lp)
        if _lm:
            st.info(f"Loaded analysis session: {_lm.get('created_at','')} - {_lm.get('label','')}")

    st.subheader("User Memory Explorer")

    _all_users = ux.list_users("")
    if not _all_users:
        st.info("No user-memory records yet. Continue chatting or run Update User Memory.")
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
        """Overlay series=[(name,color,values), ...] on a single radar (for max/mean/min)."""
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
        """Chat with the memory-grounded agent. Saved into a dedicated session."""
        st.markdown("---")
        st.subheader("Chat with the memory-grounded agent")
        if not context_text:
            st.caption("Cannot chat because the target data is empty.")
            return
        with st.expander("Grounding context (the context passed to the agent)"):
            st.text(context_text[:4000])

        _agent_list = st.session_state.agent_list
        _aidx = _agent_list.index(st.session_state.agent_id) if st.session_state.get("agent_id") in _agent_list else 0
        _agent = st.selectbox("Agent:", _agent_list, index=_aidx, key=f"{key_prefix}_agent")
        _q = st.text_area("Question:", placeholder="e.g. Explain this person's / this cohort's interest evolution and background",
                          height=90, key=f"{key_prefix}_q")
        if _q and st.button("Ask", key=f"{key_prefix}_ask"):
            _af = next((a["FILE"] for a in st.session_state.agents if a["AGENT"] == _agent), None)
            if _af:
                _ui = f"{context_text}\n\n[Question]\n{_q}"
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
                with st.spinner("Running the agent..."):
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
                        st.error(f"Execution error: {type(e).__name__}: {e}")
                    finally:
                        _tmp.save_status("UNLOCKED")
        for _h in st.session_state.get(f"_{key_prefix}_hist", []):
            with st.chat_message("user"):
                st.markdown(f"**[{_h['timestamp']}] {_h['agent']}**")
                st.markdown(_h["query"])
            with st.chat_message("assistant"):
                st.markdown(_h["response"])

    def _um_twin_chat(user_id, key_prefix="ume_deep"):
        """Chat with an AI that only has the selected user's memory (= that user's digital twin).

        - Only LLM engines attached to the sidebar-selected agent can be chosen.
        - The sidebar agent's persona / knowledge / system prompt are NOT used.
        - Persona / Nowaday / History are composed via the "user memory context injection" form
          (History is scored and selected by keywords in the question).
        - The LLM replies directly. The AI is named after the selected user.
        """
        import DigiM_UserMemory as _dmum_t
        import DigiM_UserMemoryBuilder as _dmumb_t
        import DigiM_FoundationModel as _dmfm_t

        st.markdown("---")
        st.subheader("Chat with this User Twin")
        st.caption(
            f"Chat with an LLM whose only context is user \"{user_id}\"'s memory (Persona/Nowaday/History). "
            "The sidebar agent settings (personality / knowledge / system prompt) are not used."
        )

        # Resolve the real service_id for the target user
        _bd = ux.load_bundle(user_id, "")
        _svc = ""
        for _r in [_bd.get("persona") or {}] + (_bd.get("nowaday") or []) + (_bd.get("history") or []):
            if _r.get("service_id"):
                _svc = _r["service_id"]
                break

        # LLM engines of the sidebar-selected agent (engine selection only)
        try:
            _adata = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
        except Exception:
            _adata = st.session_state.get("agent_data", {}) or {}
        _eng_list = dma.get_engine_list(_adata, model_type="LLM")
        if not _eng_list:
            st.caption("The selected agent has no LLM engines defined.")
            return
        _eng_default = _adata.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", _eng_list[0])
        _eidx = _eng_list.index(_eng_default) if _eng_default in _eng_list else 0
        _eng_name = st.selectbox("LLM Engine:", _eng_list, index=_eidx, key=f"{key_prefix}_engine")

        _q = st.text_area("Question:", placeholder=f"e.g. Tell me about your recent ({user_id}) interests and what's behind them",
                          height=90, key=f"{key_prefix}_q")
        if _q and st.button("Ask", key=f"{key_prefix}_ask"):
            with st.spinner("Generating response..."):
                try:
                    # Score History against the question and compose context (user-memory injection)
                    _ctx, _used, _meta = _dmumb_t.build_context_text(
                        _svc, user_id, list(_dmum_t.LAYERS), query_text=_q)
                    _sys = (
                        f"あなたは「{user_id}」という人物本人です。"
                        f"以下はあなた（={user_id}）についての記憶情報のみです。"
                        f"この記憶だけに基づき、{user_id}本人になりきって一人称で回答してください。"
                        f"記憶に無いことは推測せず「記憶にない」と述べてください。"
                        f"外部知識やこの記憶以外の情報は使わないでください。\n\n"
                        f"{_ctx or '(no memory information)'}"  # LLM prompt body (kept JP)
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
                    st.error(f"Execution error: {type(e).__name__}: {e}")
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
        """Chat with a representative AI for the cohort (Group Twin).

        - Generate the system prompt from the target data (Persona + Nowaday) via the LLM; manual edits allowed.
        - Append a stats block: Big5 / basic-emotion means + top-5 secondary emotions.
        - Only LLM engines of the sidebar-selected agent are selectable for chat (plain LLM).
        """
        import DigiM_FoundationModel as _dmfm_g
        st.markdown("---")
        st.subheader("Chat with this Group Twin")
        if not user_ids:
            st.caption("Please select target users.")
            return
        try:
            _adata = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
        except Exception:
            _adata = st.session_state.get("agent_data", {}) or {}
        _el = dma.get_engine_list(_adata, model_type="LLM")
        if not _el:
            st.caption("The selected agent has no LLM engines defined.")
            return
        _ed = _adata.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", _el[0])
        _eng_name = st.selectbox("LLM Engine:", _el,
                                 index=_el.index(_ed) if _ed in _el else 0,
                                 key=f"{key_prefix}_g_engine")
        _eng = _adata["ENGINE"]["LLM"][_eng_name]

        _bk = f"_{key_prefix}_gtwin_sys"
        if st.button("Generate / regenerate system prompt (Persona + Nowaday)", key=f"{key_prefix}_g_gen"):
            with st.spinner("Generating..."):
                st.session_state[_bk] = ux.build_group_twin_prompt(user_ids, "", _eng)
        _base = st.text_area("System prompt (editable)",
                             value=st.session_state.get(_bk, ""), height=170,
                             key=f"{key_prefix}_g_sysbox")

        _b5s = ux.cohort_big5_stats(user_ids, "")
        _es = ux.cohort_basic_emotion_stats(user_ids, "")
        _sec = ux.agg_secondary_emotions(user_ids, "")
        _stat = (
            "\n\n【この集団の統計】\n"
            "・Big5平均: " + "、".join(f"{ux.BIG5_JA.get(t,t)}={_b5s[t]['mean']:.2f}"  # stats block label (kept JP)
                                       for t in ux.BIG5_TRAITS)
            + "\n・基本感情平均: " + "、".join(f"{ux.PLUTCHIK_JA.get(e,e)}={_es[e]['mean']:.2f}"  # stats block label (kept JP)
                                              for e in ux.PLUTCHIK_PRIMARY)
            + "\n・二次感情Top5: " + ("、".join(f"{ux.PLUTCHIK_JA.get(k,k)}({c})"  # stats block label (kept JP)
                                               for k, c in _sec.most_common(5)) or "なし")
        )
        with st.expander("Stats block that will be attached"):
            st.text(_stat)

        _q = st.text_area("Question:", height=90, key=f"{key_prefix}_g_q",
                          placeholder="e.g. Which value does this cohort prioritize most?")
        if _q and st.button("Ask", key=f"{key_prefix}_g_ask"):
            with st.spinner("Generating response..."):
                try:
                    _sys = (_base or "You represent this user cohort.") + _stat
                    _resp = ""
                    for _p, _r, _c in _dmfm_g.call_function_by_name(
                            _eng["FUNC_NAME"], _q, _sys, _eng, [], [], {}, False):
                        if _r:
                            _resp += _r
                    st.session_state.setdefault(f"_{key_prefix}_g_hist", [])
                    st.session_state[f"_{key_prefix}_g_hist"].append({
                        "agent": f"Group Twin ({len(user_ids)} users / {_eng_name})",
                        "query": _q, "response": _resp,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                except Exception as e:
                    st.error(f"Execution error: {type(e).__name__}: {e}")
        for _h in st.session_state.get(f"_{key_prefix}_g_hist", []):
            with st.chat_message("user"):
                st.markdown(f"**[{_h['timestamp']}] {_h['agent']}**")
                st.markdown(_h["query"])
            with st.chat_message("assistant"):
                st.markdown(_h["response"])

    _tab_edit, _tab_deep, _tab_cross = st.tabs(
        ["My Memory", "User Understanding (Individual)", "User Understanding (Group)"])

    # ===== Tab: User Understanding (Individual) =====
    with _tab_deep:
        _uid = st.selectbox("User:", _all_users, key="ume_deep_user")
        _b = ux.load_bundle(_uid, "")
        _p = _b["persona"] or {}

        st.markdown("#### Persona (long-term profile)")
        if _p:
            if _p.get("role"):
                st.markdown(f"**Role:** {_p.get('role')}")
            if _p.get("summary_text"):
                st.caption(_p.get("summary_text"))
            _b5 = _p.get("big5") or {}
            _appr = []  # (label, score) for radar
            _b5rows = []  # for table (trait/score only)
            for t in ux.BIG5_TRAITS:
                _it = _b5.get(t)
                if not isinstance(_it, dict):
                    continue
                _stt = (_it.get("status") or "").strip().lower()
                if _stt == "deleted":
                    continue
                _sc = float(_it.get("score", 0.5) or 0.5)
                _appr.append((ux.BIG5_JA.get(t, t), _sc))
                _b5rows.append({"Trait": ux.BIG5_JA.get(t, t), "Score": _sc})
            if _appr:
                _c1, _c2 = st.columns([1, 1])
                with _c1:
                    st.pyplot(_radar([l for l, _ in _appr], [v for _, v in _appr],
                                     "Big5 (approved+pending)"))
                with _c2:
                    st.dataframe(pd.DataFrame(_b5rows), hide_index=True)
            else:
                st.caption("Big5 is not yet populated (see the review-needed section below)")

            # 6-attribute visualization (treemap -> data table)
            _PFLD_COLORS = {
                "expertise": "#2E86AB",
                "recurring_interests": "#A23B72",
                "values_principles": "#F18F01",
                "constraints": "#C73E1D",
                "communication_style": "#3CB371",
                "avoid_topics": "#7B68EE",
            }
            _PFLD_JA = {
                "expertise": "Expertise", "recurring_interests": "Interests",
                "values_principles": "Values", "constraints": "Constraints",
                "communication_style": "Tone", "avoid_topics": "Topics to avoid",
            }
            _PSTATUS_COLOR = {
                "approved": "#2E8B57", "pending": "#FFA500", "deleted": "#A0A0A0",
            }
            _has_p_items = any((_p.get(_pf) or []) for _pf in _PFLD_COLORS)
            if _has_p_items:
                st.markdown("**Persona attribute visualization (3 layouts shown together for comparison)**")
                _stat_sel = st.multiselect("Status filter",
                                            ["approved", "pending", "deleted"],
                                            default=["approved", "pending"],
                                            key="ume_deep_pfield_status")
                _stat_norm = {s.lower() for s in _stat_sel}
                _by_pfield = {pf: [] for pf in _PFLD_COLORS}
                for _pf in _PFLD_COLORS:
                    for _it in (_p.get(_pf) or []):
                        if not isinstance(_it, dict):
                            continue
                        _st = (_it.get("status") or "pending").lower()
                        if _st not in _stat_norm:
                            continue
                        _lbl = (_it.get("label") or "").strip()
                        if not _lbl:
                            continue
                        _conf = float(_it.get("confidence") or 0.0)
                        _by_pfield[_pf].append({"label": _lbl, "confidence": _conf, "status": _st})
                _total_items = sum(len(v) for v in _by_pfield.values())

                if _total_items == 0:
                    st.caption("No attributes match the selected status filter")
                else:
                    # ===== Treemap =====
                    st.markdown("##### Treemap (row = category / area = confidence ratio / color = category)")
                    import matplotlib.patches as _mpatches_t
                    import textwrap as _tw_t
                    _field_totals = {pf: sum(x["confidence"] for x in its)
                                     for pf, its in _by_pfield.items() if its}
                    _grand = sum(_field_totals.values())
                    # Larger figure + bigger font for label readability
                    _fig_t, _ax_t = plt.subplots(figsize=(11, 6))
                    _canvas_w, _canvas_h = 100.0, 100.0
                    _MAX_LBL_CHARS = 32  # Max label characters (truncate with ellipsis when exceeded)
                    _LBL_FS = 11         # Label font size
                    _CONF_FS = 9         # confidence font size
                    _cur_y = 0.0
                    for _pf, _its in _by_pfield.items():
                        if not _its:
                            continue
                        _strip_h = _canvas_h * _field_totals[_pf] / max(_grand, 1e-9)
                        _items_sorted = sorted(_its, key=lambda x: x["confidence"], reverse=True)
                        _f_total = max(_field_totals[_pf], 1e-9)
                        _cur_x = 0.0
                        for _x in _items_sorted:
                            _w_r = _canvas_w * _x["confidence"] / _f_total
                            _rect = _mpatches_t.Rectangle(
                                (_cur_x, _cur_y), _w_r, _strip_h,
                                facecolor=_PFLD_COLORS[_pf], edgecolor="white", linewidth=1.5)
                            _ax_t.add_patch(_rect)
                            # Wrap & truncate: derive per-line max chars and max lines from rectangle size
                            if _w_r > 5 and _strip_h > 4:
                                _chars_per_line = max(3, int(_w_r * 0.50))
                                _max_lines = max(1, int(_strip_h / 4.5))
                                _budget = max(1, _chars_per_line * _max_lines - 1)
                                _lbl_t = _x["label"]
                                if len(_lbl_t) > min(_MAX_LBL_CHARS, _budget):
                                    _lbl_t = _lbl_t[:max(1, min(_MAX_LBL_CHARS, _budget))] + "…"
                                _wrapped = _tw_t.fill(_lbl_t, width=_chars_per_line,
                                                      break_long_words=True, break_on_hyphens=False)
                                # Main label (slightly above center) and confidence value (bottom)
                                _ax_t.text(_cur_x + _w_r / 2, _cur_y + _strip_h * 0.42,
                                           _wrapped, ha="center", va="center",
                                           fontsize=_LBL_FS, color="white",
                                           fontfamily="IPAexGothic", linespacing=1.1)
                                _ax_t.text(_cur_x + _w_r / 2, _cur_y + _strip_h * 0.85,
                                           f"({_x['confidence']:.2f})",
                                           ha="center", va="center",
                                           fontsize=_CONF_FS, color="white",
                                           fontfamily="IPAexGothic")
                            _cur_x += _w_r
                        _cur_y += _strip_h
                    _ax_t.set_xlim(0, _canvas_w)
                    _ax_t.set_ylim(_canvas_h, 0)
                    _ax_t.axis("off")
                    plt.tight_layout()
                    st.pyplot(_fig_t)
                    plt.close(_fig_t)
                    # Category color legend (shown below)
                    _tm_legend = " &nbsp;&nbsp; ".join(
                        f"<span style='color:{_c};font-weight:bold;font-size:1.05em'>■ {_PFLD_JA[_k]}</span>"
                        for _k, _c in _PFLD_COLORS.items()
                    )
                    st.markdown(_tm_legend, unsafe_allow_html=True)

                    # ===== Data table =====
                    st.markdown("##### Data table (category = color / confidence = progress bar / sortable & searchable)")
                    _rows_a = []
                    for _pf, _its in _by_pfield.items():
                        for _x in _its:
                            _rows_a.append({
                                "Category": _PFLD_JA[_pf], "Label": _x["label"],
                                "confidence": _x["confidence"], "status": _x["status"],
                            })
                    _df_a = pd.DataFrame(_rows_a)
                    # Color the Category column to match the treemap; color the status column by status
                    _ja_to_color = {_PFLD_JA[_k]: _c for _k, _c in _PFLD_COLORS.items()}
                    def _style_pfld_col(_vals):
                        return [f"color: {_ja_to_color.get(_v, '#000')}; font-weight: bold"
                                for _v in _vals]
                    def _style_status_col(_vals):
                        return [f"color: {_PSTATUS_COLOR.get(str(_v).lower(), '#000')}; font-weight: bold"
                                for _v in _vals]
                    try:
                        _df_show = (_df_a.style
                                    .apply(_style_pfld_col, subset=["Category"])
                                    .apply(_style_status_col, subset=["status"]))
                    except Exception:
                        _df_show = _df_a
                    st.dataframe(
                        _df_show, hide_index=True, use_container_width=True,
                        column_config={
                            "confidence": st.column_config.ProgressColumn(
                                "confidence", min_value=0.0, max_value=1.0, format="%.2f"),
                        },
                    )
        else:
            st.caption("Persona has not been generated yet")

        st.markdown("#### Nowaday (recent trends)")
        if _b["nowaday"]:
            # Select the snapshot (sorted by generated_at descending; first is latest)
            _nws_d = _b["nowaday"]
            _nw_opts_d = {f"{m.get('period','')} @ {m.get('generated_at','')}": m for m in _nws_d}
            _osel_d = st.selectbox("Snapshot (period @ generated_at; top is latest)",
                                    list(_nw_opts_d.keys()),
                                    index=0, key="ume_deep_nw_sel")
            _nw = _nw_opts_d[_osel_d]
            st.markdown(f"**Period:** {_nw.get('period','')}")
            if _nw.get("summary_text"):
                st.caption(_nw["summary_text"])
            _be = _nw.get("basic_emotions") or {}
            _vals = [float(_be.get(e, 0) or 0) for e in ux.PLUTCHIK_PRIMARY]
            if any(v > 0 for v in _vals):
                _ec1, _ec2 = st.columns([1, 1])
                with _ec1:
                    st.pyplot(_radar([ux.PLUTCHIK_JA.get(e, e) for e in ux.PLUTCHIK_PRIMARY],
                                     _vals, "Basic emotions (intensity)"))
                with _ec2:
                    st.dataframe(pd.DataFrame(
                        [{"Trait": ux.PLUTCHIK_JA.get(e, e),
                          "Score": round(float(_be.get(e, 0) or 0), 2)}
                         for e in ux.PLUTCHIK_PRIMARY]), hide_index=True)
            if _nw.get("secondary_emotions"):
                st.markdown("**Secondary emotions:** " + ", ".join(
                    ux.PLUTCHIK_JA.get(s, s) for s in _nw["secondary_emotions"]))
            for _lbl, _k in (("Recurring", "recurring_topics"), ("Emerging", "emerging"),
                             ("Declining", "declining"), ("Shifts", "shifts")):
                if _nw.get(_k):
                    st.markdown(f"**{_lbl}:** " + "、".join(str(x) for x in _nw[_k]))
        else:
            st.caption("Nowaday has not been generated yet")

        st.markdown("#### History emotion trajectory")
        _traj_all = ux.user_emotion_trajectory(_uid, "")
        if _traj_all:
            _def_end = now_time.date()
            _def_start = (now_time - timedelta(days=30)).date()
            _rng = st.date_input(
                "Period (filtered by this user's History dates)",
                value=(_def_start, _def_end), key="ume_deep_traj_period",
            )
            if isinstance(_rng, (list, tuple)) and len(_rng) == 2:
                _s, _e = _rng[0].isoformat(), _rng[1].isoformat()
            elif isinstance(_rng, (list, tuple)) and len(_rng) == 1:
                _s, _e = _rng[0].isoformat(), _def_end.isoformat()
            else:
                _s, _e = _rng.isoformat(), _def_end.isoformat()
            _traj = [(d, t, es) for d, t, es in _traj_all if _s <= d <= _e]
            st.caption(f"Target {_s} - {_e}: {len(_traj)} / total {len(_traj_all)}")
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
                with st.expander(f"Per-session emotion log ({len(_traj)} sessions)"):
                    st.dataframe(pd.DataFrame(
                        [{"date": d, "topic": t, "emotions": "、".join(ux.PLUTCHIK_JA.get(e, e) for e in es)}
                         for d, t, es in reversed(_traj)], ), hide_index=True)
            else:
                st.caption("No History entries in the specified period")
        else:
            st.caption("History has not been generated yet")

        _rev = ux.persona_review_items(_uid, "")
        if _rev["big5"] or _rev["lists"]:
            with st.expander("Review-needed (pending) items"):
                if _rev["big5"]:
                    st.markdown("**Big5:** " + "、".join(
                        f"{ux.BIG5_JA.get(t,t)}(score={s},conf={c})" for t, s, c in _rev["big5"]))
                for _f, _items in _rev["lists"].items():
                    st.markdown(f"**{_f}:** " + "、".join(_items))

        # ============ Agent relationship / communication analysis ============
        st.markdown("---")
        st.markdown("### Relationship with Agent")
        _ua_ag = st.selectbox(
            "Conversation partner agent",
            st.session_state.agent_list,
            index=(st.session_state.agent_list.index(st.session_state.agent_id)
                   if st.session_state.get("agent_id") in st.session_state.agent_list else 0),
            key="ume_deep_ua_agent",
        )
        _ua_af = next((a["FILE"] for a in st.session_state.agents if a["AGENT"] == _ua_ag), None)
        if _ua_af:
            import glob as _glob_ua
            import json as _json_ua
            import json as _json
            import re as _re
            from collections import Counter as _Cnt_ua
            from datetime import datetime as _dt_ua, date as _date_ua, timedelta as _td_ua

            _FAR_FUTURE_UA = _date_ua(2099, 12, 31)
            _today_ua = _dt_ua.now().date()
            try:
                _default_from_ua = _date_ua(_today_ua.year - 1, _today_ua.month, _today_ua.day)
            except ValueError:
                _default_from_ua = _date_ua(_today_ua.year - 1, 2, 28)

            _pcol1, _pcol2 = st.columns(2)
            _ua_period_from = _pcol1.date_input(
                "Period From:", value=_default_from_ua,
                min_value=_date_ua(2000, 1, 1), max_value=_FAR_FUTURE_UA,
                key="ume_deep_ua_period_from")
            _ua_period_to = _pcol2.date_input(
                "Period To:", value=_today_ua,
                min_value=_date_ua(2000, 1, 1), max_value=_FAR_FUTURE_UA,
                key="ume_deep_ua_period_to")
            st.caption("* Specify the period and press \"Run analysis\" to filter the panels from activity to Knowledge references with that period.")

            def _ua_scan(uid, af, p_from, p_to):
                _pf_s = p_from.isoformat()
                _pt_s = p_to.isoformat()
                _result = []
                for _sf in sorted(_glob_ua.glob("user/session2*"), reverse=True):
                    _p = os.path.join(_sf, "chat_memory.json")
                    if not os.path.exists(_p):
                        continue
                    try:
                        _d = _json_ua.load(open(_p, encoding="utf-8"))
                    except Exception:
                        continue
                    _seq1_st = _d.get("1", {}).get("SETTING", {})
                    if (_seq1_st.get("user_info") or {}).get("USER_ID") != uid:
                        continue
                    _sid = os.path.basename(_sf).replace("session", "")
                    for _sk, _sv in _d.items():
                        if not isinstance(_sv, dict):
                            continue
                        for _bk, _bv in _sv.items():
                            if _bk == "SETTING" or not isinstance(_bv, dict):
                                continue
                            _st_ = _bv.get("setting") or {}
                            if _st_.get("agent_file") != af:
                                continue
                            _q = ((_bv.get("prompt") or {}).get("query") or {}).get("input", "") or ""
                            _r = ((_bv.get("response") or {}).get("text", "")) or ""
                            _ts = ((_bv.get("response") or {}).get("timestamp", "")
                                   or (_bv.get("prompt") or {}).get("timestamp", ""))
                            _tsd = _ts[:10] if _ts else ""
                            if _tsd and not (_pf_s <= _tsd <= _pt_s):
                                continue
                            _kref = ((_bv.get("response") or {}).get("reference") or {}).get("knowledge_rag", []) or []
                            _result.append({
                                "session_id": _sid,
                                "session_name": _st_.get("session_name", ""),
                                "seq": _sk, "sub_seq": _bk,
                                "query": _q, "response": _r, "timestamp": _ts,
                                "knowledge_rag": _kref,
                            })
                return _result

            _run_btn = st.button("Run analysis", key="ume_deep_ua_run", type="primary",
                                  help="Aggregate the dialog history and render each panel")
            _cache_key = f"_ume_deep_ua_cache_{_uid}_{_ua_af}"
            if _run_btn:
                with st.spinner("Scanning dialog history..."):
                    _scan_result = _ua_scan(_uid, _ua_af, _ua_period_from, _ua_period_to)
                _chunk_refs_tmp = {}
                for _s in _scan_result:
                    for _kref in (_s.get("knowledge_rag") or []):
                        try:
                            _rd = dmu.parse_log_template(_kref)
                        except Exception:
                            continue
                        _bk = _rd.get("DB") or _rd.get("bucket")
                        _rid = str(_rd.get("ID") or _rd.get("id") or "")
                        if not (_bk and _rid):
                            continue
                        _chunk_refs_tmp.setdefault((_bk, _rid), []).append({
                            "sQ": float(_rd.get("similarity_Q") or 0.0),
                            "sA": float(_rd.get("similarity_A") or 0.0),
                            "ts": _s.get("timestamp", ""),
                        })
                _chunk_meta_tmp = {}
                _all_chunks_by_bn = {}
                _col_to_rag_name_ua = {}
                _agent_data_ua = {}
                try:
                    _agent_data_ua = dmu.read_json_file(_ua_af, agent_folder_path) or {}
                except Exception:
                    _agent_data_ua = {}
                for _kn_entry in _agent_data_ua.get("KNOWLEDGE", []):
                    _rn_v = _kn_entry.get("RAG_NAME")
                    if not _rn_v:
                        continue
                    for _dt_entry in _kn_entry.get("DATA", []):
                        _dn = _dt_entry.get("DATA_NAME", "")
                        if _dn:
                            _col_to_rag_name_ua[_dn] = _rn_v
                _bns_to_fetch = sorted(set(list(_col_to_rag_name_ua.keys()) + [b for b, _ in _chunk_refs_tmp.keys()]))
                if _bns_to_fetch:
                    with st.spinner("Fetching RAG metadata..."):
                        for _bn in _bns_to_fetch:
                            try:
                                _rows = dmc.get_rag_collection_data(_bn)
                                _all_chunks_by_bn[_bn] = _rows
                                for _row in _rows:
                                    _rid2 = str(_row.get("id") or "")
                                    _chunk_meta_tmp[(_bn, _rid2)] = _row
                            except Exception:
                                pass
                st.session_state[_cache_key] = {
                    "seqs": _scan_result,
                    "chunk_refs": _chunk_refs_tmp,
                    "chunk_meta": _chunk_meta_tmp,
                    "all_chunks_by_bn": _all_chunks_by_bn,
                    "col_to_rag_name": _col_to_rag_name_ua,
                    "period_from": _ua_period_from, "period_to": _ua_period_to,
                }
            _cached = st.session_state.get(_cache_key)
            if _cached is None:
                st.caption("Pick an agent and period, then press \"Run analysis\" to display results.")
            elif not _cached.get("seqs"):
                st.info(f"No dialog history between \"{_uid}\" and \"{_ua_ag}\" (period: {_ua_period_from} - {_ua_period_to})")
            else:
                _ua_seqs = _cached["seqs"]
                _chunk_refs = _cached["chunk_refs"]
                _chunk_meta = _cached["chunk_meta"]
                _all_chunks_by_bn = _cached.get("all_chunks_by_bn", {})
                _col_to_rag_name_ua = _cached.get("col_to_rag_name", {})
                _cached_pf = _cached.get("period_from")
                _cached_pt = _cached.get("period_to")
                _hist_by_sid = {h.get("session_id"): h for h in (_b.get("history") or [])}
                _sess_ids = sorted(set(s["session_id"] for s in _ua_seqs))
                from datetime import datetime as _dt_a, timedelta as _td_a
                from collections import Counter as _Cnt_a

                st.caption(f"Target period: **{_cached_pf} - {_cached_pt}** / sessions: {len(_sess_ids)} / turns: {len(_ua_seqs)}")

                # ===== 1. Basic summary =====
                st.markdown("#### Summary")
                _kc = st.columns(5)
                _kc[0].metric("Sessions", len(_sess_ids))
                _kc[1].metric("Turns", len(_ua_seqs))
                _total_chars = sum(len(s["query"]) + len(s["response"]) for s in _ua_seqs)
                _kc[2].metric("Total chars", f"{_total_chars:,}")
                _avg_turns_per = round(len(_ua_seqs) / max(len(_sess_ids), 1), 1)
                _kc[3].metric("Avg turns/session", _avg_turns_per)
                _last_ts = max((s["timestamp"] for s in _ua_seqs if s["timestamp"]), default="")
                _kc[4].metric("Last contact", _last_ts[:10] if _last_ts else "-")

                # ===== 2. Activity trend =====
                st.markdown("#### Activity trend")
                _gran = st.selectbox("Granularity", ["月", "週", "日"], index=0, key="ume_deep_ua_actgran")  # values are JP because the bucket logic matches on them

                def _gkey(_ts, _g):
                    if not _ts:
                        return "Unset"
                    if _g == "月":  # "Month"
                        return _ts[:7]
                    if _g == "日":  # "Day"
                        return _ts[:10]
                    try:
                        _tt = pd.Timestamp(_ts[:10])
                        _ws = (_tt - pd.Timedelta(days=int(_tt.weekday()))).date()
                        return f"{_ws.year}-{_ws.month}-{_ws.day}+w"
                    except Exception:
                        return _ts[:7]
                _by_g_s = _Cnt_a(); _by_g_t = _Cnt_a()
                _sess_first_g = {}
                for s in _ua_seqs:
                    _k = _gkey(s["timestamp"], _gran)
                    _by_g_t[_k] += 1
                    if s["session_id"] not in _sess_first_g:
                        _sess_first_g[s["session_id"]] = _k
                for _sid_x, _k in _sess_first_g.items():
                    _by_g_s[_k] += 1
                _keys = sorted(set(_by_g_s.keys()) | set(_by_g_t.keys()))
                if _keys:
                    _fig_act, _ax_act = plt.subplots(figsize=(10, 3.6))
                    _ax_act.bar(_keys, [_by_g_s[k] for k in _keys],
                                color="#4A90D9", alpha=0.75, label="Sessions")
                    _ax2 = _ax_act.twinx()
                    _ax2.plot(_keys, [_by_g_t[k] for k in _keys],
                              color="#E74C3C", marker="o", label="Turns")
                    _ax_act.set_ylabel("Sessions", color="#4A90D9")
                    _ax2.set_ylabel("Turns", color="#E74C3C")
                    _ax_act.set_xticks(range(len(_keys)))
                    _ax_act.set_xticklabels(_keys, rotation=45, ha="right", fontsize=9)
                    _ax_act.grid(True, alpha=0.3)
                    plt.tight_layout()
                    st.pyplot(_fig_act); plt.close(_fig_act)
                else:
                    st.caption("No data in the target period")

                # ===== 3. Conversation pattern (KMeans on Q chars x R chars + LLM explanation) =====
                st.markdown("#### Conversation pattern")
                _qlens_all = [len(s["query"]) for s in _ua_seqs]
                _rlens_all = [len(s["response"]) for s in _ua_seqs]
                _qmin_a, _qmax_a = (min(_qlens_all), max(_qlens_all)) if _qlens_all else (0, 0)
                _rmin_a, _rmax_a = (min(_rlens_all), max(_rlens_all)) if _rlens_all else (0, 0)
                _avg_q = sum(_qlens_all) / max(len(_qlens_all), 1)
                _avg_r = sum(_rlens_all) / max(len(_rlens_all), 1)
                _kpc = st.columns(3)
                _kpc[0].metric("Avg query chars", int(_avg_q))
                _kpc[1].metric("Avg response chars", int(_avg_r))
                _kpc[2].metric("Response/query ratio", f"{(_avg_r / max(_avg_q, 1)):.1f}x")

                _fq1, _fq2 = st.columns(2)
                if _qmax_a > _qmin_a:
                    _qr = _fq1.slider("Query-char range", min_value=int(_qmin_a), max_value=int(_qmax_a),
                                      value=(int(_qmin_a), int(_qmax_a)), key="ume_deep_ua_qrange")
                else:
                    _qr = (int(_qmin_a), int(_qmax_a)); _fq1.caption(f"Query chars: {int(_qmin_a)} (single value)")
                if _rmax_a > _rmin_a:
                    _rr = _fq2.slider("Response-char range", min_value=int(_rmin_a), max_value=int(_rmax_a),
                                      value=(int(_rmin_a), int(_rmax_a)), key="ume_deep_ua_rrange")
                else:
                    _rr = (int(_rmin_a), int(_rmax_a)); _fq2.caption(f"Response chars: {int(_rmin_a)} (single value)")
                _filt_qr = [s for s in _ua_seqs
                            if _qr[0] <= len(s["query"]) <= _qr[1] and _rr[0] <= len(s["response"]) <= _rr[1]]

                _kc1, _kc2 = st.columns([1, 3])
                _kk = _kc1.number_input("Number of clusters (k)", min_value=2, max_value=8, value=3,
                                         step=1, key="ume_deep_ua_kmeans_k")
                _run_cl = _kc2.button("Run clustering (KMeans)", key="ume_deep_ua_kmeans_run")
                _cl_cache_key = f"_ume_deep_ua_kmeans_{_uid}_{_ua_af}"
                if _run_cl:
                    if len(_filt_qr) < int(_kk):
                        st.warning(f"Not enough data ({len(_filt_qr)} rows) for k={_kk}")
                    else:
                        try:
                            from sklearn.cluster import KMeans as _KM_qr
                            _Xqr = [[len(s["query"]), len(s["response"])] for s in _filt_qr]
                            _km_qr = _KM_qr(n_clusters=int(_kk), random_state=0, n_init=10).fit(_Xqr)
                            _labels_qr = _km_qr.labels_.tolist()
                            _items_cl = []
                            for s, _lb in zip(_filt_qr, _labels_qr):
                                _items_cl.append({**s, "Cluster": int(_lb)})
                            st.session_state[_cl_cache_key] = {
                                "items": _items_cl, "k": int(_kk),
                                "centers": _km_qr.cluster_centers_.tolist(),
                            }
                            st.session_state[f"{_cl_cache_key}_names"] = None
                        except Exception as _e:
                            st.warning(f"KMeans error: {_e}")

                _clc_qr = st.session_state.get(_cl_cache_key)
                _names_qr = st.session_state.get(f"{_cl_cache_key}_names") or {}
                _fig_qa, _ax_qa = plt.subplots(figsize=(9, 4.4))
                from matplotlib.lines import Line2D as _L2D_qr
                if _clc_qr and (_clc_qr.get("items") or []):
                    _items_show = [it for it in (_clc_qr.get("items") or [])
                                   if _qr[0] <= len(it["query"]) <= _qr[1]
                                   and _rr[0] <= len(it["response"]) <= _rr[1]]
                    _cmap_qr_lbl = sorted(set(it["Cluster"] for it in _items_show))
                    _tab_qr = plt.cm.get_cmap("tab10", max(len(_cmap_qr_lbl), 1))
                    _c2col = {cl: _tab_qr(i) for i, cl in enumerate(_cmap_qr_lbl)}
                    for it in _items_show:
                        _ax_qa.scatter(len(it["query"]), len(it["response"]),
                                       color=_c2col.get(it["Cluster"], "gray"),
                                       alpha=0.7, s=55, edgecolors="white", linewidths=0.6)
                    _lh_qr = [_L2D_qr([0], [0], linestyle="", label="〔Cluster〕")]
                    for cl in _cmap_qr_lbl:
                        _nm = _names_qr.get(str(int(cl))) or _names_qr.get(int(cl))
                        _lab_qr = f"C{int(cl)}: {str(_nm)[:14]}" if _nm else f"Cluster {int(cl)}"
                        _lh_qr.append(_L2D_qr([0], [0], marker="o", linestyle="",
                                              color=_c2col[cl], markersize=8, label=_lab_qr))
                    _ax_qa.legend(handles=_lh_qr, loc="upper left", bbox_to_anchor=(1.02, 1), fontsize=8)
                    _ax_qa.set_title(f"Per-seq query x response chars (KMeans k={_clc_qr.get('k')})")
                else:
                    _u_m = sorted(set(s["timestamp"][:7] for s in _filt_qr if s["timestamp"]))
                    _m_idx = {m: i for i, m in enumerate(_u_m)}
                    _cmap_qa = plt.cm.get_cmap("viridis", max(len(_u_m), 1))
                    for s in _filt_qr:
                        _col_q = _cmap_qa(_m_idx.get(s["timestamp"][:7], 0)) if s["timestamp"] else "gray"
                        _ax_qa.scatter(len(s["query"]), len(s["response"]),
                                       color=_col_q, alpha=0.65, s=50, edgecolors="white", linewidths=0.6)
                    _ax_qa.set_title("Per-seq query x response chars (color = month)")
                _ax_qa.set_xlabel("Query chars (per seq)"); _ax_qa.set_ylabel("Response chars (per seq)")
                _ax_qa.grid(True, alpha=0.3)
                plt.tight_layout()
                st.pyplot(_fig_qa); plt.close(_fig_qa)

                if _clc_qr and _clc_qr.get("items"):
                    def _cl_qa_ctx():
                        _cc = st.session_state.get(_cl_cache_key)
                        if not _cc:
                            return ""
                        _txt = ("KMeans clustering result on (per-seq) query x response chars.\n"
                                f"k={_cc.get('k')}\n")
                        _by_cl = {}
                        for it in (_cc.get("items") or []):
                            _by_cl.setdefault(int(it["Cluster"]), []).append(it)
                        for _cl in sorted(_by_cl.keys()):
                            _xs = _by_cl[_cl]
                            _qq = [len(s["query"]) for s in _xs]
                            _rr2 = [len(s["response"]) for s in _xs]
                            _txt += (f"\n[Cluster {int(_cl)}] ({len(_xs)} rows) "
                                     f"query chars avg={sum(_qq)/len(_qq):.0f} (min={min(_qq)}, max={max(_qq)}), "
                                     f"response chars avg={sum(_rr2)/len(_rr2):.0f} (min={min(_rr2)}, max={max(_rr2)})\n")
                            for s in _xs[:3]:
                                _txt += f"  - Q: {s['query'][:80]} / R: {s['response'][:80]}\n"
                        _txt += "\nNote each cluster's characteristics (interaction nature) succinctly from the user-agent relationship perspective."
                        return _txt

                    def _cl_qa_post(resp):
                        _m = _re.search(r"```json\s*(\{.*?\})\s*```", resp, _re.DOTALL) or _re.search(r"(\{[^{}]*\})", resp, _re.DOTALL)
                        if _m:
                            try:
                                _raw = _json.loads(_m.group(1))
                                st.session_state[f"{_cl_cache_key}_names"] = {str(k): str(v)[:14] for k, v in _raw.items()}
                            except Exception:
                                pass
                        return _re.sub(r"```json\s*\{.*?\}\s*```\s*", "", resp, count=1, flags=_re.DOTALL).strip()
                    _explanation_block("_ume_deep_ua_qa_expl", "Cluster Analyst UME", "agent_23DataAnalyst.json",
                                       _cl_qa_ctx, "Conversation cluster", "ume_deep_ua_qa", postprocess=_cl_qa_post)

                # ===== 4. Emotional tone =====
                st.markdown("#### Emotional tone")
                st.caption("Source: User Memory **history** table (history.emotions: emotion tags estimated by the LLM per session). Basic emotions are normalized by max to a radar; secondary emotions are the top-N by occurrence.")
                _emo_c = _Cnt_a()
                for sid in _sess_ids:
                    _h = _hist_by_sid.get(sid)
                    if _h:
                        for _e in (_h.get("emotions") or []):
                            _emo_c[_e] += 1
                if _emo_c:
                    _basic_vals = [_emo_c.get(e, 0) for e in ux.PLUTCHIK_PRIMARY]
                    _mx = max(_basic_vals) if max(_basic_vals) > 0 else 1
                    _bvals_n = [v / _mx for v in _basic_vals]
                    _ec1, _ec2 = st.columns([1, 1])
                    with _ec1:
                        st.pyplot(_radar([ux.PLUTCHIK_JA.get(e, e) for e in ux.PLUTCHIK_PRIMARY],
                                          _bvals_n, "Basic emotion occurrence ratio (normalized)"))
                    with _ec2:
                        _sec_pairs = [(_e, _emo_c[_e]) for _e in _emo_c if _e in ux.PLUTCHIK_SECONDARY]
                        _sec_pairs.sort(key=lambda x: x[1], reverse=True)
                        if _sec_pairs:
                            st.markdown("**Top secondary emotions**")
                            st.dataframe(
                                pd.DataFrame([{"Emotion": ux.PLUTCHIK_JA.get(e, e), "Count": c}
                                              for e, c in _sec_pairs[:10]]),
                                hide_index=True, use_container_width=True)
                        else:
                            st.caption("No secondary-emotion data")
                else:
                    st.caption("No emotion data")

                # ===== 5. Compatibility score =====
                st.markdown("#### Compatibility score")
                st.caption("Source: chat_memory.json (query chars / response chars / RAG references / timestamps) + User Memory **history** table (axis_tags.interests). Continuity = dialog span (months) / 12, Frequency = turns / active months / 20, Focus = top interest tag ratio * 2, Richness = avg response chars / 500, Engagement = avg query chars / 200, Knowledge use = avg RAG references / 5. All clipped to 0..1.")
                _all_ts = sorted([s["timestamp"] for s in _ua_seqs if s["timestamp"]])
                _span_months = 0
                if len(_all_ts) >= 2:
                    try:
                        _t0 = _dt_a.fromisoformat(_all_ts[0][:10])
                        _t1 = _dt_a.fromisoformat(_all_ts[-1][:10])
                        _span_months = max(0, (_t1.year - _t0.year) * 12 + (_t1.month - _t0.month))
                    except Exception:
                        _span_months = 0
                _continuity = min(_span_months / 12.0, 1.0)
                _active_months = len(set(s["timestamp"][:7] for s in _ua_seqs if s["timestamp"])) or 1
                _frequency = min((len(_ua_seqs) / _active_months) / 20.0, 1.0)
                _ax_int_c = _Cnt_a()
                for sid in _sess_ids:
                    _h = _hist_by_sid.get(sid)
                    if _h:
                        for _x in ((_h.get("axis_tags") or {}).get("interests") or []):
                            _ax_int_c[_x] += 1
                _top_share = 0.0
                _all_int_n = sum(_ax_int_c.values())
                if _all_int_n > 0 and _ax_int_c:
                    _top_share = _ax_int_c.most_common(1)[0][1] / _all_int_n
                _focus = min(_top_share * 2.0, 1.0)
                _richness = min(_avg_r / 500.0, 1.0)
                _engagement = min(_avg_q / 200.0, 1.0)
                _kn_per_turn = sum(len(s["knowledge_rag"]) for s in _ua_seqs) / max(len(_ua_seqs), 1)
                _knowledge_use = min(_kn_per_turn / 5.0, 1.0)
                _comp_labels = ["Continuity", "Frequency", "Focus", "Richness", "Engagement", "Knowledge use"]
                _comp_vals = [_continuity, _frequency, _focus, _richness, _engagement, _knowledge_use]
                _crc1, _crc2 = st.columns([1, 1])
                with _crc1:
                    st.pyplot(_radar(_comp_labels, _comp_vals, "Compatibility score", vmax=1.0))
                with _crc2:
                    st.dataframe(
                        pd.DataFrame([{"Axis": _l, "Score (0-1)": round(_v, 2)}
                                      for _l, _v in zip(_comp_labels, _comp_vals)]),
                        hide_index=True, use_container_width=True)
                    _verdict = []
                    _verdict.append("Long-term" if _continuity >= 0.5 else ("Ongoing" if _continuity >= 0.2 else "Short-term"))
                    _verdict.append("High-frequency" if _frequency >= 0.5 else ("Medium-frequency" if _frequency >= 0.2 else "Low-frequency"))
                    _verdict.append("Focused" if _focus >= 0.5 else "Multi-theme")
                    _verdict.append("Verbose-response" if _richness >= 0.5 else "Concise-response")
                    _verdict.append("High-knowledge-use" if _knowledge_use >= 0.5 else ("Medium-knowledge-use" if _knowledge_use >= 0.2 else "Low-knowledge-use"))
                    st.markdown(f"**Relationship label:** {' / '.join(_verdict)}")

                # ===== 6. Theme overlap =====
                st.markdown("#### Theme overlap")
                st.caption("Source: User Memory **history** table (history.axis_tags: interests / values / constraints). Aggregated only over conversations with this agent.")
                _ax_c = {"interests": _Cnt_a(), "values": _Cnt_a(), "constraints": _Cnt_a()}
                for sid in _sess_ids:
                    _h = _hist_by_sid.get(sid)
                    if _h:
                        _at = _h.get("axis_tags") or {}
                        for _ck in _ax_c:
                            for _x in (_at.get(_ck) or []):
                                _ax_c[_ck][_x] += 1
                _tc1, _tc2, _tc3 = st.columns(3)
                for _ic, (_jl, _ck, _co) in enumerate([
                    ("Interests", "interests", _tc1),
                    ("Values", "values", _tc2),
                    ("Constraints", "constraints", _tc3),
                ]):
                    with _co:
                        st.markdown(f"**{_jl}**")
                        _items = _ax_c[_ck].most_common(10)
                        if _items:
                            st.dataframe(pd.DataFrame(_items, columns=["Item", "Count"]),
                                         hide_index=True, use_container_width=True)
                        else:
                            st.caption("—")

                # ===== 7. Knowledge references (scatter + list, KE-Overall style) =====
                st.markdown("#### Knowledge references (scatter + list)")
                st.caption("Source: chat_memory.json `response.reference.knowledge_rag` + RAG collection metadata (including vector_data_value_text). The scatter plots **all RAG data as of the period's end (<= Period To)**; within that, only **chunks referenced in the period** are shown in category colors (others in light gray). Dot Size has the same 3 modes as Knowledge Explorer Overall.")

                if not _all_chunks_by_bn:
                    st.caption("No RAG-reference history in the target period")
                else:
                    import io as _io_kn
                    import numpy as _np_k
                    _cat_color_map_kn = {}
                    try:
                        _cmj = dmu.read_json_file("category_map.json", mst_folder_path) or dmu.read_json_file("sample_category_map.json", mst_folder_path)
                        _cat_color_map_kn = (_cmj or {}).get("CategoryColor", {})
                    except Exception:
                        _cat_color_map_kn = {}

                    _kc_l, _kc_r = st.columns([1, 1])
                    _kn_dim = _kc_l.radio("Dimension Reduction:", ["PCA", "t-SNE"], index=0, horizontal=True, key="ume_deep_ua_kn_dim")
                    _kn_size_mode = _kc_r.radio("Dot Size:", ["Uniform", "Newer=Larger", "Highlight Period"], index=0, horizontal=True, key="ume_deep_ua_kn_size")
                    _kn_exclude_private = st.checkbox("Exclude Private Data", value=True, key="ume_deep_ua_kn_excl_priv")
                    _kn_hl_from = None
                    _kn_hl_to = None
                    if _kn_size_mode == "Highlight Period":
                        _h1k, _h2k = st.columns(2)
                        _kn_hl_from = _h1k.date_input("Highlight Period From:", value=_cached_pf,
                                                      min_value=_date_ua(2000, 1, 1), max_value=_FAR_FUTURE_UA,
                                                      key="ume_deep_ua_kn_hl_from")
                        _kn_hl_to = _h2k.date_input("Highlight Period To:", value=_cached_pt,
                                                    min_value=_date_ua(2000, 1, 1), max_value=_FAR_FUTURE_UA,
                                                    key="ume_deep_ua_kn_hl_to")
                    _kn_tsne_perp = 30
                    if _kn_dim == "t-SNE":
                        _kn_tsne_perp = int(st.number_input("Perplexity:", value=30, step=1, min_value=2,
                                                            key="ume_deep_ua_kn_tsne_perp"))

                    def _norm_date(_s):
                        try:
                            return pd.to_datetime(str(_s)).date()
                        except Exception:
                            return None

                    def _png_kn(_fig):
                        _buf = _io_kn.BytesIO()
                        _fig.savefig(_buf, format="png", dpi=140, bbox_inches="tight")
                        plt.close(_fig)
                        return _buf.getvalue()

                    def _build_scatter(_rows_with_bn, _title):
                        """_rows_with_bn: list of dicts with '__bn__' key per row. Plots all chunks <=period_to,
                        colors only those referenced in period, others lightgray.
                        Returns (png_bytes, df_for_table)."""
                        if not _rows_with_bn:
                            return None, pd.DataFrame()
                        _kept = []
                        for _r in _rows_with_bn:
                            if _kn_exclude_private:
                                _pv = _r.get("private")
                                if _pv is True or str(_pv).lower() == "true":
                                    continue
                            _cd = _r.get("create_date")
                            _d = _norm_date(_cd)
                            if _d is not None and _d > _cached_pt:
                                continue
                            _v = _r.get("vector_data_value_text")
                            if not _v:
                                continue
                            _kept.append(_r)
                        if not _kept:
                            return None, pd.DataFrame()
                        _df_in = pd.DataFrame(_kept)
                        try:
                            _df_red, _info = dmva.reduce_dimensions(
                                _df_in, method=_kn_dim,
                                params={"perplexity": _kn_tsne_perp} if _kn_dim == "t-SNE" else {})
                        except Exception as _e:
                            return None, pd.DataFrame()
                        _x = _df_red["X1"].values
                        _y = _df_red["X2"].values
                        _ids = _df_red["id"].astype(str).tolist()
                        _bns = [_r.get("__bn__", "") for _r in _kept]
                        _rags = [_r.get("__rag_name__", "") for _r in _kept]
                        _cats = (_df_red["category"].fillna("Unset").astype(str).tolist()
                                 if "category" in _df_red.columns else ["Unset"] * len(_ids))
                        _titles = (_df_red["title"].fillna("").astype(str).tolist()
                                   if "title" in _df_red.columns else _ids)
                        _cdates = (_df_red["create_date"].fillna("").astype(str).tolist()
                                   if "create_date" in _df_red.columns else [""] * len(_ids))
                        _is_ref = [((_bns[_i], _ids[_i]) in _chunk_refs) for _i in range(len(_ids))]
                        _cats_in_period = sorted(set(_cats[_i] for _i in range(len(_ids)) if _is_ref[_i]))
                        _tab_c = plt.cm.get_cmap("tab10", max(len(_cats_in_period), 1))
                        _cat2col = {}
                        for _i, _c in enumerate(_cats_in_period):
                            _cat2col[_c] = _cat_color_map_kn.get(_c) or _tab_c(_i)
                        _sizes = [50] * len(_ids)
                        if _kn_size_mode == "Newer=Larger":
                            _ds = pd.to_datetime(_cdates, errors="coerce")
                            if _ds.notna().any():
                                _mn = _ds.min().timestamp(); _mx = _ds.max().timestamp()
                                _rg = _mx - _mn if _mx > _mn else 1
                                _sizes = [10 + 190 * ((_dx.timestamp() - _mn) / _rg) if pd.notna(_dx) else 10 for _dx in _ds]
                        elif _kn_size_mode == "Highlight Period" and _kn_hl_from is not None and _kn_hl_to is not None:
                            _hf = _kn_hl_from.isoformat(); _ht = _kn_hl_to.isoformat()
                            _sizes = []
                            for _i_ in range(len(_ids)):
                                _hit = False
                                if _is_ref[_i_]:
                                    for _r2 in (_chunk_refs.get((_bns[_i_], _ids[_i_])) or []):
                                        _tsd = (_r2.get("ts") or "")[:10]
                                        if _tsd and _hf <= _tsd <= _ht:
                                            _hit = True; break
                                _sizes.append(220 if _hit else 25)
                        _fig, _ax = plt.subplots(figsize=(9, 6))
                        _gray = (0.55, 0.55, 0.55, 0.6)
                        _gx = []; _gy = []; _gs = []
                        for _i_ in range(len(_ids)):
                            if not _is_ref[_i_]:
                                _gx.append(_x[_i_]); _gy.append(_y[_i_]); _gs.append(_sizes[_i_])
                        if _gx:
                            _ax.scatter(_gx, _gy, color=_gray, s=_gs, edgecolors="white", linewidths=0.4)
                        for _c in _cats_in_period:
                            _xs = []; _ys = []; _ss = []
                            for _i_ in range(len(_ids)):
                                if _is_ref[_i_] and _cats[_i_] == _c:
                                    _xs.append(_x[_i_]); _ys.append(_y[_i_]); _ss.append(_sizes[_i_])
                            if _xs:
                                _ax.scatter(_xs, _ys, color=_cat2col[_c], s=_ss, alpha=0.85,
                                            edgecolors="white", linewidths=0.6)
                        from matplotlib.lines import Line2D as _L2D_kn
                        _lh = []
                        _lh.append(_L2D_kn([0], [0], marker="o", linestyle="",
                                            markerfacecolor=_gray, markeredgecolor="white",
                                            markersize=8, label="Not referenced in period"))
                        for _c in _cats_in_period:
                            _lh.append(_L2D_kn([0], [0], marker="o", linestyle="",
                                                color=_cat2col[_c], markersize=8, label=_c))
                        if _lh:
                            _ax.legend(handles=_lh, loc="upper left", bbox_to_anchor=(1.02, 1), fontsize=8)
                        _ax.set_title(f"{_kn_dim} | {_title} (chunks≤{_cached_pt}, n={len(_ids)})\n{_info}")
                        _ax.grid(True, alpha=0.3)
                        _ax.set_xlabel("X1"); _ax.set_ylabel("X2")
                        _png = _png_kn(_fig)
                        _rows_out = []
                        for _i_ in range(len(_ids)):
                            _refs2 = _chunk_refs.get((_bns[_i_], _ids[_i_])) or []
                            _sQs = [r["sQ"] for r in _refs2]
                            _arr = _np_k.array([r["sQ"] - r["sA"] for r in _refs2]) if _refs2 else _np_k.array([])
                            _rows_out.append({
                                "RAG_NAME": _rags[_i_],
                                "Bucket": _bns[_i_],
                                "ID": _ids[_i_],
                                "Title": _titles[_i_],
                                "Category": _cats[_i_],
                                "CreateDate": _cdates[_i_],
                                "X1": round(float(_x[_i_]), 3),
                                "X2": round(float(_y[_i_]), 3),
                                "Ref count": len(_refs2),
                                "Ref in period": "Y" if _is_ref[_i_] else "",
                                "Avg similarity_Q": round(float(sum(_sQs) / len(_sQs)), 3) if _sQs else None,
                                "Knowledge utility (sum)": round(float(_arr.sum()), 3) if _refs2 else None,
                                "Knowledge utility (avg)": round(float(_arr.mean()), 3) if _refs2 else None,
                                "Knowledge utility (median)": round(float(_np_k.median(_arr)), 3) if _refs2 else None,
                                "Knowledge utility (max)": round(float(_arr.max()), 3) if _refs2 else None,
                                "Knowledge utility (min)": round(float(_arr.min()), 3) if _refs2 else None,
                                "Knowledge utility (var)": round(float(_arr.var()), 3) if _refs2 else None,
                            })
                        return _png, pd.DataFrame(_rows_out)

                    _total_rows = []
                    _rows_by_rag = {}
                    for _bn, _rs in _all_chunks_by_bn.items():
                        _rn = _col_to_rag_name_ua.get(_bn, _bn)
                        for _r in (_rs or []):
                            _r2 = dict(_r)
                            _r2["__bn__"] = _bn
                            _r2["__rag_name__"] = _rn
                            _r2["id"] = str(_r.get("id") or "")
                            _total_rows.append(_r2)
                            _rows_by_rag.setdefault(_rn, []).append(_r2)
                    if _total_rows:
                        st.markdown("**Total**")
                        try:
                            _png_t, _df_t = _build_scatter(_total_rows, _title="Total")
                        except Exception as _e:
                            _png_t, _df_t = None, pd.DataFrame()
                            st.warning(f"Error drawing Total: {_e}")
                        if _png_t is not None:
                            st.image(_png_t)
                        if not _df_t.empty:
                            st.dataframe(
                                _df_t.sort_values(["Ref in period", "Ref count"], ascending=[False, False]),
                                hide_index=True, use_container_width=True, height=320)

                    st.markdown("**Per RAG_NAME (2 columns)**")
                    try:
                        _agent_data_disp = dmu.read_json_file(_ua_af, agent_folder_path) or {}
                    except Exception:
                        _agent_data_disp = {}
                    _rag_order = [_kn.get("RAG_NAME") for _kn in _agent_data_disp.get("KNOWLEDGE", []) if _kn.get("RAG_NAME")]
                    _rag_keys = [_r for _r in _rag_order if _r in _rows_by_rag] + \
                                sorted([_r for _r in _rows_by_rag.keys() if _r not in _rag_order])
                    _rag_panels = []
                    for _rn in _rag_keys:
                        try:
                            _png_b, _df_b = _build_scatter(_rows_by_rag[_rn], _title=f"RAG_NAME: {_rn}")
                        except Exception as _e:
                            _png_b, _df_b = None, pd.DataFrame()
                            st.warning(f"Error drawing {_rn}: {_e}")
                        if _png_b is not None:
                            _rag_panels.append((_rn, _png_b, _df_b))
                    for _i in range(0, len(_rag_panels), 2):
                        _row = _rag_panels[_i:_i + 2]
                        _cols = st.columns(len(_row))
                        for _j, (_rn, _pb, _df_b) in enumerate(_row):
                            _cols[_j].image(_pb, caption=f"RAG_NAME: {_rn}")
                    for _rn, _pb, _df_b in _rag_panels:
                        if not _df_b.empty:
                            with st.expander(f"Data list: {_rn}", expanded=False):
                                st.dataframe(
                                    _df_b.sort_values(["Ref in period", "Ref count"], ascending=[False, False]),
                                    hide_index=True, use_container_width=True, height=320)

        _um_twin_chat(_uid, "ume_deep")

    # ===== Tab: Group understanding =====
    with _tab_cross:
        import DigiM_VAnalytics as _dmva_g
        st.markdown("#### Select target users")
        _cohort = st.multiselect("Target users", _all_users,
                                  default=list(_all_users), key="ume_cross_users")
        st.caption(f"{len(_cohort)} selected")
        if not _cohort:
            st.info("Please select at least one target user.")
        else:
            _b5L = [ux.BIG5_JA.get(t, t) for t in ux.BIG5_TRAITS]
            _emL = [ux.PLUTCHIK_JA.get(e, e) for e in ux.PLUTCHIK_PRIMARY]

            # ---------- Persona ----------
            st.markdown("### Persona")
            _b5s = ux.cohort_big5_stats(_cohort, "")
            _pc1, _pc2 = st.columns([1, 1])
            with _pc1:
                st.pyplot(_radar3(_b5L, [
                    ("Max", "#d62728", [_b5s[t]["max"] for t in ux.BIG5_TRAITS]),
                    ("Mean", "#1f77b4", [_b5s[t]["mean"] for t in ux.BIG5_TRAITS]),
                    ("Min", "#2ca02c", [_b5s[t]["min"] for t in ux.BIG5_TRAITS]),
                ], "Big5 (max / mean / min)"))
            with _pc2:
                st.dataframe(pd.DataFrame([
                    {"Trait": ux.BIG5_JA.get(t, t), "Max": _b5s[t]["max"],
                     "Mean": _b5s[t]["mean"], "Min": _b5s[t]["min"]}
                    for t in ux.BIG5_TRAITS]), hide_index=True)

            _ptext = "\n".join(ux.persona_text(u, "") for u in _cohort)
            _pf = ux.word_freq(_ptext)
            if _pf:
                _wcf = _dmva_g.make_wordcloud_figure(_pf, title="Persona", width=560, height=300)
                if _wcf is not None:
                    st.pyplot(_wcf)

            _pkmax = max(2, len(_cohort))
            _pk = st.number_input("Persona cluster count", 2, _pkmax,
                                  min(3, _pkmax), key="ume_cross_pk")
            if st.button("Run Persona clustering", key="ume_cross_pcl"):
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
                    if st.button("Explain clusters (Persona)", key="ume_cross_pexp_btn"):
                        with st.spinner("Generating explanation..."):
                            st.session_state["_ume_pexp"] = ux.explain_clusters(_pcl["summary"])
                    if st.session_state.get("_ume_pexp"):
                        st.markdown(st.session_state["_ume_pexp"])

            # ---------- Nowaday ----------
            st.markdown("### Nowaday")
            _es = ux.cohort_basic_emotion_stats(_cohort, "")
            _nc1, _nc2 = st.columns([1, 1])
            with _nc1:
                st.pyplot(_radar3(_emL, [
                    ("Max", "#d62728", [_es[e]["max"] for e in ux.PLUTCHIK_PRIMARY]),
                    ("Mean", "#1f77b4", [_es[e]["mean"] for e in ux.PLUTCHIK_PRIMARY]),
                    ("Min", "#2ca02c", [_es[e]["min"] for e in ux.PLUTCHIK_PRIMARY]),
                ], "Basic emotions (max / mean / min)"))
            with _nc2:
                st.dataframe(pd.DataFrame([
                    {"Emotion": ux.PLUTCHIK_JA.get(e, e), "Max": _es[e]["max"],
                     "Mean": _es[e]["mean"], "Min": _es[e]["min"]}
                    for e in ux.PLUTCHIK_PRIMARY]), hide_index=True)

            _sec = ux.agg_secondary_emotions(_cohort, "")
            if _sec:
                st.markdown("**Secondary-emotion ranking (total count)**")
                st.dataframe(pd.DataFrame([
                    {"Secondary emotion": ux.PLUTCHIK_JA.get(k, k), "Count": c}
                    for k, c in _sec.most_common()]), hide_index=True)

            _nfc = ux.nowaday_field_corpus(_cohort, "")
            st.markdown("**Nowaday word cloud**")
            _wcc = st.columns(2)
            for _i, (_fk, _fl) in enumerate(
                    [("summary", "Summary"), ("recurring", "Recurring"),
                     ("emerging", "Emerging"), ("declining", "Declining"), ("shifts", "Shifts")]):
                _fr = ux.word_freq(_nfc.get(_fk, ""))
                if _fr:
                    _wf = _dmva_g.make_wordcloud_figure(_fr, title=_fl, width=360, height=220)
                    if _wf is not None:
                        _wcc[_i % 2].pyplot(_wf)
                else:
                    _wcc[_i % 2].caption(f"{_fl}: no data")

            _nkmax = max(2, len(_cohort))
            _nk = st.number_input("Nowaday cluster count", 2, _nkmax,
                                  min(3, _nkmax), key="ume_cross_nk")
            if st.button("Run Nowaday clustering", key="ume_cross_ncl"):
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
                    if st.button("Explain clusters (Nowaday)", key="ume_cross_nexp_btn"):
                        with st.spinner("Generating explanation..."):
                            st.session_state["_ume_nexp"] = ux.explain_clusters(_ncl["summary"])
                    if st.session_state.get("_ume_nexp"):
                        st.markdown(st.session_state["_ume_nexp"])

            # ---------- History emotion trajectory (total) ----------
            st.markdown("### History emotion trajectory (total)")
            _ht = ux.cohort_history_emotion_totals(_cohort, "")
            if _ht:
                st.bar_chart(pd.Series(
                    {ux.PLUTCHIK_JA.get(k, k): v for k, v in _ht.items()}, name="Count"))
                st.caption(f"Total across all History entries for the {len(_cohort)} selected users: "
                           + "、".join(f"{ux.PLUTCHIK_JA.get(k,k)}={v}"
                                       for k, v in list(_ht.items())[:8]))
            else:
                st.caption("History has not been generated yet")

            # ---------- Chat with this Group Twin ----------
            _um_group_twin(_cohort, "ume_cross")

    # ===== Tab: My Memory (view/edit own memory only) =====
    with _tab_edit:
        import DigiM_UserMemory as _dmum_e
        _me = st.session_state.get("user_id", "")
        st.caption(f"Target: **{_me}** (you can edit only your own user memory)")
        if not _me:
            st.info("Could not identify the logged-in user.")
        else:
            _mb = ux.load_bundle(_me, "")
            _emo_all = list(ux.PLUTCHIK_PRIMARY) + list(ux.PLUTCHIK_SECONDARY)
            _stat_opts = ["approved", "pending", "deleted"]

            # ---- Persona ----
            with st.expander("Edit Persona (long-term)", expanded=True):
                _pr = _mb["persona"] or {}
                if not _pr:
                    st.caption("Persona has not been generated yet")
                else:
                    _role = st.text_input("Role", value=_pr.get("role", ""), key="ume_e_role")
                    # Regenerate the Persona Summary draft (not persisted until the save button is pressed)
                    _pcg1, _pcg2 = st.columns([1, 4])
                    if _pcg1.button("Regenerate Summary draft", key="ume_e_regen_persona"):
                        import DigiM_GeneUserMemory as _gum
                        with st.spinner("Regenerating Persona summary..."):
                            try:
                                _draft = _gum.merge_persona(_pr.get("service_id", ""), _me, save=False)
                                if _draft and _draft.get("summary_text"):
                                    st.session_state["ume_e_summary"] = _draft["summary_text"]
                                    st.session_state.sidebar_message = "Regenerated Persona summary draft (apply via \"Save Persona\")"
                                    st.rerun()
                                else:
                                    st.warning("Could not regenerate (a Nowaday profile is required)")
                            except Exception as e:
                                st.error(f"Regeneration error: {type(e).__name__}: {e}")
                    _pcg2.caption("* Generating a draft does NOT save it; press \"Save Persona\" below.")
                    _summary = st.text_area("Summary text", value=_pr.get("summary_text", ""),
                                            height=120, key="ume_e_summary")
                    _flds = {
                        "expertise": "Expertise", "recurring_interests": "Interests",
                        "values_principles": "Values", "constraints": "Constraints",
                        "communication_style": "Tone / explanation preference", "avoid_topics": "Topics to avoid",
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
                    if st.button("Save Persona", key="ume_e_save_persona"):
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
                        st.session_state.sidebar_message = "Saved Persona"
                        st.rerun()

            # ---- Nowaday ----
            with st.expander("Edit Nowaday (recent trends)"):
                # Generate a new snapshot (with a period; appended as new, never overwrites existing snapshots)
                st.markdown("**Generate a new snapshot**")
                _ngc1, _ngc2, _ngc3 = st.columns([1.5, 1.5, 1])
                _pmode = _ngc1.selectbox("Period mode",
                                          ["YYYY-MM", "since_YYYY-MM-DD", "rolling_<N>d", "all"],
                                          key="ume_e_nw_pmode")
                _period_val = "all"
                if _pmode == "YYYY-MM":
                    _ym = _ngc2.text_input("YYYY-MM", value=datetime.now().strftime("%Y-%m"), key="ume_e_nw_ym")
                    _period_val = (_ym or "").strip() or datetime.now().strftime("%Y-%m")
                elif _pmode == "since_YYYY-MM-DD":
                    _sd = _ngc2.date_input("Since", value=(datetime.now() - timedelta(days=30)).date(), key="ume_e_nw_sd")
                    _period_val = f"since_{_sd.isoformat()}"
                elif _pmode == "rolling_<N>d":
                    _nd = _ngc2.number_input("N days", min_value=1, max_value=365, value=30, step=1, key="ume_e_nw_nd")
                    _period_val = f"rolling_{int(_nd)}d"
                if _ngc3.button("Generate new snapshot", key="ume_e_nw_gen"):
                    import DigiM_GeneUserMemory as _gum_nw
                    _svc_for_nw = ((_mb.get("nowaday") or [{}])[0].get("service_id", "") if _mb.get("nowaday") else "")
                    with st.spinner(f"Generating Nowaday ({_period_val})..."):
                        try:
                            _new = _gum_nw.build_nowaday_profile(_svc_for_nw, _me, _period_val)
                            if _new:
                                st.session_state.sidebar_message = f"Generated Nowaday snapshot ({_period_val})"
                                st.rerun()
                            else:
                                st.warning("No History entries in the period")
                        except Exception as e:
                            st.error(f"Generation error: {type(e).__name__}: {e}")
                st.markdown("---")
                _nws = _mb["nowaday"]
                if not _nws:
                    st.caption("Nowaday has not been generated yet")
                else:
                    # _nws is sorted by generated_at descending; uniquely identified by period @ generation time
                    _nw_opts = {
                        f"{m.get('period','')} @ {m.get('generated_at','')}": m for m in _nws
                    }
                    _osel = st.selectbox("Snapshot (period @ generated_at; top is latest)",
                                         list(_nw_opts.keys()), key="ume_e_nw_period")
                    _nw = _nw_opts[_osel]
                    _psel = _nw.get("period", "")
                    _k = "".join(ch for ch in str(_nw.get("id", _osel)) if ch.isalnum() or ch == "_")
                    _nw_sum = st.text_area("Summary text", value=_nw.get("summary_text", ""),
                                           height=110, key=f"ume_e_nw_sum_{_k}")
                    _listflds = {"recurring_topics": "Recurring topics", "emerging": "Emerging interests",
                                 "declining": "Declining topics", "shifts": "Shifts"}
                    for _lf, _lj in _listflds.items():
                        st.text_area(f"{_lj} (one per line)",
                                     value="\n".join(str(x) for x in (_nw.get(_lf) or [])),
                                     height=80, key=f"ume_e_nw_{_lf}_{_k}")
                    st.markdown("**Basic emotions (intensity 0-1)**")
                    _be = _nw.get("basic_emotions") or {}
                    _bcols = st.columns(4)
                    for _ei, _e in enumerate(ux.PLUTCHIK_PRIMARY):
                        _bcols[_ei % 4].number_input(
                            f"{ux.PLUTCHIK_JA.get(_e,_e)}", min_value=0.0, max_value=1.0,
                            value=float(_be.get(_e, 0) or 0), step=0.05,
                            key=f"ume_e_nw_be_{_e}_{_k}")
                    _sec_cur = [s for s in (_nw.get("secondary_emotions") or []) if s in ux.PLUTCHIK_SECONDARY]
                    st.multiselect("Secondary emotions", list(ux.PLUTCHIK_SECONDARY), default=_sec_cur,
                                   format_func=lambda s: ux.PLUTCHIK_JA.get(s, s),
                                   key=f"ume_e_nw_sec_{_k}")
                    if st.button("Save Nowaday", key=f"ume_e_save_nw_{_k}"):
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
                        st.session_state.sidebar_message = f"Saved Nowaday ({_psel})"
                        st.rerun()

            # ---- History ----
            with st.expander("Edit History (session summary)"):
                _hs = _mb["history"]
                if not _hs:
                    st.caption("History has not been generated yet")
                else:
                    _hopts = {
                        f"{str(h.get('create_date') or '')[:16]} | {str(h.get('topic') or '')[:30]} | {h.get('session_id','')}": h
                        for h in _hs}
                    _hsel = st.selectbox("Session", list(_hopts.keys()), key="ume_e_h_sel")
                    _h = _hopts[_hsel]
                    _hk = _h.get("session_id", "x")
                    st.text_input("Topic", value=_h.get("topic", ""), key=f"ume_e_h_topic_{_hk}")
                    st.text_area("Excerpt", value=_h.get("excerpt", ""), height=110,
                                 key=f"ume_e_h_exc_{_hk}")
                    _hemo = [e for e in (_h.get("emotions") or []) if e in _emo_all]
                    st.multiselect("Emotions (Plutchik)", _emo_all, default=_hemo,
                                   format_func=lambda s: ux.PLUTCHIK_JA.get(s, s),
                                   key=f"ume_e_h_emo_{_hk}")
                    st.number_input("confidence", min_value=0.0, max_value=1.0,
                                    value=float(_h.get("confidence") or 0.0), step=0.05,
                                    key=f"ume_e_h_conf_{_hk}")
                    st.checkbox("Active -- uncheck to exclude from lists/context",
                                value=((_h.get("active") or "Y") == "Y"),
                                key=f"ume_e_h_act_{_hk}")
                    if st.button("Save History", key=f"ume_e_save_h_{_hk}"):
                        _u = dict(_h)
                        _u["topic"] = st.session_state.get(f"ume_e_h_topic_{_hk}", _u.get("topic", ""))
                        _u["excerpt"] = st.session_state.get(f"ume_e_h_exc_{_hk}", _u.get("excerpt", ""))
                        _u["emotions"] = list(st.session_state.get(f"ume_e_h_emo_{_hk}", []))
                        _u["confidence"] = float(st.session_state.get(f"ume_e_h_conf_{_hk}", 0.0))
                        _u["active"] = "Y" if st.session_state.get(f"ume_e_h_act_{_hk}", True) else "N"
                        _dmum_e.upsert("history", _u)
                        st.session_state.sidebar_message = "Saved History"
                        st.rerun()

    # =========================================================
    # Export Report
    # =========================================================
    st.markdown("---")
    st.subheader("Export Report")
    if st.button("Generate Report", key="ume_gen_report"):
        _now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _r = [f"# User Memory Explorer {_now}", ""]

        # ---- User understanding (individual) ----
        _ud = st.session_state.get("ume_deep_user")
        if _ud:
            _r.append("## User understanding (individual)")
            _r.append(f"- **Target user:** {_ud}")
            _bd = ux.load_bundle(_ud, "")
            _pp = _bd.get("persona") or {}
            if _pp:
                _r.append(f"- **Role:** {_pp.get('role','') or '-'}")
                if _pp.get("summary_text"):
                    _r.append(f"- **Summary:** {_pp.get('summary_text')}")
                _b5 = _pp.get("big5") or {}
                _b5lines = []
                for _t in ux.BIG5_TRAITS:
                    _it = _b5.get(_t) or {}
                    if isinstance(_it, dict) and (_it.get("status") or "").lower() != "deleted":
                        _b5lines.append(f"{ux.BIG5_JA.get(_t,_t)}={float(_it.get('score',0.5) or 0.5):.2f}({_it.get('status','')})")
                if _b5lines:
                    _r.append("- **Big5:** " + "、".join(_b5lines))
            if _bd["nowaday"]:
                _nw = _bd["nowaday"][0]
                _r.append("")
                _r.append(f"### Nowaday (latest: period={_nw.get('period','')}, generated_at={_nw.get('generated_at','')})")
                if _nw.get("summary_text"):
                    _r.append(_nw["summary_text"])
                _be = _nw.get("basic_emotions") or {}
                _r.append("- **Basic emotions:** " + ", ".join(
                    f"{ux.PLUTCHIK_JA.get(e,e)}={float(_be.get(e,0) or 0):.2f}" for e in ux.PLUTCHIK_PRIMARY))
                if _nw.get("secondary_emotions"):
                    _r.append("- **Secondary emotions:** " + ", ".join(
                        ux.PLUTCHIK_JA.get(s,s) for s in _nw["secondary_emotions"]))
                for _lbl, _k in (("Recurring","recurring_topics"),("Emerging","emerging"),
                                 ("Declining","declining"),("Shifts","shifts")):
                    if _nw.get(_k):
                        _r.append(f"- **{_lbl}:** " + "、".join(str(x) for x in _nw[_k]))
            _traj_all = ux.user_emotion_trajectory(_ud, "")
            if _traj_all:
                _rng = st.session_state.get("ume_deep_traj_period")
                _s = _e = ""
                if isinstance(_rng, (list, tuple)) and len(_rng) == 2:
                    _s, _e = _rng[0].isoformat(), _rng[1].isoformat()
                    _tj = [t for t in _traj_all if _s <= t[0] <= _e]
                else:
                    _tj = _traj_all
                from collections import Counter as _C
                _ct = _C()
                for _d, _t, _es in _tj:
                    for _x in _es:
                        _ct[ux.PLUTCHIK_JA.get(_x, _x)] += 1
                _r.append("")
                _r.append(f"### History emotion trajectory ({_s or 'all'} - {_e or 'now'}, {len(_tj)} / total {len(_traj_all)})")
                if _ct:
                    _r.append("- **Aggregate:** " + ", ".join(f"{k}={v}" for k, v in _ct.most_common()))
            _dh = st.session_state.get("_ume_deep_hist") or []
            if _dh:
                _r.append("")
                _r.append("### Chat with this User Twin")
                for _h in _dh:
                    _r.append(f"- **[{_h.get('timestamp','')}] {_h.get('agent','')}**")
                    _r.append(f"  - Q: {_h.get('query','')}")
                    _r.append(f"  - A: {_h.get('response','')}")
            _r.append("")

        # ---- Group understanding ----
        _ch = st.session_state.get("ume_cross_users") or []
        if _ch:
            _r.append("## Group understanding")
            _r.append(f"- **Target users ({len(_ch)}):** " + ", ".join(_ch))
            _b5s = ux.cohort_big5_stats(_ch, "")
            _r.append("")
            _r.append("### Persona — Big5 (max/mean/min)")
            _r.append("| Trait | Max | Mean | Min |")
            _r.append("|---|---|---|---|")
            for _t in ux.BIG5_TRAITS:
                _r.append(f"| {ux.BIG5_JA.get(_t,_t)} | {_b5s[_t]['max']:.2f} | {_b5s[_t]['mean']:.2f} | {_b5s[_t]['min']:.2f} |")
            _es = ux.cohort_basic_emotion_stats(_ch, "")
            _r.append("")
            _r.append("### Nowaday - basic emotions (max/mean/min)")
            _r.append("| Emotion | Max | Mean | Min |")
            _r.append("|---|---|---|---|")
            for _e in ux.PLUTCHIK_PRIMARY:
                _r.append(f"| {ux.PLUTCHIK_JA.get(_e,_e)} | {_es[_e]['max']:.2f} | {_es[_e]['mean']:.2f} | {_es[_e]['min']:.2f} |")
            _sec = ux.agg_secondary_emotions(_ch, "")
            if _sec:
                _r.append("")
                _r.append("### Secondary-emotion ranking")
                _r.append("- " + "、".join(f"{ux.PLUTCHIK_JA.get(k,k)}({c})" for k, c in _sec.most_common()))
            _pc = st.session_state.get("_ume_pcluster") or {}
            if _pc.get("df") is not None:
                _r.append("")
                _r.append(f"### Persona clustering ({_pc.get('info','')})")
                _r.append(_pc["df"].to_markdown(index=False))
                if st.session_state.get("_ume_pexp"):
                    _r.append("")
                    _r.append("#### Cluster explanation")
                    _r.append(str(st.session_state["_ume_pexp"]))
            _nc = st.session_state.get("_ume_ncluster") or {}
            if _nc.get("df") is not None:
                _r.append("")
                _r.append(f"### Nowaday clustering ({_nc.get('info','')})")
                _r.append(_nc["df"].to_markdown(index=False))
                if st.session_state.get("_ume_nexp"):
                    _r.append("")
                    _r.append("#### Cluster explanation")
                    _r.append(str(st.session_state["_ume_nexp"]))
            _ht = ux.cohort_history_emotion_totals(_ch, "")
            if _ht:
                _r.append("")
                _r.append("### History emotion trajectory (total)")
                _r.append("- " + "、".join(f"{ux.PLUTCHIK_JA.get(k,k)}={v}" for k, v in _ht.items()))
            _gsys = st.session_state.get("_ume_cross_gtwin_sys")
            if _gsys:
                _r.append("")
                _r.append("### Group Twin System Prompt")
                _r.append("```\n" + _gsys + "\n```")
            _gh = st.session_state.get("_ume_cross_g_hist") or []
            if _gh:
                _r.append("")
                _r.append("### Chat with this Group Twin")
                for _h in _gh:
                    _r.append(f"- **[{_h.get('timestamp','')}] {_h.get('agent','')}**")
                    _r.append(f"  - Q: {_h.get('query','')}")
                    _r.append(f"  - A: {_h.get('response','')}")
            _r.append("")

        _r.append(f"\n---\nGenerated: {_now}")
        _report_text = "\n".join(_r)
        st.session_state._ume_report = _report_text
        try:
            _label = (_ud or "") + (f"+{len(_ch)}users" if _ch else "")
            _saved = _ume_save_session(_label or "session")
            st.success(f"Generated report and saved the session: {_saved}")
        except Exception as e:
            st.success("Report generated")
            st.warning(f"Failed to save the session: {e}")

    if st.session_state.get("_ume_report"):
        _rname = f"UserMemoryExplorer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        st.download_button("Download (.md)", data=st.session_state._ume_report.encode("utf-8"),
                           file_name=f"{_rname}.md", mime="text/markdown", key="ume_dl_md")


### Support Agent Test screen ###
def _support_agent_test():
    """Support-Agent evaluation (the legacy sidebar Support Eval, moved to the main view)."""
    st.subheader("Support Agent Test")

    _agent_file = st.session_state.get("agent_file", "")
    _eval_targets = {}
    if _agent_file:
        try:
            _eval_targets = dmse.get_support_targets(_agent_file)
        except Exception:
            pass

    st.caption(f"Target agent: {_agent_file or '(none selected)'}")
    if not _eval_targets:
        st.info("The selected agent has no support agent configured.")
        return

    _target_options = {v["label"]: k for k, v in _eval_targets.items()}
    _target_options["Both"] = "both"
    _selected_label = st.selectbox("Target", list(_target_options.keys()), key="eval_target_select")
    _selected_target = _target_options[_selected_label]

    _all_engines = []
    for k, v in _eval_targets.items():
        if _selected_target in ("both", k):
            _all_engines.extend(v["engines"])
    _all_engines = list(dict.fromkeys(_all_engines))
    _selected_engines = st.multiselect("Engines", _all_engines, default=_all_engines, key="eval_engines")

    _num_questions = st.number_input("Question count", min_value=1, max_value=20, value=3, key="eval_num_q")
    _default_questions = "What do you think about AI governance?\nWhat was a recent book you enjoyed?\nPlease introduce yourself"
    _questions_text = st.text_area("Questions (one per line)", value=_default_questions,
                                   height=120, key="eval_questions")
    _questions = [q.strip() for q in _questions_text.strip().split("\n") if q.strip()][:_num_questions]

    if st.button("Run evaluation", key="run_support_eval", disabled=bool(st.session_state._bg_task)):
        if not _selected_engines:
            st.warning("Please select engines")
        elif not _questions:
            st.warning("Please enter questions")
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
            _run_bg_task("eval", "Running support-agent evaluation", _run_eval)
            st.rerun()

    if st.session_state.eval_summary:
        st.dataframe(pd.DataFrame(st.session_state.eval_summary), hide_index=True)

    if st.session_state.eval_results_excel:
        st.download_button(
            label="Result Excel",
            data=st.session_state.eval_results_excel,
            file_name=f"support_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_eval_excel"
        )


### Streamlit screens ###
def main():
    # Initialize the session state
    initialize_session_states()

    # Run the login flow
    if login_enable_flg == "Y":
        ensure_login()

    # Sidebar setup
    with st.sidebar:
        st.title(web_title)

        # Show the logged-in user info
        if login_enable_flg == "Y":
            if "login_user" in st.session_state and st.session_state.login_user:
                lu = st.session_state.login_user
                st.markdown(f"User: {lu.get('Name', '')}")
                if st.button("Logout"):
                    _clear_auth_cookie(_get_cookie_manager())
                    # Clear all UI cache (session_state).
                    # When another user logs in, don't leave behind the previous user's
                    # session list, agent settings, permission flags, etc.
                    _preserved = {"_cookie_manager"}
                    for key in list(st.session_state.keys()):
                        if key in _preserved:
                            continue
                        del st.session_state[key]
                    st.session_state._just_logged_out = True
                    st.rerun()

        # Switch the main view
        _view_options = ["Chat"]
        if st.session_state.allowed_knowledge_explorer:
            _view_options.append("Knowledge Explorer")
        if st.session_state.allowed_user_memory_explorer:
            _view_options.append("User Memory Explorer")
        if st.session_state.allowed_support_eval:
            _view_options.append("Support Agent Test")
        if st.session_state.allowed_scheduler:
            _view_options.append("Scheduler")
        if len(_view_options) > 1:
            _current = st.session_state.get("main_view", "Chat")
            _view_index = _view_options.index(_current) if _current in _view_options else 0
            st.session_state.main_view = st.radio("View:", _view_options, index=_view_index, horizontal=True, label_visibility="collapsed")
        else:
            st.session_state.main_view = "Chat"

        # Select the agent (JSON)
        if agent_id_selected := st.selectbox("Select Agent:", st.session_state.agent_list, index=st.session_state.agent_list_index):
            if st.session_state.agent_id != agent_id_selected:
                # Reset ORG / Persona selection when the agent changes
                st.session_state.selected_org = None
                st.session_state.selected_persona_ids = []
            st.session_state.agent_id = agent_id_selected
            st.session_state.agent_file = next((a2["FILE"] for a2 in st.session_state.agents if a2["AGENT"] == st.session_state.agent_id), None)
            st.session_state.agent_data = dmu.read_json_file(st.session_state.agent_file, agent_folder_path)
            st.session_state.engine_name = st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}).get("DEFAULT", "")
            st.session_state.imagegen_engine_name = st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}).get("DEFAULT", "")

        # ORG / Persona selection (only when the agent has ORG defined)
        _agent_orgs = st.session_state.agent_data.get("ORG") or []
        if isinstance(_agent_orgs, list) and _agent_orgs:
            def _format_org(org_dict):
                if not isinstance(org_dict, dict) or not org_dict:
                    return "(empty)"
                return ", ".join(f"{k}={v}" for k, v in org_dict.items())

            _org_labels = [_format_org(o) for o in _agent_orgs]
            _label_to_org = dict(zip(_org_labels, _agent_orgs))

            # If there's an existing selection, restore that index; otherwise pick the first
            _current_idx = 0
            if st.session_state.selected_org in _agent_orgs:
                _current_idx = _agent_orgs.index(st.session_state.selected_org)
            _selected_label = st.selectbox("ORG:", _org_labels, index=_current_idx, key="org_select")
            _selected_org = _label_to_org[_selected_label]
            if st.session_state.selected_org != _selected_org:
                st.session_state.selected_org = _selected_org
                st.session_state.selected_persona_ids = []  # Reset Persona selection when ORG changes

            # Fetch personas matching the ORG
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
                st.warning(f"Failed to fetch personas: {_e}")

            if _candidate_personas:
                _persona_labels = [f"{p['persona_id']}: {p['name']}" for p in _candidate_personas]
                _label_to_pid = {lbl: p["persona_id"] for lbl, p in zip(_persona_labels, _candidate_personas)}
                _pid_to_label = {p["persona_id"]: lbl for lbl, p in zip(_persona_labels, _candidate_personas)}
                _default_labels = [_pid_to_label[pid] for pid in st.session_state.selected_persona_ids if pid in _pid_to_label]
                _selected_labels = st.multiselect("Personas:", _persona_labels, default=_default_labels, key="persona_select")
                st.session_state.selected_persona_ids = [_label_to_pid[lbl] for lbl in _selected_labels]
                if len(st.session_state.selected_persona_ids) >= 2:
                    st.caption(f"Multi-persona parallel-execution mode ({len(st.session_state.selected_persona_ids)} personas)")
            else:
                st.caption("No matching personas")
                st.session_state.selected_persona_ids = []

        side_col1, side_col2 = st.columns(2)

        # Issue a new session (specify the ID, refresh the session anew)
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

        # Update the chat history
        if side_col2.button("Refresh List", key="refresh_session_list"):
            st.session_state.sidebar_message = ""
            refresh_session_list(st.session_state.service_id, st.session_state.user_id, st.session_state.user_admin_flg)

        # Select the agent's engines
        engines_expander = st.expander("Engines")
        with engines_expander:
            # LLM engine selection
            _engine_list = dma.get_engine_list(st.session_state.agent_data, model_type="LLM")
            if _engine_list:
                _engine_index = _engine_list.index(st.session_state.engine_name) if st.session_state.engine_name in _engine_list else 0
                st.session_state.engine_name = st.selectbox("Select Engine(LLM):", _engine_list, index=_engine_index)

            # IMAGEGEN engine selection
            _imagegen_engine_list = dma.get_engine_list(st.session_state.agent_data, model_type="IMAGEGEN")
            if _imagegen_engine_list:
                _imagegen_index = _imagegen_engine_list.index(st.session_state.imagegen_engine_name) if st.session_state.imagegen_engine_name in _imagegen_engine_list else 0
                st.session_state.imagegen_engine_name = st.selectbox("Select Engine(IMAGEGEN):", _imagegen_engine_list, index=_imagegen_index)

        # Session management
        sessions_expander = st.expander("Sessions")
        with sessions_expander:
            # Manage in-flight background jobs
            _running_jobs = djr.list_jobs(user_id=st.session_state.get("user_id")) if st.session_state.get("user_admin_flg") != "Y" else djr.list_jobs()
            st.markdown("**Background Jobs**")
            if not _running_jobs:
                st.caption("No jobs in flight")
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
                    st.session_state.sidebar_message = f"Requested cancellation for {_cancelled} background job(s)"
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
                st.session_state.sidebar_message = f"Re-displayed sessions ({activate_sessions_str})"
                st.rerun()

            # DB Export / Archive (shown only to users with Session Archive permission)
            if st.session_state.allowed_session_archive:
                st.markdown("---")

                # DB Export button (shown only when connection info is configured)
                if _db_configured:
                    # Connection test: lightweight psycopg2 SELECT 1 (5s timeout)
                    if st.button("Check DB Connection", key="db_check"):
                        with st.spinner("Checking DB connection..."):
                            try:
                                import psycopg2
                                _cfg = dict(dmdbe.DB_CONFIG)
                                _cfg["connect_timeout"] = 5
                                with psycopg2.connect(**_cfg) as _conn:
                                    with _conn.cursor() as _cur:
                                        _cur.execute("SELECT version()")
                                        _ver = _cur.fetchone()[0]
                                st.session_state.sidebar_message = f"DB connection OK: {_ver}"
                            except Exception as _e:
                                st.session_state.sidebar_message = f"DB connection failed: {_e}"
                        st.rerun()

                    if st.button("Export to DB", key="db_export"):
                        with st.spinner("Exporting to DB..."):
                            try:
                                dmdbe.main()
                                st.session_state.sidebar_message = "DB export completed"
                            except Exception as e:
                                st.session_state.sidebar_message = f"DB export error: {e}"
                        with st.spinner("Vectorizing..."):
                            try:
                                dmdbe.vectorize_dialogs()
                            except Exception as e:
                                st.session_state.sidebar_message += f" / Vectorization error: {e}"
                        st.rerun()

                # Archive button
                _archive_days = st.number_input(
                    "Archive Older Than (days)", min_value=1, value=30, step=1,
                    key="archive_days_input",
                    help="Compress sessions older than this many days (by last update date) into a ZIP",
                )
                if st.button("Archive Old Sessions", key="archive_sessions"):
                    with st.spinner("Archiving..."):
                        try:
                            result = dms.archive_old_sessions(days=int(_archive_days))
                            archived_count = len(result["archived"])
                            st.session_state.sidebar_message = f"Archive complete: compressed {archived_count} sessions"
                            st.session_state.last_archive_zip = result["zip_path"]
                        except Exception as e:
                            st.session_state.sidebar_message = f"Archive error: {e}"
                            st.session_state.last_archive_zip = None
                    st.rerun()

                # Archive ZIP download (always shown)
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
                    st.caption("No archive ZIPs available")

        # Knowledge update flow
        if st.session_state.allowed_rag_management:
            rag_expander = st.expander("RAG Management")
            with rag_expander:
                # RAG update flow
                if st.button("Update RAG Data", key="update_rag", disabled=bool(st.session_state._bg_task)):
                    def _rag_update():
                        dmc.generate_rag()
                        # Legacy UserDialog auto-save (kept for compat). Triggered when auto_save_flg=Y.
                        if cfg.user_dialog_auto_save_flg == "Y":
                            try:
                                dmgu.save_user_dialogs(st.session_state.web_service, st.session_state.web_user)
                            except Exception:
                                pass
                        # New short-term UserMemory: auto-process unsaved sessions
                        if (os.getenv("USER_MEMORY_HISTORY_AUTO_SAVE_FLG") or "N") == "Y":
                            import DigiM_GeneUserMemory as _dmgum_rag
                            try:
                                _dmgum_rag.save_history_for_unsaved_sessions()
                            except Exception:
                                pass
                    _run_bg_task("rag", "Updating RAG data", _rag_update)
                    st.rerun()

                # RAG deletion (delete all if none selected)
                st.session_state.rag_data_list_selected = st.multiselect("RAG DB", st.session_state.rag_data_list)
                if st.button("Delete RAG DB", key="delete_rag_db"):
                    dmc.del_rag_db(st.session_state.rag_data_list_selected)
                    st.session_state.sidebar_message = "Deleted RAG"
                    st.session_state.rag_data_list = dmc.get_rag_list()

                # PageIndex Export: download the selected PageIndex as a ZIP of Excel + individual files
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
                            st.error(f"Export failed: {_pi_err}")
                        if _pi_zip:
                            st.download_button(
                                "Download (Excel + Files)", data=_pi_zip,
                                file_name=f"{_pi_export}.zip", mime="application/zip",
                                key=f"pi_dl_{_pi_export}",
                            )

                # Save the session's user dialog
                if cfg.user_dialog_auto_save_flg == "N":
                    st.markdown("---")
                    st.markdown("**User Dialog**")
                    if st.button("Save User Dialog", key="save_user_dialog"):
                        dmgu.save_user_dialogs(st.session_state.web_service, st.session_state.web_user)
                        st.session_state.sidebar_message = "Saved the user dialog"

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

        # Schedule management is in a separate menu (Scheduler) and is not touched from RAG Management.

        # User Memory expander moved to the main area (below BOOK).

        # Web API management
        if st.session_state.allowed_web_api:
            api_expander = st.expander("Web API")
            with api_expander:
                import subprocess
                # Check FastAPI process status
                _api_check = subprocess.run(
                    ["pgrep", "-f", "uvicorn DigiM_API:app"],
                    capture_output=True, text=True
                )
                _api_running = _api_check.returncode == 0

                if _api_running:
                    st.success("FastAPI: Running (port 8899)")
                    if st.button("Stop API Server", key="stop_api"):
                        subprocess.run(["pkill", "-f", "uvicorn DigiM_API:app"])
                        st.session_state.sidebar_message = "Stopped FastAPI"
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
                        st.session_state.sidebar_message = "Started FastAPI"
                        st.rerun()

                # Health check
                if _api_running:
                    if st.button("Health Check", key="api_health"):
                        try:
                            import urllib.request
                            with urllib.request.urlopen("http://localhost:8899/health", timeout=5) as resp:
                                _health = resp.read().decode()
                            st.code(_health)
                        except Exception as e:
                            st.error(f"Health Check Failed: {e}")

        # Support-agent evaluation has moved to the "Support Agent Test" main view

        # Background-task monitor
        if st.session_state._bg_task:
            _task_status = _read_bg_task_status()
            if _task_status.get("status") == "done":
                if _task_status.get("error"):
                    st.error(f"Error: {_task_status['error']}")
                else:
                    st.session_state.sidebar_message = f"{_task_status.get('message', '')} completed"
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
                    st.info(f"⏳ {_ts.get('message', 'Running...')}")
                _task_monitor()

        st.write(st.session_state.sidebar_message)

        # Session list is shown only on the Chat screen
        if st.session_state.get("main_view", "Chat") == "Chat":
            st.markdown("----")
            # Session-name search filter
            _session_filter = st.text_input("Session Name:", value="", placeholder="Search (wildcard * supported)", label_visibility="collapsed")

            # Render the session list
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
                            # Session-name filter (wildcard * supported)
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
                                st.session_state.sidebar_message = f"Hid session ({session_id_list}_{session_name_list})"
                                st.rerun()
                            num_sessions += 1
                except Exception as e:
                    sid = session_dict["id"]
                    st.warning(f"Skipped session {sid} due to render error: {e}")
                    continue

        # Knowledge Explorer: saved analysis sessions
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

        # User Memory Explorer: saved analysis sessions
        elif st.session_state.get("main_view", "Chat") == "User Memory Explorer":
            st.markdown("----")
            _ume_base = "user/common/analytics/user_memory_explorer/"
            if os.path.exists(_ume_base):
                _ume_folders = sorted(
                    [f for f in os.listdir(_ume_base)
                     if os.path.isdir(os.path.join(_ume_base, f)) and f.startswith("analytics")],
                    reverse=True)
                for _sf in _ume_folders[:10]:
                    _meta_p = os.path.join(_ume_base, _sf, "meta.json")
                    if os.path.exists(_meta_p):
                        _m = dmu.read_json_file(_meta_p)
                        _label = f"{_m.get('created_at', '')[:10]} {_m.get('label', '')}"[:24]
                        if st.button(_label, key=f"ume_load_{_sf}"):
                            st.session_state._ume_load_folder = os.path.join(_ume_base, _sf)
                            st.rerun()

    # Switch main-area screens
    if st.session_state.get("main_view") == "Knowledge Explorer":
        _knowledge_explorer()
        return
    if st.session_state.get("main_view") == "User Memory Explorer":
        _user_memory_explorer()
        return
    if st.session_state.get("main_view") == "Support Agent Test":
        _support_agent_test()
        return
    if st.session_state.get("main_view") == "Scheduler":
        _scheduler_view()
        return

    # Configure the chat session name
    if session_name := st.text_input("Chat Name:", value=st.session_state.session.session_name):
        st.session_state.session = dms.DigiMSession(st.session_state.session.session_id, session_name)
        if session_name != dms.get_session_name(st.session_state.session.session_id) and dms.get_session_name(st.session_state.session.session_id) != "":
            if st.button("Change Session Name", key="chg_session_name"):
                st.session_state.session.chg_session_name(session_name)
                st.session_state.sidebar_message = "Changed the session name"
                st.rerun()

    # Web component layout
    header_col1, header_col2, header_col3, header_col4 = st.columns(4)

    # Time setup
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
            selected_time_setting = st.text_input("Situation Date:", key="custom_time_input", placeholder="e.g. 500 BC, Tenpo 3 Edo, AD 30000")
            if not selected_time_setting:
                selected_time_setting = datetime.combine(_cd_date, _cd_time).strftime("%Y/%m/%d %H:%M:%S")
    time_setting = str(selected_time_setting)
    st.session_state.time_setting = time_setting

    # Execution settings
    if st.session_state.allowed_exec_setting:
        header_col2.markdown("Exec Setting:")

        # Streaming setting
        if header_col2.checkbox("Streaming Mode", value=st.session_state.stream_mode):
            st.session_state.stream_mode = True
        else:
            st.session_state.stream_mode = False

        # Conversation memory toggle
        if header_col2.checkbox("Memory Use", value=st.session_state.memory_use):
            st.session_state.memory_use = True
        else:
            st.session_state.memory_use = False

        # Memory digest save toggle
        if header_col2.checkbox("Save Digest", value=st.session_state.save_digest):
            st.session_state.save_digest = True
        else:
            st.session_state.save_digest = False

        # Magic-word toggle
        if header_col2.checkbox("Magic Word", value=st.session_state.magic_word_use):
            st.session_state.magic_word_use = True
        else:
            st.session_state.magic_word_use = False

    #    # Memory save toggle
    #    if header_col2.checkbox("Memory Save", value=st.session_state.memory_save):
    #        st.session_state.memory_save = True
    #    else:
    #        st.session_state.memory_save = False

    #    # Memory similarity toggle
    #    if header_col2.checkbox("Memory Similarity", value=st.session_state.memory_similarity):
    #        st.session_state.memory_similarity = True
    #    else:
    #        st.session_state.memory_similarity = False


    # Execution settings
    if st.session_state.allowed_rag_setting:
        header_col3.markdown("RAG Setting:")

        # RAG search-query generation toggle
        if header_col3.checkbox("RAG Query Gen", value=st.session_state.RAG_query_gene):
            st.session_state.RAG_query_gene = True
        else:
            st.session_state.RAG_query_gene = False

        # Meta-search toggle
        if header_col3.checkbox("Meta Search", value=st.session_state.meta_search):
            st.session_state.meta_search = True
        else:
            st.session_state.meta_search = False

    # Toggle which chat history is shown
    num_seq_visible = 10
    sub_header_col1, sub_header_col2 = header_col4.columns(2)
    option = sub_header_col1.radio("History Seq Visible:", ("LATEST", "FULL"))
    if option == "LATEST":
        st.session_state.seq_visible_set = True
        if num_seq_visible := sub_header_col2.number_input(label="Visible Seq", value=10, step=1, format="%d"):
            st.session_state.seq_visible_set = True
    elif option == "FULL":
        st.session_state.seq_visible_set = False

    # Chat history row count
    option = header_col4.radio("History Detail Visible:", ("ALL", "SUMMARY"))
    if option == "ALL":
        st.session_state.chat_history_visible_dict = st.session_state.session.chat_history_active_dict
    elif option == "SUMMARY":
        st.session_state.chat_history_visible_dict = st.session_state.session.chat_history_active_omit_dict

    # Delete chat history (button)
    if header_col4.button("Delete Chat History(Chk)", key="delete_chat_history"):
        if st.session_state.seq_memory:
            for del_seq in st.session_state.seq_memory:
                st.session_state.session.chg_seq_history(del_seq, "N")
            st.session_state.sidebar_message = "Deleted chat history"
            st.session_state.seq_memory = []
            st.rerun()

    # Situation setup
    situation_setting = st.text_input("Situation Setting:", value=st.session_state.situation_setting)

    # Configure Chat history row count
    max_seq = dms.max_seq_dict(st.session_state.chat_history_visible_dict)
    seq_visible_key = 0
    if st.session_state.seq_visible_set:
        seq_visible_key = int(max_seq) - num_seq_visible
    else:
        seq_visible_key = 0

    # Render chat history
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

                                if "ACTIVE" in agent_feedback and agent_feedback["ACTIVE"] == "Y":
                                    # Fetch category choices
                                    _cat_map = dmu.read_json_file("category_map.json", mst_folder_path)
                                    _cat_options = list(_cat_map.get("Category", {}).keys()) if _cat_map else ["Unset"]
                                    _default_cat = agent_feedback.get("DEFAULT_CATEGORY") or _cat_options[0]

                                    # Include session_id in the widget key so that a draft for the same (seq, sub_seq)
                                    # does not linger when switching sessions
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
                                                st.session_state.sidebar_message = f"Saved feedback ({k}_{k2})"
                                                st.rerun()
                                            else:
                                                st.session_state.sidebar_message = f"No changes to feedback ({k}_{k2})"

                        # Detail
                        if st.session_state.allowed_details:
                            with st.chat_message("detail"):
                                download_data.append({"role": "detail", "content": st.session_state.session.get_detail_info(k, k2)})
                                chat_expander = st.expander("Detail Information")
                                with chat_expander:
                                    _detail_info = st.session_state.session.get_detail_info(k, k2)
                                    # Split into 【】 blocks and attach a copy button to each
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
                                                _run_bg_task("compare", f"Running comparative analysis ({_cmp_k}_{_cmp_k2})", _run_compare)
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
                                                _ak_title = f"{k}-{k2}-{st.session_state.session.session_id}"
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
                                                _run_bg_task("knowledge", f"Analyzing knowledge utility ({_ak_k}_{_ak_k2})", _run_ak)
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
                                                            _cak_title = f"{k}-{k2}-{st.session_state.session.session_id}_compare{selected_compare_idx}"
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
                                                            _run_bg_task("knowledge", f"Analyzing knowledge utility ({_cak_k}_{_cak_k2}_compare{_cak_idx})", _run_cak)
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
                                                            _ku_seq, _ku_sub = k, k2
                                                            rag_to_files = {
                                                                rag: {lk: _resolve_ku_file(st.session_state.session.session_analytics_folder_path, _ku_seq, _ku_sub, v, lk, rag) for lk, v in image_files.items()}
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
                                                    _ku_seq, _ku_sub = k, k2
                                                    rag_to_files = {
                                                        rag: {lk: _resolve_ku_file(st.session_state.session.session_analytics_folder_path, _ku_seq, _ku_sub, v, lk, rag) for lk, v in image_files.items()}
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

            # Chat-history logical-delete setting
            if st.checkbox(f"Delete(seq:{k})", key="del_chat_seq"+k):
                st.session_state.seq_memory.append(k)

            # Exclude from memory references only (display remains). Persist on toggle change.
            _seq_setting = v.get("SETTING", {})
            _mem_off_now = (_seq_setting.get("MEMORY_FLG", "Y") == "N")
            _mem_off_new = st.checkbox(f"Memory Off(seq:{k})", value=_mem_off_now,
                                       key="mem_off_chat_seq"+k,
                                       help="When ON, this seq stays visible but is excluded from the LLM's conversation memory")
            if _mem_off_new != _mem_off_now:
                st.session_state.session.chg_seq_memory_flg(k, "N" if _mem_off_new else "Y")
                st.rerun()

    if st.session_state.session_user_id == st.session_state.user_id:
        # File uploader (after run completion, increment the key to re-instantiate the widget -> clear attachments)
        uploaded_files = st.file_uploader(
            "Attached Files:",
            type=["txt", "vtt", "csv", "json", "pdf", "md", "docx", "xlsx", "pptx", "jpg", "jpeg", "png", "mp3"],
            accept_multiple_files=True,
            key=f"file_upload_{st.session_state.file_uploader_key}",
        )
        st.session_state.uploaded_files = uploaded_files
        show_uploaded_files_widget(st.session_state.uploaded_files)

        # Web search settings
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

        # URL fetch: http(s) links in the input are auto-fetched and treated as attachments.
        # Crawling subpages is optional (default OFF).
        st.session_state.url_fetch_subpages = st.checkbox(
            "Include URL Subpages", value=st.session_state.url_fetch_subpages,
            help="If the input contains a URL, it is fetched automatically. When ON, also fetches in-domain links where possible (caps in setting.yaml URL_FETCH).",
        )

        # Include Query: shown only when the previous seq ran multi-persona
        def _prev_seq_is_multi_persona():
            try:
                _hist = st.session_state.session.chat_history_active_dict or {}
                if not _hist:
                    return False
                _max_seq = max(_hist.keys(), key=int)
                _seq_block = _hist.get(_max_seq, {})
                # seq-level MEMORY_FLG=N (Phase 4: whole-practice parallel)
                if _seq_block.get("SETTING", {}).get("MEMORY_FLG") == "N":
                    return True
                # persona_id is set in 2+ sub_seqs (Phase 6: chain.PERSONAS)
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
                "Include Query (include previous personas' responses)",
                value=st.session_state.get("include_query", False),
                help="When ON, embed each persona's full response from the previous seq at the head of the next turn's input. Does not affect RAG query generation.",
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
            # The Personas option is added only for agents with ORG defined
            _agent_orgs = st.session_state.agent_data.get("ORG") or []
            if isinstance(_agent_orgs, list) and _agent_orgs:
                _thinking_options.append("Personas")
            # Drop choices not supported by the current agent from existing selection
            _saved_targets = [t for t in st.session_state.thinking_targets if t in _thinking_options]
            st.session_state.thinking_targets = st.multiselect(
                "Thinking Targets", _thinking_options,
                default=_saved_targets, label_visibility="collapsed",
            )

            # Max Personas: shown only when Thinking Mode is ON and Personas is selected
            if "Personas" in st.session_state.thinking_targets:
                try:
                    _yaml = dmu.read_yaml_file("setting.yaml")
                    _default_max_p = int(_yaml.get("MAX_PERSONAS", 3))
                except Exception:
                    _default_max_p = 3
                st.session_state.max_personas = st.number_input(
                    "Max Personas (cap when using Thinking)",
                    min_value=1, max_value=20,
                    value=int(st.session_state.get("max_personas", _default_max_p)),
                    step=1,
                    help="Upper bound for PersonaSelector in chain.PERSONAS=\"THINKING\" steps. Does not affect the manual multiselect.",
                )

        # Select from BOOK (shown only when the agent has at least one Book configured)
        if st.session_state.allowed_book:
            _book_list = st.session_state.agent_data.get("BOOK") or []
            if isinstance(_book_list, list) and len(_book_list) > 0:
                st.session_state.book_selected = st.multiselect(
                    "BOOK", [item["RAG_NAME"] for item in _book_list]
                )

        # User Memory (placed directly below BOOK on the main screen; shown when Allowed.User Memory=True)
        if st.session_state.allowed_user_memory:
            import DigiM_UserMemorySetting as _dmus
            _uid_for_um = st.session_state.user_id

            with st.expander("User Memory", expanded=False):
                _user_setting = _dmus.load_user_setting(_uid_for_um)
                _active_layers = _dmus.resolve_active_layers(_uid_for_um)
                st.caption(f"Active layers: {', '.join(_active_layers) if _active_layers else '(all off)'}")

                # Layer On/Off (3 columns) + Save Layer Setting
                _checked_layers = _user_setting.get("layers", [])
                _layer_cols = st.columns(3)
                _new_layers = []
                for _i, _l in enumerate(("persona", "nowaday", "history")):
                    _val = _layer_cols[_i].checkbox(_l, value=(_l in _checked_layers), key=f"um_layer_{_l}")
                    if _val:
                        _new_layers.append(_l)
                # The current checkbox state is reflected immediately for this session (next chat) without pressing Save
                st.session_state.user_memory_layers_now = _new_layers
                if st.button("Save Layer Setting", key="um_save_layers"):
                    _dmus.save_user_setting(_uid_for_um, _new_layers)
                    st.session_state.sidebar_message = "Layer setting saved."
                    st.rerun()

                # Reviewing/editing Persona/Nowaday/History has moved
                # to the User Memory Explorer's tab 3 (Edit My Memory).

    # File downloader
    if st.session_state.allowed_download_md:
        footer_col1, footer_col2, footer_col3 = st.columns(3)
        st.session_state.dl_type = footer_col1.radio("Download Mode:", ("Chats Only", "ALL"))
        dl_file_id = st.session_state.session.session_id +"_"+ st.session_state.session.session_name[:20]
        dl_data, dl_file_name, dl_mime = set_dl_file(download_data, st.session_state.dl_type, file_id=dl_file_id)
        footer_col2.download_button(label="Download(.md)", data=dl_data, file_name=dl_file_name, mime=dl_mime)
        pdf_data, pdf_file_name = set_dl_pdf(download_data, st.session_state.dl_type, file_id=dl_file_id)
        footer_col3.download_button(label="Download(.pdf)", data=pdf_data, file_name=pdf_file_name, mime="application/pdf")

    # User query input
    if st.session_state.session_user_id == st.session_state.user_id:

        # Chat input (while locked or background-running, poll to monitor)
        _status_locked = st.session_state.session.get_status() == "LOCKED"
        _bg_running = bool(st.session_state._bg_user_input)
        is_locked = _status_locked or _bg_running
        if is_locked:
            # Display the in-flight user input
            if st.session_state._bg_user_input:
                with st.chat_message("user"):
                    st.markdown(st.session_state._bg_user_input.replace("\n", "<br>"), unsafe_allow_html=True)
            @st.fragment(run_every=2)
            def _lock_monitor():
                _still_locked = st.session_state.session.get_status() == "LOCKED"
                if not _still_locked:
                    # Background completed: clean up and full reload
                    st.session_state._bg_user_input = ""
                    st.session_state.is_processing = False
                    refresh_session_list(st.session_state.service_id, st.session_state.user_id, st.session_state.user_admin_flg)
                    st.rerun(scope="app")
                _partial = st.session_state.session.get_status_response()
                if _partial:
                    st.markdown(_partial)
                _msg = st.session_state.session.get_status_message()
                st.info(f"⏳ {_msg}" if _msg else "⏳ Running...")
            with st.chat_message("ai"):
                _lock_monitor()

        # Show background-execution errors (read from status.yaml and clear immediately)
        if not is_locked:
            _bg_error = st.session_state.session.get_status_error()
            if _bg_error:
                st.session_state.session.save_status("UNLOCKED")
                st.error(f"Error during execution: {_bg_error}")

        _chat_disabled = is_locked or st.session_state.is_processing
        if raw_input := st.chat_input("Your Message", disabled=_chat_disabled):
            st.session_state.pending_input = raw_input
            st.session_state.is_processing = True
            st.rerun()

        if st.session_state.is_processing and st.session_state.pending_input:
            user_input = st.session_state.pending_input
            st.session_state.pending_input = ""
            # Attachment settings
            uploaded_contents = []
            if st.session_state.uploaded_files:
                for uploaded_file in st.session_state.uploaded_files:
                    uploaded_file_path = temp_folder_path + uploaded_file.name
                    with open(uploaded_file_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    uploaded_contents.append(uploaded_file_path)
                # Release attachments from the WebUI once consumed by the run (next render re-instantiates an empty uploader)
                st.session_state.uploaded_files = []
                st.session_state.file_uploader_key += 1

            # URL fetch (auto-detect and fetch http(s) links in the input)
            if dmuf.extract_urls(user_input):
                with st.spinner("Fetching URL content..."):
                    try:
                        _uf_result = dmuf.fetch_urls_from_text(
                            user_input,
                            temp_folder_path,
                            include_subpages=st.session_state.url_fetch_subpages,
                        )
                    except Exception as _uf_err:
                        _uf_result = {"saved_paths": [], "summaries": [], "blocked": [],
                                      "error": str(_uf_err)}
                        st.error(f"Exception fetching URL: {_uf_err}")
                for _p in _uf_result.get("saved_paths", []):
                    uploaded_contents.append(_p)
                for _s in _uf_result.get("summaries", []):
                    st.info(f"Fetched: {_s.get('title') or _s['url']} ({_s['pages']} pages) -> {_s['file']}")
                for _b in _uf_result.get("blocked", []):
                    st.warning(f"Blocked / fetch failed: {_b.get('url')} - {_b.get('reason')}")

            # Overwrite-items setup
            overwrite_items = {}
            # Engine switch (LLM)
            if st.session_state.engine_name and st.session_state.engine_name in st.session_state.agent_data.get("ENGINE", {}).get("LLM", {}):
                overwrite_items.setdefault("ENGINE", {})["LLM"] = st.session_state.agent_data["ENGINE"]["LLM"][st.session_state.engine_name]
            # Engine switch (IMAGEGEN)
            if st.session_state.imagegen_engine_name and st.session_state.imagegen_engine_name in st.session_state.agent_data.get("ENGINE", {}).get("IMAGEGEN", {}):
                overwrite_items.setdefault("ENGINE", {})["IMAGEGEN"] = st.session_state.agent_data["ENGINE"]["IMAGEGEN"][st.session_state.imagegen_engine_name]

            # Knowledge addition
            add_knowledges = []
            # BOOK setup
            if st.session_state.book_selected:
                for book_data in st.session_state.agent_data["BOOK"]:
                    if book_data["RAG_NAME"] in st.session_state.book_selected:
                        add_knowledges.append(book_data)

            # Situation setup
            situation = {}
            situation["TIME"] = time_setting
            situation["SITUATION"] = situation_setting

            # Execution settings
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
            # User Memory: current checkbox state takes top priority (reflected immediately regardless of Save)
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

            # Start execution in the background (pre-locked)
            import threading
            st.session_state.session.save_status("LOCKED")
            execution["_PRE_LOCKED"] = True
            # Phase 7: inject PersonaSelector cap into execution
            execution["MAX_PERSONAS"] = int(st.session_state.get("max_personas", 3))
            # Resolve the selected persona IDs into real persona dicts
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

            # Include Query: if the previous seq is MEMORY_FLG=N (multi-persona etc.), embed every
            # sub_seq response at the head of the user input. RAG query still uses the original input (rag_query_text).
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
                                    "[Each persona's previous response]\n" + "\n\n".join(_persona_blobs)
                                    + "\n\n[Current question]\n" + user_input
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
                        pass  # Drain chunks (results are saved to chat_memory.json)
                except Exception as e:
                    _exec_error = str(e)
                # Auto-generate the session name (don't skip on error either)
                try:
                    _session = dms.DigiMSession(params["session_id"], params["session_name"])
                    if not _session.session_name or _session.session_name == "New Chat":
                        _, _, new_name, _, _, _ = dmt.gene_session_name(
                            params["service_info"], params["user_info"],
                            params["session_id"], _session.session_name, "", params["user_input"])
                        _session.chg_session_name(new_name)
                except Exception:
                    pass
                # Record into status only on error (UNLOCK is handled inside DigiMatsuExecute_Practice)
                if _exec_error:
                    _session = dms.DigiMSession(params["session_id"])
                    # The digest thread may still be running; record the error after UNLOCK completes
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
