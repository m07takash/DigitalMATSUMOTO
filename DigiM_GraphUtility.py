# DigiM_GraphUtility.py
# ============================================================================
# Knowledge Utility renderer for GraphRAG usage analysis.
#
# Renders the WHOLE graph with per-turn usage overlays as a self-contained
# SVG (pure Python: deterministic spring layout, no JS / no external libs),
# plus the text tables shown under the figure. Works identically in the
# Streamlit WebUI, the sample demo, and offline tests.
#
# Two views over DigiM_Graph.analyze_graph_usage(...) output:
#
#   view="retrieval"  … 検索ビュー
#     grey       : graph background (untouched nodes / edges)
#     blue       : nodes & edges selected by this turn's retrieval
#     skyblue    : seed nodes linked from the query
#
#   view="generation" … 生成ビュー
#     grey       : background
#     blue→skyblue gradient : nodes & edges actually used in the AI output
#                             (mention frequency; max freq = skyblue)
#     red        : in the output but NOT retrieved this turn (coverage gap)
#
# Streamlit wiring (Knowledge Utility):
#     import DigiM_Graph as dmg, DigiM_GraphUtility as dgu
#     usage = dmg.analyze_graph_usage(query, response_text, rag_entry)
#     st.markdown(dgu.render_usage_svg(usage, view="retrieval"),
#                 unsafe_allow_html=True)
#     st.dataframe(dgu.usage_tables(usage, view="retrieval")["edges"])
# ============================================================================

import hashlib
import math
import html

# --- color spec (kept in one place; matches the agreed design) --------------
COL_BG_NODE   = "#d9d9d9"
COL_BG_EDGE   = "#c9c9c9"
COL_BLUE      = "#1f4fd8"   # retrieved / low-frequency output
COL_SKYBLUE   = "#7ec8ff"   # seeds / high-frequency output
COL_RED       = "#d33a3a"   # in output but not retrieved (coverage gap)
COL_TEXT      = "#20242e"
COL_TEXT_DIM  = "#8a8f98"


# ------------------------------------------------------------------ layout --
def spring_layout(graph, iterations=80, width=1.0, height=1.0):
    """Deterministic force-directed layout (Fruchterman–Reingold style).
    Initial positions derive from md5(node id), so the same graph always
    lays out the same way — no RNG, reproducible across sessions."""
    nodes = list(graph["nodes"].keys())
    n = len(nodes)
    if n == 0:
        return {}
    pos = {}
    for nid in nodes:
        h = hashlib.md5(nid.encode()).hexdigest()
        pos[nid] = [int(h[:8], 16) / 0xFFFFFFFF, int(h[8:16], 16) / 0xFFFFFFFF]

    adj = [(e["source"], e["target"]) for e in graph["edges"]
           if e["source"] in pos and e["target"] in pos]
    k = math.sqrt((width * height) / n)
    t = 0.12  # initial temperature

    for it in range(iterations):
        disp = {nid: [0.0, 0.0] for nid in nodes}
        # repulsion (all pairs — fine for the hundreds-of-nodes scale)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = nodes[i], nodes[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d = math.sqrt(dx * dx + dy * dy) or 1e-6
                f = (k * k / d) * 0.05
                disp[a][0] += dx / d * f; disp[a][1] += dy / d * f
                disp[b][0] -= dx / d * f; disp[b][1] -= dy / d * f
        # attraction along edges
        for a, b in adj:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            d = math.sqrt(dx * dx + dy * dy) or 1e-6
            f = (d * d / k) * 0.05
            disp[a][0] -= dx / d * f; disp[a][1] -= dy / d * f
            disp[b][0] += dx / d * f; disp[b][1] += dy / d * f
        # apply with cooling
        for nid in nodes:
            dx, dy = disp[nid]
            d = math.sqrt(dx * dx + dy * dy) or 1e-6
            step = min(d, t)
            pos[nid][0] = min(1.0, max(0.0, pos[nid][0] + dx / d * step))
            pos[nid][1] = min(1.0, max(0.0, pos[nid][1] + dy / d * step))
        t *= 0.96
    return pos


# -------------------------------------------------------------- coloring ---
def _lerp_color(c1, c2, ratio):
    """Hex color interpolation c1→c2 (ratio 0..1)."""
    r = max(0.0, min(1.0, ratio))
    a = [int(c1[i:i+2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a[i] + (b[i]-a[i]) * r):02x}" for i in range(3))


def _freq_color(freq, max_freq):
    """blue → skyblue gradient by output-mention frequency."""
    if max_freq <= 1:
        return COL_SKYBLUE if freq >= 1 else COL_BLUE
    return _lerp_color(COL_BLUE, COL_SKYBLUE, (freq - 1) / (max_freq - 1))


def _node_style(nid, usage, view):
    """(fill, stroke, radius, emphasized?) for one node."""
    if view == "retrieval":
        if nid in set(usage["seeds"]):
            return (COL_SKYBLUE, COL_BLUE, 11, True)
        if nid in set(usage["retrieved_nodes"]):
            return (COL_BLUE, COL_BLUE, 9, True)
    else:  # generation
        freq = usage["output_nodes"].get(nid, 0)
        if freq:
            if nid in set(usage["missed_nodes"]):
                return (COL_RED, COL_RED, 10, True)
            max_freq = max(usage["output_nodes"].values() or [1])
            return (_freq_color(freq, max_freq), COL_BLUE, 9 + min(3, freq), True)
    return (COL_BG_NODE, COL_BG_NODE, 7, False)


def _edge_style(ei, usage, view):
    """(stroke, width, emphasized?) for one edge index."""
    if view == "retrieval":
        if ei in set(usage["retrieved_edges"]):
            return (COL_BLUE, 2.4, True)
    else:
        hit = next((h for h in usage["output_edges"] if h["index"] == ei), None)
        if hit:
            if any(h["index"] == ei for h in usage["missed_edges"]):
                return (COL_RED, 2.4, True)
            max_freq = max((h["freq"] for h in usage["output_edges"]), default=1)
            return (_freq_color(hit["freq"], max_freq), 2.4, True)
    return (COL_BG_EDGE, 1.0, False)


# ------------------------------------------------------------------- svg ---
def render_usage_svg(usage, view="retrieval", width=880, height=560, font_size=11):
    """Whole-graph SVG with the usage overlay for one view.
    Returns an SVG string (embed via st.markdown(..., unsafe_allow_html=True)
    or save to a file)."""
    graph = usage["graph"]
    pos = spring_layout(graph)
    pad = 60

    def sx(nid): return pad + pos[nid][0] * (width - 2 * pad)
    def sy(nid): return pad + pos[nid][1] * (height - 2 * pad)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" style="background:#ffffff;font-family:sans-serif">']

    # edges first (emphasized ones on top of grey ones)
    grey_edges, hot_edges = [], []
    for ei, e in enumerate(graph["edges"]):
        if e["source"] not in pos or e["target"] not in pos:
            continue
        stroke, w, emph = _edge_style(ei, usage, view)
        x1, y1, x2, y2 = sx(e["source"]), sy(e["source"]), sx(e["target"]), sy(e["target"])
        line = (f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                f'stroke="{stroke}" stroke-width="{w}">'
                f'<title>{html.escape(e["relation"])}</title></line>')
        (hot_edges if emph else grey_edges).append((line, ei, emph))
        if emph:
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            hot_edges.append((f'<text x="{mx:.0f}" y="{my - 4:.0f}" font-size="{font_size - 2}" '
                              f'fill="{stroke}" text-anchor="middle">{html.escape(e["relation"])}</text>',
                              ei, emph))
    parts += [l for l, _, _ in grey_edges]
    parts += [l for l, _, _ in hot_edges]

    # nodes (grey first, highlighted on top)
    grey_nodes, hot_nodes = [], []
    for nid, n in graph["nodes"].items():
        fill, stroke, r, emph = _node_style(nid, usage, view)
        x, y = sx(nid), sy(nid)
        label_fill = COL_TEXT if emph else COL_TEXT_DIM
        weight = "600" if emph else "400"
        g = (f'<g><circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{fill}" '
             f'stroke="{stroke}" stroke-width="1.5"><title>{html.escape(n["name"])} '
             f'({html.escape(n.get("type", ""))})</title></circle>'
             f'<text x="{x:.0f}" y="{y + r + font_size:.0f}" font-size="{font_size}" '
             f'fill="{label_fill}" font-weight="{weight}" text-anchor="middle">'
             f'{html.escape(n["name"])}</text></g>')
        (hot_nodes if emph else grey_nodes).append(g)
    parts += grey_nodes + hot_nodes

    # legend (white backing plate so it never collides with graph elements)
    if view == "retrieval":
        legend = [(COL_SKYBLUE, "シード（クエリで選択）"), (COL_BLUE, "検索で抽出"), (COL_BG_NODE, "未使用")]
    else:
        legend = [(COL_BLUE, "出力に使用（低頻度）"), (COL_SKYBLUE, "出力に使用（高頻度）"),
                  (COL_RED, "出力にあるが未検索"), (COL_BG_NODE, "未使用")]
    plate_h = len(legend) * 20 + 12
    parts.append(f'<rect x="6" y="4" width="200" height="{plate_h}" rx="6" '
                 f'fill="#ffffff" fill-opacity="0.92" stroke="#e3e4e0"/>')
    lx, ly = 18, 22
    for color, label in legend:
        parts.append(f'<circle cx="{lx}" cy="{ly}" r="6" fill="{color}"/>')
        parts.append(f'<text x="{lx + 12}" y="{ly + 4}" font-size="{font_size}" fill="{COL_TEXT}">{label}</text>')
        ly += 20
    parts.append("</svg>")
    return "".join(parts)


# ----------------------------------------------------------------- tables --
def usage_tables(usage, view="retrieval"):
    """Text lists shown under the figure. Returns {'nodes': [...], 'edges': [...]}
    as list-of-dict rows (st.dataframe-ready)."""
    graph = usage["graph"]
    seeds = set(usage["seeds"])
    retrieved_n = set(usage["retrieved_nodes"])
    retrieved_e = set(usage["retrieved_edges"])
    missed_n = set(usage["missed_nodes"])
    missed_ei = {h["index"] for h in usage["missed_edges"]}

    def node_name(nid):
        return graph["nodes"].get(nid, {}).get("name", nid)

    def triple(ei):
        e = graph["edges"][ei]
        return f'({node_name(e["source"])}) --[{e["relation"]}]--> ({node_name(e["target"])})'

    nodes_rows, edges_rows = [], []
    if view == "retrieval":
        for nid in usage["retrieved_nodes"]:
            n = graph["nodes"].get(nid, {})
            nodes_rows.append({
                "区分": "シード" if nid in seeds else "抽出",
                "エンティティ": n.get("name", nid),
                "型": n.get("type", ""),
                "ドメイン": " / ".join(n.get("domains", [])),
            })
        for ei in usage["retrieved_edges"]:
            edges_rows.append({"区分": "抽出", "エッジ": triple(ei),
                               "ドメイン": " / ".join(graph["edges"][ei].get("domains", []))})
    else:
        for nid, freq in sorted(usage["output_nodes"].items(), key=lambda x: -x[1]):
            n = graph["nodes"].get(nid, {})
            nodes_rows.append({
                "区分": "未検索(赤)" if nid in missed_n else "出力に使用",
                "エンティティ": n.get("name", nid),
                "頻度": freq,
                "検索でも抽出": "Y" if nid in retrieved_n else "N",
            })
        for h in sorted(usage["output_edges"], key=lambda x: -x["freq"]):
            edges_rows.append({
                "区分": "未検索(赤)" if h["index"] in missed_ei else "出力に使用",
                "エッジ": triple(h["index"]),
                "頻度": h["freq"],
                "述語一致": "Y" if h.get("predicate_match") else "N",
                "検索でも抽出": "Y" if h["index"] in retrieved_e else "N",
            })
    return {"nodes": nodes_rows, "edges": edges_rows}


# -------------------------------------------------------------- preview ----
def save_preview_html(usage, out_path, title="Graph Utility Preview"):
    """Both views + tables in one standalone HTML file (offline check /
    sharing). Not used by the WebUI, which composes the pieces itself."""
    def table_html(rows):
        if not rows:
            return "<p style='color:#888'>（該当なし）</p>"
        cols = list(rows[0].keys())
        head = "".join(f"<th>{html.escape(str(c))}</th>" for c in cols)
        body = "".join("<tr>" + "".join(f"<td>{html.escape(str(r.get(c, '')))}</td>" for c in cols) + "</tr>"
                       for r in rows)
        return (f"<table border='0' cellspacing='0' style='border-collapse:collapse;font-size:13px'>"
                f"<tr style='color:#667;text-align:left'>{head}</tr>{body}</table>"
                "<style>td,th{padding:4px 10px;border-bottom:1px solid #e3e4e0}</style>")

    sections = []
    for view, label in (("retrieval", "検索ビュー"), ("generation", "生成ビュー")):
        t = usage_tables(usage, view)
        sections.append(
            f"<h2 style='font-family:sans-serif'>{label}</h2>"
            + render_usage_svg(usage, view)
            + "<h3 style='font-family:sans-serif'>ノード</h3>" + table_html(t["nodes"])
            + "<h3 style='font-family:sans-serif'>エッジ</h3>" + table_html(t["edges"]))
    doc = (f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
           f"<body style='max-width:960px;margin:24px auto'>" + "".join(sections) + "</body>")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return out_path
