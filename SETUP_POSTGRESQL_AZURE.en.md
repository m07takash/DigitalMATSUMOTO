**[日本語](SETUP_POSTGRESQL_AZURE.md)** | **English**

# Azure PostgreSQL Setup Guide

A step-by-step guide for building the DigitalMATSUMOTO analytics DB from scratch on Azure Database for PostgreSQL.

---

## 1. Creating Azure Database for PostgreSQL

### 1-1. Create Resource

1. Sign in to [Azure Portal](https://portal.azure.com)
2. Select "Create a resource" → "Databases" → "Azure Database for PostgreSQL"
3. Select **Flexible server** and click "Create"

### 1-2. Basic settings

| Item | Value (example) |
|------|-------------|
| Subscription | Any |
| Resource group | Any (can be newly created) |
| Server name | `digim-rdb` (→ `digim-rdb.postgres.database.azure.com`) |
| Region | Japan East (any) |
| PostgreSQL version | 16 (recommended) |
| Workload type | Development (for small scale) |
| Admin user name | `digimatsuadmin` (any) |
| Password | Any (keep it noted) |

### 1-3. Network configuration

1. Open the "Networking" tab
2. Connectivity method: **Public access (allow all networks)**
3. SSL connection: **Enabled** (default)

### 1-4. Verify creation

- Click "Review + create" → "Create"
- After deployment, check the host name from the "Overview" of the resource page
  Example: `digim-rdb.postgres.database.azure.com`

---

## 2. Creating the Azure OpenAI Resource

### 2-1. Create Resource

1. Azure Portal → "Create a resource" → "Azure OpenAI"
2. Basic settings:

| Item | Value |
|------|-------|
| Region | East US / Sweden Central (more models available) |
| Pricing tier | Standard S0 |
| Network | Allow all networks |

3. After creation, note the following from "Keys and Endpoint":
   - **Endpoint**: `https://xxxx.openai.azure.com/`
   - **API key**: Key 1 or Key 2

### 2-2. Deploy Embedding Model (Azure AI Foundry)

1. From the Azure OpenAI resource page, click "Go to Azure AI Foundry portal"
2. Left menu "**Deployments**" → "+ Deploy model" → "Deploy base model"
3. Search for and select `text-embedding-3-large`
4. Deployment settings:

| Item | Value |
|------|-------|
| Deployment name | `text-embedding-3-large` |
| Deployment type | Standard |
| Tokens per minute rate limit | 150,000 or more recommended |

---

## 3. Configuring Server Parameters

In the Azure Portal, open the PostgreSQL resource → "Server Parameters".

Search for `azure.extensions`, add the following to the value and save, then restart the server.

```
AZURE_AI,VECTOR
```

---

## 4. Create Database

### 4-1. Connect with psql

```bash
psql "host=digim-rdb.postgres.database.azure.com port=5432 dbname=postgres user=digimatsuadmin sslmode=require"
```

### 4-2. Create database

```sql
CREATE DATABASE digim_analytics
    WITH ENCODING = 'UTF8'
         LC_COLLATE = 'en_US.utf8'
         LC_CTYPE   = 'en_US.utf8';
```

### 4-3. Connect to the created DB

```bash
psql "host=digim-rdb.postgres.database.azure.com port=5432 dbname=digim_analytics user=digimatsuadmin sslmode=require"
```

---

## 5. Enabling Extensions and Connection Settings

```sql
-- Enable extensions
CREATE EXTENSION IF NOT EXISTS azure_ai;
CREATE EXTENSION IF NOT EXISTS vector;

-- Configure Azure OpenAI connection settings
SELECT azure_ai.set_setting('azure_openai.endpoint', 'https://xxxx.openai.azure.com/');
SELECT azure_ai.set_setting('azure_openai.subscription_key', 'YOUR_API_KEY');

-- Connection check (a numeric array means success)
SELECT azure_openai.create_embeddings('text-embedding-3-large', 'test')::text;
```

---

## 6. Create Tables

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
    flg                       CHAR(1),       -- Logical-delete flag ('N' excludes from both display and reference)
    memory_flg                CHAR(1),       -- Memory-reference flag ('N' stays visible but is excluded from memory references)
    persona_id                VARCHAR(64),   -- Applied persona ID (empty when there is no persona)
    persona_name              VARCHAR(128),  -- Applied persona name (for display)
    chain_index               INTEGER,       -- Step index inside the Practice chain (0-based)
    chain_role                VARCHAR(32),   -- 'persona' / 'merge' / null (identifies steps in the PERSONAS parallel chain)
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

> If `digim_dialogs` has already been created without the `memory_flg` column, run:
> ```sql
> ALTER TABLE digim_dialogs ADD COLUMN IF NOT EXISTS memory_flg CHAR(1);
> UPDATE digim_dialogs SET memory_flg = 'Y' WHERE memory_flg IS NULL;
> ```
>
> To add Phase 6 multi-persona columns:
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

### 6-4. Create Indexes

```sql
-- digim_dialogs
CREATE INDEX digim_dialogs_session_id_idx       ON digim_dialogs (session_id);
CREATE INDEX digim_dialogs_model_name_idx       ON digim_dialogs (model_name);
CREATE INDEX digim_dialogs_prompt_timestamp_idx ON digim_dialogs (prompt_timestamp);

-- digim_references
CREATE INDEX digim_references_dialog_id_idx        ON digim_references (dialog_id);
CREATE INDEX digim_references_rag_name_db_name_idx ON digim_references (rag_name, db_name);
```

### 6-5. digim_users (Authentication master)

Create this when using Azure PostgreSQL as the WebUI login authentication source (set `LOGIN_AUTH_METHOD=RDB` in `system.env`). It is also auto-created via `CREATE TABLE IF NOT EXISTS` on first application startup, but creating it explicitly makes operations clearer.

```sql
CREATE TABLE IF NOT EXISTS digim_users (
    user_id    TEXT PRIMARY KEY,
    name       TEXT,
    pw         TEXT,           -- bcrypt hash. Plaintext on first login is auto-converted to a hash
    group_cd   JSONB,          -- Array of belonging groups (multiple allowed, e.g. ["Admin"] / ["Sales","Marketing"])
    agent      TEXT,           -- Default agent file name ("DEFAULT" or "agent_*.json")
    allowed    JSONB           -- Show/hide map for UI features
);
```

Example migration from existing JSON (`users.json`):

```sql
INSERT INTO digim_users (user_id, name, pw, group_cd, agent, allowed) VALUES
  ('ADMIN0001', 'Administrator', 'password', '["Admin"]'::jsonb, 'DEFAULT', '{}'::jsonb),
  ('USER0001', 'Consult Oh', 'password', '["User"]'::jsonb, 'DEFAULT', '{}'::jsonb)
ON CONFLICT (user_id) DO UPDATE
SET name=EXCLUDED.name, pw=EXCLUDED.pw, group_cd=EXCLUDED.group_cd,
    agent=EXCLUDED.agent, allowed=EXCLUDED.allowed;
```

> If a plaintext password is entered, it will be automatically converted to a bcrypt hash on first login. You can also insert hash values (`$2b$...`) from the start.

> If the table was previously created with `group_cd TEXT`, a type conversion to JSONB is required:
> ```sql
> ALTER TABLE digim_users ALTER COLUMN group_cd TYPE JSONB
> USING CASE WHEN group_cd IS NULL OR group_cd = '' THEN '[]'::jsonb
>            ELSE jsonb_build_array(group_cd) END;
> ```

### 6-6. digim_agent_personas (Agent persona master)

Create this when managing multiple personas (personality, affiliation, permission restrictions) for a template agent on the PostgreSQL side (set `AGENT_PERSONA_SOURCE=RDB` or `BOTH` in `system.env`). It is also auto-created via `CREATE TABLE IF NOT EXISTS` on first application use.

```sql
CREATE TABLE IF NOT EXISTS digim_agent_personas (
    persona_id     TEXT PRIMARY KEY,
    template_agent TEXT,           -- Associated template agent file name (optional)
    org            JSONB,          -- Belonging organization (dict). Matches when this dict equals all keys of the agent-side ORG
    company        TEXT,
    dept           TEXT,
    name           TEXT,
    act            TEXT,
    personality    JSONB,          -- Personality settings (sex / Big5 etc.). Fully replaces agent.PERSONALITY
    habits         JSONB,          -- ["ALL"] or list of executable HABIT names
    knowledge      JSONB,          -- ["ALL"] or list of referable KNOWLEDGE.RAG_NAME values
    define_code    JSONB,          -- Free-form schema (COMPANY_CODE / DEPT_CODE / EMP_CODE, etc.)
    character_text TEXT,           -- Character text (described inline)
    character_file TEXT,           -- File name under the character/ folder (for long descriptions)
    active         CHAR(1) DEFAULT 'Y'
);
```

Example migration from Excel (`user/common/agent/persona_data/`):

```sql
INSERT INTO digim_agent_personas
  (persona_id, template_agent, org, company, dept, name, act, personality,
   habits, knowledge, define_code, character_text, character_file, active)
VALUES
  ('P0001', 'agent_10Sample.json',
   '{"company":"DigiM Lab","dept":"Consulting","BU":"DX"}'::jsonb,
   'DigiM Lab', 'Consulting', 'DX Consultant Taro', 'DX strategy consultant',
   '{"SEX":"Male","NATIONALITY":"Japanese","SPEAKING_STYLE":"Polite"}'::jsonb,
   '["ALL"]'::jsonb, '["ALL"]'::jsonb,
   '{"COMPANY_CODE":["DML"],"DEPT_CODE":["CON"],"EMP_CODE":["e0001"]}'::jsonb,
   'A strategy consultant strong in driving DX initiatives.', '', 'Y')
ON CONFLICT (persona_id) DO UPDATE
SET template_agent=EXCLUDED.template_agent, org=EXCLUDED.org,
    company=EXCLUDED.company, dept=EXCLUDED.dept, name=EXCLUDED.name,
    act=EXCLUDED.act, personality=EXCLUDED.personality,
    habits=EXCLUDED.habits, knowledge=EXCLUDED.knowledge,
    define_code=EXCLUDED.define_code,
    character_text=EXCLUDED.character_text, character_file=EXCLUDED.character_file,
    active=EXCLUDED.active;
```

> By defining `"ORG": [...]` and `"PERSONA_FILES": [...]` in the agent JSON, an ORG selectbox + Persona multiselect appears in the WebUI sidebar. Use `active='N'` for logical delete. When `AGENT_PERSONA_SOURCE=BOTH`, Excel + RDB are merged, and entries with the same `persona_id` give precedence to RDB.

### 6-7. digim_user_memory_history / _nowaday / _persona (Hierarchical User Memory)

When any of `USER_MEMORY_HISTORY_BACKEND` / `_NOWADAY_BACKEND` / `_PERSONA_BACKEND` is set to `RDB` in `system.env`, the corresponding three tables are **auto-created** (on first access) via `CREATE TABLE IF NOT EXISTS`. There is no need to run DDL in advance, but the schemas are listed here for backup and permission design during operation.

```sql
-- Short-term memory (per-session dialogue summaries)
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
    emotions        JSONB,         -- Plutchik basic + secondary emotion scores
    confidence      DOUBLE PRECISION,
    source_seq      JSONB,
    active          CHAR(1) DEFAULT 'Y'
);

-- Mid-term memory (snapshots such as period=YYYY-MM)
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

-- Long-term memory (user persona profile; unique by service_id + user_id)
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

> Each backend can be switched independently (e.g., only Persona on RDB, History on EXCEL, etc.). For layers using the EXCEL/NOTION backend, these tables are not created.

---

## 7. Creating the Auto-Vectorization Trigger

Set up a trigger that automatically generates vectors on INSERT / UPDATE.

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

> `LEFT(text, 4000)` limits the text to 4000 characters as a countermeasure to the 8192 token limit, since one Japanese character is roughly 2 tokens.
> The trigger fires on INSERT/UPDATE, but is **disabled for large batch processing (via DigiM_DB_Export.py)**. In that case, vectorize using the Python script in step 9.

---

## 8. Configuring system.env

Copy `system.env_sample` to create `system.env` and fill in the connection details.

```env
# PostgreSQL connection info
POSTGRES_HOST=digim-rdb.postgres.database.azure.com
POSTGRES_PORT=5432
POSTGRES_DB=digim_analytics
POSTGRES_USER=digimatsuadmin
POSTGRES_PASSWORD=<your_password>

# Azure OpenAI (used for vectorization)
AZURE_OPENAI_ENDPOINT=https://xxxx.openai.azure.com/
AZURE_OPENAI_API_KEY=<your_api_key>
AZURE_OPENAI_EMBED_MODEL=text-embedding-3-large

# Switch the login authentication source ("JSON" or "RDB")
# When "RDB", uses the digim_users table over the POSTGRES_* connection above
LOGIN_AUTH_METHOD="RDB"

# Source for agent personas ("EXCEL" or "RDB" or "BOTH")
AGENT_PERSONA_SOURCE="RDB"
```

> Add `system.env` to `.gitignore` and do not commit it to the repository.

---

## 9. Connection check

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
print('Connection OK:', conn.server_version)
conn.close()
"
```

---

## 10. Initial data load

### 10-1. Export session data

```bash
python3 DigiM_DB_Export.py
```

Alternatively, you can run it from the WebUI **Sessions → Export to DB** button.

### 10-2. Bulk vectorization of existing data

After exporting, batch-process the unvectorized records.

```bash
python3 -c "import DigiM_DB_Export as dmdbe; dmdbe.vectorize_dialogs()"
```

> Subsequent new data is automatically vectorized when the WebUI **Export to DB** button is executed.

---

## Table structure overview

```
digim_sessions  (1)
    └── digim_dialogs  (N)  <- linked by session_id
            └── digim_references  (N)  <- linked by dialog_id
```

| Table | Description |
|---------|------|
| `digim_sessions` | Per-session metadata (name, user, agent, etc.) |
| `digim_dialogs` | Each turn of the conversation (input, response, token counts, RAG usage, etc.) |
| `digim_references` | Details of the RAG knowledge chunks referenced in each turn |
