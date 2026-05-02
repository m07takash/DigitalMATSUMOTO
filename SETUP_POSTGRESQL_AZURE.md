# Azure PostgreSQL セットアップ手順

DigitalMATSUMOTO の分析用DBを Azure Database for PostgreSQL にゼロから構築する手順です。

---

## 1. Azure Database for PostgreSQL の作成

### 1-1. リソース作成

1. [Azure Portal](https://portal.azure.com) にログイン
2. 「リソースの作成」→「データベース」→「Azure Database for PostgreSQL」を選択
3. **フレキシブルサーバー** を選択して「作成」

### 1-2. 基本設定

| 項目 | 設定値（例） |
|------|-------------|
| サブスクリプション | 任意 |
| リソースグループ | 任意（新規作成可） |
| サーバー名 | `digim-rdb`（→ `digim-rdb.postgres.database.azure.com`） |
| リージョン | Japan East（任意） |
| PostgreSQL バージョン | 16（推奨） |
| ワークロードの種類 | 開発（小規模の場合） |
| 管理者ユーザー名 | `digimatsuadmin`（任意） |
| パスワード | 任意（控えておくこと） |

### 1-3. ネットワーク設定

1. 「ネットワーク」タブを開く
2. 接続方法: **パブリックアクセス（すべてのネットワークを許可）**
3. SSL接続: **有効**（デフォルト）

### 1-4. 作成完了の確認

- 「確認および作成」→「作成」をクリック
- デプロイ完了後、リソースページの「概要」からホスト名を確認
  例: `digim-rdb.postgres.database.azure.com`

---

## 2. Azure OpenAI リソースの作成

### 2-1. リソース作成

1. Azure Portal →「リソースの作成」→「Azure OpenAI」
2. 基本設定：

| 項目 | 設定値 |
|------|-------|
| リージョン | East US / Sweden Central（モデル提供状況が多い） |
| 価格レベル | Standard S0 |
| ネットワーク | すべてのネットワークを許可 |

3. 作成完了後、「キーとエンドポイント」から以下を控える
   - **エンドポイント**: `https://xxxx.openai.azure.com/`
   - **APIキー**: キー1 または キー2

### 2-2. Embedding モデルのデプロイ（Azure AI Foundry）

1. Azure OpenAI リソースページ →「Go to Azure AI Foundry portal」をクリック
2. 左メニュー「**デプロイ**」→「＋モデルのデプロイ」→「基本モデルをデプロイする」
3. `text-embedding-3-large` を検索して選択
4. デプロイ設定：

| 項目 | 設定値 |
|------|-------|
| デプロイ名 | `text-embedding-3-large` |
| デプロイの種類 | Standard |
| トークン/分のレート制限 | 150,000以上推奨 |

---

## 3. サーバーパラメーターの設定

Azure Portal の PostgreSQL リソース →「サーバーパラメーター」を開く。

`azure.extensions` を検索して値に以下を追加して保存、その後サーバーを再起動。

```
AZURE_AI,VECTOR
```

---

## 4. データベースの作成

### 4-1. psql で接続

```bash
psql "host=digim-rdb.postgres.database.azure.com port=5432 dbname=postgres user=digimatsuadmin sslmode=require"
```

### 4-2. データベース作成

```sql
CREATE DATABASE digim_analytics
    WITH ENCODING = 'UTF8'
         LC_COLLATE = 'en_US.utf8'
         LC_CTYPE   = 'en_US.utf8';
```

### 4-3. 作成したDBに接続

```bash
psql "host=digim-rdb.postgres.database.azure.com port=5432 dbname=digim_analytics user=digimatsuadmin sslmode=require"
```

---

## 5. 拡張機能の有効化・接続設定

```sql
-- 拡張の有効化
CREATE EXTENSION IF NOT EXISTS azure_ai;
CREATE EXTENSION IF NOT EXISTS vector;

-- Azure OpenAI の接続情報を設定
SELECT azure_ai.set_setting('azure_openai.endpoint', 'https://xxxx.openai.azure.com/');
SELECT azure_ai.set_setting('azure_openai.subscription_key', 'YOUR_API_KEY');

-- 接続確認（数値配列が返ればOK）
SELECT azure_openai.create_embeddings('text-embedding-3-large', 'テスト')::text;
```

---

## 6. テーブルの作成

### 6-1. digim_sessions

```sql
CREATE TABLE digim_sessions (
    session_id        VARCHAR(64)  NOT NULL,
    session_name      VARCHAR(255),
    user_id           VARCHAR(128),
    service_id        VARCHAR(64),
    agent_file        VARCHAR(255),
    active            CHAR(1),
    status            VARCHAR(32),
    user_dialog       VARCHAR(32),
    last_update_date  TIMESTAMP,
    created_date      TIMESTAMP,
    CONSTRAINT digim_sessions_pkey PRIMARY KEY (session_id)
);
```

### 6-2. digim_dialogs

```sql
CREATE TABLE digim_dialogs (
    id                        BIGSERIAL    NOT NULL,
    session_id                VARCHAR(64),
    seq                       INTEGER,
    sub_seq                   INTEGER,
    flg                       CHAR(1),       -- 論理削除フラグ（'N'は表示・参照とも除外）
    memory_flg                CHAR(1),       -- メモリ参照フラグ（'N'は表示は残るがメモリ参照から除外）
    practice_name             VARCHAR(128),
    model_type                VARCHAR(32),
    agent_file                VARCHAR(255),
    agent_name                VARCHAR(255),
    model_name                VARCHAR(128),
    prompt_template           VARCHAR(128),
    situation_time            TIMESTAMP,
    user_input                TEXT,
    query_text                TEXT,
    response_text             TEXT,
    digest_text               TEXT,
    prompt_timestamp          TIMESTAMP,
    response_timestamp        TIMESTAMP,
    response_duration_sec     DOUBLE PRECISION,
    prompt_tokens_total       INTEGER,
    query_tokens              INTEGER,
    response_tokens           INTEGER,
    digest_tokens             INTEGER,
    digest_model              VARCHAR(128),
    rag_query_used            BOOLEAN,
    rag_query_model           VARCHAR(128),
    rag_query_prompt_tokens   INTEGER,
    rag_query_response_tokens INTEGER,
    meta_search_date_used     BOOLEAN,
    meta_search_date_result   VARCHAR(255),
    web_search_used           BOOLEAN,
    knowledge_ref_count       INTEGER,
    memory_ref_count          INTEGER,
    query_vec                 vector(3072),
    response_vec              vector(3072),
    CONSTRAINT digim_dialogs_pkey PRIMARY KEY (id),
    CONSTRAINT digim_dialogs_session_id_seq_sub_seq_key UNIQUE (session_id, seq, sub_seq),
    CONSTRAINT digim_dialogs_session_id_fkey FOREIGN KEY (session_id)
        REFERENCES digim_sessions (session_id)
);
```

> 既に `digim_dialogs` を作成済みで `memory_flg` カラムが無い場合は以下を実行:
> ```sql
> ALTER TABLE digim_dialogs ADD COLUMN IF NOT EXISTS memory_flg CHAR(1);
> UPDATE digim_dialogs SET memory_flg = 'Y' WHERE memory_flg IS NULL;
> ```

### 6-3. digim_references

```sql
CREATE TABLE digim_references (
    id                  BIGSERIAL NOT NULL,
    dialog_id           BIGINT,
    session_id          VARCHAR(64),
    seq                 INTEGER,
    sub_seq             INTEGER,
    rag_name            VARCHAR(128),
    db_name             VARCHAR(128),
    query_seq           VARCHAR(64),
    query_mode          VARCHAR(64),
    chunk_id            VARCHAR(255),
    chunk_timestamp     TIMESTAMP,
    category            VARCHAR(128),
    similarity_prompt   DOUBLE PRECISION,
    similarity_response DOUBLE PRECISION,
    title               VARCHAR(255),
    text_short          TEXT,
    CONSTRAINT digim_references_pkey PRIMARY KEY (id),
    CONSTRAINT digim_references_dialog_id_fkey FOREIGN KEY (dialog_id)
        REFERENCES digim_dialogs (id)
);
```

### 6-4. インデックスの作成

```sql
-- digim_dialogs
CREATE INDEX digim_dialogs_session_id_idx       ON digim_dialogs (session_id);
CREATE INDEX digim_dialogs_model_name_idx       ON digim_dialogs (model_name);
CREATE INDEX digim_dialogs_prompt_timestamp_idx ON digim_dialogs (prompt_timestamp);

-- digim_references
CREATE INDEX digim_references_dialog_id_idx        ON digim_references (dialog_id);
CREATE INDEX digim_references_rag_name_db_name_idx ON digim_references (rag_name, db_name);
```

### 6-5. digim_users（ログイン認証マスタ）

WebUIのログイン認証ソースとしてAzure PostgreSQLを使う場合に作成します（`system.env` で `LOGIN_AUTH_METHOD=RDB` を指定）。アプリ初回起動時に `CREATE TABLE IF NOT EXISTS` で自動作成もされますが、明示的に作成しておくと運用が分かりやすいです。

```sql
CREATE TABLE IF NOT EXISTS digim_users (
    user_id    TEXT PRIMARY KEY,
    name       TEXT,
    pw         TEXT,           -- bcryptハッシュ。平文初回ログイン時は自動でハッシュ化される
    group_cd   JSONB,          -- 所属グループの配列（複数指定可、["Admin"]/["Sales","Marketing"]等）
    agent      TEXT,           -- デフォルトエージェントファイル名（"DEFAULT" or "agent_*.json"）
    allowed    JSONB           -- UI機能の表示/非表示マップ
);
```

既存JSON（`users.json`）からの移行登録例:

```sql
INSERT INTO digim_users (user_id, name, pw, group_cd, agent, allowed) VALUES
  ('ADMIN0001', 'Administrator', 'password', '["Admin"]'::jsonb, 'DEFAULT', '{}'::jsonb),
  ('USER0001', 'Consult Oh', 'password', '["User"]'::jsonb, 'DEFAULT', '{}'::jsonb)
ON CONFLICT (user_id) DO UPDATE
SET name=EXCLUDED.name, pw=EXCLUDED.pw, group_cd=EXCLUDED.group_cd,
    agent=EXCLUDED.agent, allowed=EXCLUDED.allowed;
```

> 平文パスワードを入れた場合、初回ログイン後にbcryptハッシュへ自動変換されます。最初からハッシュ値（`$2b$...`）を入れることも可能。

> 過去に `group_cd TEXT` で作成済みの場合は、JSONBへの型変換が必要です:
> ```sql
> ALTER TABLE digim_users ALTER COLUMN group_cd TYPE JSONB
> USING CASE WHEN group_cd IS NULL OR group_cd = '' THEN '[]'::jsonb
>            ELSE jsonb_build_array(group_cd) END;
> ```

---

## 7. ベクトル自動生成トリガーの作成

INSERT / UPDATE 時に自動でベクトルを生成するトリガーを設定します。

```sql
CREATE OR REPLACE FUNCTION trg_fn_digim_dialogs_vec()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.user_input IS NOT NULL AND NEW.user_input <> '' THEN
        NEW.query_vec := azure_openai.create_embeddings(
            'text-embedding-3-large',
            LEFT(NEW.user_input, 4000)
        )::vector;
    END IF;

    IF NEW.response_text IS NOT NULL AND NEW.response_text <> '' THEN
        NEW.response_vec := azure_openai.create_embeddings(
            'text-embedding-3-large',
            LEFT(NEW.response_text, 4000)
        )::vector;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_digim_dialogs_vec
BEFORE INSERT OR UPDATE OF user_input, response_text
ON digim_dialogs
FOR EACH ROW EXECUTE FUNCTION trg_fn_digim_dialogs_vec();
```

> `LEFT(text, 4000)` は日本語1文字≒2トークンのため8192トークン上限対策として4000文字に制限しています。
> トリガーはINSERT/UPDATEで動作しますが、**大量バッチ処理（DigiM_DB_Export.py経由）では無効**です。その場合は手順9のPythonスクリプトでベクトル化します。

---

## 8. system.env の設定

`system.env_sample` をコピーして `system.env` を作成し、接続情報を記載します。

```env
# PostgreSQL接続情報
POSTGRES_HOST=digim-rdb.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_DB=digim_analytics
POSTGRES_USER=digimatsuadmin
POSTGRES_PASSWORD=<your_password>

# Azure OpenAI（ベクトル化に使用）
AZURE_OPENAI_ENDPOINT=https://xxxx.openai.azure.com/
AZURE_OPENAI_API_KEY=<your_api_key>
AZURE_OPENAI_EMBED_MODEL=text-embedding-3-large

# ログイン認証ソースの切替（"JSON" or "RDB"）
# RDBの場合、上記POSTGRES_*接続でdigim_usersテーブルを使用
LOGIN_AUTH_METHOD="RDB"
```

> `system.env` は `.gitignore` に含めてリポジトリにコミットしないこと。

---

## 9. 接続確認

```bash
python3 -c "
import psycopg2, os
from dotenv import load_dotenv
load_dotenv('system.env')
conn = psycopg2.connect(
    host=os.getenv('POSTGRES_HOST'),
    port=int(os.getenv('POSTGRES_PORT', 5432)),
    dbname=os.getenv('POSTGRES_DB'),
    user=os.getenv('POSTGRES_USER'),
    password=os.getenv('POSTGRES_PASSWORD'),
    sslmode='require',
)
print('接続OK:', conn.server_version)
conn.close()
"
```

---

## 10. 初回データ投入

### 10-1. セッションデータのエクスポート

```bash
python3 DigiM_DB_Export.py
```

または WebUI の **Sessions → Export to DB** ボタンから実行できます。

### 10-2. 既存データの一括ベクトル化

エクスポート後、未ベクトル化レコードを一括処理します。

```bash
python3 -c "import DigiM_DB_Export as dmdbe; dmdbe.vectorize_dialogs()"
```

> 以降の新規データは WebUI の **Export to DB** ボタン実行時に自動でベクトル化されます。

---

## テーブル構成の概要

```
digim_sessions  (1)
    └── digim_dialogs  (N)  ← session_id で紐付け
            └── digim_references  (N)  ← dialog_id で紐付け
```

| テーブル | 説明 |
|---------|------|
| `digim_sessions` | セッション単位のメタ情報（名前・ユーザー・エージェント等） |
| `digim_dialogs` | 会話の各ターン（入力・応答・トークン数・RAG利用状況等） |
| `digim_references` | 各ターンで参照されたRAGナレッジチャンクの詳細 |
