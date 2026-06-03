"""[Deprecated] Backward-compatibility shim for DigiM_GeneUserMemory.

The legacy UserDialog (Sample10_UserDialog.csv / agent_58UserDialog /
practice_13UserDialog) has been removed and replaced with the 3-layer
UserMemory (short-term / mid-term / long-term).

This function is just a stub that bridges calls from the legacy WebUI
(WebDigiMatsuAgent.py) to the new short-term memory generation pipeline.
"""
import logging

logger = logging.getLogger(__name__)


def save_user_dialogs(service_info=None, user_info=None):
    try:
        import DigiM_GeneUserMemory as dmgum
    except Exception as e:
        logger.warning(f"[user_memory.shim] failed to load DigiM_GeneUserMemory: {e}")
        return
    try:
        result = dmgum.save_history_for_unsaved_sessions()
        logger.info(f"[user_memory.shim] save_history result: {result}")
    except Exception as e:
        logger.error(f"[user_memory.shim] save_history_for_unsaved_sessions failed: {e}")
