import os
import logging
import pytz
import re
import numpy as np
import json
import yaml
import shutil
import mimetypes
import math
import bcrypt
import pdfplumber
from dateutil import parser
from datetime import datetime
from dotenv import load_dotenv

import unicodedata
from pathlib import Path

import MeCab
from sklearn.feature_extraction.text import TfidfVectorizer
from wordcloud import WordCloud

import base64
import tiktoken
import openai
from openai import OpenAI
from google import genai
import fitz  # PyMuPDF
from docx import Document as DocxDocument
from pptx import Presentation
from pptx.util import Emu

# system.envファイルをロードして環境変数を設定
if os.path.exists("system.env"):
    load_dotenv("system.env")
timezone = os.getenv("TIMEZONE")
openai_api_key = os.getenv("OPENAI_API_KEY")
gemini_api_key = os.getenv("GEMINI_API_KEY")
embedding_model = os.getenv("EMBEDDING_MODEL")

# ロギングの初期設定（アプリケーション起動時に一度呼び出す）
def setup_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

#タイムスタンプ文字列を時刻に変換
def safe_parse_timestamp(timestamp_str):
    jst = pytz.timezone(timezone)
    try:
        return jst.localize(datetime.strptime(timestamp_str, "%Y/%m/%d %H:%M:%S")).isoformat()
    except ValueError:
        return datetime.now(jst).isoformat()

#日付型文字列の変換
def parse_date(d):
    try:
        return datetime.fromisoformat(d)
    except Exception:
        return datetime.min

# LOG_TEMPLATE形式の文字列をdictに安全にパース
def parse_log_template(ref_str: str) -> dict:
    """LOG_TEMPLATE形式の文字列（'key': value, ...）をdictに変換。
    テキスト内にシングルクォートやダブルクォート、特殊文字が含まれていてもパース可能。"""
    import re
    s = str(ref_str).replace("\n", "").replace("$", "＄")
    try:
        return ast.literal_eval("{" + s + "}")
    except Exception:
        pass
    # フォールバック: 既知のキー名で分割してパース
    result = {}
    # 'key': パターンの位置を全て検出
    key_pattern = re.compile(r"'(\w+)'\s*:\s*")
    matches = list(key_pattern.finditer(s))
    for i, m in enumerate(matches):
        key = m.group(1)
        val_start = m.end()
        val_end = matches[i + 1].start() if i + 1 < len(matches) else len(s)
        raw_val = s[val_start:val_end].strip().rstrip(",").strip()
        # クォートを除去
        if (raw_val.startswith("'") and raw_val.endswith("'")) or \
           (raw_val.startswith('"') and raw_val.endswith('"')):
            raw_val = raw_val[1:-1]
        # 数値変換を試みる
        try:
            result[key] = int(raw_val)
        except (ValueError, TypeError):
            try:
                result[key] = float(raw_val)
            except (ValueError, TypeError):
                result[key] = raw_val
    return result

# テキストのサニタイズ（JSON/XML禁則文字・制御文字を除去）
def sanitize_text(text: str) -> str:
    """LLM応答テキストからJSON/XMLで問題になる制御文字を除去する。
    サロゲートペア（絵文字等）は保持する。"""
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    # NUL文字と制御文字（タブ・改行・CRは保持）を除去
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

# ファイル名のサニタイズ
def sanitize_filename(name: str, replacement: str = "_", max_length: int = 255, keep_unicode: bool = True) -> str:
    """
    ファイル名として危険/不便な文字を除去 or 置換して返す。
    - パス区切り /, \\ や制御文字などは除去
    - Windows 禁止文字 <>:"/\\|?* を除去
    - 例にある ", ', $, %, / も除去対象
    - 末尾のドット/スペースを除去（Windows対策）
    - 空になった場合は 'untitled'
    """
    if name is None:
        return "untitled"
    
    # Windows予約語（拡張子無し部分がこれだと保存できない/面倒）
    _WINDOWS_RESERVED = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }

    # 前後の空白（特に末尾の空白はWindowsで問題になりやすい）
    name = name.strip()

    # Unicode正規化（見た目同じの文字を揃える）
    name = unicodedata.normalize("NFKC", name)

    # 文字種の扱い：ASCIIに寄せたいなら keep_unicode=False
    if not keep_unicode:
        name = name.encode("ascii", "ignore").decode("ascii")

    # 制御文字を除去
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")

    # パス区切りは絶対に消す（ディレクトリトラバーサル対策にもなる）
    name = name.replace("/", replacement).replace("\\", replacement)

    # Windowsで禁止の文字を置換/除去: <>:"/\|?*
    name = re.sub(r'[<>:"/\\|?*]', replacement, name)

    # 例の文字など、一般にファイル名で面倒になりやすい記号を広めに除去したい場合
    # 必要に応じて増減してください
    name = re.sub(r"""["'$%]""", "", name)

    # 連続する replacement をまとめる
    if replacement:
        rep_esc = re.escape(replacement)
        name = re.sub(rf"{rep_esc}+", replacement, name)

    # 先頭/末尾の replacement やドット/スペースを整理
    name = name.strip(" ._")

    # 空になったら保険
    if not name:
        name = "untitled"

    # Windows予約語対策（拡張子を除いた部分が予約語なら前に _ を付ける）
    stem, dot, suffix = name.partition(".")
    if stem.upper() in _WINDOWS_RESERVED:
        name = f"_{name}"

    # 長すぎる場合（拡張子はなるべく残す）
    if len(name) > max_length:
        p = Path(name)
        ext = p.suffix
        base = p.stem
        cut = max_length - len(ext)
        name = base[:max(1, cut)] + ext

    name = name.rstrip(" .")
    return name

# パスワードのハッシュ化と検証
def hash_password(plain: str) -> str:
    # bcrypt は bytes を扱う
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(plain.encode("utf-8"), salt)
    return hashed.decode("utf-8")

# パスワードの検証
def verify_password(plain: str, stored: str) -> bool:
    if stored.startswith("$2a$") or stored.startswith("$2b$") or stored.startswith("$2y$"):
        return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
    return plain == stored

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

# パターンからリストを出力するPG
def extract_list_pattern(text, pattern=r"(\[\s*{.*?}\s*\])"):
    match = re.search(pattern, text, re.DOTALL)
    if match:
        json_str = match.group(1)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return []
    return []

# 期間リストの絞込
def merge_periods(periods):
    converted = [
        {
            "start": datetime.strptime(p["start"], "%Y/%m/%d"),
            "end": datetime.strptime(p["end"], "%Y/%m/%d"),
        }
        for p in periods
    ]

    # startでソート
    converted.sort(key=lambda x: x["start"])
    merged = []
    for p in converted:
        if not merged:
            merged.append(p)
            continue
        last = merged[-1]

        # 重なり or 隣接している場合はマージ
        if p["start"] <= last["end"]:
            last["end"] = max(last["end"], p["end"])
        else:
            merged.append(p)

    # datetime
    result = [
        {
            "start": m["start"].strftime("%Y/%m/%d"),
            "end": m["end"].strftime("%Y/%m/%d"),
        }
        for m in merged
    ]

    return result

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
    files = []
    if os.path.exists(folder_path):
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

# PDFファイルからテキスト＋画像を抽出
def read_pdf_with_images(file_path, temp_folder):
    """PDFからテキスト（ページ単位）と埋め込み画像を抽出する"""
    pdf_text = {}
    image_files = []
    os.makedirs(temp_folder, exist_ok=True)

    # テキスト抽出（pdfplumber）
    with pdfplumber.open(file_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            # テーブルも抽出
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    text += "\n[表]\n"
                    for row in table:
                        text += " | ".join([str(cell) if cell else "" for cell in row]) + "\n"
            pdf_text[f"Page_{i + 1}"] = text

    # 画像抽出（PyMuPDF）
    doc = fitz.open(file_path)
    img_idx = 0
    for page_num in range(len(doc)):
        page = doc[page_num]
        images = page.get_images(full=True)
        for img in images:
            xref = img[0]
            base_image = doc.extract_image(xref)
            if base_image and base_image["image"]:
                ext = base_image.get("ext", "png")
                img_path = os.path.join(temp_folder, f"pdf_p{page_num+1}_img{img_idx}.{ext}")
                with open(img_path, "wb") as f:
                    f.write(base_image["image"])
                image_files.append(img_path)
                img_idx += 1
    doc.close()
    return pdf_text, image_files

# DOCXファイルからテキスト＋画像を抽出
def read_docx_file(file_path, temp_folder):
    """DOCXから段落テキスト・テーブル・埋め込み画像を抽出する"""
    os.makedirs(temp_folder, exist_ok=True)
    doc = DocxDocument(file_path)
    text_parts = []
    image_files = []
    img_idx = 0

    # 段落テキスト
    for para in doc.paragraphs:
        if para.text.strip():
            text_parts.append(para.text)

    # テーブル
    for table in doc.tables:
        text_parts.append("[表]")
        for row in table.rows:
            cells = [cell.text for cell in row.cells]
            text_parts.append(" | ".join(cells))

    # 埋め込み画像
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            img_data = rel.target_part.blob
            ext = os.path.splitext(rel.target_ref)[1] or ".png"
            img_path = os.path.join(temp_folder, f"docx_img{img_idx}{ext}")
            with open(img_path, "wb") as f:
                f.write(img_data)
            image_files.append(img_path)
            img_idx += 1

    return "\n".join(text_parts), image_files

# XLSXファイルからテキストを抽出
def read_xlsx_file(file_path):
    """XLSXから全シートのセルデータをテーブル形式で抽出する"""
    import openpyxl
    wb = openpyxl.load_workbook(file_path, data_only=True)
    text_parts = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        text_parts.append(f"[シート: {sheet_name}]")
        for row in ws.iter_rows(values_only=True):
            cells = [str(cell) if cell is not None else "" for cell in row]
            if any(cells):
                text_parts.append(" | ".join(cells))
    return "\n".join(text_parts)

# PPTXファイルからテキスト＋画像を抽出
def read_pptx_file(file_path, temp_folder):
    """PPTXからスライドごとのテキスト・テーブル・ノート・埋め込み画像を抽出する"""
    os.makedirs(temp_folder, exist_ok=True)
    prs = Presentation(file_path)
    text_parts = []
    image_files = []
    img_idx = 0

    for slide_num, slide in enumerate(prs.slides, 1):
        slide_text = f"\n[スライド {slide_num}]"

        # タイトル
        if slide.shapes.title and slide.shapes.title.text:
            slide_text += f"\nタイトル: {slide.shapes.title.text}"

        # テキスト・テーブル・画像
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    if para.text.strip():
                        slide_text += f"\n{para.text}"
            elif shape.has_table:
                slide_text += "\n[表]"
                for row in shape.table.rows:
                    cells = [cell.text for cell in row.cells]
                    slide_text += "\n" + " | ".join(cells)
            if shape.shape_type == 13:  # Picture
                try:
                    img_blob = shape.image.blob
                    ext = shape.image.content_type.split("/")[-1] if shape.image.content_type else "png"
                    img_path = os.path.join(temp_folder, f"pptx_s{slide_num}_img{img_idx}.{ext}")
                    with open(img_path, "wb") as f:
                        f.write(img_blob)
                    image_files.append(img_path)
                    img_idx += 1
                    slide_text += f"\n[画像: pptx_s{slide_num}_img{img_idx-1}.{ext}]"
                except Exception:
                    pass

        # ノート
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                slide_text += f"\nノート: {notes}"

        text_parts.append(slide_text)

    return "\n".join(text_parts), image_files

# JSONファイルの読込
def read_json_file(file_name, folder_path=""):
    data = {}
    file_path = folder_path + file_name
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            data = json.load(file)
    return data

# YAMLファイルの読込
def read_yaml_file(file_name, folder_path=""):
    data = {}
    file_path = folder_path + file_name
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding="utf-8") as file:
            data = yaml.safe_load(file)
    if data is None:
        data = {}
    return data

# YAMLファイルの保存
def save_text_file(data, file_path):
    with open(file_path, 'w', encoding="utf-8") as f:
        f.write(data)

def save_json_file(data, file_path):
    with open(file_path, 'w', encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def save_yaml_file(data, file_name, folder_path=""):
    current_data = read_yaml_file(file_name, folder_path)
    current_data.update(data)
    file_path = folder_path + file_name
    with open(file_path, 'w', encoding="utf-8") as f:
#        yaml.dump(data, file, allow_unicode=True)
        yaml.dump(current_data, f, allow_unicode=True)

# MP3ファイルをテキストに変換
def mp3_to_text(file_name, folder_path=""):
    client = OpenAI(api_key=openai_api_key)
    file_path = folder_path + file_name
    if os.path.exists(file_path):
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ja"
            )
        data = transcript.text
    else:
        data = ""
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

# Embeddingクライアント・トークナイザのシングルトン
_embed_client = None
_embed_enc = None

def _get_embed_client():
    global _embed_client, _embed_enc
    if _embed_client is None:
        _embed_client = OpenAI(api_key=openai_api_key)
    if _embed_enc is None:
        _embed_enc = tiktoken.encoding_for_model(embedding_model)
    return _embed_client, _embed_enc

# テキストを埋め込みベクトルに変換（OpenAIのEmbeddingモデル）
def embed_text(text):
    client, enc = _get_embed_client()
    max_tokens = 8192
    tokens = enc.encode(text)
    if len(tokens) > max_tokens:
        tokens = tokens[:max_tokens]
    safe_text = enc.decode(tokens)
    response = client.embeddings.create(model=embedding_model, input=safe_text)
    return response.data[0].embedding

# C-3: 複数テキストを1回のAPI呼び出しでベクトル化（バッチ処理）
def embed_texts_batch(texts):
    client, enc = _get_embed_client()
    max_tokens = 8192
    safe_texts = []
    for text in texts:
        tokens = enc.encode(text)
        if len(tokens) > max_tokens:
            tokens = tokens[:max_tokens]
        safe_texts.append(enc.decode(tokens))
    response = client.embeddings.create(model=embedding_model, input=safe_texts)
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]

# 埋め込みベクトルの配列を1つのnpyファイルに保存
def save_vectext_to_npy(vec_text, file_path, dtype="float32"):
    arr = np.asarray(vec_text, dtype=dtype)
    np.save(file_path, arr)

# 埋め込みベクトルの配列をnpyファイルから読込
def read_vectext_to_npy(file_path, mmap=False):
    # ファイルが存在しない場合は空の配列を返す
    if not os.path.exists(file_path):
        return np.array([])

    # mmapがTrueの場合はメモリマップド配列として読み込む
    if mmap:
        return np.load(file_path, mmap_mode="r")
    else:
        return np.load(file_path)

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
def get_wordcloud(title, dict, folder_path="user/common/analytics/insight/"):
    font_path = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"
    wc = WordCloud(background_color="white", font_path=font_path, width=800, height=600, max_words=50, contour_color='steelblue')
    wc.generate_from_frequencies(dict)
    file_name = folder_path + f"WordCloud_{title}.png"
    wc.to_file(file_name)

# トークンの計算
def count_token(tokenizer, model, text):
    tokens = 0
    if tokenizer == "tiktoken":
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = len(encoding.encode(text))
    elif tokenizer == "gemini":
        gemini_client = genai.Client(api_key=gemini_api_key)
        response_tokens = gemini_client.models.count_tokens(model=model, contents=text)
        tokens = response_tokens.total_tokens
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
    elif logic == "Chebyshev":
        distance = calculate_minkowski_distance(vec1, vec2, float('inf'))
    else: #通常はコサイン距離
        distance = calculate_cosine_distance(vec1, vec2)
    return distance