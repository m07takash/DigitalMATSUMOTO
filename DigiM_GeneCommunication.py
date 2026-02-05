import os
import csv
from datetime import datetime
from dotenv import load_dotenv

import DigiM_Agent as dma
import DigiM_Session as dms
import DigiM_Util as dmu
import DigiM_Notion as dmn

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]
rag_data_csv_path = system_setting_dict["RAG_DATA_CSV_FOLDER"]

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
notion_db_mst_file = os.getenv("NOTION_MST_FILE")

# フィードバックデータの定義
def get_feedback_data(fb_k, memo, k1, k2, v2, default_category, service_id, user_id):
    fb_data = {}
    fb_data["title"] = v2["feedback"]["name"]+"-"+fb_k+"("+v2["prompt"]["query"]["situation"]["TIME"]+")"
    fb_data["RAG_Category"] = fb_k
    fb_data["category"] = default_category
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
def save_communication_csv(fb_data, save_db):
    fieldnames = [
        "title",
        "RAG_Category",
        "category",
        "create_date",
        "memo",
        "service_id",
        "user_id",
        "session_name",
        "seq",
        "sub_seq",
        "query",
        "response"
    ]

    # 日付型を変換
    fb_data["create_date"] = datetime.fromisoformat(fb_data["create_date"]).strftime("%Y/%m/%d")

    # ファイル名を設定
    file_path = rag_data_csv_path + save_db + ".csv"

    # 現在のデータを読み込み
    records = []
    if os.path.exists(file_path):
        with open(file_path, mode="r", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            records = list(reader)

    # Titleが一致する行があれば上書き、なければ追加
    updated = False
    for i, row in enumerate(records):
        if row.get("title") == fb_data.get("title"):
            records[i] = {k: str(fb_data.get(k, "")).replace('\r\n', '').replace('\r', '').replace('\n', '') for k in fieldnames}
            updated = True
            break

    if not updated:
        records.append({k: str(fb_data.get(k, "")).replace('\r\n', '').replace('\r', '').replace('\n', '') for k in fieldnames})

    # 全体を書き戻し（上書き保存）
    with open(file_path, mode="w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

# Notionデータベースへの保存
def save_communication_notion(fb_data, save_db):
    notion_db_mst_file_path = mst_folder_path + notion_db_mst_file
    notion_db_mst = dmu.read_json_file(notion_db_mst_file_path)
    db_id = notion_db_mst[save_db]

    # Notionページの保存
    response = dmn.create_page(db_id, fb_data["title"])
    page_id = response["id"]
    dmn.update_notion_select(page_id, "RAGカテゴリ", fb_data["RAG_Category"])
    dmn.update_notion_select(page_id, "カテゴリ", fb_data["category"])
    dmn.update_notion_date(page_id, "タイムスタンプ", fb_data["create_date"])
    dmn.update_notion_rich_text_content(page_id, "コンテキスト", fb_data["memo"])
    dmn.update_notion_rich_text_content(page_id, "サービスID", fb_data["service_id"])
    dmn.update_notion_rich_text_content(page_id, "ユーザーID", fb_data["user_id"])
    dmn.update_notion_rich_text_content(page_id, "セッション", fb_data["session_name"])
    dmn.update_notion_num(page_id, "seq", fb_data["seq"])
    dmn.update_notion_num(page_id, "sub_seq", fb_data["sub_seq"])
    dmn.update_notion_rich_text_content(page_id, "クエリ", fb_data["query"])
    dmn.update_notion_rich_text_content(page_id, "レスポンス", fb_data["response"])
    dmn.update_notion_rich_text_content(page_id, "メモ", fb_data["memo"])
    dmn.update_notion_chk(page_id, "確定Chk", True)

# フィードバックデータの保存
def create_communication_data(session_id, agent_file):
    session = dms.DigiMSession(session_id)
    agent = dma.DigiM_Agent(agent_file)
    save_mode = agent.communication["SAVE_MODE"]
    save_db = agent.communication["SAVE_DB"]
    default_category = agent.communication["DEFAULT_CATEGORY"]

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
                            fb_data = get_feedback_data(fb_k, fb_v["memo"], k1, k2, v2, default_category, service_id, user_id)
                            if save_mode == "Notion":
                                save_communication_notion(fb_data, save_db)
                            else:
                                save_communication_csv(fb_data, save_db)
                            v2["feedback"][fb_k]["flg"]=False
                    session.set_feedback_history(k1, k2, v2["feedback"])
