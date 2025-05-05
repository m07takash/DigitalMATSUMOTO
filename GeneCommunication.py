import os
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
mst_folder_path = os.getenv("MST_FOLDER")
notion_db_mst_file = os.getenv("NOTION_MST_FILE")

#タイムスタンプ文字列を安全に解析し、時刻までのdatetimeオブジェクト
def safe_parse_timestamp(timestamp_str):
    try:
        return datetime.strptime(timestamp_str, "%Y-%m-%d")
    except ValueError:
        return datetime.now()
    
#    try:
#        # タイムゾーン付きISO形式を解析
#        return parser.isoparse(timestamp_str)
#    except ValueError:
#        try:
#            # 一部フォーマットに対応 (例: "YYYY/MM/DD HH:MM:SS")
#            return datetime.strptime(timestamp_str, "%Y/%m/%d %H:%M:%S")
#        except ValueError:
#            try:
#                # フォーマットが日付だけの場合 (例: "YYYY-MM-DD")
#                return datetime.strptime(timestamp_str, "%Y-%m-%d")
#            except ValueError:
#                # 最後に現在時刻を返す
#                print(f"Invalid timestamp format: {timestamp_str}. Using current time.")
#                return datetime.now()

# 個別ページの作成
def create_page_communication(db_id, title, k1, k2, v_dict):
    # 新規ページ作成
    response = dmn.create_page(db_id, title)
    page_id = response["id"]
    
    # ページアイテムデータの取得
    session_name = v_dict["setting"]["session_name"]    
    seq = int(k1)    
    sub_seq = int(k2)    
    timestamp = safe_parse_timestamp(v_dict["setting"]["situation"]["TIME"])
#    timestamp_str = timestamp.isoformat()
    timestamp_str = datetime.fromisoformat(timestamp.isoformat()).strftime("%Y/%m/%d")
    query = v_dict["prompt"]["query"]["input"]
    situation = v_dict["setting"]["situation"]["SITUATION"]
    if situation:
        query += "\n"+situation
    response = v_dict["response"]["text"]
    good = v_dict["feedback"]["good"]     
    likeme = v_dict["feedback"]["likeme"]

    memo = ""
    if good:
        memo += "「良いコメント」です！"
    if likeme:
        memo += "「松本らしいコメント」です！"
    memo += v_dict["feedback"]["memo"]

    # Notionページの更新
    dmn.update_notion_rich_text_content(page_id, "セッション", session_name)
    dmn.update_notion_num(page_id, "seq", seq)
    dmn.update_notion_num(page_id, "sub_seq", sub_seq)
    dmn.update_notion_date(page_id, "タイムスタンプ", timestamp_str)
    dmn.update_notion_rich_text_content(page_id, "クエリ", query)
    dmn.update_notion_rich_text_content(page_id, "レスポンス", response)
#    dmn.update_notion_rich_text_content(page_id, "コンテキスト", response)
    dmn.update_notion_chk(page_id, "good", good)
    dmn.update_notion_chk(page_id, "likeme", likeme)
    dmn.update_notion_rich_text_content(page_id, "メモ", memo)

# 会話RAGのNotionページ作成
def create_pages_communication(session_id):
    mst_folder_path = os.getenv("MST_FOLDER")
    notion_db_mst_file = os.getenv("NOTION_MST_FILE")
    
    # Notion_DBのIDを取得
    db_name = "DigiMATSU_Communication"
    notion_db_mst_file_path = mst_folder_path + notion_db_mst_file
    notion_db_mst = dmu.read_json_file(notion_db_mst_file_path)
    db_id = notion_db_mst[db_name]
    page_data = dmn.get_all_pages(db_id)
    
    # セッションから会話履歴データを取得
    session = dms.DigiMSession(session_id)
    history_dict = session.chat_history_dict
    for k1, v1 in history_dict.items():
        for k2, v2 in v1.items():
            if k2 != "SETTING":
                if "feedback" in v2.keys():
                    title = k1+"-"+k2+"-"+v2["setting"]["session_name"]+str(safe_parse_timestamp(str(v2["setting"]["situation"]["TIME"])))+v2["prompt"]["query"]["input"][:20]
                    if any(title == item['properties']['名前']['title'][0]['plain_text'] for item in page_data):
                        print(f"{title}は既に作成されています")
                    else:
                        create_page_communication(db_id, title, k1, k2, v2)