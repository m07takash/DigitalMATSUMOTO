# LINE 受け口のサンプル（`line_receiver.py`）

スケジュールジョブの「Send to the service's front end via API」が送る JSON を受け取り、LINE の Messaging API で各利用者へ push するサンプルです。Teams / Slack / Azure Bot Service など、ほかのフロントエンドを作るときのひな形にもなります（受け取る JSON の形は README の「サービスのフロントエンドへの配信」）。

| エンドポイント | 役割 | 必要なもの |
|---|---|---|
| `POST /digim/push` | DigiM のジョブから受け取り、LINE へ push する | DigiM から届けば良いので **localhost で動く** |
| `POST /line/webhook` | （任意）LINE で話しかけると DigiM の `/run` に送り、回答を push で返す。LINE のセッションもこれで作られる | LINE から届く **公開 HTTPS の URL** |
| `GET /health` | 設定の有無（値は出さない） | |

## 自分の LINE で試す

### 1. LINE 側の準備

1. [LINE Developers](https://developers.line.biz/) でプロバイダーと **Messaging API チャネル**を作る（LINE 公式アカウントの作成から案内されます）。
2. チャネルの設定画面で次の3つを控える。
   - **チャネルアクセストークン（長期）** — Messaging API 設定
   - **チャネルシークレット** — チャネル基本設定（webhook を使うときだけ）
   - **あなたのユーザーID**（`U` で始まる33文字） — チャネル基本設定。これが DigiM のセッションの `user_id` になります
3. Messaging API 設定の QR コードから、自分の LINE でその公式アカウントを**友だち追加**する（友だちでない相手には push できません）。

> 無料プランは月の送信数に上限があり、push はその数に入ります。

### 2. 設定（`system.env`）

受け口は既定で DigiM と同じ `system.env` を読みます（`DIGIM_ENV_FILE` で変更可）。

```env
LINE_CHANNEL_ACCESS_TOKEN=<チャネルアクセストークン>
LINE_CHANNEL_SECRET=<チャネルシークレット>
PUSH_TOKEN_LINE=<任意の文字列。DigiM → 受け口の合言葉>
```

`user/common/mst/services.json` の `LINE` を有効にして、送り先をこの受け口にします。

```json
"LINE": {
    "NAME": "LINE (sample receiver)",
    "ACTIVE": true,
    "PUSH": {"URL": "http://localhost:8898/digim/push", "TOKEN_ENV": "PUSH_TOKEN_LINE",
             "BATCH_SIZE": 20, "INTERVAL_SEC": 1, "TIMEOUT_SEC": 15}
}
```

### 3. 受け口を起動する

```bash
cd demo/push_receiver
LINE_PUSH_DRY_RUN=Y uvicorn line_receiver:app --host 0.0.0.0 --port 8898   # まずは LINE に送らずログだけ
uvicorn line_receiver:app --host 0.0.0.0 --port 8898                       # 本当に送る
curl -s http://localhost:8898/health
```

### 4. LINE のセッションを作る

ジョブが送るのは「`service_id` が `LINE` のセッション」です。webhook を使わないなら、API で1ターン実行して作ります（LLM を1回呼びます）。

```bash
curl -s -X POST http://localhost:8899/run -H "Content-Type: application/json" -d '{
  "service_info": {"SERVICE_ID": "LINE"},
  "user_info": {"USER_ID": "U0123...（あなたのユーザーID）"},
  "session_id": "LINEU0123...",
  "user_input": "こんにちは"}'
```

### 5. ジョブを作って送る

WebUI の **Scheduler** → **Add New Job**:

- Kind: `agent_run`、Deliver to: `active_all`、**Filter: user_id** にあなたのユーザーID
  （`selected` の一覧は自分の WebUI のセッションだけなので、LINE のセッションはフィルタで指定します）
- Message: `fixed`（LLM を呼ばない）で「テストです」など
- **Send to the service's front end via API** を ON、Response only
- Save → **Run Now**

自分の LINE に届けば成功です。ジョブ一覧の `API delivery: sent 1` と、受け口のログで確認できます。

### 6.（任意）LINE から話しかける

`/line/webhook` を公開 HTTPS で出し（例: NGINX で `location /line/ { proxy_pass http://127.0.0.1:8898; }`）、LINE Developers の **Webhook URL** に `https://<ホスト>/line/webhook` を設定して「Webhook の利用」を ON にします。LINE Official Account Manager の応答メッセージ（自動応答）は OFF にしてください。

- 話しかけると、DigiM の `/run` を `service_id=LINE`・`user_id=<あなたのID>`・`session_id=LINE<あなたのID>` で呼び、回答を push で返します（LINE が webhook の応答を待つ時間より実行が長いため、返信ではなく push にしています）。
- エージェントは `LINE_AGENT_FILE`（空なら API の既定 `API_AGENT_FILE`）。

## 注意

- このサンプルには再送がありません。DigiM 側も送り直さないので、失敗はジョブ一覧の `API delivery` で確認します。
- 同じジョブ・セッション・seq の push には同じ `X-Line-Retry-Key` を付けるので、24時間以内に同じ内容を送り直しても LINE 側で1回になります。
