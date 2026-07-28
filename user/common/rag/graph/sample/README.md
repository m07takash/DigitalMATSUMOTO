# GraphRAG 取込サンプル（sample_governance）

GraphRAG（`RETRIEVER: "Graph"`）のデータ取込サンプル一式です。
取込は **2レーン方式** で、どの列をエンティティ／状態（props）／関係にするかを
`mapping.json` で宣言します。

```
sample/
├── source/
│   ├── SampleGraph01_Person.csv        # レーンA: 人物マスタ（状態 + 所属エッジ）
│   ├── SampleGraph02_Organization.csv  # レーンA: 組織マスタ（状態のみ）
│   ├── SampleGraph03_Initiative.csv    # レーンA: 取り組み・規範（複数値の関係列）
│   └── SampleGraph04_Insight.csv       # レーンB: 考察コラム（自由文 → LLM抽出）
├── mapping.json                        # ソース定義（列マッピング / レーン指定）
├── dictionary.json                     # エイリアス正規化・シード・prop_schema
└── README.md
```

## 2レーン方式

| レーン | 対象 | 変換方法 | LLM |
|--------|------|----------|-----|
| **STRUCTURED**（レーンA） | CSV列 / NotionプロパティE/ RDBカラム | `MAPPING` の宣言どおり決定的に変換 | 不要 |
| **TEXT**（レーンB） | 自由文列 | agent_67GraphExtract が三つ組・状態候補を抽出 | 必要 |

同じ状態キーに複数ソースから値が来た場合の優先順位:
**① STRUCTURED > ② 辞書シード > ③ TEXT（LLM抽出）**、同順位は `AS_OF` の新しい方。

## このサンプルが実演していること

- **状態（props）の列指定** — `birth_date` → `生年月日` など（SampleGraph01）
- **エッジの状態** — `所属` エッジに `役職` / `期間` を付与（SampleGraph01 の org/role/join_period）
- **複数値セル** — `;` 区切り（`経済産業省;総務省` → 策定エッジ2本。MULTI_VALUE_SEPARATOR）
- **共通ドメイン** — 経済産業省は `AIガバナンス;海外動向` の2ドメイン所属
- **方向指定** — `direction: "IN"`（`(経済産業省) --[策定]--> (AI事業者ガイドライン)`）
- **エイリアス正規化** — レーンBの本文中の「経産省」「松本さん」「RCModel」が
  dictionary.json で正規名に吸収される
- **スタンス抽出** — レーンBの「〜と評価する」「〜と懸念を示している」から
  `--[評価]-->` / `--[懸念]-->` エッジが抽出される（述語の具体化）

## 備考

- CSVは既存サンプル（`user/common/csv/Sample*.csv`）と同じ UTF-8(BOM付き)・
  英小文字ヘッダー・日本語値の規約
- グラフ本体（graph.json）は取込バッチ（DigiM_GraphBuilder / Phase 1 実装予定）が
  この定義から生成する
