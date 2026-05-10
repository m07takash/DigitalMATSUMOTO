"""ユーザーメモリのOn/Off設定（3階層: システム > ユーザー > セッション）。

優先順:
  1. セッション一時設定 (chat_history SETTING の user_memory_override)
  2. ユーザーマスタ設定 (user/<user_id>/user_memory_setting.json)
  3. システムデフォルト   (system.env: USER_MEMORY_DEFAULT_LAYERS)

ユーザーマスタ設定:
  override_allowed: bool  (ユーザー自身がWebUIで変更できるか — 管理者のみ初期値False)
  layers:           list  (有効化する層のリスト ["short","mid","long"])

setオペレーションは `override_allowed=True` のときのみユーザー自身に許可される。
管理者は `set_admin` 経由でいつでも変更可。
"""
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

import DigiM_Util as dmu
import DigiM_UserMemory as dmum

logger = logging.getLogger(__name__)

if os.path.exists("system.env"):
    load_dotenv("system.env")

_setting = dmu.read_yaml_file("setting.yaml")
_user_folder_path = _setting["USER_FOLDER"]

SETTING_FILENAME = "user_memory_setting.json"


def _user_setting_path(user_id: str) -> str:
    return str(Path(_user_folder_path) / user_id / SETTING_FILENAME)


def get_system_default_layers() -> list:
    return dmum.get_default_layers()


def load_user_setting(user_id: str) -> dict:
    """ユーザーマスタ設定を取得。未設定なら override_allowed=False + システムデフォルト層。"""
    path = _user_setting_path(user_id)
    if os.path.exists(path):
        try:
            data = dmu.read_json_file(path)
            return {
                "override_allowed": bool(data.get("override_allowed", False)),
                "layers": [l for l in data.get("layers", []) if l in dmum.LAYERS],
            }
        except Exception as e:
            logger.warning(f"[user_memory] ユーザー設定読込失敗 {user_id}: {e}")
    return {"override_allowed": False, "layers": get_system_default_layers()}


def save_user_setting(user_id: str, override_allowed: bool, layers: list):
    """管理者またはoverride許可ユーザーが呼び出す。検証は呼び出し側で。"""
    path = _user_setting_path(user_id)
    Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
    payload = {
        "override_allowed": bool(override_allowed),
        "layers": [l for l in (layers or []) if l in dmum.LAYERS],
    }
    dmu.save_json_file(payload, path)


def set_admin(user_id: str, override_allowed: bool, layers: list):
    """管理者操作: そのままsave。"""
    save_user_setting(user_id, override_allowed, layers)


def set_user(user_id: str, layers: list) -> bool:
    """ユーザー操作: override_allowedがTrueの場合のみlayersを変更。
    成功時True、不許可時False。"""
    cur = load_user_setting(user_id)
    if not cur.get("override_allowed"):
        return False
    save_user_setting(user_id, True, layers)
    return True


def resolve_active_layers(user_id: str, session_override=None) -> list:
    """実効的に使う層リストを返す。

    - session_override: そのセッションだけの一時オーバーライド（list or None）
                        空リスト [] は「このセッションは全層Off」を意味する。
    """
    if session_override is not None:
        return [l for l in session_override if l in dmum.LAYERS]
    user = load_user_setting(user_id)
    if user.get("override_allowed") and user.get("layers") is not None:
        return user["layers"]
    return get_system_default_layers()


def is_user_override_allowed(user_id: str) -> bool:
    return bool(load_user_setting(user_id).get("override_allowed", False))
