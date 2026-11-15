// Sample Agent Demo recording. Load via <script src>.
// ---------------------------------------------------------------------------
// A hand-authored example of the WebUI-style chat flow: sidebar options,
// a background run polled to completion, the turn view, a turn's Detail
// Information, Memory Off and the chat session list. Replace freely.
// ---------------------------------------------------------------------------

window.Recorder && window.Recorder.register({
  id: "sample_async_chat",
  meta: {
    title: "Sample WebUI-style chat (background run + turn actions)",
    createdAt: "2026-11-15T09:00:00Z",
    backendUrl: "http://localhost:8899"
  },
  events: [
    {
      t: 300, type: "api", method: "GET", path: "/agents/agent_11Sample.json/chat_options", status: 200,
      request: null,
      response: {
        agent_file: "agent_11Sample.json", agent_name: "Sample Agent 2",
        LLM: { default: "GPT-6.1-Sol", engines: ["GPT-6.1-Sol", "Gemini-3.5-Flash-Lite"] },
        IMAGEGEN: { default: "", engines: [] },
        skills: [
          { name: "WebSearch", phase: "BEFORE", label: "WebSearch", default: false, flag: false, merge: "CONTEXT",
            description: "Search the web and pass the result to the answer." },
          { name: "diagram_mode", phase: "BEFORE", label: "Diagrams", default: false, flag: true, merge: "RECORD",
            description: "Ask for Markdown tables and Mermaid diagrams where they clarify the explanation." },
          { name: "cite_knowledge", phase: "AFTER", label: "Reference Knowledge", default: true, flag: true, merge: "RECORD",
            description: "Append a '## Reference Knowledge' section listing the KNOWLEDGE chunks the turn actually used." }
        ],
        books: [{ rag_name: "Articles", retriever: "Vector" }],
        orgs: [{
          org: { company: "寄稿先エディター陣" }, label: "company=寄稿先エディター陣",
          personas: [{ persona_id: "E0001", name: "三宅慧" }, { persona_id: "E0002", name: "榊原一平" }]
        }],
        thinking: { mode: false, targets: [], max_turns: 1,
                    options: ["Habit", "Web Search", "RAG Query", "Books", "Skills", "Personas"], max_personas: 3 },
        execution_defaults: { MEMORY_USE: true, MEMORY_SAVE: true, SAVE_DIGEST: true, MAGIC_WORD_USE: false,
                              RAG_QUERY_GENE: true, META_SEARCH: true, PRIVATE_MODE: false },
        personality: { LANGUAGE: "日本語", SPEAKING_STYLE: "" },
        feedback_active: true
      }
    },
    {
      t: 1500, type: "api", method: "POST", path: "/run_async", status: 200,
      request: {
        service_info: { SERVICE_ID: "DEMO", SERVICE_DATA: {} },
        user_info: { USER_ID: "DemoUser", USER_DATA: {} },
        session_id: null, user_input: "AIエージェントの記事タイトル案を1つください",
        agent_file: "agent_11Sample.json", personas: ["E0001", "E0002"],
        org: { company: "寄稿先エディター陣" }
      },
      response: { job_id: "0f1e2d3c4b5a69788796a5b4c3d2e1f0", session_id: "APIDEMO20261115_090000_0",
                  session_name: "", state: "running", started_at: "2026-11-15 09:00:01" }
    },
    {
      t: 3500, type: "api", method: "GET", path: "/jobs/0f1e2d3c4b5a69788796a5b4c3d2e1f0", status: 200,
      request: null,
      response: { job_id: "0f1e2d3c4b5a69788796a5b4c3d2e1f0", session_id: "APIDEMO20261115_090000_0",
                  state: "running", elapsed_sec: 2,
                  progress: { status: "LOCKED", message: "Starting RAG", partial_response: "", error: "" } }
    },
    {
      t: 5500, type: "api", method: "GET", path: "/jobs/0f1e2d3c4b5a69788796a5b4c3d2e1f0", status: 200,
      request: null,
      response: { job_id: "0f1e2d3c4b5a69788796a5b4c3d2e1f0", session_id: "APIDEMO20261115_090000_0",
                  state: "running", elapsed_sec: 4,
                  progress: { status: "LOCKED", message: "Running LLM", partial_response: "「判断を任せたAIに、", error: "" } }
    },
    {
      t: 7500, type: "api", method: "GET", path: "/jobs/0f1e2d3c4b5a69788796a5b4c3d2e1f0", status: 200,
      request: null,
      response: {
        job_id: "0f1e2d3c4b5a69788796a5b4c3d2e1f0", session_id: "APIDEMO20261115_090000_0",
        session_name: "(User:DemoUser)AIエージェント記事案", state: "done", elapsed_sec: 6,
        user_input: "AIエージェントの記事タイトル案を1つください",
        progress: { status: "UNLOCKED", message: "", partial_response: "", error: "" },
        result: {
          session_id: "APIDEMO20261115_090000_0", session_name: "(User:DemoUser)AIエージェント記事案",
          seq: "1", sub_seq: "2",
          response: "「値札の裏で決まること — AIエージェントに任せた判断の行方」",
          response_display: "「値札の裏で決まること — AIエージェントに任せた判断の行方」",
          answers: [
            { sub_seq: "1", type: "LLM", name: "三宅慧", persona_id: "E0001", persona_name: "三宅慧",
              response: "「判断を任せたAIに、異議は誰が申し立てるのか」" },
            { sub_seq: "2", type: "LLM", name: "榊原一平", persona_id: "E0002", persona_name: "榊原一平",
              response: "「値札の裏で決まること — AIエージェントに任せた判断の行方」" }
          ],
          references: { knowledge: [], page_index: [], web: {}, user_memory: [] }
        }
      }
    },
    {
      t: 8300, type: "api", method: "GET", path: "/sessions/APIDEMO20261115_090000_0/turns?view=all", status: 200,
      request: null,
      response: {
        session_id: "APIDEMO20261115_090000_0", session_name: "(User:DemoUser)AIエージェント記事案",
        agent: "agent_11Sample.json", active: "Y", status: "UNLOCKED", view: "all", turn_count: 1,
        turns: [{
          seq: "1", memory_flg: "Y", user_id: "DemoUser",
          entries: [
            { sub_seq: "1", detail_sub_seq: "1", type: "LLM", name: "三宅慧", persona_name: "三宅慧",
              agent_file: "agent_11Sample.json", answer_agent_file: "agent_11Sample.json", engine: "GPT-6.1-Sol",
              user_input: "AIエージェントの記事タイトル案を1つください", contents: [], images: [],
              response: "「判断を任せたAIに、異議は誰が申し立てるのか」",
              response_display: "「判断を任せたAIに、異議は誰が申し立てるのか」",
              response_timestamp: "2026-11-15 09:00:06", memory_flg: "N",
              feedback: {}, feedback_config: { active: true, items: ["memo", "comment"], default_category: "未設定" },
              references: { knowledge: [], page_index: [], web: {}, user_memory: [] } },
            { sub_seq: "2", detail_sub_seq: "2", type: "LLM", name: "榊原一平", persona_name: "榊原一平",
              agent_file: "agent_11Sample.json", answer_agent_file: "agent_11Sample.json", engine: "GPT-6.1-Sol",
              user_input: "AIエージェントの記事タイトル案を1つください", contents: [], images: [],
              response: "「値札の裏で決まること — AIエージェントに任せた判断の行方」",
              response_display: "「値札の裏で決まること — AIエージェントに任せた判断の行方」",
              response_timestamp: "2026-11-15 09:00:07", memory_flg: "N",
              feedback: {}, feedback_config: { active: true, items: ["memo", "comment"], default_category: "未設定" },
              references: { knowledge: [], page_index: [], web: {}, user_memory: [] } }
          ]
        }]
      }
    },
    {
      t: 9000, type: "api", method: "GET", path: "/sessions?user_id=DemoUser&service_id=DEMO&active=Y", status: 200,
      request: null,
      response: { sessions: [
        { id: "APIDEMO20261115_090000_0", name: "(User:DemoUser)AIエージェント記事案",
          agent: "agent_11Sample.json", last_update_date: "2026-11-15 09:00:07", active: "Y", status: "UNLOCKED" }
      ] }
    },
    {
      t: 11000, type: "api", method: "GET", path: "/sessions/APIDEMO20261115_090000_0/turns/1/detail?sub_seq=2", status: 200,
      request: null,
      response: { session_id: "APIDEMO20261115_090000_0", seq: "1", sub_seq: "2",
                  detail: "[Execution info]\nFunction: generate_response_T_gpt\nPrompt template: Normal Template\n\n[Tokens]\nprompt: 2,841 / response: 64\n\n(sample text)" }
    },
    {
      t: 13000, type: "api", method: "POST", path: "/sessions/APIDEMO20261115_090000_0/turns/1/memory", status: 200,
      request: { enabled: false },
      response: { status: "ok", session_id: "APIDEMO20261115_090000_0", seq: "1", memory_flg: "N" }
    }
  ]
});
