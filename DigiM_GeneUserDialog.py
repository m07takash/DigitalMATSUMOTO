import os
import csv
from datetime import datetime
from dotenv import load_dotenv

import DigiM_Session as dms
import DigiM_Util as dmu
import DigiM_Notion as dmn
import DigiM_Tool as dmt

# setting.yamlからフォルダパスなどを設定
system_setting_dict = dmu.read_yaml_file("setting.yaml")
mst_folder_path = system_setting_dict["MST_FOLDER"]
rag_data_csv_path = system_setting_dict["RAG_DATA_CSV_FOLDER"]

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
notion_db_mst_file = os.getenv("NOTION_MST_FILE")
user_dialog_save_mode = os.getenv("USER_DIALOG_SAVE_MODE")
user_dialog_save_db = os.getenv("USER_DIALOG_SAVE_DB")

# データの保存形式の設定
def get_user_dialog_data(session_id):
    user_dialog_data = {}
    session = dms.DigiMSession(session_id)
    history_dict = session.chat_history_active_dict
    if history_dict:
        max_seq = dms.max_seq_dict(history_dict)
        if "SETTING" in history_dict[max_seq]:
            create_date = dms.get_last_update_date(session_id) #dms.get_history_update_date(history_dict)
            service_id, user_id = dms.get_ids(session_id)
            #service_id = history_dict[max_seq]["SETTING"]["service_info"]["SERVICE_ID"]
            #user_id = history_dict[max_seq]["SETTING"]["user_info"]["USER_ID"]
            session_name = dms.get_session_name(session_id) #history_dict[max_seq][max_sub_seq]["setting"]["session_name"]
            max_sub_seq = dms.max_seq_dict(history_dict[max_seq])

            user_dialog_data["title"] = f"[ユーザーの傾向]セッション{session_id}"
#            user_dialog_data["create_date"] = dmu.safe_parse_timestamp(create_date.strftime("%Y/%m/%d %H:%M:%S"))
            user_dialog_data["create_date"] = dmu.safe_parse_timestamp(datetime.fromisoformat(create_date).strftime("%Y/%m/%d %H:%M:%S"))
            user_dialog_data["service_id"] = service_id
            user_dialog_data["user_id"] = user_id
            user_dialog_data["session_id"] = session_id
            user_dialog_data["session_name"] = session_name
            user_dialog_data["seq"] = int(max_seq)
            user_dialog_data["sub_seq"] = int(max_sub_seq)
    return user_dialog_data

# CSVファイルへの保存
def save_user_dialog_csv(service_info, user_info, save_session_ids, del_session_ids):
    file_path = rag_data_csv_path + user_dialog_save_db + ".csv"
    file_session_id_list = []
    fieldnames = [
        "title",
        "flg",
        "create_date",
        "service_id",
        "user_id",
        "session_id",
        "session_name",
        "seq",
        "sub_seq",
        "dialog"
    ]

    # 現在のデータを読み込み
    records = []
    if os.path.exists(file_path):
        with open(file_path, mode="r", encoding="utf-8-sig") as csvfile:
            reader = csv.DictReader(csvfile)
            records = list(reader)

    for i, row in enumerate(records):
        file_session_id_list.append(row.get("session_id"))
        # データの更新
        if row.get("session_id") in save_session_ids:
            user_dialog_data = get_user_dialog_data(row.get("session_id"))
            user_dialog_data["flg"] = "Y"
            user_dialog_data["create_date"] = datetime.fromisoformat(user_dialog_data["create_date"]).strftime("%Y/%m/%d")
            _, _, user_dialog, _, _, _ = dmt.gene_user_dialog(service_info, user_info, row.get("session_id"), "", "", "")
            user_dialog_data["dialog"] = user_dialog
            records[i] = {k: str(user_dialog_data.get(k, "")).replace('\r\n', '').replace('\r', '').replace('\n', '') for k in fieldnames}

            save_session = dms.DigiMSession(row.get("session_id"), user_dialog_data["session_name"])
            save_session.save_user_dialog_session("SAVED")

        # データの論理削除
        if row.get("session_id") in del_session_ids:
            records[i]["flg"] = "N"        

    for save_session_id in save_session_ids:
        if save_session_id not in file_session_id_list:
            user_dialog_data = get_user_dialog_data(save_session_id)
            user_dialog_data["flg"] = "Y"
            user_dialog_data["create_date"] = datetime.fromisoformat(user_dialog_data["create_date"]).strftime("%Y/%m/%d")
            _, _, user_dialog, _, _, _ = dmt.gene_user_dialog(service_info, user_info, save_session_id, "", "", "")
            user_dialog_data["dialog"] = user_dialog
            records.append({k: str(user_dialog_data.get(k, "")).replace('\r\n', '').replace('\r', '').replace('\n', '') for k in fieldnames})

            # セッションの状態を保存済みに変更
            save_session = dms.DigiMSession(save_session_id, user_dialog_data["session_name"])
            save_session.save_user_dialog_session("SAVED")

    # 全体を書き戻し（上書き保存）
    with open(file_path, mode="w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


# Notionデータベースへの保存
def save_user_dialog_notion(service_info, user_info, save_session_ids, del_session_ids):
    notion_db_mst_file_path = mst_folder_path + notion_db_mst_file
    notion_db_mst = dmu.read_json_file(notion_db_mst_file_path)
    db_id = notion_db_mst[user_dialog_save_db]
    page_session_id_list = []
    
    # Notionページの取得
    pages = dmn.get_all_pages(db_id)
    for page in pages:
        page_id = page["id"]
        page_session_id = dmn.get_notion_item_by_id(pages, page_id, "セッションID", "rich_text")
        page_session_id_list.append(page_session_id)
        
        # ページの上書き
        if page_session_id in save_session_ids:
            user_dialog_data = get_user_dialog_data(page_session_id)
            if user_dialog_data:
                dmn.update_notion_chk(page_id, "有効Chk", True)
                dmn.update_notion_date(page_id, "タイムスタンプ", user_dialog_data["create_date"])
                dmn.update_notion_rich_text_content(page_id, "サービスID", user_dialog_data["service_id"])
                dmn.update_notion_rich_text_content(page_id, "ユーザーID", user_dialog_data["user_id"])
                dmn.update_notion_rich_text_content(page_id, "セッションID", user_dialog_data["session_id"])
                dmn.update_notion_rich_text_content(page_id, "セッション名", user_dialog_data["session_name"])
                dmn.update_notion_num(page_id, "seq", user_dialog_data["seq"])
                dmn.update_notion_num(page_id, "sub_seq", user_dialog_data["sub_seq"])
                _, _, user_dialog, _, _, _ = dmt.gene_user_dialog(service_info, user_info, page_session_id, "", "", "")
                dmn.update_notion_rich_text_content(page_id, "ダイアログ", user_dialog)
                
                # セッションの状態を保存済みに変更
                save_session = dms.DigiMSession(page_session_id, user_dialog_data["session_name"])
                save_session.save_user_dialog_session("SAVED")
        
        # ページの論理削除
        if page_session_id in del_session_ids:
            dmn.update_notion_chk(page_id, "有効Chk", False)
    
    # ページの追加
    for save_session_id in save_session_ids:
        if save_session_id not in page_session_id_list:
            user_dialog_data = get_user_dialog_data(save_session_id)
            response = dmn.create_page(db_id, user_dialog_data["title"])
            page_id = response["id"]
            dmn.update_notion_chk(page_id, "有効Chk", True)
            dmn.update_notion_date(page_id, "タイムスタンプ", user_dialog_data["create_date"])
            dmn.update_notion_rich_text_content(page_id, "サービスID", user_dialog_data["service_id"])
            dmn.update_notion_rich_text_content(page_id, "ユーザーID", user_dialog_data["user_id"])
            dmn.update_notion_rich_text_content(page_id, "セッションID", save_session_id)
            dmn.update_notion_rich_text_content(page_id, "セッション名", user_dialog_data["session_name"])
            dmn.update_notion_num(page_id, "seq", user_dialog_data["seq"])
            dmn.update_notion_num(page_id, "sub_seq", user_dialog_data["sub_seq"])
            _, _, user_dialog, _, _, _ = dmt.gene_user_dialog(service_info, user_info, save_session_id, "", "", "")
            dmn.update_notion_rich_text_content(page_id, "ダイアログ", user_dialog)
            
            # セッションの状態を保存済みに変更
            save_session = dms.DigiMSession(save_session_id, user_dialog_data["session_name"])
            save_session.save_user_dialog_session("SAVED")

# ユーザーダイアログの保存
def save_user_dialogs(service_info, user_info):
    sessions = dms.get_session_list()
    save_session_ids = []
    del_session_ids = []
    for session_dict in sessions:
        session_id = session_dict["id"]
        user_dialog_status = dms.get_user_dialog_session(session_id)
        if user_dialog_status == "UNSAVED":
            save_session_ids.append(session_id)
        elif user_dialog_status == "DISCARD":
            del_session_ids.append(session_id)

    if user_dialog_save_mode == "Notion":
        save_user_dialog_notion(service_info, user_info, save_session_ids, del_session_ids)
    else:
        save_user_dialog_csv(service_info, user_info, save_session_ids, del_session_ids)

    

