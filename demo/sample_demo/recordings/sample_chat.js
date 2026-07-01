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
        response: "セッション管理・ユーザーメモリ・RAG・Web 検索といった基本機能を備えたエージェントです。詳細は接続先のバックエンド仕様をご参照ください。"
      }
    },
    {
      t: 9000, type: "api", method: "POST", path: "/run", status: 200,
      request: {
        service_info: { SERVICE_ID: "DEMO", SERVICE_DATA: {} },
        user_info:    { USER_ID: "DemoUser", USER_DATA: {} },
        session_id: "APIDEMO2026063000001",
        user_input: "ありがとう。",
        agent_file: "agent_10Sample.json"
      },
      response: {
        session_id: "APIDEMO2026063000001",
        session_name: "(User:DemoUser)サンプルエージェント自己紹介",
        response: "こちらこそ、ありがとうございました。またいつでもお声がけください。"
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
    }
  ]
});
