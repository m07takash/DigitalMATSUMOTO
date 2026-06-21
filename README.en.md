**[日本語](README.md)** | **English**

# Digital MATSUMOTO

<details>
<summary><strong>📑 Table of Contents (click to expand)</strong></summary>

- [Introduction](#introduction)
- [Design principles of this program](#design-principles-of-this-program)
- [Reference documents](#reference-documents)
- [Architecture overview](#architecture-overview)
- [Main modules](#main-modules)
- [Directory structure](#directory-structure)
- [Environment setup / installation](#environment-setup--installation)
  - [Prerequisites](#prerequisites)
  - [1. Clone the repository](#1-clone-the-repository)
  - [2. Build the Docker image](#2-build-the-docker-image)
  - [3. Start the container](#3-start-the-container)
  - [4. Configure environment variables](#4-configure-environment-variables)
  - [5. Launching the application (executed inside the container)](#5-launching-the-application-executed-inside-the-container)
  - [6. Verify operation](#6-verify-operation)
  - [7. Configuring Nginx reverse proxy (for production)](#7-configuring-nginx-reverse-proxy-for-production)
  - [8. Deploying to a closed network (Azure)](#8-deploying-to-a-closed-network-azure)
- [Setup guide](#setup-guide)
  - [Master data configuration](#master-data-configuration)
  - [RAG data configuration](#rag-data-configuration)
  - [Agent configuration](#agent-configuration)
  - [Practice configuration](#practice-configuration)
  - [Web search configuration](#web-search-configuration)
  - [Tool Plugin System (SKILL / Tool / Slash Command)](#tool-plugin-system-skill--tool--slash-command)
  - [Citation injection](#citation-injection)
  - [Auto URL fetching (as attachments)](#auto-url-fetching-as-attachments)
  - [User Memory (Hierarchical User Understanding)](#user-memory-hierarchical-user-understanding)
  - [Background job management](#background-job-management)
  - [How to launch](#how-to-launch)
- [Knowledge Explorer](#knowledge-explorer)
  - [Selecting a data source](#selecting-a-data-source)
  - [1. Overall](#1-overall)
  - [2. Trend (formerly Time-Series Analysis)](#2-trend-formerly-time-series-analysis)
  - [3. Topic (formerly Sensitivity Analysis)](#3-topic-formerly-sensitivity-analysis)
  - [4. Ask Agent](#4-ask-agent)
  - [PageIndex](#pageindex)
  - [Export / Report](#export--report)
  - [Session management](#session-management)
- [User Memory Explorer](#user-memory-explorer)
- [Agent Performance Explorer (APE)](#agent-performance-explorer-ape)
  - [Data sources (precedence: PG → live folders → archives)](#data-sources-precedence-pg--live-folders--archives)
  - [Tab 1: Overview](#tab-1-overview)
  - [Tab 2: Knowledge / Book Utilization](#tab-2-knowledge--book-utilization)
  - [Integration with Chat tab Analytics Results](#integration-with-chat-tab-analytics-results)
- [Chat tab — other features](#chat-tab--other-features)
  - [Detail Information tabs](#detail-information-tabs)
  - [Compare Agent — regression with KNOWLEDGE / BOOK exclusion](#compare-agent--regression-with-knowledge--book-exclusion)
  - [Draft input mode](#draft-input-mode)
- [Batch Test (bulk Q&A evaluation)](#batch-test-bulk-qa-evaluation)
  - [Input Excel format](#input-excel-format)
  - [Output Excel format](#output-excel-format)
  - [Key features](#key-features)
  - [Result Analysis (instant)](#result-analysis-instant)
  - [LLM critique (on-demand)](#llm-critique-on-demand)
  - [Implementation notes](#implementation-notes)
- [Evaluation](#evaluation)
  - [Plugin architecture](#plugin-architecture)
  - [UI flow](#ui-flow)
  - [PersonalEvaluation plugin](#personalevaluation-plugin)
  - [Adding a new evaluation](#adding-a-new-evaluation)
- [API Reference](#api-reference)
  - [Endpoint list](#endpoint-list)
  - [POST /run — Send a message](#post-run--send-a-message)
  - [Execution examples](#execution-examples)
  - [LINE integration usage example](#line-integration-usage-example)

</details>

## Introduction

This program is published under the Apache 2.0 License and commercial use is permitted.
However, the developer assumes no responsibility for any user-side activities conducted using this program; please use it strictly at your own risk.

While this program has been used in business contexts, it is developed primarily for research or PoC purposes, and program updates are made at the developer's discretion.
When using it in an actual business setting, we recommend that you build and operate it in the optimal system environment, at your own judgment and responsibility, while complying with the Apache 2.0 License.

Digital MATSUMOTO lab LLC

## Design principles of this program

- The main purpose is not work efficiency, but whether AI can reproduce human knowledge
- Make knowledge contributions observable
- Autonomy is not the goal. The thesis is whether humans themselves can grow while using AI
- Not dependent on any specific LLM
- Carefully crafted context design
- Avoid frameworks like LangChain or llama index (call the bare LLM API directly)
- A configuration that can run even in personal environments

## Reference documents

- [Overview and architecture description(JPN)](https://github.com/m07takash/DigitalMATSUMOTO/blob/main/docs/%E3%83%87%E3%82%B8%E3%82%BF%E3%83%ABMATSUMOTO%E3%81%AE%E6%A6%82%E8%A6%81%E3%81%A8%E3%82%A2%E3%83%BC%E3%82%AD%E3%83%86%E3%82%AF%E3%83%81%E3%83%A3.pdf)
- [Feature list (conceptual level)](docs/FEATURE_LIST.md)

## Architecture overview

```
[Streamlit UI / FastAPI / Jupyter Notebook]
          |
   DigiM_Execute.py        # Execution orchestration
          |
   DigiM_Agent.py          # Agent invocation
   DigiM_Context.py        # Context generation / RAG query
   DigiM_Session.py        # Session / chat history management
          |
   DigiM_FoundationModel.py  # LLM abstraction layer
   DigiM_Tool.py             # Tools (registered functions)
          |
[GPT / Gemini / Claude / Grok]
```

Agent settings (Personality, LLM in use, Knowledge) are managed in `user/common/agent/*.json`,
and the context is dynamically generated by combining prompt templates (`user/common/mst/prompt_templates.json`)
and RAG (ChromaDB).

## Main modules

| Module | Role |
|-----------|------|
| `DigiM_Execute.py` | Main execution engine |
| `DigiM_Session.py` | Session / chat history management |
| `DigiM_Context.py` | Context generation / RAG processing |
| `DigiM_FoundationModel.py` | LLM abstraction (multi-LLM support) |
| `DigiM_Agent.py` | Agent settings management (template + persona override support) |
| `DigiM_AgentPersona.py` | Master of Agent Personas (Excel/RDB) |
| `DigiM_Auth.py` | Login user master (switchable JSON / RDB backend) |
| `DigiM_Tool.py` | Tool set (analytics, history operations, persona integration, etc.) |
| `DigiM_Util.py` | Common functions |
| `DigiM_Notion.py` | Notion API integration |
| `WebDigiMatsuAgent.py` | WebUI screen |
| `DigiM_API.py` | FastAPI endpoints |
| `DigiM_DB_Export.py` | PostgreSQL export / vectorization |
| `DigiM_VAnalytics.py` | Knowledge usage analysis |
| `DigiM_GeneFeedback.py` | User feedback (CSV/Notion storage) |
| `DigiM_UserMemory.py` | User Memory (History/Nowaday/Persona) storage abstraction (Excel/Notion/RDB) |
| `DigiM_UserMemorySetting.py` | User Memory On/Off 2-layer resolution (user master / system). Layers are stored in `Allowed["User Memory Layers"]` of `users.json` |
| `DigiM_UserMemoryBuilder.py` | "Information about the dialogue partner" context synthesis (prompt insertion before Knowledge). History uses MeCab x tag x time hybrid search |
| `DigiM_Scheduler.py` | Background scheduler (APScheduler / multi-job support / reloadable without restart) |
| `DigiM_ScheduledJobs.py` | Scheduled jobs master CRUD (read/write `user/common/mst/scheduled_jobs.json` and record execution results) |
| `DigiM_GeneUserMemory.py` | User Memory generation / diff merge / auto-approval / verification loop update / emotion/Big5 backfill for existing records (with CLI) |
| `DigiM_UserMemoryExplorer.py` | Backend of User Memory Explorer (cohort filtering / 3-layer aggregation / interest topic transitions / context synthesis for dialogue) |
| `DigiM_GeneUserDialog.py` | (Deprecated) Legacy user dialog storage. Backward-compat shim to `DigiM_GeneUserMemory.py` |
| `DigiM_SupportEval.py` | Support Agent performance evaluation |
| `DigiM_Benchmark.py` | Support Agent speed / output comparison benchmark (CLI) |
| `DigiM_JobRegistry.py` | Background thread registration / cancellation (for stopping from the UI) |
| `DigiM_UrlFetch.py` | Auto-fetch of http(s) links in chat input (with subpage crawling support) |

## Directory structure

```
DigitalMATSUMOTO/
├── user/
│   ├── common/
│   │   ├── agent/                # Agent configuration JSON
│   │   ├── agent/persona_data/   # Agent persona xlsx (for multi-persona parallel execution)
│   │   ├── practice/             # Practice configuration JSON
│   │   ├── tool/                 # Tool plugins (.py, auto-loaded) — drop a .py file here to add a new tool/SKILL
│   │   ├── mst/                  # Master data (users, RAG, prompts, etc.)
│   │   ├── rag/chromadb/         # Vector DB (ChromaDB)
│   │   ├── rag/pages/            # PageIndex RAG (.md + _index.json)
│   │   ├── csv/                  # CSV data for RAG
│   │   ├── csv/pageindex/        # Excel-input PageIndex (Excel + per-page body files)
│   │   ├── analytics/knowledge_explorer/ # Saved sessions for Knowledge Explorer
│   │   ├── user_memory/          # User Memory (storage for history/nowaday/persona.xlsx, etc.)
│   │   └── temp/                 # Temp files for chat attachments / URL fetches, etc.
│   ├── session*/                 # Session data (chat history)
│   └── archive/                  # Session archive (ZIP)
├── test/                         # Benchmark / evaluation I/O (questions.xlsx, etc.)
├── setting.yaml                  # System settings such as folder paths
├── system.env                    # Environment variables for API keys, etc. (create by hand)
├── system.env_sample             # Template for environment variables
├── requirements.txt              # Python package list
└── Dockerfile                    # Docker build definition
```

## Environment setup / installation

### Prerequisites

- Docker is installed
- You have obtained an API key for one of the LLMs (OpenAI / Google Gemini / Anthropic Claude / Grok)

### 1. Clone the repository

```bash
git clone https://github.com/m07takash/DigitalMATSUMOTO.git
cd DigitalMATSUMOTO
```

### 2. Build the Docker image

```bash
docker build -t digimatsumoto .
```

The build automatically installs the following:
- Python3 and all packages listed in `requirements.txt`
- MeCab (Japanese morphological analyzer) + NEologd dictionary
- Japanese fonts (IPAex, Noto CJK)

### 3. Start the container

First, start the container in a standby state without launching the app (Streamlit is launched manually after the environment variables are configured).

```bash
docker run -dit --name digimatsumoto \
  -p 8501:8501 \
  -p 8899:8899 \
  -v $(pwd):/app/DigitalMATSUMOTO \
  -w /app/DigitalMATSUMOTO \
  digimatsumoto \
  bash
```

| Port | Purpose |
|-------|------|
| 8501 | Streamlit WebUI |
| 8899 | FastAPI endpoint |

Note: Change the port numbers as needed.

Thanks to the volume mount (`-v $(pwd):/app/DigitalMATSUMOTO`), file edits on the host side are immediately reflected inside the container. If you create the `system.env` in the next step on the host side, it can be read directly from the container.

### 4. Configure environment variables

Copy `system.env_sample` to create `system.env`, then set the API keys and so on.

```bash
cp system.env_sample system.env
```

**Required settings:**

| Variable | Description |
|------|------|
| `OPENAI_API_KEY` | OpenAI API key (used for GPT and Embedding models) |

> Depending on the LLM you use, also set `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, and `XAI_API_KEY`.

**Basic settings:**

| Variable | Default | Description |
|------|-----------|------|
| `TIMEZONE` | `Asia/Tokyo` | Timezone |
| `LOGIN_ENABLE_FLG` | `N` | Enable login authentication (`Y` to enable) |
| `LOGIN_AUTH_METHOD` | `JSON` | Login authentication method. `JSON`: uses `USER_MST_FILE` / `RDB`: uses the PostgreSQL `digim_users` table (the table is auto-created on first access) |
| `AGENT_PERSONA_SOURCE` | `EXCEL` | Source of Agent Personas. `EXCEL`: xlsx under `user/common/agent/persona_data/` / `RDB`: `digim_agent_personas` table / `BOTH`: merged |
| `USER_MEMORY_HISTORY_BACKEND` / `NOWADAY_BACKEND` / `PERSONA_BACKEND` | `EXCEL` | Storage backend for each User Memory layer (EXCEL/NOTION/RDB). See "User Memory (Hierarchical User Understanding)" for details |
| `USER_MEMORY_DEFAULT_LAYERS` | `persona,nowaday,history` | System default enabled layers for User Memory (empty string `""` turns all off) |
| `USER_MEMORY_AUTO_APPROVE_THRESHOLD` | `0.8` | Threshold for auto-approving Persona items by confidence |
| `USER_MEMORY_PERSONA_MAX_CHARS_PER_FIELD` | `300` | Max character count retained per Persona field |
| `USER_MEMORY_HISTORY_MAX_CHARS` | `800` | Max total character count for History memory injection |
| `EMBEDDING_MODEL` | `text-embedding-3-large` | Embedding vector model (also used to select the tiktoken tokenizer) |
| `EMBED_PROVIDER` | `openai` | Embedding generation provider: `openai` or `azure`. When `azure`, used together with `AZURE_OPENAI_*` and `AZURE_OPENAI_EMBED_MODEL` |
| `TRANSCRIBE_PROVIDER` | `openai` | Speech-to-text (Whisper) provider: `openai` or `azure`. When `azure`, used together with `AZURE_OPENAI_WHISPER_MODEL` |
| `WEB_TITLE` | `Digital Twin` | Title of the WebUI |
| `WEB_DEFAULT_AGENT_FILE` | `agent_10Sample.json` | Default agent in the WebUI |
| `WEB_MAX_UPLOAD_SIZE` | `500` | File upload limit (MB) |

**Master file settings:**

| Variable | Default | Description |
|------|-----------|------|
| `USER_MST_FILE` | `sample_users.json` | User master |
| `RAG_MST_FILE` | `sample_rags.json` | RAG master |
| `PROMPT_TEMPLATE_MST_FILE` | `sample_prompt_templates.json` | Prompt templates |

**Optional settings (PostgreSQL):**

To use the analytics DB, configure the following (see `SETUP_POSTGRESQL.en.md` / `SETUP_POSTGRESQL_AZURE.en.md` for details).

| Variable | Description |
|------|------|
| `POSTGRES_HOST` | Host name |
| `POSTGRES_PORT` | Port number |
| `POSTGRES_DB` | Database name |
| `POSTGRES_USER` | User ID |
| `POSTGRES_PASSWORD` | Password |

**Optional settings (Notion integration):**

Configure when using Notion as the storage destination for feedback or RAG data.

| Variable | Description |
|------|------|
| `NOTION_VERSION` | Notion API version (`2022-06-28`) |
| `NOTION_TOKEN` | Notion integration token |
| `NOTION_MST_FILE` | Notion DB definition file (`sample_notion_db.json`) |

**Optional settings (Azure OpenAI Service):**

Configure when using deployments such as gpt-* / dall-e / gpt-image-* on Azure as chat/image generation engines, and when running embedding or audio transcription via Azure.

| Variable | Description |
|------|------|
| `AZURE_OPENAI_ENDPOINT` | Endpoint URL of the Azure OpenAI resource |
| `AZURE_OPENAI_API_KEY` | API key |
| `AZURE_OPENAI_API_VERSION` | API version for the chat/image engine (default `2024-12-01-preview` / required for gpt-5 series). Per-agent overrides go in `PARAMETER.api_version` |
| `AZURE_OPENAI_EMBED_MODEL` | Embedding deployment name (used when `EMBED_PROVIDER="azure"`) |
| `AZURE_OPENAI_WHISPER_MODEL` | Whisper deployment name (used when `TRANSCRIBE_PROVIDER="azure"`) |

In the agent JSON, specify `FUNC_NAME: "generate_response_T_azure_openai"` under `ENGINE.LLM`, and `"generate_image_azure_dalle"` under `ENGINE.IMAGEGEN`. In `MODEL`, put the **deployment name on Azure**. For `gpt-5*` / `o1` / `o3` / `o4` series, `max_tokens` is automatically translated to `max_completion_tokens`.

**OpenAI / Azure combination examples:**

| Mode | env settings |
|---|---|
| OpenAI only (legacy) | Nothing to change (`EMBED_PROVIDER` / `TRANSCRIBE_PROVIDER` may be omitted; only `OPENAI_API_KEY` is required) |
| Fully Azure | `EMBED_PROVIDER="azure"` / `TRANSCRIBE_PROVIDER="azure"` + the full `AZURE_OPENAI_*` set. In the agent JSON, choose the `generate_response_T_azure_openai`-family. The OpenAI WebSearch tool has no Azure equivalent and should not be used |
| Mixed | `EMBED_PROVIDER` / `TRANSCRIBE_PROVIDER` can be switched independently per subsystem (e.g., chat=OpenAI, embedding=Azure) |

### 5. Launching the application (executed inside the container)

Once you have finished configuring `system.env`, enter the container and start Streamlit.

```bash
docker exec -it digimatsumoto bash
```

Inside the container:

```bash
streamlit run WebDigiMatsuAgent.py --server.port 8501 --server.address 0.0.0.0
```

> Without `--server.address 0.0.0.0`, it may not be accessible from outside the container (the host's browser).

To launch with a one-liner (from outside, without entering the container):

```bash
docker exec -d digimatsumoto streamlit run WebDigiMatsuAgent.py --server.port 8501 --server.address 0.0.0.0
```

**Launching multiple services (WebUI + FastAPI) together:**

Copy `startup.sh_sample` to `startup.sh` and use it (`startup.sh` is environment-dependent and is already `.gitignore`d). The sample launches `WebDigiMatsuAgent.py` (standard WebUI) + FastAPI.

```bash
# Copy the template on the host (edit as needed)
cp startup.sh_sample startup.sh

# Execute inside the container
docker exec -it digimatsumoto bash startup.sh
```

> **Suppressing auto-start (when bootstrapping a new environment or debugging):** The Dockerfile's default `CMD` is `startup.sh`, which auto-starts all services. If you run the container without overriding the CMD (e.g. running a pre-built image with `docker run` directly) and want it to idle first, pass `DIGIM_AUTOSTART=false`. `startup.sh` then idles with `tail -f /dev/null` instead of starting services, so the container stays up and no Streamlit Rerun loop occurs. After verifying, run `./startup.sh` manually to start normally.
>
> ```bash
> # Start in an idle state (auto-start OFF), then exec in to debug manually
> docker run -d --name digimatsumoto -p 8501:8501 -p 8899:8899 \
>   -e DIGIM_AUTOSTART=false --env-file ./system.env digimatsumoto
> docker exec -it digimatsumoto bash
> ```
>
> Without `DIGIM_AUTOSTART`, all services auto-start as before.

### 6. Verify operation

Access `http://localhost:8501` in your browser; if the WebUI is displayed, you are done.

### 7. Configuring Nginx reverse proxy (for production)

When using HTTPS or operating under a domain, place Nginx as a reverse proxy. The following is an example configuration with Azure VM + Let's Encrypt.

#### Global settings (`/etc/nginx/nginx.conf`)

Add the following inside the `http` block. This setting is required if you get errors (413) when uploading files (PPTX/PDF, etc.).

```nginx
http {
    client_max_body_size 500m;  # Default: 1m
    ...
}
```

#### Site settings (`/etc/nginx/sites-available/your-site`)

```nginx
# HTTP -> HTTPS redirect
server {
    listen 80;
    server_name your-domain.example.com;

    # For Let's Encrypt certificate renewal
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS main site
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

        # WebSocket support (required by Streamlit)
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

#### Enable and reload

```bash
# Enable the site configuration
sudo ln -s /etc/nginx/sites-available/your-site /etc/nginx/sites-enabled/

# Syntax check
sudo nginx -t

# Reload
sudo systemctl reload nginx
```

> **About WebSocket support:** Streamlit communicates over WebSocket, so the `proxy_http_version 1.1` setting and the `Upgrade` / `Connection` headers are required. Without them the WebUI does not function correctly.

> **About timeouts:** LLM execution can take tens of seconds to a few minutes, so set `proxy_read_timeout` / `proxy_send_timeout` to a sufficiently large value (300s or more).

### 8. Deploying to a closed network (Azure)

To deploy into a closed (air-gapped) Azure environment where pip / Git / apt are unavailable, carry a pre-built Docker image over in its entirety from an internet-connected environment. For the full procedure — saving and splitting the image as a tar, transferring and loading it, and switching to Azure OpenAI (changing `FUNC_NAME` in the agent definitions) — see [SETUP_OFFLINE_DOCKER.en.md](SETUP_OFFLINE_DOCKER.en.md).

---

## Setup guide

### Master data configuration

Place the master data under `user/common/mst/`. Files prefixed with `sample_` are bundled as samples and work as-is, but typically you copy and customize them as follows.

| Sample file | Operational file | Purpose |
|----------------|------------|------|
| `sample_users.json` | `users.json` | User master |
| `sample_rags.json` | `rags.json` | RAG master |
| `sample_prompt_templates.json` | `prompt_templates.json` | Prompt templates |
| `sample_category_map.json` | `category_map.json` | Category definitions |
| `sample_notion_db.json` | `notion_db.json` | Notion DB definitions |

To switch to operational files, change the master file settings in `system.env`.

```env
USER_MST_FILE=users.json
RAG_MST_FILE=rags.json
PROMPT_TEMPLATE_MST_FILE=prompt_templates.json
```

#### User master

```json
{
  "USER0001": {
    "Name": "Display Name",
    "PW": "password",
    "Group": ["User"],
    "Agent": "agent_10Sample.json",
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
      "Knowledge Explorer": true,
      "Scheduler": false,
      "User Memory": true,
      "User Memory Layers": ["persona", "nowaday", "history"]
    }
  }
}
```

| Item | Description |
|------|------|
| `Name` | User name displayed in the WebUI |
| `PW` | Password (automatically converted to a bcrypt hash on first login) |
| `Group` | User groups (array; see below) |
| `Agent` | Agent file name used by default |
| `Allowed` | Controls show/hide for each feature (`true`/`false`) |

**Allowed setting items:**

| Key | Description |
|------|------|
| `Session Archive` | Session archive feature |
| `RAG Management` | RAG data management (Update RAG Data, etc.) |
| `Exec Setting` | Show/change execution settings |
| `RAG Setting` | Show/change RAG settings |
| `Feedback` | Feedback feature |
| `Details` | Show detailed information |
| `Analytics Knowledge` | Knowledge usage analysis |
| `Analytics Compare` | Agent comparison analysis |
| `WEB Search` | Web search feature |
| `Book` | Book (reference information) feature |
| `Download Md` | Markdown download |
| `Knowledge Explorer` | RAG data analysis screen (see below) |
| `Scheduler` | Schedule management screen (register, edit, and immediately execute background jobs) |
| `User Memory` | View / save / verification loop for User Memory (Hierarchical User Understanding) |
| `User Memory Explorer` | User Memory analytics screen (cross-view / deep-dive + memory-grounded dialogue; see below). Default `false` |
| `User Memory Layers` | (Non-bool; array.) Subset of `["persona","nowaday","history"]` enabled for this user. If unset, falls back to `USER_MEMORY_DEFAULT_LAYERS` |

> Users in the Admin group can access all features regardless of the `Allowed` settings.

**About passwords:**
- If the password is in plain text on first login, it is automatically converted to a bcrypt hash and saved
- You can change the password from the "Change Password" tab on the WebUI login screen

**About Group:**
- Array form (e.g. `["User"]`, `["Sales", "Marketing"]`) supports **multiple groups**. For backward compatibility a string is also accepted (normalized to an array internally)
- If any element of the array is `"Admin"`, the user can view all users' chat history and select all agents
- If individual group names are set, only agents whose `GROUP` matches one of those names are selectable (**OR match**: agents matching any of your groups are eligible)
- To enable login authentication, set `LOGIN_ENABLE_FLG=Y` in `system.env`
- To switch the authentication source to PostgreSQL, set `LOGIN_AUTH_METHOD=RDB`. The `digim_users` table will be auto-created (columns: `user_id`/`name`/`pw`/`group_cd[JSONB]`/`agent`/`allowed[JSONB]`)

#### Prompt templates

Define prompt templates and speaking styles in `prompt_templates.json`.

- **PROMPT_TEMPLATE**: Templates of instructions to the LLM (Normal Template, Chat Template, etc.)
- **SPEAKING_STYLE**: Speaking style settings (Polite (teineigo), Honorific (keigo), Samurai style (bushigo), etc.)

#### Category map

Define category names and display colors used in feedback and analytics in `category_map.json`.

```json
{
  "Category": {
    "AI": "AI",
    "Business": "Business",
    "Unset": "Unset"
  },
  "CategoryColor": {
    "AI": "purple",
    "Business": "blue",
    "Unset": "lightgray"
  }
}
```

### RAG data configuration

Building RAG data takes three steps: "Data preparation" -> "RAG master configuration" -> "Vector DB generation".

#### Step 1: Data preparation

**For CSV (basic):**

Place CSV files under `user/common/csv/`. Create them in UTF-8 (with BOM).

| File | Main columns | Purpose |
|---------|-----------|------|
| `Sample01_Quote.csv` | speaker, situation, quote | Quote collection |
| `Sample02_Memo.csv` | create_date, memo | Memo |
| `Sample03_Feedback.csv` | emp_code, speaker, create_date, feedback | Feedback |

**For Notion (optional):**

After setting the following in `system.env`, define the Notion database IDs in `notion_db.json`.

```env
NOTION_VERSION=2022-06-28
NOTION_TOKEN=Notion integration API key
NOTION_MST_FILE=notion_db.json
```

```json
{
  "DatabaseName": "Notion database ID"
}
```

#### Step 2: RAG master configuration

Define RAG data sources in `rags.json`.

**For CSV:**

```json
{
  "Sample01_Quote": {
    "active": "Y",
    "input": "csv",
    "data_type": "chromadb",
    "bucket": "Sample01_Quote",
    "data_name": "Quote collection",
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

**For Notion**

```json
{
  "NotionDB_Name": {
    "active": "Y",
    "input": "notion",
    "data_type": "chromadb",
    "bucket": "NotionDB_Name",
    "data_name": "Display name",
    "item_dict": {"PropertyName": "internal_key_name"},
    "chk_dict": {"ConfirmedChk": true},
    "date_dict": {"Timestamp": "create_date"},
    "category_dict": {"Category": "category"}
  }
}
```

| Item | Description |
|------|------|
| `active` | `Y` to enable |
| `input` | Data source (`csv` or `notion`) |
| `data_type` | Storage destination (`chromadb`) |
| `bucket` | ChromaDB collection name |
| `file_name` | CSV file name (multiple can be specified as a list) |
| `field_items` | CSV columns to use |
| `title` | Fields used for the display title |
| `key_text` | Search text (used for the embedding index) |
| `value_text` | Reference text (referenced when generating responses) |
| `category_items` | Category filter conditions (see below) |

**Private Mode (RAG data publication control):**

You can set a `private` flag on RAG data. Data with `private: true` is excluded from search targets at execution time when Private Mode is enabled.

**For Notion** — specify the property in `item_dict`:

```json
"item_dict": {
  "db": "DigiMATSU_Identity_Memo",
  "title": {"Name": "title"},
  "private": {"Private": "chk"}
}
```

In the above, the value of Notion's "Private" checkbox property (`true`/`false`) becomes the `private` flag of the RAG data as-is.

To set a fixed value (do not mark all records as private):

```json
"private": false
```

**For CSV** — add a `"private"` column to `field_items`:

```json
"field_items": ["speaker", "situation", "quote", "private"]
```

Enter `True` / `False` in the `private` column inside the CSV.

> Data with no `private` flag set is automatically treated as `false` (public). There is no impact on existing data.

**Filtering data with category_items:**

Specifying `category_items` lets you filter by values of specific columns in the target CSV data. Multiple conditions are applied as AND conditions.

```json
"category_items": [
  {"RAG_Category": ["memo"]},
  {"category": ["Feedback"]}
]
```

In the above, only records where the `RAG_Category` column is `"memo"` and the `category` column is `"Feedback"` are registered to the RAG.

#### Step 3: Generating the vector DB

When you click the "**Update RAG Data**" button in the **RAG** section of the WebUI sidebar, the data is loaded and vector data is generated in ChromaDB.

> On the first run, all records are vectorized. From the second run onward, only data with changes to `title` / `key_text` / `value_text` is re-vectorized, and changes to other fields update only the metadata.

> **Using Private Mode:** Turning on the "Private Mode" checkbox near the WebUI chat input excludes RAG data with `private: true` from search targets. From the API it can be controlled via the `"private_mode": true` parameter. To migrate existing data so that `private: false` is set in bulk, run the following command:
>
> ```python
> import DigiM_Context as dmc
> dmc.migrate_add_private_flag()
> ```

#### Page index RAG (pageindex type)

Rather than vector search, this is an RAG method where the LLM selects relevant pages from a page list. It is suited for structured documents (system guides, knowledge collections, etc.).

**Example definition in rags.json (when importing from Notion):**

```json
{
  "AIUCStandard": {
    "active": "Y",
    "input": "notion",
    "data_type": "pageindex",
    "data_name": "DigiMATSU_Book",
    "bucket": "AIUCStandard",
    "item_dict": {
      "book": {"BookName": "select"},
      "id": {"ID": "rich_text"},
      "title": {"Title": "rich_text"},
      "create_date": {"Timestamp": "date"},
      "category": {"Category": "select"},
      "summary": {"Summary": "rich_text"},
      "tags": {"Tags": "multi_select"},
      "url": ""
    },
    "chk_dict": {
      "ConfirmedChk": true,
      "BookName": "AI Product \"Fundamental Patterns\"",
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

| item_dict key | Destination in `_index.json` |
|---------------|-------------------------|
| `book` | `BOOK.title` (book name) |
| `id` | `PAGES[].id` (also the file name `{id}.md`) |
| `title` | `PAGES[].title` |
| `create_date` | `PAGES[].timestamp` |
| `summary` | `PAGES[].summary` |
| `tags` (multi_select) | `PAGES[].tags` (array) |
| `category` | `PAGES[].category` |

| chk_dict value type | Filter on the Notion side |
|---------------|--------------------|
| `true` / `false` | checkbox property |
| String | select property (`equals` match) |

When "Update RAG Data" is executed, `.md` files for each page (Notion page bodies converted to Markdown-like format) and `_index.json` (page index) are auto-generated under `user/common/rag/pages/{bucket}/`.

- If an `id` is duplicated, it is overwritten
- `sort_order` is dynamically computed from `id` (e.g. `"1-0"->100`, `"1-2-3"->10203`)
- After registration completes, the Notion property specified by `fin_flg` (e.g. `RAGChk`) is updated to `true`

To place page data manually, use the following structure:

```
user/common/rag/pages/DigiMPGSystemGuide/
├── _index.json    # BOOK + PAGES list
├── 0-1.md         # Body for each page
├── 1-1.md
└── ...
```

Structure of `_index.json`:

```json
{
  "BOOK": {
    "title": "Consulting Know-how"
  },
  "PAGES": [
    {
      "id": "1-1",
      "title": "External environment analysis (PEST / 5 Forces)",
      "timestamp": "2026-04-01",
      "summary": "Technique to grasp the macro environment via PEST analysis and industry structure via 5 Forces analysis",
      "tags": ["Strategy", "PEST", "5Forces"],
      "category": "Strategic planning",
      "sort_order": 101
    }
  ]
}
```

If you set `"RETRIEVER": "PageIndex"` on the agent's BOOK, it becomes selectable from the BOOK section of the WebUI (see the BOOK section for details).

##### Generating page indexes from an Excel source

In addition to Notion, you can generate page indexes from Excel files (1 row = 1 page). You place the Excel and body text files (`.txt`/`.md`) together under `source_dir`.

```json
{
  "DigiMPGSystemGuide": {
    "active": "Y",
    "input": "excel",
    "data_type": "pageindex",
    "data_name": "DigiMPGSystemGuide",
    "bucket": "DigiMPGSystemGuide",
    "source_dir": "user/common/csv/pageindex/DigiMPGSystemGuide",
    "source_file": "DigiMPGSystemGuide.xlsx",
    "sheet": "pages",
    "item_dict": {
      "book": "BookName",
      "id": "ID",
      "title": "Title",
      "summary": "Summary",
      "tags": "Tags",
      "category": "Category",
      "body": "Body"
    }
  }
}
```

- The values in `item_dict` are **Excel column names**. Assign a column name to each of the keys `book`/`id`/`title`/`summary`/`tags`/`category`/`body`
- For the `tags` column, comma (`,`) or pipe (`|`) separated strings are converted to arrays
- **`body` cell resolution logic**:
  - If the cell value matches a `.txt`/`.md` file name present under `source_dir`, that file's body is loaded
  - If it does not match, the cell value itself is used as the body (for short text)
  - To prevent path traversal, values containing separators (`/`/`\\`/`..`) are treated inline

Folder structure example:
```
user/common/csv/pageindex/DigiMPGSystemGuide/
├── DigiMPGSystemGuide.xlsx   # Index file (1 row = 1 page)
├── 0-1.md                    # Referenced when the body column contains "0-1.md"
├── 1-1.md
├── 2-1.md
└── ...
```

When "Update RAG Data" is executed, `_index.json` and each page's `.md` are generated under `user/common/rag/pages/{bucket}/` (same output format as the Notion-derived case).

##### Local download of the page index (Page Index Export)

From the WebUI sidebar **RAG Management -> Page Index Export**, you can download an existing page index (regardless of whether it originated from Notion or Excel) as a ZIP of **Excel + individual .md files**.

- The output Excel format is import-compatible with `input: "excel"` (the `body` column references file names)
- ZIP structure: `{bucket}/{bucket}.xlsx` + `{bucket}/{id}.md`
- Useful for an offline editing workflow: edit Excel locally -> re-extract under `user/common/csv/pageindex/{bucket}/` -> re-import

### Agent configuration

Place agent definition JSON files under `user/common/agent/`. It is recommended to copy `agent_10Sample.json` and customize it.

#### PERSONALITY (personality settings)

Defines the personality of the agent.

```json
"PERSONALITY": {
  "SEX": "Female",
  "BIRTHDAY": "01-Jan-1980",
  "IS_ALIVE": true,
  "NATIONALITY": "Japanese",
  "LANGUAGE": "Japanese",
  "SPEAKING_STYLE": "Polite",
  "CHARACTER": "Sample.txt",
  "Openness": 0.7,
  "Conscientiousness": 0.7,
  "Extraversion": 0.7,
  "Agreeableness": 0.7,
  "Neuroticism": 0.2
}
```

| Item | Description |
|------|------|
| `SPEAKING_STYLE` | Specify the speaking style defined in `SPEAKING_STYLE` of the prompt template |
| `CHARACTER` | A text file under `user/common/agent/character/` (**`.txt` or `.md`**), or directly described. Detailed personality definition such as career, values, first person, etc. |
| Big Five traits | Set `Openness` / `Conscientiousness` / `Extraversion` / `Agreeableness` / `Neuroticism` in the 0.0-1.0 range |

#### ENGINE (LLM engine settings)

**LLM (text generation):**

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

The model with the key name specified in `DEFAULT` is used. It can also be switched from the WebUI.

| API | FUNC | Supported model examples |
|-----|------|------------|
| OpenAI | `generate_response_T_gpt` | GPT-4.1, GPT-4.1-mini, etc. |
| Google | `generate_response_T_gemini` | Gemini-2.5-Flash, Gemini-3.1, etc. |
| Anthropic | `generate_response_T_claude` | Claude-Sonnet-4.5, Claude-Haiku, etc. |
| XAI | `generate_response_T_grok` | Grok-4, etc. |
| **Azure OpenAI** | `generate_response_T_azure_openai` | gpt-* deployments on Azure (specify the deployment name in `MODEL`) |

**Using Azure OpenAI Service**

Set `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` / `AZURE_OPENAI_API_VERSION` (default `2024-12-01-preview`, required for gpt-5 series) in `system.env`. In the agent JSON, put the Azure deployment name in `MODEL`. You can also **override on a per-engine basis** with `PARAMETER.api_version` (e.g., use a new API version only for gpt-5 series). For `gpt-5*` / `o1` / `o3` / `o4` series, `max_tokens` is automatically translated to `max_completion_tokens`:

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

For image generation, you can similarly use Azure's `gpt-image-1`/`dall-e-3` deployments via `generate_image_azure_dalle`.

**IMAGEGEN (image generation):**

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

| FUNC_NAME | Description |
|-----------|------|
| `generate_image_dalle` | Image generation by OpenAI DALL-E |
| `generate_image_gemini` | Image generation by Google Gemini |
| `generate_image_azure_dalle` | dall-e/gpt-image deployments on Azure OpenAI Service |

#### HABIT (behavior switching)

When a specific trigger word (`MAGIC_WORD`) is included in the user's input, the agent switches to the corresponding Practice (processing pipeline).

```json
"HABIT": {
  "DEFAULT": {
    "MAGIC_WORD": [""],
    "PRACTICE": "practice_00Default.json"
  },
  "Chat": {
    "MAGIC_WORD": ["Answer concisely", "Reply briefly"],
    "PRACTICE": "practice_01Chat.json"
  },
  "SENRYU_SENSEI": {
    "MAGIC_WORD": ["Compose a senryu."],
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

- `MAGIC_WORD`: A list of trigger words (an empty string represents the default behavior)
- `PRACTICE`: The Practice file to execute
- `KNOWLEDGE`: **A HABIT-specific RAG data source can be configured**. When specified, the relevant RAG is referenced only when that HABIT fires

#### KNOWLEDGE (knowledge settings)

Defines the RAG data sources referenced in ordinary dialogue.

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

- `RAG_DATA`: The RAG data sources to reference (corresponds to the `bucket` in the RAG master). Multiple can be specified
- `TEXT_LIMITS`: The maximum character count included in the context
- `DISTANCE_LOGIC`: Similarity calculation method (`Cosine`)

#### FEEDBACK (feedback settings)

Defines the storage destination and format for feedback against conversation history.

```json
"FEEDBACK": {
  "ACTIVE": "Y",
  "SAVE_MODE": "CSV",
  "SAVE_DB": "Sample00_Feedback",
  "DEFAULT_CATEGORY": "Unset",
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

| Item | Description |
|------|------|
| `ACTIVE` | `Y` to enable the feedback feature |
| `SAVE_MODE` | Storage destination (`CSV` or `Notion`) |
| `SAVE_DB` | CSV file name / key name for the Notion database ID |
| `DEFAULT_CATEGORY` | Default value for the WebUI category selection |
| `FEEDBACK_ITEM_LIST` | List of feedback items |
| `FIELD_MAP` | Definition of save fields (`key`: internal key, `name`: CSV column name, `type`: data type) |

**FIELD_MAP data types:**

| type | CSV | Notion |
|------|-----|--------|
| `title` | First column | Page title |
| `text` | String | `update_notion_rich_text_content` |
| `number` | String | `update_notion_num` |
| `date` | Date conversion (YYYY/MM/DD) | `update_notion_date` |
| `category` | String | `update_notion_select` |
| `checkbox` | String | `update_notion_chk` |

When saving to Notion, you can specify the property name individually via `notion_name`. Also, specifying `default` lets you set a fixed value that is independent of the data.

```json
{"key": "input_class", "name": "input_class", "notion_name": "Input Class", "type": "category", "default": "Feedback"},
{"key": "confirmed",   "name": "confirmed",   "notion_name": "ConfirmedChk",  "type": "checkbox", "default": true}
```

#### SUPPORT_AGENT (support agents)

Specifies Support Agents that assist the main dialogue. Each Support Agent is defined as an independent agent JSON and can be customized.

```json
"SUPPORT_AGENT": {
  "DIALOG_DIGEST": "agent_51DialogDigest.json",
  "ART_CRITICS": "agent_52ArtCritic.json",
  "EXTRACT_DATE": "agent_55ExtractDate.json",
  "RAG_QUERY_GENERATOR": "agent_56RAGQueryGenerator.json",
  "THINKING": "agent_58Thinking.json",
  "KNOWLEDGE_INTERPRET": "agent_78DigiMKnowledgeInterpret.json",
  "CITATION_INJECT": "agent_79DigiMCitationInject.json"
}
```

| Agent name | Role |
|------|------|
| `DIALOG_DIGEST` | Generates a digest (summary) of the conversation history |
| `ART_CRITICS` | Generates explanation / critique after image generation |
| `EXTRACT_DATE` | Extracts date information from user input (used for RAG metadata search) |
| `RAG_QUERY_GENERATOR` | Generates auxiliary queries for RAG search from user input |
| `THINKING` | Analyzes the user's question and dynamically decides on Habit selection / Web search / RAG query generation / Book addition (when Thinking Mode is enabled) |
| `KNOWLEDGE_INTERPRET` | Invoked by the "Interpret with LLM" buttons under Analytics Results - Knowledge Utility. Reads the inventory CSV / similarity rank (+ optional scatter / bar images) and returns three sections: overall composition vs. this-query selection, contribution analysis using delta = response_sim − question_sim, and notable / improvement points. Back-data centric; images are optional for vision-capable models. |
| `CITATION_INJECT` | After the main response is generated, this agent inserts `[N]` markers at sentences grounded in web URLs or BOOK chunks and appends a `## References` section. Fires automatically whenever a web URL or a BOOK chunk was used (KNOWLEDGE entries are not cited — they are treated as the agent's internalised knowledge). Defaults to a lightweight model (Claude-Haiku-4.5 / Gemini Flash Lite / GPT-5-mini). On LLM failure, falls back to leaving the body untouched and appending only the References list. |

#### BOOK (reference information)

The agent obtains information from RAG data as "books and quotes it knows" and displays it in the Book section of the WebUI.

```json
"BOOK": [
  {
    "RAG_NAME": "Quote",
    "RAG_DATA": [{"DATA_NAME": "Sample01_Quote", "BUCKET": "Sample01_Quote"}],
    "HEADER_TEMPLATE": "The following are quotes by famous people you appreciate.\n",
    "CHUNK_TEMPLATE": "- {speaker}: \"{value_text}\"\n\n",
    "TEXT_LIMITS": 1000,
    "DISTANCE_LOGIC": "Cosine"
  }
]
```

You can customize the display format of the RAG data with `HEADER_TEMPLATE` and `CHUNK_TEMPLATE`. RAG data values can be embedded with `{field_name}`.

**PageIndex-type BOOK (page index search):**

Rather than vector search, this method has the LLM select relevant pages from a page index and inject them into the context. It is suited for structured documents (system guides, etc.).

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
    "HEADER_TEMPLATE": "[System Guide] The following is technical information about the system.\n",
    "LOG_TEMPLATE": "'rag':'{rag_name}', 'page_id':'{page_id}', 'title':'{title}', 'category':'{category}', 'summary':'{summary}'",
    "TEXT_LIMITS": 6000,
    "MAX_PAGES": 5,
    "DISTANCE_LOGIC": "PageIndex"
  }
]
```

| Item | Description |
|------|------|
| `RETRIEVER` | Specify `PageIndex` |
| `DATA_TYPE` | Specify `PAGE_INDEX` |
| `DATA_NAME` | Folder name under `user/common/rag/pages/` |
| `SUPPORT_AGENT` | LLM agent used for page selection |
| `LOG_TEMPLATE` | Log format displayed in Detail Information. `{rag_name}`, `{page_id}`, `{title}`, `{category}`, `{summary}` can be used |
| `MAX_PAGES` | Max number of pages selected per query |

Page data is placed under `user/common/rag/pages/{DATA_NAME}/` with `_index.json` (page listing) and a `.md` file per page. When using Notion integration with `"data_type": "pageindex"` defined in `rags.json`, "Update RAG Data" auto-generates them (see "Page index RAG (pageindex type)" for details).

**Auto breadcrumb**: Each PageIndex page selected for context gets a single line prepended to its body — `[Path] ParentTitle > ChildTitle > SelfTitle` — derived from the dash-separated id hierarchy (e.g. `id=1-1-1` → `[Path] System overview > Architecture > ChromaDB integration`). This lets the LLM understand the page's **position within the broader knowledge base**. Intermediate ids that aren't in `_index.json` are silently skipped.

#### AgentSearch / FunctionSearch (dynamic retrieval, KNOWLEDGE / BOOK)

Beyond vector search and PageIndex, two more retriever types can be placed in either `KNOWLEDGE` or `BOOK`: **AgentSearch** (invokes another agent) and **FunctionSearch** (invokes a registered tool function). Output is formatted via `CHUNK_TEMPLATE` and injected like any other RAG chunk.

**AgentSearch (call another agent)**

Runs a target agent (including self) through `DigiMatsuExecute_Practice` and pulls its response into the context. To prevent runaway recursion, the request-wide call counter is capped by `AGENT_SEARCH_MAX_CALLS` at the agent root (default 3); each block's `MAX_CALLS` can override.

```json
{
  "RAG_NAME": "DigitalConsultantSecondOpinion",
  "RETRIEVER": "AgentSearch",
  "DATA": [{
    "DATA_TYPE": "AGENT_SEARCH",
    "AGENT_FILE": "agent_10Sample.json",
    "MAX_CALLS": 2,
    "EXECUTION": {
      "MEMORY_USE": false,
      "MEMORY_SAVE": false,
      "SAVE_DIGEST": false,
      "STREAM_MODE": false,
      "PRIVATE_MODE": true,
      "WEB_SEARCH": false,
      "THINKING_MODE": false
    },
    "OVERWRITE_ITEMS": {},
    "ADD_KNOWLEDGE": [],
    "SITUATION": {"TIME": "", "SITUATION": ""}
  }],
  "HEADER_TEMPLATE": "[Second Opinion] The following is another consultant agent's view.\n",
  "CHUNK_TEMPLATE": "## Second opinion by {agent_name}\nQ: {query}\nA: {response}\n\n",
  "LOG_TEMPLATE": "'rag':'{rag_name}', 'agent':'{agent_name}', 'tokens':'{response_tokens}'",
  "TEXT_LIMITS": 4000
}
```

| Field | Description |
|------|------|
| `AGENT_FILE` | Target agent (self is allowed, bounded by the call cap) |
| `MAX_CALLS` | Per-block override of the request-wide `AGENT_SEARCH_MAX_CALLS` |
| `EXECUTION` | Same shape as `Execute_Practice`'s `in_execution`. **Omitted fields fall back to safe defaults** (memory off / history not persisted / no digest / PRIVATE_MODE=true → zero side effects) |
| `OVERWRITE_ITEMS` | Overrides for the child agent's `HABIT` / `PERSONALITY` / ... |
| `ADD_KNOWLEDGE` | Extra RAG blocks injected into the child's KNOWLEDGE |
| `SITUATION` | `TIME` / `SITUATION` passed to the child |
| `CHUNK_TEMPLATE` placeholders | `{rag_name} {agent_name} {agent_file} {query} {response} {response_tokens}` |

**The child's input/output is NOT saved to chat history** (effect of `MEMORY_SAVE: false`). Instead, it's logged into the parent turn's `prompt.agent_search` field (alongside `thinking` / `web_search`) so you can trace it from the Detail Info panel.

**FunctionSearch (invoke a tool function)**

Calls any function registered in `DigiM_ToolRegistry` (standard tools and the user's custom tools under `user/common/tool/local/`) and pulls its return value into the context.

```json
{
  "RAG_NAME": "CurrentTimeContext",
  "RETRIEVER": "FunctionSearch",
  "DATA": [{
    "DATA_TYPE": "FUNCTION_SEARCH",
    "FUNCTION_NAME": "current_time",
    "ARGS_TEMPLATE": "{query}"
  }],
  "HEADER_TEMPLATE": "[Function result]\n",
  "CHUNK_TEMPLATE": "[{rag_name} / {function_name}] {response}\n\n",
  "LOG_TEMPLATE": "'rag':'{rag_name}', 'function':'{function_name}'",
  "TEXT_LIMITS": 500
}
```

| Field | Description |
|------|------|
| `FUNCTION_NAME` | A function name registered in `DigiM_ToolRegistry` (see `/skills`) |
| `ARGS_TEMPLATE` | Input template (the user's query is available as `{query}`). Defaults to `"{query}"` |
| `CHUNK_TEMPLATE` placeholders | `{rag_name} {function_name} {query} {args} {response}` |

Return values can be generators / 4-tuples / 6-tuples — all are normalised. Each invocation is logged into the parent turn's `prompt.function_search` field.

**KNOWLEDGE vs BOOK**

- **In KNOWLEDGE**: retrieved every turn. Treated as the agent's internalised knowledge — excluded from citation_inject.
- **In BOOK**: retrieved only when the Thinking step requests the block by name (or always, if you put it under KNOWLEDGE). Eligible for `citation_inject` as a citation source.

**Sample**: `user/common/agent/agent_11Sample.json` ships a sample agent with Vector + AgentSearch + FunctionSearch coexisting in `KNOWLEDGE`.

**Analytics Result - Knowledge Utility integration**: PageIndex / AgentSearch / FunctionSearch chunks each compute `similarity_Q` (similarity to the question) and `similarity_A` (similarity to the response) internally — the same fields that Vector entries carry — so they appear in the Chat tab's **"Analytics Results - Knowledge Utility"** panel side-by-side with Vector results. This lets you compare "how much did vector search vs. other-agent referrals vs. external functions contribute to the answer". Read `knowledge_utility = similarity_Q − similarity_A`: a high value means the chunk fit the question well but wasn't fully reflected in the response → room for improvement.

#### ORG / Persona (multi-persona parallel execution)

For a single template agent, you can register **multiple personas** in PostgreSQL (`digim_agent_personas`) or Excel (`user/common/agent/persona_data/`), and switch between them via ORG to run them in parallel from the WebUI or a Practice.

**Additional items added to the agent JSON**:
```json
"ORG": [
  {"company": "DigiM Lab"},
  {"company": "DigiM Lab", "dept": "Consulting"},
  {"company": "DigiM Lab", "BU": "DX"}
],
"PERSONA_FILES": ["TheRound_personas.xlsx"],
"PERSONA_SOURCE": "RDB"
```
- `ORG`: List of selectable org dicts (one is chosen at execution time by the WebUI / Practice)
- `PERSONA_FILES`: List of Excel file names to load from under `persona_data/` (if omitted, all xlsx are scanned. Ignored when `PERSONA_SOURCE="RDB"`)
- `PERSONA_SOURCE`: **Per-agent override of the reference source**. Choose from `"EXCEL"`/`"RDB"`/`"BOTH"`. **If omitted, falls back to the environment variable `AGENT_PERSONA_SOURCE`**

**Matching**: A match occurs if `persona.org` contains all keys of `agent.ORG` (the one element selected at execution time) with equal values (the agent is a subset of the persona). Example:
- persona: `{company:"DigiM Lab", dept:"Consulting", BU:"DX"}`
- agent (selected): `{company:"DigiM Lab", BU:"DX"}` -> match

**Targets of persona override (against the template)**:
- Overridden: `NAME` / `ACT` / `PERSONALITY` (including `character_text` or `character_file`) / `HABIT` (if not `["ALL"]`, filtered by a name whitelist) / `KNOWLEDGE` (if not `["ALL"]`, filtered by `RAG_NAME`) / `DEFINE_CODE`
- Immutable: `ENGINE` / `SUPPORT_AGENT` / `BOOK` / `SKILL` / `FEEDBACK`

**Parallel execution / memory control**:
- Select multiple personas in the WebUI sidebar -> on send, run in parallel via `ThreadPoolExecutor` (limit `MAX_PARALLEL_PERSONAS`)
- Each sub_seq run in parallel is automatically assigned `setting.memory_flg="N"` and excluded from the next turn's conversation memory (`get_memory`). The display remains
- If the "Include Query" checkbox is ON, the full responses of each persona are embedded at **the head of the user input on the next turn** (no effect on RAG query generation)

**Practice integration (chain.PERSONAS)**:

In each CHAIN step of a Practice, you can have **only that step** run in parallel across multiple personas -> merge the results -> proceed to the next step:
```json
"CHAINS": [
  {
    "TYPE": "LLM",
    "PERSONAS": "WEB_UI",            // "WEB_UI" / list of persona_id / "THINKING"
    "PERSONA_MERGE": "include_query", // "summary"/"concat"/"first"/"include_query"/"none"
    "PERSONA_MERGE_LEVEL": "medium", // "light"/"medium"/"heavy" or free text (only used when summary)
    "SETTING": { ... }
  },
  {
    "TYPE": "LLM",
    "SETTING": {
      "USER_INPUT": ["OUTPUT_1", "\n\n[Additional instruction]\nCompare and evaluate"],
      ...
    }
  }
]
```
- `PERSONAS = "WEB_UI"`: Use the personas selected in the UI / fixed list with `["P0001",...]`
- `PERSONA_MERGE = "include_query"`: Send each persona response into the next step input in the format `[Previous responses of each persona]\n- name: text\n... [Current question] ...`
- Each parallel persona sub_seq has `chain_role="persona"`, `memory_flg="N"`
- The next step references the merged result of the previous step with `OUTPUT_<starting sub_seq>`

**Samples**:
- [`practice_51PersonaCompare.json`](user/common/practice/practice_51PersonaCompare.json): chain[0] runs **WEB_UI-selected personas** in parallel -> chain[1] comparative evaluation. Triggered by the magic word **"Ask everyone's opinion"** (`皆の意見を聞いて`)
- [`practice_52PersonaThinking.json`](user/common/practice/practice_52PersonaThinking.json): chain[0] runs in parallel using personas **auto-selected by Thinking** -> chain[1] comparative evaluation. Triggered by the magic word **"Ask the appropriate person"** (`適任に聞いて`)

**Phase 7: ThinkingMode persona auto-select**:

When `chain.PERSONAS = "THINKING"`, [`agent_54PersonaSelector.json`](user/common/agent/agent_54PersonaSelector.json) is called and **up to N** optimal personas are auto-selected based on the user's question:
- **Candidate pool**: All personas matching the selected ORG (the one chosen in the WebUI)
- **Upper bound N**: The "Max Personas" input in the WebUI sidebar (default is `MAX_PERSONAS=3` in `setting.yaml`)
- **Selection logic**: PersonaSelector picks personas whose viewpoints are complementary to one another and to the question. If one is sufficient, only one; out-of-domain personas are excluded
- **Fallback**: Selection failure / 0 selected -> falls back to the UI multiselect selection
- **Detail Information**: The selection reasons are recorded in `_THINKING_RESULT.personas_reason`

**Support agents**:
- `agent_50PersonaMerge.json`: The integration LLM called when `PERSONA_MERGE="summary"`
- The summary intensity is controlled via the `{summary_level}` placeholder in the "Persona Merge" prompt template
- Called from `DigiM_Tool.dialog_persona_merge()`

**Excel schema** (`personas` sheet, one persona per row):

| Column | Type | Description |
|---|---|---|
| `persona_id` | str | Unique ID |
| `template_agent` | str | Linked template (empty means shared across all templates) |
| `org` | JSON | `{"company":"...", "dept":"..."}` |
| `company` / `dept` / `name` / `act` | str | For display / logging |
| `personality` | JSON | Fully replaces the template's `PERSONALITY` |
| `habits` | str | `ALL` or `DEFAULT,FRIENDLY` |
| `knowledge` | str | `ALL` or `Quote,Memo` |
| `define_code` | JSON | Free schema |
| `character_text` | str | Direct description |
| `character_file` | str | File name under `character/` |
| `active` | `Y`/`N` | Logical deletion |

**RDB schema**: See the `digim_agent_personas` section of `SETUP_POSTGRESQL.en.md` for details.

### Practice configuration

A Practice is a JSON file that defines the processing pipeline of an agent. Place it under `user/common/practice/`.

#### Basic structure

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

| Item | Description |
|------|------|
| `NAME` | Practice name |
| `CHAIN` | List of execution steps (executed in order) |

#### Each step in CHAIN

| Item | Description |
|------|------|
| `TYPE` | Execution type (`LLM` / `IMAGEGEN` / `FUNC`) |
| `AGENT_FILE` | The agent to use (`USER` to use the caller's agent, a file name to specify a different agent) |
| `OVERWRITE_ITEMS` | Override of engine settings (`USER` to inherit user settings, `{}` for no override) |
| `ADD_KNOWLEDGE` | Additional knowledge sources (`["USER"]` to use the user agent's KNOWLEDGE) |
| `PROMPT_TEMPLATE` | Name of the prompt template to use |
| `MEMORY_USE` | Whether to include past conversation history in the context |
| `USER_INPUT` | Fixed value of the input text (used instead of user input when specified) |
| `CONTENTS` | Reference to the previous step's output (`EXPORT_1` for the output of the first step) |
| `SITUATION` | Situation information settings |

#### Multi-step example (image generation + critique)

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
      "USER_INPUT": "Explain the content in about 300 characters while relating it to the conversation so far.",
      "CONTENTS": "EXPORT_1",
      "MEMORY_USE": true
    }
  ]
}
```

In this example, the first step generates an image, and the second step has a different agent (ArtCritic) critique the image. With `CONTENTS: "EXPORT_1"`, the output of the first step is set as input for the second step.

### Web search configuration

Enabling Web search lets you supplement the input to the LLM with the latest information from the Web. You enable it with the "WEB Search" checkbox above the WebUI chat input field, and switch engines with the adjacent select box.

#### Supported engines

| Engine | API key | Features |
|---------|---------|------|
| **Perplexity** | `PERPLEXITY_API_KEY` | A model specialized for Web search. Responses include source URLs |
| **OpenAI** | `OPENAI_API_KEY` | Searches via GPT's `web_search_preview` tool. High accuracy |
| **Google** | `GEMINI_API_KEY` | Gemini's Google Search Grounding. Google search based |
| **Claude** | `ANTHROPIC_API_KEY` | Anthropic's `web_search_20260209` server-side tool. Dynamic Filtering returns results efficiently |

#### setting.yaml settings

Set the default engine and parameters of each engine in `setting.yaml`.

```yaml
# Default search engine (Perplexity / OpenAI / Google / Claude)
WEB_SEARCH_DEFAULT: "OpenAI"

# Perplexity
PERPLEXITY_URL: "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL: "sonar"
PERPLEXITY_SYSTEM_PROMPT: "Be precise and concise."
PERPLEXITY_USER_PROMPT: "Based on the following input, provide related information."
PERPLEXITY_MAX_TOKENS: 2000
PERPLEXITY_REASONING_EFFORT: "medium"

# OpenAI Web Search
OPENAI_SEARCH_MODEL: "gpt-5-mini"
OPENAI_SEARCH_SYSTEM_PROMPT: "Be precise and concise."
OPENAI_SEARCH_USER_PROMPT: "Based on the following input, provide related information."

# Google Grounding Search
GOOGLE_SEARCH_MODEL: "gemini-2.5-flash-preview-05-20"
GOOGLE_SEARCH_USER_PROMPT: "Based on the following input, provide related information."

# Claude Web Search (web_search_20260209)
CLAUDE_SEARCH_MODEL: "claude-sonnet-4-6"
CLAUDE_SEARCH_SYSTEM_PROMPT: "Be precise and concise."
CLAUDE_SEARCH_USER_PROMPT: "Based on the following input, provide related information."
CLAUDE_SEARCH_MAX_TOKENS: 4096
```

#### system.env settings

Set the API key for the engine you use.

```env
PERPLEXITY_API_KEY=Perplexity API key
OPENAI_API_KEY=OpenAI API key (shared with LLM)
GEMINI_API_KEY=Google Gemini API key (shared with LLM)
ANTHROPIC_API_KEY=Anthropic API key (shared with LLM)
```

### Tool Plugin System (SKILL / Tool / Slash Command)

All non-LLM agent capabilities (history operations, web search, analysis, etc.) flow through an **engine-agnostic tool registry**. The same tools work on GPT / Gemini / Claude / Grok with no vendor-specific changes.

#### Architecture overview

```
┌────────────────────────────────────────────────────────────────┐
│  user/common/tool/<name>.py  ← drop a .py file to add a tool       │
│      └─ dmtr.register_tool("name", description, schema, func)      │
│                              │                                  │
│                              ▼                                  │
│  DigiM_ToolRegistry.TOOL_REGISTRY ← name → {func, schema, ...}     │
│                              │                                  │
│       ┌──────────────────────┼──────────────────────┐           │
│       ▼                      ▼                      ▼           │
│  call_function_by_name   pick_tools()           __getattr__     │
│   (Practice TOOL chains)  (Thinking/SKILL)    (dmt.X back-compat)│
└────────────────────────────────────────────────────────────────┘
```

- **`DigiM_ToolRegistry.py`** — Single source of truth: `{name: {description, schema, func}}`.
- **`user/common/tool/`** — Streamlit auto-loads every `*.py` on startup (filenames starting with `_` are skipped, useful for private helpers). Each plugin self-registers by calling `dmtr.register_tool(...)` at module level.
- **`DigiM_Tool.call_function_by_name(svc, usr, name, ...)`** — Single dispatch point. Practice `TYPE:TOOL` chains, the fixed pipeline in `DigiM_Execute`, the WebUI slash command, and TOOL_PICK chains all go through here.
- **`DigiM_Tool.pick_tools(agent, query, allowed=...)`** — Engine-agnostic tool picker. `render_tools_for_prompt` advertises the tools as a JSON-Schema block in the system prompt; the LLM replies with `{"tool_calls":[{"name":..., "args":...}]}` which `parse_tool_calls` decodes. **No vendor-specific `tools=[]` parameter is used, so the exact same code works on Claude / Gemini / GPT / Grok.**
- **`__getattr__` shim** — PEP 562 fallback at the bottom of `DigiM_Tool`. Resolution order: registry → plugin module namespaces. Legacy callers like `dmt.fixed_message(...)` keep working after their functions move into plugin files.

#### Bundled tools (21 — all plugins)

| Category | Plugin file | Tools |
|---|---|---|
| History control | `history.py` | `fixed_message`, `forget_history`, `remember_history` |
| Dialog / summary | `dialog.py` | `dialog_digest`, `gene_session_name`, `dialog_persona_merge` |
| Thinking | `thinking.py` | `thinking_agent`, `RAG_query_generator`, `page_index_search` |
| Analysis | `analysis.py` | `extract_date`, `management_analysis`, `compare_texts` |
| Persona | `persona.py` | `select_personas` |
| Image critique | `art_critic.py` | `art_critics` |
| Web search | `web_search.py` | `WebSearch` (dispatcher), `WebSearch_PerplexityAI`, `WebSearch_OpenAI`, `WebSearch_Google`, `WebSearch_Claude` |
| Knowledge Utility | `knowledge_interpret.py` | `knowledge_utility_interpret` |
| Citation injection | `citation_inject.py` | `inject_citations` |
| Utility | `current_time.py` | `current_time` |

#### Adding a new tool

```python
# user/common/tool/my_skill.py
import DigiM_ToolRegistry as dmtr

def my_skill(service_info, user_info, session_id, session_name, agent_file,
             input, import_contents=[], add_info={}):
    # ...do work...
    return service_info, user_info, "result text", []

dmtr.register_tool(
    "my_skill",
    description="Used by the LLM (Thinking-mode pick) and the user (/my_skill) to decide when to call it",
    schema={"type":"object","properties":{"input":{"type":"string"}},"required":["input"]},
    func=my_skill,
)
```

Drop the file and restart Streamlit — the tool is available immediately.

**Standard vs. site-local plugins**

| Location | Purpose | Git tracking |
|---|---|---|
| `user/common/tool/*.py` | Standard plugins shipped with the repo (the 10 listed in this README) | **tracked** |
| `user/common/tool/local/*.py` | Site-local / user-authored plugins | **excluded by `.gitignore`** (will never be accidentally pushed) |

The loader scans both locations, with `local/` loaded **after** the standard
plugins. So:

- New custom tools go in `user/common/tool/local/<name>.py` — automatically excluded from pushes
- To **locally override** a standard tool, drop a same-named file under `local/` and call `register_tool(...)` with the same name — the registry treats re-registration as an update, and `local/` wins by load order

`.gitignore` rule:

```
user/common/tool/local/*          # exclude everything under local/
!user/common/tool/local/.gitkeep  # …except the .gitkeep so the directory stays
```

#### Agent JSON `SKILL` block (tools the agent is allowed to use from the WebUI / Thinking)

```json
"SKILL": {
  "TOOL_LIST": ["forget_history", "remember_history", "management_analysis", "fixed_message"],
  "CHOICE": "auto"
}
```

- `TOOL_LIST` — Allow-list of tool names. Used both for the WebUI slash command (`/skills`) and for the Thinking-mode auto-picker.
- `CHOICE` — `"auto"` (LLM picks) / `"manual"` (user must specify), etc. (reserved for future expansion).

#### Running a SKILL explicitly from the WebUI (slash command)

Typing `/<skill_name> <input>` in the chat box executes the tool directly. **The execution is persisted to the session as a normal user/assistant turn**, so the digest pipeline, next-turn memory, and Detail Information all see it (**session continuity is preserved**).

| Input | Behavior |
|---|---|
| `/skills` or `/help` | Show the list of skills available on this agent |
| `/<skill_name> <text>` | Run the skill if it's in SKILL.TOOL_LIST; otherwise show an error |
| `/<unknown_skill>` | Show "Skill is not registered" in chat |
| Plain text | Existing LLM flow (unchanged) |

Sample agent: `agent_02DigitalMATSUMOTO_ToolUser.json` is configured with `fixed_message / forget_history / remember_history / management_analysis` in `SKILL.TOOL_LIST` for hands-on testing.

#### Calling tools from a Practice chain

Two chain TYPEs are available:

| TYPE | Behavior |
|---|---|
| `TOOL` | Run the tool named by `setting.FUNC_NAME` (existing — for Practice authors that hard-wire the tool) |
| `TOOL_PICK` | Engine-agnostic: send the agent's `SKILL.TOOL_LIST` to the agent's LLM, let it pick, then run the picked tool. No vendor function-calling required. |

```json
{
  "TYPE": "TOOL_PICK",
  "SETTING": {
    "AGENT_FILE": "USER",
    "USER_INPUT": "USER",
    "TOOL_LIST": ["WebSearch", "extract_date"]
  }
}
```

#### Fixed pipeline tools called from DigiM_Execute (formerly direct `dmt.X` calls)

The 7 pipeline calls `RAG_query_generator` / `extract_date` / `thinking_agent` / `dialog_digest` / `WebSearch` / `dialog_persona_merge` / `select_personas` **now all go through `call_function_by_name`**. This collapses logging and error capture into one place: failures (e.g. a `SUPPORT_AGENT` pointing at a non-existent agent file) are now captured with full tracebacks in `user/_bg_errors.log` and the per-session `user/<session>/errors.log`.

### Citation injection

After the main LLM generates its response, a lightweight LLM runs an **additional pass** that extracts citation sources from web URLs and BOOK chunks, inserts `[N]` markers at the end of relevant sentences, and appends a `## References` section. **Body wording is not rewritten.**

#### Pipeline

```
[User input] → WebSearch → Main LLM (response generation) ──┐
                                                            │ If 1+ Web URL or
                                                            │ BOOK chunk was used
                                                            ▼
                          Citation Injector (Claude-Haiku-4.5 etc.)
                                                            │ Inserts [N] at end-of-sentence
                                                            │ Appends ## References block
                                                            ▼
                          Overwrites response.text in chat_memory.json
                                                            ▼
                          Visible in chat / digest pipeline / next-turn memory
```

#### What is and isn't cited

| Kind | Meaning | Cited? |
|------|---------|----|
| **KNOWLEDGE** | The agent's **internalised intellectual essence** | Not cited |
| **BOOK (Vector search)** | **Reference information** with explicit attribution | Yes ✓ |
| **BOOK (PageIndex)** | **Reference information** with explicit attribution | Yes ✓ (LOG_TEMPLATE strings are parsed via regex) |
| **Web search** | **Reference information** with explicit attribution | Yes ✓ |

BOOK is distinguished from KNOWLEDGE by filtering on `agent.agent["BOOK"]` `RAG_NAME`s.

#### Default and control knobs

- **Default ON**: `_parse_execution_settings.insert_citations` defaults to `True`. There is no WebUI toggle — the injector fires automatically whenever there is at least one citation source (a Web URL or a BOOK chunk).
- **Explicit OFF** (API etc.): pass `execution["INSERT_CITATIONS"] = false` to disable.
- **Engine override**: `SUPPORT_AGENT.CITATION_INJECT` selects the agent_file. Default is `agent_79DigiMCitationInject.json` (Claude-Haiku-4.5 family).

#### Graceful fallback

| Failure mode | Behaviour |
|---|---|
| 0 citation candidates | Skip (body unchanged) |
| Support agent load failure | Tool-internal fallback → body + auto-generated `## References` |
| LLM call exception | Same → body + auto-generated `## References` |
| LLM output extremely short vs. original | Same → body unchanged |
| Unexpected exception on the Execute side | Body unchanged; traceback recorded in `_bg_errors.log` / `<session>/errors.log` |

#### Output example

```markdown
... The new generator is released under Apache 2.0[1]. The core
technology is based on a 2024 paper[2]. As the saying goes,
"true creation is born from constraint"[3], so ...

## References
[1] (web) https://example.com/news/release - Press release
[2] (web) https://arxiv.org/abs/2401.xxxxx - Original paper
[3] (book: Quote) "true creation is born from constraint" — Unattributed quote collection ...
```

#### Diagnostic logs

The injector logs the following on every run — useful when citations don't appear:

```
[citation_inject] starting: web=2, book=1, book_rag_names=['Quote'],
                  book_titles=['"true creation is born ..."'], agent_file='agent_79...', body_len=842
[citation_inject] applied: new body_len=950, contains '[1]': True, contains '## References': True
```

- Empty `book_rag_names` → the agent has no `BOOK` config at all
- Has candidates but `book=0` → BOOK declared but chunks not retrieved (missing data / PageIndex `_index.json` absent / `page_index_search` returned 0 results)
- `book>0` but body has no `[N]` → LLM didn't follow instructions (switch to a smaller / different model)

### Auto URL fetching (as attachments)

When a `http(s)://...` link is included in the user input, `DigiM_UrlFetch` automatically fetches the page body and adds it as an attachment to the LLM's input.

- **Subpage crawling**: Toggled by the "Include URL Subpages" checkbox above the chat input field (default OFF). When ON, links within the same domain are also fetched.
- **Safety controls**: Access to private IPs / loopback / link-local is forbidden, with a size limit (`MAX_BYTES`) and rejection of dangerous extensions (`.exe`/`.dll`, etc.).

You can adjust the behavior via `URL_FETCH` in `setting.yaml`:

| Item | Description |
|------|------|
| `TIMEOUT` | HTTP timeout seconds |
| `MAX_BYTES` | Max bytes fetched per page |
| `MAX_SUBPAGES` / `MAX_DEPTH` | Upper limits for subpage crawling |
| `USER_AGENT` | UA string used in the request |
| `ALLOWED_DOMAINS` | When non-empty, switches to whitelist mode (only the listed domains are allowed) |
| `BLOCKED_DOMAINS` | Domains to reject (subdomains are recursively rejected too) |
| `BLOCKLIST_FILE` | Path to an external block list in hosts format or one domain per line (StevenBlack/hosts, UT1 blacklists, Hagezi DNS blocklists, etc.) |
| `BLOCKED_EXTENSIONS` | List of extensions to reject for fetching |

### User Memory (Hierarchical User Understanding)

A mechanism that accumulates a user's characteristics, interests, and values across sessions and automatically injects them as context into subsequent chats. It has a 3-layer structure, each with different granularity / lifespan.

| Layer | Unit | Content | Generation timing |
|----|------|------|---------------|
| **History** (`session_digest`) | 1 session = 1 record | Topic / excerpt of statements / axis tags (interest, values, constraints, tone) / Plutchik emotion list / confidence | At session end or manually |
| **Nowaday** (`period_profile`) | Period (YYYY-MM or rolling_<N>d or since_<date> or all). **Snapshot is appended (history) on every generation** | Continuing topics / new interests / waning topics / change in attitude / **Plutchik 8 basic emotions (intensity)** / **secondary emotions currently in effect** / summary paragraph | Monthly batch or manual (snapshotted each time) |
| **Persona** (`persona_profile`) | 1 user = 1 record | Role / expertise / interests / values / constraints / tone / topics to avoid (each with confidence and status) / **Big5 (5-trait scores + confidence + status)** | Diff-merged when Nowaday is updated |

#### Injection flow

`DigiM_UserMemoryBuilder.build_context_text()` synthesizes the "Information about the dialogue partner" text, which `DigiM_Execute.py` inserts at the head of the prompt **right before the Knowledge context**.

The synthesized User Memory text is **also included as input to RAG search query generation (`RAG_QUERY_GENERATOR`)** in addition to the main response prompt. When User Memory is enabled, RAG search queries are generated taking the persona profile, recent trends, and emotions into account (when disabled, behavior is unchanged). It is applied in both WebUI and API execution paths. In API execution, since `USER_MEMORY_LAYERS` is not specified explicitly, `Allowed["User Memory Layers"]` in `users.json` (or `USER_MEMORY_DEFAULT_LAYERS` if absent) is applied.

Injected structure (the actual prompt text is in Japanese since the system targets a Japanese-language LLM; an English-localized rendering is shown below for clarity):

```
# About the dialogue partner
Use the following as a reference for tone, interests, and topics to avoid in your response.

## Profile             <- Persona (approved + pending. pending is suffixed with "(tentative)". only deleted is excluded)
- Role: ...
- Expertise: ...
- Interests: machine learning, probabilistic programming (tentative) ...
- Values: ...
- Constraints: ...
- Tone / explanation preference: ...
- Topics to avoid: ...
- Big5: openness=0.85, extraversion=0.45 (tentative), ...   <- pending traits suffixed with "(tentative)"
(summary_text up to 1500 chars)

## Recent trends (period) <- Nowaday
(Summary paragraph + continuing / new / declining / shifts)
- Basic emotions: anticipation(0.7), joy(0.6), trust(0.5)   <- only basic emotions with intensity >= 0.2, in descending order
- Secondary emotions: optimism, love                         <- secondary emotions that occurred during the period

## Recent sessions      <- History (tag x time hybrid search)
- [YYYY-MM-DD][topic] excerpt (emotions: joy, optimism)  <- Plutchik emotions per session
...
```

**Emotion model (Plutchik's wheel of emotions):**

- **8 basic emotions**: `joy` / `trust` / `fear` / `surprise` / `sadness` / `disgust` / `anger` / `anticipation`
- **Secondary emotions (dyads)**: `love` (joy+trust) / `submission` (trust+fear) / `awe` (fear+surprise) / `disapproval` (surprise+sadness) / `remorse` (sadness+disgust) / `contempt` (disgust+anger) / `aggressiveness` (anger+anticipation) / `optimism` (anticipation+joy)

History.emotions is a list per session (max 4, English keys), Nowaday.basic_emotions is a fixed-8-key dict (intensity 0-1), and Nowaday.secondary_emotions is a list of currently occurring secondary emotions. History search detects emotion words (Japanese keywords) contained in the query text and adds them to the match score.

**Big5 (Persona):** The 5 traits of the Big Five (Five Factor Model) — `openness` / `conscientiousness` / `extraversion` / `agreeableness` / `neuroticism` — are retained inside the Persona. Each trait is structured as `{score: 0..1, confidence: 0..1, status: pending|approved|deleted}` and follows the same pending -> approved auto-promotion rule (`confidence >= USER_MEMORY_AUTO_APPROVE_THRESHOLD`) as list items. **Both approved and pending** are included in the context (pending is suffixed with "(暫定)" — meaning "tentative" — to indicate low confidence; only `deleted` is excluded).

In IMAGEGEN (image generation) execution steps, User Memory injection is skipped so as not to crowd out the 3000-character prompt limit.

#### Emotion/Big5 backfill for existing records

To backfill emotion/Big5 into existing records created before the schema extension, use the CLI of `DigiM_GeneUserMemory.py`. Only fields missing from each record's compressed output (topic/excerpt/summary/list) are inferred by the LLM, and records that already have values are skipped. With the Notion backend, missing properties are automatically added.

```bash
python3 DigiM_GeneUserMemory.py --backfill                        # All layers, all records (only missing fields)
python3 DigiM_GeneUserMemory.py --backfill --layer history        # Limit to a specific layer
python3 DigiM_GeneUserMemory.py --backfill --user RealMatsumoto   # Limit by user_id
python3 DigiM_GeneUserMemory.py --backfill --dry-run              # Run the LLM only, do not save
python3 DigiM_GeneUserMemory.py --backfill --no-schema            # Skip auto-adding Notion properties
```

#### Storage destinations (backends)

You can choose independently per layer from **Excel / Notion / RDB**. Specified in `system.env`:

```env
USER_MEMORY_HISTORY_BACKEND="EXCEL"   # EXCEL/NOTION/RDB
USER_MEMORY_NOWADAY_BACKEND="EXCEL"
USER_MEMORY_PERSONA_BACKEND="EXCEL"
```

- **EXCEL**: Saved to `user/common/user_memory/<layer>.xlsx`
- **NOTION**: Saved to the Notion DB specified by the `DigiM_UserMemory_History` / `_Nowaday` / `_Persona` keys of the JSON specified in `NOTION_MST_FILE`
- **RDB**: Saved to the PostgreSQL `digim_user_memory_<layer>` table (the table is auto-created on first access)

#### On/Off 2-layer hierarchy

The priority is **User > System default**.

| Hierarchy | Storage | Content |
|------|--------|------|
| System default | `USER_MEMORY_DEFAULT_LAYERS` in `system.env` | Initial value for all users (e.g., `"persona,nowaday,history"`) |
| User master | `Allowed["User Memory Layers"]` in `users.json` | List of layers enabled for this user |

Whether a user can change their own `layers` is controlled by `Allowed["User Memory"]` (true/false) in `users.json`. Only when `true`, a **User Memory** expander appears directly below BOOK on the main screen, where layers can be freely edited and saved (the save destination is the same `Allowed["User Memory Layers"]`). Users with `false` or unset see no UI; if they have `User Memory Layers`, that setting applies; otherwise the system default applies. Checkbox changes **take effect immediately in that conversation regardless of pressing Save**, and pressing Save persists them to `users.json`. Switching the chat session resets to the saved value.

Example of user master entry:

```json
"RealMatsumoto": {
  "Allowed": {
    "User Memory": true,
    "User Memory Layers": ["persona", "nowaday", "history"]
  }
}
```

#### Background scheduler (general job management)

The general-purpose scheduler is managed from the **Scheduler menu** (at the top of the WebUI, next to Chat / Knowledge Explorer / User Memory Explorer). Jobs are saved to `user/common/mst/scheduled_jobs.json`, and can be reflected via the **Reload Schedulers** button without restarting Streamlit.

**Job kinds (`kind`):**

| kind | Description |
|------|------|
| `rag_update` | Calls `DigiM_Context.generate_rag()` to re-vectorize RAG data (when `USER_MEMORY_HISTORY_AUTO_SAVE_FLG=Y`, History of unsaved sessions is also auto-saved). No session is created. |
| `user_memory_nowaday` | For all users, runs the current month's Nowaday profile update -> diff merge into Persona, in order. No session is created. |
| `agent_run` | Runs the agent with the specified agent / prompt / execution mode. Each run issues a new session as the **owner user** (service_id=`Scheduler`, session_id=`SCH<datetime>`, name=`[Scheduler] <job name>`), and the response is saved to chat history as usual. |

**cron syntax:** `"off"` / `"daily"` (03:00) / `"weekly"` (Mon 03:00) / `"monthly"` (1st 03:00) / 5-field cron string (e.g., `"0 3 1 * *"`)

**Recording of last run:** For kinds other than `agent_run`, no session is left; only `last_run` / `last_status` / `last_error` are recorded in the job row (on error, shown in the Error log expander). Only for `agent_run` is `last_session_id` also saved, so the session can be opened from the chat history to check the response.

**Permissions:** The Scheduler menu is accessible only to users with `Allowed["Scheduler"] = true` (configured in `users.json` / `sample_users.json`). The owner user (`owner_user_id`) is auto-set to the logged-in user at save time, and is associated with the session at `agent_run` execution.

**WebUI operations:** Per job, **Edit** / **Run Now** (run once immediately) / **Enable/Disable** / **Delete**. Add jobs from **Add New Job**; after cron changes, reflect them in the running scheduler with **Reload Schedulers**. In environments without APScheduler installed, cron triggers are skipped, but manual execution via Run Now is possible.

#### Persona status and auto-approval

Each Persona item has 3 statuses:

| Status | Meaning | Included in context |
|---|---|---|
| **Approved** | Trustworthy (user-approved or auto-approved by `confidence >= threshold`) | Yes |
| **Pending** | Unreviewed | Yes (suffixed with "(暫定)" — meaning "tentative" — to indicate low confidence) |
| **Deleted** | Unnecessary (re-suggestions are also rejected) | No |

- On merge, `pending` items with `confidence >= USER_MEMORY_AUTO_APPROVE_THRESHOLD` (default 0.8) are auto-promoted to `approved`
- Items the user has set to `approved` in the WebUI are protected at the next merge (only confidence is updated by max value)
- `deleted` items are retained internally, and the LLM re-suggesting the same label is rejected
- Each field (expertise / recurring_interests, etc.) has a total character count cap of `USER_MEMORY_PERSONA_MAX_CHARS_PER_FIELD` (default 300). Approved is prioritized -> within the same status, items are packed in descending confidence

#### History memory selection logic (tag x time hybrid)

From the accumulated History data, items relevant to the current user input are selected and injected (no embedding vectors are used):

1. **MeCab** extracts nouns from the user input
2. Against each History record's `axis_tags` (which retains tag full text), "matching tags" are determined by partial match against the query nouns
3. **Matched group**: Ranked by match-tag ratio x (1 - alpha) + time score x alpha (alpha = `USER_MEMORY_HISTORY_RECENCY_WEIGHT`)
4. **Unmatched group**: Time score only (exponential decay, half-life = `USER_MEMORY_HISTORY_RECENCY_HALF_LIFE_DAYS`)
5. Matched group is prioritized -> remainder filled with the unmatched group -> packed up to a total of `USER_MEMORY_HISTORY_MAX_CHARS` (default 800 chars)

Tags themselves are retained as semantic units (e.g. a tag meaning "the relation between compensation and responsibility" is kept as one phrase, not broken down into the individual nouns), so the meaning of compound words is not lost.

#### WebUI operations

**Main screen > User Memory expander (`Allowed.User Memory: true` users)**
- Placed directly below BOOK, collapsed by default
- Displays the current enabled layers
- **Layer On/Off** (3-column horizontal checkboxes for persona/nowaday/history)
  - Changing the check takes effect immediately in that conversation **regardless of pressing Save**
  - Pressing **Save Layer Setting** persists to `Allowed["User Memory Layers"]` in `users.json`
  - Switching the chat session resets to the user master saved value
- Confirmation / modification of memory content (Persona/Nowaday/History) has been moved to the **"My Memory" tab of User Memory Explorer** (the Chat User Memory expander is dedicated to layer On/Off)

**Sidebar > RAG Management > User Memory (`RAG Management` and `User Memory` permissions)**
- Display of each layer's backend
- **Target User IDs**: multiselect from the user master (none selected = all users)
- **Period**: When checkbox ON, specify a start date in the calendar. Aggregates only History on/after the specified date. When OFF, the entire period (`period="all"`)
- **Update User Memory (History -> Nowaday -> Persona)**: Run the pipeline with a single button
  1. Generate History from unsaved sessions of the target users
  2. Filter History by period and **append Nowaday as a snapshot** (re-creating the same period does not overwrite past data; it accumulates as history. For incremental generation, the latest snapshot of the same period is referenced as the existing value)
  3. Diff-merge into Persona from the latest Nowaday (`generated_at` latest among `active='Y'`) (auto-approval also applies)

> Context injection, User Memory Explorer analytics, and Persona merging all use a single Nowaday snapshot with the latest `generated_at`. Past snapshots can be selected and viewed per period@generation time on the "My Memory" tab of Explorer.

#### Effect log and Detail Information

- The IDs of the layers injected at LLM call time are recorded in each session's conversation history `response.reference.user_memory`
- The full injected context is saved in `prompt.user_memory_context`
- They can be checked in the `[User Memory]` section of **Detail Information** in the WebUI

#### History memory generation input

When extracting History memory with the LLM, the following are taken into account:
- The session's conversation history (`role=user`/`role=assistant`)
- **User feedback** (appended at the end as `role=feedback`) — treated as the strongest expression of the user's intent
- **Excluded**: seq with SETTING.FLG="N" (deleted) / MEMORY_FLG="N" (excluded from memory reference), and sub_seq with setting.memory_flg="N"

#### Related environment variables (system.env)

| Variable | Default | Description |
|------|----------|------|
| `USER_MEMORY_HISTORY_BACKEND` | `EXCEL` | Storage destination of History (EXCEL/NOTION/RDB) |
| `USER_MEMORY_NOWADAY_BACKEND` | `EXCEL` | Storage destination of Nowaday |
| `USER_MEMORY_PERSONA_BACKEND` | `EXCEL` | Storage destination of Persona |
| `USER_MEMORY_DEFAULT_LAYERS` | `persona,nowaday,history` | System default enabled layers (set to empty string `""` to turn all off) |
| `USER_MEMORY_HISTORY_AUTO_SAVE_FLG` | `N` | `Y` to enable History auto-update tied to `Update RAG Data` |
| `USER_MEMORY_NOWADAY_MAX_CHARS` | `50000` | Max total character count of history_records passed to the LLM at Nowaday generation. Excess is truncated from the oldest History, and the count is reported as `truncated_older_count` |
| `USER_MEMORY_PERSONA_TOKEN_LIMIT` | `3000` | Upper token limit at Persona injection |
| `USER_MEMORY_AUTO_APPROVE_THRESHOLD` | `0.8` | Pending items with at least this confidence are auto-promoted to approved |
| `USER_MEMORY_PERSONA_MAX_CHARS_PER_FIELD` | `300` | Max total label character count per Persona field |
| `USER_MEMORY_HISTORY_MAX_CHARS` | `800` | Max total character count when inserting History context |
| `USER_MEMORY_HISTORY_RECENCY_WEIGHT` | `0.3` | Weight allocated to the time score in History scoring (match ratio = 1 - this value) |
| `USER_MEMORY_HISTORY_RECENCY_HALF_LIFE_DAYS` | `30` | Half-life of the History time score (days) |

### Background job management

Background threads running on Streamlit (RAG update, knowledge usage analysis, agent comparison, conversation digest generation, etc.) are tracked by `DigiM_JobRegistry`, and from the sidebar **Sessions -> Background Jobs**, you can list running jobs and cancel selected ones.

- **Displayed items**: Job kind / related session ID / message / elapsed seconds / cancellation request status
- **Scope**: Regular users see only jobs of their own `user_id`; Admins see all jobs
- **Cancellation method**: `cancel_requested` flag + `SystemExit` injection via `PyThreadState_SetAsyncExc`

**Limitations**:
- For C-extension I/O (e.g., during HTTP reception), the exception does not fire until the syscall returns (LLM streams return to Python every chunk, so they stop within seconds)
- Workers inside `ThreadPoolExecutor` are not registered as targets
- As an emergency hammer, resource leaks such as locks can occur. Use it to clear stuck jobs

### How to launch

```bash
# WebUI (Streamlit)
streamlit run WebDigiMatsuAgent.py --server.port 8501

# API (FastAPI)
python DigiM_API.py

# Benchmark (speed / output comparison of Support Agents)
# Input:  test/questions.xlsx (write questions in the `question` column)
# Output: test/questions_result_YYYYMMDD_HHMMSS.xlsx
python3 DigiM_SupportEval.py questions.xlsx                  # RAG query generation + meta search
python3 DigiM_SupportEval.py questions.xlsx --target intent  # RAG query generation only
python3 DigiM_SupportEval.py questions.xlsx --target meta    # meta search only
```

---

## Knowledge Explorer

Knowledge Explorer is the analytics screen for RAG data. Access it by switching from the sidebar radio button (Chat / Knowledge Explorer).

> **Access control:** Setting `"Knowledge Explorer": true` in the `Allowed` of the user master (`users.json`) makes it available. Users in the Admin group can always access it.

The screen consists of four sections stacked vertically: **Overall -> Trend -> Topic -> Ask Agent** (when the data source is Collection/VectorDB).

### Selecting a data source

Switch between **Collection (VectorDB)** and **PageIndex** via radio button. The list of collections is filtered based on the KNOWLEDGE and BOOK settings of the selected agent. When PageIndex is selected, it becomes a dedicated screen for tree-structure display / page sensitivity analysis.

> **Persona filtering:** When a Persona is selected in the sidebar, that persona's `define_code` is used to narrow chunks according to the **per-DATA `FILTER` (mapping in `DEFINE_CODE.CODES`)** of each KNOWLEDGE entry (same logic as the runtime RAG path `_build_where_limitation`). When multiple personas are selected, results are the **union** (e.g., `user_name in [Reika, Mone]`). If DATA has no `FILTER` or no persona is selected, no narrowing is applied (all chunks).

> **Explanation agent persona:** In Clustering / Trend / Topic explanations, if the selected explanation agent has `PERSONA_FILES`, a **Persona selector (optional / single)** appears and the explanation is generated under that persona (`(none)` skips). Multiple runs are recorded in the history as "Agent · persona / engine" and can be switched in the dropdown.

All analyses are fixedly displayed for **Total and per RAG NAME**. Heavy figures (scatter plot, bar chart, word cloud, etc.) are generated and rasterized once at analysis execution time, and are not recomputed on subsequent redraws (operability improvement).

> **Future date allowance:** All date inputs in Knowledge Explorer (Overall's `Date From/To`, the additional Period filter in Trend/Topic, and the Bonus Period in Topic) accept **future dates up to `2099-12-31`**. `Highlight Period` / `Cluster Period` are constrained inside `Date From-To`, so extending Date To into the future lets them extend along with it.

### 1. Overall

This section integrates initial data search and scatter plot generation.

| Element | Description |
|------|------|
| Filter | Column filter (multi-select), wildcard (`*`) text search, date range, Private exclusion |
| Scatter plot options | Dimensionality reduction (PCA / t-SNE), Color By, Marker By, Dot Size (Uniform / Newer=Larger / Highlight Period = enlarge only dots within a further period inside Date From-To) |
| **Search & Plot** | Run search and scatter plot generation with one button. **The scatter plot outputs Total + per RAG NAME**. Display order is **scatter plot -> data list (coordinates are based on Total) -> CSV** |
| Clustering | Clustering of the data narrowed by the search using **only Total** (K-Means / DBSCAN (eps auto-estimated) / Hierarchical). `Cluster Period From/To` further narrows within Date From-To. Each RAG NAME **applies the same cluster assignment / color defined for Total as-is** (no per-RAG re-clustering). Per-RAG NAME scatter plots are arranged in 2 columns |
| Clustering explanation | First explains the features of the clusters defined for Total, then explains based on which clusters each RAG NAME contains. The explanation agent and LLM engine can be selected and run multiple times. **One item can be selected from the history via dropdown**. The version on display is what gets exported in the report |

### 2. Trend (formerly Time-Series Analysis)

Available when `create_date` exists. Displayed fixedly for **Total / each RAG NAME** (View Mode selection has been removed).

- **Additional filters**: Period / RAG NAME / Collection (further narrow within Overall's range. Independent of Topic)
- **Period units**: Month (initial) / Quarter / Year, TF-IDF keyword extraction (nouns only, with stopword exclusion)
- **Category Column**: Changes only the breakdown of the stacked bar chart
- **Display per group (Total / each RAG NAME)**: Composition trend (stacked bar chart) -> keywords per period -> word cloud
- **Word cloud**: 4 horizontal columns, uniform size, arranged in **descending order of Period** (also displayed for Total)
- For RAG data with no period information (`create_date`), the RAG data name and "no time information" are shown
- **Trend explanation**: Does not output a "topic chronology"; rather, **Wikipedia-summary-like narrative text** weaving overall trends and notable changes (Total and each RAG NAME). Future topic predictions are **bulleted with rationale**. Uses the dedicated template `Trend Analyst`. Agent/engine selection, multiple runs, dropdown history switching
- **Explanation target period** (optional): When `Focus Period From/To` is specified, **the [Overview] focuses on the specified period's characteristics** with the whole-period data as background, and the [Future topic prediction] is presented as an outlook for after the target period. If unspecified, it uses the whole period as before + future topic predictions

### 3. Topic (formerly Sensitivity Analysis)

Analyzes which knowledge chunks react strongly to the query text (clustering is not included). Displayed fixedly for **Total / each RAG NAME**.

- **Additional filters**: Period / RAG NAME / Collection (within Overall's range, an independent filter separate from Trend)
- **Query input / Top N / Date Bonus**: The target period of Date Bonus is specified with **Bonus Period From/To**, **separately** from the filter's Period From/To
- **Overall chart**: Horizontal axis **Period** (initial value: month). Count (bar) + similarity score sum / average / max (lines) on dual axes, displayed per Total / each RAG NAME
- **Scatter plot**: For each of Total / each RAG NAME, the population (gray) is shown, and the selected items within it are shown with score shading
- **Data list**: With X1/X2 coordinates on the scatter plot
- **Topic explanation**: Content that intuitively describes the features / trends of knowledge likely to react to the input, for each of Total and each RAG NAME. Agent/engine selection, multiple runs, dropdown history switching

### 4. Ask Agent

You can ask the agent questions using the same pipeline as Chat (DigiMatsuExecute). The currently-displayed explanations of Overall/Trend/Topic are passed as context.

| Item | Description |
|------|------|
| Web Search | Enable Web search |
| Private Mode | Exclude Private data |
| Thinking Mode | AI thinking mode |
| Books | Enable Book reference |
| Conversation History | Retain conversation history within the session |
| Detail Information | Display execution detail information |
| Analytics Results | Knowledge usage analysis / agent comparison |

### PageIndex

- **Tree structure display**: Visualize the page index hierarchy as a tree
- **Page sensitivity analysis**: Page selection simulation by LLM

### Export / Report

The **Generate Report** button saves the analysis session and lets you download a `.md` file with embedded graphs. Each section's explanation is exported as **the version on display in the dropdown**.

### Session management

| Item | Description |
|------|------|
| Storage destination | `user/common/analytics/knowledge_explorer/analyticsYYYYMMDD_HHMMSS/` |
| State saving | Full state saved in pickle format |
| Loading | Restored by selecting from the session list in the sidebar |

---

## User Memory Explorer

A screen for analyzing User Memory (Persona/Nowaday/History) from a "user understanding" perspective. Switched via the sidebar radio button (Chat / Knowledge Explorer / **User Memory Explorer** / Scheduler). The backend is `DigiM_UserMemoryExplorer.py`.

> **Access control:** Available only to users with `Allowed["User Memory Explorer"]` set to `true` in `users.json` (default `false`). The Admin group always has access. This is independent of the `User Memory` (memory save) permission.

A 3-tab layout from the left: **"My Memory" / "User Understanding (Individual)" / "Group Understanding"**. "User Understanding (Individual)" / "Group Understanding" are read-only analytics + dialogue (`Clear Dialogue` clears the dialogue history) — the Individual tab is **User Memory + LLM-only** Chat with this User Twin, and the Group tab is the group's system prompt (LLM-generated, manually editable) + statistics block + LLM-only Chat with this Group Twin. "My Memory" is for confirming / modifying the logged-in user's own memory.

**My Memory (only your own memory)** — if you have `Allowed["User Memory Explorer"]`, you can edit your own 3 layers (other users cannot edit yours):
- Persona: role / summary_text / each list item (label override + status approved/pending/deleted) / Big5 (score 0-1 + status)
  - **Summary draft regeneration**: Calls `merge_persona(..., save=False)` with the latest Nowaday to regenerate a draft `summary_text` into the text area. **Nothing is saved until you press "Save Persona"**
- Nowaday: snapshot selection (period @ generation time, latest on top) -> summary_text / continuing / new / waning / change (one item per line) / 8 basic emotion intensities / secondary emotions
  - **New snapshot generation**: Choose a period mode (`YYYY-MM` / `since_YYYY-MM-DD` / `rolling_<N>d` / `all`) and generate a **new snapshot** (existing snapshots are not overwritten — history style)
- History: session selection -> topic / excerpt / emotion / confidence / active (when off, excluded from list / context)
- Each layer's Save button does `DigiM_UserMemory.upsert` only for that record (key items are preserved)

**User Understanding (Individual)** — select one user:
- Persona: role / summary / Big5 radar + a "trait / score" table on the right (status hidden) / items requiring review (pending)
- **Persona 6-attribute treemap + data table**: Visualizes `expertise / recurring_interests / values_principles / constraints / communication_style / avoid_topics` as a treemap (rows = field / area = confidence ratio / color = field) plus a data table (field = colored / confidence = progress bar / status = colored). Filterable by **Status** (default approved+pending)
- Nowaday: **snapshot selection (period @ generation time, latest on top)** -> period summary / basic emotion radar + an "emotion / score" table on the right / secondary emotions / continuing / new / waning / change
- History emotion trajectory: with a specified period (default = today through past 1 month), stacks Plutchik emotions of each session by date + per-session log
- **User × Agent relationship (button-driven)**: Pick an agent and press "Run analysis" to scan dialog history and render 7 panels (cached):
  - **(1) Basic summary** (5 KPI metrics): session count / turn count / total chars / average turns per session / last contact date
  - **(2) Activity trend**: with **Period (From-To)** + **granularity (Month/Week/Day)** selectors. Bar (sessions) + line (turns) on dual axes
  - **(3) Communication features**: averages of query chars / response chars / ratio + **seq-unit** query × response scatter (color = month)
  - **(4) Emotional tone**: basic-emotion radar from `history.emotions` (max-normalized) + top secondary emotions (derivation noted in caption)
  - **(5) Compatibility score (6-axis radar)**: Continuity / Frequency / Focus / Richness / Engagement / Knowledge use + auto "relationship label" (e.g., "Long-term / High-frequency / Theme-focused / Verbose response / High knowledge reliance")
  - **(6) Theme overlap**: top-10 of `axis_tags.interests/values/constraints` in 3 columns
  - **(7) Knowledge references (scatter + list)**: Scatter (X = avg similarity_Q / Y = avg knowledge_utility (sQ−sA) / color = category linked with `category_map.json` / size = reference count) + list (Bucket / Title / Category / CreateDate / refs / knowledge utility {sum, avg, median, max, min, variance})
- **Chat with this User Twin**: Dialogue with an AI (= a digital twin) that has only the selected user's memories. The agent is not selected; **only the LLM engine of the sidebar-selected agent** is selectable. Responds using only the context synthesized from Persona/Nowaday/History via the User Memory injection method (History is scored by question keywords) + LLM-only (the sidebar agent's personality / knowledge / system prompt are not used). The AI acts as the user themself, by their name

**Group Understanding** — select target users with multiselect (default = everyone, no filter):
- Persona: Big5 radar (max / mean / min, 3 series) + max/mean/min table, Persona word cloud, clustering (specify cluster count -> embedding -> PCA -> K-Means; table = user / cluster / coordinates / Big5) + cluster explanation (same as Knowledge Explorer)
- Nowaday: 8 basic emotion radar (max / mean / min) + table, secondary emotion ranking (total), 5 word clouds for summary / continuing / new / waning / change, clustering + cluster explanation
- History emotion trajectory (total): For all History of the target users, the Plutchik emotions are totaled and shown as bars
- **Chat with this Group Twin**: From the target group's Persona/Nowaday, generate a system prompt via LLM (manually editable) + attach a statistics block of Big5 / basic emotion averages / Top 5 secondary emotions. Select only the LLM engine of the sidebar-selected agent and dialogue with LLM-only

**Export Report / saved sessions** (same mechanism as Knowledge Explorer):
- **Generate Report** button: Aggregates the current state of the 3 tabs (deep-dive + User Twin dialogue, Group Understanding + Group Twin dialogue) into Markdown and saves to `user/common/analytics/user_memory_explorer/analyticsYYYYMMDD_HHMMSS/` as `meta.json` / `state.pkl` / `report.md`
- **Download (.md)**: Download the generated report
- **Sidebar**: While User Memory Explorer is displayed, restore from the list of saved sessions (latest 10)

| Item | Description |
|------|------|
| Group profile | Not a juxtaposition of individual summaries, but a synthesis of Big5 averages / emotion averages / top-N interests / representative History excerpts (with a character cap) |
| Storage destination | `user/common/analytics/user_memory_explorer/analyticsYYYYMMDD_HHMMSS/` |
| State saving | Pickle format saves the analysis cache / selection / dialogue history. `report.md` is output simultaneously |
| Data source | The 3 layers from `DigiM_UserMemory.load_all`. Formatting reuses `DigiM_UserMemoryBuilder` |

---

## Agent Performance Explorer (APE)

The agent-side counterpart of User Memory Explorer. Pick a target agent from the **Agent Performance Explorer** sidebar option and explore its cross-session performance. Backend: `DigiM_AgentPerformanceExplorer.py`. Requires `Allowed["Agent Performance Explorer"] = true`.

### Data sources (precedence: PG → live folders → archives)

| # | Source | Purpose |
|---|------|------|
| 1 | **PostgreSQL** (`digim_dialogs / digim_references / digim_sessions`) | Warehouse populated by the sidebar Sessions → **Export DB** button. Indexed and fast |
| 2 | **Live session folders** (`user/session2*/chat_memory.json`) | Sessions not yet Export-DB'd |
| 3 | **Archived ZIPs** (`user/archive/sessions_archive_*.zip`) | Compressed after `ARCHIVE_DAYS` |

De-duplicated by session_id with PG winning. The union gives the full history including archived sessions and not-yet-exported sessions.

### Tab 1: Overview

- Sessions / Turns / Users / Total chars / Avg turns per session
- Data period (first_ts – last_ts)
- Monthly activity bar chart
- Top Users table

### Tab 2: Knowledge / Book Utilization

Cumulative reference profile per KNOWLEDGE / BOOK / PageIndex entry:

- **Per-RAG summary**: Unique chunks / Total refs / Σ utility / Max utility
- **Value selector**: `count` / `Σ similarity_Q` / `Σ similarity_A` / `Σ utility`
- **Scatter (Vector RAG)**: every chunk in the backing collection as a gray background dot; referenced chunks overlaid
  - **Color**: by **sign** of the selected value — 🔵 blue (+) / 🔴 red (−) / ⚫ gray (0)
  - **Size**: scales with `|value|` by default; **Uniform size** checkbox flattens all referenced dots to a constant size
- **Page Tree (PageIndex RAG)**: same shape as Knowledge Explorer's PageIndex view. Referenced pages rendered in **blue** with `>>>` marker + `(N refs)` suffix; unreferenced ones in muted gray
- **Top chunks table**: by `ref_count` / by `Σ knowledge_utility` (top 10)

### Integration with Chat tab Analytics Results

The Chat tab's **"Analytics Results - Knowledge Utility"** button also renders a **Page Tree** when the referenced RAGs include any PageIndex (referenced pages in blue with ref counts). Both surfaces share the same `_render_ape_pageindex_tree` helper.

The Knowledge Utility scatter's **background dots** ("all chunks") are now scoped to the **persona-accessible subset** of the Chroma collection — the `where` filter is built from the persona's `define_code` at chat time so each persona sees its own knowledge space.

---

## Chat tab — other features

### Detail Information tabs

The "**Detail Information**" expander under each turn is now split into three tabs:

1. **LLM Input** — the actual LLM input recovered for this turn
   - **System Prompt** — reconstructed with the chat-time persona override
   - **Conversation Memories Loaded** — what was actually pulled from history
   - **Final Assembled Prompt** — the full user-message string (newlines preserved, wrapped `<pre>` block so the whole thing is visible top-to-bottom)
   - **Components Breakdown** — User Memory / RAG / Prompt Template Code / Situation / Web Context / AgentSearch / FunctionSearch
2. **Token Usage** — per-role table of consumed tokens
   - **Main LLM / Thinking / RAG Query Gen / Meta Search / Dialog Digest** — real token counts
   - **Web Search / Embedding** — estimated via `dmu.count_token` (`Note: estimated`)
   - **AgentSearch / FunctionSearch** — chunk count + response tokens
   - TOTAL row + a **Per-Model Summary** when multiple models were used
3. **Detail** — the previous text-block view (per-section Copy buttons)

### Compare Agent — regression with KNOWLEDGE / BOOK exclusion

After picking a compare agent in "Analytics Results - Compare Agents", two multiselects (`Exclude KNOWLEDGE (regression):` / `Exclude BOOK (regression):`) let you **remove specific RAG_NAME entries** before re-running the same question.

Example use: "What changes if I drop the `Comment` Knowledge? What about `SystemGuide` Book?" Multiple ablations stack in one session and their labels carry an `[-K:Comment,Diary]` style suffix. Available on both the Chat tab and Knowledge Explorer side.

### Draft input mode

The chat input is **always editable** even while a previous turn is running. On Enter:

- **Idle** → runs immediately as usual
- **Busy** → stashed into `draft_input`, a `📝 下書き:` banner appears above the chat input

The banner has `Send draft` / `Discard` buttons. Send becomes enabled once the previous turn finishes. Re-submitting overwrites the draft; slash commands (`/skill_name …`) are preserved verbatim.

---

## Batch Test (bulk Q&A evaluation)

The `Batch Test (upload Q&A xlsx)` expander at the bottom of the Chat screen runs a spreadsheet of questions through **the current session with the current chat settings**, and — when a Ground Truth column is present — auto-scores each answer with LLM + deterministic metrics.

### Input Excel format

| Column | Required | Description |
|------|------|------|
| `Question` | ✓ | The question text |
| `Question Style` / `QuestionStyle` | – | When present, prepended to the query (`Question Style\nQuestion` sent to the agent). Both spaced and camelCase variants are accepted |
| `No` | – | Row identifier. Referenced by `Memory No` to pin specific prior rows for history |
| `Memory No` / `MemoryNo` | – | Per-row history access control (see below). Both spaced and camelCase variants are accepted |
| `Ground Truth` | – | Expected answer. Triggers evaluation when present |
| `Answer` | – | Filled in by the run |
| Any other column | – | Preserved verbatim in the output |

**`Memory No` semantics**

| Cell value | Effect |
|------|------|
| `All` | Full history (MEMORY_USE=True) |
| `1, 3` / `1,3` / `1; 3` / `1 3` | Load history ONLY from the rows whose `No` is 1 or 3 (others get `MEMORY_FLG=N` for the duration of this row, then restored) |
| Empty cell | No history (MEMORY_USE=False) |
| `Memory No` column absent | All rows: no history |

When a `Memory No` column is present, `MEMORY_SAVE` is auto-promoted to True so the seq map stays populated. Separators: comma / semicolon / whitespace. Excel's `1.0` auto-coercion is normalised back to `1`.

- **Multi-sheet xlsx** is supported: every sheet that has a `Question` column is auto-detected; a dropdown lets you target one sheet or run them all. Each input sheet is written back to a same-named output sheet.
- **Sheet name is arbitrary** (no need to be called `Test`).
- Sample: `test/Sample_BatchTest.xlsx`.

### Output Excel format

Input columns are preserved as-is; the following are appended (overwritten if already present):

| Column | Content |
|------|------|
| `Persona` | Persona name for the run (multi-persona only). Empty for 0/1 persona |
| `Answer` | The agent's response |
| `Verdict` | LLM verdict (○ / △ / ✕) |
| `Score` | 0-100 (LLM-judged against `Ground Truth`) |
| `Match` | `Y` / `N` — exact match after normalisation |
| `Seq Ratio` | `difflib.SequenceMatcher` ratio (0-1) |
| `Token F1` | Token-overlap F1 over word + CJK-char tokens (0-1) |
| `Eval` | One-line LLM comment |

### Key features

- **Per-row history is fully driven by the `Memory No` column**: the previous `Memory Use (BatchTest only)` checkbox has been removed in favour of `No` + `Memory No` columns, which let you express "this row sees rows 1 & 3" / "this row sees nothing" at row granularity rather than one toggle for the whole run.
- **`Save Digest (BatchTest only)` checkbox**: independent toggle to suppress digest generation. OFF saves cost / time on large runs. Independent from the chat header `Save Digest`.
- **Honors the sidebar persona selection**: when 2+ persona ids are selected, each question is run in **multi-persona parallel mode** and the result xlsx is written in **long format** (one row per question × persona).
- **Progress display**: the sidebar bg-task message shows `(N/N) Running batch Q&A...` in near-real-time (counter ticks per persona completion).
- **Result file picker**: a dropdown switches between past `batch_results_*.xlsx` files for download / analysis.

### Result Analysis (instant)

Reads the result xlsx from the session folder and renders a cross-sheet summary plus per-sheet panels:

- Verdict (○/△/✕) distribution bar chart
- Score histogram (0-100, 10-wide bins)
- Count / Score avg / ○ ratio / Exact-match count
- Worst-5 rows table

### LLM critique (on-demand)

"LLM評価を生成" sends the summary + worst rows (up to 5 per sheet) to the LLM and produces a Markdown critique cached to `batch_results_<TS>.critique.md`:

- **Overall** (2-3 lines)
- **Failure patterns** (pattern name / example / hypothesised cause)
- **Improvements** (concrete actions on Agent JSON / KNOWLEDGE / prompts / etc., ordered by priority)

### Implementation notes

- Multi-persona mode auto-sets `MEMORY_SAVE=True` (the parallel path only streams `[STATUS]` chunks; per-persona responses are read from chat_memory's sub_seqs of the latest seq).
- Evaluation uses `dmt.eval_answer_vs_groundtruth` in `user/common/tool/analysis.py`. Default LLM agent for the verdict step is `agent_53CompareTexts.json`.
- LLM critique uses `dmt.critique_batch_results` (same file).

---

## Evaluation

Sidebar → **Evaluation**: a plugin host for evaluation tests. Requires `Allowed["Evaluation"] = true`. Backend: [DigiM_Evaluation.py](DigiM_Evaluation.py).

### Plugin architecture

Drop a `Plugin` class under `user/common/evaluation/<name>/main.py` and it shows up in the picker automatically. **Plugin contract**:

```python
class Plugin:
    name         = "<internal id>"
    display_name = "<UI label>"
    description  = "<short blurb>"

    @staticmethod
    def sample_path() -> str | None:
        "Path to a sample input (used as the downloadable template)."

    @staticmethod
    def run(input_path: str) -> dict:
        "Heavy lifting. Returns a dict consumed by render & report below."

    @staticmethod
    def render(result: dict) -> None:
        "Streamlit render (st.pyplot / st.dataframe / ...)."

    @staticmethod
    def report_md(result: dict) -> str:
        "Markdown for `Generate Report`."
```

LLM critique is provided by the generic `DigiM_Evaluation.llm_evaluate()` helper — it formats `report_md` and asks a chosen agent to write a critique in 4 sections (全体評価 / 強み / 弱み / 改善提案). Plugins may override by exposing their own `llm_evaluate(...)`.

### UI flow

1. Pick a plugin from the dropdown
2. **Download template (.xlsx)** — when the plugin's `sample_path()` points to a real file
3. **Upload input (.xlsx)** — the filled-in spreadsheet
4. **Run analysis** → plugin's `run()` → `render()` displays the result
5. **LLM Evaluation** — choose an agent → `Evaluate with LLM` (the critique is cached on the result)
6. **Generate Report** → Markdown export including the LLM critique

### PersonalEvaluation plugin

Scores 7 personality theories at once: Big Five / Schwartz Value Theory / Self-Determination / Personal Strivings / Narrative Identity / Social Identity / Attachment. Template ships in the plugin folder itself (`user/common/evaluation/PersonalEvaluation/PersonalTestQA.xlsx`) — grab it from the `Download template (.xlsx)` button.

**Input Excel** — 2 sheets:
- `Category`: 7 rows of theory metadata
- `PersonalTest`: Q/A rows (`No / Category / Question Style / Question / Memory No / Memo / Answer / Ground Truth / Compare`)

**Scoring**:
- The `Memo` column is parsed into `(axis_label, reverse_flag)` — e.g. "神経症傾向の逆（Emotional Stability）" → axis=`Emotional Stability`, reverse=True.
- Answer keywords → 0–1 scores: `はい/Agree`→1.0, `どちらでもない/Neutral`→0.5, `いいえ/Disagree`→0.0; bare `1-5` / `1-7` scales are auto-normalised.
- 4 categories (Traits / Values / Motivations / Attachment) get a **radar chart** + score table.
- 3 narrative-only categories (Goals / Identity / Sociability) are rendered as text and read by the LLM critique step.

### Adding a new evaluation

Drop a `<name>/main.py` under `user/common/evaluation/` that defines the `Plugin` class — the picker auto-discovers it on next page load. No restart, no registration step.

---

## API Reference

When FastAPI is launched, you can execute the agent via REST API. It also supports calls from external services such as LINE / Slack.

### Endpoint list

| Method | Path | Description |
|---------|------|------|
| `POST` | `/run` | Send a message and get the agent's response (synchronous) |
| `GET` | `/agents` | Get the list of available agents |
| `GET` | `/agents/{agent_file}/engines` | Get the list of engines available for the agent |
| `GET` | `/agents/{agent_file}/feedback` | Get the agent's feedback settings |
| `GET` | `/web_search_engines` | Get the list of available Web search engines |
| `POST` | `/feedback` | Send feedback (saved to CSV/Notion) |
| `GET` | `/sessions` | Get the session list |
| `GET` | `/sessions/{session_id}` | Get the conversation history of a session |
| `GET` | `/health` | Health check |

### POST /run — Send a message

A single HTTP request completes one LLM execution and returns the response directly. The conversation continues when the same `session_id` is specified.

If the same session is in execution (LOCKED), it waits up to 60 seconds and runs after release. On timeout, it returns `429`.

**Request:**

```json
{
  "service_info": {"SERVICE_ID": "ServiceName", "SERVICE_DATA": {}},
  "user_info": {"USER_ID": "UserID", "USER_DATA": {}},
  "session_id": "SessionID",
  "session_name": "SessionName",
  "user_input": "Message body",
  "situation": {"TIME": "", "SITUATION": ""},
  "agent_file": "AgentFileName",
  "engine": "EngineName",
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

**Basic parameters:**

| Parameter | Required | Default | Description |
|-----------|------|-----------|------|
| `service_info` | Yes | | Service identification (`SERVICE_ID` distinguishes services) |
| `user_info` | Yes | | User identification (`USER_ID` distinguishes users) |
| `user_input` | Yes | | The user's input message |
| `session_id` | | Auto-issued | Session ID. For LINE integration, specifying the LINE user ID continues the conversation |
| `session_name` | | Auto-generated | Session name |
| `agent_file` | | `API_AGENT_FILE` | The agent to use (e.g., `agent_10Sample.json`) |
| `engine` | | Agent's DEFAULT | LLM engine name (e.g., `Gemini-2.5-Flash`). Specify a name defined in the agent's ENGINE.LLM |
| `situation` | | `{"TIME":"","SITUATION":""}` | Date/time / situation settings. If `TIME` is empty, executes without date/time |

**Execution settings (Exec Setting):**

API default values are used for omitted parameters. These correspond to the WebUI's Exec Setting.

| Parameter | API default | Description |
|-----------|-------------|------|
| `stream_mode` | `true` | Streaming mode |
| `save_digest` | `true` | Save the conversation digest |
| `memory_use` | `true` | Reference the conversation history |
| `magic_word_use` | `false` | Habit switching by MAGIC_WORD |
| `meta_search` | `true` | Metadata search (date extraction) |
| `rag_query_gene` | `true` | Query generation for RAG search |
| `web_search` | `false` | Web search (when `true`, searches with the engine specified by `web_search_engine`) |
| `web_search_engine` | `"OpenAI"` | Web search engine (`Perplexity` / `OpenAI` / `Google`). Not used when `web_search` is `false` |
| `private_mode` | `false` | Private Mode. When `true`, RAG data with `private: true` is excluded from search |
| `thinking_mode` | `false` | Thinking Mode. When `true`, the AI analyzes the question and dynamically decides Habit / Web search / RAG query generation / Book addition |
| `user_memory` | (unspecified) | Whether to use User Memory (information about the dialogue partner). `true` = all layers ON / `false` = all Off / unspecified = follows `Allowed["User Memory Layers"]` in `users.json` (or `USER_MEMORY_DEFAULT_LAYERS` if absent) |
| `user_memory_layers` | (unspecified) | Explicitly specify enabled layers (subset of `["persona","nowaday","history"]`, `[]` to turn all off). When specified, takes priority over `user_memory`. Invalid layer names are ignored |

> `memory_similarity` is always `false` via the API (the parameter cannot be specified).
>
> User Memory injection is enabled only when `memory_use=true` (the API default) and at LLM execution time (even if `user_memory` is specified, it is not injected if `memory_use=false`). When enabled, the User Memory text is also included as input to RAG search query generation.

**Response:**

```json
{
  "session_id": "API_TEST_001",
  "session_name": "(User:TestUser) Question about AI",
  "response": "Agent response text"
}
```

### Execution examples

```bash
# Health check
curl -s http://localhost:8899/health

# List agents
curl -s http://localhost:8899/agents | python3 -m json.tool --no-ensure-ascii

# Send message (new session)
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_001",
    "user_input": "Hello, please introduce yourself.",
    "agent_file": "agent_10Sample.json"
  }' | python3 -m json.tool --no-ensure-ascii

# Continue the conversation in the same session
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_001",
    "user_input": "Tell me about the future of AI",
    "agent_file": "agent_10Sample.json"
  }' | python3 -m json.tool --no-ensure-ascii

# Run with a specific engine
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_002",
    "user_input": "Tell me about quantum computers",
    "agent_file": "agent_10Sample.json",
    "engine": "Gemini-2.5-Flash"
  }' | python3 -m json.tool --no-ensure-ascii

# Run with all parameters explicitly set to defaults
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_001",
    "user_input": "Hello",
    "agent_file": "agent_10Sample.json",
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

# Lightweight execution (RAG query generation OFF + meta search OFF)
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "API_TEST_003",
    "user_input": "Hello",
    "agent_file": "agent_10Sample.json",
    "rag_query_gene": false,
    "meta_search": false
  }' | python3 -m json.tool --no-ensure-ascii

# Without conversation history (one-shot question mode)
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "user_input": "Please introduce yourself",
    "agent_file": "agent_10Sample.json",
    "memory_use": false,
    "save_digest": false
  }' | python3 -m json.tool --no-ensure-ascii

# Explicitly enable User Memory (example using only Persona + History)
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "RealMatsumoto", "USER_DATA": {}},
    "user_input": "Make a suggestion taking my recent interests into account",
    "agent_file": "agent_10Sample.json",
    "user_memory_layers": ["persona", "history"]
  }' | python3 -m json.tool --no-ensure-ascii

# Explicitly disable User Memory (user_memory=false turns everything off)
curl -s -X POST http://localhost:8899/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "RealMatsumoto", "USER_DATA": {}},
    "user_input": "Explain from a general perspective",
    "agent_file": "agent_10Sample.json",
    "user_memory": false
  }' | python3 -m json.tool --no-ensure-ascii

# Session list (filtered by user)
curl -s "http://localhost:8899/sessions?user_id=TestUser" | python3 -m json.tool --no-ensure-ascii

# Session history
curl -s http://localhost:8899/sessions/API_TEST_001 | python3 -m json.tool --no-ensure-ascii

# Engine list (LLM / IMAGEGEN engines selectable by an agent)
curl -s http://localhost:8899/agents/agent_10Sample.json/engines | python3 -m json.tool --no-ensure-ascii

# Web search engine list
curl -s http://localhost:8899/web_search_engines | python3 -m json.tool --no-ensure-ascii

# Verify feedback settings (feedback items / categories accepted by the agent)
curl -s http://localhost:8899/agents/agent_10Sample.json/feedback | python3 -m json.tool --no-ensure-ascii

# Submit feedback (feedback against the seq=1, sub_seq=1 turn)
curl -s -X POST http://localhost:8899/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "API_TEST_001",
    "agent_file": "agent_10Sample.json",
    "seq": "1",
    "sub_seq": "1",
    "feedbacks": {
      "name": "Feedback",
      "memo": {"visible": true, "flg": true, "memo": "Helpful", "category": "AI"}
    }
  }' | python3 -m json.tool --no-ensure-ascii
```

> In HTTPS environments, read `http://localhost:8899` as `https://your-domain.com/api`. LLM execution takes 10-30 seconds, so beware of timeouts.

### LINE integration usage example

Image of a call from a LINE Messaging API webhook.

```python
# LINE Webhook -> FastAPI call example
import requests

def handle_line_message(line_user_id, message_text):
    response = requests.post("https://your-domain.com/api/run", json={
        "service_info": {"SERVICE_ID": "LINE", "SERVICE_DATA": {}},
        "user_info": {"USER_ID": line_user_id, "USER_DATA": {}},
        "session_id": line_user_id,  # Use the LINE user ID as the session ID
        "user_input": message_text,
        "agent_file": "agent_10Sample.json"
    }, timeout=120)
    return response.json()["response"]
```
