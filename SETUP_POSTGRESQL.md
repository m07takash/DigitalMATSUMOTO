# PostgreSQL セットアップ手順（Docker環境）

Docker がインストールされているだけの環境で、DigitalMATSUMOTO の分析用DBをゼロから構築する手順です。

---

## 1. PostgreSQL コンテナの起動

### 1-1. docker-compose.yml の作成（推奨）

プロジェクトルートに `docker-compose.yml` を作成します。

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: digim-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: digimatsuadmin
      POSTGRES_PASSWORD: <your_password>
      POSTGRES_DB: digim_analytics
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

> `pgvector/pgvector:pg16` イメージは `pgvector` 拡張が最初から含まれています。
> ベクトル検索が不要な場合は `postgres:16` で代替可能です。

### 1-2. コンテナ起動

```bash
docker compose up -d
```

### 1-3. 起動確認

```bash
docker compose ps
# または
docker ps | grep digim-postgres
```

---

## 2. データベースへの接続

### 2-1. コンテナ内から psql で接続

```bash
docker exec -it digim-postgres psql -U digimatsuadmin -d digim_analytics
```

### 2-2. ホストから psql で接続（psql がインストール済みの場合）

```bash
psql "host=localhost port=5432 dbname=digim_analytics user=digimatsuadmin"
```

---

## 3. 拡張機能の有効化

`pgvector/pgvector` イメージを使用した場合、以下を実行します。

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

> `postgres:16` イメージを使用した場合は拡張が含まれないため、省略するかカラム定義から `vector` 型を外してください。

---

## 4. テーブルの作成

psql に接続した状態で以下を実行します。

### 4-1. digim_sessions

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

### 4-2. digim_dialogs

```sql
CREATE TABLE digim_dialogs (
    id                        BIGSERIAL    NOT NULL,
    session_id                VARCHAR(64),
    seq                       INTEGER,
    sub_seq                   INTEGER,
    flg                       CHAR(1),       -- 論理削除フラグ（'N'は表示・参照とも除外）
    memory_flg                CHAR(1),       -- メモリ参照フラグ（'N'は表示は残るがメモリ参照から除外）
    persona_id                VARCHAR(64),   -- 適用ペルソナID（personaなしのときは空）
    persona_name              VARCHAR(128),  -- 適用ペルソナ名（display用）
    chain_index               INTEGER,       -- Practiceチェイン内のステップ番号（0始まり）
    chain_role                VARCHAR(32),   -- 'persona' / 'merge' / null（PERSONAS並列ステップの識別）
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

> `vector(3072)` は `text-embedding-3-large` に対応した次元数です。ベクトル検索が不要な場合は該当行を削除してください。

> 既に `digim_dialogs` を作成済みで `memory_flg` カラムが無い場合は以下を実行:
> ```sql
> ALTER TABLE digim_dialogs ADD COLUMN IF NOT EXISTS memory_flg CHAR(1);
> UPDATE digim_dialogs SET memory_flg = 'Y' WHERE memory_flg IS NULL;
> ```
>
> Phase 6 マルチペルソナ用カラムを追加する場合:
> ```sql
> ALTER TABLE digim_dialogs
>   ADD COLUMN IF NOT EXISTS persona_id   VARCHAR(64),
>   ADD COLUMN IF NOT EXISTS persona_name VARCHAR(128),
>   ADD COLUMN IF NOT EXISTS chain_index  INTEGER,
>   ADD COLUMN IF NOT EXISTS chain_role   VARCHAR(32);
> ```

### 4-3. digim_references

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

### 4-4. インデックスの作成

```sql
-- digim_dialogs
CREATE INDEX digim_dialogs_session_id_idx       ON digim_dialogs (session_id);
CREATE INDEX digim_dialogs_model_name_idx       ON digim_dialogs (model_name);
CREATE INDEX digim_dialogs_prompt_timestamp_idx ON digim_dialogs (prompt_timestamp);

-- digim_references
CREATE INDEX digim_references_dialog_id_idx        ON digim_references (dialog_id);
CREATE INDEX digim_references_rag_name_db_name_idx ON digim_references (rag_name, db_name);
```

### 4-5. digim_users（ログイン認証マスタ）

WebUIのログイン認証ソースとしてPostgreSQLを使う場合に作成します（`system.env` で `LOGIN_AUTH_METHOD=RDB` を指定）。アプリ初回起動時に `CREATE TABLE IF NOT EXISTS` で自動作成もされますが、明示的に作成しておくと運用が分かりやすいです。

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

### 4-6. digim_agent_personas（エージェントペルソナマスタ）

テンプレートエージェントに対して複数のペルソナ（人格・所属・権限制限）をPostgreSQL側で管理する場合に作成します（`system.env` で `AGENT_PERSONA_SOURCE=RDB` または `BOTH` を指定）。アプリ初回利用時に `CREATE TABLE IF NOT EXISTS` で自動作成もされます。

```sql
CREATE TABLE IF NOT EXISTS digim_agent_personas (
    persona_id     TEXT PRIMARY KEY,
    template_agent TEXT,           -- 紐付くテンプレートエージェントファイル名（任意）
    org            JSONB,          -- 所属組織（dict）。agent側ORGの全キーをこの値が同値で含めばマッチ
    company        TEXT,
    dept           TEXT,
    name           TEXT,
    act            TEXT,
    personality    JSONB,          -- 性別/Big5等の人格設定（agent.PERSONALITYを全置換）
    habits         JSONB,          -- ["ALL"]または実行可能なHABIT名のリスト
    knowledge      JSONB,          -- ["ALL"]または参照可能なKNOWLEDGE.RAG_NAMEのリスト
    define_code    JSONB,          -- 自由スキーマ（COMPANY_CODE/DEPT_CODE/EMP_CODE等）
    character_text TEXT,           -- キャラクターテキスト（直接記述）
    character_file TEXT,           -- character/フォルダ配下のファイル名（長文の場合）
    active         CHAR(1) DEFAULT 'Y'
);
```

Excel（`user/common/agent/persona_data/`）からの移行登録例:

```sql
INSERT INTO digim_agent_personas
  (persona_id, template_agent, org, company, dept, name, act, personality,
   habits, knowledge, define_code, character_text, character_file, active)
VALUES
  ('P0001', 'agent_X0Sample.json',
   '{"company":"デジMラボ","dept":"Consulting","BU":"DX"}'::jsonb,
   'デジMラボ', 'Consulting', 'DXコンサル太郎', 'DX戦略コンサルタント',
   '{"SEX":"男性","NATIONALITY":"Japanese","SPEAKING_STYLE":"Polite"}'::jsonb,
   '["ALL"]'::jsonb, '["ALL"]'::jsonb,
   '{"COMPANY_CODE":["DML"],"DEPT_CODE":["CON"],"EMP_CODE":["e0001"]}'::jsonb,
   'DXの推進力に長けた戦略コンサル。', '', 'Y')
ON CONFLICT (persona_id) DO UPDATE
SET template_agent=EXCLUDED.template_agent, org=EXCLUDED.org,
    company=EXCLUDED.company, dept=EXCLUDED.dept, name=EXCLUDED.name,
    act=EXCLUDED.act, personality=EXCLUDED.personality,
    habits=EXCLUDED.habits, knowledge=EXCLUDED.knowledge,
    define_code=EXCLUDED.define_code,
    character_text=EXCLUDED.character_text, character_file=EXCLUDED.character_file,
    active=EXCLUDED.active;
```

> WebUIのサイドバーから Excel をアップロードして RDB に一括 UPSERT するUIも今後追加予定（Phase 7）。`active='N'` で論理削除。

### 4-7. digim_agent_personas（エージェントペルソナマスタ）

1つのテンプレートエージェントに複数ペルソナ（人格・所属・権限制限）を登録し、ORGで切り替えて並列実行する場合に作成します（`system.env` で `AGENT_PERSONA_SOURCE=RDB` または `BOTH` を指定）。アプリ初回利用時に `CREATE TABLE IF NOT EXISTS` で自動作成もされます。

```sql
CREATE TABLE IF NOT EXISTS digim_agent_personas (
    persona_id     TEXT PRIMARY KEY,
    template_agent TEXT,                 -- 紐付くテンプレートエージェントファイル名
    org            JSONB,                -- 所属組織dict（agent側ORGの全キーをこの値が同値で含めばマッチ）
    company        TEXT,
    dept           TEXT,
    name           TEXT,
    act            TEXT,
    personality    JSONB,                -- agent.PERSONALITYを全置換
    habits         JSONB,                -- ["ALL"]または実行可能なHABIT名のリスト
    knowledge      JSONB,                -- ["ALL"]または参照可能なKNOWLEDGE.RAG_NAMEのリスト
    define_code    JSONB,                -- 自由スキーマ
    character_text TEXT,
    character_file TEXT,
    active         CHAR(1) DEFAULT 'Y'
);
```

Excel（`user/common/agent/persona_data/`）からの移行登録例:

```sql
INSERT INTO digim_agent_personas
  (persona_id, template_agent, org, company, dept, name, act, personality,
   habits, knowledge, define_code, character_text, character_file, active)
VALUES
  ('P0001', 'agent_X0Sample.json',
   '{"company":"デジMラボ","dept":"Consulting","BU":"DX"}'::jsonb,
   'デジMラボ', 'Consulting', 'DXコンサル太郎', 'DX戦略コンサルタント',
   '{"SEX":"男性","NATIONALITY":"Japanese","SPEAKING_STYLE":"Polite"}'::jsonb,
   '["ALL"]'::jsonb, '["ALL"]'::jsonb,
   '{"COMPANY_CODE":["DML"],"DEPT_CODE":["CON"],"EMP_CODE":["e0001"]}'::jsonb,
   'DXの推進力に長けた戦略コンサル。', '', 'Y')
ON CONFLICT (persona_id) DO UPDATE
SET template_agent=EXCLUDED.template_agent, org=EXCLUDED.org,
    company=EXCLUDED.company, dept=EXCLUDED.dept, name=EXCLUDED.name,
    act=EXCLUDED.act, personality=EXCLUDED.personality,
    habits=EXCLUDED.habits, knowledge=EXCLUDED.knowledge,
    define_code=EXCLUDED.define_code,
    character_text=EXCLUDED.character_text, character_file=EXCLUDED.character_file,
    active=EXCLUDED.active;
```

> エージェントJSONに `"ORG": [...]` と `"PERSONA_FILES": [...]` を定義することで、WebUIサイドバーにORG selectbox + Persona multiselectが出現します。

---

## 5. system.env の設定

`system.env_sample` をコピーして `system.env` を作成し、接続情報を記載します。

```env
# PostgreSQL接続情報
POSTGRES_HOST=localhost
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

# エージェントペルソナのソース（"EXCEL" or "RDB" or "BOTH"）
AGENT_PERSONA_SOURCE="RDB"
```

> DigitalMATSUMOTO 自体も Docker コンテナ上で動作している場合、`POSTGRES_HOST` は `localhost` ではなく Docker ネットワーク上のサービス名（例: `postgres`）を指定してください。
> `system.env` は `.gitignore` に含めてリポジトリにコミットしないこと。

---

## 6. 接続確認

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
)
print('接続OK:', conn.server_version)
conn.close()
"
```

> Azure と異なり `sslmode='require'` は不要です（ローカル接続のためデフォルトで無効）。

---

## 7. 初回データ投入

### 7-1. セッションデータのエクスポート

```bash
python3 DigiM_DB_Export.py
```

または WebUI の **Sessions → Export to DB** ボタンから実行できます。

### 7-2. 既存データの一括ベクトル化

エクスポート後、未ベクトル化レコードを一括処理します。

```bash
python3 -c "import DigiM_DB_Export as dmdbe; dmdbe.vectorize_dialogs()"
```

> Docker環境ではazure_ai拡張が使えないため、Pythonからベクトル化します。
> 以降の新規データはWebUIの **Export to DB** ボタン実行時に自動でベクトル化されます。

---

## コンテナの管理

```bash
# 停止
docker compose stop

# 停止 + コンテナ削除（データは保持）
docker compose down

# 停止 + コンテナ・ボリューム削除（データも消える）
docker compose down -v

# ログ確認
docker compose logs postgres
```

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
