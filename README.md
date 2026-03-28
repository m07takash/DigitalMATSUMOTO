# Digital MATSUMOTO

## はじめに

本PGはApache2.0Licenceで公開しており、商用利用を認めています。
ただし、本PGを用いたユーザー側での活動に対して、開発者は一切の責任を負いませんので、あくまで御自身の責任においてPGを利用してください。

本PGはビジネスのシーンで活用されたことがありますが、
あくまで研究もしくはPoCを目的として開発を行っており、開発者の任意のタイミングでプログラムの更新が行われます。
実際のビジネスで用いる場合、Apache2.0のライセンスを遵守いただきながら、御自身の判断と責任において最適なシステム環境で構築・運用いただくことを推奨します。

Digital MATSUMOTO lab合同会社

## 本プログラム開発においてこだわっていること

- 作業効率化ではなく、人間の知識をAIが再現できるかが主目的
- 知識の貢献などを観察できるようにする
- 自律化は目的としない。AIを使いながらヒト自身も成長できるかが命題
- 特定のLLMに依存しない
- コンテキストデザインをこだわって作る
- LangChainやllama indexのようなライブラリを使わない（LLMのAPIを裸の状態で叩く）
- 個人の環境でも動くような構成

## 参考ドキュメント

- [概要とアーキテクチャの説明](https://github.com/m07takash/DigitalMATSUMOTO/blob/main/docs/%E3%83%87%E3%82%B8%E3%82%BF%E3%83%ABMATSUMOTO%E3%81%AE%E6%A6%82%E8%A6%81%E3%81%A8%E3%82%A2%E3%83%BC%E3%82%AD%E3%83%86%E3%82%AF%E3%83%81%E3%83%A3.pdf)
- [インストール＆セットアップ及びエージェントの設定等（ハンズオン資料）](https://github.com/m07takash/DigitalMATSUMOTO/blob/main/docs/%E3%83%87%E3%82%B8%E3%82%BF%E3%83%ABMATSUMOTO-PG%E3%83%8F%E3%83%B3%E3%82%BA%E3%82%AA%E3%83%B3.pdf)

## アーキテクチャ概要

```
[Streamlit UI / FastAPI / Jupyter Notebook]
          |
   DigiM_Execute.py        # 実行オーケストレーション
          |
   DigiM_Agent.py          # エージェント呼出
   DigiM_Context.py        # コンテキスト生成・RAGクエリ
   DigiM_Session.py        # セッション・履歴管理
          |
   DigiM_FoundationModel.py  # LLM抽象化レイヤー
   DigiM_Tool.py             # ツール(定義された関数)
          |
[GPT / Gemini / Claude / Grok]
```

エージェントの設定（人格・使用LLM・知識）は `user/common/agent/*.json` で管理し、
コンテキストはプロンプトテンプレート（`user/common/mst/prompt_templates.json`）と
RAG（ChromaDB）を組み合わせて動的に生成します。

## 主要モジュール

| モジュール | 役割 |
|-----------|------|
| `DigiM_Execute.py` | メイン実行エンジン |
| `DigiM_Session.py` | セッション・チャット履歴管理 |
| `DigiM_Context.py` | コンテキスト生成・RAG処理 |
| `DigiM_FoundationModel.py` | LLM抽象化（マルチLLM対応） |
| `DigiM_Agent.py` | エージェント設定管理 |
| `DigiM_Tool.py` | ツール群（分析・履歴操作等） |
| `DigiM_Util.py` | 共通関数 |
| `DigiM_Notion.py` | Notion API連携 |
| `WebDigiMatsuAgent.py` | WebUI画面 |
| `DigiM_API.py` | FastAPI エンドポイント |
| `DigiM_DB_Export.py` | PostgreSQLエクスポート・ベクトル化 |
| `DigiM_VAnalytics.py` | 知識活用分析 |
| `DigiM_GeneCommunication.py` | ユーザーフィードバック |
| `DigiM_GeneUserDialog.py` | ユーザー対話の保存 |

## ディレクトリ構造

```
DigitalMATSUMOTO/
├── user/
│   ├── common/
│   │   ├── agent/          # エージェント設定JSON
│   │   ├── practice/       # プラクティス設定JSON
│   │   ├── mst/            # マスターデータ（ユーザー・RAG・プロンプト等）
│   │   ├── rag/chromadb/   # ベクトルDB（ChromaDB）
│   │   └── csv/            # RAG用CSVデータ
│   ├── session*/           # セッションデータ（チャット履歴）
│   └── archive/            # セッションアーカイブ（ZIP）
├── setting.yaml            # フォルダパス等のシステム設定
├── system.env              # APIキー等の環境変数（要作成）
├── system.env_sample       # 環境変数のテンプレート
├── requirements.txt        # Pythonパッケージ一覧
└── Dockerfile              # Dockerビルド定義
```

## 環境構築・インストレーション

### 前提条件

- Docker がインストール済みであること
- いずれかのLLM APIキーを取得済みであること（OpenAI / Google Gemini / Anthropic Claude / Grok）

### 1. リポジトリの取得

```bash
git clone https://github.com/m07takash/DigitalMATSUMOTO.git
cd DigitalMATSUMOTO
```

### 2. Dockerイメージのビルド

```bash
docker build -t digimatsumoto .
```

ビルドでは以下が自動的にインストールされます：
- Python3 および `requirements.txt` に記載の全パッケージ
- MeCab（日本語形態素解析）+ NEologd辞書
- 日本語フォント（IPAex, Noto CJK）

### 3. コンテナの起動

```bash
docker run -d --name digimatsumoto \
  -p 8501:8501 \
  -p 8900:8900 \
  -v $(pwd):/app/DigitalMATSUMOTO \
  digimatsumoto \
  bash -c "cd /app/DigitalMATSUMOTO && streamlit run WebDigiMatsuAgent.py --server.port 8501"
```

| ポート | 用途 |
|-------|------|
| 8501 | Streamlit WebUI |
| 8900 | FastAPI エンドポイント |

※ポート番号は必要に応じて変更してください。

### 4. 環境変数の設定

`system.env_sample` をコピーして `system.env` を作成し、APIキー等を設定します。

```bash
cp system.env_sample system.env
```

**必須設定：**

| 変数 | 説明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI APIキー（GPTおよびEmbeddingモデルで使用） |

> 使用するLLMに応じて `GEMINI_API_KEY`、`ANTHROPIC_API_KEY`、`XAI_API_KEY` も設定してください。

**基本設定：**

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `TIMEZONE` | `Asia/Tokyo` | タイムゾーン |
| `LOGIN_ENABLE_FLG` | `N` | ログイン認証の有効化（`Y` で有効） |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | 埋め込みベクトルモデル |
| `WEB_TITLE` | `Digital Twin` | WebUIのタイトル |
| `WEB_DEFAULT_AGENT_FILE` | `agent_X0Sample.json` | WebUIのデフォルトエージェント |

**マスターファイル設定：**

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `USER_MST_FILE` | `sample_users.json` | ユーザーマスター |
| `RAG_MST_FILE` | `sample_rags.json` | RAGマスター |
| `PROMPT_TEMPLATE_MST_FILE` | `sample_prompt_templates.json` | プロンプトテンプレート |

**オプション設定（PostgreSQL）：**

分析用DBを使用する場合は以下を設定します（詳細は `SETUP_POSTGRESQL.md` / `SETUP_POSTGRESQL_AZURE.md` を参照）。

| 変数 | 説明 |
|------|------|
| `POSTGRES_HOST` | ホスト名 |
| `POSTGRES_PORT` | ポート番号 |
| `POSTGRES_DB` | データベース名 |
| `POSTGRES_USER` | ユーザーID |
| `POSTGRES_PASSWORD` | パスワード |

**オプション設定（Notion連携）：**

フィードバックやRAGデータの保存先としてNotionを使用する場合に設定します。

| 変数 | 説明 |
|------|------|
| `NOTION_VERSION` | Notion APIバージョン（`2022-06-28`） |
| `NOTION_TOKEN` | Notionインテグレーショントークン |
| `NOTION_MST_FILE` | NotionDB定義ファイル（`sample_notion_db.json`） |

### 5. 動作確認

ブラウザで `http://localhost:8501` にアクセスし、WebUIが表示されれば完了です。

---

## セットアップガイド

### マスターデータの設定

マスターデータは `user/common/mst/` 配下に配置します。`sample_` 付きのファイルがサンプルとして同梱されており、そのままでも動作しますが、通常は以下のようにコピーしてカスタマイズします。

| サンプルファイル | 運用ファイル | 用途 |
|----------------|------------|------|
| `sample_users.json` | `users.json` | ユーザーマスター |
| `sample_rags.json` | `rags.json` | RAGマスター |
| `sample_prompt_templates.json` | `prompt_templates.json` | プロンプトテンプレート |
| `sample_category_map.json` | `category_map.json` | カテゴリ定義 |
| `sample_notion_db.json` | `notion_db.json` | Notion DB定義 |

運用ファイルに切り替えるには `system.env` のマスターファイル設定を変更してください。

```env
USER_MST_FILE=users.json
RAG_MST_FILE=rags.json
PROMPT_TEMPLATE_MST_FILE=prompt_templates.json
```

#### ユーザーマスター

```json
{
  "USER0001": {
    "Name": "表示名",
    "PW": "パスワード",
    "Group": "User",
    "Agent": "agent_X0Sample.json",
    "Allowed": {
      "Session Archive": true,
      "RAG Management": true,
      "Exec Setting": true,
      "RAG Setting": true,
      "Feedback": true,
      "Details": true,
      "Analytics Knowledge": true,
      "Analytics Compare": true,
      "WEB Search": true,
      "Book": true,
      "Download Md": true
    }
  }
}
```

| 項目 | 説明 |
|------|------|
| `Name` | WebUIに表示されるユーザー名 |
| `PW` | パスワード（初回ログイン時にbcryptハッシュ値へ自動変換される） |
| `Group` | ユーザーグループ（後述） |
| `Agent` | デフォルトで使用するエージェントファイル名 |
| `Allowed` | 各機能の表示/非表示を制御（`true`/`false`） |

**パスワードについて：**
- 初回ログイン時にパスワードが平文の場合、自動的にbcryptハッシュ値に変換されて保存されます
- WebUIのログイン画面の「Change Password」タブからパスワードを変更できます

**Groupについて：**
- `"Admin"` を設定すると全ユーザーのチャット履歴を閲覧でき、全エージェントが選択可能になります
- 個別のグループ名（例: `"Sales"`）を設定すると、エージェント側で同じ `GROUP` が設定されたエージェントのみ選択可能になります
- ログイン認証を有効にするには `system.env` で `LOGIN_ENABLE_FLG=Y` を設定してください

#### プロンプトテンプレート

`prompt_templates.json` でプロンプトテンプレートと話し方スタイルを定義します。

- **PROMPT_TEMPLATE**: LLMへの指示の雛形（Normal Template, Chat Template 等）
- **SPEAKING_STYLE**: 口調の設定（丁寧語, 敬語, 武士語 等）

#### カテゴリマップ

`category_map.json` でフィードバックや分析で使用するカテゴリ名と表示色を定義します。

```json
{
  "Category": {
    "AI": "AI",
    "ビジネス": "ビジネス",
    "未設定": "未設定"
  },
  "CategoryColor": {
    "AI": "purple",
    "ビジネス": "blue",
    "未設定": "lightgray"
  }
}
```

### RAGデータの設定

RAGデータの構築は「データの準備」→「RAGマスターの設定」→「ベクトルDB生成」の3ステップです。

#### Step 1: データの準備

**CSVの場合（基本）：**

`user/common/csv/` にCSVファイルを配置します。UTF-8（BOM付き）で作成してください。

| ファイル | 主要カラム | 用途 |
|---------|-----------|------|
| `Sample01_Quote.csv` | speaker, situation, quote | 名言集 |
| `Sample02_Memo.csv` | create_date, memo | メモ |
| `Sample03_Feedback.csv` | emp_code, speaker, create_date, feedback | フィードバック |

**Notionの場合（オプション）：**

`system.env` に以下を設定した上で、`notion_db.json` にNotionデータベースIDを定義します。

```env
NOTION_VERSION=2022-06-28
NOTION_TOKEN=NotionのインテグレーションAPIキー
NOTION_MST_FILE=notion_db.json
```

```json
{
  "データベース名": "NotionデータベースID"
}
```

#### Step 2: RAGマスターの設定

`rags.json` でRAGデータソースを定義します。

**CSVの場合：**

```json
{
  "Sample01_Quote": {
    "active": "Y",
    "input": "csv",
    "data_type": "chromadb",
    "bucket": "Sample01_Quote",
    "data_name": "名言集",
    "file_path": "",
    "file_name": "Sample01_Quote.csv",
    "field_items": ["speaker", "situation", "quote"],
    "title": ["speaker", "quote"],
    "key_text": ["speaker", "situation", "quote"],
    "value_text": ["quote"],
    "category_items": []
  }
}
```

**Notionの場合**

```json
{
  "NotionDB_Name": {
    "active": "Y",
    "input": "notion",
    "data_type": "chromadb",
    "bucket": "NotionDB_Name",
    "data_name": "表示名",
    "item_dict": {"プロパティ名": "内部キー名"},
    "chk_dict": {"確定Chk": true},
    "date_dict": {"タイムスタンプ": "create_date"},
    "category_dict": {"カテゴリ": "category"}
  }
}
```

| 項目 | 説明 |
|------|------|
| `active` | `Y` で有効 |
| `input` | データ取得元（`csv` または `notion`） |
| `data_type` | 保存先（`chromadb`） |
| `bucket` | ChromaDBのコレクション名 |
| `file_name` | CSVファイル名（リストで複数指定可） |
| `field_items` | 使用するCSVカラム |
| `title` | 表示タイトルに使用するフィールド |
| `key_text` | 検索用テキスト（Embeddingインデックスに使用） |
| `value_text` | 参照用テキスト（回答生成時に参照） |
| `category_items` | カテゴリフィルタ条件（後述） |

**category_items によるデータのフィルタリング：**

`category_items` を指定すると、対象CSVデータの特定カラムの値でフィルタリングができます。複数条件はAND条件として適用されます。

```json
"category_items": [
  {"RAG_Category": ["memo"]},
  {"category": ["Feedback"]}
]
```

上記の場合、`RAG_Category` カラムが `"memo"` かつ `category` カラムが `"Feedback"` のレコードのみがRAGに登録されます。

#### Step 3: ベクトルDBの生成

WebUIのサイドバー **RAG** セクションから「**Update RAG Data**」ボタンを実行すると、データが読み込まれ ChromaDB にベクトルデータが生成されます。

> 初回実行時は全件のベクトル化が行われます。2回目以降は、`title` / `key_text` / `value_text` に変更があるデータのみ再ベクトル化され、それ以外のフィールド変更はメタデータのみ更新されます。

### エージェントの設定

`user/common/agent/` 配下にエージェント定義JSONを配置します。`agent_X0Sample.json` をコピーしてカスタマイズするのが推奨です。

#### PERSONALITY（性格設定）

エージェントの人格を定義します。

```json
"PERSONALITY": {
  "SEX": "女性",
  "BIRTHDAY": "01-Jan-1980",
  "IS_ALIVE": true,
  "NATIONALITY": "Japanese",
  "LANGUAGE": "日本語",
  "SPEAKING_STYLE": "Polite",
  "CHARACTER": "Sample.txt",
  "Openness": 0.7,
  "Conscientiousness": 0.7,
  "Extraversion": 0.7,
  "Agreeableness": 0.7,
  "Neuroticism": 0.2
}
```

| 項目 | 説明 |
|------|------|
| `SPEAKING_STYLE` | プロンプトテンプレートの `SPEAKING_STYLE` に定義された口調を指定 |
| `CHARACTER` | `user/common/agent/character/` 配下のテキストファイル。経歴・価値観・一人称等の詳細な人格定義を記述 |
| Big Five特性 | `Openness`（開放性）/ `Conscientiousness`（誠実性）/ `Extraversion`（外向性）/ `Agreeableness`（協調性）/ `Neuroticism`（神経症傾向）を 0.0〜1.0 で設定 |

#### ENGINE（LLMエンジン設定）

**LLM（テキスト生成）：**

```json
"ENGINE": {
  "LLM": {
    "DEFAULT": "GPT-4.1-mini",
    "GPT-4.1-mini": {
      "MODEL": "gpt-4.1-mini",
      "API": "OpenAI",
      "FUNC": "generate_response_T_gpt"
    }
  }
}
```

`DEFAULT` に指定したキー名のモデルが使用されます。WebUIからも切り替え可能です。

| API | FUNC | 対応モデル例 |
|-----|------|------------|
| OpenAI | `generate_response_T_gpt` | GPT-4.1, GPT-4.1-mini 等 |
| Google | `generate_response_T_gemini` | Gemini-2.5-Flash, Gemini-3.1 等 |
| Anthropic | `generate_response_T_claude` | Claude-Sonnet-4.5, Claude-Haiku 等 |
| XAI | `generate_response_T_grok` | Grok-4 等 |

**IMAGEGEN（画像生成）：**

```json
"IMAGEGEN": {
  "DEFAULT": "GPT-Image",
  "GPT-Image": {
    "NAME": "GPT-Image-1",
    "FUNC_NAME": "generate_image_dalle",
    "MODEL": "gpt-image-1",
    "PARAMETER": {"size": "1024x1024", "quality": "high"}
  },
  "nano-banana-2": {
    "NAME": "nano-banana-2",
    "FUNC_NAME": "generate_image_gemini",
    "MODEL": "gemini-3.1-flash-image-preview",
    "PARAMETER": {"aspect_ratio": "1:1"}
  }
}
```

| FUNC_NAME | 説明 |
|-----------|------|
| `generate_image_dalle` | OpenAI DALL-E による画像生成 |
| `generate_image_gemini` | Google Gemini による画像生成 |

#### HABIT（振る舞いの切り替え）

ユーザーの入力に特定のトリガーワード（`MAGIC_WORD`）が含まれると、対応するプラクティス（処理パイプライン）に切り替わります。

```json
"HABIT": {
  "DEFAULT": {
    "MAGIC_WORD": [""],
    "PRACTICE": "practice_00Default.json"
  },
  "Chat": {
    "MAGIC_WORD": ["簡潔に回答して", "簡潔に答えて"],
    "PRACTICE": "practice_01Chat.json"
  },
  "SENRYU_SENSEI": {
    "MAGIC_WORD": ["川柳を詠んでください。"],
    "PRACTICE": "practice_05Senryu.json",
    "KNOWLEDGE": [
      {
        "NAME": "Quote",
        "RAG_DATA": [{"DATA_NAME": "Sample01_Quote", "BUCKET": "Sample01_Quote"}],
        "TEXT_LIMITS": 1000,
        "DISTANCE_LOGIC": "Cosine"
      }
    ]
  }
}
```

- `MAGIC_WORD`: トリガーワードのリスト（空文字はデフォルト動作）
- `PRACTICE`: 実行するプラクティスファイル
- `KNOWLEDGE`: **HABITごとに固有のRAGデータソースを設定可能**。指定するとそのHABIT発動時のみ該当RAGを参照します

#### KNOWLEDGE（知識設定）

通常の対話で参照するRAGデータソースを定義します。

```json
"KNOWLEDGE": [
  {
    "NAME": "Experience",
    "RAG_DATA": [
      {"DATA_NAME": "Sample02_Memo", "BUCKET": "Sample02_Memo"},
      {"DATA_NAME": "Sample03_Feedback", "BUCKET": "Sample03_Feedback"}
    ],
    "TEXT_LIMITS": 2000,
    "DISTANCE_LOGIC": "Cosine"
  }
]
```

- `RAG_DATA`: 参照するRAGデータソース（RAGマスターの `bucket` と対応）。複数指定可
- `TEXT_LIMITS`: コンテキストに含める最大文字数
- `DISTANCE_LOGIC`: 類似度計算方式（`Cosine`）

#### COMMUNICATION（フィードバック設定）

会話履歴に対するフィードバックの保存先と形式を定義します。

```json
"COMMUNICATION": {
  "ACTIVE": "Y",
  "SAVE_MODE": "CSV",
  "SAVE_DB": "Sample00_Communication",
  "DEFAULT_CATEGORY": "未設定",
  "FEEDBACK_ITEM_LIST": ["memo", "comment"],
  "FIELD_MAP": [
    {"key": "title",      "name": "title",      "type": "title"},
    {"key": "category",   "name": "category",   "type": "category"},
    {"key": "memo",       "name": "memo",       "type": "text"},
    {"key": "seq",        "name": "seq",        "type": "number"},
    {"key": "create_date","name": "create_date", "type": "date"}
  ]
}
```

| 項目 | 説明 |
|------|------|
| `ACTIVE` | `Y` でフィードバック機能を有効化 |
| `SAVE_MODE` | 保存先（`CSV` または `Notion`） |
| `SAVE_DB` | CSVファイル名 / NotionデータベースID のキー名 |
| `DEFAULT_CATEGORY` | WebUIのカテゴリ選択のデフォルト値 |
| `FEEDBACK_ITEM_LIST` | フィードバック項目のリスト |
| `FIELD_MAP` | 保存フィールドの定義（`key`: 内部キー、`name`: CSV列名、`type`: データ型） |

**FIELD_MAPのデータ型：**

| type | CSV | Notion |
|------|-----|--------|
| `title` | 先頭列 | ページタイトル |
| `text` | 文字列 | `update_notion_rich_text_content` |
| `number` | 文字列 | `update_notion_num` |
| `date` | 日付変換（YYYY/MM/DD） | `update_notion_date` |
| `category` | 文字列 | `update_notion_select` |
| `checkbox` | 文字列 | `update_notion_chk` |

Notion保存時は `notion_name` でプロパティ名を個別に指定できます。また、`default` を指定するとデータに依存しない固定値を設定できます。

```json
{"key": "input_class", "name": "input_class", "notion_name": "入力分類", "type": "category", "default": "Feedback"},
{"key": "confirmed",   "name": "confirmed",   "notion_name": "確定Chk",  "type": "checkbox", "default": true}
```

#### SUPPORT_AGENT（補助エージェント）

メインの対話をサポートする補助エージェントを指定します。各補助エージェントは独立したエージェントJSONとして定義されており、カスタマイズ可能です。

```json
"SUPPORT_AGENT": {
  "DIALOG_DIGEST": "agent_51DialogDigest.json",
  "ART_CRITICS": "agent_52ArtCritic.json",
  "EXTRACT_DATE": "agent_55ExtractDate.json",
  "RAG_QUERY_GENERATOR": "agent_56RAGQueryGenerator.json"
}
```

| エージェント名 | 役割 |
|------|------|
| `DIALOG_DIGEST` | 会話履歴のダイジェスト（要約）を生成 |
| `ART_CRITICS` | 画像生成後の解説・批評を生成 |
| `EXTRACT_DATE` | ユーザー入力から日付情報を抽出（RAGのメタデータ検索に使用） |
| `RAG_QUERY_GENERATOR` | ユーザー入力からRAG検索用の補助クエリを生成 |

#### BOOK（参考情報）

エージェントが「知っている本や名言」としてRAGデータから情報を取得し、WebUIの Book セクションに表示します。

```json
"BOOK": [
  {
    "RAG_NAME": "Quote",
    "RAG_DATA": [{"DATA_NAME": "Sample01_Quote", "BUCKET": "Sample01_Quote"}],
    "HEADER_TEMPLATE": "以下はあなたが気に入っている著名人による名言です。\n",
    "CHUNK_TEMPLATE": "・{speaker}「{value_text}」\n\n",
    "TEXT_LIMITS": 1000,
    "DISTANCE_LOGIC": "Cosine"
  }
]
```

`HEADER_TEMPLATE` と `CHUNK_TEMPLATE` でRAGデータの表示フォーマットをカスタマイズできます。`{フィールド名}` でRAGデータの値を埋め込めます。

### プラクティスの設定

プラクティスはエージェントの処理パイプラインを定義するJSONファイルです。`user/common/practice/` 配下に配置します。

#### 基本構造

```json
{
  "NAME": "Default",
  "CHAIN": [
    {
      "TYPE": "LLM",
      "AGENT_FILE": "USER",
      "OVERWRITE_ITEMS": "USER",
      "ADD_KNOWLEDGE": ["USER"],
      "PROMPT_TEMPLATE": "Normal Template",
      "MEMORY_USE": true
    }
  ]
}
```

| 項目 | 説明 |
|------|------|
| `NAME` | プラクティス名 |
| `CHAIN` | 実行ステップのリスト（順番に実行される） |

#### CHAINの各ステップ

| 項目 | 説明 |
|------|------|
| `TYPE` | 実行タイプ（`LLM` / `IMAGEGEN` / `FUNC`） |
| `AGENT_FILE` | 使用するエージェント（`USER` で呼び出し元エージェントを使用、ファイル名で別エージェントを指定） |
| `OVERWRITE_ITEMS` | エンジン設定の上書き（`USER` でユーザー設定を継承、`{}` で上書きなし） |
| `ADD_KNOWLEDGE` | 追加の知識ソース（`["USER"]` でユーザーエージェントのKNOWLEDGEを使用） |
| `PROMPT_TEMPLATE` | 使用するプロンプトテンプレート名 |
| `MEMORY_USE` | 過去の会話履歴をコンテキストに含めるか |
| `USER_INPUT` | 入力テキストの固定値（指定するとユーザー入力の代わりに使用） |
| `CONTENTS` | 前ステップの出力を参照（`EXPORT_1` で1つ目のステップの出力） |
| `SITUATION` | 状況情報の設定 |

#### マルチステップの例（画像生成 + 批評）

```json
{
  "NAME": "ImageGen",
  "CHAIN": [
    {
      "TYPE": "IMAGEGEN",
      "AGENT_FILE": "USER",
      "PROMPT_TEMPLATE": "Image Gen",
      "MEMORY_USE": true
    },
    {
      "TYPE": "LLM",
      "AGENT_FILE": "agent_52ArtCritic.json",
      "PROMPT_TEMPLATE": "Art Critic",
      "USER_INPUT": "コンテンツについて、これまでの話と関連付けながら300文字程度で解説してください。",
      "CONTENTS": "EXPORT_1",
      "MEMORY_USE": true
    }
  ]
}
```

この例では、1つ目のステップで画像を生成し、2つ目のステップで別のエージェント（ArtCritic）がその画像を批評します。`CONTENTS: "EXPORT_1"` により、1つ目の出力が2つ目の入力として設定されます。

### 起動方法

```bash
# WebUI（Streamlit）
streamlit run WebDigiMatsuAgent.py --server.port 8501

# API（FastAPI）
python DigiM_API.py
```
