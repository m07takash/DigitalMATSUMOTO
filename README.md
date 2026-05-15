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
- [機能一覧（概念レベル）](docs/FEATURE_LIST.md)

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
| `DigiM_Agent.py` | エージェント設定管理（テンプレート + persona上書き対応） |
| `DigiM_AgentPersona.py` | エージェントペルソナのマスタ（Excel/RDB） |
| `DigiM_Auth.py` | ログインユーザーマスタ（JSON / RDB バックエンド切替） |
| `DigiM_Tool.py` | ツール群（分析・履歴操作・ペルソナ統合等） |
| `DigiM_Util.py` | 共通関数 |
| `DigiM_Notion.py` | Notion API連携 |
| `WebDigiMatsuAgent.py` | WebUI画面 |
| `DigiM_API.py` | FastAPI エンドポイント |
| `DigiM_DB_Export.py` | PostgreSQLエクスポート・ベクトル化 |
| `DigiM_VAnalytics.py` | 知識活用分析 |
| `DigiM_GeneFeedback.py` | ユーザーフィードバック（CSV/Notion保存） |
| `DigiM_UserMemory.py` | ユーザーメモリ（History/Nowaday/Persona）のストレージ抽象化（Excel/Notion/RDB） |
| `DigiM_UserMemorySetting.py` | ユーザーメモリのOn/Off2階層解決（ユーザーマスタ/システム）。Layersは `users.json` の `Allowed["User Memory Layers"]` に保存 |
| `DigiM_UserMemoryBuilder.py` | 「対話相手についての情報」コンテキスト合成（Knowledgeより前にプロンプト挿入）。HistoryはMeCab×タグ×時間ハイブリッド検索 |
| `DigiM_Scheduler.py` | バックグラウンドスケジューラ（APScheduler / 複数ジョブ対応 / 再起動なしReload可能） |
| `DigiM_ScheduledJobs.py` | スケジュールジョブのマスタCRUD（`user/common/mst/scheduled_jobs.json`の読み書き・実行結果記録） |
| `DigiM_GeneUserMemory.py` | ユーザーメモリの生成・差分マージ・自動承認・検証ループ更新・既存レコードへの感情/Big5バックフィル（CLI付き） |
| `DigiM_GeneUserDialog.py` | （Deprecated）旧ユーザー対話保存。`DigiM_GeneUserMemory.py` への後方互換シム |
| `DigiM_SupportEval.py` | サポートエージェントのパフォーマンス評価 |
| `DigiM_Benchmark.py` | サポートエージェントの速度・出力比較ベンチマーク（CLI） |
| `DigiM_JobRegistry.py` | バックグラウンドスレッドの登録・キャンセル（UIからの停止用） |
| `DigiM_UrlFetch.py` | チャット入力中のhttp(s)リンク自動取得（サブページクロール対応） |

## ディレクトリ構造

```
DigitalMATSUMOTO/
├── user/
│   ├── common/
│   │   ├── agent/                # エージェント設定JSON
│   │   ├── agent/persona_data/   # エージェントペルソナのxlsx（複数ペルソナ並列実行用）
│   │   ├── practice/             # プラクティス設定JSON
│   │   ├── mst/                  # マスターデータ（ユーザー・RAG・プロンプト等）
│   │   ├── rag/chromadb/         # ベクトルDB（ChromaDB）
│   │   ├── rag/pages/            # ページインデックスRAG（.md + _index.json）
│   │   ├── csv/                  # RAG用CSVデータ
│   │   ├── csv/pageindex/        # Excel入力のページインデックス（Excel + 個別本文ファイル）
│   │   ├── analytics/rag_explorer/ # RAG Explorer の保存セッション
│   │   ├── user_memory/          # ユーザーメモリ（history/nowaday/persona.xlsx 等の保存先）
│   │   └── temp/                 # チャット添付・URL取得等の一時ファイル
│   ├── session*/                 # セッションデータ（チャット履歴）
│   └── archive/                  # セッションアーカイブ（ZIP）
├── test/                         # ベンチマーク・評価入出力（questions.xlsx 等）
├── setting.yaml                  # フォルダパス等のシステム設定
├── system.env                    # APIキー等の環境変数（要作成）
├── system.env_sample             # 環境変数のテンプレート
├── requirements.txt              # Pythonパッケージ一覧
└── Dockerfile                    # Dockerビルド定義
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
  -p 8899:8899 \
  -v $(pwd):/app/DigitalMATSUMOTO \
  digimatsumoto \
  bash -c "cd /app/DigitalMATSUMOTO && streamlit run WebDigiMatsuAgent.py --server.port 8501"
```

| ポート | 用途 |
|-------|------|
| 8501 | Streamlit WebUI |
| 8899 | FastAPI エンドポイント |

※ポート番号は必要に応じて変更してください。

複数サービス（WebUI + FastAPI）をまとめて起動したい場合は、`startup.sh_sample` を `startup.sh` にコピーして使ってください（`startup.sh` は環境依存のため `.gitignore` 済み）。サンプルは `WebDigiMatsuAgent.py`（標準WebUI）+ FastAPI を起動します。

```bash
cp startup.sh_sample startup.sh   # 必要に応じて編集
bash startup.sh
```

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
| `LOGIN_AUTH_METHOD` | `JSON` | ログイン認証方法。`JSON`: `USER_MST_FILE`を使用 / `RDB`: PostgreSQLの`digim_users`テーブルを使用（テーブルは初回アクセス時に自動作成） |
| `AGENT_PERSONA_SOURCE` | `EXCEL` | エージェントペルソナのソース。`EXCEL`: `user/common/agent/persona_data/`配下のxlsx / `RDB`: `digim_agent_personas`テーブル / `BOTH`: マージ |
| `USER_MEMORY_HISTORY_BACKEND` / `NOWADAY_BACKEND` / `PERSONA_BACKEND` | `EXCEL` | ユーザーメモリ各層の保存先（EXCEL/NOTION/RDB）。詳細は「ユーザーメモリ（階層的ユーザー理解）」を参照 |
| `USER_MEMORY_DEFAULT_LAYERS` | `persona,nowaday,history` | ユーザーメモリのシステムデフォルト有効層（空文字 `""` で全Off） |
| `USER_MEMORY_AUTO_APPROVE_THRESHOLD` | `0.8` | Persona項目をconfidenceで自動承認する閾値 |
| `USER_MEMORY_PERSONA_MAX_CHARS_PER_FIELD` | `300` | Persona各フィールドの保持文字数上限 |
| `USER_MEMORY_HISTORY_MAX_CHARS` | `800` | Historyメモリ注入の合計文字数上限 |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | 埋め込みベクトルモデル |
| `WEB_TITLE` | `Digital Twin` | WebUIのタイトル |
| `WEB_DEFAULT_AGENT_FILE` | `agent_X0Sample.json` | WebUIのデフォルトエージェント |
| `WEB_MAX_UPLOAD_SIZE` | `500` | ファイルアップロード上限（MB） |

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

**オプション設定（Azure OpenAI Service）：**

Azure 上の gpt-* / dall-e / gpt-image-* 等のデプロイをチャット・画像生成エンジンとして使う場合、および埋め込みベクトル化を Azure 経由で行う場合に設定します。

| 変数 | 説明 |
|------|------|
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI リソースのエンドポイントURL |
| `AZURE_OPENAI_API_KEY` | APIキー |
| `AZURE_OPENAI_API_VERSION` | チャット/画像エンジン用APIバージョン（既定 `2024-10-21`）。エージェント単位の上書きは `PARAMETER.api_version` |
| `AZURE_OPENAI_EMBED_MODEL` | 埋め込み用デプロイ名（PostgreSQLベクトル化で使用） |

エージェントJSONの `ENGINE.LLM` で `FUNC_NAME: "generate_response_T_azure_openai"`、`ENGINE.IMAGEGEN` で `"generate_image_azure_dalle"` を指定。`MODEL` には**Azure上のデプロイ名**を入れます。

### 5. 動作確認

ブラウザで `http://localhost:8501` にアクセスし、WebUIが表示されれば完了です。

### 6. Nginx リバースプロキシの設定（本番環境向け）

HTTPS対応やドメイン運用を行う場合、Nginxをリバースプロキシとして配置します。以下はAzure VM + Let's Encrypt での構成例です。

#### グローバル設定（`/etc/nginx/nginx.conf`）

`http` ブロック内に以下を追加します。ファイルアップロード（PPTX/PDF等）でエラー（413）が出る場合はこの設定が必要です。

```nginx
http {
    client_max_body_size 500m;  # デフォルト: 1m
    ...
}
```

#### サイト設定（`/etc/nginx/sites-available/your-site`）

```nginx
# HTTP → HTTPS リダイレクト
server {
    listen 80;
    server_name your-domain.example.com;

    # Let's Encrypt 証明書更新用
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS メインサイト
server {
    listen 443 ssl;
    server_name your-domain.example.com;

    ssl_certificate     /etc/letsencrypt/live/your-domain.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.example.com/privkey.pem;

    # Streamlit WebUI
    location / {
        proxy_pass http://127.0.0.1:8501/;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_connect_timeout 10s;

        # WebSocket対応（Streamlit必須）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # FastAPI
    location /api/ {
        proxy_pass http://127.0.0.1:8899/;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_connect_timeout 10s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

#### 有効化とリロード

```bash
# サイト設定を有効化
sudo ln -s /etc/nginx/sites-available/your-site /etc/nginx/sites-enabled/

# 構文チェック
sudo nginx -t

# リロード
sudo systemctl reload nginx
```

> **WebSocket対応について：** StreamlitはWebSocketで通信するため、`proxy_http_version 1.1` と `Upgrade` / `Connection` ヘッダーの設定が必須です。これがないとWebUIが正常に動作しません。

> **タイムアウトについて：** LLM実行は数十秒〜数分かかることがあるため、`proxy_read_timeout` / `proxy_send_timeout` を十分な値（300s以上）に設定してください。

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
    "Group": ["User"],
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
      "Download Md": true,
      "RAG Explorer": true,
      "Scheduler": false,
      "User Memory": true,
      "User Memory Layers": ["persona", "nowaday", "history"]
    }
  }
}
```

| 項目 | 説明 |
|------|------|
| `Name` | WebUIに表示されるユーザー名 |
| `PW` | パスワード（初回ログイン時にbcryptハッシュ値へ自動変換される） |
| `Group` | ユーザーグループ（配列。後述） |
| `Agent` | デフォルトで使用するエージェントファイル名 |
| `Allowed` | 各機能の表示/非表示を制御（`true`/`false`） |

**Allowedの設定項目：**

| キー | 説明 |
|------|------|
| `Session Archive` | セッションアーカイブ機能 |
| `RAG Management` | RAGデータ管理（Update RAG Data等） |
| `Exec Setting` | 実行設定の表示・変更 |
| `RAG Setting` | RAG設定の表示・変更 |
| `Feedback` | フィードバック機能 |
| `Details` | 詳細情報の表示 |
| `Analytics Knowledge` | 知識活用分析 |
| `Analytics Compare` | エージェント比較分析 |
| `WEB Search` | Web検索機能 |
| `Book` | Book（参考情報）機能 |
| `Download Md` | Markdownダウンロード |
| `RAG Explorer` | RAGデータ分析画面（後述） |
| `Scheduler` | スケジュール管理画面（バックグラウンドジョブの登録・編集・即時実行） |
| `User Memory` | ユーザーメモリ（階層的ユーザー理解）の表示・保存・検証ループ |
| `User Memory Layers` | （bool以外。配列）このユーザーが有効化する層 `["persona","nowaday","history"]` のサブセット。未設定なら `USER_MEMORY_DEFAULT_LAYERS` |

> Adminグループのユーザーは `Allowed` の設定に関わらず全機能にアクセスできます。

**パスワードについて：**
- 初回ログイン時にパスワードが平文の場合、自動的にbcryptハッシュ値に変換されて保存されます
- WebUIのログイン画面の「Change Password」タブからパスワードを変更できます

**Groupについて：**
- 配列形式（例: `["User"]`、`["Sales", "Marketing"]`）で**複数グループを指定可能**。後方互換のため文字列も受け付けます（内部で配列に正規化）
- 配列のいずれかが `"Admin"` の場合、全ユーザーのチャット履歴を閲覧でき、全エージェントが選択可能になります
- 個別のグループ名を設定すると、エージェント側で同じ `GROUP` が設定されたエージェントのみ選択可能になります（**OR一致**: 自分のグループのいずれかと一致するエージェントが対象）
- ログイン認証を有効にするには `system.env` で `LOGIN_ENABLE_FLG=Y` を設定してください
- 認証ソースをPostgreSQLに切り替える場合は `LOGIN_AUTH_METHOD=RDB` を設定。`digim_users` テーブルが自動作成されます（カラム: `user_id`/`name`/`pw`/`group_cd[JSONB]`/`agent`/`allowed[JSONB]`）

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

**Private Mode（RAGデータの公開制御）：**

RAGデータに `private` フラグを設定できます。`private: true` のデータは、実行時に Private Mode が有効な場合に検索対象から除外されます。

**Notionの場合** — `item_dict` にプロパティを指定:

```json
"item_dict": {
  "db": "DigiMATSU_Identity_Memo",
  "title": {"名前": "title"},
  "private": {"非公開": "chk"}
}
```

上記の場合、Notionの「非公開」チェックボックスプロパティの値（`true`/`false`）がそのままRAGデータの `private` フラグになります。

固定値を設定する場合（全レコードを非公開にしない）:

```json
"private": false
```

**CSVの場合** — `field_items` に `"private"` 列を追加:

```json
"field_items": ["speaker", "situation", "quote", "private"]
```

CSV内の `private` 列に `True` / `False` を記載します。

> `private` フラグが未設定のデータは自動的に `false`（公開）として扱われます。既存データへの影響はありません。

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

> **Private Mode の利用：** WebUIのチャット入力欄付近にある「Private Mode」チェックボックスをONにすると、`private: true` が設定されたRAGデータが検索対象から除外されます。APIからは `"private_mode": true` パラメータで制御できます。既存データに一括で `private: false` を付与するマイグレーションは以下のコマンドで実行できます:
>
> ```python
> import DigiM_Context as dmc
> dmc.migrate_add_private_flag()
> ```

#### ページインデックスRAG（pageindex型）

ベクトル検索ではなく、LLMがページ一覧から関連ページを選択する方式のRAGです。構造化されたドキュメント（システムガイド、ノウハウ集等）に向いています。

**rags.json での定義例（Notionから取り込む場合）：**

```json
{
  "AIUCStandard": {
    "active": "Y",
    "input": "notion",
    "data_type": "pageindex",
    "data_name": "DigiMATSU_Book",
    "bucket": "AIUCStandard",
    "item_dict": {
      "book": {"ブック名": "select"},
      "id": {"ID": "rich_text"},
      "title": {"タイトル": "rich_text"},
      "create_date": {"タイムスタンプ": "date"},
      "category": {"カテゴリ": "select"},
      "summary": {"サマリー": "rich_text"},
      "tags": {"タグ": "multi_select"},
      "url": ""
    },
    "chk_dict": {
      "確定Chk": true,
      "ブック名": "AIプロダクト「基本の型」",
      "RAGChk": false
    },
    "date_dict": {},
    "category_dict": {},
    "fin_flg": {
      "RAGChk": true
    }
  }
}
```

| item_dictキー | `_index.json` への反映先 |
|---------------|-------------------------|
| `book` | `BOOK.title`（ブック名） |
| `id` | `PAGES[].id`（同時に `{id}.md` のファイル名） |
| `title` | `PAGES[].title` |
| `create_date` | `PAGES[].timestamp` |
| `summary` | `PAGES[].summary` |
| `tags`（multi_select） | `PAGES[].tags`（配列） |
| `category` | `PAGES[].category` |

| chk_dictの値型 | Notion側のフィルタ |
|---------------|--------------------|
| `true` / `false` | checkboxプロパティ |
| 文字列 | selectプロパティ（`equals` 一致） |

「Update RAG Data」を実行すると、`user/common/rag/pages/{bucket}/` 配下に各ページの `.md` ファイル（Notionページ本文がMarkdown風に変換されて格納）と `_index.json`（ページインデックス）が自動生成されます。

- `id` が重複する場合は上書き更新
- `sort_order` は `id` から動的に算出（例: `"1-0"→100`, `"1-2-3"→10203`）
- 登録完了後は `fin_flg` で指定したNotionプロパティ（例: `RAGChk`）を `true` に更新

ページデータを手動で配置する場合は、以下の構造で作成します：

```
user/common/rag/pages/SampleConsultingBook/
├── _index.json    # BOOK + PAGES一覧
├── 1-0.md         # 各ページの本文
├── 1-1.md
└── ...
```

`_index.json` の構造：

```json
{
  "BOOK": {
    "title": "コンサルティングノウハウ"
  },
  "PAGES": [
    {
      "id": "1-1",
      "title": "外部環境分析（PEST・5Forces）",
      "timestamp": "2026-04-01",
      "summary": "マクロ環境をPEST分析、業界構造を5Forces分析で把握する手法",
      "tags": ["戦略", "PEST", "5Forces"],
      "category": "戦略立案",
      "sort_order": 101
    }
  ]
}
```

エージェントのBOOKに `"RETRIEVER": "PageIndex"` で設定すると、WebUIのBOOKセクションから選択できます（詳細はBOOKの項を参照）。

##### Excelソースからのページインデックス生成

Notion以外に、Excelファイル（1行=1ページ）からもページインデックスを生成できます。`source_dir` 配下にExcelと本文用テキストファイル（`.txt`/`.md`）を一緒に格納する形です。

```json
{
  "SampleConsultingBookExcel": {
    "active": "Y",
    "input": "excel",
    "data_type": "pageindex",
    "data_name": "SampleConsultingBookExcel",
    "bucket": "SampleConsultingBookExcel",
    "source_dir": "user/common/csv/pageindex/SampleConsultingBookExcel",
    "source_file": "SampleConsultingBookExcel.xlsx",
    "sheet": "pages",
    "item_dict": {
      "book": "ブック名",
      "id": "ID",
      "title": "タイトル",
      "summary": "サマリー",
      "tags": "タグ",
      "category": "カテゴリ",
      "body": "本文"
    }
  }
}
```

- `item_dict` の値は **Excelの列名**。`book`/`id`/`title`/`summary`/`tags`/`category`/`body` の各キーに列名を割り当てる
- `tags` 列はカンマ（`,`）または縦棒（`|`）区切りの文字列を配列に変換
- **`body` セルの解決ロジック**：
  - セル値が `source_dir` 配下に存在する `.txt`/`.md` ファイル名と一致 → そのファイル本文を取り込む
  - 一致しなければ → セル値自体を本文として使用（短文向け）
  - パストラバーサル防止のため、区切り文字（`/`/`\\`/`..`）を含む値はインライン扱い

フォルダ構成例：
```
user/common/csv/pageindex/SampleConsultingBookExcel/
├── SampleConsultingBookExcel.xlsx   # 1行1ページのインデックス
├── 1-1.txt                          # body列に "1-1.txt" と書かれていれば参照
├── 1-2.txt
├── 2-2.md
└── ...
```

「Update RAG Data」を実行すると、`user/common/rag/pages/{bucket}/` に `_index.json` と各ページの `.md` が生成されます（Notion由来と同じ出力形式）。

##### ページインデックスのローカルダウンロード（Page Index Export）

WebUIのサイドバー **RAG Management → Page Index Export** から、既存のページインデックス（Notion由来・Excel由来問わず）を **Excel + 個別.mdファイルのZIP** としてダウンロードできます。

- 出力Excelの書式は `input: "excel"` のインポート互換（`body` 列はファイル名参照）
- ZIP内構造: `{bucket}/{bucket}.xlsx` + `{bucket}/{id}.md`
- ローカルでExcel編集 → `user/common/csv/pageindex/{bucket}/` に展開し直して再インポート、というオフライン編集ワークフローに使える

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
| `CHARACTER` | `user/common/agent/character/` 配下のテキストファイル（**`.txt` または `.md`**）または直接記述。経歴・価値観・一人称等の詳細な人格定義 |
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
| **Azure OpenAI** | `generate_response_T_azure_openai` | Azure上のgpt-*デプロイ（`MODEL`にデプロイ名を指定） |

**Azure OpenAI Service の利用**

`system.env` に `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_API_VERSION`（既定 `2024-10-21`）を設定。エージェントJSONの`MODEL`はAzure上のdeployment名を入れます。`PARAMETER.api_version`で**エンジン単位の上書き**（例: gpt-5系のみ新版APIを使う）も可能:

```json
"GPT-Azure": {
  "NAME": "GPT-Azure",
  "FUNC_NAME": "generate_response_T_azure_openai",
  "MODEL": "my-gpt5-deployment",
  "PARAMETER": {"api_version": "2025-04-01-preview"},
  "TOKENIZER": "tiktoken",
  "MEMORY": {"limit": 10000, "role": "both", ...}
}
```

画像生成も同様に `generate_image_azure_dalle` で Azure 上の `gpt-image-1`/`dall-e-3` deployment を使えます。

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
  },
  "GPT-Image-Azure": {
    "NAME": "GPT-Image-Azure",
    "FUNC_NAME": "generate_image_azure_dalle",
    "MODEL": "gpt-image-1",
    "PARAMETER": {"size": "1024x1024", "quality": "high"}
  }
}
```

| FUNC_NAME | 説明 |
|-----------|------|
| `generate_image_dalle` | OpenAI DALL-E による画像生成 |
| `generate_image_gemini` | Google Gemini による画像生成 |
| `generate_image_azure_dalle` | Azure OpenAI Service 上の dall-e/gpt-image デプロイ |

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

#### FEEDBACK（フィードバック設定）

会話履歴に対するフィードバックの保存先と形式を定義します。

```json
"FEEDBACK": {
  "ACTIVE": "Y",
  "SAVE_MODE": "CSV",
  "SAVE_DB": "Sample00_Feedback",
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
  "RAG_QUERY_GENERATOR": "agent_56RAGQueryGenerator.json",
  "THINKING": "agent_59Thinking.json"
}
```

| エージェント名 | 役割 |
|------|------|
| `DIALOG_DIGEST` | 会話履歴のダイジェスト（要約）を生成 |
| `ART_CRITICS` | 画像生成後の解説・批評を生成 |
| `EXTRACT_DATE` | ユーザー入力から日付情報を抽出（RAGのメタデータ検索に使用） |
| `RAG_QUERY_GENERATOR` | ユーザー入力からRAG検索用の補助クエリを生成 |
| `THINKING` | ユーザーの質問を分析し、Habit選択・Web検索・RAGクエリ生成・Book追加を動的に判定（Thinking Mode有効時） |

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

**PageIndex型 BOOK（ページインデックス検索）：**

ベクトル検索ではなく、LLMがページインデックスから関連ページを選択してコンテキストに注入する方式です。構造化されたドキュメント（システムガイド等）に向いています。

```json
"BOOK": [
  {
    "RAG_NAME": "SystemGuide",
    "RETRIEVER": "PageIndex",
    "DATA": [
      {
        "DATA_TYPE": "PAGE_INDEX",
        "DATA_NAME": "DigiMPGSystemGuide",
        "SUPPORT_AGENT": "agent_59PageIndexSearch.json"
      }
    ],
    "HEADER_TEMPLATE": "【システムガイド】以下はシステムに関する技術情報です。\n",
    "LOG_TEMPLATE": "'rag':'{rag_name}', 'page_id':'{page_id}', 'title':'{title}', 'category':'{category}', 'summary':'{summary}'",
    "TEXT_LIMITS": 6000,
    "MAX_PAGES": 5,
    "DISTANCE_LOGIC": "PageIndex"
  }
]
```

| 項目 | 説明 |
|------|------|
| `RETRIEVER` | `PageIndex` を指定 |
| `DATA_TYPE` | `PAGE_INDEX` を指定 |
| `DATA_NAME` | `user/common/rag/pages/` 配下のフォルダ名 |
| `SUPPORT_AGENT` | ページ選択に使うLLMエージェント |
| `LOG_TEMPLATE` | Detail Informationに表示するログ形式。`{rag_name}`, `{page_id}`, `{title}`, `{category}`, `{summary}` が使用可能 |
| `MAX_PAGES` | 1クエリで選択する最大ページ数 |

ページデータは `user/common/rag/pages/{DATA_NAME}/` 配下に `_index.json`（ページ一覧）と各ページの `.md` ファイルを配置します。Notion連携で `rags.json` に `"data_type": "pageindex"` を定義すると、「Update RAG Data」で自動生成されます（詳細は「ページインデックスRAG（pageindex型）」の項を参照）。

#### ORG / Persona（複数ペルソナ並列実行）

1つのテンプレートエージェントに対して、PostgreSQL（`digim_agent_personas`）またはExcel（`user/common/agent/persona_data/`）で **複数ペルソナ** を登録し、ORGで切り替えてWebUI／プラクティスから並列実行できます。

**エージェントJSONへの追加項目**:
```json
"ORG": [
  {"company": "デジMラボ"},
  {"company": "デジMラボ", "dept": "Consulting"},
  {"company": "デジMラボ", "BU": "DX"}
],
"PERSONA_FILES": ["agent_X0Sample_personas.xlsx"],
"PERSONA_SOURCE": "RDB"
```
- `ORG`: 選択可能な組織dictのリスト（実行時にWebUI/プラクティスで1つ選ぶ）
- `PERSONA_FILES`: `persona_data/` 配下から読み込むExcelファイル名のリスト（省略時は全xlsx走査。`PERSONA_SOURCE="RDB"`時は無視）
- `PERSONA_SOURCE`: **エージェント単位で参照先を上書き**。`"EXCEL"`/`"RDB"`/`"BOTH"`から選択。**省略時は環境変数 `AGENT_PERSONA_SOURCE`** にフォールバック

**マッチング**: `agent.ORG`（実行時に選択した1要素）の全キーを、`persona.org` が同値で含めばマッチ（agentがpersonaのサブセット）。例:
- persona: `{company:"デジMラボ", dept:"Consulting", BU:"DX"}`
- agent (selected): `{company:"デジMラボ", BU:"DX"}` → ✅ match

**Persona上書きの対象**（テンプレートに対して）:
- 上書き: `NAME` / `ACT` / `PERSONALITY`（`character_text` または `character_file` を含む）/ `HABIT`（`["ALL"]`以外なら名前ホワイトリストでフィルタ）/ `KNOWLEDGE`（`["ALL"]`以外なら`RAG_NAME`でフィルタ）/ `DEFINE_CODE`
- 不変: `ENGINE` / `SUPPORT_AGENT` / `BOOK` / `SKILL` / `FEEDBACK`

**並列実行・メモリ制御**:
- WebUIサイドバーで複数ペルソナを選択 → 送信時に `ThreadPoolExecutor`（上限 `MAX_PARALLEL_PERSONAS`）で並列実行
- 並列実行された各 sub_seq には自動的に `setting.memory_flg="N"` が付与され、次ターンの会話メモリ（`get_memory`）から除外される。表示は残る
- 「Include Query」チェックボックスONなら、次ターンの**ユーザー入力先頭**に各ペルソナの全文応答を埋め込む（RAGクエリ生成には影響なし）

**Practice統合（chain.PERSONAS）**:

Practiceの各CHAINステップで、その**ステップだけ**を複数ペルソナで並列実行 → 結果をマージ → 次ステップへ、という構成が可能:
```json
"CHAINS": [
  {
    "TYPE": "LLM",
    "PERSONAS": "WEB_UI",            // "WEB_UI" / persona_idリスト / "THINKING"
    "PERSONA_MERGE": "include_query", // "summary"/"concat"/"first"/"include_query"/"none"
    "PERSONA_MERGE_LEVEL": "medium", // "light"/"medium"/"heavy" or 自由記述（summary時のみ使用）
    "SETTING": { ... }
  },
  {
    "TYPE": "LLM",
    "SETTING": {
      "USER_INPUT": ["OUTPUT_1", "\n\n[追加指示]\n比較評価して"],
      ...
    }
  }
]
```
- `PERSONAS = "WEB_UI"`: UIで選択中のペルソナを使う / `["P0001",...]` で固定指定
- `PERSONA_MERGE = "include_query"`: 各ペルソナ応答を `[前回の各ペルソナの回答]\n- name: text\n... [今回の質問] ...` 形式で次ステップ入力に
- 各並列ペルソナsub_seqは `chain_role="persona"`, `memory_flg="N"` を持つ
- 次ステップは `OUTPUT_<開始sub_seq>` で前ステップのマージ結果を参照

**サンプル**:
- [`practice_51PersonaCompare.json`](user/common/practice/practice_51PersonaCompare.json): chain[0]で**WEB_UI選択ペルソナ**並列回答 → chain[1]で比較評価。マジックワード **「皆の意見を聞いて」** で起動
- [`practice_52PersonaThinking.json`](user/common/practice/practice_52PersonaThinking.json): chain[0]で**Thinkingが自動選定**したペルソナで並列回答 → chain[1]で比較評価。マジックワード **「適任に聞いて」** で起動

**Phase 7: ThinkingMode persona auto-select**:

`chain.PERSONAS = "THINKING"` のときは [`agent_54PersonaSelector.json`](user/common/agent/agent_54PersonaSelector.json) が呼ばれ、ユーザーの質問内容に応じて最適なペルソナを **最大N人** 自動選定します:
- **候補プール**: 選択中ORG（WebUIで選んだ1つ）に合致するペルソナ全件
- **上限N**: WebUIサイドバーの「Max Personas」入力（既定は `setting.yaml` の `MAX_PERSONAS=3`）
- **選定ロジック**: PersonaSelectorが質問の内容と互いに補完的な視点を持つペルソナを選ぶ。1人で十分なら1人、専門外は除外
- **フォールバック**: 選定失敗 / 0人選定 → UI multiselect の選択にフォールバック
- **Detail Information**: `_THINKING_RESULT.personas_reason` に選定理由が記録される

**サポートエージェント**:
- `agent_50PersonaMerge.json`: `PERSONA_MERGE="summary"` 時に呼ばれる統合用LLM
- プロンプトテンプレ「Persona Merge」内の `{summary_level}` プレースホルダで要約強度を制御
- `DigiM_Tool.dialog_persona_merge()` から呼び出し

**Excelスキーマ** (`personas` シート、1行1ペルソナ):

| 列 | 型 | 説明 |
|---|---|---|
| `persona_id` | str | 一意ID |
| `template_agent` | str | 紐付くテンプレ（空なら全テンプレ共通） |
| `org` | JSON | `{"company":"...", "dept":"..."}` |
| `company` / `dept` / `name` / `act` | str | 表示・ログ用 |
| `personality` | JSON | テンプレの`PERSONALITY`を全置換 |
| `habits` | str | `ALL` または `DEFAULT,FRIENDLY` |
| `knowledge` | str | `ALL` または `Quote,Memo` |
| `define_code` | JSON | 自由スキーマ |
| `character_text` | str | 直接記述 |
| `character_file` | str | `character/` 配下のファイル名 |
| `active` | `Y`/`N` | 論理削除 |

**RDBスキーマ**: 詳細は `SETUP_POSTGRESQL.md` の `digim_agent_personas` 項を参照。

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

### Web検索の設定

Web検索を有効にすると、LLMへの入力にWebの最新情報を付加できます。WebUIのチャット入力欄上部の「WEB Search」チェックボックスで有効化し、隣のセレクトボックスでエンジンを切り替えられます。

#### 対応エンジン

| エンジン | APIキー | 特徴 |
|---------|---------|------|
| **Perplexity** | `PERPLEXITY_API_KEY` | Web検索特化モデル。検索ソースURL付きで回答 |
| **OpenAI** | `OPENAI_API_KEY` | GPTの `web_search_preview` ツールで検索。高精度 |
| **Google** | `GEMINI_API_KEY` | Gemini の Google Search Grounding。Google検索ベース |

#### setting.yaml の設定

デフォルトエンジンと各エンジンのパラメータを `setting.yaml` で設定します。

```yaml
# デフォルトの検索エンジン（Perplexity / OpenAI / Google）
WEB_SEARCH_DEFAULT: "Perplexity"

# Perplexity
PERPLEXITY_URL: "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL: "sonar"
PERPLEXITY_SYSTEM_PROMPT: "Be precise and concise."
PERPLEXITY_USER_PROMPT: "以下の入力に基づいて、関連する情報を提供してください。"
PERPLEXITY_MAX_TOKENS: 2000
PERPLEXITY_REASONING_EFFORT: "medium"

# OpenAI Web Search
OPENAI_SEARCH_MODEL: "gpt-5-mini"
OPENAI_SEARCH_SYSTEM_PROMPT: "Be precise and concise."
OPENAI_SEARCH_USER_PROMPT: "以下の入力に基づいて、関連する情報を提供してください。"

# Google Grounding Search
GOOGLE_SEARCH_MODEL: "gemini-2.5-flash-preview-05-20"
GOOGLE_SEARCH_USER_PROMPT: "以下の入力に基づいて、関連する情報を提供してください。"
```

#### system.env の設定

使用するエンジンに応じたAPIキーを設定してください。

```env
PERPLEXITY_API_KEY=PerplexityのAPIキー
OPENAI_API_KEY=OpenAIのAPIキー（LLMと共用）
GEMINI_API_KEY=Google GeminiのAPIキー（LLMと共用）
```

### URL自動取得（添付ファイル化）

ユーザー入力に `http(s)://...` のリンクが含まれていると、`DigiM_UrlFetch` が自動的にページ本文を取得し、添付ファイルとしてLLMの入力に追加します。

- **サブページクロール**: チャット入力欄上部の「Include URL Subpages」チェックボックスでON/OFF（デフォルトOFF）。ONにすると同一ドメイン内のリンク先も追加取得します。
- **安全制御**: プライベートIP・ループバック・リンクローカルへのアクセス禁止、サイズ上限（`MAX_BYTES`）、危険な拡張子（`.exe`/`.dll`等）の取得拒否。

`setting.yaml` の `URL_FETCH` で挙動を調整できます：

| 項目 | 説明 |
|------|------|
| `TIMEOUT` | HTTPタイムアウト秒数 |
| `MAX_BYTES` | 1ページあたりの最大取得バイト数 |
| `MAX_SUBPAGES` / `MAX_DEPTH` | サブページクロールの上限 |
| `USER_AGENT` | リクエスト時のUA文字列 |
| `ALLOWED_DOMAINS` | 非空のときホワイトリストモード（列挙ドメインのみ許可） |
| `BLOCKED_DOMAINS` | 拒否するドメイン（サブドメインも再帰的に拒否） |
| `BLOCKLIST_FILE` | hosts形式または1行1ドメインの外部ブロックリストへのパス（StevenBlack/hosts、UT1 blacklists、Hagezi DNS blocklists 等） |
| `BLOCKED_EXTENSIONS` | 取得を拒否する拡張子リスト |

### ユーザーメモリ（階層的ユーザー理解）

セッションを横断してユーザーの特徴や関心、価値観を蓄積し、以降のチャットへ自動的に文脈として注入する仕組みです。3層構造で、それぞれ異なる粒度・寿命を持ちます。

| 層 | 単位 | 内容 | 生成タイミング |
|----|------|------|---------------|
| **History** (`session_digest`) | 1セッション=1レコード | トピック / 発言抜粋 / 軸タグ（関心・価値観・制約・口調）/ プルチック感情リスト / confidence | セッション終了時 or 手動 |
| **Nowaday** (`period_profile`) | 期間（YYYY-MM or rolling_<N>d or since_<date> or all） | 継続トピック / 新規関心 / 減退話題 / 態度の変化 / **プルチック8基本感情(強度)** / **発生中の二次感情** / 要約段落 | 月次バッチ or 手動 |
| **Persona** (`persona_profile`) | 1ユーザー=1レコード | 役割 / 専門 / 関心 / 価値観 / 制約 / 口調 / 避けたい話題（各項目に confidence と status）/ **Big5(5特性のスコア+confidence+status)** | Nowaday更新時に差分マージ |

#### 注入の流れ

`DigiM_UserMemoryBuilder.build_context_text()` で「対話相手についての情報」テキストを合成し、`DigiM_Execute.py` で **Knowledgeコンテキストの直前**にプロンプト先頭として挿入します。

合成したユーザーメモリテキストは、本応答プロンプトに加えて **RAG検索クエリ生成（`RAG_QUERY_GENERATOR`）の入力にも含められます**。ユーザーメモリが有効な場合、人物像・最近の傾向・感情を踏まえたRAG検索クエリが生成されます（無効時は従来どおり影響なし）。WebUI / API いずれの実行経路でも適用され、API実行では `USER_MEMORY_LAYERS` を明示しないため `users.json` の `Allowed["User Memory Layers"]`（無ければ `USER_MEMORY_DEFAULT_LAYERS`）が適用されます。

注入される構造:

```
# 対話相手について
応答時の口調・関心・避けたい話題の参考にしてください。

## 人物像             ← Persona(approvedのみ)
・役割: ...
・専門: ...
・関心: ...
・価値観: ...
・制約: ...
・口調/説明の好み: ...
・避けたい話題: ...
・Big5: 開放性=0.85、誠実性=0.60、…   ← approvedの特性のみ表示
(summary_text 1500字以内)

## 最近の傾向（period） ← Nowaday
(要約段落 + 継続/新規/減退/変化)
・基本感情: 期待(0.7)、喜び(0.6)、信頼(0.5)   ← 強度0.2以上の基本感情のみ降順表示
・二次感情: 楽観、愛                          ← 期間内に発生している二次感情

## 直近セッション      ← History(タグ×時間ハイブリッド検索)
・[YYYY-MM-DD][topic] excerpt（感情: 喜び、楽観）  ← 各セッションのプルチック感情
...
```

**感情モデル（プルチックの感情の輪）:**

- **基本8感情**: `joy`(喜び) / `trust`(信頼) / `fear`(恐れ) / `surprise`(驚き) / `sadness`(悲しみ) / `disgust`(嫌悪) / `anger`(怒り) / `anticipation`(期待)
- **二次感情(ダイアド)**: `love`(愛=joy+trust) / `submission`(服従=trust+fear) / `awe`(畏怖=fear+surprise) / `disapproval`(不満=surprise+sadness) / `remorse`(後悔=sadness+disgust) / `contempt`(軽蔑=disgust+anger) / `aggressiveness`(攻撃性=anger+anticipation) / `optimism`(楽観=anticipation+joy)

History.emotions は1セッションあたりリスト形式（最大4個、英語キー）、Nowaday.basic_emotions は8キー固定のdict（強度0-1）、Nowaday.secondary_emotions は発生している二次感情のリスト。History検索ではクエリ文に含まれる感情語（日本語キーワード）を検出してマッチ対象に加算します。

**Big5（Persona）:** ビッグファイブ(Five Factor Model)の5特性 — `openness`(開放性) / `conscientiousness`(誠実性) / `extraversion`(外向性) / `agreeableness`(協調性) / `neuroticism`(神経症傾向) — を Persona 内に保持。各特性は `{score: 0..1, confidence: 0..1, status: pending|approved|deleted}` の構造で、リスト項目と同じ pending → approved 自動昇格（`confidence >= USER_MEMORY_AUTO_APPROVE_THRESHOLD`）ルールに従います。コンテキストには **approved の特性のみ** スコアが表示されます。

IMAGEGEN（画像生成）はプロンプト3000字制限を圧迫しないようスキップされます。

#### 既存レコードへの感情/Big5バックフィル

スキーマ拡張前に作られた既存レコードに感情/Big5を後追いで埋めるには `DigiM_GeneUserMemory.py` のCLIを使います。各レコードの圧縮済み出力（topic/excerpt/summary/list）から欠けているフィールドだけをLLMで推定し、既に値があるレコードはスキップします。Notionバックエンド時は不足プロパティを自動追加します。

```bash
python3 DigiM_GeneUserMemory.py --backfill                        # 全層・全件（欠損のみ）
python3 DigiM_GeneUserMemory.py --backfill --layer history        # 層を限定
python3 DigiM_GeneUserMemory.py --backfill --user RealMatsumoto   # user_idで限定
python3 DigiM_GeneUserMemory.py --backfill --dry-run              # LLM呼び出しのみ・保存しない
python3 DigiM_GeneUserMemory.py --backfill --no-schema            # Notionプロパティ自動追加をスキップ
```

#### 保存先（バックエンド）

層ごとに **Excel / Notion / RDB** から個別に選択できます。`system.env` で指定:

```env
USER_MEMORY_HISTORY_BACKEND="EXCEL"   # EXCEL/NOTION/RDB
USER_MEMORY_NOWADAY_BACKEND="EXCEL"
USER_MEMORY_PERSONA_BACKEND="EXCEL"
```

- **EXCEL**: `user/common/user_memory/<layer>.xlsx` に保存
- **NOTION**: `NOTION_MST_FILE` で指定したJSONの `DigiM_UserMemory_History` / `_Nowaday` / `_Persona` キーで指定したNotionDBに保存
- **RDB**: PostgreSQL の `digim_user_memory_<layer>` テーブルに保存（テーブルは初回アクセス時に自動作成）

#### On/Offの2階層

優先順は **ユーザー > システムデフォルト** です。

| 階層 | 格納先 | 内容 |
|------|--------|------|
| システムデフォルト | `system.env` の `USER_MEMORY_DEFAULT_LAYERS` | 全ユーザー初期値（例: `"persona,nowaday,history"`） |
| ユーザーマスタ | `users.json` の `Allowed["User Memory Layers"]` | このユーザーの有効化する層リスト |

ユーザーが自分の `layers` を変更できるかは `users.json` の `Allowed["User Memory"]`（true/false）で制御します。`true` の場合のみメイン画面の BOOK 直下に **User Memory** expander が表示され、自由に層を編集・保存できます（保存先は同じ `Allowed["User Memory Layers"]`）。`false` または未設定のユーザーは UI が出ず、`User Memory Layers` を持っていればその設定、持っていなければシステムデフォルトが適用されます。チェックボックスの変更は **Save 押下に関わらずその会話で即時反映**され、Save を押すと `users.json` に永続保存されます。チャットセッションを切替えると保存値にリセットされます。

ユーザーマスタの記述例:

```json
"RealMatsumoto": {
  "Allowed": {
    "User Memory": true,
    "User Memory Layers": ["persona", "nowaday", "history"]
  }
}
```

#### バックグラウンドスケジューラ（汎用ジョブ管理）

汎用スケジューラは **Scheduler メニュー**（WebUI上部、Chat / RAG Explorer の隣）から管理します。ジョブは `user/common/mst/scheduled_jobs.json` に保存され、Streamlit再起動なしで **Reload Schedulers** ボタンから反映できます。

**ジョブの種類 (`kind`):**

| kind | 内容 |
|------|------|
| `rag_update` | `DigiM_Context.generate_rag()` を呼んでRAGデータを再ベクトル化（`USER_MEMORY_HISTORY_AUTO_SAVE_FLG=Y` の場合は併せて未保存セッションのHistoryも自動保存）。セッションは作成されない。 |
| `user_memory_nowaday` | 全ユーザーに対し当月のNowadayプロファイル更新 → Personaへの差分マージを順に実行。セッションは作成されない。 |
| `agent_run` | 指定のエージェント・プロンプト・実行モードでエージェント実行。実行ごとに **所有者ユーザー** で新規セッションを発番（service_id=`Scheduler`、session_id=`SCH<日時>`、名前=`[Scheduler] <ジョブ名>`）し、応答はチャット履歴として通常通り保存。 |

**cron書式:** `"off"` / `"daily"`(03:00) / `"weekly"`(月03:00) / `"monthly"`(1日03:00) / 5フィールドのcron文字列（例: `"0 3 1 * *"`）

**最終実行の記録:** `agent_run` 以外はセッションを残さず、ジョブ行に `last_run` / `last_status` / `last_error` のみが記録されます（エラー時は Error log expander で表示）。`agent_run` のみ `last_session_id` も保存されるので、当該セッションをチャット履歴から開いて応答を確認できます。

**権限:** Scheduler メニューは `Allowed["Scheduler"] = true` のユーザーのみアクセス可能（`users.json` / `sample_users.json` で設定）。所有者ユーザー（`owner_user_id`）は保存時のログインユーザーが自動セットされ、`agent_run` 実行時のセッションに紐付きます。

**WebUI操作:** ジョブごとに **Edit** / **Run Now**（即時1回実行）/ **Enable/Disable** / **Delete**。ジョブ追加は **Add New Job** から、cron変更後は **Reload Schedulers** で稼働中スケジューラに反映。APScheduler 未インストール環境では cron 起動はスキップされますが Run Now による手動実行は可能。

#### Personaのステータスと自動承認

Personaの各項目は3つのステータスを持ちます:

| ステータス | 意味 | コンテキスト含有 |
|---|---|---|
| **Approved** | 信頼できる（ユーザー承認済 or `confidence ≥ 閾値` で自動承認） | ✓ |
| **Pending** | 未レビュー | ✗ |
| **Deleted** | 不要（再提案も弾く） | ✗ |

- マージ時に `confidence ≥ USER_MEMORY_AUTO_APPROVE_THRESHOLD`（デフォルト 0.8）の `pending` 項目は自動で `approved` に昇格
- ユーザーがWebUIで `approved` にした項目は次回マージでも保護される（信頼度のみ最大値で更新）
- `deleted` 項目は内部に保持され、LLMが同じラベルを再提案しても弾かれる
- 各フィールド（expertise / recurring_interests 等）には `USER_MEMORY_PERSONA_MAX_CHARS_PER_FIELD`（デフォルト 300字）の合計文字数上限。Approvedを優先 → 同status内は confidence 降順で詰める

#### Historyメモリの選定ロジック（タグ × 時間ハイブリッド）

蓄積したHistoryデータから、現在のユーザー入力に関連するものを選んで注入します（埋め込みベクトル不使用）:

1. **MeCab** でユーザー入力から名詞を抽出
2. 各Historyレコードの `axis_tags`（タグ全文を保持）に対し、クエリ名詞の部分一致で「マッチタグ」を判定
3. **マッチ群**: マッチタグ率 × (1 - α) + 時間スコア × α（α=`USER_MEMORY_HISTORY_RECENCY_WEIGHT`）でランク
4. **非マッチ群**: 時間スコアのみ（指数減衰、半減期=`USER_MEMORY_HISTORY_RECENCY_HALF_LIFE_DAYS`）
5. マッチ群を優先 → 余りを非マッチ群で埋める → 合計 `USER_MEMORY_HISTORY_MAX_CHARS`（デフォルト 800字）まで詰める

タグ自体は意味の単位として保持される（`対価と責任の関係` を `{対価, 責任, 関係}` に分解しない）ため、複合語の意味が消えません。

#### WebUIでの操作

**メイン画面 > User Memory expander（`Allowed.User Memory: true` のユーザー）**
- BOOK の直下に配置、デフォルト畳み
- 現在の有効層を表示
- **Layer On/Off**（persona/nowaday/history の3カラム横並びチェックボックス）
  - チェックを変えると **Save 押下に関わらず** その会話で即時反映
  - **Save Layer Setting** 押下で `users.json` の `Allowed["User Memory Layers"]` に永続保存
  - チャットセッションを切替えると、ユーザーマスタ保存値にリセット
- **Review User Memory** 展開でPersonaの全項目を一覧表示
  - 各項目: テキスト入力（ラベル上書き可能）+ ステータス select（Approved/Pending/Deleted）+ confidence
  - 上部の **Save User Memory** ボタンで一括保存（編集は触っただけではDBに書き込まれない）

**サイドバー > RAG Management > User Memory（`RAG Management` かつ `User Memory` 権限）**
- 各層のバックエンド表示
- **Target User IDs**: ユーザーマスタからmultiselect（未選択=全ユーザー）
- **Period**: チェックボックスON時にカレンダーで開始日を指定。指定日以降のHistoryだけを集約。チェックOFFなら全期間（`period="all"`）
- **Update User Memory (History → Nowaday → Persona)**: 1ボタンでパイプライン実行
  1. 対象ユーザーの未保存セッションからHistoryを生成
  2. Historyを期間でフィルタしてNowadayプロファイルを更新
  3. 最新のNowadayからPersonaを差分マージ（自動承認も適用）

#### 効果ログと Detail Information

- LLM呼び出し時に注入した層のIDが、各セッションの会話履歴 `response.reference.user_memory` に記録されます
- 注入したコンテキスト全文は `prompt.user_memory_context` に保存されます
- WebUIの **Detail Information** 内 `【ユーザーメモリ】` セクションで参照ID + 注入コンテキストを確認できます

#### Historyメモリの生成入力

HistoryメモリのLLM抽出時、以下を加味します:
- セッションの会話履歴(`role=user`/`role=assistant`)
- **ユーザーフィードバック**(`role=feedback` として末尾に付与) — 本人意思が最も強く出る情報として重視
- **除外**: SETTING.FLG="N"（削除）/ MEMORY_FLG="N"（メモリ参照対象外）の seq、setting.memory_flg="N" の sub_seq

#### 関連環境変数（system.env）

| 変数 | デフォルト | 説明 |
|------|----------|------|
| `USER_MEMORY_HISTORY_BACKEND` | `EXCEL` | Historyの保存先（EXCEL/NOTION/RDB） |
| `USER_MEMORY_NOWADAY_BACKEND` | `EXCEL` | Nowadayの保存先 |
| `USER_MEMORY_PERSONA_BACKEND` | `EXCEL` | Personaの保存先 |
| `USER_MEMORY_DEFAULT_LAYERS` | `persona,nowaday,history` | システムデフォルトの有効層（空文字 `""` 指定で全Off） |
| `USER_MEMORY_HISTORY_AUTO_SAVE_FLG` | `N` | `Y` で `Update RAG Data` 連動のHistory自動更新を有効化 |
| `USER_MEMORY_NOWADAY_MAX_CHARS` | `50000` | Nowaday生成時にLLMへ渡す history_records 全体の最大文字数。超過分は古いHistoryから切り捨て、`truncated_older_count` で件数を告知 |
| `USER_MEMORY_PERSONA_TOKEN_LIMIT` | `3000` | Persona注入時の上限トークン |
| `USER_MEMORY_AUTO_APPROVE_THRESHOLD` | `0.8` | この confidence 以上の pending 項目を自動 approved に昇格 |
| `USER_MEMORY_PERSONA_MAX_CHARS_PER_FIELD` | `300` | Persona各フィールドの label 合計文字数上限 |
| `USER_MEMORY_HISTORY_MAX_CHARS` | `800` | Historyコンテキスト挿入時の合計文字数上限 |
| `USER_MEMORY_HISTORY_RECENCY_WEIGHT` | `0.3` | Historyスコアリングで時間スコアに割く重み（マッチ率=1-この値） |
| `USER_MEMORY_HISTORY_RECENCY_HALF_LIFE_DAYS` | `30` | Historyの時間スコア半減期（日数） |

### バックグラウンドジョブの管理

Streamlit上で走るバックグラウンドスレッド（RAG更新、知識活用分析、エージェント比較、会話ダイジェスト生成など）を `DigiM_JobRegistry` で追跡し、サイドバー **Sessions → Background Jobs** から稼働中ジョブの一覧表示・選択キャンセルが可能です。

- **表示項目**: ジョブ種別 / 関連セッションID / メッセージ / 経過秒数 / キャンセル要求状態
- **スコープ**: 一般ユーザーは自分の `user_id` のジョブのみ、Adminは全ジョブを閲覧
- **キャンセル方式**: `cancel_requested` フラグ + `PyThreadState_SetAsyncExc` による `SystemExit` 注入

**限界**:
- C拡張のI/O（HTTP受信中など）ではsyscallが返るまで例外が発火しない（LLMストリームはチャンク毎にPythonへ戻るので秒単位で止まる）
- `ThreadPoolExecutor` 内部のワーカーは登録対象外
- 非常時のハンマー手段のためロック等のリソースリークが発生し得る。詰まったジョブの解消用途で使用

### 起動方法

```bash
# WebUI（Streamlit）
streamlit run WebDigiMatsuAgent.py --server.port 8501

# API（FastAPI）
python DigiM_API.py

# ベンチマーク（サポートエージェントの速度・出力比較）
# 入力: test/questions.xlsx（question列に質問を記載）
# 出力: test/questions_result_YYYYMMDD_HHMMSS.xlsx
python3 DigiM_SupportEval.py questions.xlsx                  # RAGクエリ生成 + メタ検索
python3 DigiM_SupportEval.py questions.xlsx --target intent  # RAGクエリ生成のみ
python3 DigiM_SupportEval.py questions.xlsx --target meta    # メタ検索のみ
```

---

## RAG Explorer

RAG Explorerは、RAGデータの分析画面です。サイドバーのラジオボタン（Chat / RAG Explorer）から切り替えてアクセスします。

> **アクセス制御：** ユーザーマスター（`users.json`）の `Allowed` で `"RAG Explorer": true` を設定すると利用可能になります。Adminグループのユーザーは常にアクセスできます。

### データソースの選択

ラジオボタンで **Collection（VectorDB）** と **PageIndex** を切り替えます。コレクション一覧は、選択中のエージェントの KNOWLEDGE および BOOK 設定に基づいてフィルタリングされます。

### データフィルタリング

| フィルタ | 説明 |
|---------|------|
| カラムフィルタ | 値の複数選択によるフィルタリング |
| テキスト検索 | ワイルドカード（`*`）対応のテキスト検索 |
| 日付範囲フィルタ | `create_date` が存在する場合に利用可能 |
| Private除外トグル | Privateデータの表示/非表示切り替え |

### 散布図（VectorDBのみ）

- **次元削減**: PCA / t-SNE
- **色分け**: カテゴリ別（`category_map.json` の色定義を使用）
- **ドットサイズ**: Uniform（均一） / Newer=Larger（新しいデータほど大きく表示）

### 感度分析（VectorDBのみ）

クエリテキストを入力し、どの知識チャンクが最も強く反応するかを確認できます。

| 項目 | 説明 |
|------|------|
| クエリ入力 | 分析対象のテキストを入力 |
| 日付ボーナス | 指定期間内のデータにスコアをブーストする |
| 散布図上の表示 | 青=通常、緑=日付ボーナス適用 |

### クラスタリング（VectorDBのみ）

| アルゴリズム | 特徴 |
|------------|------|
| K-Means | クラスタ数を指定 |
| DBSCAN | eps自動推定に対応 |
| 階層的クラスタリング | デンドログラムベース |

クラスタリング結果に対して、LLMによるクラスタ説明を生成できます（`agent_23DataAnalyst.json` を使用）。

### 時系列分析（create_dateが存在する場合）

- **期間単位**: 月 / 四半期 / 年
- **TF-IDFキーワード抽出**: 名詞のみ対象、ストップワード除外
- **カテゴリ構成**: 積み上げ棒グラフで表示
- **LLMトレンド説明**: 時系列の傾向をLLMが分析・解説

### PageIndex

- **ツリー構造表示**: ページインデックスの階層をツリー形式で可視化
- **ページ感度分析**: LLMによるページ選択シミュレーション

### Ask Agent

チャットと同じパイプライン（DigiMatsuExecute）を使用してエージェントに質問できます。

| 項目 | 説明 |
|------|------|
| Web Search | Web検索の有効化 |
| Private Mode | Privateデータの除外 |
| Thinking Mode | AI思考モード |
| Books | Book参照の有効化 |
| 会話履歴 | セッション内で会話履歴を保持 |
| Detail Information | 実行詳細情報の表示 |
| Analytics Results | 知識活用分析・エージェント比較 |

### エクスポート・レポート

**Generate Report** ボタンで分析セッションを保存し、グラフ埋め込みの `.md` ファイルをダウンロードできます。

### セッション管理

| 項目 | 説明 |
|------|------|
| 保存先 | `user/common/analytics/rag_explorer/analyticsYYYYMMDD_HHMMSS/` |
| 状態保存 | pickle形式で全状態を保存 |
| 読み込み | サイドバーのセッション一覧から選択して復元 |

---

## API リファレンス

FastAPI を起動すると、REST API 経由でエージェントを実行できます。LINE・Slack 等の外部サービスからの呼び出しにも対応しています。

### エンドポイント一覧

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/run` | メッセージを送信してエージェントの応答を取得（同期） |
| `GET` | `/agents` | 利用可能なエージェント一覧を取得 |
| `GET` | `/agents/{agent_file}/engines` | エージェントの選択可能なエンジン一覧を取得 |
| `GET` | `/agents/{agent_file}/feedback` | エージェントのフィードバック設定を取得 |
| `GET` | `/web_search_engines` | 利用可能なWeb検索エンジン一覧を取得 |
| `POST` | `/feedback` | フィードバックを送信（CSV/Notionに保存） |
| `GET` | `/sessions` | セッション一覧を取得 |
| `GET` | `/sessions/{session_id}` | セッションの会話履歴を取得 |
| `GET` | `/health` | ヘルスチェック |

### POST /run — メッセージ送信

1回の HTTP リクエストで LLM 実行が完結し、応答を直接返します。同一 `session_id` を指定すれば会話が継続されます。

同じセッションが実行中（LOCKED）の場合は最大60秒待機し、解除後に実行されます。タイムアウト時は `429` を返します。

**リクエスト:**

```json
{
  "service_info": {"SERVICE_ID": "サービス名", "SERVICE_DATA": {}},
  "user_info": {"USER_ID": "ユーザーID", "USER_DATA": {}},
  "session_id": "セッションID",
  "session_name": "セッション名",
  "user_input": "メッセージ本文",
  "situation": {"TIME": "", "SITUATION": ""},
  "agent_file": "エージェントファイル名",
  "engine": "エンジン名",
  "stream_mode": true,
  "save_digest": true,
  "memory_use": true,
  "magic_word_use": false,
  "meta_search": true,
  "rag_query_gene": true,
  "web_search": false,
  "web_search_engine": "OpenAI",
  "thinking_mode": false,
  "user_memory": true,
  "user_memory_layers": ["persona", "nowaday", "history"]
}
```

**基本パラメータ:**

| パラメータ | 必須 | デフォルト | 説明 |
|-----------|------|-----------|------|
| `service_info` | ○ | | サービス識別情報（`SERVICE_ID` でサービスを区別） |
| `user_info` | ○ | | ユーザー識別情報（`USER_ID` でユーザーを区別） |
| `user_input` | ○ | | ユーザーの入力メッセージ |
| `session_id` | | 自動発番 | セッションID。LINE連携なら LINE ユーザーID を指定すると会話が継続される |
| `session_name` | | 自動生成 | セッション名 |
| `agent_file` | | `API_AGENT_FILE` | 使用するエージェント（例: `agent_X0Sample.json`） |
| `engine` | | エージェントのDEFAULT | LLMエンジン名（例: `Gemini-2.5-Flash`）。エージェントの ENGINE.LLM に定義されている名前を指定 |
| `situation` | | `{"TIME":"","SITUATION":""}` | 日時・状況設定。`TIME` を空にすると日時なしで実行 |

**実行設定（Exec Setting）:**

省略したパラメータはAPI用デフォルト値が使われます。WebUIのExec Settingに対応しています。

| パラメータ | APIデフォルト | 説明 |
|-----------|-------------|------|
| `stream_mode` | `true` | ストリーミングモード |
| `save_digest` | `true` | 会話ダイジェストの保存 |
| `memory_use` | `true` | 会話履歴の参照 |
| `magic_word_use` | `false` | MAGIC_WORD によるHabit切り替え |
| `meta_search` | `true` | メタデータ検索（日付抽出） |
| `rag_query_gene` | `true` | RAG検索用クエリ生成 |
| `web_search` | `false` | Web検索（`true` にすると `web_search_engine` で指定したエンジンで検索） |
| `web_search_engine` | `"OpenAI"` | Web検索エンジン（`Perplexity` / `OpenAI` / `Google`）。`web_search` が `false` の場合は使用されない |
| `private_mode` | `false` | Private Mode。`true` にすると `private: true` のRAGデータが検索対象外になる |
| `thinking_mode` | `false` | Thinking Mode。`true` にするとAIが質問を分析してHabit・Web検索・RAGクエリ生成・Book追加を動的に判定する |
| `user_memory` | （未指定） | ユーザーメモリ（対話相手についての情報）を使うか。`true`=全層ON / `false`=全Off / 未指定= `users.json` の `Allowed["User Memory Layers"]`（無ければ `USER_MEMORY_DEFAULT_LAYERS`）に従う |
| `user_memory_layers` | （未指定） | 有効化する層を明示指定（`["persona","nowaday","history"]` のサブセット、`[]` で全Off）。指定すると `user_memory` より優先。不正な層名は無視 |

> `memory_similarity` はAPI経由では常に `false` です（パラメータ指定不可）。
>
> ユーザーメモリの注入は `memory_use=true`（APIデフォルト）かつ LLM 実行時のみ有効です（`user_memory` を指定しても `memory_use=false` だと注入されません）。有効時はユーザーメモリテキストがRAG検索クエリ生成の入力にも含まれます。

**レスポンス:**

```json
{
  "session_id": "API_TEST_001",
  "session_name": "(User:TestUser)AIについての質問",
  "response": "エージェントの応答テキスト"
}
```

### 実行例

```bash
# ヘルスチェック
curl -s http://localhost:8899/health

# エージェント一覧
curl -s http://localhost:8899/agents | python3 -m json.tool --no-ensure-ascii

# メッセージ送信（新規セッション）
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_001",
    "user_input": "こんにちは、自己紹介してください。",
    "agent_file": "agent_X0Sample.json"
  }' | python3 -m json.tool --no-ensure-ascii

# 同じセッションで会話を継続
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_001",
    "user_input": "AIの未来について教えて",
    "agent_file": "agent_X0Sample.json"
  }' | python3 -m json.tool --no-ensure-ascii

# エンジンを指定して実行
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_002",
    "user_input": "量子コンピュータについて教えて",
    "agent_file": "agent_X0Sample.json",
    "engine": "Gemini-2.5-Flash"
  }' | python3 -m json.tool --no-ensure-ascii

# 全パラメータをデフォルト状態で明示指定して実行
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_001",
    "user_input": "こんにちは",
    "agent_file": "agent_X0Sample.json",
    "engine": "",
    "situation": {"TIME": "", "SITUATION": ""},
    "stream_mode": true,
    "save_digest": true,
    "memory_use": true,
    "magic_word_use": false,
    "meta_search": true,
    "rag_query_gene": true,
    "web_search": false,
    "web_search_engine": "OpenAI",
    "thinking_mode": false
  }' | python3 -m json.tool --no-ensure-ascii

# 軽量実行（RAGクエリ生成OFF + メタ検索OFF）
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_003",
    "user_input": "こんにちは",
    "agent_file": "agent_X0Sample.json",
    "rag_query_gene": false,
    "meta_search": false
  }' | python3 -m json.tool --no-ensure-ascii

# 会話履歴なし（単発質問モード）
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "user_input": "自己紹介してください",
    "agent_file": "agent_X0Sample.json",
    "memory_use": false,
    "save_digest": false
  }' | python3 -m json.tool --no-ensure-ascii

# ユーザーメモリを明示的に有効化（Persona+Historyのみ使う例）
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "RealMatsumoto", "USER_DATA": {}},
    "user_input": "最近の私の関心を踏まえて提案して",
    "agent_file": "agent_X0Sample.json",
    "user_memory_layers": ["persona", "history"]
  }' | python3 -m json.tool --no-ensure-ascii

# ユーザーメモリを明示的に無効化（user_memory=false で全Off）
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "RealMatsumoto", "USER_DATA": {}},
    "user_input": "一般的な観点で説明して",
    "agent_file": "agent_X0Sample.json",
    "user_memory": false
  }' | python3 -m json.tool --no-ensure-ascii

# セッション一覧（ユーザーで絞り込み）
curl -s "http://localhost:8899/sessions?user_id=TestUser" | python3 -m json.tool --no-ensure-ascii

# セッション履歴
curl -s http://localhost:8899/sessions/API_TEST_001 | python3 -m json.tool --no-ensure-ascii

# エンジン一覧（エージェントが選択可能なLLM/IMAGEGENエンジン）
curl -s http://localhost:8899/agents/agent_X0Sample.json/engines | python3 -m json.tool --no-ensure-ascii

# Web検索エンジン一覧
curl -s http://localhost:8899/web_search_engines | python3 -m json.tool --no-ensure-ascii

# フィードバック設定の確認（エージェントが受け付けるフィードバック項目・カテゴリ一覧）
curl -s http://localhost:8899/agents/agent_X0Sample.json/feedback | python3 -m json.tool --no-ensure-ascii

# フィードバック送信（seq=1, sub_seq=1 の会話に対してフィードバック）
curl -s -X POST http://localhost:8899/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "API_TEST_001",
    "agent_file": "agent_X0Sample.json",
    "seq": "1",
    "sub_seq": "1",
    "feedbacks": {
      "name": "Feedback",
      "memo": {"visible": true, "flg": true, "memo": "参考になった", "category": "AI"}
    }
  }' | python3 -m json.tool --no-ensure-ascii
```

> HTTPS 環境では `http://localhost:8899` を `https://your-domain.com/api` に読み替えてください。LLM 実行は 10〜30 秒かかるため、タイムアウトに注意してください。

### LINE 連携での利用例

LINE Messaging API のWebhookからの呼び出しイメージです。

```python
# LINE Webhook → FastAPI 呼び出し例
import requests

def handle_line_message(line_user_id, message_text):
    response = requests.post("https://your-domain.com/api/run", json={
        "service_info": {"SERVICE_ID": "LINE", "SERVICE_DATA": {}},
        "user_info": {"USER_ID": line_user_id, "USER_DATA": {}},
        "session_id": line_user_id,  # LINE ユーザーIDをセッションIDに
        "user_input": message_text,
        "agent_file": "agent_X0Sample.json"
    }, timeout=120)
    return response.json()["response"]
```

`session_id` に LINE ユーザーID を指定することで、同一ユーザーとの会話が自動的に継続されます。
