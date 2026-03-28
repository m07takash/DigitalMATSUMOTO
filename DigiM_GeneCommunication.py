import os
import csv
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import DigiM_Agent as dma
import DigiM_Session as dms
import DigiM_Util as dmu
import DigiM_Notion as dmn

logger = logging.getLogger(__name__)

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]
rag_data_csv_path = system_setting_dict["RAG_DATA_CSV_FOLDER"]

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
notion_db_mst_file = os.getenv("NOTION_MST_FILE")

# デフォルトのFIELD_MAP（後方互換用）
# name: CSV列名, notion_name: Notionプロパティ名（省略時はnameを使用）
DEFAULT_FIELD_MAP = [
    {"key": "title",        "name": "title",        "notion_name": "title",         "type": "title"},
    {"key": "RAG_Category", "name": "RAG_Category", "notion_name": "RAGカテゴリ",   "type": "category"},
    {"key": "category",     "name": "category",     "notion_name": "カテゴリ",       "type": "category"},
    {"key": "create_date",  "name": "create_date",  "notion_name": "タイムスタンプ", "type": "date"},
    {"key": "memo",         "name": "memo",         "notion_name": "メモ",           "type": "text"},
    {"key": "service_id",   "name": "service_id",   "notion_name": "サービスID",     "type": "text"},
    {"key": "user_id",      "name": "user_id",      "notion_name": "ユーザーID",     "type": "text"},
    {"key": "session_name", "name": "session_name", "notion_name": "セッション",     "type": "text"},
    {"key": "seq",          "name": "seq",           "notion_name": "seq",           "type": "number"},
    {"key": "sub_seq",      "name": "sub_seq",       "notion_name": "sub_seq",       "type": "number"},
    {"key": "query",        "name": "query",         "notion_name": "クエリ",        "type": "text"},
    {"key": "response",     "name": "response",      "notion_name": "レスポンス",    "type": "text"},
]

# フィードバックデータの定義
def get_feedback_data(fb_k, memo, category, k1, k2, v2, service_id, user_id):
    fb_data = {}
    fb_data["title"] = v2["setting"]["session_name"][:20]+"-"+memo[:20]
    fb_data["RAG_Category"] = fb_k
    fb_data["category"] = category
    fb_data["create_date"] = dmu.safe_parse_timestamp(v2["prompt"]["query"]["situation"]["TIME"])
    fb_data["service_id"] = service_id
    fb_data["user_id"] = user_id
    fb_data["session_name"] = v2["setting"]["session_name"]
    fb_data["seq"] = int(k1)
    fb_data["sub_seq"] = int(k2)
    fb_data["query"] = v2["prompt"]["query"]["input"]
    situation = v2["prompt"]["query"]["situation"]["SITUATION"]
    if situation:
        fb_data["query"] = fb_data["query"]+"\n"+situation
    fb_data["response"] = v2["response"]["text"]
    fb_data["memo"] = memo
    return fb_data

# CSVファイルへの保存
def save_communication_csv(fb_data, save_db, field_map):
    fieldnames = [f["name"] for f in field_map]
    date_keys = {f["key"] for f in field_map if f["type"] == "date"}

    # 内部キー → 出力列名のマッピングで行データを構築
    row_data = {}
    for f in field_map:
        val = fb_data.get(f["key"], f.get("default", ""))
        if f["key"] in date_keys and val:
            try:
                val = datetime.fromisoformat(str(val)).strftime("%Y/%m/%d")
            except Exception:
                pass
        row_data[f["name"]] = str(val).replace('\r\n', '').replace('\r', '').replace('\n', '')

    # ファイル名を設定
    file_path = rag_data_csv_path + save_db + ".csv"

    # 現在のデータを読み込み
    records = []
    if os.path.exists(file_path):
        with open(file_path, mode="r", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            records = list(reader)

    # title列名を取得（FIELD_MAPでtype="title"の列名）
    title_col = next((f["name"] for f in field_map if f["type"] == "title"), fieldnames[0])

    # Titleが一致する行があれば上書き、なければ追加
    updated = False
    for i, row in enumerate(records):
        if row.get(title_col) == row_data.get(title_col):
            records[i] = row_data
            updated = True
            break

    if not updated:
        records.append(row_data)

    # 全体を書き戻し（上書き保存）
    with open(file_path, mode="w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

# Notionデータベースへの保存
def save_communication_notion(fb_data, save_db, field_map):
    notion_db_mst_file_path = str(Path(mst_folder_path) / notion_db_mst_file)
    notion_db_mst = dmu.read_json_file(notion_db_mst_file_path)
    if save_db not in notion_db_mst:
        logger.error(f"Notionマスターに '{save_db}' が見つかりません。登録済みキー: {list(notion_db_mst.keys())}")
        return
    db_id = notion_db_mst[save_db]

    # titleフィールドを取得してNotionページを作成
    title_field = next((f for f in field_map if f["type"] == "title"), None)
    title_val = fb_data.get(title_field["key"], "") if title_field else fb_data.get("title", "")
    response = dmn.create_page(db_id, title_val)
    page_id = response["id"]

    # FIELD_MAPに基づいて型別にNotionプロパティを更新
    for f in field_map:
        if f["type"] == "title":
            continue
        val = fb_data.get(f["key"], f.get("default", ""))
        prop_name = f.get("notion_name", f["name"])
        field_type = f["type"]

        if field_type == "text":
            dmn.update_notion_rich_text_content(page_id, prop_name, str(val))
        elif field_type == "number":
            dmn.update_notion_num(page_id, prop_name, val)
        elif field_type == "date":
            dmn.update_notion_date(page_id, prop_name, val)
        elif field_type == "category":
            dmn.update_notion_select(page_id, prop_name, str(val))
        elif field_type == "checkbox":
            dmn.update_notion_chk(page_id, prop_name, bool(val))

# フィードバックデータの保存
def create_communication_data(session_id, agent_file):
    session = dms.DigiMSession(session_id)
    agent = dma.DigiM_Agent(agent_file)
    save_mode = agent.communication["SAVE_MODE"]
    save_db = agent.communication["SAVE_DB"]
    default_category = agent.communication["DEFAULT_CATEGORY"]
    field_map = agent.communication.get("FIELD_MAP", DEFAULT_FIELD_MAP)

    service_id = ""
    user_id = ""
    history_dict = session.chat_history_dict
    for k1, v1 in history_dict.items():
        for k2, v2 in v1.items():
            if k2 == "SETTING":
                if v2["FLG"] == "N":
                    continue
                if "service_info" not in v2.keys():
                    continue
                service_id = v2["service_info"]["SERVICE_ID"]
                user_id = v2["user_info"]["USER_ID"]
            if k2 != "SETTING":
                if "feedback" in v2.keys():
                    for fb_k, fb_v in v2["feedback"].items():
                        if fb_k != "name" and fb_v["flg"]:
                            category = fb_v.get("category", default_category)
                            fb_data = get_feedback_data(fb_k, fb_v["memo"], category, k1, k2, v2, service_id, user_id)
                            if save_mode == "Notion":
                                save_communication_notion(fb_data, save_db, field_map)
                            else:
                                save_communication_csv(fb_data, save_db, field_map)
                            v2["feedback"][fb_k]["flg"]=False
                    session.set_feedback_history(k1, k2, v2["feedback"])
