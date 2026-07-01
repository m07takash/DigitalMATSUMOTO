# Digital MATSUMOTO — Sample Demo (Mockup)

Digital MATSUMOTO の FastAPI バックエンドをそのまま叩けるデモ用画面のスケルトンです。HTML + CSS + JavaScript のみで構成されており、CDNや外部依存はありません。フォルダをそのままコピーすれば、ローカルPCからでも動作します。

> 📖 **実際にデモを打つ人向けの詳細マニュアルは [`MANUAL.md`](MANUAL.md) を参照してください**（画面ごとの操作手順・デモシナリオ例・オフライン運用・トラブル対処など）。このファイルは要点まとめです。

## 何ができるか

- FastAPI (`DigiM_API.py`) の全エンドポイントに UI から到達できます。
- 各種操作を **録画** し、後から **再生** できます（バックエンドが無くてもデモ可能）。
- 生の API を直接叩く「Raw fetch」パネルも同梱。

対応済みエンドポイント:

| Method | Path                                    | 画面 |
|--------|-----------------------------------------|------|
| POST   | `/run`                                  | Chat |
| POST   | `/run_function` (legacy)                | Raw fetch から呼び出し可 |
| GET    | `/sessions`                             | Sessions |
| GET    | `/sessions/{id}`                        | Sessions（行クリックで詳細表示） |
| GET    | `/agents`                               | Agents & Engines |
| GET    | `/agents/{file}/engines`                | Agents & Engines（行クリック） |
| GET    | `/web_search_engines`                   | Web Search Engines |
| GET    | `/agents/{file}/feedback`               | Feedback |
| POST   | `/feedback`                             | Feedback |
| GET    | `/health`                               | Header の Check ボタン / Health タブ |

さらに、録画の内容を画面上で編集するための **Recording Editor** タブがあります（詳細は [`MANUAL.md`](MANUAL.md) の § 6-7 と § 7）。

## 使い方

### 1. バックエンドの起動

FastAPI を起動しておきます（詳細はリポジトリの README を参照）。

```bash
python DigiM_API.py
```

デフォルトでは `http://localhost:8899` で待ち受けます。

### 2. デモ画面を開く

**Aパターン: そのままダブルクリック（`file://`）**
```
demo/sample_demo/index.html
```
録画・再生・単純な設定はすべて動きますが、ブラウザによっては `fetch()` の CORS/セキュリティ制約で実バックエンドに繋がらないことがあります。

**Bパターン: 簡易HTTPサーバ経由（推奨）**
```bash
cd demo/sample_demo
python3 -m http.server 8000
# ブラウザで http://localhost:8000/
```

### 3. 接続先の設定

ヘッダー上部の「Backend」欄で FastAPI の URL を書き換えられます。設定は `localStorage` に保存されます。デフォルト値は `config.json` を編集してください（`config.js` は読み込み用のローダーで、通常は触りません）。

```json
// config.json
{
  "BACKEND_URL": "http://localhost:8899",
  "DEFAULT_USER_ID": "DemoUser",
  "DEFAULT_SERVICE_ID": "DEMO",
  "PLAYBACK_SPEED": 1.0,
  "AUTO_FALLBACK_TO_RECORDING": true,
  "HEALTH_POLL_MS": 0
}
```

NGINX リバースプロキシ経由の場合は `https://your-domain.com/api` のように指定します。

> `config.json` は fetch で同期読み込みされるため、`file://` で開いた場合は同期取得ができず `config.js` に埋め込まれたデフォルト値にフォールバックします（コンソール警告あり）。編集した設定を反映したい場合は必ず HTTP サーバ経由で開いてください。

## 録画 & 再生（Record & Play）

1. ヘッダー右側の **● Record** をクリック → タイトル入力 → 通常通り画面を操作
2. **■ Stop** で録画終了。バッファに蓄積された API 呼び出し（リクエスト/レスポンス/所要時間）がすべて保存されます
3. **⬇ Save** で `rec_XXXX.js` としてダウンロード
4. `recordings/` フォルダに配置し、`index.html` の末尾に `<script src="recordings/rec_XXXX.js"></script>` を1行追加
5. リロード後、ヘッダーの録画セレクタから選んで **▶ Play** で再生

一時的に確認したいだけなら **⬆ Load** で `.js` / `.json` を直接読み込むこともできます（リロードで消えます）。

再生時は画面が該当タブに自動遷移し、録画された順番・タイミングで応答が反映されます。速度は `config.js` の `PLAYBACK_SPEED` で調整できます。

### スタンドアロン運用（バックエンド無しでデモ）

`config.js` の `AUTO_FALLBACK_TO_RECORDING` を `true` （デフォルト）にしておき、事前に録画を選択状態にしておくと、実際のネットワーク呼び出しが失敗したときに録画された応答へ自動フォールバックします。オフラインのプレゼン環境でも操作可能な状態で見せられます。

## ファイル構成

```
sample_demo/
├── index.html            エントリポイント (SPA)
├── config.json           接続先・挙動の設定（編集対象はこちら）
├── config.js             config.json を読み込むローダー（触らない）
├── css/style.css         見た目（トップに CSS 変数集約）
├── js/
│   ├── api.js            FastAPI 呼び出しラッパ + 録画フック
│   ├── recorder.js       録画/再生エンジン
│   ├── editor.js         Recording Editor タブ（画面上で録画編集）
│   └── app.js            UI 配線（各タブ / ボタン / セレクタ）
├── recordings/
│   ├── manifest.js       録画の索引（コメントのみ）
│   └── sample_chat.js    サンプル録画（3ターンの会話）
├── README.md             このファイル
└── INSTRUCTIONS.md       AI ツール（Copilot/Claude）向け改造ガイド
```

## デザインを変えたいとき

`INSTRUCTIONS.md` を Copilot/Claude 等に読ませて、デザイン変更を依頼してください。編集ポイントと守るべき境界（API 名、Recorder のイベント形式など）が書いてあります。

## トラブルシューティング

| 症状 | 対応 |
|------|------|
| Health チェックが赤 (●) | バックエンドが未起動、または URL が違う。`Backend` 欄を確認 |
| CORS エラー | FastAPI 側で CORS 許可を追加するか、同一オリジンから配信 (`python -m http.server`) |
| 録画を追加したのに Play セレクタに出ない | `index.html` に `<script src>` を追加したかリロード確認 |
| `file://` で fetch できない | `python -m http.server` を使うか、録画からのフォールバック運用に切替 |
