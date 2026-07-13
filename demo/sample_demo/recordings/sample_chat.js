// Sample Agent Demo recording. Load via <script src>.
// ---------------------------------------------------------------------------
// A hand-authored example recording so the demo has something to play back
// even before an operator captures their own. Replace freely.
// ---------------------------------------------------------------------------

window.Recorder && window.Recorder.register({
  id: "sample_chat",
  meta: {
    title: "Sample chat (3 turns + session list)",
    createdAt: "2026-06-30T09:00:00Z",
    backendUrl: "http://localhost:8899"
  },
  events: [
    {
      t: 200, type: "api", method: "GET", path: "/health", status: 200,
      request: null,
      response: { status: "ok" }
    },
    {
      t: 800, type: "api", method: "GET", path: "/agents", status: 200,
      request: null,
      response: {
        agents: [
          { file: "agent_10Sample.json", agent_name: "Sample Agent",
            description: "General-purpose sample" }
        ]
      }
    },
    {
      t: 2000, type: "api", method: "POST", path: "/run", status: 200,
      request: {
        service_info: { SERVICE_ID: "DEMO", SERVICE_DATA: {} },
        user_info:    { USER_ID: "DemoUser", USER_DATA: {} },
        session_id: null,
        user_input: "こんにちは、自己紹介してください。",
        agent_file: "agent_10Sample.json"
      },
      response: {
        session_id: "APIDEMO2026063000001",
        session_name: "(User:DemoUser)サンプルエージェント自己紹介",
        response: "こんにちは。私はサンプルエージェントです。デモ用に用意されたシンプルな AI アシスタントで、対話 API の動作確認にお使いいただけます。"
      }
    },
    {
      t: 5500, type: "api", method: "POST", path: "/run", status: 200,
      request: {
        service_info: { SERVICE_ID: "DEMO", SERVICE_DATA: {} },
        user_info:    { USER_ID: "DemoUser", USER_DATA: {} },
        session_id: "APIDEMO2026063000001",
        user_input: "あなたの特徴は？",
        agent_file: "agent_10Sample.json"
      },
      response: {
        session_id: "APIDEMO2026063000001",
        session_name: "(User:DemoUser)サンプルエージェント自己紹介",
        response: "セッション管理・ユーザーメモリ・RAG・Web 検索といった基本機能を備えたエージェントです。詳細は接続先のバックエンド仕様をご参照ください。",
        references: {
          knowledge: [
            { title: "エージェント設計ガイド",
              rag_name: "digim_manual", chunk_id: "manual_012",
              category: "Overview",
              snippet: "本システムは対話エージェント基盤として、階層的ユーザーメモリと RAG を統合...",
              similarity_response: 0.92, similarity_prompt: 0.88 },
            { title: "RAG 実装リファレンス",
              rag_name: "digim_manual", chunk_id: "manual_034",
              category: "RAG",
              snippet: "ChromaDB を用いたベクトル検索とメタ検索を組み合わせて...",
              similarity_response: 0.71, similarity_prompt: 0.64 },
            { title: "サンプル FAQ",
              rag_name: "faq", chunk_id: "faq_007",
              category: "FAQ",
              snippet: "よくある質問: セッション管理はどう動きますか?",
              similarity_response: 0.41, similarity_prompt: 0.38 }
          ],
          page_index: [
            { title: "3. 基本機能一覧",
              rag_name: "DigiMPGSystemGuide", page_id: "3-1",
              category: "Manual",
              summary: "セッション・ユーザーメモリ・RAG・Web検索の4本柱",
              similarity_response: 0.85 }
          ],
          web: {},
          user_memory: []
        }
      }
    },
    {
      t: 9000, type: "api", method: "POST", path: "/run", status: 200,
      request: {
        service_info: { SERVICE_ID: "DEMO", SERVICE_DATA: {} },
        user_info:    { USER_ID: "DemoUser", USER_DATA: {} },
        session_id: "APIDEMO2026063000001",
        user_input: "最近のAIエージェントの動向は？",
        agent_file: "agent_10Sample.json"
      },
      response: {
        session_id: "APIDEMO2026063000001",
        session_name: "(User:DemoUser)サンプルエージェント自己紹介",
        response: "2026年時点では、マルチエージェント協調・ツール実行・記憶階層化が主要トレンドです。以下のソースから要点をまとめました。",
        references: {
          knowledge: [],
          page_index: [],
          web: {
            engine: "OpenAI", model: "gpt-4.1-mini",
            search_text: "AI agent trends 2026",
            duration_sec: 2.4,
            urls: [
              { title: "MIT Tech Review: Agents in 2026",
                url: "https://www.example.com/mit-tech-review/agents-2026",
                date: "2026-06-15" },
              { title: "arXiv: Hierarchical Memory for LLM Agents",
                url: "https://arxiv.example.com/abs/2606.01234",
                date: "2026-06-02" },
              { title: "Anthropic Research Blog: Tool-use scaling",
                url: "https://anthropic.example.com/research/tool-use",
                date: "2026-05-28" }
            ]
          },
          user_memory: [
            { log: "Chat history at 2026-05-01: 3_1_user 'What is an AI agent?'<br>",
              similarity_response: 0.62 }
          ]
        }
      }
    },
    {
      t: 11000, type: "api", method: "GET", path: "/sessions", status: 200,
      request: null,
      response: {
        sessions: [
          { id: "APIDEMO2026063000001",
            name: "(User:DemoUser)サンプルエージェント自己紹介",
            agent: "agent_10Sample.json",
            last_update_date: "2026-06-30 09:00:10" }
        ]
      }
    },
    {
      t: 12000, type: "api", method: "GET", path: "/session_summary_presets", status: 200,
      request: null,
      response: {
        presets: [
          { name: "Basic",
            description: "会話の要点と決定事項を淡々と記録",
            template: "## 目的\n\n## 決定事項\n\n## Next Action\n\n## 参考\n" },
          { name: "Sales Meeting",
            description: "顧客商談の議事録テンプレ",
            template: "## 顧客\n\n## ヒアリング内容\n\n## 提案\n\n## 次回アクション\n" },
          { name: "Debug Log",
            description: "エンジニアリング調査ログ",
            template: "## 症状\n\n## 検証\n\n## 原因\n\n## 対応策\n" }
        ]
      }
    },
    {
      t: 13000, type: "api", method: "GET",
      path: "/sessions/APIDEMO2026063000001/summary", status: 200,
      request: null,
      response: {
        session_id: "APIDEMO2026063000001",
        enabled: true,
        template: "## 目的\n\n## 決定事項\n\n## Next Action\n\n## 参考\n",
        content: "## 目的\nサンプルエージェントの動作確認\n\n" +
                 "## 決定事項\n- セッション管理・ユーザーメモリ・RAG・Web検索を活用する方針\n\n" +
                 "## Next Action\n- 顧客Aへのデモで本UIを使う\n\n" +
                 "## 参考\n- MIT Tech Review: Agents in 2026\n",
        updated_at: "2026-06-30 09:00:12"
      }
    }
  ]
});
