import os
import csv
import json
import ast
import chromadb
from chromadb.errors import NotFoundError
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
rag_folder_json_path = os.getenv("RAG_FOLDER_JSON")
rag_folder_db_path = os.getenv("RAG_FOLDER_DB")
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
    if os.path.basename(content).startswith("[IN]") or os.path.basename(content).startswith("[OUT]"):
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
    rag_list = []
    
    #ChromaDBから取得
    db_client = chromadb.PersistentClient(path=rag_folder_db_path)
    collections = db_client.list_collections()
    rag_list += [col.name for col in collections]

    #JSONから取得
    identifier="_vec.json"
    rag_list += [r.replace(identifier, "") for r in dmu.get_files(rag_folder_json_path, identifier)]

    return rag_list

# RAGデータの取得
def select_rag_vector(rag_data_list, rag={}):
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
def create_rag_context(query, query_vecs=[], rags=[], meta_searches=[]):
    rag_final_context = "\n------\n"
    rag_final_selected = []

    # RAGデータセットごとに処理    
    for rag in rags:
        rag_data_list = []
        for rag_data in rag["DATA"]:
            query_seq = 0
            if rag_data["DATA_TYPE"] == "JSON":
                for query_vec in query_vecs:
                    rag_data_file = rag_data["DATA_NAME"] +'_vec.json'
                    rag_data_json = dmu.read_json_file(rag_data_file, rag_folder_json_path)
                    for k, v in rag_data_json.items():
                        similarity_prompt = dmu.calculate_similarity_vec(query_vec, v["vector_data_key_text"], rag["DISTANCE_LOGIC"])
                        v["similarity_prompt"] = round(similarity_prompt,3)
                        v["query_seq"] = query_seq
                        rag_data_list.append(v)
                    query_seq+=1

            elif rag_data["DATA_TYPE"] == "DB":
                for query_vec in query_vecs:
                    db_client = chromadb.PersistentClient(path=rag_folder_db_path)
                    try:
                        collection = db_client.get_collection(rag_data["DATA_NAME"])
    
                        result_limit = 50
                        if collection.count() <= 50:
                            result_limit = collection.count()
    
                        #メタデータ検索の追加
                        if "META_SEARCH" in rag_data: #エージェントのRAG設定にメタ検索が含まれる場合
                            query_conditions = []
                            for meta_search in meta_searches:
                                if "DATE" in meta_search and "DATE" in rag_data["META_SEARCH"]["CONDITION"]:
                                    for date_range in meta_search["DATE"]:
                                        try:
                                            start_date = datetime.strptime(date_range["start"], '%Y/%m/%d').timestamp()
                                            end_date = datetime.strptime(date_range["end"], '%Y/%m/%d').timestamp()
                                            query_conditions.append({
                                                "$and": [
                                                    {"create_date_ts": {"$gte": start_date}},
                                                    {"create_date_ts": {"$lte": end_date}}
                                                ]
                                            })
                                        except ValueError:
                                            continue                                                   
                            if query_conditions:
                                if len(query_conditions) == 1:
                                    where_clause = query_conditions[0]
                                else:
                                    where_clause = {"$or": query_conditions}
                                rag_data_db = collection.query(query_embeddings=[query_vec], n_results=result_limit, include=["metadatas", "embeddings", "distances"], where=where_clause)
                                for i in range(len(rag_data_db["ids"])):
                                    for j in range(len(rag_data_db["ids"][i])):
                                        v = {}
                                        v["id"] = rag_data_db["ids"][i][j]
                                        v |= rag_data_db["metadatas"][i][j]
                                        v["vector_data_value_text"] = ast.literal_eval(v["vector_data_value_text"])
                                        v["vector_data_key_text"] = rag_data_db["embeddings"][i][j].tolist()
                                        v["similarity_prompt"] = round(rag_data_db["distances"][i][j],3)*rag_data["META_SEARCH"]["BONUS"]
                                        v["similarity_prompt_original"] = round(rag_data_db["distances"][i][j],3)
                                        v["query_seq"] = query_seq
                                        v["query_mode"] = "(META_SEARCH:"+str(rag_data["META_SEARCH"]["BONUS"])+")"
                                        rag_data_list.append(v)
                        
                        rag_data_db = collection.query(query_embeddings=[query_vec], n_results=result_limit, include=["metadatas", "embeddings", "distances"])
                        for i in range(len(rag_data_db["ids"])):
                            for j in range(len(rag_data_db["ids"][i])):
                                v = {}
                                v["id"] = rag_data_db["ids"][i][j]
                                v |= rag_data_db["metadatas"][i][j]
                                v["vector_data_value_text"] = ast.literal_eval(v["vector_data_value_text"])
                                v["vector_data_key_text"] = rag_data_db["embeddings"][i][j].tolist()
                                v["similarity_prompt"] = round(rag_data_db["distances"][i][j],3)
                                v["similarity_prompt_original"] = round(rag_data_db["distances"][i][j],3)
                                v["query_seq"] = query_seq
                                v["query_mode"] = "NORMAL"
                                rag_data_list.append(v)
                        query_seq+=1

                    except NotFoundError:
                        print(f"{rag_data['DATA_NAME']} は存在しないためスキップしました。")

        # rag_data_listでidが重複するものは「質問との類似度」が近いものに重複削除
        filtered_data = {}
        for rag_data in rag_data_list:
            rag_data_id = rag_data["id"]
            if rag_data_id not in filtered_data:
                filtered_data[rag_data_id] = rag_data
            elif rag_data["similarity_prompt"] < filtered_data[rag_data_id]["similarity_prompt"]:
                filtered_data[rag_data_id] = rag_data
#            else:
#                print("RAGデータ被り["+rag_data_id+"]:"+rag_data["db"]+" "+rag_data["title"]+" "+str(rag_data["similarity_prompt"]))
        rag_data_list = list(filtered_data.values())
        
        # RAGデータの選択       
        if rag["RETRIEVER"] == "Vector":
#            rag_context, rag_selected = select_rag_vector(query_vec, rag_data_list, rag)    
            rag_context, rag_selected = select_rag_vector(rag_data_list, rag)    
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
        
        # 記録用のデータセット
#        keys_to_remove = ["vector_data_key_text", "vector_data_value_text", "log_format"] #一部のキーを除く
#        for key in keys_to_remove:
#            rag_data.pop(key, None)
        rag_ref.append(rag_data["log"])
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
#                "seq": seq,
#                "sub_seq": sub_seq,
#                "type": type,
#                "timestamp": timestamp,
#                "text": text,
#                "similarity_prompt": similarity_prompt, 
#                "similarity_response": similarity_response, 
                "log": memory_ref_log
            }
        )
    return memory_ref


# RAGのチャンクデータをCSV(utf-8)から生成
def get_chunk_csv(bucket, file_path, file_name, field_items, title_items, key_text_items, value_text_items):  
    rag_data = []
    with open(file_path + file_name, 'r', encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile, fieldnames=field_items)
        next(reader, None)

        for i, row in enumerate(reader):
            rag_chunk = {}
            rag_chunk["id"] = bucket+"-"+str(i+1)
            rag_chunk["bucket"] = bucket

            title = ""
            for title_item in title_items:
                title += row[title_item]
            rag_chunk["title"] = title

            value_text = ""
            for value_text_item in value_text_items:
                value_text += row[value_text_item]
            rag_chunk["value_text"] = value_text
            
            key_text = ""
            for key_text_item in key_text_items:
                key_text += row[key_text_item]
            rag_chunk["key_text"] = key_text

            value_text = ""
            for value_text_item in value_text_items:
                value_text += row[value_text_item]
            rag_chunk["value_text"] = value_text
            
            for field_item in field_items:
                rag_chunk[field_item] = row[field_item]

            create_date = datetime.now().strftime("%Y-%m-%d")
            if "create_date" in row:
                try:
                    parsed_date = datetime.strptime(row["create_date"], '%Y/%m/%d')
                    create_date = parsed_date.strftime('%Y-%m-%d')
                except ValueError:
                    create_date = datetime.now().strftime("%Y-%m-%d")
            rag_chunk["create_date"] = create_date
            
            rag_data.append(rag_chunk)
    return rag_data

# RAGのチャンクデータをNotionデータベースから生成
def get_chunk_notion(bucket, db_name, item_dict, chk_dict=None, date_dict=None, category_dict=None):
    rag_data = []
    
    # Notion_DBのIDを取得
    notion_db_mst_file_path = mst_folder_path + notion_db_mst_file
    notion_db_mst = dmu.read_json_file(notion_db_mst_file_path)
    db_id = notion_db_mst[db_name]

    # RAG対象のページを取得
    pages = dmn.get_pages_done(db_id, chk_dict, date_dict, category_dict)

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
                        if i != 0:
                            page_item_text += "\n"
                        if isinstance(item, dict):
                            for k, v in item.items():
                                page_item_text += dmn.get_notion_item_by_id(pages, page_id, k, v)
#                                if i == 0:
#                                    page_item_text += dmn.get_notion_item_by_id(pages, page_id, k, v)
#                                else:
#                                    page_item_text += "\n"+ dmn.get_notion_item_by_id(pages, page_id, k, v)
                        else:
                            page_item_text += item
                    page_items[key] = page_item_text
                else:
                    page_items[key] = value

            if "create_date" not in page_items:
                page_items["create_date"] = datetime.now().strftime("%Y-%m-%d")

            rag_data.append(page_items)
    return rag_data


# RAGチャンクデータの編集(JSON)
def save_rag_chunk_json(rag_data, rag_data_file):
    rag_data_file_updated = {}
    cnt_add = 0 
    cnt_extent = 0

    # RAGデータをcreate_dateで降順に並び替え
    if "create_date" in rag_data[0]:
        rag_data = sorted(rag_data, key=lambda x: x["create_date"], reverse=True)

    # 対象ドキュメントのベクトルデータを作成
    for rag_chunk in rag_data:
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


# RAGチャンクデータの編集(ChromaDB)
def save_rag_chunk_db(rag_id, rag_data):
    db_client = chromadb.PersistentClient(path=rag_folder_db_path)
    collection = db_client.get_or_create_collection(name=rag_id, metadata={"hnsw:space": "cosine"})
    existing_ids = []
    response = collection.get(include=["metadatas"])
    if response and "ids" in response:
        existing_ids = response["ids"]
    cnt_add = 0 
    cnt_extent = 0
    
    # RAGデータをcreate_dateで降順に並び替え
    if "create_date" in rag_data[0]:
        rag_data = sorted(rag_data, key=lambda x: x["create_date"], reverse=True)

    # 対象ドキュメントのベクトルデータを作成
    for rag_chunk in rag_data:
        rag_chunk["create_date_ts"] = datetime.strptime(rag_chunk["create_date"], "%Y-%m-%d").timestamp()
        if rag_chunk["value_text"]:
            chunk_id = rag_chunk["id"]
            if chunk_id not in existing_ids:
                vec_key_text = dmu.embed_text(rag_chunk["key_text"].replace("\n", ""))
                vec_value_text = dmu.embed_text(rag_chunk["value_text"].replace("\n", ""))
                for key in ["id"]:
                    if key in rag_chunk:
                        del rag_chunk[key]
                rag_chunk["vector_data_value_text"] = str(vec_value_text)
                # DBコレクションに追加（重複していれば更新）
                collection.add(
                    ids=[chunk_id],
                    embeddings=[vec_key_text],
                    metadatas=rag_chunk
                )
                print(f"{rag_chunk['title']}を知識情報DBに追加しました。")
                cnt_add+=1
            else:
                print(f"{rag_chunk['title']}は知識情報DBに存在しています。")
                cnt_extent+=1

    return cnt_add, cnt_extent


# RAGデータ生成
def generate_rag():
    # RAGマスターの読込
    rag_mst_dict = dmu.read_json_file(rag_mst_file, mst_folder_path)

    # 各RAGデータを生成
    rag_data_file = {}
    rag_data_file_updated = {}
    cnt_add = 0 
    cnt_extent = 0
    
    # チャンクデータの取得
    rag_data = []
    for rag_id, rag_setting in rag_mst_dict.items():
        if rag_setting["active"] == "Y":
            if rag_setting["input"] == "notion":
                rag_data = get_chunk_notion(rag_setting["bucket"], rag_setting["data_name"], rag_setting["item_dict"], rag_setting["chk_dict"], rag_setting["date_dict"], rag_setting["category_dict"])
            elif rag_setting["input"] == "csv":
                rag_data = get_chunk_csv(rag_setting["bucket"], rag_setting["file_path"], rag_setting["file_name"], rag_setting["field_items"], rag_setting["title"], rag_setting["key_text"], rag_setting["value_text"])
            else:
                print("正しいモードが設定されていません。")

            if rag_data:
                # JSONでの保存
                if rag_setting["data_type"] == "json":
                    rag_data_file_name = rag_folder_json_path + rag_id +'_vec.json'
                    rag_data_file = dmu.read_json_file(rag_data_file_name)
        
                    # チャンクデータの編集
                    rag_data_file_updated, cnt_add, cnt_extent = save_rag_chunk_json(rag_data, rag_data_file)
                    
                    # RAG用ベクトルデータの保存
                    cnt_total = cnt_add + cnt_extent
                    if os.path.exists(rag_data_file_name):
                        os.remove(rag_data_file_name)
                    with open(rag_data_file_name, 'w') as file:
                        json.dump(rag_data_file_updated, file, indent=4)
                        print(f"{rag_id}のJSON書き込みが完了しました。追加件数:{cnt_add}, トータル件数:{cnt_total}")
    
                # ChromaDBでの保存
                elif rag_setting["data_type"] == "chromadb":
                    cnt_add, cnt_extent = save_rag_chunk_db(rag_id, rag_data)
                    cnt_total = cnt_add + cnt_extent
                    print(f"{rag_id}のDB書き込みが完了しました。追加件数:{cnt_add}, トータル件数:{cnt_total}")

# RAGデータベース（Collection）の削除
def del_rag_db():
    db_client = chromadb.PersistentClient(path=rag_folder_db_path)
    collections = db_client.list_collections()
    for collection in collections:
        collection_name = collection.name
        db_client.delete_collection(name=collection_name)
        print(collection_name + "を削除しました。")
