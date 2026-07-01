# INSTRUCTIONS for AI editors (Copilot / Claude / Cursor / etc.)

このフォルダ (`sample_demo/`) は Digital MATSUMOTO デモ用モックアップの **スケルトン** です。デザインやレイアウトの変更を任せるためのガイドです。読んでから作業を始めてください。

## 全体像

- **1ページのSPA** です (`index.html`)。フレームワーク・CDN・ビルドツールは使いません。バニラ HTML/CSS/JS のみ。
- **API 呼び出しは `js/api.js` を経由します**。ここを直に `fetch()` に差し替えないでください（録画/再生が壊れます）。
- **録画/再生エンジンは `js/recorder.js`** です。イベント形式は下の「不可侵の契約」参照。
- **タブ切り替えなど UI 配線はすべて `js/app.js`** に集約。

## 変えていいもの / 変えてほしくないもの

### ✅ 自由に変えて OK

- **`css/style.css`** — 全ての色・タイポグラフィ・レイアウト。`:root` の CSS 変数だけ書き換えれば全体トーンが揃うようにしてあります。既存のクラス名を維持しつつ styling を差し替えるのが最も安全。
- **`index.html`** — マークアップ構造、追加要素、コピー文言、ロゴ、フッターなど。**ただし ID/クラス名を使っている DOM は `js/app.js` から参照されている** ため、変更したら `js/app.js` 側も追随してください（IDの grep で対応表を作れます）。
- **ペイン内のセクション分割・タブ順・アイコン追加**
- **サンプル録画 (`recordings/sample_chat.js`)** — シナリオを差し替えて OK

### ⚠ 変える前に一呼吸

- **`js/app.js`** — UI ロジックの本体。修正して構いませんが、**Recorder のフックポイントを外さないこと**（`Api.*` 経由の呼び出し・`Recorder.onChange`）。
- **`config.js`** — 公開キーは維持し、追加は末尾に。既存キーの型を変えると `js/app.js` / `js/api.js` を壊します。
- **タブ (`data-tab`) と パネル (`data-panel`) の対応** — 一致していないと切替が動きません。

### ❌ 触らないでほしいもの（不可侵の契約）

- **`js/api.js` の `Api.call(method, path, body)` シグネチャ**、および `Api.health / listSessions / getSession / listAgents / listEngines / listWebEngines / feedbackConfig / submitFeedback / run` の名前と戻り値。DigiM_API.py と直接対応しています。
- **`js/recorder.js` の `event` オブジェクト形状**（下記）。過去の録画ファイルとの互換のため。

  ```js
  {
    t: <ms since recording start>,
    type: "api",
    method: "GET" | "POST",
    path: "/run" | ...,
    request: <JSON | null>,
    response: <JSON | text | null>,
    status: <HTTP status int>,
    error: <string | null>
  }
  ```
- **`Recorder.register({ id, meta, events })` の登録関数呼び出し形式** — 全ての `recordings/*.js` がこの形式で self-register しています。

## エンドポイント → 画面 対応表

デザイン変更で「どのエンドポイントを何処に置くか」を決めるための対応表です。並び替え・統合・新規追加は自由ですが、いずれかの画面から呼び出せる状態を維持してください。

| エンドポイント                       | 画面 (data-panel) | 主要 DOM ID |
|--------------------------------------|-------------------|-------------|
| `POST /run`                          | `chat`            | `#chat-input`, `#btn-send`, `#chat-log`, `#chat-agent`, `#chat-engine`, `#flag-*` |
| `GET /sessions`                      | `sessions`        | `#sess-user-id`, `#sess-service-id`, `#btn-sess-load`, `#sess-table` |
| `GET /sessions/{id}`                 | `sessions`        | `#sess-detail`（行クリックで発火） |
| `GET /agents`                        | `agents`          | `#agents-table`, `#btn-agents-load` |
| `GET /agents/{file}/engines`         | `agents`          | `#engines-detail`（行クリックで発火） |
| `GET /web_search_engines`            | `websearch`       | `#btn-web-load`, `#web-detail` |
| `GET /agents/{file}/feedback`        | `feedback`        | `#fb-agent`, `#btn-fb-config`, `#fb-config` |
| `POST /feedback`                     | `feedback`        | `#fb-session`, `#fb-seq`, `#fb-subseq`, `#fb-body`, `#btn-fb-send`, `#fb-result` |
| `GET /health`                        | header / `health` | `#btn-health`, `#health-dot`, `#btn-raw-health`, `#raw-response` |
| （任意）                             | `health`          | `#raw-method`, `#raw-path`, `#raw-body`, `#btn-raw-send` |

新しいエンドポイントを画面に追加するときは:

1. `js/api.js` に typed helper を追加
2. `index.html` に UI 要素を追加
3. `js/app.js` にイベントハンドラを追加
4. 必要に応じて `handlePlaybackEvent` に該当 path の分岐を追加（再生時に反映されるように）

## 具体的な変更依頼のテンプレ

以下のように依頼してもらえるとスムーズです:

- 「配色を **ミッドナイトブルーとエレクトリックシアン** に。`:root` の CSS 変数だけを更新して」
- 「Chat タブのメッセージバブルを Slack 風に。アバター丸型を左に、名前を上に。`index.html` の `.msg` テンプレを拡張、CSS は `.msg.*` に集約」
- 「サイドバーを右に寄せる。既存の DOM ID は変えず、CSS だけで反転」
- 「モバイル幅 (< 768px) で `.tabs` をハンバーガーにする」
- 「Sessions パネルにセッション削除ボタンを追加。エンドポイントは `DELETE /sessions/{id}` を仮定」

## 触ってほしくないユースケース

- **設計変更**（Recorder のイベント形式変更、`Api` 命名の再設計、モジュールバンドラ導入など）はスケルトン全体の互換を壊すので、依頼者に一度確認してから。
- **CDN や npm パッケージの追加**は原則不要です（バニラで完結する設計）。どうしても入れる場合は README にも書き足してください。
- **セキュリティ関連**（トークン、認証ヘッダーなど）を追加する場合、平文の秘密情報を録画ファイルに残さないでください（`Recorder.exportAsScript` を通す前にサニタイズ）。

## 動作確認手順

1. `python3 -m http.server` でこのフォルダを配信
2. ブラウザで開き、ヘッダーの Check ボタンを押す（Backend URL を打ち直してから）
3. 各タブが表示される・Play で `sample_chat` が最後まで進むことを確認
4. リグレッションがあれば `js/app.js` の該当セクションを見る

以上です。**「触ってほしくないもの」に該当する変更が必要な場合は、必ず変更点と影響範囲を先に整理してから提案してください。**
