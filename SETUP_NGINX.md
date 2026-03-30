# NGINX セットアップ手順

DigitalMATSUMOTO の Docker コンテナを外部公開するための NGINX リバースプロキシ設定手順です。
HTTPS 化（Let's Encrypt）までを含みます。

---

## 前提条件

- Ubuntu / Debian 系のホストマシン
- Docker コンテナが起動済み（ポート 8501 / 8899 をバインド）
- 独自ドメインまたは Azure のDNS名が設定済み

## 1. NGINX のインストール

```bash
sudo apt update
sudo apt install -y nginx
```

## 2. 設定ファイルの作成

`/etc/nginx/sites-available/digitalmatsumoto` を作成します。

```nginx
# HTTP → HTTPS リダイレクト
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$host$request_uri;
}

# HTTPS
server {
    listen 443 ssl;
    server_name your-domain.com;

    # SSL証明書（Step 4 で取得後に有効化）
    ssl_certificate     /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # SSL設定
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # タイムアウト設定（LLM実行は時間がかかるため長めに設定）
    proxy_connect_timeout 300s;
    proxy_send_timeout    300s;
    proxy_read_timeout    300s;

    # --- Streamlit WebUI ---
    location / {
        proxy_pass http://127.0.0.1:8501/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket対応（Streamlit必須）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # --- FastAPI ---
    location /api/ {
        proxy_pass http://127.0.0.1:8899/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # --- JupyterLab（必要な場合のみ）---
    # location /jupyter/ {
    #     proxy_pass http://127.0.0.1:8891/;
    #     proxy_set_header Host $host;
    #     proxy_http_version 1.1;
    #     proxy_set_header Upgrade $http_upgrade;
    #     proxy_set_header Connection "upgrade";
    # }
}
```

> `your-domain.com` は実際のドメイン名に置き換えてください。
> Azure VM の場合は `xxx.japaneast.cloudapp.azure.com` のようなDNS名になります。

## 3. 設定の有効化と確認

```bash
# シンボリックリンクで有効化
sudo ln -sf /etc/nginx/sites-available/digitalmatsumoto /etc/nginx/sites-enabled/

# デフォルト設定を無効化（競合防止）
sudo rm -f /etc/nginx/sites-enabled/default

# 設定の構文チェック
sudo nginx -t

# NGINX を再起動
sudo systemctl restart nginx
```

## 4. SSL証明書の取得（Let's Encrypt）

### 4-1. Certbot のインストール

```bash
sudo apt install -y certbot python3-certbot-nginx
```

### 4-2. 証明書の取得

```bash
sudo certbot --nginx -d your-domain.com
```

対話形式でメールアドレスの入力と利用規約への同意が求められます。完了すると証明書が自動的に `/etc/letsencrypt/live/your-domain.com/` に配置されます。

> 初回は SSL 設定行をコメントアウトした状態で HTTP のみで certbot を実行し、証明書取得後にコメントを外して NGINX を再起動する方法もあります。

### 4-3. 自動更新の確認

Let's Encrypt の証明書は90日で期限切れになりますが、certbot が自動更新タイマーを設定します。

```bash
# タイマーの確認
sudo systemctl status certbot.timer

# 手動で更新テスト
sudo certbot renew --dry-run
```

## 5. ファイアウォールの設定

### Ubuntu（ufw）の場合

```bash
sudo ufw allow 'Nginx Full'  # 80 + 443
sudo ufw reload
```

### Azure VM の場合

Azure Portal →「ネットワーク セキュリティ グループ」で以下のインバウンドルールを追加：

| 優先度 | ポート | プロトコル | アクション |
|--------|-------|-----------|-----------|
| 100 | 80 | TCP | 許可 |
| 110 | 443 | TCP | 許可 |

> Docker コンテナのポート（8501, 8891, 8899）は外部に直接開放する必要はありません。NGINX 経由でアクセスします。

## 6. 動作確認

```bash
# HTTPS でWebUIにアクセス
curl -s -o /dev/null -w "%{http_code}" https://your-domain.com/

# API ヘルスチェック
curl -s https://your-domain.com/api/health

# API メッセージ送信テスト
curl -s -X POST https://your-domain.com/api/run \
  -H "Content-Type: application/json" \
  -d '{
    "service_info": {"SERVICE_ID": "API_TEST", "SERVICE_DATA": {}},
    "user_info": {"USER_ID": "TestUser", "USER_DATA": {}},
    "session_id": "NGINX_TEST_001",
    "user_input": "こんにちは",
    "agent_file": "agent_X0Sample.json"
  }' | python3 -m json.tool
```

## アクセス先の対応表

| 外部URL | プロキシ先 | 用途 |
|---------|-----------|------|
| `https://your-domain.com/` | `127.0.0.1:8501` | Streamlit WebUI |
| `https://your-domain.com/api/` | `127.0.0.1:8899` | FastAPI |
| `https://your-domain.com/jupyter/` | `127.0.0.1:8891` | JupyterLab（オプション） |

## トラブルシューティング

### WebUIで画面が真っ白になる

Streamlit は WebSocket を使用するため、NGINX で `Upgrade` ヘッダーの設定が必要です。`location /` ブロックに以下が含まれているか確認してください：

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

### API がタイムアウトする

LLM の実行には 10〜30 秒かかります。NGINX のデフォルトタイムアウト（60秒）では足りない場合があります。

```nginx
proxy_read_timeout 300s;
```

### 502 Bad Gateway

Docker コンテナが起動していないか、ポートが正しくバインドされていません。

```bash
# コンテナの状態確認
docker ps

# ポートのリッスン確認
ss -tlnp | grep -E '8501|8899'
```
