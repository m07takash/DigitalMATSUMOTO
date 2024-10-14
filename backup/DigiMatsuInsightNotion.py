import os
import json
import math
import csv
import datetime
from datetime import datetime, timedelta
import boto3
import openai
from openai import OpenAI

import DigiMatsuEngine as digim_eng
import DigiMatsuInOutNotion as digim_notion

# S3に画像をアップロードしてURLを取得（Engineに移行）
#def upload_to_s3(file_path, bucket_name, s3_key, IAM_ACCESS_KEY, IAM_SECRET_KEY):
#    s3 = boto3.client('s3',
#                      aws_access_key_id=IAM_ACCESS_KEY,
#                      aws_secret_access_key=IAM_SECRET_KEY,
#                      region_name='us-east-1'
#                     )
#    s3.upload_file(file_path, bucket_name, s3_key, ExtraArgs={'ACL': 'public-read'})
#    file_url = f"https://{bucket_name}.s3.amazonaws.com/{s3_key}"
#    return file_url

# デジタルツインの知識情報(テキスト)をNotionデータベースから取得
def get_dtwin_docs_notion(client, headers, database_id, knowledge_name, knowledge_dict):
    dtwin_docs = digim_notion.get_docs_dtwin(client, headers, database_id, knowledge_dict["item_dict"], knowledge_dict["chk_dict"], knowledge_dict["date_dict"])
    return dtwin_docs

# デジタルツインのインデックス用テキストをCSVファイル(utf-8)から取得
def get_dtwin_docs_txt(filename):
    with open(filename, 'r', encoding='utf-8') as txtfile:
        dtwin_docs = txtfile.read()
    return dtwin_docs

# デジタルツインのインデックス用テキストをCSVファイル(utf-8)から取得
def get_dtwin_docs_csv(knowledge_dict):
    filepath = knowledge_dict["file_path"]
    filenames = knowledge_dict["file_names"]
    fieldnames = ["title", "category", "eval", "generate_date", "search_text", "text", "url"]    
    page_docs = []
    for filename in filenames:
        with open(filepath+filename, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile, fieldnames=fieldnames)
            next(reader, None)
            for i, row in enumerate(reader):
                page_docs.append({**{'id': filename+""+str(i+1)}, **dict(row)})
    for page_doc in page_docs:
#        page_doc.update({"parent": knowledge_dict["parent"]})
        page_doc.update({"note": {}})
    return page_docs

# RAG用ベクトルデータの作成
def DigiMatsu_geneRAGJSON(openai_api_key, user_id, rag_path, knowledge_name, knowledge_dict, chunk_setting, notion_setting, mode="notion"):
    # OpenAIのAPIキーの設定
    os.environ["OPENAI_API_KEY"] = openai_api_key
    openai.api_key = openai_api_key
    openai_client = OpenAI()

    ###【決まり事】dtwin_docsに入れる元データは[key, title, date, text(2000文字以内)]にすること ###
    dtwin_docs = []
    vec_json_file = ""
    if knowledge_dict["active"] == "Y":
        if mode == "notion":
            # notion接続情報取得
            NOTION_VERSION= notion_setting['NOTION_VERSION']
            NOTION_TOKEN = notion_setting['NOTION_TOKEN']
            NOTION_DB_ID = notion_setting[knowledge_dict["db"]]#'DigiMATSU_Opinion']
            notion_client, notion_headers = digim_notion.connect_notion(NOTION_TOKEN, NOTION_VERSION)
            # Notionデータベースからドキュメントを取得
            dtwin_docs = get_dtwin_docs_notion(notion_client, notion_headers, NOTION_DB_ID, knowledge_name, knowledge_dict)
        elif mode == "csv":
            dtwin_docs = get_dtwin_docs_csv(knowledge_dict)
        else:
            print("正しいモードが設定されていません。")

        # DigitalMATSUMOTOデータのJSONファイルへの書出し
        vec_json_file = knowledge_name +'_vec.json'
        digim_eng.generate_vec_RAGdocs_json(openai_client, dtwin_docs, chunk_setting, vec_json_file, rag_path)
    return vec_json_file
