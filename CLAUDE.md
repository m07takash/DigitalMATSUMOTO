# DigitalMATSUMOTO — Claude Code 作業規約

Claude Code が本リポジトリで作業する際の運用ルール。**「知らないと事故る」ものだけ**を書く。
コードを読めば分かる事実（アーキテクチャ、ファイル配置、API シグネチャ等）は含めない。

---

## 1. 触るときに事故りやすい箇所

### Streamlit バックエンドは編集後にフルプロセス再起動が必要
`DigiM_*.py` などのバックエンドモジュールを変更しても、Streamlit のモジュールキャッシュはホットリロードで拾わない。
「変えたのに反映されていない」と見えたら、まずアプリを完全に落として起動し直すこと。

### `WebDigiMatsuAgent.py` と `WebDigiMatsuAgent_modified.py` はミラー
WebUI に変更を入れるときは両方に同じ差分を当てる。片方だけ直すと切り替え時に不整合が出る。

### セッション state のキー名は凍結
`_rag_*` を含む、保存済み `.pkl` セッションが依存するキー名は**絶対にリネームしない**。過去セッションの復元が壊れる。

### プロンプトテンプレートはネスト位置を間違えない
`PROMPT_TEMPLATE.<name>` のようにネストされたキーを読むコードが多い。
トップレベルに書いてしまうと読み込まれない（サイレントに動くので気付きにくい）。
`prompt_templates.json` を変更したら **`sample_prompt_templates.json` にも同じ変更を反映**すること。

### RAG 設定に `RETRIEVER` の分岐がある
`RETRIEVER` が `Vector` 前提で書かれているアナリティクス／ユーティリティが複数ある（`VAnalyticsMonthlyKnowledge`, `analytics_knowledge` など）。
Graph / PageIndex / AgentSearch / FunctionSearch を追加するときは、それぞれの関数で `if _retriever != "Vector": continue` などのガードが必要。

---

## 2. 書式ルール

### JSON（エージェント／RAG／プロンプトテンプレ／マスタ）
- **4スペースインデント**
- **`ensure_ascii=False`**（日本語はエスケープせずそのまま）
- **末尾に改行を1つ残す**
- 書き換え・再整形は `json.dumps(data, indent=4, ensure_ascii=False)` を使う
- キーの並び順は既存に合わせる（意図がなければ順序を変えない）

### Python
- **4スペースインデント**
- import 順序は既存を尊重（新しく足すときは近い場所へ）
- 冗長な docstring は書かない — 挙動は識別子とコードで語らせる
- 短い行コメントで補うのは可

### コメント／ドキュメント
- **WHY のみ書く**（WHAT は識別子で分かる）
- タスク番号／PR番号／「呼び出し元は X」といった言及はしない（コードは残るがそれらは腐る）
- コメントは英語、既存ファイルのトーンに合わせる
- 画面パーツの表記やエラーメッセージも英語

---

## 3. 命名パターン（既存に揃える）

### Python モジュール
- `DigiM_*.py` — バックエンド／コアモジュール（`DigiM_Agent`, `DigiM_Context`, `DigiM_Graph` …）
- `V*.py` — 分析／ビュー処理（`VAnalyticsArticle`, `VAnalyticsMonthlyInsight`, `VAnalyticsMonthlyKnowledge`）
- `Web*.py` — Streamlit の UI エントリ（`WebDigiMatsuAgent.py`, `WebDigiMatsuAgent_modified.py`）
- 命名スタイルは既存が **混在**（`DigiM_Agent` はアンダースコア、`DigiMSession` は連結）。**統一しようとしない** — 既存クラス／モジュールに合わせる。

### エージェント JSON — `user/common/agent/agent_<2桁>_<Name>.json`
番号帯は既存の慣習に従う。空き番があれば同じ帯に足す。
- `0X` … メインエージェント本体（`01DigitalMATSUMOTO`, `02DigitalMATSUMOTO(Vec)`）、`0A` = API 版
- `1X` … Sample／テンプレート
- `2X` … 汎用ユーティリティ（`21EthicalCheck`, `22SenryuSensei`, `23DataAnalyst` …）
- `5X` … サブエージェント（`50PersonaMerge`, `51DialogDigest`, `54PersonaSelector` …）
- `6X` … 支援エージェント（`55ExtractDate`, `56RAGQueryGenerator`, `63KnowledgeInterpret`, `67GraphExtract` …）
- `7X` … `6X` の DigiM プレフィックス派生（本体埋め込み向け。`70DigiMThinking`, `75DigiMExtractDate`, `76DigiMRAGQueryGenerator` …）
- `A0` … 他人格エージェント（`A0AkioMorita`）
- `R1`〜 … シリーズ物（TheRound の `R1Novie`, `R2Kuroe`, `R3TheRound`）

### マスタデータ — `user/common/mst/`
`<name>.json` は運用データ、`sample_<name>.json` は配布用のサンプル。
**両方に同じ変更を反映する**（サンプルだけ古いと初回セットアップで壊れる）。

### JSON キー
- エージェント／RAG のトップレベル設定キーは **SCREAMING_SNAKE_CASE**（`ENGINE`, `KNOWLEDGE`, `PERSONA`, `RETRIEVER`, `DATA_TYPE`, `RAG_NAME` …）
- 内部データやログのフィールドは **snake_case**（`create_date`, `vector_data_value_text`, `similarity_Q` …）
- 既存に迷ったら **周辺のキーに合わせる**（規約より周辺の整合の方が保守しやすい）

### Python 関数／変数
- `snake_case`
- private ヘルパは `_leading_underscore`（例: `_freq_color`, `_edge_style`, `_time_setting`）
- Session state のキーも `snake_case`。`_rag_*` は互換性のため固定（§1 参照）。

---

## 4. 触るスコープ

- **新規ファイル**: 本規約に準拠。
- **既存ファイル**: 既存の書式を尊重し、勝手に整形しない（差分を膨らませない）。
  ただし大きな書き換え中、または明らかに壊れている書式（インデント混在など）は整えてよい。
- 「ついでに周辺を綺麗にする」は基本しない。頼まれた変更に集中する。

---

## 5. 検証

- **UI 変更は起動して手元で動かして確認するのが望ましい**。
  ただし環境上難しい場合（サンドボックス／リモート実行）は「未検証」と明記する。
- 型チェックや自動テストは「コードの正しさ」を見るもので、「機能の正しさ」を保証しない。UI／プロンプト／RAG 系の変更は特にそう。

---

## 6. 参考: 直近の運用メモ

- README / README.en の内容は原則同期する（片方だけ更新しない）。
- 新しい `RETRIEVER` タイプや `DATA_TYPE` を足したら、アナリティクス系（`DigiM_VAnalytics`, `VAnalyticsMonthly*`, `VAnalyticsArticle`）にも通し確認する。
