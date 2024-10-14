import os
import numpy as np
import json
import shutil
import math
from dateutil import parser
import datetime
from datetime import datetime, timedelta
import base64
import boto3
from janome.tokenizer import Tokenizer
from collections import Counter, defaultdict

import openai
from openai import OpenAI
import google.generativeai as genai

# 日付型の変換
def convert_to_ymd(date_str, date_format='%Y-%m-%d'):
    try:
        if '/' in date_str:
            # スラッシュを含む日付を解析
            parsed_date = datetime.strptime(date_str, '%Y/%m/%d')
        else:
            # スラッシュを含まない日付を自動解析
            parsed_date = parser.parse(date_str)
        # 指定のフォーマットに変換
        formatted_date = parsed_date.strftime(date_format)
        return formatted_date
    except ValueError:
        return "Invalid date format"

# 文字型の配列を好きな長さで部分配列にする関数
def split_into_subarrays(strings, max_length=30000):
    subarrays = []
    current_array = []
    current_length = 0
    for string in strings:
        if current_length + len(string) <= max_length:
            current_array.append(string)
            current_length += len(string)
        else:
            subarrays.append(''.join(current_array))
            current_array = [string]
            current_length = len(string)
    if current_array:
        subarrays.append(''.join(current_array))
    return subarrays

# VISIONモデル用にイメージファイルをエンコード
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

# S3に画像をアップロードしてURLを取得
def upload_to_s3(file_path, file_name, IAM_ACCESS_KEY, IAM_SECRET_KEY, AWS_REGION, S3_BUCKET_NAME):
    s3 = boto3.client('s3',
                      aws_access_key_id=IAM_ACCESS_KEY,
                      aws_secret_access_key=IAM_SECRET_KEY,
                      region_name=AWS_REGION,
                     )
    s3.upload_file(file_path+file_name, S3_BUCKET_NAME, file_name, ExtraArgs={'ACL': 'public-read'})
    file_url = f"https://{S3_BUCKET_NAME}.s3.amazonaws.com/{file_name}"
    return file_url

# 文字列から関数名を取得
def call_function_by_name(func_name, *args, **kwargs):
    if func_name in globals():
        func = globals()[func_name]
        return func(*args, **kwargs)  # 引数を関数に渡す
    else:
        return "Function not found"

# JSONファイルの読み込み
def read_docs_json(json_file, file_path='data/json/'):
    json_file = file_path + json_file
    if os.path.exists(json_file):
        with open(json_file, 'r') as file:
            vec_docs_json = json.load(file)
    else:
        vec_docs_json = {}
    return vec_docs_json

# 文字列からテキストファイルの内容かテキスト自体を取得
def get_str_or_txt(file_path, input_string):
    output_string = ""
    if input_string.strip().endswith(".txt"):
        try:
            with open(file_path+input_string, "r", encoding="utf-8") as file:
                output_string = file.read()
        except FileNotFoundError:
            output_string = ""
            print("キャラクターファイルが存在しません")
    else:
        output_string = input_string
    return output_string

# 単語の除去
def remove_word(s):
    words_to_remove = [" ", "　", ",", "、",".","。"]
    for word in words_to_remove:
        s = s.replace(word, "")
    return s

# テキストを埋め込みベクトルに変換する関数
def embed_text(openai_client, text, embedding_model="text-embedding-3-large"): 
#def embed_text(openai_client, text, embedding_model="text-embedding-ada-002"): 
    response = openai_client.embeddings.create(model=embedding_model, input=text)
    return response.data[0].embedding

# Janomeによるトークナイズ
def tokenize(text, tokenizer, grammer, stop_words):
    tokens = [token.base_form for token in tokenizer.tokenize(text)
              if token.base_form not in set(stop_words) and token.part_of_speech.split(',')[0] in grammer]
    doc_freq = Counter(tokens)
    doc_len = len(tokens)
    return tokens, doc_freq, doc_len

# BM25の初期化とIDFの計算
def initialize_bm25(documents, epsilon = 1e-9):
    corpus_size = len([document['text'] for document in documents])
    doc_freqs = []
    doc_len = []
    df = Counter()
    for document in documents:
        tokens = document['tokens']
        doc_freqs.append(document['doc_freq'])
        df.update(set(tokens))
        doc_len.append(document['doc_len'])
    if corpus_size >= 1:
        avgdl = sum(doc_len) / corpus_size
        idf = {word: math.log((corpus_size - freq + 0.5) / (freq + 0.5) + 1) for word, freq in df.items()}
    else:
        avgdl = 0
        idf = None
    return doc_freqs, doc_len, avgdl, idf

# BM25スコアの計算
def get_bm25_score(query, grammer, stop_words, index, doc_freqs, doc_len, avgdl, idf, k1=1.5, b=0.75):
    score = 0.0
    tokenizer = Tokenizer()
    query_tokens = tokenize(query, tokenizer, grammer, stop_words)
    for word in query_tokens:
        if word in doc_freqs[index]:
            df = doc_freqs[index][word]
            idf_score = idf.get(word, 0)
            score += idf_score * (df * (k1 + 1)) / (df + k1 * (1 - b + b * (doc_len[index] / avgdl)))
    return score

# クエリに対する文書のランキング
def query_bm25(query, documents, grammer, stop_words, doc_freqs, doc_len, avgdl, idf):
    scores = [get_bm25_score(query, grammer, stop_words, i, doc_freqs, doc_len, avgdl, idf) for i in range(len(documents))]
    return np.argsort(scores)[::-1]

# 正規化、対数化、符号反転を行う関数
def normalize_log_invert(value, min_value, max_value, epsilon = 1e-9):
    normalized = (value - min_value) / (max_value - min_value) * (1 - epsilon) + epsilon
    logged = math.log(normalized)  # 対数を取る
    inverted = -logged  # 符号を反転
    return inverted

# 知識データ(JSON)の作成
def generate_vec_RAGdocs_json(openai_client, docs, setting, vec_json_file, file_path=''):
    vec_json_file = file_path + vec_json_file
    cnt_add = 0 
    cnt_extent = 0
    vec_docs_json = {}
    vec_docs_json_old = {}
    
    # 作成済の知識データ(JSON)の読込
    if os.path.exists(vec_json_file):
        with open(vec_json_file, 'r') as file:
            vec_docs_json_old = json.load(file)
    
    # トークナイザー用のパラメータ
    grammer = setting["GRAMMER"]
    stop_words = setting["STOP_WORDS"]
    tokenizer = Tokenizer()

    for doc_dict in docs:
        # 対象ドキュメントのベクトルデータを作成
        if doc_dict['id'] not in vec_docs_json_old:
            if doc_dict['text']:
                vec_doc_search = embed_text(openai_client, doc_dict['search_text'].replace("\n", ""))
                vec_doc_text = embed_text(openai_client, doc_dict['text'].replace("\n", ""))
                vec_docs_json[doc_dict['id']] = doc_dict
                vec_docs_json[doc_dict['id']]['vector_data_search'] = vec_doc_search
                vec_docs_json[doc_dict['id']]['vector_data_text'] = vec_doc_text
                print(f"{doc_dict['title']}を知識情報ファイル(JSON)に追加しました。")
                cnt_add+=1
        else:
            vec_docs_json[doc_dict['id']] = vec_docs_json_old[doc_dict['id']]
            print(f"{doc_dict['title']}は知識情報ファイル(JSON)に存在しています。")
            cnt_extent+=1

    # RAG用ベクトルデータの保存
    cnt_total = cnt_add + cnt_extent
    if os.path.exists(vec_json_file):
        os.remove(vec_json_file)
    with open(vec_json_file, 'w') as file:
        json.dump(vec_docs_json, file, indent=4)
        print(f"知識情報の書き込みが完了しました。知識の追加件数:{cnt_add}, 知識のトータル件数:{cnt_total}")
    with open(vec_json_file, 'r') as file:
        print(f"JSONファイルのデータ件数:{len(json.load(file))}")

# 対話のメモリデータ(JSON)の保存
def generate_memory_json(dialog, json_file, file_path='', seq=0, api_key="OPENAI_API_KEY"):    
    json_file = file_path + json_file
    if os.path.exists(json_file):
        with open(json_file, 'r') as file:
            memory_json = json.load(file)
    else:
        memory_json = {}

    seq = str(seq)
    if seq not in memory_json:
        memory_json[seq] = {}
        memory_json[seq]["FLG"] = "Y"
    
    key = dialog[1]+"_"+dialog[0]
    if not key in memory_json[seq]:
        vec_dialog = []
        if dialog[1] in ["user", "assistant", "digest"]:
            os.environ["OPENAI_API_KEY"] = api_key
            openai.api_key = api_key
            openai_client = OpenAI()
            vec_dialog = embed_text(openai_client, dialog[3].strip().replace("\n", ""))
        if dialog[1] in ["uploaded_file","generate_file"]:
            memory_json[seq][key] = {"timestamp": dialog[0], "user": dialog[1], "size": dialog[2], "text": dialog[3], "file_type": dialog[4], "file_name": dialog[5], "file_path": dialog[6], "file_url": dialog[7]}
        else:
            memory_json[seq][key] = {"timestamp": dialog[0], "user": dialog[1], "tokens": dialog[2], "text": dialog[3].strip(" "), "vector_data": vec_dialog}
        with open(json_file, 'w') as file:
            json.dump(memory_json, file, indent=4)

# 指定したメモリのシーケンスを論理削除(FLG="N"に設定)
def delete_memory_seq(json_file, file_path, seq, item="FLG", value="N"):
    json_file = file_path + json_file
    if os.path.exists(json_file):
        with open(json_file, 'r') as file:
            memory_json = json.load(file)
            memory_json[seq][item] = value
        with open(json_file, 'w') as file:
            json.dump(memory_json, file, ensure_ascii=False, indent=4)

# アップロードしたファイルの保存
def save_uploaded_files(file_path, file_name, uploaded_file):
    os.makedirs(file_path, exist_ok=True)
    with open(file_path+file_name, "wb") as f:
        f.write(uploaded_file.getbuffer())

# 現在の会話シーケンスの生成
def get_memory_seq(json_file, file_path):
    json_file = file_path + json_file
    if os.path.exists(json_file):
        with open(json_file, 'r') as file:
            memory_json = json.load(file)
            seq = max(int(key) for key in memory_json.keys()) + 1
    else:
        seq = 0
    return seq

# 類似度計算（コサイン距離）
def calculate_cosine_distance(vec1, vec2):
    # コサイン類似度を計算
    dot_product = sum(p*q for p, q in zip(vec1, vec2))
    magnitude_vec1 = math.sqrt(sum(p**2 for p in vec1))
    magnitude_vec2 = math.sqrt(sum(q**2 for q in vec2))
    if magnitude_vec1 == 0 or magnitude_vec2 == 0:
        # どちらかのベクトルの大きさが0の場合、類似度は定義できない
        return 0
    cosine_similarity = dot_product / (magnitude_vec1 * magnitude_vec2)
    # コサイン距離を計算(1-コサイン類似度)
    cosine_distance = 1-cosine_similarity
    return cosine_distance

# 類似度計算（ミンコフスキー距離）
def calculate_minkowski_distance(vec1, vec2, p):
    if p == 0:
        raise ValueError("p cannot be zero")
    elif p == float('inf'):
        return max(abs(a - b) for a, b in zip(vec1, vec2))
    else:
        return sum(abs(a - b) ** p for a, b in zip(vec1, vec2)) ** (1 / p)

# ペナルティ計算(線形)
def linear_penalty(difference, alpha=0.001):
    return alpha * difference

# ペナルティ計算(指数関数)
def exponential_penalty(difference, alpha=0.001):
    return 1 - math.exp(-alpha * difference)

# ペナルティ計算(ロジスティック回帰)
def logistic_penalty(difference, alpha=0.001):
    return 1 / (1 + math.exp(-alpha * difference))

# ペナルティ計算(ステップ)
def step_penalty(difference, alpha=0.001, beta=0.01, days=10):
    q = difference // days  # 日数をdays単位で割った商
    r = difference % days  # 日数をdays単位で割った余り
    return q*beta

# ペナルティ計算(ステップごとに係数αが増加) ※関数を別途選択(linear_penalty, exponential_penalty, logistic_penalty)
def step_gain(difference, alpha=0.001, days=10, func="linear_penalty"):
    quotient = difference // days  # 日数をdays単位で切る
    alpha = quotient*alpha
    return globals()[func](difference, alpha)

# 類似度計算（距離計算＋日付ペナルティ）
def calculate_similarity_vec(vec1, vec2, logic="Cosine"):
    if logic == "Cosine":
        distance = calculate_cosine_distance(vec1, vec2)
    elif logic == "Euclidean":
        distance = calculate_minkowski_distance(vec1, vec2, 2)
    elif logic == "Manhattan":
        distance = calculate_minkowski_distance(vec1, vec2, 1)
    elif logic == "Chebychev":
        distance = calculate_minkowski_distance(vec1, vec2, float('inf'))
    else: #通常はコサイン距離
        distance = calculate_cosine_distance(vec1, vec2)
    return distance

# メモリを取得
def select_memory(openai_client, input_text, data_dict, memory_mode=["Y","BOTH","LATEST",7500,"Cosine"]):
    results = []
    memory_data = []
    memory_digest_data = []
    memory_digest_latest = ()
    memory_use = memory_mode[0]   #メモリ参照の有無：N(Default), Yから選択
    memory_agent = memory_mode[1] #メモリ参照の対象者：BOTH(Default), USER, ASSISTANTから選択 
    memory_loader = memory_mode[2] #メモリの参照方法：LATEST(最新から：Default), EARLIEST(古いものから), SIMILAR_VEC(埋め込みベクトルの近い順)
    memory_text_limits = memory_mode[3] #メモリのテキスト上限
    memory_logic = memory_mode[4] #メモリの類似度：コサイン距離、ユークリッド距離、マンハッタン距離、チェビシェフ距離

    if memory_use == "Y":
        for k, v_dict in data_dict.items():
            if v_dict["FLG"] == "Y":
                for key, value in v_dict.items():
                    if key != "FLG":
                        if value["user"] not in ["uploaded_file", "generate_file"]:
                            similarity = calculate_similarity_vec(embed_text(openai_client, input_text.replace("\n", "")), value["vector_data"], memory_logic)
                        if memory_agent in ["user", "assistant"]:
                            if value["user"] == memory_agent: #BOTH以外（USERもしくはASSISTANT）の場合
                                memory_data.append((value["timestamp"], value["user"], value["tokens"], value["text"], similarity))
                                memory_digest_data.append(value["user"]+":"+value["text"])
                        else:
                            if value["user"] in ["user", "assistant"]: #BOTHの場合
                                memory_data.append((value["timestamp"], value["user"], value["tokens"], value["text"], similarity))
                                memory_digest_data.append(value["user"]+":"+value["text"])
                        if value["user"] in ["digest"]:
                            memory_digest_latest = (value["timestamp"], "assistant", similarity, value["text"])
        if memory_loader == "LATEST":
            memory_data.sort(key=lambda x: x[0], reverse=True)
        elif memory_loader == "EARLIEST":
            memory_data.sort(key=lambda x: x[0])
        elif memory_loader == "SIMILAR_VEC":
            memory_data.sort(key=lambda x: x[4])
        
        # 合計文字数(text_limits)になるまでnameとtextを取得（JSONファイル内ではuserトークンがコンテキスト分も含むため、テキストの文字数でカウント）
        total_characters = len(memory_digest_latest)
        buffer = 30 #プロンプトに含まれるテキストトークン数のバッファ
        for date, user, tokens, text, similarity in memory_data:
            if user in ["user", "assistant"]:
                if total_characters + len(text) + buffer > memory_text_limits:
                    break
                results.append((date, user, similarity, text))
            total_characters = total_characters + len(text) + buffer
    return results, memory_digest_data, memory_digest_latest

# RAGデータを取得
def select_rag(openai_client, input_text, data_dict, logic="Cosine", text_limits=10000, current_date=datetime.now()):
    results = []
    if data_dict:
        distances = []
        # 埋め込みベクトルの計算
        embed_vec_input = embed_text(openai_client, input_text.replace("\n", ""))
        
        for key, value in data_dict.items():
            if value["generate_date"] != "":
                date_format = "%Y-%m-%d"
                date = datetime.strptime(convert_to_ymd(value["generate_date"], date_format), date_format)
            else:
                date = current_date
            # 埋め込みベクトルの類似度
            similarity_vec = calculate_similarity_vec(embed_vec_input, value["vector_data_search"], logic)
            distances.append((key, similarity_vec, date, value["id"], value["title"], value["category"], value["text"], value["url"], value["note"], value["vector_data_text"]))
                           
        # 合計文字数(text_limits)になるまでnameとtextを取得
        total_characters = 0
        buffer = 100 #プロンプトに含まれるテキスト分のバッファ
        distances = sorted(distances, key=lambda x: x[1])
        for key, score, date, value_id, title, category, text, url, note, vec_text in distances:
            chunk_len = len(title)+len(text)
            if total_characters + chunk_len + buffer > text_limits:
                break
            date_format = "%Y-%m-%d"
            results.append((key, score, datetime.strptime(convert_to_ymd(value["generate_date"], date_format), date_format), value_id, title, category, text, url, note, vec_text))
            total_characters = total_characters + chunk_len + buffer
    return results


# RAGを含めたプロンプトテンプレートの作成
def create_rag_context(openai_client, input_text, current_date, rags, rag_file_path = ''):
    rag_context_str = "<br>---------------------<br>" #クエリに使うコンテキスト
    rag_docs_json = {}
    retrival_text = ""
    retrival_docs = [] #ログ保存用

    # RAGデータの取得
    for rag in rags:
        for rag_data in rag["datasets"]:
            rag_file = rag_data +'_vec.json'
            rag_docs_json.update({f"{rag_data}_{key}": value for key, value in read_docs_json(rag_file, rag_file_path).items()})
        rag_results = select_rag(openai_client, input_text, rag_docs_json, rag["logic"], rag["text_limits"], current_date)
        if rag["format_data"]=="":
            retrival_text += f'<br>{rag["format_data"]["Header"]}'
        for key, similarity_score, date, id, title, category, text, url, note, vec_text in rag_results:
            days_difference = (current_date - date).days
            retrival_docs.append((key, similarity_score, date.strftime('%Y-%m-%d'), days_difference, title, category, text, url, vec_text)) #Ref出力用
            retrival_text += rag["format_data"]["Data"].format(days_difference=days_difference, similarity=round(similarity_score,3), title=title, text=text)

    if retrival_text != "":
        rag_context_str += f"""
        {retrival_text}
        <br>---------------------<br>
        これらの情報を踏まえて、次の質問に日本語で回答してください。
        <br>---------------------<br>
        """
    return rag_context_str, retrival_docs

# GPTの実行
def generate_response_T_gpt(api_key, persona, model, parameter, prompt, image_urls, memory_docs):
    os.environ["OPENAI_API_KEY"] = api_key
    openai.api_key = api_key
    openai_client = OpenAI()

    #システム
    system_message=[
        {"role": "system", "content": persona}
    ]

    #メモリの設定
    memories = []
    for memory_doc in memory_docs:
        if len(memory_doc)==4:
            timestamp, user, similarity, text = memory_doc
            #text = text.replace("\n", "").strip()
            memories.append({"role": user, "content": text})

    user_prompt_image = []
    for image_url in image_urls:
        user_prompt_image.append({"type": "image_url", "image_url": {"url": image_url}})
        #user_prompt_image.append({"type": "image_url", "image_url": {"url": query_image}})
    
    #user_prompt = prompt
    user_prompt = [{"type": "text", "text": prompt}] + user_prompt_image
    
    #モデルの実行
    completion = openai_client.chat.completions.create(
        model=model,
        temperature=parameter["temperature"],
        messages=system_message+memories+[{"role": "user", "content": user_prompt}]
    )

    response = completion.choices[0].message.content
    prompt_tokens = completion.usage.prompt_tokens
    response_tokens = completion.usage.completion_tokens
    return response, completion, prompt_tokens, response_tokens

# Geminiの実行
def generate_response_T_gemini(api_key, persona, model, parameter, prompt, image_urls, memory_docs):   
    genai.configure(api_key=api_key)
    
    #モデルの実行
    gemini = genai.GenerativeModel(model)
    completion = gemini.generate_content(
        prompt,
        generation_config={"temperature": parameter["temperature"]}
    )
    response = completion.text
    prompt_tokens = gemini.count_tokens(prompt).total_tokens
    response_tokens = gemini.count_tokens(response).total_tokens
    return response, completion, prompt_tokens, response_tokens


# APIを使用して回答を生成する関数
def generate_response(api_key, agent, query, text_contents, query_images, context_str, prompt_template, model, memory, seq=0):
    persona = f'あなたの名前は「{agent["name"]}」です。{agent["role"]}として振る舞ってください。<br><br>【あなたのキャラクター設定】<br>{agent["character"]}<br><br>'
    prompt = f'{context_str}<br>-------<br><br>{prompt_template}{query}{text_contents}'
    if query_images:
        prompt += "<br>※添付された画像の対象を知らない場合は大体の印象を教えてくれれば良いので、自信が無くても謝らずに回答してください。"   
    timestamp_in = datetime.now()

    response, completion, prompt_tokens, response_tokens = call_function_by_name(model["FUNC_NAME"], api_key, persona, model["MODEL_NAME"], model["PARAMETER"], prompt, query_images, memory["memory_docs"])
    
    timestamp_out = datetime.now()
    generate_time = timestamp_out - timestamp_in
    timestamp = [str(timestamp_in), str(timestamp_out), str(generate_time)]

    # メモリへの保存
    if memory["memory_save"] == "Y":
        generate_memory_json([str(timestamp_in), "user", prompt_tokens, query], memory["memory_file"], memory["memory_file_path"], seq, api_key)
        generate_memory_json([str(timestamp_in), "text_contents", prompt_tokens, text_contents], memory["memory_file"], memory["memory_file_path"], seq, api_key)
        generate_memory_json([str(timestamp_in), "context", prompt_tokens, context_str], memory["memory_file"], memory["memory_file_path"], seq, api_key)
        generate_memory_json([str(timestamp_out), "assistant", response_tokens, response], memory["memory_file"], memory["memory_file_path"], seq, api_key)
        
    return response, prompt_tokens, response_tokens, completion, timestamp


# 考察に対する画像生成
def generate_image_dalle(api_key, persona, model, parameter, input_limit, query, in_text_contents, memory, memory_docs_json, memory_mode, instance_path, file_path, seq):
    os.environ["OPENAI_API_KEY"] = api_key
    openai.api_key = api_key
    openai_client = OpenAI()

    #プロンプトの文字列調整
    prompt_template = "次の内容を踏まえたイメージ画像をコンテンツポリシーに反しない範囲で作成してください。<br><br>"
    prompt = prompt_template
    limit_len = input_limit - len(prompt_template)
    
    system_message = []
    #if limit_len > len(persona):
    #    #システム
    #    system_message=[
    #        {"role": "system", "content": persona}
    #    ]
    #    limit_len = limit_len - len(persona)
    
    if limit_len > len(query):
        prompt += query
        limit_len = limit_len - len(query) #文字数制限の調整（設定値－（プロンプトテンプレ＋クエリ））
    else:
        prompt += query[:limit_len]
        limit_len = 0
        
        if limit_len > len(in_text_contents):
            prompt += in_text_contents
            limit_len = limit_len - len(in_text_contents) #文字数制限の調整（－コンテンツテキスト）
        else:
            prompt += in_text_contents[:limit_len]
            limit_len = 0

    # メモリの取得
    memories = []
    if limit_len > 0: 
        memory_mode = [memory_mode[0], memory_mode[1], memory_mode[2], limit_len, memory_mode[4]]
        memory_file_path = instance_path
        memory_file = memory["memory_file"]
        memory_docs_json = read_docs_json(memory_file, memory_file_path)
        memory_results, memory_digest_data, memory_digest_latest = select_memory(openai_client, query, memory_docs_json, memory_mode)
          
        #メモリの設定
        memory_docs = memory["memory_docs"]
        for memory_doc in memory_docs:
            if len(memory_doc)==4:
                timestamp, user, similarity, text = memory_doc
                if limit_len > len(text) + 100:
                    memories.append({"role": user, "content": text})
                    limit_len = limit_len - len(text)
                    
    messages = system_message + memories + [{"role": "user", "content": prompt}]   
    text = json.dumps(messages, ensure_ascii=False)

    response = openai_client.images.generate(
        model=model,
        prompt=text,
        n=parameter["n"], #イメージ枚数
        size=parameter["size"],
        response_format="b64_json",  # レスポンスフォーマット url or b64_json
        quality=parameter["quality"],  # 品質 standard or hd
        style=parameter["style"]  # スタイル vivid or natural
    )

    img_files = []
    img_type = "image"
    file_no = 0
    os.makedirs(file_path, exist_ok=True)
    for i, d in enumerate(response.data):
        img_file = f"{model}_{seq}_{file_no}.jpg"
        with open(file_path+img_file, "wb") as f:
            f.write(base64.b64decode(d.b64_json))
        img_files.append({"file_no": file_no, "file_name": img_file, "file_type": img_type})
        file_no += 1
        
    return img_files

# APIを使用して画像生成してもらう関数
def generate_image(api_key, agent, instance_path, query, in_text_contents, query_images, context_str, model, model_img, memory, memory_docs_json, memory_mode, seq, AWS_KEY):
    persona = f'あなたの名前は「{agent["name"]}」です。{agent["role"]}として振る舞ってください。<br><br>【あなたのキャラクター設定】<br>{agent["character"]}<br><br>'
    file_path = instance_path+"generate/"
    
    timestamp_in = datetime.now()
    
    #　画像生成AIの実行 img_filesはファイル名のリスト
    img_files = call_function_by_name(model_img["FUNC_NAME"], api_key, persona, model_img["MODEL_NAME"], model_img["PARAMETER"], model_img["INPUT_LIMIT"], query, in_text_contents, memory, memory_docs_json, memory_mode, instance_path, file_path, seq) 
    
    timestamp_out = datetime.now()
    generate_time = timestamp_out - timestamp_in
    timestamp = [str(timestamp_in), str(timestamp_out), str(generate_time)]

    # コンテンツの保存とテキスト情報の取得【要修正】
    text_contents = ""
    file_url = ""
    query_images = []
    file_seq = 0
    for img_file in img_files:
        file_name = img_file["file_name"]
        file_size = os.path.getsize(file_path + file_name)
        file_type = img_file["file_type"]

        # S3にアップしてファイルのURLを取得
        file_url = upload_to_s3(file_path, file_name, AWS_KEY["IAM_ACCESS_KEY"], AWS_KEY["IAM_SECRET_KEY"], AWS_KEY["AWS_REGION"], AWS_KEY["S3_BUCKET_NAME"]) 
        #text_content, file_url = get_text_content(file_type, file_path, file_name, api_key, model, AWS_KEY) 
        #text_contents += text_content
        # 画像ファイルはURLをリスト化
        if "image" in file_type:
            query_images.append(file_url)
        # 添付ファイルをメモリに保存する
        if memory["memory_save"] == "Y":
            generate_memory_json([str(timestamp_in), "user_img", 0, query], memory["memory_file"], memory["memory_file_path"], seq, api_key)
            generate_memory_json([str(file_seq), "generate_file", file_size, "", file_type, file_name, file_path, file_url], memory["memory_file"], memory["memory_file_path"], seq)
        file_seq += 1

    return query_images


# クエリに含まれているフレーズ(呪文)からコマンドを検索
def find_command(query, command_data, default_command):
    # SPELLのデータをチェック
    for key, value in command_data.items():
        if 'SPELL' in value:
            for spell in value['SPELL']:
                if spell in query and value['SPELL'] != "":
                    return key
    return default_command

# 画像データからテキスト情報を生成
def get_image_to_text(func, api_key, model, parameter, file_urls):
    prompt = ("画像に映っている「全体的な概要」「特徴的な表現」「伝わってくる印象」を教えてください。<br>※画像の対象を知らない場合は大体の印象を教えてくれれば良いので、自信が無くても謝らずに回答してください。")   
    name = "Art Critic"
    role = "絵や写真を評価するプロフェッショナル"
    persona = f"あなたの名前は「{name}」です。{role}として振る舞ってください。"
    response, completion, prompt_tokens, response_tokens = call_function_by_name(func, api_key, persona, model, parameter, prompt, file_urls, "")
    return response, prompt_tokens, response_tokens

# アップロードしたファイルからコンテンツテキストを取得
def get_text_content(file_type, file_path, file_name, api_key, model, AWS_KEY):
    text_content = ""
    file_url = ""
    if "text" in file_type:
        with open(file_path+file_name, "r", encoding="utf-8") as f:
            text_content = "<br>---------<br>ファイル名: "+file_name+"<br><br>"+f.read()
    elif "csv" in file_type:
        with open(file_path+file_name, "r", encoding="utf-8") as f:
            text_content = "<br>---------<br>ファイル名: "+file_name+"<br><br>"+f.read()
    #elif "excel" in file_type:
    #    df = pd.read_excel(uploaded_file)
    elif "image" in file_type:
        #S3に画像をアップロードしてURL取得
        file_url = upload_to_s3(file_path, file_name, AWS_KEY["IAM_ACCESS_KEY"], AWS_KEY["IAM_SECRET_KEY"], AWS_KEY["AWS_REGION"], AWS_KEY["S3_BUCKET_NAME"]) 
        response, prompt_tokens, response_tokens = get_image_to_text(model["FUNC_NAME"], api_key, model["MODEL_NAME"], model["PARAMETER"], [file_url])
        text_content = "<br>---------<br>ファイル名: "+file_name+"<br><br>"+response
    #elif "video" in file_type:
        #将来的にコンテキストを取得
    #elif "audio" in file_type:
        #将来的にコンテキストを取得
    return text_content, file_url

# 会話のダイジェスト生成
def dialog_digest(func, api_key, model, temperature, memory_digest_data):
    prompt = (
        "これまでの【会話履歴】のダイジェストを時系列で箇条書きしてください。<br>・これまでの会話履歴に登場したトピックをなるべく漏らさないように網羅的に記述してください。<br>・長くても2000文字以内にまとめてください。<br><br>"
        f"【会話履歴】<br> {memory_digest_data}<br>"
        )   
    name = "Good Facilitator"
    role = "様々な会話のダイジェストを生成する"
    persona = f"あなたの名前は「{name}」です。{role}として振る舞ってください。"
    parameter = {}
    parameter["temperature"] = temperature
    response, completion, prompt_tokens, response_tokens = call_function_by_name(func, api_key, persona, model, parameter, prompt, [], "")
    return response, prompt_tokens, response_tokens

# 会話メモリのダイジェストの生成
def process_memory_digests(func, api_key, model, temperature, memory_digest_data, max_length=30000):
    memory_digests = split_into_subarrays(memory_digest_data, max_length)
    memory_digest_texts = []
    memory_digest_text = ""
    prompt_tokens_total = 0
    response_tokens_total = 0
    for memory_digest in memory_digests:
        response, prompt_tokens, response_tokens = dialog_digest(func, api_key, model, temperature, memory_digest)
        memory_digest_texts.append(response)
        prompt_tokens_total += prompt_tokens
        response_tokens_total += response_tokens
    while len(memory_digest_texts) > 1:
        combined_text = ''.join(memory_digest_texts)
        memory_digests = split_into_subarrays(combined_text, max_length)
        memory_digest_texts = []
        for memory_digest in memory_digests:
            response, prompt_tokens, response_tokens = dialog_digest(func, api_key, model, temperature, memory_digest)
            memory_digest_texts.append(response)
            prompt_tokens_total += prompt_tokens
            response_tokens_total += response_tokens
    if memory_digest_texts:
        memory_digest_text = memory_digest_texts[0]
    return memory_digest_text, prompt_tokens_total, response_tokens_total


# デジタルMATSUMOTOを対話形式で実行
def DigiMatsu_dialog(query, chat_instance_id, common_path, instance_path, memory_file, para_persona, para_persona_data, para_persona_default_mode, para_memory, para_overwrite, para_api_key, para_models_dict, para_prompt_template_dict, rag_file_path, para_rag_data_dict, para_rag_format_dict, uploaded_files, AWS_KEY):
    # 現在(考察作成日)の設定
    current_date = datetime.now()
    
    # OpenAIのクライアント設定(メモリダイジェストとRAGのベクトルサーチ用)
    os.environ["OPENAI_API_KEY"] = para_api_key["OPENAI_API_KEY"]
    openai.api_key = para_api_key["OPENAI_API_KEY"]
    openai_client = OpenAI()
    
    # Agentのペルソナ(システムプロンプト)を初期設定（初期状態はsetting_envのpersonaに設定したDEFAULT_MODE）
    agent = {
        "name": para_persona_data[para_persona_default_mode]['NAME'],
        "role": para_persona_data[para_persona_default_mode]['ROLE'],
        "character_setting": para_persona_data[para_persona_default_mode]['CHARACTER'],
        "character": get_str_or_txt(common_path+"character/", para_persona_data[para_persona_default_mode]['CHARACTER'])
    }
    
    #【メモリ設定】
    memory_mode = [para_memory['memory_use'], para_memory['memory_agent'], para_memory['memory_loader'], para_memory['memory_text_limits'], para_memory['memory_distance_logic']]
    memory_file_path = instance_path
    memory_docs_json = read_docs_json(memory_file, memory_file_path)
    memory_digest = "Y" if para_memory["memory_digest"] else "N"
    memory_digest_latest = ()
    memory_digest_texts = []

    # 現在の会話シーケンスの設定
    seq = get_memory_seq(memory_file, memory_file_path)
    
    # メモリの取得
    memory_results, memory_digest_data, memory_digest_latest = select_memory(openai_client, query, memory_docs_json, memory_mode)
    query_memory = "" #コンテキスト検索用(文字列)
    memory_docs = [] #実行用(配列)
    for timestamp, user, similarity, text in memory_results:
        query_memory = query_memory +"<br>"+ text
        memory_docs.append((timestamp, user, similarity, text))
    memory_docs = [memory_digest_latest] + sorted(memory_docs, key=lambda x: x[0])
    
    # メモリのログ保存
    memory_format = para_memory['memory_format']
    memory_format_data = para_memory['memory_format_data']
    memory_docs_text = ""
    for memory_doc in memory_docs:
        if len(memory_doc)==4:
            timestamp, user, similarity, text = memory_doc
            text = text.replace("\n", "")[:30]
            memory_docs_text += memory_format_data.format(timestamp=timestamp, similarity=round(similarity,3), user=user, text=text)
    
    # メモリ保存の設定
    memory_save = "Y" if para_memory["memory_save"] else "N"
    memory = {
        "memory_docs": memory_docs,
        "memory_file": memory_file, 
        "memory_save": memory_save, 
        "memory_file_path": memory_file_path
    }
       
    # コマンド選択
    command = find_command(query, para_persona_data, para_persona_default_mode)
    
    # 画面設定による上書き
    if para_overwrite["overwrite"] == "Y":
        prompt_format = para_overwrite["prompt_format"]
        prompt_format_data = para_prompt_template_dict["PROMPT_FORMAT"][prompt_format]
        writing_style = para_overwrite["writing_style"]
        writing_style_data = para_prompt_template_dict["WRITING_STYLE"][writing_style]
        model = para_models_dict[para_overwrite["model"]]
        rag_knowledge = {
            "datasets": para_overwrite["rag_knowledge_data"],
            "format": para_overwrite["rag_knowledge_format"],
            "format_data": para_rag_format_dict.get(para_overwrite["rag_knowledge_format"], {}),
            "text_limits": para_overwrite["rag_knowledge_text_limits"],
            "logic": para_overwrite["rag_knowledge_distance_logic"]
        }
        rag_policy = {
            "datasets": para_overwrite["rag_policy_data"],
            "format": para_overwrite["rag_policy_format"],
            "format_data": para_rag_format_dict.get(para_overwrite["rag_policy_format"], {}),
            "text_limits": para_overwrite["rag_policy_text_limits"],
            "logic": para_overwrite["rag_policy_distance_logic"]
        }
    # Agentを設定(上書きしない場合)
    else:
        prompt_format = para_persona_data[command]["PROMPT_TEMPLATE"]["PROMPT_FORMAT"]
        prompt_format_data = para_prompt_template_dict["PROMPT_FORMAT"][prompt_format]
        writing_style = para_persona_data[command]["PROMPT_TEMPLATE"]["WRITING_STYLE"]
        writing_style_data = para_prompt_template_dict["WRITING_STYLE"][writing_style]
        model = para_models_dict[para_persona_data[command]["MODEL"]]
        rag_knowledge = {
            "datasets": para_persona_data[command]["RAG_KNOWLEDGE"]["DATA"],
            "format": para_persona_data[command]["RAG_KNOWLEDGE"]["FORMAT"],
            "format_data": para_rag_format_dict.get(para_persona_data[command]["RAG_KNOWLEDGE"]["FORMAT"], {}),
            "text_limits": para_persona_data[command]["RAG_KNOWLEDGE"]["TEXT_LIMITS"],
            "logic": para_persona_data[command]["RAG_KNOWLEDGE"]["DISTANCE_LOGIC"]
        }
        rag_policy = {
            "datasets": para_persona_data[command]["RAG_POLICY"]["DATA"],
            "format": para_persona_data[command]["RAG_POLICY"]["FORMAT"],
            "format_data": para_rag_format_dict.get(para_persona_data[command]["RAG_POLICY"]["FORMAT"], {}),
            "text_limits": para_persona_data[command]["RAG_POLICY"]["TEXT_LIMITS"],
            "logic": para_persona_data[command]["RAG_POLICY"]["DISTANCE_LOGIC"]
        }

    # コンテンツの保存とテキスト情報の取得
    text_contents = ""
    file_url = ""
    query_images = []
    file_seq = 0
    for uploaded_file in uploaded_files:
        file_name = "seq"+str(seq)+"_"+str(file_seq)+"_"+uploaded_file.name[:20]
        file_size = uploaded_file.size
        file_type = uploaded_file.type
        file_path = instance_path+"upload/"
        save_uploaded_files(file_path, file_name, uploaded_file) #ファイルのフォルダへの保存
        # コンテンツの情報をテキストに変換したものを取得（RAGに反映するため、全ファイルを一度テキスト化）
        text_content, file_url = get_text_content(file_type, file_path, file_name, para_api_key[model["API_KEY"]], model, AWS_KEY) 
        text_contents += text_content
        # 画像ファイルはURLをリスト化
        if "image" in file_type:
            query_images.append(file_url)
        # 添付ファイルをメモリに保存する
        generate_memory_json([str(file_seq), "uploaded_file", file_size, text_content, file_type, file_name, file_path, file_url], memory_file, memory_file_path, seq)
        file_seq += 1
    
    # プロンプトテンプレートを設定
    prompt_template = prompt_format_data.format()+"<br>"+writing_style_data.format()

    # RAGコンテキスト生成
    rag_context_query = ""
    if query_memory:
        rag_context_query = "これまでの会話履歴:<br>"+ query_memory +"<br><br>質問:<br>"+ query + text_contents
    else:
        rag_context_query = query + text_contents
    rag_context_str, retrival_docs = create_rag_context(openai_client, rag_context_query, current_date, [rag_knowledge, rag_policy], rag_file_path)

    # 画像生成の実行（生成した画像はgenerate_responseで解説してもらう）
    if command == "IMAGE_GEN":
        model_img = para_models_dict[para_persona_data[command]["MODEL_IMG"]]
        query_images = generate_image(para_api_key[model["API_KEY"]], agent, instance_path, query, text_contents, query_images, rag_context_str, prompt_template, model_img, memory, memory_docs_json, memory_mode, seq, AWS_KEY)
        query = f"生成された画像に映っている「全体的な概要」「特徴的な表現」「伝わってくる印象」を教えてください。<br>※画像の対象を知らない場合は大体の印象を教えてくれれば良いので、自信が無くても謝らずに回答してください。<br><br>【画像生成時のインプット】<br>{query}"
 
    # LLMを実行
    response, prompt_tokens, response_tokens, completion, timestamp = generate_response(para_api_key[model["API_KEY"]], agent, query, text_contents, query_images, rag_context_str, prompt_template, model, memory, seq)

    # レスポンスと参照情報の類似度評価
    retrival_docs_text = ""
    embed_vec_response = embed_text(openai_client, response.replace("\n", ""))
    for key, similarity_query, date, days_difference, title, category, text, url, vec_text in retrival_docs:
        # レスポンスとの類似度を出す。
        similarity_response = calculate_similarity_vec(embed_vec_response, vec_text) #デフォルト(Cosine)で類似度計算
        retrival_docs_text += f"{date}時点の知識[カテゴリ：{category}、質問との類似度：{round(similarity_query,3)}、回答との類似度：{round(similarity_response,3)}]{title}<br>{text[:50]}<br>参考情報：{url}<br>"
    
    # メモリの更新
    detail = f'名前：{agent["name"]}<br>ロール：{agent["role"]}<br>キャラクター設定：{agent["character_setting"]}<br><br>コマンド：{command}<br>プロンプトテンプレート：{prompt_format}<br>文体：{writing_style}<br><br>実行モデル：{model["MODEL_NAME"]} {model["PARAMETER"]}<br>RAG設定(Knowledge)：{rag_knowledge["format"]}<br>RAG設定(Policy)：{rag_policy["format"]}<br><br>回答時間：{timestamp[2]}<br>入力トークン数：{prompt_tokens}<br>出力トークン数：{response_tokens}<br><br>メモリ設定：{para_memory}<br><br>【参照したメモリ】<br>{memory_docs_text}<br>【参照した知識】<br>{retrival_docs_text}<br><br>【コンテンツテキスト】<br>{text_contents}<br>'
    if memory_save == "Y":
        # LLMでメモリのダイジェストを生成する
        if memory_digest == "Y":
            memory_docs_json = read_docs_json(memory_file, memory_file_path)
            memory_digest_texts = []
            memory_results_re, memory_digest_data, memory_digest_latest = select_memory(openai_client, query, memory_docs_json, memory_mode)
            memory_digest_text, prompt_tokens_total, response_tokens_total = process_memory_digests(model["FUNC_NAME"], para_api_key["OPENAI_API_KEY"], model["MODEL_NAME"], 0.1, memory_digest_data, 30000)
            generate_memory_json([str(timestamp[1]), "digest", prompt_tokens_total+response_tokens_total, memory_digest_text], memory_file, memory_file_path, seq, para_api_key["OPENAI_API_KEY"])
            detail += f"<br>【この会話のダイジェスト】<br>{memory_digest_text}"

        # 参考情報をメモリに保存する
        generate_memory_json([str(timestamp[1]), "detail", 0, detail], memory_file, memory_file_path, seq)

    return [response, prompt_tokens, response_tokens, completion, timestamp, memory_docs_text, retrival_docs_text, detail]
