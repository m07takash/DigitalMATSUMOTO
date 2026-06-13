# 閉域ネットワーク（Azure）への Docker イメージ移行手順

**日本語** | [English](SETUP_OFFLINE_DOCKER.en.md)

pip / Git / apt が使えない閉域ネットワーク下の Azure 環境へ、Digital MATSUMOTO を構築するための手順をまとめます。

## 方針

依存解決（`pip install` / `apt-get` / `git clone`）はすべて **Dockerfile のビルド時に完結** します。
したがって、

> **「ネット接続環境でビルド済みイメージを作り、それを丸ごと閉域へ持ち込む」**

ことで、閉域側では `pip` や `git` を一切使わずに構築できます。
wheel（whl）や OS パッケージを個別に搬入する必要はありません。**搬入物はイメージ本体・`system.env`・必要な `user/` データの3点のみ** です。

> ⚠️ **重要：閉域側では `docker build` をやり直さないでください。** 再ビルドすると再びネットワークが必要になります。閉域では「ロードして起動するだけ」に徹します。

### 前提条件

- 移行**元**（ネット接続環境）と移行**先**（閉域）で、CPU アーキテクチャを揃えること（例：両方 `linux/amd64`）。
  - 異なる場合は元環境で `docker build --platform linux/amd64 ...` のように明示してビルドする。
- 移行先の閉域 VM に Docker がインストール済みであること。
- Docker イメージは作成済み（本手順の出発点）。本書では `digimatsumoto:offline` というタグ名を例に進めます。

---

## ステップ 1. イメージを tar 化し、サイズ上限で分割する

移行元（ネット接続環境）で実施します。転送経路（USB / 承認付きファイル転送 / Blob 等）のサイズ制限に合わせて分割します。

```bash
# 1-1. イメージを gzip 圧縮した tar として書き出す
docker save digimatsumoto:offline | gzip > digimatsumoto_offline.tar.gz

# 1-2. 1ファイル 2GB 上限で分割（-b は 2000M / 1G / 500M 等、転送制限に合わせる）
#      連番サフィックスのファイル（digimatsumoto_offline.tar.gz.part-aa, ...-ab, ...）が生成される
split -b 2000M -d -a 3 digimatsumoto_offline.tar.gz digimatsumoto_offline.tar.gz.part-

# 1-3. 転送後の破損検知用にチェックサムを生成（分割ファイルと結合後の両方を記録）
sha256sum digimatsumoto_offline.tar.gz            > digimatsumoto_offline.sha256
sha256sum digimatsumoto_offline.tar.gz.part-*    > digimatsumoto_offline.parts.sha256

ls -lh digimatsumoto_offline.tar.gz.part-*
```

> 💡 `split -d -a 3` は数字3桁の連番（`...part-000`, `...part-001`）を付けます。`-d` を外すと `...part-aa`, `...part-ab` のように英字サフィックスになります。結合時のワイルドカード（手順3）が連番順に並ぶよう、桁数 `-a` は十分に確保してください。

転送対象は次のファイル群です。
- `digimatsumoto_offline.tar.gz.part-*`（分割イメージ）
- `digimatsumoto_offline.sha256` / `digimatsumoto_offline.parts.sha256`（検証用）

---

## ステップ 2. 閉域環境へ転送する

組織の承認された経路で、上記ファイル群を閉域 VM の作業ディレクトリ（例：`/work/transfer/`）へ転送します。

```bash
# 閉域 VM 側で受領後、分割ファイルの破損チェック
cd /work/transfer
sha256sum -c digimatsumoto_offline.parts.sha256
# すべて "OK" と表示されればロスなく転送できている
```

> Azure を経路に使う場合は、閉域 VNet 内に Private Endpoint を張った Storage Account（Blob）を経由する方法が安全です。`azcopy` / `az storage blob` で授受します。

---

## ステップ 3. 分割ファイルを再結合する

閉域 VM 側で、分割ファイルを元の単一 tar.gz に戻します。

```bash
cd /work/transfer

# 3-1. 連番順に結合（シェルのワイルドカード展開はソート順なので連番が正しく並ぶ）
cat digimatsumoto_offline.tar.gz.part-* > digimatsumoto_offline.tar.gz

# 3-2. 結合後ファイルのチェックサムを照合（ステップ1-3で記録した値と一致するか）
sha256sum -c digimatsumoto_offline.sha256
# "OK" が出れば結合成功

# 3-3. 確認できたら分割ファイルは削除してディスクを節約（任意）
rm -f digimatsumoto_offline.tar.gz.part-*
```

---

## ステップ 4. 解凍する

> `docker load` は gzip 圧縮された tar をそのまま読めるため、明示的な解凍は必須ではありません。
> 中間 tar を確認したい場合や、`docker load` に非圧縮 tar を渡したい場合のみ実施します。

```bash
# （任意）gzip を展開して非圧縮 tar を得る
gunzip -k digimatsumoto_offline.tar.gz   # -k で .tar.gz を残したまま digimatsumoto_offline.tar を生成
```

---

## ステップ 5. イメージをロードしてコンテナを作成する

```bash
# 5-1. イメージをロード（圧縮 tar をそのまま渡せる）
docker load -i digimatsumoto_offline.tar.gz
#   非圧縮 tar を使う場合: docker load -i digimatsumoto_offline.tar

# 5-2. ロードされたか確認
docker images | grep digimatsumoto

# 5-3. （任意）ネットを完全に切った状態で依存が揃っているか検証
docker run --rm --network none digimatsumoto:offline \
  python3 -c "import chromadb, psycopg2, streamlit, MeCab; print('依存OK・ネット不要')"
```

コンテナを起動します。ポートは Dockerfile / startup.sh の定義に対応します
（8501: メイン Streamlit、8895: modified Streamlit、8899: FastAPI、8891: 予備）。

> 💡 **初回構築のおすすめ：まず自動起動OFFで立ち上げる。** Dockerfile のデフォルト `CMD` は `startup.sh`（全サービス自動起動）です。新環境では設定ミスで起動が失敗し Streamlit が Rerun ループに陥ることがあるため、初回は `-e DIGIM_AUTOSTART=false` を付けて**待機状態**で起動し、`docker exec` で入って手動確認することを推奨します。問題なければ通常起動に切り替えます。

```bash
# 【推奨】初回は待機状態で起動して手動確認
docker run -d \
  --name digimatsumoto \
  --restart unless-stopped \
  -p 8501:8501 -p 8895:8895 -p 8899:8899 \
  -v /work/digimatsumoto/user:/app/DigitalMATSUMOTO/user \
  -v /work/digimatsumoto/work:/work \
  --env-file /work/digimatsumoto/system.env \
  -e DIGIM_AUTOSTART=false \
  digimatsumoto:offline

docker exec -it digimatsumoto bash
#   コンテナ内で個別に起動して動作確認:
#   streamlit run WebDigiMatsuAgent.py --server.port 8501 --server.address 0.0.0.0
#   問題なければ ./startup.sh で全サービス起動

# 【通常運用】自動起動ON（DIGIM_AUTOSTART を付けない）
docker rm -f digimatsumoto
docker run -d \
  --name digimatsumoto \
  --restart unless-stopped \
  -p 8501:8501 -p 8895:8895 -p 8899:8899 \
  -v /work/digimatsumoto/user:/app/DigitalMATSUMOTO/user \
  -v /work/digimatsumoto/work:/work \
  --env-file /work/digimatsumoto/system.env \
  digimatsumoto:offline

# 起動ログ確認
docker logs -f digimatsumoto
```

> `system.env` は `system.env_sample` を元に、閉域内のエンドポイント（Azure OpenAI / PostgreSQL）に合わせて作成しておきます（次ステップ参照）。
> `user/` をホスト側にボリュームマウントしておくと、エージェント定義・RAG・セッションデータをイメージ更新後も引き継げます。

### 動作確認

```
http://<閉域VMのIP>:8501   ← メイン WebUI
http://<閉域VMのIP>:8899   ← FastAPI（/run など）
```

---

## ステップ 6. Azure OpenAI 用にエージェントの呼出し関数を変更する

閉域では `api.openai.com` 等のパブリック API へ到達できません。
本プログラムは **Azure OpenAI Service に標準対応済み** なので、以下の2点を設定するだけで閉域内推論に切り替えられます。

### 6-1. `system.env`（環境変数）

閉域 VNet 内に **Private Endpoint** を張った Azure OpenAI を指すよう設定します。

```bash
# Azure OpenAI 本体
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<API key>
AZURE_OPENAI_API_VERSION="2024-12-01-preview"

# 埋め込み（RAG）も Azure 側へ寄せる
EMBED_PROVIDER="azure"
AZURE_OPENAI_EMBED_MODEL=<embedding のデプロイ名>

# 音声→テキストを使う場合
TRANSCRIBE_PROVIDER="azure"
AZURE_OPENAI_WHISPER_MODEL=<whisper のデプロイ名>

# tiktoken はパブリックからエンコーダをダウンロードするため、閉域では無効化推奨
#   （トークン数表示が概算になるが、外向き通信が消える）
TIKTOKEN_DISABLE="true"
#   厳密なトークン数が必要なら、代わりにネット環境で取得したキャッシュを同梱し
#   TIKTOKEN_CACHE_DIR を指定する（system.env_sample のコメント参照）
```

### 6-2. エージェント定義 JSON（`FUNC_NAME` と `MODEL`）

モデルのディスパッチは各エージェント JSON（`user/common/agent/agent_*.json`）の
`ENGINE.LLM.<キー>.FUNC_NAME` で決まります。
パブリック OpenAI 向けの `generate_response_T_gpt` を、**Azure 用の `generate_response_T_azure_openai`** に変更し、
`MODEL` を **Azure のデプロイ名** に置き換えます。

```jsonc
// 変更前（パブリック OpenAI）
"GPT-5.5": {
  "NAME": "GPT-5.5",
  "FUNC_NAME": "generate_response_T_gpt",   // ← パブリック OpenAI を呼ぶ
  "MODEL": "gpt-5.5",                        // ← OpenAI のモデル名
  ...
}

// 変更後（Azure OpenAI）
"GPT-5.5": {
  "NAME": "GPT-5.5",
  "FUNC_NAME": "generate_response_T_azure_openai",  // ← Azure クライアントを呼ぶ
  "MODEL": "<Azure のデプロイ名>",                    // ← Azure では「デプロイ名」を指定する
  ...
}
```

> **ポイント**
> - `generate_response_T_azure_openai` は `_get_azure_openai_client()`（`AzureOpenAI` クライアント）を使い、上記の `AZURE_OPENAI_*` 環境変数で接続します（[DigiM_FoundationModel.py](DigiM_FoundationModel.py) 参照）。
> - Azure では `MODEL` は OpenAI のモデル名ではなく、Azure ポータルで作成した**デプロイ名**を指定します。
> - 画像生成を使う場合は `generate_image_dalle` → `generate_image_azure_dalle` も同様に置き換えます。
> - 各エージェントの `ENGINE.LLM.DEFAULT` が Azure 化したキーを指しているか確認してください。
> - Gemini / Claude / Grok / Llama を指す `FUNC_NAME` は閉域では到達できません。Azure 系のキーのみを使う構成にしてください。

---

## 補足：Web 検索（WebSearch）について

閉域では **インターネット上の Web 検索は原則利用できません**。

- `WebSearch_OpenAI` は素の `OpenAI()` クライアント（`api.openai.com`）+ Responses API の `web_search_preview` ツールを使う実装で、**Azure OpenAI には対応していません**。Azure OpenAI 側もこのサーバーサイド Web 検索ツールを同等には提供していません。
- Perplexity / Google / Claude の各エンジンも外部 API への到達が前提のため、閉域では機能しません。

そのため閉域構成では、

- `setting.yaml` の `WEB_SEARCH_DEFAULT` を Web 検索に依存しない運用に切り替える、もしくは Web 検索機能を使わない、
- どうしても必要なら、承認された外向きプロキシ経由で特定 API のみ許可する、

のいずれかの方針をとってください。RAG（社内ナレッジ検索）は Azure 埋め込み + ローカル ChromaDB で完結するため、閉域でも利用可能です。

---

## 構築物まとめ（閉域内に用意するもの）

| 項目 | 内容 |
|---|---|
| アプリ | 本イメージ（`docker load` 済み） |
| LLM 推論 | Azure OpenAI（Private Endpoint） |
| 埋め込み（RAG） | Azure OpenAI Embedding（`EMBED_PROVIDER="azure"`） |
| ベクトル DB | コンテナ内蔵 ChromaDB（`user/common/rag/chromadb/`） |
| RDB | Azure Database for PostgreSQL（Private Endpoint）※ [SETUP_POSTGRESQL_AZURE.md](SETUP_POSTGRESQL_AZURE.md) |
| Web 検索 | 原則無効（外部到達不可） |
