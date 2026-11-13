**日本語** | **[English](SETUP_POSTGRESQL_AZURE.en.md)**

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
-- digim_sessions
CREATE INDEX IF NOT EXISTS digim_sessions_user_updated_idx
    ON digim_sessions (user_id, last_update_date DESC);

-- digim_dialogs
CREATE INDEX IF NOT EXISTS digim_dialogs_session_id_idx       ON digim_dialogs (session_id);
CREATE INDEX IF NOT EXISTS digim_dialogs_model_name_idx       ON digim_dialogs (model_name);
CREATE INDEX IF NOT EXISTS digim_dialogs_prompt_timestamp_idx ON digim_dialogs (prompt_timestamp);
-- The Agent section of the Performance Explorer scans one agent over a period
CREATE INDEX IF NOT EXISTS digim_dialogs_agent_resp_ts_idx
    ON digim_dialogs (agent_file, response_timestamp);
-- vectorize_dialogs() picks up the rows still waiting for an embedding
CREATE INDEX IF NOT EXISTS digim_dialogs_unvectorized_idx
    ON digim_dialogs (id) WHERE query_vec IS NULL;

-- digim_references
CREATE INDEX IF NOT EXISTS digim_references_dialog_id_idx        ON digim_references (dialog_id);
CREATE INDEX IF NOT EXISTS digim_references_rag_name_db_name_idx ON digim_references (rag_name, db_name);
CREATE INDEX IF NOT EXISTS digim_references_session_turn_idx
    ON digim_references (session_id, seq, sub_seq);
```

> `digim_dialogs_unvectorized_idx` は `query_vec` 列（pgvector）がある前提です。`vector` 型を外した構成ではその1行を省いてください。`CREATE INDEX IF NOT EXISTS` なので既存 DB に再実行しても安全です。

### 6-5. digim_users（ログイン認証マスタ）

> **`MST_STORE_METHOD`（`setting.yaml`）が `PostgreSQL` のときは、users も他のマスタと一緒に `digim_mst` に入ります**（下の 6-8 参照）。`LOGIN_AUTH_METHOD=RDB` で `digim_users` を使うのは `MST_STORE_METHOD` が `JSON` のときだけ効く旧方式です。両方指定すると `digim_mst` が優先され、警告ログが出ます。

WebUIのログイン認証ソースとしてAzure PostgreSQLを使う場合に作成します（`system.env` で `LOGIN_AUTH_METHOD=RDB` を指定）。アプリ初回起動時に `CREATE TABLE IF NOT EXISTS` で自動作成もされますが、明示的に作成しておくと運用が分かりやすいです。

```sql
CREATE TABLE IF NOT EXISTS digim_users (
    user_id    TEXT PRIMARY KEY,
    name       TEXT,
    pw         TEXT,           -- bcryptハッシュ。平文初回ログイン時は自動でハッシュ化される
    group_cd   JSONB,          -- 所属グループの配列（複数指定可、["Admin"]/["Sales","Marketing"]等）
    agent      TEXT,           -- デフォルトエージェントファイル名（"DEFAULT" or "agent_*.json"）
    allowed    JSONB,          -- UI機能の表示/非表示マップ
    defaults   JSONB           -- Conversation Settings の既定値（users.json の Defaults）
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

> `defaults` 列が無い既存テーブルは初回アクセス時に `ALTER TABLE ... ADD COLUMN IF NOT EXISTS defaults JSONB` で自動追加されます。以前のバージョンではこの列が無く、RDB モードでユーザーごとの既定値が失われていました。

> 平文パスワードを入れた場合、初回ログイン後にbcryptハッシュへ自動変換されます。最初からハッシュ値（`$2b$...`）を入れることも可能。

> 過去に `group_cd TEXT` で作成済みの場合は、JSONBへの型変換が必要です:
> ```sql
> ALTER TABLE digim_users ALTER COLUMN group_cd TYPE JSONB
> USING CASE WHEN group_cd IS NULL OR group_cd = '' THEN '[]'::jsonb
>            ELSE jsonb_build_array(group_cd) END;
> ```

### 6-6. digim_agent_personas（エージェントペルソナマスタ）

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
  ('P0001', 'agent_10Sample.json',
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

> エージェントJSONに `"ORG": [...]` と `"PERSONA_FILES": [...]` を定義することで、WebUIサイドバーにORG selectbox + Persona multiselectが出現します。`active='N'` で論理削除。`AGENT_PERSONA_SOURCE=BOTH` の場合は Excel + RDB をマージし、同 `persona_id` は RDB を優先します。

### 6-7. digim_user_memory_history / _nowaday / _persona（階層的ユーザーメモリ）

`system.env` で `USER_MEMORY_HISTORY_BACKEND` / `_NOWADAY_BACKEND` / `_PERSONA_BACKEND` のいずれかを `RDB` に設定すると、対応する3つのテーブルがアプリ初回アクセス時に `CREATE TABLE IF NOT EXISTS` で **自動作成** されます。事前にDDLを実行する必要はありませんが、運用時のバックアップ・権限設計用にスキーマを記載しておきます。

```sql
-- 短期メモリ（セッション単位の対話要約）
CREATE TABLE IF NOT EXISTS digim_user_memory_history (
    id              TEXT PRIMARY KEY,
    service_id      TEXT,
    user_id         TEXT,
    session_id      TEXT UNIQUE,
    session_name    TEXT,
    create_date     TIMESTAMP,
    topic           TEXT,
    excerpt         TEXT,
    axis_tags       JSONB,
    emotions        JSONB,         -- プルチック基本感情 + 二次感情のスコア
    confidence      DOUBLE PRECISION,
    source_seq      JSONB,
    active          CHAR(1) DEFAULT 'Y'
);
CREATE INDEX IF NOT EXISTS idx_digim_user_memory_history_user
    ON digim_user_memory_history (service_id, user_id, create_date DESC);

-- 中期メモリ（period=YYYY-MM 等のスナップショット）
CREATE TABLE IF NOT EXISTS digim_user_memory_nowaday (
    id                    TEXT PRIMARY KEY,
    service_id            TEXT,
    user_id               TEXT,
    period                TEXT,
    generated_at          TIMESTAMP,
    recurring_topics      JSONB,
    emerging              JSONB,
    declining             JSONB,
    shifts                JSONB,
    basic_emotions        JSONB,
    secondary_emotions    JSONB,
    evidence_session_ids  JSONB,
    summary_text          TEXT,
    token_count           INTEGER,
    active                CHAR(1) DEFAULT 'Y'
);
CREATE INDEX IF NOT EXISTS idx_digim_user_memory_nowaday_user
    ON digim_user_memory_nowaday (service_id, user_id, generated_at DESC);

-- 長期メモリ（ユーザー人物像。service_id + user_id でユニーク）
CREATE TABLE IF NOT EXISTS digim_user_memory_persona (
    service_id            TEXT,
    user_id               TEXT,
    generated_at          TIMESTAMP,
    last_reviewed         TIMESTAMP,
    role                  TEXT,
    expertise             JSONB,
    recurring_interests   JSONB,
    values_principles     JSONB,
    constraints           JSONB,
    communication_style   JSONB,
    avoid_topics          JSONB,
    big5                  JSONB,       -- score / confidence / status
    summary_text          TEXT,
    token_count           INTEGER,
    PRIMARY KEY(service_id, user_id)
);
```

> 各バックエンドは独立に切替可能（例: Persona のみ RDB、HistoryはEXCEL等）。EXCEL/NOTION バックエンドを選んだ層についてはこれらのテーブルは作成されません。


### 6-8. digim_mst（マスタデータ）

`setting.yaml` の `MST_STORE_METHOD` を `"PostgreSQL"` にすると、`user/common/mst/` 配下の7マスタ
（`users` / `rags` / `prompt_templates` / `notion_db` / `category_map` / `scheduled_jobs` / `session_summary_presets`）が
**まとめて**このテーブルに移ります。1マスタ＝1行で、JSON ファイルの中身がそのまま JSONB に入ります。
アプリ初回アクセス時に `CREATE TABLE IF NOT EXISTS` で自動作成されます。

```sql
-- Master data (users / rags / prompt_templates / notion_db / category_map /
-- scheduled_jobs / session_summary_presets) when MST_STORE_METHOD=PostgreSQL.
-- One row per master; the payload is the whole JSON document.
CREATE TABLE IF NOT EXISTS digim_mst (
    name        TEXT PRIMARY KEY,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

切り替えは設定だけでは移行されません。一度だけ取り込みます。

```bash
python3 DigiM_MstStore.py import          # JSON ファイル → digim_mst（7件）
python3 DigiM_MstStore.py import users    # 1件だけ
python3 DigiM_MstStore.py list            # 行とファイルの有無を一覧
python3 DigiM_MstStore.py export          # digim_mst → JSON ファイル（JSON に戻す／バックアップ）
```

> 取り込み後は行が正になります。JSON ファイルを手で直しても反映されないので、直したら `import` し直してください。
> 読み取りはプロセス内で `MST_STORE_CACHE_SEC`（既定 10 秒）キャッシュされます。保存したプロセスは即時、他プロセスは最大 10 秒で反映です。
> `sample_*.json` はアプリ同梱のサンプルで、常にファイルから読みます（DB には入れません）。

### 6-9. digim_chat_history_archive / digim_chat_history_archive_sessions（会話履歴の退避）

`SESSION_STORE_METHOD=PostgreSQL` のとき、履歴の退避（WebUI の History Retention、`python3 DigiM_HistoryArchive.py`、スケジューラの `history_archive`）で使います。初回の退避で `CREATE TABLE IF NOT EXISTS` により自動作成されます。

```sql
-- History retention (DigiM_HistoryArchive). Same shape as digim_chat_history,
-- plus when the copy was taken; updated_at is the live row's own timestamp.
CREATE TABLE IF NOT EXISTS digim_chat_history_archive (
    session_id  TEXT        NOT NULL,
    seq         INTEGER     NOT NULL,
    sub_seq     INTEGER     NOT NULL,
    data        JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Set when the turn was pruned out of live (kept here; restorable).
    pruned_at   TIMESTAMPTZ,
    pruned_zip  TEXT,
    PRIMARY KEY (session_id, seq, sub_seq)
);
-- One row per backed-up session: what was copied, and whether it was purged.
CREATE TABLE IF NOT EXISTS digim_chat_history_archive_sessions (
    session_id   TEXT PRIMARY KEY,
    rows         INTEGER     NOT NULL,
    content_md5  TEXT        NOT NULL,
    backed_up_at TIMESTAMPTZ NOT NULL,
    purged_at    TIMESTAMPTZ,
    zip_name     TEXT,
    restored_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_digim_chat_history_archive_sessions_purged
    ON digim_chat_history_archive_sessions (purged_at);
```

> 退避テーブルは `digim_chat_history` と同じ形で、セッションを丸ごと保持します。purge はここに複製して件数と内容ハッシュが一致したものだけをライブ側から削除します。
> 古いターンだけを消す prune では、消したターンの行に `pruned_at` / `pruned_zip` が入ります（以後の backup で消されず、復元するとまた空になります）。既存の表には次の backup で `ALTER TABLE … ADD COLUMN IF NOT EXISTS` により足されます。
> 分析用の `digim_sessions` / `digim_dialogs` / `digim_references` とは別物で、purge しても分析ミラーは消えません。
> 分析ミラーの退避先は次の 6-10 です。

### 6-10. digim_sessions_archive / digim_dialogs_archive / digim_references_archive（分析データの退避）

分析ミラー（`digim_sessions` / `digim_dialogs` / `digim_references`）の退避先です。保存方式（`SESSION_STORE_METHOD`）に関係なく、`POSTGRES_*` が設定されていれば History Retention の backup と purge のたびに更新されます。ここからは削除しないので、ミラーの古い行を消しても、ユーザー・エージェント・入力・出力・参照・ベクトルを使った分析を続けられます。

初回の backup で自動作成されます。列はミラーと同じで、ミラーの連番 `id` と `dialog_id` だけを持ちません。ミラーに列が増えると次回の backup で退避テーブルにも追加されるため、固定の DDL はありません。

| テーブル | 主キー | インデックス |
|---|---|---|
| `digim_sessions_archive` | `session_id` | `(user_id, last_update_date DESC)` / `(agent_file)` |
| `digim_dialogs_archive` | `(session_id, seq, sub_seq)` | `(agent_file, response_timestamp)` / `(prompt_timestamp)` / `(model_name)` |
| `digim_references_archive` | `(session_id, seq, sub_seq, ref_no)` | `(rag_name, db_name)` / `(chunk_id)` |
| `digim_steps_archive` | `(session_id, seq, sub_seq, step_no)` | `(step_kind, step_name)` / `(agent_file)` |

- `ref_no` はターンの中での参照の順番です。対話との結合は `(session_id, seq, sub_seq)` で行います。
- `digim_steps_archive` は `digim_steps`（6-12）の退避先です。ミラーに `digim_steps` がまだ無いときは作られません。
- `digim_sessions_archive` には退避側だけの列 `user_groups TEXT[]` があります。そのセッションのユーザーが属するグループを、最初の退避のときにユーザーマスタから記録します。一度入った値は書き換えません（ユーザーがマスタから消えても、別のグループへ移っても、過去のセッションのグループが残ります）。マスタにグループの無いユーザーは NULL のままで、後からグループが付けば次の backup で入ります。
- 各表の `archived_at` は、その行を最後に書いた時刻です。
- ベクトル（`query_vec` / `response_vec`）は、ミラー側で空になっても本文（`user_input` / `response_text`）が同じなら保持します。本文が変わった行はベクトルを捨て、ミラーで作り直された後の backup で入ります。
- ミラーの行を消すときは、セッションかターンの単位で消してください。参照だけをターンの途中で消すと `ref_no` がずれ、そのターンの退避が書き換わります。

```sql
-- ユーザー × エージェント別のターン数・参照数・ベクトル化済みのターン数
SELECT s.user_id, d.agent_file,
       COUNT(DISTINCT (d.session_id, d.seq, d.sub_seq)) AS turns,
       COUNT(r.ref_no) AS refs,
       COUNT(DISTINCT (d.session_id, d.seq, d.sub_seq)) FILTER (WHERE d.query_vec IS NOT NULL) AS vectorized
FROM digim_dialogs_archive d
JOIN digim_sessions_archive s USING (session_id)
LEFT JOIN digim_references_archive r USING (session_id, seq, sub_seq)
GROUP BY 1, 2;

-- 入力が似ている過去のターン（pgvector のコサイン距離。$1 は比較したい入力の埋め込み）
SELECT session_id, seq, sub_seq, user_input, query_vec <=> $1 AS distance
FROM digim_dialogs_archive
WHERE query_vec IS NOT NULL
ORDER BY query_vec <=> $1
LIMIT 10;
```

### 6-11. digim_pe_scores（Performance Explorer の達成度スコア）

Performance Explorer（User セクション → Achievement）で **Score** を初めて押したときに自動で作られます。手で作る必要はありません。

```sql
CREATE TABLE IF NOT EXISTS digim_pe_scores (
    theme_hash   TEXT NOT NULL,   -- 採点プロンプト＋お題の md5
    unit_kind    TEXT NOT NULL,   -- 'Session' / 'Input'
    unit_key     TEXT NOT NULL,   -- session_id、または session_id:seq
    content_hash TEXT NOT NULL,   -- 採点した入力テキストの md5
    model        TEXT NOT NULL,   -- エージェントファイル|エンジン名
    score        INTEGER,
    reason       TEXT,
    theme_text   TEXT,
    scored_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (theme_hash, unit_kind, unit_key, content_hash, model)
);
CREATE INDEX IF NOT EXISTS idx_digim_pe_scores_scored_at ON digim_pe_scores (scored_at);
```

LLM の採点結果のキャッシュです。同じお題・同じ入力・同じモデルの組は再実行しても LLM を呼びません。入力が変わる（セッションにターンが増える、期間を変える）と別の行として採点し直します。消しても分析データは失われず、次の採点で作り直されます。

### 6-12. digim_steps（サポートエージェント・SKILL などのステップ）

メインの LLM 呼び出しの前後で走ったものを、1ステップ1行で持つ分析ミラーの表です。ターン完了時のエクスポートと `resync` が最初に書くときに自動で作られます。手で作る必要はありません。

```sql
CREATE TABLE IF NOT EXISTS digim_steps (
    session_id      VARCHAR(64)  NOT NULL,
    seq             INTEGER      NOT NULL,
    sub_seq         INTEGER      NOT NULL,
    step_no         INTEGER      NOT NULL,   -- 回答の中での順番
    step_kind       VARCHAR(32)  NOT NULL,   -- job / thinking / rag_query / meta_search / web_search / skill / digest / rewrite
    step_name       VARCHAR(255),            -- SKILL 名、検索エンジン名、クエリ生成の番号など
    phase           VARCHAR(16),             -- SKILL の BEFORE / AFTER
    agent_file      VARCHAR(255),
    model_name      VARCHAR(128),
    duration_sec    DOUBLE PRECISION,
    prompt_tokens   INTEGER,
    response_tokens INTEGER,
    status          VARCHAR(32),             -- ok / error / applied / skipped / used / none
    detail          JSONB,                   -- 種類ごとの補足（Thinking が選んだ Habit・Book、SKILL の入出力文字数など）
    PRIMARY KEY (session_id, seq, sub_seq, step_no)
);
CREATE INDEX IF NOT EXISTS idx_digim_steps_kind_name ON digim_steps (step_kind, step_name);
CREATE INDEX IF NOT EXISTS idx_digim_steps_agent_file ON digim_steps (agent_file);
```

- 対話との結合は `(session_id, seq, sub_seq)` です。メインの LLM 呼び出し自体は `digim_dialogs` にあるので、ここには入りません。
- Thinking はターンに1回だけ走るので、ターンの先頭の回答行にだけ入ります。
- 履歴から作り直せる行なので、`resync` は履歴と違う行だけを書き換え、履歴より後ろの番号の行を消します。履歴が既に無いセッションの行は増えも減りもしません。
- History Retention の backup / purge で `digim_steps_archive` に写されます（6-10 参照）。

### 6-13. digim_chat_history（会話履歴のライブストア）

`setting.yaml` の `SESSION_STORE_METHOD: "PostgreSQL"` のとき、チャットの履歴を 1 エントリ 1 行で読み書きする表です。最初の書き込みで自動作成されます。DBA が事前に作る場合は以下を流してください。

```sql
CREATE TABLE IF NOT EXISTS digim_chat_history (
    session_id  TEXT        NOT NULL,
    seq         INTEGER     NOT NULL,
    sub_seq     INTEGER     NOT NULL,   -- 0 = ターンの SETTING 行、1 以上 = 対話のエントリ
    data        JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, seq, sub_seq)
);
CREATE INDEX IF NOT EXISTS idx_digim_chat_history_session
    ON digim_chat_history (session_id);
CREATE INDEX IF NOT EXISTS idx_digim_chat_history_session_seq
    ON digim_chat_history (session_id, seq DESC);
```

- 書き込みは変わった行だけを UPSERT します。`updated_at` はその行が最後に変わった時刻です（履歴の退避の判定に使います）。
- 分析ミラー（`digim_sessions` / `digim_dialogs` / `digim_references`）とは別の表です。分析はミラーと、その退避テーブル（6-10）を使います。

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
# 旧方式。setting.yaml の MST_STORE_METHOD=PostgreSQL が設定されていればそちらが優先され、この値は無視される
LOGIN_AUTH_METHOD="RDB"

# エージェントペルソナのソース（"EXCEL" or "RDB" or "BOTH"）
AGENT_PERSONA_SOURCE="RDB"
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

ターンが保存されるたびに、そのセッションが自動でエクスポートされます（`system.env` の `DB_EXPORT_AUTO`、既定 `Y`）。PostgreSQL を入れる前から使っていたセッションは、一度まとめて書き出します。

```bash
python3 DigiM_DB_Export.py full              # すべてのセッションの不足分を書き出す
python3 DigiM_DB_Export.py resync --archive  # 履歴と揃え、ターンが保存したベクトルを取り込み、分析データの退避テーブルへ写す
```

書き出しに失敗したセッションだけを拾い直すときは、WebUI のサイドバー Sessions → **Retry Pending Exports**（`python3 DigiM_DB_Export.py` と同じ）を使います。

### 10-2. 既存データの一括ベクトル化

ターンは実行時に入力と回答のベクトルを計算してセッションフォルダに保存しており、エクスポートと `resync` はそれを取り込みます（埋め込み API は呼びません）。保存されていない古いターン（入力は 2026-08-29 より前、回答はこの仕組みが入る前）だけが空のまま残るので、必要なら一括で埋めます（埋め込み API の料金がかかります）。

```bash
python3 DigiM_DB_Export.py vectorize
python3 DigiM_HistoryArchive.py backup       # 埋めたベクトルを分析データの退避テーブルへ写す
```

> 手順 7 のトリガーを有効にしている場合、ミラーに書かれた行はデータベース側で埋め込まれます。大量のエクスポートの間は無効にしておき、終わってから上のコマンドで埋めてください。

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
| `digim_chat_history` | 会話履歴のライブ R/W（`SESSION_STORE_METHOD=PostgreSQL`）。turn 1 行・JSONB |
| `digim_mst` | マスタデータ7件（`MST_STORE_METHOD=PostgreSQL`）。1マスタ 1 行・JSONB |
| `digim_chat_history_archive` / `_sessions` | 会話履歴の退避先とセッション単位の台帳（History Retention） |
| `digim_steps` | 各ターンで走ったサポートエージェント・Web 検索・SKILL・書き換え（1ステップ 1 行。エクスポートで自動作成） |
| `digim_sessions_archive` / `digim_dialogs_archive` / `digim_references_archive` / `digim_steps_archive` | 分析ミラーの退避先。削除しない（History Retention の backup / purge で更新） |
| `digim_pe_scores` | Performance Explorer の達成度スコアのキャッシュ（Achievement の Score で自動作成） |
| `digim_users` | ログイン認証マスタ（旧方式 `LOGIN_AUTH_METHOD=RDB`） |
| `digim_agent_personas` | エージェントペルソナマスタ（`AGENT_PERSONA_SOURCE=RDB`） |
| `digim_user_memory_history` / `_nowaday` / `_persona` | 階層的ユーザーメモリ（`USER_MEMORY_*_BACKEND=RDB`） |
