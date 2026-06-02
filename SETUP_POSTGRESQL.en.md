**[日本語](SETUP_POSTGRESQL.md)** | **English**

# PostgreSQL Setup Guide (Docker Environment)

A step-by-step guide for building the DigitalMATSUMOTO analytics DB from scratch in an environment with only Docker installed.

---

## 1. Starting the PostgreSQL Container

### 1-1. Creating docker-compose.yml (recommended)

Create `docker-compose.yml` at the project root.

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

> The `pgvector/pgvector:pg16` image includes the `pgvector` extension out of the box.
> If vector search is not required, you can substitute `postgres:16`.

### 1-2. Start Container

```bash
docker compose up -d
```

### 1-3. Verify Startup

```bash
docker compose ps
# or
docker ps | grep digim-postgres
```

---

## 2. Connecting to the Database

### 2-1. Connect from inside the container with psql

```bash
docker exec -it digim-postgres psql -U digimatsuadmin -d digim_analytics
```

### 2-2. Connect from the host with psql (if psql is installed)

```bash
psql "host=localhost port=5432 dbname=digim_analytics user=digimatsuadmin"
```

---

## 3. Enabling Extensions

When using the `pgvector/pgvector` image, run the following.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

> If using the `postgres:16` image, the extension is not included, so either skip this or remove the `vector` type from the column definitions.

---

## 4. Create Tables

Run the following while connected via psql.

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

> `vector(3072)` matches the dimensionality of `text-embedding-3-large`. If vector search is not required, remove the corresponding lines.

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

### 4-4. Create Indexes

```sql
-- digim_dialogs
CREATE INDEX digim_dialogs_session_id_idx       ON digim_dialogs (session_id);
CREATE INDEX digim_dialogs_model_name_idx       ON digim_dialogs (model_name);
CREATE INDEX digim_dialogs_prompt_timestamp_idx ON digim_dialogs (prompt_timestamp);

-- digim_references
CREATE INDEX digim_references_dialog_id_idx        ON digim_references (dialog_id);
CREATE INDEX digim_references_rag_name_db_name_idx ON digim_references (rag_name, db_name);
```

### 4-5. digim_users (Authentication master)

Create this when using PostgreSQL as the WebUI login authentication source (set `LOGIN_AUTH_METHOD=RDB` in `system.env`). It is also auto-created via `CREATE TABLE IF NOT EXISTS` on first application startup, but creating it explicitly makes operations clearer.

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

### 4-6. digim_agent_personas (Agent persona master)

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

### 4-7. digim_user_memory_history / _nowaday / _persona (Hierarchical User Memory)

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

## 5. Configuring system.env

Copy `system.env_sample` to create `system.env` and fill in the connection details.

```env
# PostgreSQL connection info
POSTGRES_HOST=localhost
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

> If DigitalMATSUMOTO itself is also running in a Docker container, specify `POSTGRES_HOST` as the service name on the Docker network (e.g., `postgres`) rather than `localhost`.
> Add `system.env` to `.gitignore` and do not commit it to the repository.

---

## 6. Connection check

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
print('Connection OK:', conn.server_version)
conn.close()
"
```

> Unlike Azure, `sslmode='require'` is not needed (disabled by default for local connections).

---

## 7. Initial data load

### 7-1. Export session data

```bash
python3 DigiM_DB_Export.py
```

Alternatively, you can run it from the WebUI **Sessions → Export to DB** button.

### 7-2. Bulk vectorization of existing data

After exporting, batch-process the unvectorized records.

```bash
python3 -c "import DigiM_DB_Export as dmdbe; dmdbe.vectorize_dialogs()"
```

> Since the azure_ai extension is not available in the Docker environment, vectorization is performed from Python.
> Subsequent new data is automatically vectorized when the WebUI **Export to DB** button is executed.

---

## Container management

```bash
# Stop
docker compose stop

# Stop + remove containers (data is preserved)
docker compose down

# Stop + remove containers and volumes (data is also wiped)
docker compose down -v

# View logs
docker compose logs postgres
```

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
