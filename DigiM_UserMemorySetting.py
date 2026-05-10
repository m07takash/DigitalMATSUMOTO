"""ユーザーメモリのOn/Off設定（2階層: システム > ユーザーマスタ）。

優先順:
  1. ユーザーマスタの Allowed["User Memory Layers"] (users.json または RDB)
  2. システムデフォルト   (system.env: USER_MEMORY_DEFAULT_LAYERS)

ユーザーが自分の `layers` を変更できるかは Allowed["User Memory"] (true/false) で判定。
WebUIはこのフラグでサイドバー表示をゲートし、true のユーザーだけが
このモジュールの save_user_setting を呼ぶ前提。
"""
import logging
import os

from dotenv import load_dotenv

import DigiM_Auth as dma_auth
import DigiM_UserMemory as dmum

logger = logging.getLogger(__name__)

if os.path.exists("system.env"):
    load_dotenv("system.env")

ALLOWED_LAYERS_KEY = "User Memory Layers"
ALLOWED_PERMISSION_KEY = "User Memory"


def _get_user_record(user_id: str) -> dict:
    try:
        users = dma_auth.load_user_master()
    except Exception as e:
        logger.warning(f"[user_memory] ユーザーマスタ読込失敗 {user_id}: {e}")
        return {}
    return users.get(user_id, {}) or {}


def get_system_default_layers() -> list:
    return dmum.get_default_layers()


def is_user_memory_allowed(user_id: str) -> bool:
    """ユーザーが User Memory の編集を許可されているか（Allowed.User Memory=True）。"""
    rec = _get_user_record(user_id)
    allowed = rec.get("Allowed") or {}
    return bool(allowed.get(ALLOWED_PERMISSION_KEY, False))


def load_user_setting(user_id: str) -> dict:
    """ユーザーマスタから User Memory Layers を取得。

    キーが存在する場合は空リストでもユーザーの明示的な選択として尊重し、
    キーが存在しない場合のみシステムデフォルトを返す。
    返却: {"layers": [...]}
    """
    rec = _get_user_record(user_id)
    allowed = rec.get("Allowed") or {}
    layers = allowed.get(ALLOWED_LAYERS_KEY)
    if isinstance(layers, list):
        return {"layers": [l for l in layers if l in dmum.LAYERS]}
    return {"layers": get_system_default_layers()}


def save_user_setting(user_id: str, layers: list):
    """ユーザーマスタの Allowed["User Memory Layers"] を更新。

    Allowed["User Memory"]=True のユーザーに限り呼び出すこと（WebUI側でゲート）。
    """
    try:
        users = dma_auth.load_user_master()
    except Exception as e:
        logger.error(f"[user_memory] ユーザーマスタ読込失敗 {user_id}: {e}")
        return
    if user_id not in users:
        logger.warning(f"[user_memory] 未登録ユーザー: {user_id}")
        return
    if not isinstance(users[user_id].get("Allowed"), dict):
        users[user_id]["Allowed"] = {}
    users[user_id]["Allowed"][ALLOWED_LAYERS_KEY] = [l for l in (layers or []) if l in dmum.LAYERS]
    try:
        dma_auth.save_user_master(users)
    except Exception as e:
        logger.error(f"[user_memory] ユーザーマスタ保存失敗 {user_id}: {e}")


def resolve_active_layers(user_id: str) -> list:
    """実効的に使う層リストを返す（ユーザーマスタ優先、無ければシステムデフォルト）。"""
    user = load_user_setting(user_id)
    if user.get("layers") is not None:
        return user["layers"]
    return get_system_default_layers()
