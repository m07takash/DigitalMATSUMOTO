### はじめに
本PGはApache2.0Licenceで公開しており、商用利用を認めています。
ただし、本PGを用いたユーザー側での活動に対して、開発者は一切の責任を負いませんので、あくまで御自身の責任においてPGを利用してください。

本PGはビジネスのシーンで活用されたことがありますが、
あくまで研究もしくはPoCを目的として開発を行っており、開発者の任意のタイミングでプログラムの更新が行われます。
実際のビジネスで用いる場合、Apache2.0のライセンスを遵守いただきながら、御自身の判断と責任において最適なシステム環境で構築・運用いただくことを推奨します。

Digital MATSUMOTO lab合同会社

### 本プログラム開発においてこだわっていること
・作業効率化ではなく、人間の知識をAIが再現できるかが主目的
・知識の貢献などを観察できるようにする
・自律化は目的としない。AIを使いながらヒト自身も成長できるかが命題
・特定のLLMに依存しない
・コンテキストデザインをこだわって作る
・LangChainやllama indexのようなライブラリを使わない（LLMのAPIを裸の状態で叩く）
・個人の環境でも動くような構成

### 参考ドキュメント

概要とアーキテクチャの説明
https://github.com/m07takash/DigitalMATSUMOTO/blob/main/docs/%E3%83%87%E3%82%B8%E3%82%BF%E3%83%ABMATSUMOTO%E3%81%AE%E6%A6%82%E8%A6%81%E3%81%A8%E3%82%A2%E3%83%BC%E3%82%AD%E3%83%86%E3%82%AF%E3%83%81%E3%83%A3.pdf

インストール＆セットアップ及びエージェントの設定等（ハンズオン資料）
https://github.com/m07takash/DigitalMATSUMOTO/blob/main/docs/%E3%83%87%E3%82%B8%E3%82%BF%E3%83%ABMATSUMOTO-PG%E3%83%8F%E3%83%B3%E3%82%BA%E3%82%AA%E3%83%B3.pdf

### アーキテクチャ概要

[Streamlit UI / FastAPI / Jupyter Notebook]
          ↓
   DigiM_Execute.py        # 実行オーケストレーション
          ↓
   DigiM_Agent.py          # エージェント呼出
   DigiM_Context.py        # コンテキスト生成・RAGクエリ
   DigiM_Session.py        # セッション・履歴管理
          ↓
   DigiM_FoundationModel.py  # LLM抽象化レイヤー
   DigiM_Tool.py             # ツール(定義された関数)
          ↓
[GPT / Gemini / Claude / Grok]

エージェントの設定（人格・使用LLM・知識）は `user/common/agent/*.json` で管理し、
コンテキストはプロンプトテンプレート（`user/common/mst/prompt_templates.json`）と
RAG（ChromaDB）を組み合わせて動的に生成します。


### 主要モジュール

| モジュール | 役割 |
|-----------|------|
| `DigiM_Execute.py` | メイン実行エンジン |
| `DigiM_Session.py` | セッション・チャット履歴管理 |
| `DigiM_Context.py` | コンテキスト生成・RAG処理 |
| `DigiM_FoundationModel.py` | LLM抽象化（マルチLLM対応） |
| `DigiM_Agent.py` | エージェント設定管理 |
| `DigiM_Tool.py` | ツール群（分析・履歴操作等） |
| `DigiM_Util.py` | 共通関数 |
| `DigiM_Notion.py` | Notion API連携 |
| `WebDigiMatsuAgent.py` | WebUI画面 |
| `DigiM_API.py` | FastAPI エンドポイント |
| `DigiM_VAnalytics.py` | 知識活用分析 |
| `DigiM_GeneCommunication.py` | ユーザーフィードバック |
| `DigiM_GeneUserDialog.py` | ユーザー対話の保存 |

### ディレクトリ構造

```
DigitalMATSUMOTO/
├── user/
│   ├── common/
│   │   ├── agent/          # エージェント設定JSON
│   │   ├── practice/       # プラクティス設定JSON
│   │   ├── mst/            # マスターデータ（ユーザー・RAG・プロンプト等）
│   │   ├── rag/chromadb/   # ベクトルDB（ChromaDB）
│   │   └── csv/            # RAG用CSVデータ
│   └── session*/           # セッションデータ（チャット履歴）
├── setting.yaml            # フォルダパス等のシステム設定
├── system.env              # APIキー等の環境変数（要作成）
└── system.env_sample       # 環境変数のテンプレート
```
