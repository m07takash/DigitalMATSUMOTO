**[日本語](FEATURE_LIST.md)** | **English**

# Digital MATSUMOTO Feature List (Conceptual Level)

## Overall Architecture

```
┌─────────────────────────────────┐
│  UI／インターフェース層          │  人間やシステムとの接点
├─────────────────────────────────┤
│  アプリケーション層              │  実行制御・判断・分析
├─────────────────────────────────┤
│  コンテキストデザイン層          │  AIに与える文脈の設計
├─────────────────────────────────┤
│  データ／ナレッジ層              │  知識・記憶・履歴の管理
├─────────────────────────────────┤
│  インフラ／基盤層                │  LLM接続・認証・永続化
└─────────────────────────────────┘
```

---

## 1. Infrastructure / Foundation Layer (Connect, Protect, Maintain)

| # | Feature | Overview |
|---|---------|----------|
| 1-1 | Multi-LLM Abstraction | Call GPT/Gemini/Claude/Grok through a unified interface |
| 1-2 | Multi Image-Generation Abstraction | Call DALL-E/Gemini image generation through a unified interface |
| 1-3 | Token Counting | Measure prompt/response token counts with each model's tokenizer |
| 1-4 | Text Sanitization | Remove characters that cannot be parsed as JSON (NUL, lone surrogates, control characters) from LLM input |
| 1-5 | Vector Embedding | Convert text into numeric vectors using an embedding model |
| 1-6 | Similarity Computation | Compute semantic closeness between vectors via cosine distance and similar metrics |
| 1-7 | Vector DB Management | Create, query and update metadata for ChromaDB collections |
| 1-8 | Session Persistence | Save chat history, settings and vectors to the file system |
| 1-9 | File Locking | Mutex / exclusive control of concurrent writes to the same session |
| 1-10 | Status Management | Manage session LOCK/UNLOCK/error states in YAML and keep them in sync with the UI |
| 1-11 | User Authentication | Login authentication using bcrypt hashes and HMAC-signed cookies |
| 1-12 | Access Control | Show/hide features and agents based on user groups and Allowed settings |
| 1-13 | Environment Configuration | Manage external configuration through setting.yaml / system.env |
| 1-14 | Image MIME Type Detection | Dynamically determine an image's MIME type from its file extension |
| 1-15 | Authentication Backend Toggle | Switch between JSON / RDB (`digim_users`) via `LOGIN_AUTH_METHOD` |
| 1-16 | Agent Persona Source Toggle | Switch between EXCEL / RDB (`digim_agent_personas`) / BOTH via `AGENT_PERSONA_SOURCE` |
| 1-17 | Automatic URL Fetching | Extract URLs from text, apply SSRF protection, blocklists, and sub-page crawling, then attach the content (`DigiM_UrlFetch.py`) |

---

## 2. Data / Knowledge Layer (Accumulate and Organize Knowledge)

| # | Feature | Overview |
|---|---------|----------|
| 2-1 | CSV Data Ingestion | Generate RAG chunk data from CSV files |
| 2-2 | Notion Data Ingestion | Generate RAG chunk data from a Notion DB according to property types |
| 2-3 | Incremental Vectorization | Re-vectorize only the chunks whose title/key/value have changed; for the rest, update metadata only |
| 2-4 | Private Flag | Give RAG chunks a public/private attribute |
| 2-5 | Private Flag Migration | Bulk-apply private=false to existing data |
| 2-6 | Category Filter | Filter RAG data by category conditions before registering to a collection |
| 2-7 | Structured Conversation History Storage | Save prompts, responses, settings and digests in a seq/sub_seq hierarchy |
| 2-8 | Content File Management | Save uploaded/generated files under the session directory |
| 2-9 | Session Archiving | Archive old sessions by compressing them into ZIP files |
| 2-10 | PostgreSQL Export | Export sessions, dialogues and references to an RDB |
| 2-11 | Feedback Storage | Save user feedback to CSV or Notion |
| 2-12 | User Dialogue Storage | Save user utterance trends to CSV or Notion |
| 2-13 | Master Data Management | Master definitions for users, RAG, prompt templates, categories, etc. |
| 2-14 | Hierarchical User Memory Storage | Store the three layers - short-term (History) / mid-term (Nowaday) / long-term (Persona) - to EXCEL / NOTION / RDB backends (selectable per layer) |
| 2-15 | User Memory Emotion Data | Store Plutchik's 8 basic emotions and secondary emotions (dyads) scores into History/Nowaday |
| 2-16 | Scheduled Job Definition Storage | Save kind / cron / target / enabled in `scheduled_jobs.json` and restore them after restart |
| 2-17 | Page Index RAG | Save page indexes derived from Excel/Notion (`_index.json` + `.md`) locally and use them as PageIndex-type RAG |

---

## 3. Context Design Layer (Design What to Tell the AI)

### Personality Context

| # | Feature | Overview |
|---|---------|----------|
| 3-1 | System Prompt Auto-Generation | Dynamically build the system prompt from personality settings (name, gender, nationality, Big5, tone) |
| 3-2 | Character Definition | Describe a detailed personality (background, values, first-person pronoun, etc.) in an external text file |
| 3-3 | Big5 Personality Model | Set the five factors (Openness, Conscientiousness, Extraversion, Agreeableness, Neuroticism) on a 0-1 scale and reflect them in the AI's behavior |
| 3-4 | Tone Templates | Inject speaking styles such as Polite (丁寧語), Samurai (武士語), or Gyaru (ギャル語) into the prompt |
| 3-4b | Plutchik Emotion Model | Record the 8 basic emotions (Joy/Trust/Fear/Surprise/Sadness/Disgust/Anger/Anticipation) and secondary emotions (dyads) into user memory, and reflect that state in the context |
| 3-4c | Multi-Persona Parallel Execution | For a single template agent, switch ORG/Persona in a matrix and generate responses from multiple personas in parallel (`MAX_PARALLEL_PERSONAS`). `PersonaSelector` can auto-select via Thinking |

### Knowledge Context (RAG)

| # | Feature | Overview |
|---|---------|----------|
| 3-5 | Header Templates | Define header text that makes the AI recognize the knowledge domain (Identity/Experience, etc.) |
| 3-6 | Chunk Templates | Format each knowledge chunk with semantic metadata such as timestamps and similarity scores |
| 3-7 | Log Templates | Define the format of knowledge-chunk reference logs for analysis and visualization |
| 3-8 | Text Size Limits | Set per-domain character limits for the RAG context |
| 3-9 | Timestamp Annotation | Annotate chunks with their date and a "how many days ago" elapsed time to convey freshness |
| 3-10 | Similarity Ranking | Select and order chunks by similarity to the query |
| 3-11 | Metadata Search Bonus | Add a similarity bonus to chunks that match date conditions |
| 3-12 | Context Filter | Narrow the RAG search scope by service ID, user ID, definition code, etc. |
| 3-13 | Private Mode | Exclude private=true data from RAG search results |

### Conversation Context

| # | Feature | Overview |
|---|---------|----------|
| 3-14 | Conversation Memory Selection | Include past conversation history in the prompt within a token budget |
| 3-15 | Memory Role Filter | Choose which role's utterances to include: user/assistant/both |
| 3-16 | Memory Priority | Select conversation memory by latest (newest first) / oldest (oldest first) / similar (similarity order) |
| 3-17 | Memory Similarity | Pick relevant memories by the semantic closeness between the current query and past conversation |
| 3-18 | Conversation Digest | Summarize and compress long conversation history and include it in the context |

### Situation Context

| # | Feature | Overview |
|---|---------|----------|
| 3-19 | Situation Settings | Inject the current date/time and situation into the prompt |
| 3-20 | Fictional Time Settings | Inject a fictional time setting that differs from real time as a strong instruction |

### Input Context

| # | Feature | Overview |
|---|---------|----------|
| 3-21 | Content Context Generation | Parse uploaded files (text/PDF/JSON/image/audio) and include them in the prompt |
| 3-22 | Web Search Context | Append web search results as "reference information" to the prompt |
| 3-22b | URL Attachment Context | Automatically fetch URLs in the input and turn them into content context (supports sub-page crawling) |

### User Understanding Context (Hierarchical User Memory)

| # | Feature | Overview |
|---|---------|----------|
| 3-25 | Long-term Persona Injection (Persona) | Inject the user's areas of expertise, interests, values, communication style and Big5 (approved items only) within the token limit |
| 3-26 | Mid-term Trend Injection (Nowaday) | Inject recurring topics, emerging/declining trends and emotional transitions for the recent period (period=YYYY-MM, etc.) on a per-snapshot basis |
| 3-27 | Short-term Session Injection (History) | Select related session summaries by a hybrid of tag matching x time score (with half-life) and inject them |
| 3-28 | Injection Token Control | Control per-layer limits with `USER_MEMORY_LONG_TOKEN_LIMIT` / `_LONG_MAX_CHARS_PER_FIELD` / `_SHORT_MAX_CHARS` |
| 3-29 | Per-Layer On/Off | Enable/disable each layer both per user (`Allowed["User Memory Layers"]`) and at engine execution time (IMAGEGEN steps are auto-skipped) |
| 3-30 | Context for RAG Query Generation | Pass the user-memory summary as input to the RAG-query-generation agent to improve search accuracy |

### Prompt Design

| # | Feature | Overview |
|---|---------|----------|
| 3-23 | Prompt Templates | Manage instruction templates for various purposes (normal chat, consideration, senryu, image generation, etc.) |
| 3-24 | Prompt Assembly | Concatenate knowledge context, templates, user input and situation to build the final prompt |

---

## 4. Application Layer (Decide, Execute, Analyze)

### Execution Control

| # | Feature | Overview |
|---|---------|----------|
| 4-1 | Practice Chain | Pipeline that executes multiple steps in order (LLM->LLM, LLM->image generation, etc.) |
| 4-2 | Inter-step Data Flow | Pass the previous step's output (OUTPUT) and content (EXPORT) as input to the next step |
| 4-3 | Agent Switching | Use different agents (persona, model) for each step in the chain |
| 4-4 | Setting Override | Dynamically override agent engine settings at runtime |
| 4-5 | Streaming Response | Return the LLM response in real time, token by token |
| 4-6 | Background Execution | Run in a background thread without blocking the UI and poll for completion |
| 4-7 | Session Lock Control | Prevent double execution while running, and prevent erroneous UNLOCK from intermediate digests of multi-chain runs |
| 4-7b | Scheduler (JobRegistry) | Generic cron-driven job execution via `DigiM_Scheduler` + `DigiM_ScheduledJobs`. kind=`rag_update`/`user_memory_nowaday`/`agent_run`, etc. Add / Edit / Run Now / Enable/Disable / Reload Schedulers from the WebUI |

### Autonomous Decision

| # | Feature | Overview |
|---|---------|----------|
| 4-8 | Magic Word Detection | Switch Habit (behavior) based on keyword matches in the user input |
| 4-9 | Thinking Mode | The AI analyzes the question and dynamically decides Habit, web search, RAG query strategy, and Book additions |

### Support Agents

| # | Feature | Overview |
|---|---------|----------|
| 4-10 | RAG Query Generation | Infer the underlying psychology of the user's question and generate auxiliary queries suited for RAG search |
| 4-11 | Date Extraction | Extract date information from the user's question and convert it into a metadata search condition |
| 4-12 | Conversation Digest Generation | Summarize the conversation history to compress memory usage |
| 4-13 | Session Name Generation | Automatically generate a thread name within 15 characters from the conversation content |
| 4-14 | User Dialogue Analysis | Extract and record the user's utterance tendencies |
| 4-15 | Image Critique | Comment on an image's overview, expression and impression from a curator's perspective |
| 4-16 | Text Comparison | Compare and evaluate two response texts |
| 4-16b | Persona Selector | In Thinking Mode, automatically select up to N appropriate personas within an ORG based on the question content (`MAX_PERSONAS`) |
| 4-16c | User Memory Generation (History) | At session end, summarize the dialogue and generate topics, excerpts, tags, emotions and confidence |
| 4-16d | User Memory Generation (Nowaday) | On schedule (monthly/weekly/cron), aggregate History and produce snapshots of recurring topics, emerging/declining trends, and emotional transitions |
| 4-16e | User Memory Generation (Persona) | Update the long-term persona (role, expertise, interests, values, Big5) from Nowaday snapshots and History. Auto-approve when above the confidence threshold; otherwise mark as pending |

### Analysis

| # | Feature | Overview |
|---|---------|----------|
| 4-17 | Knowledge Utilization Analysis | Compute each RAG chunk's contribution from the difference between question similarity and answer similarity |
| 4-18 | Dimensionality Reduction Visualization | Plot RAG chunk distributions in 2D with PCA/t-SNE |
| 4-19 | Agent Comparison Analysis | Compare and evaluate responses from different agents to the same question |
| 4-20 | Support Agent Evaluation | Benchmark the speed and quality of RAG query generation and date extraction using a test question set |
| 4-21 | Ethical Check | Evaluate responses across 10 inappropriate-expression categories |
| 4-22 | Knowledge Explorer Integrated Analysis | Unified analysis of RAG/PageIndex topic distribution, time-series trends, Focus Period, and chunk similarity clustering (reproducible from saved sessions) |
| 4-23 | Knowledge Utility Analysis | Color-coded plot of knowledge contribution by query type. Generated with stable file names |
| 4-24 | User Memory Explorer Analysis | Cross-aggregate the three memory layers per user / per group. Big5 radar, word cloud, PCA+K-Means clustering, interest topic transitions, emotion trajectory |
| 4-25 | User/Group Twin Dialogue | Ground the dialogue in user memory and converse with an individual/group digital twin |

---

## 5. UI / Interface Layer (Interface with Humans and External Systems)

### WebUI (Streamlit)

| # | Feature | Overview |
|---|---------|----------|
| 5-1 | Chat Screen | Chat-style display of user/AI/detail information |
| 5-2 | Engine Selection | Switch LLM/IMAGEGEN engines via dropdown |
| 5-3 | Book Selection | Select additional knowledge sources via multi-select |
| 5-4 | Web Search Toggle | Enable web search and select the engine |
| 5-5 | Private Mode / Thinking Mode Toggle | Toggle modes near the chat input |
| 5-6 | Exec Setting | Control execution options such as streaming/memory/digest |
| 5-7 | File Upload | Attach text/PDF/CSV/JSON/image/audio files |
| 5-8 | Detail Information | Detailed display of execution info, logs, Thinking results, RAG context, and web search results |
| 5-9 | Feedback Input | Input category, notes, and comments for each response |
| 5-10 | Analysis Dashboard | Run and display the results of knowledge utilization analysis and agent comparison |
| 5-11 | Session Management | List, search, switch, delete and archive sessions |
| 5-12 | Markdown/PDF Download | Export conversation history in Markdown or PDF format |
| 5-13 | RAG Management | Update and list RAG data, plus Page Index Export (Excel + individual .md as a ZIP) |
| 5-14 | Polling Monitor | Display status messages and partial responses every 2 seconds during background execution |
| 5-15a | Knowledge Explorer Screen | RAG analysis screen switched from the sidebar. Overall / Trend / Topic / Ask Agent / Generate Report. Reproducible from saved sessions (`Allowed["Knowledge Explorer"]`) |
| 5-15b | User Memory Explorer Screen | Three tabs: My Memory / Individual / Group. Edit and analyze the three memory layers and converse with User/Group Twin (`Allowed["User Memory Explorer"]`) |
| 5-15c | Scheduler Screen | Add / Edit / Run Now / Enable/Disable / Delete / Reload Schedulers for scheduled jobs |
| 5-15d | User Memory Panel | Toggle each layer on/off in an expander on the chat side. The memory body is edited from the User Memory Explorer |
| 5-15e | Feedback Detail | Input category, notes and comments. Stored to CSV (`user/common/csv/`) or Notion depending on `SAVE_DB` |

### REST API (FastAPI)

| # | Feature | Overview |
|---|---------|----------|
| 5-16 | Message Send API | Execute an agent via `/run` (supports calls from external services such as LINE/Slack). Memory injection can be enabled and per-layer via the `user_memory` / `user_memory_layers` parameters |
| 5-17 | Session Retrieval API | Retrieve session lists and history via `/sessions` and `/sessions/{id}` |
| 5-18 | Agent Information API | Retrieve agent lists, engine lists and feedback settings via `/agents`, `/agents/{file}/engines`, `/agents/{file}/feedback`. Get the list of search engines via `/web_search_engines` |
| 5-19 | Feedback Submission API | Submit feedback from external sources via `/feedback` |
| 5-20 | Function Execution API | Call tool functions directly via `/run_function` (through Function Calling) |
| 5-21 | Health Check API | Return liveness via `/health` |
