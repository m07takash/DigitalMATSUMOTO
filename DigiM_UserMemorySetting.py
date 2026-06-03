"""On/Off settings for User Memory (2-layer hierarchy: system > user master).

Priority order:
  1. Allowed["User Memory Layers"] in the user master (users.json or RDB)
  2. System default (system.env: USER_MEMORY_DEFAULT_LAYERS)

Whether a user can change their own `layers` is determined by
Allowed["User Memory"] (true/false). The WebUI gates the sidebar display
with this flag, and only users with `true` are expected to call
save_user_setting from this module.
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
        logger.warning(f"[user_memory] failed to load user master {user_id}: {e}")
        return {}
    return users.get(user_id, {}) or {}


def get_system_default_layers() -> list:
    return dmum.get_default_layers()


def is_user_memory_allowed(user_id: str) -> bool:
    """Whether the user is allowed to edit User Memory (Allowed.User Memory=True)."""
    rec = _get_user_record(user_id)
    allowed = rec.get("Allowed") or {}
    return bool(allowed.get(ALLOWED_PERMISSION_KEY, False))


def load_user_setting(user_id: str) -> dict:
    """Fetch User Memory Layers from the user master.

    If the key exists, an empty list is still respected as the user's explicit
    selection; only when the key is absent do we fall back to the system default.
    Returns: {"layers": [...]}
    """
    rec = _get_user_record(user_id)
    allowed = rec.get("Allowed") or {}
    layers = allowed.get(ALLOWED_LAYERS_KEY)
    if isinstance(layers, list):
        return {"layers": [l for l in layers if l in dmum.LAYERS]}
    return {"layers": get_system_default_layers()}


def save_user_setting(user_id: str, layers: list):
    """Update Allowed["User Memory Layers"] in the user master.

    Only call this for users where Allowed["User Memory"]=True (gated on the WebUI side).
    """
    try:
        users = dma_auth.load_user_master()
    except Exception as e:
        logger.error(f"[user_memory] failed to load user master {user_id}: {e}")
        return
    if user_id not in users:
        logger.warning(f"[user_memory] unregistered user: {user_id}")
        return
    if not isinstance(users[user_id].get("Allowed"), dict):
        users[user_id]["Allowed"] = {}
    users[user_id]["Allowed"][ALLOWED_LAYERS_KEY] = [l for l in (layers or []) if l in dmum.LAYERS]
    try:
        dma_auth.save_user_master(users)
    except Exception as e:
        logger.error(f"[user_memory] failed to save user master {user_id}: {e}")


def resolve_active_layers(user_id: str) -> list:
    """Return the effective layer list (user master takes priority, else the system default)."""
    user = load_user_setting(user_id)
    if user.get("layers") is not None:
        return user["layers"]
    return get_system_default_layers()
