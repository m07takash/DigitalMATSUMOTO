import os
import csv
import json
import re
import mimetypes
from datetime import datetime
from dotenv import load_dotenv

import DigiM_Util as dmu
import DigiM_Tool as dmt
import DigiM_Notion as dmn

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
mst_folder_path = os.getenv("MST_FOLDER")
prompt_template_mst_file = os.getenv("PROMPT_TEMPLATE_MST_FILE")
prompt_temp_mst_path = mst_folder_path + prompt_template_mst_file
rag_mst_file = os.getenv("RAG_MST_FILE")
rag_folder_path = os.getenv("RAG_FOLDER")
notion_db_mst_file = os.getenv("NOTION_MST_FILE")

# 現在日付
current_date = datetime.now()

# 添付したコンテンツからコンテキストを取得
def create_contents_context(agent_data, contents, seq=0, sub_seq=0):
    contents_context = ""
    contents_records = []
    image_files = []
    file_seq = 0

    for content in contents:
        content_context, content_record, image_file = get_text_content(agent_data, content, seq, sub_seq, file_seq) 
        contents_context += content_context
        contents_records.append(content_record)
        if image_file:
            image_files.append(image_file)
        file_seq += 1

    return contents_context, contents_records, image_files


# アップロードしたファイルからコンテンツテキストを取得
def get_text_content(agent_data, content, seq, sub_seq, file_seq):
    content_context = ""
    image_file = ""

    # コンテンツに関わる情報を設定
    if os.path.basename(content).startswith("[OUT]"):
        file_name = os.path.basename(content)
    else:
        file_name = "[IN]seq"+str(seq)+"-"+str(sub_seq)+"_"+str(file_seq)+"_"+os.path.basename(content)
    file_size = os.path.getsize(content)
    file_type, encoding = mimetypes.guess_type(content)
    
    if "text" in file_type:
        content_context = "<br>---------<br>ファイル名: "+file_name+"<br><br>"+dmu.read_text_file(content)
    elif "pdf" in file_type:
        content_context = "<br>---------<br>ファイル名: "+file_name+"<br><br>"+json.dumps(dmu.read_pdf_file(content), ensure_ascii=False)
    elif "json" in file_type:
        content_context = "<br>---------<br>ファイル名: "+file_name+"<br><br>"+json.dumps(dmu.read_json_file(content), ensure_ascii=False)
    elif "image" in file_type:
        response, prompt_tokens, response_tokens = dmt.art_critics(image_paths=[content])
        content_context = "<br>---------<br>ファイル名: "+file_name+"<br><br>"+response
        image_file = content
    #elif "video" in file_type:
        #将来的にコンテキストを取得
    #elif "audio" in file_type:
        #将来的にコンテキストを取得

    # コンテンツの記録
    content_records = {"from": content, "to":{"file_name": file_name, "file_type": file_type, "file_size": file_size, "context": content_context}}

    return content_context, content_records, image_file

# プロンプトテンプレートの取得
def set_prompt_template(prompt_temp_cd):
    prompt_temp_mst_path = mst_folder_path + prompt_template_mst_file
    prompt_temps_json = dmu.read_json_file(prompt_temp_mst_path)
    prompt_temp = prompt_temps_json["PROMPT_TEMPLATE"][prompt_temp_cd]
    prompt_template = ""
    if prompt_temp:
        prompt_template = prompt_template + prompt_temp +"\n"
    return prompt_template


# RAGデータ一覧の取得
def get_rag_list():
    identifier="_vec.json"
    rag_list = [r.replace(identifier, "") for r in dmu.get_files(rag_folder_path, identifier)]
    return rag_list


# RAGデータの取得
def select_rag_vector(query_vec, rag_data_list, rag={}):
    total_characters = 0
    buffer = 100
    rag_all = []
    rag_selected = []
    rag_context = ""

    # RAGテキストの選択
    for rag_data in rag_data_list:
        rag_data["rag_name"] = rag["RAG_NAME"]
        if rag["TIMESTAMP"]=="CREATE_DATE":
            if rag_data["create_date"]:
                timestamp = datetime.strptime(dmu.convert_to_ymd(rag_data["create_date"], "%Y-%m-%d"), "%Y-%m-%d")
            else:
                timestamp = current_date
        elif rag["TIMESTAMP"]=="CURRENT_DATE" or not rag["TIMESTAMP"]:
            timestamp = current_date
        else:
            timestamp = datetime.strptime(dmu.convert_to_ymd(rag["TIMESTAMP"], "%Y-%m-%d"), "%Y-%m-%d")
        
        # 埋め込み用の日付設定
        timestamp_str = timestamp.strftime(rag["TIMESTAMP_STYLE"])
        days_difference = (current_date - timestamp).days
        rag_data["timestamp"] = timestamp_str
        rag_data["days_difference"] = days_difference
        
        # 埋め込みベクトルの類似度
        similarity_prompt = dmu.calculate_similarity_vec(query_vec, rag_data["vector_data_key_text"], rag["DISTANCE_LOGIC"])
        rag_data["similarity_prompt"] = round(similarity_prompt,3)

        # チャンクテンプレートでコンテキスト化
        chunk_item_list = re.findall(r"\{(.*?)\}", rag["CHUNK_TEMPLATE"])
        chunk_items = {}
        for item in chunk_item_list:
            chunk_items[item] = rag_data[item]
        rag_data["chunk_context"] = rag["CHUNK_TEMPLATE"].format(**chunk_items)
        rag_data["log_format"] = rag["LOG_TEMPLATE"]

        rag_all.append(rag_data)
    
    # 類似度でソート
    rag_all_sorted = sorted(rag_all, key=lambda x: x["similarity_prompt"])
    
    # RAGテキストを選択（テキスト上限値まで取得）
    rag_context += rag["HEADER_TEMPLATE"]    
    total_char = len(rag["HEADER_TEMPLATE"])
    for rag_data in rag_all_sorted:
        chunk_len = len(rag_data["chunk_context"])
        if total_char + chunk_len + buffer > rag["TEXT_LIMITS"]:
            break
        rag_selected.append(rag_data)
        rag_context += rag_data["chunk_context"]
        total_char = total_char + chunk_len + buffer

    return rag_context, rag_selected


# RAGからのコンテキスト取得
def create_rag_context(query, query_vec=[], rags=[]):
    rag_final_context = "\n------\n"
    rag_final_selected = []

    # RAGデータセットごとに処理    
    for rag in rags:
        rag_data_list = []
        for rag_data in rag["DATA"]:
            rag_data_file = rag_data +'_vec.json'
            rag_data_json = dmu.read_json_file(rag_data_file, rag_folder_path)
            for k, v in rag_data_json.items():
                rag_data_list.append(v)
        
        # RAGデータの選択       
        if rag["RETRIEVER"] == "Vector":
            rag_context, rag_selected = select_rag_vector(query_vec, rag_data_list, rag)    
            rag_final_context += rag_context
            rag_final_selected += rag_selected

    rag_final_context += "----\nこれらの情報を踏まえて、次の質問に日本語で回答してください。\n----\n"

    return rag_final_context, rag_final_selected


# レスポンスとRAGの類似度評価
def get_rag_similarity_response(response_vec, rag_selected, logic="Cosine"):
    rag_ref = []
    
    # 各チャンクと類似度評価
    for rag_data in rag_selected:
        rag_data["value_text_short"] = rag_data["value_text"][:50] #50文字に絞る
        similarity_response = dmu.calculate_similarity_vec(response_vec, rag_data["vector_data_value_text"], logic)
        rag_data["similarity_response"] = round(similarity_response,3)

        # 画面表示用のログ形式
        chunk_item_list = re.findall(r"\{(.*?)\}", rag_data["log_format"])
        chunk_items = {}
        for item in chunk_item_list:
            chunk_items[item] = rag_data[item]
        rag_data["log"] = rag_data["log_format"].format(**chunk_items)
        
        # 記録用のデータセット(一部のキーを除く)
        keys_to_remove = ["vector_data_key_text", "vector_data_value_text", "log_format"]
        for key in keys_to_remove:
            rag_data.pop(key, None)
        rag_ref.append(rag_data)
    return rag_ref


# レスポンスと会話メモリの類似度評価
def get_memory_similarity_response(response_vec, memory_selected, logic="Cosine"):
    memory_ref = []
        
    for memory_data in memory_selected:
        seq = memory_data["seq"]
        sub_seq = memory_data["sub_seq"]
        type = memory_data["type"]
        timestamp = memory_data["timestamp"]
        text = memory_data["text"] 
        similarity_prompt = round(memory_data["similarity_prompt"],3)
        similarity_response = round(dmu.calculate_similarity_vec(response_vec, memory_data["vec_text"], logic),3)
        
        # 画面表示用のログ形式
        memory_ref_log = f"{timestamp}の会話履歴：{seq}_{sub_seq}_{type}[質問との類似度：{round(similarity_prompt,3)}、回答との類似度：{round(similarity_response,3)}]{text[:50]}<br>"
        
        # 記録用のデータセット
        memory_ref.append(
            {
                "seq": seq,
                "sub_seq": sub_seq,
                "type": type,
                "timestamp": timestamp,
                "text": text,
                "similarity_prompt": similarity_prompt, 
                "similarity_response": similarity_response, 
                "log": memory_ref_log
            }
        )
    return memory_ref


# RAGのチャンクデータをCSV(utf-8)から生成
def get_chunk_csv(bucket, file_path, file_names, field_items=["title", "create_date", "key_text", "value_text"]):   
    rag_data = []
    for file_name in file_names:
        with open(file_path + file_name, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile, fieldnames=field_items)
            next(reader, None)
            for i, row in enumerate(reader):
                #【テスト追加】From
                if 'create_date' in row and row['create_date']:
                    try:
                        # Attempt to parse the date
                        parsed_date = datetime.strptime(row['create_date'], '%Y-%m-%d')
                        row['create_date'] = parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                        # If parsing fails, set it to a default or handle the error
                        try:
                            # Try alternative formats if needed
                            parsed_date = datetime.strptime(row['create_date'], '%Y/%m/%d')
                            row['create_date'] = parsed_date.strftime('%Y-%m-%d')
                        except ValueError:
                            row['create_date'] = '1970-01-01'  # Default date or handle as needed
                #【テスト追加】To
                rag_data.append({**{'id': file_name + str(i + 1)}, **{'bucket': bucket}, **dict(row)})
    return rag_data

# RAGのチャンクデータをNotionデータベースから生成
def get_chunk_notion(bucket, db_name, item_dict, chk_dict=None, date_dict=None):
    rag_data = []
    
    # Notion_DBのIDを取得
    notion_db_mst_file_path = mst_folder_path + notion_db_mst_file
    notion_db_mst = dmu.read_json_file(notion_db_mst_file_path)
    db_id = notion_db_mst[db_name]

    # RAG対象のページを取得
    pages = dmn.get_pages_done(db_id, chk_dict, date_dict)

    # RAGデータの形式に変換
    page_ids = [page['id'] for page in pages]
    for page_id in page_ids:
        if item_dict is not None:
            page_items = {}
            page_items.update({'id': page_id})
            page_items.update({'bucket': bucket})
            for key, value in item_dict.items():
                if isinstance(value, dict):
                    for k, v in value.items():
                        page_items[key] = dmn.get_notion_item_by_id(pages, page_id, k, v)
                elif isinstance(value, list):
                    page_item_text = ""
                    for item in value:
                        i = 0
                        for k, v in item.items():
                            if i == 0:
                                page_item_text += dmn.get_notion_item_by_id(pages, page_id, k, v)
                            else:
                                page_item_text += "\n"+ dmn.get_notion_item_by_id(pages, page_id, k, v)
                    page_items[key] = page_item_text
                else:
                    page_items[key] = value
            rag_data.append(page_items)
    return rag_data


# RAGチャンクデータの編集
def get_rag_chunk(rag_data, rag_data_file):
    rag_data_file_updated = {}
    cnt_add = 0 
    cnt_extent = 0

    # RAGデータをcreate_dateで降順に並び替え
    if "create_date" in rag_data[0]:
        rag_data = sorted(rag_data, key=lambda x: x["create_date"], reverse=True)

    for rag_chunk in rag_data:
        # 対象ドキュメントのベクトルデータを作成
        if rag_chunk['id'] not in rag_data_file:
            if rag_chunk['value_text']:
                vec_key_text = dmu.embed_text(rag_chunk['key_text'].replace("\n", ""))
                vec_value_text = dmu.embed_text(rag_chunk['value_text'].replace("\n", ""))
                rag_data_file_updated[rag_chunk['id']] = rag_chunk
                rag_data_file_updated[rag_chunk['id']]['vector_data_key_text'] = vec_key_text
                rag_data_file_updated[rag_chunk['id']]['vector_data_value_text'] = vec_value_text
                print(f"{rag_chunk['title']}を知識情報ファイル(JSON)に追加しました。")
                cnt_add+=1
        else:
            rag_data_file_updated[rag_chunk['id']] = rag_data_file[rag_chunk['id']]
            print(f"{rag_chunk['title']}は知識情報ファイル(JSON)に存在しています。")
            cnt_extent+=1

    return rag_data_file_updated, cnt_add, cnt_extent


# RAGデータ生成（JSON：ベクトルサーチ）
def generate_rag_vec_json():
    # RAGマスターの読込
    rag_mst_dict = dmu.read_json_file(rag_mst_file, mst_folder_path)

    # 各RAGデータを生成（JSON）
    rag_data_file = {}
    rag_data_file_updated = {}
    cnt_add = 0 
    cnt_extent = 0
    log = ""
    
    # チャンクデータの取得
    rag_data = []
    for rag_id, rag_setting in rag_mst_dict.items():
        if rag_setting["active"] == "Y":
            if rag_setting["mode"] == "notion":
                rag_data = get_chunk_notion(rag_setting["bucket"], rag_setting["db"], rag_setting["item_dict"], rag_setting["chk_dict"], rag_setting["date_dict"])
            elif rag_setting["mode"] == "csv":
                rag_data = get_chunk_csv(rag_setting["bucket"], rag_setting["file_path"], rag_setting["file_names"], rag_setting["field_items"])
            else:
                print("正しいモードが設定されていません。")
        
            # RAGデータのファイル読込
            rag_data_file_name = rag_folder_path + rag_id +'_vec.json'
            rag_data_file = dmu.read_json_file(rag_data_file_name)
            
            # チャンクデータの編集
            rag_data_file_updated, cnt_add, cnt_extent = get_rag_chunk(rag_data, rag_data_file)
            
            # RAG用ベクトルデータの保存
            cnt_total = cnt_add + cnt_extent
            if os.path.exists(rag_data_file_name):
                os.remove(rag_data_file_name)
            with open(rag_data_file_name, 'w') as file:
                json.dump(rag_data_file_updated, file, indent=4)
                log = log + f"{rag_id}の書き込みが完了しました。追加件数:{cnt_add}, トータル件数:{cnt_total}<br>"
    
    return log
