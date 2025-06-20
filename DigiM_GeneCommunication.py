import os
import pytz
import csv
from datetime import datetime
from dateutil import parser
from dotenv import load_dotenv

import DigiM_Session as dms
import DigiM_Context as dmc
import DigiM_Tool as dmt
import DigiM_Util as dmu
import DigiM_Notion as dmn

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
timezone = os.getenv("TIMEZONE")
mst_folder_path = os.getenv("MST_FOLDER")
rag_data_csv_path = os.getenv("RAG_DATA_CSV_FOLDER")
notion_db_mst_file = os.getenv("NOTION_MST_FILE")
save_communication_mode = os.getenv("SAVE_COMMUNICATION_MODE")
save_communication_db = os.getenv("SAVE_COMMUNICATION_DB")
default_communication_category = os.getenv("DEFAULT_COMMUNICATION_CATEGORY")

#タイムスタンプ文字列を安全に解析し、時刻までのdatetimeオブジェクト
def safe_parse_timestamp(timestamp_str):
    jst = pytz.timezone(timezone)
    try:
        return jst.localize(datetime.strptime(timestamp_str, "%Y/%m/%d %H:%M:%S")).isoformat()
    except ValueError:
        return datetime.now(jst).isoformat()

# フィードバックデータの取得
def get_feedback_data(fb_k, memo, k1, k2, v2):
    fb_data = {}
    fb_data["title"] = v2["feedback"]["name"]+"-"+fb_k+"("+v2["setting"]["situation"]["TIME"]+")"
    fb_data["RAG_Category"] = fb_k
    fb_data["category"] = default_communication_category
    fb_data["timestamp"] = safe_parse_timestamp(v2["setting"]["situation"]["TIME"])
    fb_data["session_name"] = v2["setting"]["session_name"]    
    fb_data["seq"] = int(k1)
    fb_data["sub_seq"] = int(k2)
    fb_data["query"] = v2["prompt"]["query"]["input"]
    situation = v2["setting"]["situation"]["SITUATION"]
    if situation:
        query += "\n"+situation
    fb_data["response"] = v2["response"]["text"]
    fb_data["memo"] = memo
    return fb_data

# JSONファイルへの保存
def save_communication_json(fb_data):
    fieldnames = [
        "title",
        "RAG_Category",
        "category",
        "timestamp",
        "memo",
        "session_name",
        "seq",
        "sub_seq",
        "query",
        "response"
    ]

    # ファイル名を設定
    file_path = rag_data_csv_path + save_communication_db + ".csv"

    # 現在のデータを読み込み
    records = []
    if os.path.exists(file_path):
        with open(file_path, mode="r", encoding="utf-8") as csvfile:
            reader = csv.DictReader(csvfile)
            records = list(reader)

    # Titleが一致する行があれば上書き、なければ追加
    updated = False
    for i, row in enumerate(records):
        if row.get("title") == fb_data.get("title"):
            records[i] = {k: str(fb_data.get(k, "")) for k in fieldnames}
            updated = True
            break

    if not updated:
        records.append({k: str(fb_data.get(k, "")) for k in fieldnames})

    # 全体を書き戻し（上書き保存）
    with open(file_path, mode="w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

# Notionデータベースへの保存
def save_communication_notion(fb_data):
    notion_db_mst_file_path = mst_folder_path + notion_db_mst_file
    notion_db_mst = dmu.read_json_file(notion_db_mst_file_path)
    db_id = notion_db_mst[save_communication_db]
    
    # Notionページの保存
    response = dmn.create_page(db_id, fb_data["title"])
    page_id = response["id"]
    dmn.update_notion_select(page_id, "RAGカテゴリ", fb_data["RAG_Category"])
    dmn.update_notion_select(page_id, "カテゴリ", fb_data["category"])
    dmn.update_notion_date(page_id, "タイムスタンプ", fb_data["timestamp"])
    dmn.update_notion_rich_text_content(page_id, "コンテキスト", fb_data["memo"])
    dmn.update_notion_rich_text_content(page_id, "セッション", fb_data["session_name"])
    dmn.update_notion_num(page_id, "seq", fb_data["seq"])
    dmn.update_notion_num(page_id, "sub_seq", fb_data["sub_seq"])
    dmn.update_notion_rich_text_content(page_id, "クエリ", fb_data["query"])
    dmn.update_notion_rich_text_content(page_id, "レスポンス", fb_data["response"])
    dmn.update_notion_rich_text_content(page_id, "メモ", fb_data["memo"])
    dmn.update_notion_chk(page_id, "確定Chk", True)

# フィードバックデータの保存
def create_communication_data(session_id):
    session = dms.DigiMSession(session_id)
    history_dict = session.chat_history_dict
    for k1, v1 in history_dict.items():
        for k2, v2 in v1.items():
            if k2 != "SETTING":
                if "feedback" in v2.keys():
                    for fb_k, fb_v in v2["feedback"].items():
                        if fb_k != "name" and fb_v["flg"]:
                            fb_data = get_feedback_data(fb_k, fb_v["memo"], k1, k2, v2)
                            if save_communication_mode == "Notion":
                                save_communication_notion(fb_data)
                            else:
                                save_communication_json(fb_data)
                            v2["feedback"][fb_k]["flg"]=False
                    session.set_feedback_history(k1, k2, v2["feedback"])

