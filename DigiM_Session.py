import os
import json
import logging
import threading
from datetime import datetime
from datetime import timezone
from pathlib import Path
import zipfile
import shutil

# Per-session-file write lock (prevents race conditions)
_session_file_locks: dict = {}
_session_file_locks_meta = threading.Lock()

def _get_file_lock(file_path: str) -> threading.Lock:
    with _session_file_locks_meta:
        if file_path not in _session_file_locks:
            _session_file_locks[file_path] = threading.Lock()
        return _session_file_locks[file_path]

from dotenv import load_dotenv
import DigiM_Util as dmu

logger = logging.getLogger(__name__)

# Load folder paths and other settings from setting.yaml
system_setting_dict = dmu.read_yaml_file("setting.yaml")
user_folder_path = system_setting_dict["USER_FOLDER"]
session_folder_prefix = system_setting_dict["SESSION_FOLDER_PREFIX"]
session_file_name = system_setting_dict["SESSION_FILE_NAME"]
session_status_file_name = system_setting_dict["SESSION_STATUS_FILE_NAME"]
session_contents_folder = system_setting_dict["SESSION_CONTENTS_FOLDER"]
session_analytics_folder = system_setting_dict["SESSION_ANALYTICS_FOLDER"]
archive_folder = system_setting_dict["ARCHIVE_FOLDER"]
archive_days = int(system_setting_dict.get("ARCHIVE_DAYS", 30))

# Load system.env and set environment variables
if os.path.exists("system.env"):
    load_dotenv("system.env")
temp_move_flg = os.getenv("TEMP_MOVE_FLG")

DB_EXPORT_DONE = "DONE"
DB_EXPORT_UNDO = "UNDO"

# Get the list of sessions
def get_session_list():
    sessions = []
    for session_folder_name in os.listdir(user_folder_path):
        try:
            if session_folder_name.startswith(session_folder_prefix):
                session_folder_path = os.path.join(user_folder_path, session_folder_name)
                session_status_path = str(Path(session_folder_path) / session_status_file_name)
                status_dict = {}
                status_dict = dmu.read_yaml_file(session_status_path)
                if "id" not in status_dict:
                    status_dict["id"] = session_folder_name[len(session_folder_prefix):]
                session_id = status_dict["id"]
                if "name" not in status_dict:
                    status_dict["name"] = get_session_name(session_id)
                if "active" not in status_dict:
                    status_dict["active"] = "Y"
                if "agent" not in status_dict:
                    status_dict["agent"] = get_agent_file(session_id)
                if "last_update_date" not in status_dict:
                    status_dict["last_update_date"] = get_last_update_date(session_id)
                if "service_id" not in status_dict or "user_id" not in status_dict:
                    service_id, user_id = get_ids(session_id)
                    if "service_id" not in status_dict:
                        status_dict["service_id"] = service_id
                    if "user_id" not in status_dict:
                        status_dict["user_id"] = user_id
                sessions.append(status_dict)
        except Exception as e:
            logger.warning(f"Skipped {session_folder_name} due to error: {e}")
            continue
    return sessions

# Get the list of inactive sessions
def get_session_list_inactive():
    sessions_list = []
    sessions = get_session_list()
    for session_status in sessions:
        if session_status["active"] == "N":
            sessions_list.append(session_status)
    return sessions_list

# Get the list of sessions (for the UI)
def get_session_list_visible(input_service_id, input_user_id, admin_flg="N"):
    sessions_list = []
    sessions = get_session_list()
    for session_status in sessions:
        if admin_flg=="Y" or (input_service_id == session_status["service_id"] and input_user_id == session_status["user_id"]):
            sessions_list.append(session_status)
    sessions_list_sorted = sorted(sessions_list, key=lambda x: x.get("last_update_date"), reverse=True)
    return sessions_list_sorted

# Get the list of inactive sessions (for the UI)
def get_session_list_inactive_visible(input_service_id, input_user_id, admin_flg="N"):
    sessions_list = []
    sessions = get_session_list_inactive()
    for session_status in sessions:
        if admin_flg=="Y" or (input_service_id == session_status["service_id"] and input_user_id == session_status["user_id"]):
            sessions_list.append(session_status)
    sessions_list_sorted = sorted(sessions_list, key=lambda x: x.get("last_update_date"), reverse=True)
    return sessions_list_sorted

# Get the session dictionary by session ID
def get_session_data(session_id):
    session_key = session_folder_prefix + session_id
    session_file_path = str(Path(user_folder_path) / session_key / session_file_name)
    session_file_dict = dmu.read_json_file(session_file_path)
    return session_file_dict

# Get the session status data by session ID
def get_status_data(session_id):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    status_dict = dmu.read_yaml_file(session_status_path)
    return status_dict

# Get the maximum sequence number from a dictionary
def max_seq_dict(session_dict):
    max_seq = 0
    seqs = [int(k) for k in session_dict.keys() if k.isdigit()]
    if seqs:
        max_seq = max(seqs, key=int)
    return str(max_seq)

# Get the session name
def get_session_name(session_id):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    status_dict = {}
    status_dict = dmu.read_yaml_file(session_status_path)
    session_name = ""
    if "name" in status_dict:
        session_name = status_dict["name"]
    else:
        session_file_dict = get_session_data(session_id)
        session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
        if session_file_active_dict:
            max_seq = max_seq_dict(session_file_active_dict)
            max_sub_seq = max_seq_dict(session_file_active_dict[max_seq])
            session_name = session_file_active_dict[max_seq][max_sub_seq]["setting"]["session_name"]
    return session_name

# Get service name and user name from chat history
def get_ids(session_id):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    status_dict = {}
    status_dict = dmu.read_yaml_file(session_status_path)
    service_id = ""
    if "service_id" in status_dict:
        service_id = status_dict["service_id"]
    else:
        session_file_dict = get_session_data(session_id)
        session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
        if session_file_active_dict:
            max_seq = max(session_file_active_dict.keys(), key=int)
            if "service_info" in session_file_active_dict[max_seq]["SETTING"]:
                service_id = session_file_active_dict[max_seq]["SETTING"]["service_info"]["SERVICE_ID"]
    user_id = ""
    if "user_id" in status_dict:
        user_id = status_dict["user_id"]
    else:
        session_file_dict = get_session_data(session_id)
        session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
        if session_file_active_dict:
            max_seq = max(session_file_active_dict.keys(), key=int)
            if "user_info" in session_file_active_dict[max_seq]["SETTING"]:
                user_id = session_file_active_dict[max_seq]["SETTING"]["user_info"]["USER_ID"]
    return service_id, user_id

# Get the chat history's last update date
def get_last_update_date(session_id):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    status_dict = {}
    status_dict = dmu.read_yaml_file(session_status_path)
    current_date = datetime.now()
    last_update_date = current_date
    if "last_update_date" in status_dict:
        last_update_date = datetime.strptime(status_dict["last_update_date"], "%Y-%m-%d %H:%M:%S.%f")
    else:
        session_file_dict = get_session_data(session_id)
        session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
        if session_file_active_dict:
            max_seq = max(session_file_active_dict.keys(), key=int)
            max_sub_seq = 0
            sub_seq_candidates = [k for k, v in session_file_active_dict[max_seq].items() if isinstance(v, dict) and "response" in v]
            if sub_seq_candidates:
                max_sub_seq = max(sub_seq_candidates, key=int)
                last_update_date = datetime.strptime(session_file_active_dict[max_seq][max_sub_seq]["response"]["timestamp"], "%Y-%m-%d %H:%M:%S.%f")
    last_update_date_str = str(last_update_date)
    return last_update_date_str

# Get the agent file
def get_agent_file(session_id):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    status_dict = {}
    status_dict = dmu.read_yaml_file(session_status_path)
    agent_file = ""
    if "agent" in status_dict:
        agent_file = status_dict["agent"]
    else:
        session_file_dict = get_session_data(session_id)
        session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
        if session_file_active_dict:
            max_seq = max_seq_dict(session_file_active_dict)
            max_sub_seq = max_seq_dict(session_file_active_dict[max_seq])
            agent_file = session_file_active_dict[max_seq]["1"]["setting"]["agent_file"]
    return agent_file

# Get the engine name last executed in the session
def get_last_engine_name(session_id):
    session_file_dict = get_session_data(session_id)
    if not session_file_dict:
        return ""
    session_file_active_dict = {k: v for k, v in session_file_dict.items() if isinstance(v, dict) and v.get("SETTING", {}).get("FLG") == "Y"}
    if not session_file_active_dict:
        return ""
    max_seq = max_seq_dict(session_file_active_dict)
    max_sub_seq = max_seq_dict(session_file_active_dict[max_seq])
    setting = session_file_active_dict[max_seq][max_sub_seq].get("setting", {})
    engine = setting.get("engine", {})
    return engine.get("NAME", engine.get("MODEL", ""))

# Get the session active state
def get_active_session(session_id):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    status_dict = {}
    status_dict = dmu.read_yaml_file(session_status_path)
    if "active" in status_dict:
        active_flg = status_dict["active"]
    else:
        active_flg = "Y"
    return active_flg

# Get the session user_dialog save state
def get_user_dialog_session(session_id):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    status_dict = {}
    status_dict = dmu.read_yaml_file(session_status_path)
    # user_dialog is one of SAVED / UNSAVED / DISCARD / NONE
    if "user_dialog" in status_dict:
        user_dialog_status = status_dict["user_dialog"]
    else:
        user_dialog_status = "UNSAVED"
    return user_dialog_status

# Get the situation
def get_situation(session_id):
    session_key = session_folder_prefix + session_id
    session_file_path = str(Path(user_folder_path) / session_key / session_file_name)
    session_file_dict = dmu.read_json_file(session_file_path)
    session_file_active_dict = {k: v for k, v in session_file_dict.items() if v["SETTING"].get("FLG") == "Y"}
    situation = {}

    # Get the situation from the max seq / sub_seq
    if session_file_active_dict:
        max_seq = max_seq_dict(session_file_active_dict)
        max_sub_seq = max_seq_dict(session_file_active_dict[max_seq])
        situation = session_file_active_dict[max_seq][max_sub_seq]["prompt"]["query"]["situation"]

    return situation

# Get the DB Export status and lastSeq
def get_db_export_info(session_id):
    status_dict = get_status_data(session_id)
    info = status_dict.get("db_export")
    if not isinstance(info, dict):
        return "", 0
    return info.get("status", ""), int(info.get("last_seq", 0))

# Update the DB Export status to DONE
def save_db_export_done(session_id, last_seq: int):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    dmu.save_yaml_file({"db_export": {"status": DB_EXPORT_DONE, "last_seq": last_seq}}, session_status_path)

# Update the DB Export status to UNDO
def save_db_export_undo(session_id, last_seq: int):
    session_key = session_folder_prefix + session_id
    session_status_path = str(Path(user_folder_path) / session_key / session_status_file_name)
    dmu.save_yaml_file({"db_export": {"status": DB_EXPORT_UNDO, "last_seq": last_seq}}, session_status_path)

# ZIP-compress session folders that haven't been updated for 30+ days, then delete them
def archive_old_sessions(days: int = None) -> dict:
    """
    Bundle session folders whose last update is >= `days` ago into a single ZIP
    and then delete the original folders.

    ZIP path: archive_folder / sessions_archive_YYYYMMDD_HHMMSS.zip
    Returns: {"zip_path": str, "archived": [folder_name,...], "skipped": [folder_name,...]}
    """
    now = datetime.now(tz=timezone.utc)
    threshold_days = days if days is not None else archive_days
    archived = []
    skipped = []

    # Collect folders to compress
    target_folders = []
    for entry in os.scandir(user_folder_path):
        if not entry.is_dir():
            continue
        if not entry.name.startswith(session_folder_prefix):
            continue
        try:
            mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            elapsed_days = (now - mtime).days
            if elapsed_days >= threshold_days:
                target_folders.append((entry.name, entry.path))
            else:
                skipped.append(entry.name)
        except Exception as e:
            logger.warning(f"[archive] Failed to read mtime for {entry.name}: {e}")
            skipped.append(entry.name)

    if not target_folders:
        logger.info(f"[archive] No sessions older than {threshold_days} days.")
        return {"zip_path": None, "archived": [], "skipped": skipped}

    # Resolve the ZIP file path
    archive_dir = Path(archive_folder)
    archive_dir.mkdir(parents=True, exist_ok=True)
    zip_name = "sessions_archive_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip"
    zip_path = str(archive_dir / zip_name)

    # Compress
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder_name, folder_path in target_folders:
            for file_path in Path(folder_path).rglob("*"):
                if file_path.is_file():
                    arcname = Path(folder_name) / file_path.relative_to(folder_path)
                    zf.write(file_path, arcname)

    # Delete folders
    for folder_name, folder_path in target_folders:
        try:
            shutil.rmtree(folder_path)
            archived.append(folder_name)
            logger.info(f"[archive] Deleted {folder_name}.")
        except Exception as e:
            logger.error(f"[archive] Failed to delete {folder_name}: {e}")

    logger.info(f"[archive] Done -- ZIP: {zip_path} / archived={len(archived)} / skipped={len(skipped)}")
    return {"zip_path": zip_path, "archived": archived, "skipped": skipped}

# Issue a new session ID (numeric sequence only)
def set_new_session_id():
    new_session_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_list = get_session_list()

    session_nums = []
    for item in session_list:
        id_val = item.get("id", "")
        if id_val.startswith(new_session_prefix + "_"):
            try:
                session_nums.append(int(id_val.split("_", 1)[1]))
            except ValueError:
                pass
    if session_nums:
        new_session_id = new_session_prefix+"_"+str(max(session_nums))
    else:
        new_session_id = new_session_prefix+"_0"

    return new_session_id


# Centralized error log for backend errors (background jobs, dispatchers, etc.)
# that are not necessarily tied to a single session. File: <USER_FOLDER>_bg_errors.log.
#
# Size-bounded rotation:
#   - When the active file exceeds BG_ERRORS_MAX_BYTES (default 2 MB), it is
#     rotated to _bg_errors.log.YYYYMMDDHHMMSS and a fresh file is started.
#   - At most BG_ERRORS_BACKUPS rotated files are kept (default 5).
#   - Both knobs are overridable via system.env:
#       BG_ERRORS_MAX_BYTES=<int bytes>
#       BG_ERRORS_BACKUPS=<int>
def _bg_errors_rotate_if_needed(log_path):
    try:
        max_bytes = int(os.getenv("BG_ERRORS_MAX_BYTES") or 2_000_000)
    except (TypeError, ValueError):
        max_bytes = 2_000_000
    try:
        backups = int(os.getenv("BG_ERRORS_BACKUPS") or 5)
    except (TypeError, ValueError):
        backups = 5
    try:
        if os.path.getsize(log_path) < max_bytes:
            return
    except OSError:
        return
    # Use microsecond precision so multiple rotations within the same second
    # do not overwrite each other.
    rotated = log_path + "." + datetime.now().strftime("%Y%m%d%H%M%S%f")
    try:
        os.replace(log_path, rotated)
    except OSError:
        return
    # Trim oldest rotated backups beyond the retention count.
    try:
        prefix = os.path.basename(log_path) + "."
        dir_ = os.path.dirname(log_path) or "."
        olds = sorted(
            [os.path.join(dir_, n) for n in os.listdir(dir_) if n.startswith(prefix)],
            key=lambda p: os.path.getmtime(p),
        )
        # Keep the newest `backups`; remove the rest.
        for p in olds[: max(0, len(olds) - backups)]:
            try:
                os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def save_global_error_log(exc, context=None):
    import traceback as _tb
    os.makedirs(user_folder_path, exist_ok=True)
    log_path = str(Path(user_folder_path) / "_bg_errors.log")
    # Rotate before append so a single large traceback can't push us far past the cap.
    _bg_errors_rotate_if_needed(log_path)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    lines = ["=" * 72, f"[{ts}] (global)"]
    if isinstance(context, dict) and context:
        for k, v in context.items():
            lines.append(f"  {k}: {v}")
    if isinstance(exc, BaseException):
        lines.append(f"  exception: {type(exc).__name__}: {exc}")
        tb_text = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
        lines.append(tb_text.rstrip())
    else:
        lines.append(f"  error: {exc}")
    body = "\n".join(lines) + "\n"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(body)
    except Exception:
        pass
    return log_path


# Session class
class DigiMSession:
    def __init__(self, session_id="", session_name="", base_path=""):
        self.session_id = session_id if session_id else set_new_session_id()
        self.session_name = session_name if session_name else get_session_name(self.session_id)
        if base_path:
            _session_base = Path(base_path)
        else:
            _session_base = Path(user_folder_path) / (session_folder_prefix + self.session_id)
        self.session_folder_path = str(_session_base) + "/"
        self.session_vec_folder_path = str(_session_base / "vecs") + "/"
        self.session_file_path = str(_session_base / session_file_name)
        self.session_status_path = str(_session_base / session_status_file_name)
        self.session_contents_folder_path = str(_session_base / session_contents_folder) + "/"
        self.session_analytics_folder_path = str(_session_base / session_analytics_folder) + "/"
        self.set_history()

    # Reload chat history
    def set_history(self):
        self.chat_history_dict = self.get_history()
        self.chat_history_active_dict = self.get_history_active()
        self.chat_history_active_omit_dict = self.get_history_active_omit()

    # Truncate chat history up to the given seq / sub_seq
    def extract_history_by_keys(self, chat_history_dict, seq_str="", sub_seq_str=""):
        trimmed_dict = {}
        if seq_str:
            for key, sub_dict in chat_history_dict.items():
                if key < seq_str:
                    trimmed_dict[key] = sub_dict
                elif key == seq_str:
                    if sub_seq_str:
                        trimmed_dict[key] = {sub_key: sub_dict[sub_key] for sub_key in sub_dict if sub_key <= sub_seq_str}
                    else:
                        trimmed_dict[key] = sub_dict
            return trimmed_dict
        else:
            return chat_history_dict

    # Get the session status
    def get_status(self):
        status_dict = {}
        status_dict = dmu.read_yaml_file(self.session_status_path)
        if "status" in status_dict:
            status = status_dict["status"]
        else:
            status = "UNLOCKED"
        return status

    # Get the session active state
    def get_active_session(self):
        active_flg = get_active_session(self.session_id)
        return active_flg

    # Get the session user_dialog save state
    def get_user_dialog_session(self):
        user_dialog_status = get_user_dialog_session(self.session_id)
        return user_dialog_status

    # Get the entire chat history
    def get_history(self):
        chat_history_dict = {}
        chat_history_dict = dmu.read_json_file(self.session_file_path)
        return chat_history_dict

    # Get the active chat history
    def get_history_active(self):
        chat_history_active_dict = {}
        if self.chat_history_dict:
            chat_history_active_dict = {k: v for k, v in self.chat_history_dict.items() if "SETTING" in v and v["SETTING"].get("FLG") == "Y"}
        return chat_history_active_dict

    # Get the min/max sub_seq dict data
    def get_history_active_omit(self):
        chat_history_active_omit_dict = {}
        if self.chat_history_active_dict:
            for key, sub_dict in self.chat_history_active_dict.items():
                sub_seqs = sorted((int(k) for k in sub_dict if k != "SETTING"))
                # Get the min and max sub keys
                min_subseq = str(sub_seqs[0])
                max_subseq = str(sub_seqs[-1])
                chat_history_active_omit_dict[key] = {}
                chat_history_active_omit_dict[key]["1"] = {}
                chat_history_active_omit_dict[key]["1"]["setting"] = sub_dict[str(min_subseq)]["setting"]
                if "prompt" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["prompt"] = sub_dict[str(min_subseq)]["prompt"]
                # Collect images from both max_subseq and intermediate sub_seqs (when IMAGEGEN is mid-chain)
                _merged_images = {}
                for _ss in sub_seqs:
                    _ss_block = sub_dict.get(str(_ss), {})
                    if "image" in _ss_block and isinstance(_ss_block["image"], dict):
                        for _img_k, _img_v in _ss_block["image"].items():
                            _merged_images[f"{_ss}_{_img_k}"] = _img_v
                if _merged_images:
                    chat_history_active_omit_dict[key]["1"]["image"] = _merged_images
                if "response" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["response"] = sub_dict[str(max_subseq)]["response"]
                if "digest" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["digest"] = sub_dict[str(max_subseq)]["digest"]
                if "log" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["log"] = sub_dict[str(max_subseq)]["log"]
                if "feedback" in sub_dict[str(max_subseq)]:
                    chat_history_active_omit_dict[key]["1"]["feedback"] = sub_dict[str(max_subseq)]["feedback"]
        return chat_history_active_omit_dict

    # Get the digest just before the given seq
    def get_history_digest(self, seq="", sub_seq=""):
        chat_history_active_dict = self.get_history_active()
        set_seq = ""
        set_sub_seq = ""
        if chat_history_active_dict:
            chat_history_digest_dict = {}
            if int(sub_seq) <= 1:
                set_seq = str(int(seq)-1)
                if int(set_seq) > 0:
                    sub_seq_candidates = [k for k, v in chat_history_active_dict[set_seq].items() if isinstance(v, dict) and "digest" in v]
                    if sub_seq_candidates:
                        set_sub_seq = max(sub_seq_candidates, key=int)
                        chat_history_digest_dict = chat_history_active_dict[set_seq][set_sub_seq]["digest"]
            else:
                set_seq = seq
                sub_seq_candidates = [k for k, v in chat_history_active_dict[set_seq].items() if k < sub_seq and isinstance(v, dict) and "digest" in v]
                if sub_seq_candidates:
                    set_sub_seq = max(sub_seq_candidates, key=int)
                    chat_history_digest_dict = chat_history_active_dict[set_seq][set_sub_seq]["digest"]
        return set_seq, set_sub_seq, chat_history_digest_dict

    # Get the latest agent
    def get_history_max_agent(self):
        chat_history_active_dict = self.get_history_active()
        max_seq = max(chat_history_active_dict.keys(), key=int)
        max_sub_seq = 0
        agent_file = ""
        agent_name = ""
        engine_name = ""
        sub_seq_candidates = [k for k, v in chat_history_active_dict[max_seq].items() if isinstance(v, dict) and "setting" in v]
        if sub_seq_candidates:
            max_sub_seq = max(sub_seq_candidates, key=int)
            agent_file = chat_history_active_dict[max_seq][max_sub_seq]["setting"]["agent_file"]
            agent_name = chat_history_active_dict[max_seq][max_sub_seq]["setting"]["name"]
            engine_name = chat_history_active_dict[max_seq][max_sub_seq]["setting"]["engine"]["NAME"]
        return agent_name+":"+engine_name

    # Get the latest digest
    def get_history_max_digest(self):
        chat_history_active_dict = self.get_history_active()
        max_seq = max(chat_history_active_dict.keys(), key=int)
        max_sub_seq = 0
        chat_history_max_digest_dict = {}
        sub_seq_candidates = [k for k, v in chat_history_active_dict[max_seq].items() if isinstance(v, dict) and "digest" in v]
        if sub_seq_candidates:
            max_sub_seq = max(sub_seq_candidates, key=int)
            chat_history_max_digest_dict = chat_history_active_dict[max_seq][max_sub_seq]["digest"]
        return max_seq, max_sub_seq, chat_history_max_digest_dict

    # Get conversation memory (truncated by token limit)
    def get_memory(self, query_vec, model_name, tokenizer, memory_limit_tokens, memory_role="both", memory_priority="latest", memory_similarity=False, memory_similarity_logic="cosine", memory_digest="Y", seq_limit="", sub_seq_limit=""):
        memories_list = []
        memories_list_final = []
        total_tokens = 0

        # Speaker-name prefix (fall back to USER_ID when NAME is missing in chat history;
        # the user master is not consulted)
        def _prefix(role, name):
            _n = (name or "").strip() or ("(unknown)" if role == "user" else "AI")
            if role == "user":
                return f"[User: {_n}] "
            if role == "assistant":
                return f"[Agent: {_n}] "
            return ""

        # Pick history items to inject into memory from the active chat history
        chat_history_active_dict = self.extract_history_by_keys(self.chat_history_active_dict, seq_limit, sub_seq_limit)

        if chat_history_active_dict:
            # Get the latest digest
            if memory_digest == "Y":
                chat_history_digest_dict = {}
                if seq_limit or sub_seq_limit:
                    max_seq, max_sub_seq, chat_history_digest_dict = self.get_history_digest(seq_limit, sub_seq_limit)
                else:
                    max_seq, max_sub_seq, chat_history_digest_dict = self.get_history_max_digest()
                if chat_history_digest_dict:
                    # If under the token limit, include the digest
                    total_tokens += chat_history_digest_dict["token"]
                    if total_tokens <= memory_limit_tokens:
                        chat_history_digest_dict["vec_text"] = []
                        similarity_prompt = 0
                        if memory_similarity:
                            chat_history_digest_dict["vec_text"] = self.get_vec_file(max_seq, max_sub_seq, "digest")
                            similarity_prompt = dmu.calculate_similarity_vec(query_vec, chat_history_digest_dict["vec_text"], memory_similarity_logic)
                        memories_list.append({"seq": max_seq, "sub_seq": max_sub_seq, "type": "digest", "role": chat_history_digest_dict["role"], "timestamp": chat_history_digest_dict["timestamp"], "token": chat_history_digest_dict["token"], "similarity_prompt": similarity_prompt, "text": chat_history_digest_dict["text"], "vec_text": chat_history_digest_dict["vec_text"]})

            # Collect each entry (seq with MEMORY_FLG="N" or sub_seq with setting.memory_flg="N" is excluded from memory; display remains)
            for k, v in chat_history_active_dict.items():
                if v.get("SETTING", {}).get("MEMORY_FLG", "Y") == "N":
                    continue
                # Per-seq speaker identification: user_info.NAME (falls back to USER_ID when absent)
                _u_info = v.get("SETTING", {}).get("user_info") or {}
                _user_disp = (_u_info.get("NAME") or _u_info.get("USER_ID") or "").strip()
                for k2, v2 in v.items():
                    if k2 != "SETTING":
                        if v2.get("setting", {}).get("memory_flg", "Y") == "N":
                            continue
                        similarity_prompt = 0
                        v2["prompt"]["query"]["vec_text"] = []
                        v2["response"]["vec_text"] = []
                        if memory_role in ["both", "user"]:
                            if v2["prompt"]["role"] == "user":
                                if memory_similarity:
                                    v2["prompt"]["query"]["vec_text"] = self.get_vec_file(k, k2, "query")
                                    similarity_prompt = dmu.calculate_similarity_vec(query_vec, v2["prompt"]["query"]["vec_text"], memory_similarity_logic)
                                _utxt = _prefix("user", _user_disp) + (v2["prompt"]["query"]["text"] or "")
                                memories_list.append({"seq": k, "sub_seq": k2, "type": v2["prompt"]["role"], "role": v2["prompt"]["role"], "timestamp": v2["prompt"]["timestamp"], "token": v2["prompt"]["query"]["token"], "similarity_prompt": similarity_prompt, "text": _utxt, "vec_text": v2["prompt"]["query"]["vec_text"]})
                        if memory_role in ["both", "assistant"]:
                            if v2["response"]["role"] == "assistant":
                                if memory_similarity:
                                    v2["response"]["vec_text"] = self.get_vec_file(k, k2, "response")
                                    similarity_prompt = dmu.calculate_similarity_vec(query_vec, v2["response"]["vec_text"], memory_similarity_logic)
                                _agent_name = (v2.get("setting") or {}).get("name", "")
                                _atxt = _prefix("assistant", _agent_name) + (v2["response"]["text"] or "")
                                memories_list.append({"seq": k, "sub_seq": k2, "type": v2["response"]["role"], "role": v2["response"]["role"], "timestamp": v2["response"]["timestamp"], "token": v2["response"]["token"], "similarity_prompt": similarity_prompt, "text": _atxt, "vec_text": v2["response"]["vec_text"]})

            # Sort each entry by priority
            if memory_priority == "latest":
                memories_list_priority = sorted(memories_list, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"), reverse=True)
            elif memory_priority == "oldest":
                memories_list_priority = sorted(memories_list, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"))
            elif memory_similarity and memory_priority == "similar":
                memories_list_priority = sorted(memories_list, key=lambda x: x["similarity_prompt"])
            else :
                memories_list_priority = memories_list

            # Build conversation memory while staying under the token limit
            memories_list_selected = []
            for memory_list_priority in memories_list_priority:
                total_tokens += memory_list_priority["token"]
                if total_tokens <= memory_limit_tokens:
                    memories_list_selected.append(memory_list_priority)

            # Finally, sort by timestamp
            memories_list_final = sorted(memories_list_selected, key=lambda x: datetime.strptime(x["timestamp"], "%Y-%m-%d %H:%M:%S.%f"))

        return memories_list_final

    # Save vector data into the session folder
    def save_vec_file(self, seq, sub_seq="1", mode="query", vec_text=[]):
        # Create the session folder if missing
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)

        # Create the vector-data folder if missing
        if not os.path.exists(self.session_vec_folder_path):
            os.makedirs(self.session_vec_folder_path, exist_ok=True)

        # Save vector data as .npy
        vec_file_name = seq+"-"+sub_seq+"_"+mode+".npy"
        dmu.save_vectext_to_npy(vec_text, str(Path(self.session_vec_folder_path) / vec_file_name))

        return vec_file_name

    # Load vector data from the session folder
    def get_vec_file(self, seq, sub_seq="1", mode="query"):
        vec_file_name = seq+"-"+sub_seq+"_"+mode+".npy"
        vec_text=[]
        vec_text = dmu.read_vectext_to_npy(str(Path(self.session_vec_folder_path) / vec_file_name))
        return vec_text

    # Save session metadata in one shot (a single YAML read/write)
    def save_session_metadata(self, **kwargs):
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)
        status_dict = dmu.read_yaml_file(self.session_status_path)
        if not status_dict:
            status_dict = {}
        status_dict.update(kwargs)
        # Clear error info when metadata is updated
        status_dict["error"] = ""
        dmu.save_yaml_file(status_dict, self.session_status_path)

    def _update_status_yaml(self, updates):
        """Update the specified keys while preserving existing data in status.yaml."""
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)
        status_dict = dmu.read_yaml_file(self.session_status_path)
        if not status_dict:
            status_dict = {}
        status_dict.update(updates)
        dmu.save_yaml_file(status_dict, self.session_status_path)

    # Set the session ID
    def save_session_id(self):
        self._update_status_yaml({"id": self.session_id})

    # Set the session name
    def save_session_name(self):
        self._update_status_yaml({"name": self.session_name})

    # Save the session service ID
    def save_service_id(self, service_id):
        self._update_status_yaml({"service_id": service_id})

    # Save the session user ID
    def save_user_id(self, user_id):
        self._update_status_yaml({"user_id": user_id})

    # ── Session Summary (user-defined session dossier, cf. sessionsummary) ──
    # Optional per-session structured document. Distinct from `memory_digest`
    # (which the LLM auto-generates for context compression) — the summary
    # follows a user-picked template and is updated deliberately after each
    # turn so the operator can watch key facts accumulate.
    #
    #   session_summary_enabled   : bool  — feature toggle for this session
    #   session_summary_template  : str   — Markdown skeleton (preset or edited)
    #   session_summary_content   : str   — current filled-in summary
    #   session_summary_updated_at: str   — ISO timestamp of last write
    def get_session_summary(self):
        """Return the tuple (enabled, template, content, updated_at). Any
        missing keys fall back to sensible defaults (False / '' / '' / '')."""
        status_dict = dmu.read_yaml_file(self.session_status_path) or {}
        return (
            bool(status_dict.get("session_summary_enabled", False)),
            str(status_dict.get("session_summary_template", "") or ""),
            str(status_dict.get("session_summary_content",  "") or ""),
            str(status_dict.get("session_summary_updated_at", "") or ""),
        )

    def save_session_summary_settings(self, enabled: bool, template: str):
        """Write the operator-controlled bits (feature toggle + template).
        Called from the WebUI's summary settings expander."""
        self._update_status_yaml({
            "session_summary_enabled":  bool(enabled),
            "session_summary_template": str(template or ""),
        })

    def save_session_summary_content(self, content: str):
        """Write the LLM-generated body + bump the updated_at timestamp.
        Called from the auto-update background task after each turn."""
        from datetime import datetime as _dt
        self._update_status_yaml({
            "session_summary_content":    str(content or ""),
            "session_summary_updated_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    # Save the session service ID
    def save_agent_file(self, agent_file):
        self._update_status_yaml({"agent": agent_file})

    # Save the session last update date
    def save_last_update_date(self, last_update_date):
        self._update_status_yaml({"last_update_date": last_update_date})

    # Save the session status
    def save_status(self, status, error=""):
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)
        status_dict = {"status": status, "message": "", "response": "", "error": error}
        dmu.save_yaml_file(status_dict, self.session_status_path)
        # Mirror to errors.log under the session folder when an error is set,
        # so users can find the full context next to the session data.
        if error:
            try:
                self.save_error_log(error)
            except Exception:
                pass

    # Centralized error log for backend errors not tied to a specific session
    # (background tasks, job queue dispatch errors, etc.).
    # File: <USER_FOLDER>_bg_errors.log (append). Same row format as the per-session errors.log.

    # Append a backend error entry to <session>/errors.log with timestamp + context.
    # `exc` may be a string message or an exception object. When it's an exception,
    # the full traceback (when available) is captured.
    def save_error_log(self, exc, context=None):
        import traceback as _tb
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)
        log_path = str(Path(self.session_folder_path) / "errors.log")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        lines = [
            "=" * 72,
            f"[{ts}] session_id={self.session_id} session_name={self.session_name}",
        ]
        if isinstance(context, dict) and context:
            for k, v in context.items():
                lines.append(f"  {k}: {v}")
        if isinstance(exc, BaseException):
            lines.append(f"  exception: {type(exc).__name__}: {exc}")
            tb_text = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
            lines.append(tb_text.rstrip())
        else:
            lines.append(f"  error: {exc}")
        body = "\n".join(lines) + "\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(body)
        return log_path

    def get_status_error(self):
        status_dict = dmu.read_yaml_file(self.session_status_path)
        return status_dict.get("error", "")

    def save_status_message(self, message, response=""):
        status_dict = {"status": "LOCKED", "message": message}
        if response:
            status_dict["response"] = response
        dmu.save_yaml_file(status_dict, self.session_status_path)

    def get_status_message(self):
        status_dict = dmu.read_yaml_file(self.session_status_path)
        return status_dict.get("message", "")

    def get_status_response(self):
        status_dict = dmu.read_yaml_file(self.session_status_path)
        return status_dict.get("response", "")

    # Update the session active state
    def save_active_session(self, active_flg):
        self._update_status_yaml({"active": active_flg})

    # Update the session user_dialog save state
    def save_user_dialog_session(self, user_dialog_status):
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)
        status_dict = {"user_dialog": user_dialog_status}
        dmu.save_yaml_file(status_dict, self.session_status_path)

    # Get the DB Export status and lastSeq
    def get_db_export_info(self):
        status_dict = dmu.read_yaml_file(self.session_status_path)
        info = status_dict.get("db_export")
        if not isinstance(info, dict):
            return "", 0
        return info.get("status", ""), int(info.get("last_seq", 0))

    # Update the DB Export status to DONE
    def save_db_export_done(self, last_seq: int):
        dmu.save_yaml_file({"db_export": {"status": DB_EXPORT_DONE, "last_seq": last_seq}}, self.session_status_path)

    # Update the DB Export status to UNDO
    def save_db_export_undo(self, last_seq: int):
        dmu.save_yaml_file({"db_export": {"status": DB_EXPORT_UNDO, "last_seq": last_seq}}, self.session_status_path)

    # Save chat history in bulk (B-5)
    # sub_seq_data: {sub_seq_str: {key: dict, ...}, ...}
    # seq_setting_data: {key: dict, ...} -- saved at the SETTING level
    def save_history_batch(self, seq, sub_seq_data=None, seq_setting_data=None):
        with _get_file_lock(self.session_file_path):
            chat_history_dict = {}
            if not os.path.exists(self.session_folder_path):
                os.makedirs(self.session_folder_path, exist_ok=True)
            if os.path.exists(self.session_file_path):
                chat_history_dict = dmu.read_json_file(self.session_file_path)
            if seq not in chat_history_dict:
                chat_history_dict[seq] = {}
                chat_history_dict[seq]["SETTING"] = {"FLG": "Y"}
            if seq_setting_data:
                for key, data in seq_setting_data.items():
                    chat_history_dict[seq]["SETTING"][key] = data
            if sub_seq_data:
                for sub_seq, entries in sub_seq_data.items():
                    if sub_seq not in chat_history_dict[seq]:
                        chat_history_dict[seq][sub_seq] = {}
                    for key, data in entries.items():
                        chat_history_dict[seq][sub_seq][key] = data
            dmu.save_json_file(chat_history_dict, self.session_file_path, indent=4)
            # Reset DB Export to UNDO when new conversation is saved
            export_status, last_exported_seq = self.get_db_export_info()
            if export_status == DB_EXPORT_DONE:
                self.save_db_export_undo(last_exported_seq)

    # Save chat history
    def save_history(self, seq, chat_dict_key, chat_dict, level="SEQ", sub_seq="1"):
        # Create the session folder if missing (mkdir is idempotent; OK outside the lock)
        if not os.path.exists(self.session_folder_path):
            os.makedirs(self.session_folder_path, exist_ok=True)

        with _get_file_lock(self.session_file_path):
            chat_history_dict = {}
            # Read the saved chat history
            if os.path.exists(self.session_file_path):
                chat_history_dict = dmu.read_json_file(self.session_file_path)

            # If the seq is missing, set it together with FLG
            if seq not in chat_history_dict:
                chat_history_dict[seq] = {}
                chat_history_dict[seq]["SETTING"] = {}
                chat_history_dict[seq]["SETTING"]["FLG"] = "Y"

            # Append data to chat history
            if level == "SEQ":
                chat_history_dict[seq]["SETTING"][chat_dict_key] = chat_dict
            elif level == "SUB_SEQ":
                if sub_seq not in chat_history_dict[seq]:
                    chat_history_dict[seq][sub_seq] = {}
                chat_history_dict[seq][sub_seq][chat_dict_key] = chat_dict

            # Save chat history
            dmu.save_json_file(chat_history_dict, self.session_file_path, indent=4)
            # Reset DB Export to UNDO when new conversation is saved
            export_status, last_exported_seq = self.get_db_export_info()
            if export_status == DB_EXPORT_DONE:
                self.save_db_export_undo(last_exported_seq)

    # Change the session name
    def chg_session_name(self, new_session_name):
        self.session_name = new_session_name
        self.save_session_name()
        with _get_file_lock(self.session_file_path):
            if not os.path.exists(self.session_file_path):
                return
            session_file_dict = dmu.read_json_file(self.session_file_path)
            for seq_key, seq_val in session_file_dict.items():
                if not isinstance(seq_val, dict):
                    continue
                for sub_key, sub_val in seq_val.items():
                    if sub_key == "SETTING" or not isinstance(sub_val, dict):
                        continue
                    if "setting" in sub_val and isinstance(sub_val["setting"], dict):
                        sub_val["setting"]["session_name"] = new_session_name
            dmu.save_json_file(session_file_dict, self.session_file_path, indent=4)

    # Get a sequence of chat history
    def get_seq_history(self):
        seq = 0
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            if chat_history_dict:
                seq = max(int(key) for key in chat_history_dict.keys())
        return seq

    # Change the status of a chat-history sequence
    def chg_seq_history(self, seq, value="N"):
        with _get_file_lock(self.session_file_path):
            if not os.path.exists(self.session_file_path):
                return
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict[seq]["SETTING"]["FLG"] = value
            dmu.save_json_file(chat_history_dict, self.session_file_path, indent=4)

    # Change the memory-reference flag of a chat-history sequence
    # MEMORY_FLG="N": display remains but excluded from memory references (LLM context)
    def chg_seq_memory_flg(self, seq, value="Y"):
        with _get_file_lock(self.session_file_path):
            if not os.path.exists(self.session_file_path):
                return
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            if seq in chat_history_dict and "SETTING" in chat_history_dict[seq]:
                chat_history_dict[seq]["SETTING"]["MEMORY_FLG"] = value
                dmu.save_json_file(chat_history_dict, self.session_file_path, indent=4)

    # Change the per-sub_seq memory-reference flag (Phase 6: for chain.PERSONAS)
    # sub_seq with setting.memory_flg = "N" still displays but is excluded from memory references
    def chg_subseq_memory_flg(self, seq, sub_seq, value="Y"):
        with _get_file_lock(self.session_file_path):
            if not os.path.exists(self.session_file_path):
                return
            chat_history_dict = dmu.read_json_file(self.session_file_path)
            if seq in chat_history_dict and sub_seq in chat_history_dict[seq]:
                if "setting" not in chat_history_dict[seq][sub_seq]:
                    chat_history_dict[seq][sub_seq]["setting"] = {}
                chat_history_dict[seq][sub_seq]["setting"]["memory_flg"] = value
                dmu.save_json_file(chat_history_dict, self.session_file_path, indent=4)

    # Add a key/value to the per-sub_seq setting (Phase 6: for assigning chain_index / chain_role etc.)
    def update_subseq_setting(self, seq, sub_seq, updates):
        if not isinstance(updates, dict) or not updates:
            return
        with _get_file_lock(self.session_file_path):
            if not os.path.exists(self.session_file_path):
                return
            chat_history_dict = dmu.read_json_file(self.session_file_path)
            if seq in chat_history_dict and sub_seq in chat_history_dict[seq]:
                if "setting" not in chat_history_dict[seq][sub_seq]:
                    chat_history_dict[seq][sub_seq]["setting"] = {}
                chat_history_dict[seq][sub_seq]["setting"].update(updates)
                dmu.save_json_file(chat_history_dict, self.session_file_path, indent=4)

    # Save feedback into chat history
    def set_feedback_history(self, seq, sub_seq, feedbacks={}):
        with _get_file_lock(self.session_file_path):
            if not os.path.exists(self.session_file_path):
                return
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict[seq][sub_seq]["feedback"] = feedbacks
            dmu.save_json_file(chat_history_dict, self.session_file_path, indent=4)

    # Save analytics result into chat history
    def set_analytics_history(self, seq, sub_seq, analytics={}):
        import logging
        _logger = logging.getLogger(__name__)
        with _get_file_lock(self.session_file_path):
            if not os.path.exists(self.session_file_path):
                _logger.warning(f"set_analytics_history: file not found {self.session_file_path}")
                return
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict[seq][sub_seq]["analytics"] = analytics
            dmu.save_json_file(chat_history_dict, self.session_file_path, indent=4)
            _logger.info(f"set_analytics_history: seq={seq}, sub_seq={sub_seq} written to {self.session_file_path}")

    # Get detailed info from chat history
    def get_detail_info(self, seq, sub_seq="1"):
        chat_detail_info = ""
        if os.path.exists(self.session_file_path):
            chat_history_dict = dmu.read_json_file(session_file_name, self.session_folder_path)
            chat_history_dict_seq = chat_history_dict[seq][sub_seq]

            chat_detail_info += "\n[Execution info]\n"
            chat_detail_info += "Function: "+chat_history_dict_seq["setting"]["engine"]["FUNC_NAME"]+"\n"
            chat_detail_info += "Prompt template: "+chat_history_dict_seq["prompt"]["prompt_template"]["setting"]+"\n"
            chat_detail_info += "RAG data: "
            for rag_set_dict in chat_history_dict_seq["prompt"]["knowledge_rag"]["setting"]:
                chat_detail_info += str(rag_set_dict["DATA"])
            chat_detail_info += "\n"

            chat_detail_info += "\n[Execution result]\n"
            chat_detail_info += "Agent: "+chat_history_dict_seq["setting"]["agent_file"]+"\n"
            chat_detail_info += "Model: "+chat_history_dict_seq["setting"]["engine"]["MODEL"]+"("+str(chat_history_dict_seq["setting"]["engine"]["PARAMETER"])+")\n"
            chat_detail_info += "Response time: "+dmu.get_time_diff(chat_history_dict_seq["prompt"]["timestamp"], chat_history_dict_seq["response"]["timestamp"], format_str="%Y-%m-%d %H:%M:%S.%f")+"\n"
            chat_detail_info += "Prompt tokens: "+str(chat_history_dict_seq["prompt"]["token"])+"\n"
            chat_detail_info += "Response tokens: "+str(chat_history_dict_seq["response"]["token"])+"\n"

            if "log" in chat_history_dict_seq:
                chat_detail_info += "\n[Execution history]\n"
                chat_detail_info += chat_history_dict_seq["log"]["timestamp_log"]

            if "digest" in chat_history_dict_seq:
                chat_detail_info += "\n[Conversation digest]\n"
                chat_detail_info += "Agent: "+chat_history_dict_seq["digest"]["agent_file"]+"\n"
                if "model" in chat_history_dict_seq["digest"]:
                    chat_detail_info += "Model: "+chat_history_dict_seq["digest"]["model"]+"\n"
                if "timestamp_start" in chat_history_dict_seq["digest"] and "timestamp" in chat_history_dict_seq["digest"]:
                    chat_detail_info += "Duration: "+dmu.get_time_diff(chat_history_dict_seq["digest"]["timestamp_start"], chat_history_dict_seq["digest"]["timestamp"], format_str="%Y-%m-%d %H:%M:%S.%f")+"\n"
                chat_detail_info += "Response tokens: "+str(chat_history_dict_seq["digest"]["token"])+"\n"
                chat_detail_info += chat_history_dict_seq["digest"]["text"]+"\n"

            chat_detail_info += "\n[Memory]\n"
            for memory_set_dict in chat_history_dict_seq["response"]["reference"]["memory"]:
                chat_detail_info += memory_set_dict["log"]

            if "thinking" in chat_history_dict_seq["prompt"] and chat_history_dict_seq["prompt"]["thinking"]:
                thinking = chat_history_dict_seq["prompt"]["thinking"]
                chat_detail_info += "\n【Thinking】\n"
                if "agent_file" in thinking:
                    chat_detail_info += "Agent: "+thinking["agent_file"]+"\n"
                if "model" in thinking:
                    chat_detail_info += "Model: "+thinking["model"]+"\n"
                if "duration_sec" in thinking:
                    chat_detail_info += "Duration: "+str(thinking["duration_sec"])+"s\n"
                if "prompt_token" in thinking:
                    chat_detail_info += "Prompt tokens: "+str(thinking["prompt_token"])+"\n"
                if "response_token" in thinking:
                    chat_detail_info += "Response tokens: "+str(thinking["response_token"])+"\n"
                if "reasoning" in thinking:
                    chat_detail_info += "Reasoning: "+thinking["reasoning"]+"\n"
                if "result" in thinking:
                    chat_detail_info += "Decision: "+str(thinking["result"])+"\n"

            chat_detail_info += "\n[RAG search query]\n"
            if chat_history_dict_seq["prompt"]["RAG_query_genetor"]:
                rag_qg = chat_history_dict_seq["prompt"]["RAG_query_genetor"]
                chat_detail_info += "Agent: "+rag_qg["agent_file"]+"\n"
                chat_detail_info += "Model: "+rag_qg["model"]+"\n"
                if "duration_sec" in rag_qg:
                    chat_detail_info += "Duration: "+str(rag_qg["duration_sec"])+"s\n"
                if rag_qg.get("rag_query_hint"):
                    chat_detail_info += "Thinking hint: "+rag_qg["rag_query_hint"]+"\n"
                chat_detail_info += "Prompt tokens: "+str(rag_qg["prompt_token"])+"\n"
                chat_detail_info += "Response tokens: "+str(rag_qg["response_token"])+"\n"
                chat_detail_info += rag_qg["llm_response"]+"\n"

            chat_detail_info += "\n[Meta search]\n"
            if chat_history_dict_seq["prompt"]["meta_search"]:
                meta_date = chat_history_dict_seq["prompt"]["meta_search"]["date"]
                chat_detail_info += "[Date search]\n"
                chat_detail_info += "Agent: "+meta_date["agent_file"]+"\n"
                chat_detail_info += "Model: "+meta_date["model"]+"\n"
                if "duration_sec" in meta_date:
                    chat_detail_info += "Duration: "+str(meta_date["duration_sec"])+"s\n"
                chat_detail_info += "Prompt tokens: "+str(meta_date["prompt_token"])+"\n"
                chat_detail_info += "Response tokens: "+str(meta_date["response_token"])+"\n"
                chat_detail_info += "Conditions: "+str(meta_date["condition_list"])+"\n"
                chat_detail_info += meta_date["llm_response"]+"\n"

            # Display PageIndex selected pages
            page_index_refs = [r for r in chat_history_dict_seq["response"]["reference"]["knowledge_rag"] if "page_id" in r]
            if page_index_refs:
                chat_detail_info += "\n[PageIndex selected pages]\n"
                for ref in page_index_refs:
                    ref_dict = dmu.parse_log_template(ref)
                    page_id = ref_dict.get("page_id", "")
                    title = ref_dict.get("title", "")
                    category = ref_dict.get("category", "")
                    summary = ref_dict.get("summary", "")
                    chat_detail_info += f"[{page_id}] {title}（{category}）\n  {summary}\n"

            chat_detail_info += "\n[RAG context]\n["
            for rag_set_dict in chat_history_dict_seq["response"]["reference"]["knowledge_rag"]:
                chat_detail_info += "{"+ rag_set_dict.replace("\n", "").replace("$", "＄") + "},\n"
            if chat_detail_info.endswith(",\n"):
                chat_detail_info = chat_detail_info[:-2] + "]"+"\n"

            chat_detail_info += "\n[Content context]\n"
            for content_dict in chat_history_dict_seq["prompt"]["query"]["contents"]:
                chat_detail_info += content_dict["context"]+"\n"

            chat_detail_info += "\n[Web search result]\n"
            if "web_search" in chat_history_dict_seq["prompt"]:
                web_dict = chat_history_dict_seq["prompt"]["web_search"]
                if web_dict:
                    if "engine" in web_dict:
                        chat_detail_info += "Search engine: "+web_dict["engine"]+"\n"
                    if "model" in web_dict:
                        chat_detail_info += "Model: "+web_dict["model"]+"\n"
                    if "duration_sec" in web_dict:
                        chat_detail_info += "Duration: "+str(web_dict["duration_sec"])+"s\n"
                    if "search_text" in web_dict:
                        chat_detail_info += "Search text: "+web_dict["search_text"]+"\n"
                    chat_detail_info += web_dict["web_context"]+"\n"
                    chat_detail_info += "Reference URLs:\n"
                    for url in web_dict["urls"]:
                        url_title = url.get("title") or ""
                        url_date = url.get("date") or ""
                        url_link = url.get("url") or ""
                        chat_detail_info += f"{url_title}({url_date}){url_link}\n"

            # Display user memory (injected context)
            _um_ctx = chat_history_dict_seq.get("prompt", {}).get("user_memory_context") or ""
            _um_used = chat_history_dict_seq.get("response", {}).get("reference", {}).get("user_memory") or []
            _um_meta = chat_history_dict_seq.get("prompt", {}).get("user_memory_meta") or {}
            _um_keywords = _um_meta.get("short_keywords") or []
            if _um_ctx or _um_used or _um_keywords:
                chat_detail_info += "\n[User memory]\n"
                if _um_used:
                    chat_detail_info += "Reference IDs: " + ", ".join(str(x) for x in _um_used) + "\n"
                if _um_keywords:
                    chat_detail_info += "Short search keywords: " + str(list(_um_keywords)) + "\n"
                if _um_ctx:
                    chat_detail_info += _um_ctx + "\n"

        return chat_detail_info

    # Save the content file
    def save_contents_file(self, from_file_path, content_file_name):
        to_folder_path = self.session_contents_folder_path
        to_file_path = str(Path(to_folder_path) / content_file_name)
        # Create the content folder if missing
        if not os.path.exists(to_folder_path):
            os.makedirs(to_folder_path, exist_ok=True)
        if temp_move_flg == "Y":
            dmu.copy_file(from_file_path, to_file_path)
