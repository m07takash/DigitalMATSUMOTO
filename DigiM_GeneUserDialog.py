"""[Deprecated] DigiM_GeneUserMemory への後方互換シム。

旧 UserDialog（Sample10_UserDialog.csv / agent_58UserDialog / practice_13UserDialog）
は廃止され、3層構造の UserMemory（短期/中期/長期）に置換されました。

この関数は旧 WebUI（WebDigiMatsuAgent.py）からの呼び出しを受けても
新しい短期メモリ生成パイプラインへブリッジするだけのスタブです。
"""
import logging

logger = logging.getLogger(__name__)


def save_user_dialogs(service_info=None, user_info=None):
    try:
        import DigiM_GeneUserMemory as dmgum
    except Exception as e:
        logger.warning(f"[user_memory.shim] DigiM_GeneUserMemory読込失敗: {e}")
        return
    try:
        result = dmgum.save_history_for_unsaved_sessions()
        logger.info(f"[user_memory.shim] save_history result: {result}")
    except Exception as e:
        logger.error(f"[user_memory.shim] save_history_for_unsaved_sessions失敗: {e}")
