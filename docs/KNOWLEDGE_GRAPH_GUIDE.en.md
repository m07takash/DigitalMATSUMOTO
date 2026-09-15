# Knowledge Graph Authoring Guide

A guide to **designing and writing by hand** the knowledge graphs used by DigitalMATSUMOTO's graph RAG (`RETRIEVER: "Graph"`). Every example uses the bundled sample agent **Hideto Komakino (`agent_10Sample.json` / `Sample01_Relations`)**.

For the graph RAG settings themselves (`rags.json`, the KNOWLEDGE / BOOK search policy, visualisation), see [Graph RAG (graph type) in the README](../README.en.md#graph-rag-graph-type). This guide focuses on one question: what shape of graph actually lets retrieval find what you need.

---

## 1. The big picture: where a graph comes from

A graph is saved as `user/common/rag/graph/<folder>/graph.json` and holds **only entities (nodes) and predicate edges** — no body text (that lives on the Vector RAG side). There are three ways to build one.

| Route | Input | LLM | Best for |
|---|---|---|---|
| **Hand-written graph column** (this guide) | Triples written as JSON on each Notion row | No | Getting facts in exactly, cheaply, and in the shape you designed |
| CSV column mapping (Lane A) | A ledger CSV (one row = one entity) + `mapping.json` | No | You already have a roster whose columns are the relations |
| LLM extraction from text (Lane B) | Free text | Yes | You only have prose and no time to write triples |

When ingesting from Notion, **each row uses its hand-written graph column if it is valid, and falls back to LLM extraction of the text column if the graph column is empty or broken**. Hand-written rows are recorded as `lane=STRUCTURED`, extracted rows as `lane=TEXT`, and when the same property collides **the hand-written value always wins**. You can let the LLM do everything first and then replace the important rows by hand.

`rags.json` example (a Notion DB with a "テキスト" text column and a "ナレッジグラフ" graph column):

```json
"Sample01_Relations_Notion": {
    "active": "Y",
    "input": "notion",
    "data_type": "graph",
    "data_name": "NotionDB",
    "bucket": "Sample01_Relations_Notion",
    "file_path": "user/common/rag/graph/sample01_relations_notion/",
    "extractor_agent": "agent_56GraphExtract.json",
    "item_dict": {
        "create_date": {"タイムスタンプ": "date"},
        "graph_json":  {"ナレッジグラフ": "rich_text"},
        "key_text":    [{"テキスト": "rich_text"}],
        "value_text":  {"テキスト": "rich_text"},
        "category":    {"対象": "select"}
    },
    "chk_dict": {"確定Chk": true, "GraphChk": false},
    "date_dict": {},
    "category_dict": {},
    "fin_flg": {"GraphChk": true}
}
```

- `graph_json` — the hand-written graph column. Rows where it parses never call the LLM
- `value_text` — only rows whose graph column is empty or invalid send this column to LLM extraction. **Do not point `value_text` at the graph column**, or the LLM will re-read your JSON as prose
- `create_date` — becomes the "as of" date (`as_of`) of edges and properties. When the same property comes from several rows, the newer one wins. Omit the key and the ingestion date is used
- `category` — becomes the `domains` of the edges created from that row

---

## 2. Graph column format

Write one JSON object per row (one fact).

```json
{
  "triples": [
    {"subject": "subject", "subject_type": "type", "relation": "predicate", "object": "object", "object_type": "type", "props": {"key": "value"}}
  ],
  "node_props": [
    {"entity": "node", "key": "property", "value": "value"}
  ]
}
```

| Field | Meaning |
|---|---|
| `triples` | Edges (subject → predicate → object). Subjects and objects become nodes if they do not exist yet |
| `subject_type` / `object_type` | Node type (`人物` / `組織` / `場所` …). **The first type a node gets is kept**. Types are not used to start a search (→ section 4) |
| `props` | Properties on the edge (period, role, rating …) |
| `node_props` | Properties on a node (birthday, height, title …) |

**A row is used only if** (otherwise it falls back to LLM extraction):

- It parses as JSON (a surrounding ` ```json ` fence is fine)
- `triples` or `node_props` has at least one usable item
- A triple has non-empty `subject`, `relation` and `object` (a triple missing one is dropped on its own)
- A node_prop has non-empty `entity` and `key`

> **Pasting into Notion**: half-width spaces inside values can be wrapped into line breaks during the paste. A line break breaks the JSON and the row silently falls back to LLM extraction. Write `"バー Cielo"` as `"バー Cielo"` — the ` ` escape turns back into a normal space when the row is read.

---

## 3. What becomes a node, what becomes a property

| Make it a node | Make it a property (`props` / `node_props`) |
|---|---|
| Things that can relate to other things, or that someone could ask about | Numbers, dates, titles, short descriptions |
| People, organisations, places, works, events, themes | Height, birthday, role, period, rating |

**Example**: "Meeting my stepfather" (1994/11/3) in Sample02_Experience

> My mother remarried and my surname became Komakino. Her husband, Shingo Komakino, ran a bar of his own; when we first met he slapped my shoulder instead of shaking hands.

```json
{
  "triples": [
    {"subject": "駒木乃佳代", "subject_type": "人物", "relation": "再婚する", "object": "駒木乃真吾", "object_type": "人物", "props": {"時期": "1994年11月"}},
    {"subject": "駒木乃真吾", "subject_type": "人物", "relation": "経営する", "object": "バー Cielo", "object_type": "組織"},
    {"subject": "駒木乃英人", "subject_type": "人物", "relation": "継子である", "object": "駒木乃真吾", "object_type": "人物"}
  ],
  "node_props": [
    {"entity": "駒木乃英人", "key": "姓の変遷", "value": "佐野 → 駒木乃（1994年、母の再婚による）"}
  ]
}
```

(The sample data is Japanese, so node names and values stay in Japanese: 駒木乃佳代 = his mother Kayo, 駒木乃真吾 = stepfather Shingo, バー Cielo = Bar Cielo.)

- "Bar Cielo" connects to other rows (regulars, events), so it is a node
- "November 1994" is never asked about on its own, so it goes into the edge's `props`
- How his surname changed has nothing to connect to, so it goes into `node_props`

**Avoid**: `{"subject": "駒木乃英人", "relation": "身長", "object": "176cm"}`. It only adds a leaf node "176cm" that connects to nothing. Write `{"entity": "駒木乃英人", "key": "身長", "value": "176cm"}` in `node_props` instead.

---

## 4. Design backwards from how retrieval works

Graph retrieval has three properties. Once you know them, the shape to write mostly follows.

### 4.1 The only way in is a node name (or alias) appearing in the question

A node becomes a starting point (a seed) when **its name or one of its aliases appears verbatim in the question**. `subject_type` / `object_type` play no part in choosing seeds.

```text
❌ Only giving 東京 (Tokyo) and ブエノスアイレス (Buenos Aires) object_type "場所" (place)
   → "Where has Komakino lived?" finds no node called "place", so nothing is reachable

✅ Connect Tokyo and Buenos Aires to a "居住地" (place of residence) node
   → wording in the question such as "lived" is caught by aliases (section 5)
```

**Make shared factors (themes, outlets, genres) real nodes, not types.**

### 4.2 Retrieval walks two hops, and each node has an edge cap

These come from the search policy on the agent's KNOWLEDGE / BOOK entry.

| Key | Meaning | Effect |
|---|---|---|
| `HOPS` | How many hops from a seed to walk | 2 means seed → neighbour → its neighbour |
| `FANOUT_LIMIT` | Max edges followed out of one node | The rest are dropped |
| `EDGE_LIMIT` | Max edges collected per search | Stops once reached |

Hang 100 edges off one protagonist and, with `FANOUT_LIMIT: 40`, 60 are thrown away on every search. Which ones survive depends on edge weight and date — and if every edge was ingested on the same day, **it is effectively down to ingestion order**.

### 4.3 Use three layers: domain → subcategory → concrete item

Instead of linking the protagonist straight to every concrete item, put a shared factor in between.

```text
駒木乃英人 ─[関心を持つ]→ 取材テーマ ←[属する]─ 移民・難民 ←[分類される]─ ザアタリ難民キャンプ {駒木乃の関わり: 現地取材}
                                     ←[属する]─ 労働       ←[分類される]─ 名前のない働き手たち {駒木乃の関わり: 記事}
```

(取材テーマ = reporting themes, 移民・難民 = migrants & refugees, 労働 = labour, ザアタリ難民キャンプ = Zaatari refugee camp, 名前のない働き手たち = the article "Nameless workers".)

- **Seed is a concrete item** ("Zaatari refugee camp"): one hop reaches "migrants & refugees", two hops list the other places reported on under that theme
- **Seed is a subcategory** ("Where did he report on migrants & refugees?"): one hop lists every place
- **Seed is the protagonist** ("What are Komakino's reporting themes?"): one hop reaches "reporting themes", two hops list the themes. You get a **table of contents** rather than details, and it stays well under the edge caps

Stop at three layers. With `HOPS: 2`, a concrete item reaches its siblings exactly; a fourth layer puts them out of reach.

As a graph column, one row might read:

```json
{
  "triples": [
    {"subject": "ザアタリ難民キャンプ", "subject_type": "場所", "relation": "分類される", "object": "移民・難民", "object_type": "カテゴリ", "props": {"駒木乃の関わり": "現地取材"}},
    {"subject": "移民・難民", "subject_type": "カテゴリ", "relation": "属する", "object": "取材テーマ", "object_type": "領域"},
    {"subject": "駒木乃英人", "subject_type": "人物", "relation": "関心を持つ", "object": "取材テーマ", "object_type": "領域"}
  ]
}
```

It is fine to repeat the second and third "structure" edges on every row under the same domain. Identical edges merge into one; only the list of rows they came from grows. Writing them on each row also means the structure survives if one row is later excluded from ingestion.

### 4.4 Depth comes from real links across domains

A hierarchy alone is just a tree. The depth that makes a graph useful comes from facts that join different domains.

**Example**: "Grandfather's tango shoes" in Sample03_Impressions and "Learning the ocho from grandfather" in Sample02_Experience

```json
{
  "triples": [
    {"subject": "エドゥアルド・アヤラ", "subject_type": "人物", "relation": "教える", "object": "オチョ", "object_type": "技能", "props": {"時期": "1990年", "場所": "畳の上"}},
    {"subject": "駒木乃英人", "subject_type": "人物", "relation": "習う", "object": "オチョ", "object_type": "技能", "props": {"年齢": "4歳"}},
    {"subject": "オチョ", "subject_type": "技能", "relation": "分類される", "object": "タンゴのステップ", "object_type": "カテゴリ"}
  ],
  "node_props": [
    {"entity": "駒木乃英人", "key": "ペンネームの由来", "value": "祖父に教わった8の字のステップ「オチョ」"}
  ]
}
```

"Family (grandfather Eduardo Ayala)" and "work (the pen name Eight)" now meet at "ocho", so "Where does the pen name come from?" reaches the grandfather, and "Tell me about his grandfather" reaches his work, both within two hops.

Adding general-knowledge facts ("Zaatari refugee camp is in Jordan") helps too — but **only facts that are certainly true**, and about the person themselves, only what the source material actually says.

---

## 5. Keep names, predicates and property keys consistent

### Name nodes with the words users actually type

Seeds are chosen by substring match, so an administrative name like "preference category: visual works" never becomes a seed. Choose words that appear in questions as-is: "取材テーマ" (reporting themes), "媒体" (outlets), "家族" (family).

Spelling variants ("エイト", "Eight", "英人") should not become separate nodes — merge them into one node with `aliases` in `dictionary.json` (section 6).

> **Very short aliases misfire.** Matching is by substring, so a one- or two-character alias hits unrelated questions. The sample's `"母": "駒木乃佳代"` ("mother") also matches words like 母国 ("home country") and 分母 ("denominator"), and `"自分": "駒木乃英人"` ("myself") turns questions like "I want to look it up myself" into a seed. In real use, prefer longer aliases such as "駒木乃の母" ("Komakino's mother").

### Fix a small set of predicates

| Predicate | Use for |
|---|---|
| `分類される` (is classified as) | concrete item → subcategory ("a kind of") |
| `属する` (belongs to) | subcategory → domain ("part of") |
| `関心を持つ` (is interested in) | protagonist → domain |
| Concrete verbs | `取材する` (reports on), `寄稿する` (writes for), `教える` (teaches), `経営する` (runs) — the fact itself |

- Avoid vague predicates like "関連" (related). The LLM cannot tell what connects to what
- Do not multiply synonyms: if `好む` / `好き` / `選好する` / `支持する` ("likes / is fond of / prefers / supports") all appear, they can no longer be read as the same kind of relation

### Express ratings and strength as a props value, not a predicate

```json
{"subject": "季刊SOIL", "relation": "分類される", "object": "寄稿先", "props": {"駒木乃の評価": "最も書きやすい"}}
```

(季刊SOIL = the quarterly SOIL, 寄稿先 = outlets he writes for, 駒木乃の評価 = Komakino's rating, 最も書きやすい = easiest to write for.) Rather than splitting predicates into "likes most / especially likes / likes", pick one key (`駒木乃の評価`) and vary the value; it stays readable across the whole graph later.

### Watch out for self-loops

An edge whose subject and object resolve to the same node through aliases is **dropped at ingestion**.

```text
❌ {"subject": "Eight", "relation": "呼ばれる", "object": "駒木乃英人"}
   → "Eight" is an alias of 駒木乃英人, so this is an edge from a node to itself and is dropped
✅ Put nicknames in dictionary.json aliases, or in node_props:
   {"entity": "駒木乃英人", "key": "ペンネーム", "value": "Eight"}
```

---

## 6. dictionary.json (aliases, seeds, property notes)

A settings file placed in the graph folder (next to `graph.json`). It is read both at ingestion and at search time. The sample is `user/common/rag/graph/Sample01_Relations/dictionary.json`.

```json
{
    "aliases": {
        "エイト": "駒木乃英人",
        "Eight": "駒木乃英人",
        "英人": "駒木乃英人",
        "祖父アヤラ": "エドゥアルド・アヤラ",
        "継父": "駒木乃真吾",
        "シエロ": "バー Cielo",
        "ATLAS": "ATLAS日本版"
    },
    "seeds": [
        {"name": "駒木乃英人", "type": "人物", "aliases": ["エイト", "Eight", "英人"], "domains": ["家族", "仕事", "ルーツ"]}
    ],
    "prop_schema": {
        "役割": {"description": "そのエンティティの立場・肩書き"}
    }
}
```

| Key | At ingestion | At search |
|---|---|---|
| `aliases` | Names written in the graph column are mapped to the canonical name (writing "継父" / stepfather still lands on the 駒木乃真吾 node) | An alias in the question makes the canonical node a seed |
| `seeds` | While the graph is still empty, these nodes are created unconditionally (with type, aliases and domains) | — |
| `prop_schema` | Notes on what each property key means (for people and agents) | — |

Delete Graph DB removes only `graph.json`; `dictionary.json` stays.

---

## 7. Ingesting and rebuilding

### Ingesting from Notion

1. Add a `rags.json` entry like the one in section 1
2. Tick `確定Chk` on the rows to include (only rows matching `chk_dict` are ingested)
3. Press **Update RAG Data** in the WebUI
4. Ingested rows get `GraphChk` ticked as `fin_flg` says, and are skipped from then on

### "I fixed the graph column but nothing changed"

**A page that has already been ingested is skipped, even if you rewrite its graph column**, because its page ID is already recorded on the graph's edges. To rebuild:

1. Delete the graph's `graph.json` with **Delete Graph DB** in the WebUI
2. **Untick `GraphChk` on every row** in Notion
3. Press **Update RAG Data**

### Excel editing is for trying things out

From the graph screen in Knowledge Explorer you can download nodes and edges as Excel, edit them, and upload to apply. It is handy for adding a shared factor and checking whether retrieval improves. But a rebuild using the steps above **discards Excel edits**. Write the changes that worked back into the Notion graph column, which is the source of truth.

### Building from CSV (Lane A)

With a ledger CSV and `mapping.json`, one command rebuilds the whole graph every time (no LLM).

```bash
python3 DigiM_GraphBuilder.py user/common/rag/graph/Sample01_Relations
```

### Pasting a graph column into Notion in bulk

- Sort the Notion table by **ID ascending** before pasting. If the source CSV's row order differs from Notion's, graphs end up on the wrong rows
- After pasting, open a few rows and check that the text and graph columns describe the same fact

---

## 8. Common mistakes

| Symptom | Cause | Fix |
|---|---|---|
| One row was LLM-extracted instead | A half-width space in a value turned into a line break and broke the JSON | Write spaces as ` ` (section 2) |
| A fact from another row is in the graph | The graph column was pasted by row position | Re-paste matched by ID (section 7) |
| Asking about "outlets" or "reporting themes" returns nothing | Things were classified only by type (`object_type`), so no node has that name | Make the shared factor a real node (4.1) |
| Questions about the protagonist return loosely related edges | Edges pile up on the protagonist and get cut by the cap | Split the hub with three layers (4.3) |
| Editing the graph column changes nothing | Already-ingested pages are skipped | Delete `graph.json`, untick `GraphChk`, ingest again (section 7) |
| Naming a domain in the question lowers the ranking | The search policy's `DOMAIN_BONUS` is below 1 (it multiplies, so it becomes a penalty) | Set it to 1 or more (the sample uses `1.3`) |
| Every property has the same "as of" date | `create_date` is not mapped, so the ingestion date is used | Add a timestamp column in Notion and map it in `item_dict.create_date` |
| An edge is never created | Subject and object resolve to the same node via aliases (self-loop) | Put nicknames in `aliases` or `node_props` (section 5) |

---

## 9. Checking the graph you wrote

### Look at its shape

The graph screen in Knowledge Explorer shows node and edge counts and the highest-degree nodes. The graph is in a retrieval-friendly shape when:

- The highest-degree nodes are domains and subcategories, not the protagonist
- No node has far more edges than the search policy's `FANOUT_LIMIT`
- There are no isolated nodes connected to nothing

### Run an actual search

With the same search policy as the agent, you can see which nodes a question seeds and which edges come back (no LLM call).

```python
import DigiM_Graph as dmg

policy = {"HOPS": 2, "EDGE_LIMIT": 30, "FANOUT_LIMIT": 5, "DOMAIN_BONUS": 1.3}  # same as agent_10Sample
r = dmg.search_graph("移民・難民の取材で関わった場所は？",
                     "user/common/rag/graph/Sample01_Relations/", policy)
G, N = r["graph"], r["graph"]["nodes"]
print("seeds:", [N[s]["name"] for s in r["seeds"]])
for ei, hop, kind in r["selected"]:
    e = G["edges"][ei]
    print(hop, kind, N[e["source"]]["name"], f"-[{e['relation']}]->", N[e["target"]]["name"])
```

- **No seeds** → the question's words are neither a node name nor an alias (4.1 / section 6)
- **The node you want is missing** → it is three or more hops away, or a hub on the way cut it off (4.2 / 4.3)
- **Mostly loosely related edges** → the seed itself is a hub (4.3)

Running this check every time you rewrite the graph column catches "I wrote it but it never comes back" early.
