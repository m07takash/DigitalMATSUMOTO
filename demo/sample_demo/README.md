# Digital MATSUMOTO — Sample Demo (Mockup)

Digital MATSUMOTO の FastAPI バックエンドをそのまま叩けるデモ用画面のスケルトンです。HTML + CSS + JavaScript のみで構成されており、CDNや外部依存はありません。フォルダをそのままコピーすれば、ローカルPCからでも動作します。

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

ヘッダー上部の「Backend」欄で FastAPI の URL を書き換えられます。設定は `localStorage` に保存されます。デフォルト値は `config.js` の `BACKEND_URL` を編集してください。

```js
// config.js
window.DIGIM_CONFIG = {
  BACKEND_URL: "http://localhost:8899",
  ...
};
```

NGINX リバースプロキシ経由の場合は `https://your-domain.com/api` のように指定します。

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
├── config.js             接続先・挙動の設定
├── css/style.css         見た目（トップに CSS 変数集約）
├── js/
│   ├── api.js            FastAPI 呼び出しラッパ + 録画フック
│   ├── recorder.js       録画/再生エンジン
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
