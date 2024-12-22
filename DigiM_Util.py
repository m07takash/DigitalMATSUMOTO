import os
import numpy as np
import json
import shutil
import mimetypes
import math
import pdfplumber
from dateutil import parser
from datetime import datetime
from dotenv import load_dotenv

import MeCab
from sklearn.feature_extraction.text import TfidfVectorizer

from wordcloud import WordCloud
import matplotlib.pyplot as plt

import base64
import tiktoken
import openai
from openai import OpenAI

# system.envファイルをロードして環境変数を設定
load_dotenv("system.env")
openai_api_key = os.getenv("OPENAI_API_KEY")
embedding_model = os.getenv("EMBEDDING_MODEL")

# ローカルファイルをStreamlitのUploadedFileと同じオブジェクト型に変換
class ConvertedLocalFile:
    def __init__(self, file_path):
        self.file_path = file_path
        self.name = os.path.basename(file_path)
        self.size = os.path.getsize(file_path)
        self.type, _ = mimetypes.guess_type(file_path)
        
    def read(self):
        with open(self.file_path, 'rb') as f:
            return f.read()

# 辞書を再帰的に上書きする関数
def update_dict(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            # ネストされた辞書がある場合、再帰的に更新
            update_dict(target[key], value)
        else:
            target[key] = value

# フォルダから複数ファイルを取得
def get_files(folder_path="", identifier="", file_sort="Y"):
    all_files = os.listdir(folder_path)
    files = [f for f in all_files if f.endswith(identifier)]
    if file_sort == "Y":
        files.sort()
    return files

# ファイルの移動
def copy_file(from_file_path, to_file_path):
    shutil.move(from_file_path, to_file_path)

# テキストファイルの読込
def read_text_file(file_name, folder_path=""):
    file_path = folder_path + file_name
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            data = file.read()
    else:
        data = ""
    return data

# PDFファイルの読込
def read_pdf_file(file_name, folder_path=""):
    file_path = folder_path + file_name
    pdf_dict = {}
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            # 各ページのテキストを抽出してページごとに辞書型に格納
            pdf_dict[f"Page_{i + 1}"] = page.extract_text()
    return pdf_dict

# JSONファイルの読込
def read_json_file(file_name, folder_path=""):
    file_path = folder_path + file_name
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            data = json.load(file)
    else:
        data = {}
    return data

# 画像ファイルをbase64でエンコード　
def encode_image_file(image_path):
    image_base64 = None
    with open(image_path, "rb") as image_file:
        image_base64 = base64.b64encode(image_file.read()).decode('utf-8')
    return image_base64

# 二つのタイムスタンプの差を文字列で得る
def get_time_diff(timestamp1, timestamp2, format_str="%Y-%m-%d %H:%M:%S.%f"):
    time1 = datetime.strptime(timestamp1, format_str)
    time2 = datetime.strptime(timestamp2, format_str)
    time_difference = time2 - time1
    return str(time_difference)

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

# テキストを埋め込みベクトルに変換（OpenAIのEmbeddingモデル）
def embed_text(text):
    openai.api_key = openai_api_key
    openai_client = OpenAI()
    response = openai_client.embeddings.create(model=embedding_model, input=text)
    response_vec = response.data[0].embedding    
    return response_vec

# 形態素解析(Owakati)
def tokenize_Owakati(text, mode="Default", stop_words=[], grammer=('名詞', '動詞', '形容詞', '副詞')):
    mecab = MeCab.Tagger("-Owakati")
    wakati_text = mecab.parse(text)
    tokens = wakati_text.split()    
    if mode == "All":
        # stop_wordsの除去
        tokens = [word for word in tokens if word not in stop_words]
    else:
        mecab = MeCab.Tagger()  # 形態素解析のタグを取得するためにデフォルトのオプションで再度MeCabインスタンスを作成
        valid_tokens = []
        for token in tokens:
            node = mecab.parseToNode(token)  # 各トークンに対して形態素解析を実行
            while node:
                pos = node.feature.split(",")[0]
                if pos.startswith(grammer) and token not in stop_words:
                    valid_tokens.append(token)
                    break  # 同じトークンに対する重複検査を避けるためにループを終了
                node = node.next
        tokens = valid_tokens
    return tokens

# テキストの集合からTF-IDFベクトライザーを作成
def fit_tfidf(texts, mode="Default", stop_words=[], grammer=('名詞', '動詞', '形容詞', '副詞')):
    vectorizer = TfidfVectorizer(tokenizer=lambda x: tokenize_Owakati(x, mode, stop_words, grammer), lowercase=False)
    vectorizer.fit(texts)
    return vectorizer

# キーワードのTF-IDF値を取得
def get_tfidf(text, vectorizer):
    tfidf_matrix = vectorizer.transform([text])
    feature_names = vectorizer.get_feature_names_out()
    tfidf_scores = tfidf_matrix.toarray()[0]
    tfidf_pairs = sorted(zip(feature_names, tfidf_scores), key=lambda x: x[1], reverse=True)
    tfidf_dict = dict(tfidf_pairs)
    #tfidf_pairs = [(word, score) for word, score in tfidf_dict.items()]
    return tfidf_pairs, tfidf_dict

# リストからTF-IDFを取得
def get_tfidf_list(text, vectorizer, TopN):
    tfidf_pairs, tfidf_dict = get_tfidf(text, vectorizer)
    tfidf_topN = tfidf_pairs[:TopN] # 上位Nの項目を取得
    tfidf_topN_list = [i[0] for i in tfidf_topN]
    tfidf_topN_str = '、'.join([f'{item[0]}：{round(item[1], 10)}' for item in tfidf_topN])
    return tfidf_dict, tfidf_topN, tfidf_topN_str

# ワードクラウドで可視化
def get_wordcloud(title, dict, folder_path="user/common/wordcloud/"):
    font_path = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"
    wc = WordCloud(background_color="white", font_path=font_path, width=800, height=600, max_words=50, contour_color='steelblue')
    wc.generate_from_frequencies(dict)
    file_name = folder_path + f"WordCloud_{title}.png"
    wc.to_file(file_name)

# トークンの計算
def count_token(tokenizer, model, text):
    tokens = 0
    if tokenizer == "tiktoken":
        encoding = tiktoken.encoding_for_model(model)
        tokens = len(encoding.encode(text))
    else:
        tokens = len(text)
    return tokens

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