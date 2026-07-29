# DigiM_Graph.py
# ============================================================================
# GraphRAG core for Digital MATSUMOTO.
#
# The graph is *pure structure*: Entity nodes + predicate edges. It carries
# no chunk bodies and no free-text descriptions — body text stays in the
# Vector RAG (ChromaDB) side. Both nodes and edges may carry "props"
# (states) such as 生年月日 / 居住地 (node) or 役職 / 期間 (edge).
#
# Storage: one folder per graph (rags master data_type="graph"):
#     <graph_dir>/graph.json       node-link JSON (this module's schema)
#     <graph_dir>/dictionary.json  alias map + seeds + prop_schema
#     <graph_dir>/mapping.json     ingestion source definitions (2 lanes)
#
# Node : { id, name, type, aliases[], domains[],
#          props{key: {value, as_of, source_id, lane}}, embedding? }
# Edge : { source, target, relation, domains[],
#          props{key: {value, as_of, source_id, lane}},
#          source_ids[], create_date }
#
# Retrieval = paths between seed entities (protected) + neighborhoods
# (hop-ascending), capped by EDGE_LIMIT / FANOUT_LIMIT, with DOMAIN_BONUS
# when the query names a domain. Policy knobs live on the agent's
# KNOWLEDGE/BOOK entry, not here and not in the rags master.
# ============================================================================

import os
import csv
import json
import hashlib
import re
from pathlib import Path
from collections import deque

import DigiM_Util as dmu

# Lane priority for prop conflicts: higher wins; ties -> newer as_of wins.
LANE_PRIORITY = {"STRUCTURED": 3, "SEED": 2, "TEXT": 1}

_setting = dmu.read_yaml_file("setting.yaml") or {}
rag_folder_graph_path = _setting.get("RAG_FOLDER_GRAPH", "user/common/rag/graph/")
mst_folder_path = _setting.get("MST_FOLDER", "user/common/mst/")


# ---------------------------------------------------------------- storage --
def resolve_graph_dir(data_name):
    """DATA_NAME -> graph folder. Prefer the rags master (data_type='graph'),
    fall back to RAG_FOLDER_GRAPH/<data_name>/."""
    try:
        rags_file = _setting.get("RAG_MST_FILE", "sample_rags.json")
        rags = dmu.read_json_file(rags_file, mst_folder_path) or {}
        entry = rags.get(data_name) or {}
        if entry.get("data_type") == "graph" and entry.get("file_path"):
            return entry["file_path"]
    except Exception:
        pass
    return str(Path(rag_folder_graph_path) / data_name) + os.sep


def get_graph_list():
    """List available graphs for UI selectors: active rags-master entries
    (data_type='graph') plus RAG_FOLDER_GRAPH subfolders holding a graph.json
    that no master entry already covers."""
    names, covered = [], set()
    try:
        rags_file = _setting.get("RAG_MST_FILE", "sample_rags.json")
        rags = dmu.read_json_file(rags_file, mst_folder_path) or {}
        for k, v in rags.items():
            if v.get("data_type") == "graph" and v.get("active", "Y") == "Y":
                names.append(k)
                covered.add(os.path.normpath(v.get("file_path", "")))
    except Exception:
        pass
    if os.path.isdir(rag_folder_graph_path):
        for d in sorted(os.listdir(rag_folder_graph_path)):
            p = os.path.join(rag_folder_graph_path, d)
            if os.path.exists(os.path.join(p, "graph.json")) and os.path.normpath(p) not in covered:
                names.append(d)
    return names


def load_graph(graph_dir):
    path = str(Path(graph_dir) / "graph.json")
    if os.path.exists(path):
        g = dmu.read_json_file(path) or {}
    else:
        g = {}
    g.setdefault("nodes", {})
    g.setdefault("edges", [])
    return g


def save_graph(graph_dir, graph):
    os.makedirs(graph_dir, exist_ok=True)
    path = str(Path(graph_dir) / "graph.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(graph, f, ensure_ascii=False, indent=1)
    return path


def load_dictionary(graph_dir):
    path = str(Path(graph_dir) / "dictionary.json")
    d = dmu.read_json_file(path) if os.path.exists(path) else {}
    d = d or {}
    d.setdefault("aliases", {})
    d.setdefault("seeds", [])
    d.setdefault("prop_schema", {})
    return d


# ------------------------------------------------------- entity resolution --
def canonical_name(name, dictionary):
    """Normalize an entity mention through the alias map."""
    name = (name or "").strip()
    return dictionary.get("aliases", {}).get(name, name)


def node_id_for(name):
    """Deterministic node id from the canonical name (stable across builds)."""
    return "ent_" + hashlib.md5(name.encode("utf-8")).hexdigest()[:12]


def upsert_node(graph, name, node_type="", aliases=None, domains=None, dictionary=None):
    """Create or merge a node by canonical name. Returns the node dict."""
    dictionary = dictionary or {"aliases": {}}
    cname = canonical_name(name, dictionary)
    if not cname:
        return None
    nid = node_id_for(cname)
    node = graph["nodes"].get(nid)
    if node is None:
        node = {"id": nid, "name": cname, "type": node_type or "",
                "aliases": [], "domains": [], "props": {}}
        graph["nodes"][nid] = node
    if node_type and not node.get("type"):
        node["type"] = node_type
    for a in (aliases or []):
        a = a.strip()
        if a and a != cname and a not in node["aliases"]:
            node["aliases"].append(a)
    for d in (domains or []):
        if d and d not in node["domains"]:
            node["domains"].append(d)
    return node


def set_prop(props, key, value, as_of="", source_id="", lane="STRUCTURED"):
    """Overwrite-semantics state write. Higher lane wins; same lane -> newer
    as_of wins (missing as_of loses to any dated value)."""
    if value in (None, ""):
        return
    cur = props.get(key)
    if cur:
        cur_p = LANE_PRIORITY.get(cur.get("lane", "TEXT"), 1)
        new_p = LANE_PRIORITY.get(lane, 1)
        if new_p < cur_p:
            return
        if new_p == cur_p and str(as_of or "") < str(cur.get("as_of") or ""):
            return
    props[key] = {"value": value, "as_of": as_of or "", "source_id": source_id or "", "lane": lane}


def upsert_edge(graph, src_id, dst_id, relation, domains=None, props=None,
                source_id="", create_date="", lane="STRUCTURED"):
    """Create or merge an edge keyed by (source, target, relation)."""
    if not (src_id and dst_id and relation) or src_id == dst_id:
        return None
    edge = None
    for e in graph["edges"]:
        if e["source"] == src_id and e["target"] == dst_id and e["relation"] == relation:
            edge = e
            break
    if edge is None:
        edge = {"source": src_id, "target": dst_id, "relation": relation,
                "domains": [], "props": {}, "source_ids": [], "create_date": create_date or ""}
        graph["edges"].append(edge)
    for d in (domains or []):
        if d and d not in edge["domains"]:
            edge["domains"].append(d)
    for k, v in (props or {}).items():
        if isinstance(v, dict):
            set_prop(edge["props"], k, v.get("value"), v.get("as_of", ""), v.get("source_id", ""), v.get("lane", lane))
        else:
            set_prop(edge["props"], k, v, create_date, source_id, lane)
    if source_id and source_id not in edge["source_ids"]:
        edge["source_ids"].append(source_id)
    if create_date and (not edge["create_date"] or create_date > edge["create_date"]):
        edge["create_date"] = create_date
    return edge


# ------------------------------------------------------------- ingestion ---
def _split_multi(value, sep):
    return [v.strip() for v in str(value or "").split(sep) if v.strip()]


def ingest_seeds(graph, dictionary):
    """Dictionary seeds become nodes unconditionally (lane=SEED)."""
    for seed in dictionary.get("seeds", []):
        upsert_node(graph, seed.get("name", ""), seed.get("type", ""),
                    aliases=seed.get("aliases", []), domains=seed.get("domains", []),
                    dictionary=dictionary)


def ingest_structured_source(graph, dictionary, graph_dir, source, sep=";"):
    """Lane A: deterministic column mapping. No LLM involved."""
    mapping = source.get("MAPPING", {})
    file_path = str(Path(graph_dir) / source.get("FILE", ""))
    if not os.path.exists(file_path):
        return {"file": source.get("FILE"), "rows": 0, "error": "file not found"}

    ent_map = mapping.get("ENTITY", {})
    props_map = mapping.get("PROPS", {})
    rel_maps = mapping.get("RELATIONS", [])
    domains_col = mapping.get("DOMAINS", "")
    as_of_col = mapping.get("AS_OF", "")

    rows = 0
    with open(file_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows += 1
            name = row.get(ent_map.get("name", ""), "")
            if not name:
                continue
            # ENTITY.type is either a literal type label or a column name.
            type_spec = ent_map.get("type", "")
            node_type = row.get(type_spec, type_spec)
            aliases = _split_multi(row.get(ent_map.get("aliases", ""), ""), sep)
            domains = _split_multi(row.get(domains_col, ""), sep)
            as_of = row.get(as_of_col, "")

            node = upsert_node(graph, name, node_type, aliases, domains, dictionary)
            if node is None:
                continue
            for prop_key, col in props_map.items():
                set_prop(node["props"], prop_key, row.get(col, ""), as_of,
                         source.get("FILE", ""), "STRUCTURED")

            for rel in rel_maps:
                targets = _split_multi(row.get(rel.get("target_col", ""), ""), sep)
                for target_name in targets:
                    tnode = upsert_node(graph, target_name, "", [], domains, dictionary)
                    if tnode is None:
                        continue
                    edge_props = {k: row.get(col, "") for k, col in (rel.get("props") or {}).items()}
                    # direction OUT (default): entity -> target / IN: target -> entity
                    if rel.get("direction", "OUT") == "IN":
                        src, dst = tnode["id"], node["id"]
                    else:
                        src, dst = node["id"], tnode["id"]
                    upsert_edge(graph, src, dst, rel.get("relation", "関連"),
                                domains=domains, props=edge_props,
                                source_id=source.get("FILE", ""), create_date=as_of,
                                lane="STRUCTURED")
    return {"file": source.get("FILE"), "rows": rows}


GRAPH_EXTRACT_PROMPT = """あなたは知識グラフの抽出器です。以下の本文から三つ組と状態を抽出し、JSONのみで出力してください。

ルール:
- 述語(relation)は「関連」のような曖昧語を避け、評価/懸念/提案/参画/策定/対照 などの具体動詞にする
- エンティティは (1)他エンティティとも関係を持ちうる (2)質問の主題になりうる もののみ。数値・日付・役職などは props に入れる
- 出力形式: {"triples": [{"subject": "", "subject_type": "", "relation": "", "object": "", "object_type": "", "props": {"期間": "", "役割": ""}}], "node_props": [{"entity": "", "key": "", "value": ""}]}

既知のエンティティ: %s

本文:
%s
"""


def ingest_text_source(graph, dictionary, graph_dir, source, llm_extractor, sep=";"):
    """Lane B: free-text extraction through an LLM extractor callable.
    `llm_extractor(prompt) -> str(JSON)` keeps this module offline-testable."""
    mapping = source.get("MAPPING", {})
    file_path = str(Path(graph_dir) / source.get("FILE", ""))
    if not os.path.exists(file_path):
        return {"file": source.get("FILE"), "rows": 0, "error": "file not found"}
    if llm_extractor is None:
        return {"file": source.get("FILE"), "rows": 0, "skipped": "no LLM extractor (use --use-llm)"}

    text_col = mapping.get("TEXT", "text")
    domains_col = mapping.get("DOMAINS", "category")
    as_of_col = mapping.get("AS_OF", "create_date")
    source_id_col = mapping.get("SOURCE_ID", "")

    known = [n["name"] for n in graph["nodes"].values()]
    rows = 0
    with open(file_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows += 1
            text = row.get(text_col, "")
            if not text:
                continue
            domains = _split_multi(row.get(domains_col, ""), sep)
            as_of = row.get(as_of_col, "")
            source_id = row.get(source_id_col, "") or source.get("FILE", "")

            prompt = GRAPH_EXTRACT_PROMPT % (", ".join(known[:50]), text)
            try:
                raw = llm_extractor(prompt)
                data = json.loads(re.sub(r"^```(json)?|```$", "", str(raw).strip(), flags=re.M))
            except Exception as e:
                data = {}
                print(f"[DigiM_Graph] extract failed ({source_id}): {e}")
            for t in data.get("triples", []):
                s = upsert_node(graph, t.get("subject", ""), t.get("subject_type", ""), [], domains, dictionary)
                o = upsert_node(graph, t.get("object", ""), t.get("object_type", ""), [], domains, dictionary)
                if s and o:
                    upsert_edge(graph, s["id"], o["id"], t.get("relation", "関連"),
                                domains=domains, props=t.get("props") or {},
                                source_id=source_id, create_date=as_of, lane="TEXT")
            for p in data.get("node_props", []):
                node = upsert_node(graph, p.get("entity", ""), "", [], domains, dictionary)
                if node:
                    set_prop(node["props"], p.get("key", ""), p.get("value", ""), as_of, source_id, "TEXT")
    return {"file": source.get("FILE"), "rows": rows}


def promote_props_to_edges(graph, dictionary):
    """Props whose value matches an existing node (or seed) become edges.
    Deterministic: dictionary/name match only. e.g. 居住地:東京 -> --[居住地]--> (東京)
    only when 東京 is already a node."""
    name_index = {n["name"]: n["id"] for n in graph["nodes"].values()}
    for n in list(graph["nodes"].values()):
        for key in list(n["props"].keys()):
            p = n["props"][key]
            cval = canonical_name(str(p.get("value", "")), dictionary)
            target_id = name_index.get(cval)
            if target_id and target_id != n["id"]:
                upsert_edge(graph, n["id"], target_id, key,
                            domains=n.get("domains", []),
                            source_id=p.get("source_id", ""), create_date=p.get("as_of", ""),
                            lane=p.get("lane", "STRUCTURED"))
                del n["props"][key]


def embed_nodes(graph):
    """Optional: node embeddings from 'name (type) [domains] aliases'.
    Requires an embedding API key; failures leave nodes without embeddings
    (retrieval then falls back to lexical linking)."""
    done, failed = 0, 0
    for n in graph["nodes"].values():
        base = f'{n["name"]} ({n.get("type","")}) [{" ".join(n.get("domains",[]))}] {" ".join(n.get("aliases",[]))}'
        try:
            vec = dmu.embed_text(base)
            if vec:
                n["embedding"] = vec
                done += 1
        except Exception:
            failed += 1
    return {"embedded": done, "failed": failed}


def build_graph(graph_dir, use_llm=False, embed=False, llm_agent_file="agent_67GraphExtract.json"):
    """Full build from mapping.json + dictionary.json. Returns a report dict."""
    mapping = dmu.read_json_file(str(Path(graph_dir) / "mapping.json")) or {}
    dictionary = load_dictionary(graph_dir)
    sep = mapping.get("MULTI_VALUE_SEPARATOR", ";")
    graph = {"nodes": {}, "edges": []}

    report = {"graph_name": mapping.get("GRAPH_NAME", ""), "sources": []}
    ingest_seeds(graph, dictionary)

    llm_extractor = None
    if use_llm:
        import DigiM_Agent as dma
        def llm_extractor(prompt):
            return dma.ext_generate_pureLLM(llm_agent_file, prompt)

    for source in mapping.get("SOURCES", []):
        lane = source.get("LANE", "STRUCTURED")
        if lane == "STRUCTURED":
            report["sources"].append(ingest_structured_source(graph, dictionary, graph_dir, source, sep))
        else:
            report["sources"].append(ingest_text_source(graph, dictionary, graph_dir, source, llm_extractor, sep))

    promote_props_to_edges(graph, dictionary)
    if embed:
        report["embedding"] = embed_nodes(graph)

    report["nodes"] = len(graph["nodes"])
    report["edges"] = len(graph["edges"])
    report["path"] = save_graph(graph_dir, graph)
    return report


# -------------------------------------------------------------- retrieval --
def _adjacency(graph):
    adj = {}
    for i, e in enumerate(graph["edges"]):
        adj.setdefault(e["source"], []).append(i)
        adj.setdefault(e["target"], []).append(i)
    return adj


def link_entities(query, graph, dictionary, query_vecs=None, top_k=4, sim_threshold=0.45):
    """Seed selection: lexical first (aliases + names as substrings of the
    query), then embedding similarity when node embeddings and query vectors
    are both available."""
    seeds = {}
    mentions = dict(dictionary.get("aliases", {}))
    for n in graph["nodes"].values():
        mentions[n["name"]] = n["name"]
        for a in n.get("aliases", []):
            mentions.setdefault(a, n["name"])
    for mention, cname in mentions.items():
        if mention and mention in query:
            nid = node_id_for(canonical_name(cname, dictionary))
            if nid in graph["nodes"]:
                seeds[nid] = max(seeds.get(nid, 0.0), 1.0)  # lexical hit = full confidence

    if query_vecs:
        scored = []
        for n in graph["nodes"].values():
            vec = n.get("embedding")
            if not vec:
                continue
            best = max((dmu.calculate_similarity_vec(qv, vec, "Cosine") for qv in query_vecs if qv), default=0.0)
            if best >= sim_threshold:
                scored.append((best, n["id"]))
        for best, nid in sorted(scored, reverse=True)[:top_k]:
            seeds[nid] = max(seeds.get(nid, 0.0), round(best, 3))
    return seeds  # {node_id: confidence}


def detect_domains(query, graph):
    """Domains explicitly named in the query -> boost set."""
    all_domains = set()
    for n in graph["nodes"].values():
        all_domains.update(n.get("domains", []))
    for e in graph["edges"]:
        all_domains.update(e.get("domains", []))
    return {d for d in all_domains if d and d in query}


def _shortest_path_edges(graph, adj, src, dst, max_len):
    """BFS shortest path (undirected view). Returns list of edge indexes."""
    if src == dst:
        return []
    prev = {src: (None, None)}
    q = deque([(src, 0)])
    while q:
        cur, depth = q.popleft()
        if depth >= max_len:
            continue
        for ei in adj.get(cur, []):
            e = graph["edges"][ei]
            nxt = e["target"] if e["source"] == cur else e["source"]
            if nxt in prev:
                continue
            prev[nxt] = (cur, ei)
            if nxt == dst:
                path = []
                node = dst
                while prev[node][0] is not None:
                    path.append(prev[node][1])
                    node = prev[node][0]
                return list(reversed(path))
            q.append((nxt, depth + 1))
    return None


def _edge_score(edge, boost_domains, domain_bonus):
    score = 1.0
    if boost_domains and set(edge.get("domains", [])) & boost_domains:
        score *= domain_bonus
    return score


def search_graph(query, graph_dir, policy, query_vecs=None, meta_dates=None):
    """Core retrieval: paths between seeds (protected) + hop-ascending
    neighborhoods, capped by EDGE_LIMIT / FANOUT_LIMIT.
    Returns dict with seeds / paths / edges (selected) / domains."""
    graph = load_graph(graph_dir)
    dictionary = load_dictionary(graph_dir)
    adj = _adjacency(graph)

    hops = int(policy.get("HOPS", 2))
    edge_limit = int(policy.get("EDGE_LIMIT", 30))
    fanout_limit = int(policy.get("FANOUT_LIMIT", 5))
    domain_bonus = float(policy.get("DOMAIN_BONUS", 1.3))

    seeds = link_entities(query, graph, dictionary, query_vecs)
    boost_domains = detect_domains(query, graph)

    selected = []          # [(edge_index, hop, kind)]
    selected_set = set()

    # 1) Paths between every seed pair (protected allocation).
    seed_ids = list(seeds.keys())
    paths = []
    for i in range(len(seed_ids)):
        for j in range(i + 1, len(seed_ids)):
            p = _shortest_path_edges(graph, adj, seed_ids[i], seed_ids[j], max_len=hops * 2)
            if p:
                paths.append(p)
                for ei in p:
                    if ei not in selected_set and len(selected) < edge_limit:
                        selected.append((ei, 0, "path"))
                        selected_set.add(ei)

    # 2) Neighborhood expansion, hop by hop, with per-node fanout pruning.
    frontier = set(seed_ids)
    visited = set(seed_ids)
    for hop in range(1, hops + 1):
        next_frontier = set()
        for nid in frontier:
            incident = adj.get(nid, [])
            ranked = sorted(
                incident,
                key=lambda ei: (-_edge_score(graph["edges"][ei], boost_domains, domain_bonus),
                                graph["edges"][ei].get("create_date", "")),
            )[:fanout_limit]
            for ei in ranked:
                e = graph["edges"][ei]
                other = e["target"] if e["source"] == nid else e["source"]
                if ei not in selected_set and len(selected) < edge_limit:
                    selected.append((ei, hop, "neighbor"))
                    selected_set.add(ei)
                if other not in visited:
                    next_frontier.add(other)
                    visited.add(other)
        frontier = next_frontier
        if len(selected) >= edge_limit:
            break

    return {"graph": graph, "seeds": seeds, "paths": paths,
            "selected": selected, "boost_domains": boost_domains}


# ----------------------------------------------------- context assembly ----
def _props_inline(props, max_items=3):
    items = [f'{k}:{v.get("value","")}' for k, v in list(props.items())[:max_items] if v.get("value")]
    return f' ({", ".join(items)})' if items else ""


def _render_edge(graph, edge, template):
    src = graph["nodes"].get(edge["source"], {}).get("name", edge["source"])
    dst = graph["nodes"].get(edge["target"], {}).get("name", edge["target"])
    date = f' ({edge.get("create_date","")[:7]})' if edge.get("create_date") else ""
    return template.format(subject=src, relation=edge["relation"] + _props_inline(edge.get("props", {})),
                           object=dst, description="", date=date)


# ------------------------------------------------------- usage analysis ----
def link_output(text, graph, dictionary, min_mention_len=2):
    """Match a *generated response* back onto the graph (lexical, zero-API).

    Returns:
      nodes : {node_id: mention_count}   (name + alias occurrences summed)
      edges : [{"index": i, "freq": n, "predicate_match": bool}]
              An edge counts as "used in the output" when BOTH endpoint
              nodes are mentioned (co-occurrence rule). freq is the weaker
              endpoint's count; predicate_match flags when the relation
              string itself also appears in the text.
    """
    text = text or ""
    node_counts = {}
    mention_map = {}  # mention string -> node_id
    for n in graph["nodes"].values():
        mention_map[n["name"]] = n["id"]
        for a in n.get("aliases", []):
            mention_map.setdefault(a, n["id"])
    for mention, cname in dictionary.get("aliases", {}).items():
        nid = node_id_for(cname)
        if nid in graph["nodes"]:
            mention_map.setdefault(mention, nid)

    for mention, nid in mention_map.items():
        if len(mention) < min_mention_len:
            continue
        c = text.count(mention)
        if c:
            node_counts[nid] = node_counts.get(nid, 0) + c

    edge_hits = []
    for i, e in enumerate(graph["edges"]):
        cs = node_counts.get(e["source"], 0)
        ct = node_counts.get(e["target"], 0)
        if cs and ct:
            edge_hits.append({
                "index": i,
                "freq": min(cs, ct),
                "predicate_match": bool(e.get("relation")) and e["relation"] in text,
            })
    return {"nodes": node_counts, "edges": edge_hits}


def analyze_graph_usage(query, response_text, rag, query_vecs=None):
    """On-demand per-turn usage analysis for Knowledge Utility.

    Recomputes the (deterministic, lexical) retrieval for `query` and links
    `response_text` back onto the graph, then diffs the two:

      seeds           : query-linked seed node ids
      retrieved_nodes : node ids touched by the retrieval (seeds + endpoints)
      retrieved_edges : edge indexes selected by the retrieval
      output_nodes    : {node_id: mention count in the response}
      output_edges    : [{"index", "freq", "predicate_match"}]
      missed_nodes    : in the output but NOT retrieved  (coverage gap = red)
      missed_edges    : same, for edges

    Needs only the session log's (query, response) pair — no runtime
    recording. Note: results reflect the *current* graph; if the graph was
    rebuilt since the turn, the replayed retrieval may differ slightly.
    """
    data_list = [d for d in rag.get("DATA", []) if d.get("DATA_TYPE") == "GRAPH"]
    if not data_list:
        return None
    graph_dir = resolve_graph_dir(data_list[0]["DATA_NAME"])
    result = search_graph(query, graph_dir, rag, query_vecs=query_vecs)
    graph = result["graph"]
    dictionary = load_dictionary(graph_dir)

    retrieved_edges = {ei for ei, _hop, _kind in result["selected"]}
    retrieved_nodes = set(result["seeds"].keys())
    for ei in retrieved_edges:
        e = graph["edges"][ei]
        retrieved_nodes.add(e["source"])
        retrieved_nodes.add(e["target"])

    out = link_output(response_text, graph, dictionary)
    missed_nodes = [nid for nid in out["nodes"] if nid not in retrieved_nodes]
    missed_edges = [h for h in out["edges"] if h["index"] not in retrieved_edges]

    return {
        "graph": graph,
        "graph_dir": graph_dir,
        "seeds": list(result["seeds"].keys()),
        "paths": result["paths"],
        "retrieved_nodes": sorted(retrieved_nodes),
        "retrieved_edges": sorted(retrieved_edges),
        "output_nodes": out["nodes"],
        "output_edges": out["edges"],
        "missed_nodes": missed_nodes,
        "missed_edges": missed_edges,
        "boost_domains": sorted(result["boost_domains"]),
    }


def build_graph_context(query, rag, exec_info=None, query_vecs=None, meta_searches=None):
    """Entry point used by DigiM_Context.create_rag_context (RETRIEVER='Graph').
    Returns (rag_context, rag_selected) in the same shape the Vector /
    PageIndex paths produce: context string + list of log-format strings."""
    data_list = [d for d in rag.get("DATA", []) if d.get("DATA_TYPE") == "GRAPH"]
    if not data_list:
        return "", []

    header = rag.get("HEADER_TEMPLATE", "以下はあなたの知識グラフから取得した関連構造です。\n")
    path_tpl = rag.get("PATH_TEMPLATE", "・{path}\n")
    edge_tpl = rag.get("EDGE_TEMPLATE", "・({subject}) --[{relation}]--> ({object}){date}\n")
    log_tpl = rag.get("LOG_TEMPLATE",
        "'rag':'{rag_name}', 'DB': 'Graph', 'QUERY_SEQ': '{query_seq}', 'QUERY_MODE': '{query_mode}', "
        "'ID': '{id}', 'similarity_Q': {similarity_prompt}, 'similarity_A': {similarity_response}, "
        "'relation': '{relation}', 'text_short': '{text_short}'")
    props_limit = int(rag.get("PROPS_LIMIT", 5))

    rag_context = ""
    rag_selected = []

    for rd in data_list:
        graph_dir = resolve_graph_dir(rd["DATA_NAME"])
        result = search_graph(query, graph_dir, rag, query_vecs=query_vecs)
        graph = result["graph"]
        if not result["selected"]:
            continue

        query_mode = "(GRAPH:local"
        if result["boost_domains"]:
            query_mode += "+domain:" + "/".join(sorted(result["boost_domains"]))
        query_mode += ")"

        block = header

        # ■経路 — follow BFS edge order, orienting each edge relative to the
        # previous node in the walk: (A) --[r]--> (B) <--[r]-- (C) …
        path_lines = []
        for p in result["paths"]:
            walk = []
            prev_node = None
            for idx, ei in enumerate(p):
                e = graph["edges"][ei]
                sname = graph["nodes"].get(e["source"], {}).get("name", "")
                dname = graph["nodes"].get(e["target"], {}).get("name", "")
                if idx == 0:
                    # find shared node with next edge to determine start
                    if len(p) > 1:
                        e2 = graph["edges"][p[1]]
                        shared = {e["source"], e["target"]} & {e2["source"], e2["target"]}
                        start = ({e["source"], e["target"]} - shared).pop() if shared else e["source"]
                    else:
                        start = e["source"]
                    prev_node = start
                    walk.append(f"({graph['nodes'].get(start, {}).get('name', '')})")
                rel = e["relation"] + _props_inline(e.get("props", {}))
                if e["source"] == prev_node:
                    walk.append(f" --[{rel}]--> ({dname})")
                    prev_node = e["target"]
                else:
                    walk.append(f" <--[{rel}]-- ({sname})")
                    prev_node = e["source"]
            path_lines.append(path_tpl.format(path="".join(walk)))
        if path_lines:
            block += "■経路（質問に関わるつながり）\n" + "".join(dict.fromkeys(path_lines))

        # ■関係（近傍・path外のエッジ）
        rel_lines = []
        for ei, hop, kind in result["selected"]:
            if kind == "path":
                continue
            rel_lines.append(_render_edge(graph, graph["edges"][ei], edge_tpl))
        if rel_lines:
            block += "■関係（近傍・関連度順）\n" + "".join(rel_lines)

        # ■状態（シードノードのみ）
        state_lines = []
        for nid in result["seeds"]:
            node = graph["nodes"].get(nid, {})
            props = {k: v for k, v in node.get("props", {}).items() if v.get("value")}
            if props:
                items = [f'{k}={v["value"]}' for k, v in list(props.items())[:props_limit]]
                state_lines.append(f'・{node.get("name","")}: {", ".join(items)}\n')
        if state_lines:
            block += "■主要エンティティの状態\n" + "".join(state_lines)

        rag_context += block + "\n"

        # References (legacy string log entries, PageIndex-style).
        for ei, hop, kind in result["selected"]:
            e = graph["edges"][ei]
            sname = graph["nodes"].get(e["source"], {}).get("name", "")
            dname = graph["nodes"].get(e["target"], {}).get("name", "")
            try:
                rag_selected.append(log_tpl.format(
                    rag_name=rag.get("RAG_NAME", ""),
                    query_seq="0", query_mode=query_mode,
                    id=f'{e["source"]}->{e["target"]}',
                    similarity_prompt=0.0, similarity_response=0.0,
                    relation=e["relation"],
                    text_short=f'({sname}) --[{e["relation"]}]--> ({dname})'[:50],
                ))
            except (KeyError, IndexError):
                rag_selected.append(f"'rag':'{rag.get('RAG_NAME','')}', 'QUERY_MODE': '{query_mode}', "
                                    f"'text_short': '({sname}) --[{e['relation']}]--> ({dname})'")

    return rag_context, rag_selected
