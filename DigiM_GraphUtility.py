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
#   view="retrieval"  ... retrieval view
#     grey       : graph background (untouched nodes / edges)
#     blue       : nodes & edges selected by this turn's retrieval
#     skyblue    : seed nodes linked from the query
#
#   view="generation" ... generation view
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
def render_usage_svg(usage, view="retrieval", width=880, height=560, font_size=11,
                       show_legend=True):
    """Whole-graph SVG with the usage overlay for one view.
    Returns an SVG string (embed via st.markdown(..., unsafe_allow_html=True)
    or save to a file). Pass `show_legend=False` to omit the inline plate
    when the caller renders a legend outside the figure via
    `usage_legend_html(view)`."""
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

    # Optional inline legend (white backing plate). Callers that render an
    # external legend via `usage_legend_html(view)` should pass show_legend=False.
    if show_legend:
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


# ================================================================ unified ==
# Unified view merging retrieval + generation into one image. Base coloring
# is the generation view (high freq = skyblue / low freq = blue / surfaced
# but not retrieved = red / unused = grey). Nodes/edges that WERE retrieved
# but not touched in generation are added in translucent BLUE (opacity 0.5).
# Seeds get an underline on the label and are also listed as chips in a
# horizontal row below the graph.
# ---------------------------------------------------------------------------

# Precedence of the 5 states (highest first): missed → output-high → output-low
# → search-only → untouched. Returned tuple is (fill, stroke, fill_opacity,
# stroke_opacity, radius, emphasized?).
def _unified_node_style(nid, usage):
    max_freq = max(usage["output_nodes"].values() or [1])
    freq = usage["output_nodes"].get(nid, 0)
    missed_set = set(usage["missed_nodes"])
    retrieved_set = set(usage["retrieved_nodes"])
    if freq:
        if nid in missed_set:
            return (COL_RED, COL_RED, 1.0, 1.0, 10, "missed")
        fill = _freq_color(freq, max_freq)
        return (fill, COL_BLUE, 1.0, 1.0, 9 + min(3, freq),
                "hi" if freq >= max_freq else "lo")
    if nid in retrieved_set:
        return (COL_BLUE, COL_BLUE, 0.5, 0.5, 8, "search")
    return (COL_BG_NODE, COL_BG_NODE, 1.0, 1.0, 7, "bg")


def _unified_edge_style(ei, usage):
    hit = next((h for h in usage["output_edges"] if h["index"] == ei), None)
    missed_e = {h["index"] for h in usage["missed_edges"]}
    if hit:
        if ei in missed_e:
            return (COL_RED, 2.4, 1.0, "missed")
        max_freq = max((h["freq"] for h in usage["output_edges"]), default=1)
        return (_freq_color(hit["freq"], max_freq), 2.4, 1.0,
                "hi" if hit["freq"] >= max_freq else "lo")
    if ei in set(usage["retrieved_edges"]):
        return (COL_BLUE, 2.0, 0.5, "search")
    return (COL_BG_EDGE, 1.0, 1.0, "bg")


def render_unified_svg(usage, width=880, height=560, font_size=11,
                        show_legend=False, show_labels=True):
    """Unified retrieval+generation view. See _unified_node_style /
    _unified_edge_style for the color precedence. Seeds get an underlined
    label to distinguish them from other emphasized nodes. Callers should
    render the legend externally via `unified_legend_html()` and pass
    `show_legend=False` (the default).

    `show_labels=True` (default) draws every node / edge label inline.
    `show_labels=False` hides them by default and reveals a single label on
    hover — used when the graph carries sensitive / niche node names that
    shouldn't be visible during demos. Both modes still expose the label
    via a native SVG `<title>` tooltip on the circle, so accessibility
    (screen readers, browser hover) still works either way."""
    graph = usage["graph"]
    pos = spring_layout(graph)
    pad = 60
    seeds = set(usage.get("seeds") or [])

    def sx(nid): return pad + pos[nid][0] * (width - 2 * pad)
    def sy(nid): return pad + pos[nid][1] * (height - 2 * pad)

    # SVG-scoped CSS: when show_labels is off, hide the .gu-label class by
    # default and reveal only the one whose parent <g class="gu-item"> is
    # being hovered. Kept inside the SVG so it doesn't leak to the rest of
    # the page.
    hover_css = ""
    if not show_labels:
        hover_css = (
            '<style>'
            '.gu-label{opacity:0;pointer-events:none;transition:opacity 80ms}'
            '.gu-item:hover .gu-label{opacity:1}'
            '.gu-item:hover circle,.gu-item:hover line{stroke-width:2.4}'
            '</style>'
        )

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" viewBox="0 0 {width} {height}" '
             f'style="background:#ffffff;font-family:sans-serif;max-width:100%">',
             hover_css]

    label_cls = ' class="gu-label"' if not show_labels else ""

    # Edges: bg → search-only → emphasized (missed/output) so hot edges stay on top.
    _tier = {"bg": 0, "search": 1, "hi": 2, "lo": 2, "missed": 3}
    _tiered_edges = []
    for ei, e in enumerate(graph["edges"]):
        if e["source"] not in pos or e["target"] not in pos:
            continue
        stroke, w, opacity, tier = _unified_edge_style(ei, usage)
        x1, y1, x2, y2 = sx(e["source"]), sy(e["source"]), sx(e["target"]), sy(e["target"])
        # When hover-labels are on, each edge is a group so hover on the
        # line reveals its own label. When labels are always on, keep the
        # simpler line + optional label structure.
        line_inner = (f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
                      f'stroke="{stroke}" stroke-width="{w}" '
                      f'stroke-opacity="{opacity:.2f}">'
                      f'<title>{html.escape(e["relation"])}</title></line>')
        emph_label = ""
        if tier in ("hi", "lo", "missed"):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            emph_label = (f'<text{label_cls} x="{mx:.0f}" y="{my - 4:.0f}" '
                          f'font-size="{font_size - 2}" fill="{stroke}" '
                          f'text-anchor="middle">{html.escape(e["relation"])}</text>')
        if show_labels:
            grouped = line_inner
        else:
            grouped = f'<g class="gu-item">{line_inner}{emph_label}</g>'
            emph_label = ""  # label already inside the group
        _tiered_edges.append((_tier[tier], grouped, emph_label))
    _tiered_edges.sort(key=lambda t: t[0])
    for _, line, label in _tiered_edges:
        parts.append(line)
        if label:
            parts.append(label)

    # Nodes: same tiering — bg first, hot on top.
    _tiered_nodes = []
    for nid, n in graph["nodes"].items():
        if nid not in pos:
            continue
        fill, stroke, fop, sop, r, tier = _unified_node_style(nid, usage)
        x, y = sx(nid), sy(nid)
        emph = tier in ("hi", "lo", "search", "missed")
        label_fill = COL_TEXT if emph else COL_TEXT_DIM
        weight = "600" if emph else "400"
        text_deco = ' text-decoration="underline"' if nid in seeds else ""
        _group_cls = ' class="gu-item"' if not show_labels else ""
        g = (f'<g{_group_cls}><circle cx="{x:.0f}" cy="{y:.0f}" r="{r}" fill="{fill}" '
             f'stroke="{stroke}" stroke-width="1.5" '
             f'fill-opacity="{fop:.2f}" stroke-opacity="{sop:.2f}">'
             f'<title>{html.escape(n["name"])} ({html.escape(n.get("type", ""))})</title>'
             f'</circle>'
             f'<text{label_cls} x="{x:.0f}" y="{y + r + font_size:.0f}" font-size="{font_size}" '
             f'fill="{label_fill}" font-weight="{weight}" text-anchor="middle"'
             f'{text_deco}>{html.escape(n["name"])}</text></g>')
        _tiered_nodes.append((_tier[tier], g))
    _tiered_nodes.sort(key=lambda t: t[0])
    for _, g in _tiered_nodes:
        parts.append(g)

    if show_legend:
        # Optional inline legend (rarely used — Streamlit renders it externally).
        legend = [(COL_SKYBLUE, "出力に使用（高頻度）"),
                  (COL_BLUE,    "出力に使用（低頻度）"),
                  (COL_BLUE,    "出力で未使用 (半透明)"),
                  (COL_RED,     "出力にあるが未検索"),
                  (COL_BG_NODE, "未使用")]
        plate_h = len(legend) * 20 + 12
        parts.append(f'<rect x="6" y="4" width="220" height="{plate_h}" rx="6" '
                     f'fill="#ffffff" fill-opacity="0.92" stroke="#e3e4e0"/>')
        lx, ly = 18, 22
        for i, (color, label) in enumerate(legend):
            opac = 0.5 if i == 2 else 1.0
            parts.append(f'<circle cx="{lx}" cy="{ly}" r="6" fill="{color}" fill-opacity="{opac}"/>')
            parts.append(f'<text x="{lx + 12}" y="{ly + 4}" font-size="{font_size}" fill="{COL_TEXT}">{label}</text>')
            ly += 20
    parts.append("</svg>")
    return "".join(parts)


def unified_legend_html():
    """External-to-SVG legend for `render_unified_svg` — chips in the order
    requested (高頻度 → 低頻度 → 出力で未使用 → 出力にあるが未検索 → 未使用)
    plus a seed-underline marker chip."""
    # (fill_color, opacity, label)
    items = [
        (COL_SKYBLUE, 1.0, "出力に使用（高頻度）"),
        (COL_BLUE,    1.0, "出力に使用（低頻度）"),
        (COL_BLUE,    0.5, "出力で未使用"),
        (COL_RED,     1.0, "出力にあるが未検索"),
        (COL_BG_NODE, 1.0, "未使用"),
    ]
    chips = ""
    for c, opa, l in items:
        chips += (
            f'<span style="display:inline-flex;align-items:center;'
            f'margin:0 12px 6px 0;font-size:12px;color:{COL_TEXT};">'
            f'<span style="display:inline-block;width:12px;height:12px;'
            f'border-radius:50%;background:{c};opacity:{opa};'
            f'border:1px solid #8b90a0;margin-right:6px;"></span>{html.escape(l)}'
            f'</span>')
    # Seed underline marker (text with underline, not a circle)
    chips += (
        f'<span style="display:inline-flex;align-items:center;'
        f'margin:0 12px 6px 0;font-size:12px;color:{COL_TEXT};">'
        f'<span style="text-decoration:underline;font-weight:600;'
        f'margin-right:6px;">シード</span>'
        f'<span style="color:{COL_TEXT_DIM};">(グラフ上のラベルにアンダーライン)</span>'
        f'</span>')
    return f'<div style="padding:4px 0 8px 0;line-height:1.6;">{chips}</div>'


def graph_recall_scores(usage):
    """Compute the three per-turn Graph scores displayed in the Knowledge
    Utility summary:

      ① node_recall = |retrieved ∩ output_nodes| / |output_nodes|
                    = 1 - (missed_nodes / output_nodes)
      ② edge_recall = |retrieved ∩ output_edges| / |output_edges|
                    = 1 - (missed_edges / output_edges)
      ③ combined    = ① + ②   (undefined side counted as 0)

    node_recall / edge_recall are None when the output contains 0 items of
    that kind (nothing to hit — vacuous). The combined score always sums
    them by counting None as 0 so "the LLM didn't cite any edges" pulls
    combined down instead of quietly disappearing."""
    output_nodes = usage.get("output_nodes") or {}
    output_edges = usage.get("output_edges") or []
    missed_nodes = usage.get("missed_nodes") or []
    missed_edges = usage.get("missed_edges") or []

    if output_nodes:
        node_recall = 1.0 - (len(missed_nodes) / len(output_nodes))
    else:
        node_recall = None
    if output_edges:
        edge_recall = 1.0 - (len(missed_edges) / len(output_edges))
    else:
        edge_recall = None

    combined = (0.0 if node_recall is None else node_recall) \
             + (0.0 if edge_recall is None else edge_recall)
    return {
        "node_recall": node_recall,
        "edge_recall": edge_recall,
        "combined": combined,
        "output_node_count": len(output_nodes),
        "output_edge_count": len(output_edges),
        "missed_node_count": len(missed_nodes),
        "missed_edge_count": len(missed_edges),
    }


def seeds_chip_html(usage):
    """Horizontal chip row listing the final seed names below the graph.
    Returns '' when there are no seeds."""
    names = usage.get("seed_names") or []
    if not names:
        return ""
    chips = "".join(
        f'<span style="display:inline-block;padding:4px 10px;'
        f'background:{COL_SKYBLUE};color:{COL_TEXT};font-weight:600;'
        f'border-radius:14px;margin:0 6px 6px 0;font-size:12px;'
        f'border:1px solid {COL_BLUE};">'
        f'{html.escape(n)}</span>' for n in names
    )
    return (
        f'<div style="margin:6px 0 12px 0;">'
        f'<span style="color:{COL_TEXT_DIM};font-size:12px;margin-right:8px;">'
        f'シード ({len(names)} 件):</span>{chips}</div>'
    )


# --- unified table (HTML with per-row color + bold) ---
def _unified_row_color(state):
    """Map a unified-view state → text CSS color for tables."""
    if state == "missed":
        return COL_RED
    if state == "hi":
        return COL_SKYBLUE
    if state == "lo":
        return COL_BLUE
    if state == "search":
        return COL_BLUE  # half-alpha in the graph, but the table uses full alpha for legibility
    return COL_TEXT_DIM


def _classify_node_state(nid, usage):
    max_freq = max(usage["output_nodes"].values() or [1])
    freq = usage["output_nodes"].get(nid, 0)
    if freq:
        if nid in set(usage["missed_nodes"]):
            return "missed"
        return "hi" if freq >= max_freq else "lo"
    if nid in set(usage["retrieved_nodes"]):
        return "search"
    return "bg"


def _classify_edge_state(ei, usage, hit):
    if hit:
        if ei in {h["index"] for h in usage["missed_edges"]}:
            return "missed"
        max_freq = max((h["freq"] for h in usage["output_edges"]), default=1)
        return "hi" if hit["freq"] >= max_freq else "lo"
    if ei in set(usage["retrieved_edges"]):
        return "search"
    return "bg"


def unified_usage_tables_html(usage):
    """Return HTML for the node and edge tables where the entity/edge text
    is colored + bolded per the unified view state. `st.markdown(...,
    unsafe_allow_html=True)` renders this directly."""
    graph = usage["graph"]
    seeds = set(usage.get("seeds") or [])
    retrieved_n = set(usage["retrieved_nodes"])
    retrieved_e = set(usage["retrieved_edges"])
    output_n_freq = dict(usage["output_nodes"])
    output_e_map = {h["index"]: h for h in usage["output_edges"]}
    missed_n = set(usage["missed_nodes"])
    missed_ei = {h["index"] for h in usage["missed_edges"]}

    def _node_name(nid):
        return graph["nodes"].get(nid, {}).get("name", nid)

    # ---- nodes ----
    node_ids = list(dict.fromkeys(list(retrieved_n) + list(output_n_freq.keys())))
    node_rows = []
    for nid in node_ids:
        n = graph["nodes"].get(nid, {})
        state = _classify_node_state(nid, usage)
        node_rows.append({
            "nid": nid,
            "name": n.get("name", nid),
            "type": n.get("type", ""),
            "domains": " / ".join(n.get("domains", [])),
            "search": "seed" if nid in seeds else ("Y" if nid in retrieved_n else "N"),
            "gen_freq": int(output_n_freq.get(nid, 0)),
            "missed": nid in missed_n,
            "state": state,
        })
    node_rows.sort(key=lambda r: (0 if r["missed"] else 1, -r["gen_freq"], r["name"]))

    _n_head = "".join(f"<th>{h}</th>" for h in
                       ("Entity", "Type", "Domain", "Retrieval", "Gen freq", "Missed (red)"))
    _n_body = ""
    for r in node_rows:
        color = _unified_row_color(r["state"])
        deco = ";text-decoration:underline" if r["search"] == "seed" else ""
        name_cell = (f'<td style="color:{color};font-weight:700{deco}">'
                     f'{html.escape(r["name"])}</td>')
        _n_body += (
            f'<tr>{name_cell}'
            f'<td>{html.escape(r["type"])}</td>'
            f'<td>{html.escape(r["domains"])}</td>'
            f'<td>{html.escape(r["search"])}</td>'
            f'<td style="text-align:right">{r["gen_freq"]}</td>'
            f'<td>{"Y" if r["missed"] else "N"}</td></tr>'
        )
    nodes_table = (
        f'<div style="overflow-x:auto"><table style="border-collapse:collapse;'
        f'font-size:12px;width:100%;font-family:sans-serif">'
        f'<thead><tr style="text-align:left;color:{COL_TEXT_DIM};'
        f'border-bottom:1px solid #e3e4e0">{_n_head}</tr></thead>'
        f'<tbody>{_n_body or ""}</tbody>'
        f'<style>td,th{{padding:4px 10px;border-bottom:1px solid #f0f1f2}}</style>'
        f'</table></div>'
    ) if node_rows else "<p style='color:#888;font-size:12px'>（該当なし）</p>"

    # ---- edges ----
    edge_ids = list(dict.fromkeys(list(retrieved_e) + list(output_e_map.keys())))
    edge_rows = []
    for ei in edge_ids:
        e = graph["edges"][ei]
        hit = output_e_map.get(ei)
        state = _classify_edge_state(ei, usage, hit)
        edge_rows.append({
            "ei": ei,
            "text": f'({_node_name(e["source"])}) --[{e.get("relation","")}]--> ({_node_name(e["target"])})',
            "domains": " / ".join(e.get("domains", [])),
            "search": "Y" if ei in retrieved_e else "N",
            "gen_freq": int(hit["freq"]) if hit else 0,
            "pmatch": "Y" if (hit and hit.get("predicate_match")) else "N",
            "missed": ei in missed_ei,
            "state": state,
        })
    edge_rows.sort(key=lambda r: (0 if r["missed"] else 1, -r["gen_freq"], r["text"]))

    _e_head = "".join(f"<th>{h}</th>" for h in
                       ("Edge", "Domain", "Retrieval", "Gen freq", "Predicate match", "Missed (red)"))
    _e_body = ""
    for r in edge_rows:
        color = _unified_row_color(r["state"])
        edge_cell = (f'<td style="color:{color};font-weight:700">'
                     f'{html.escape(r["text"])}</td>')
        _e_body += (
            f'<tr>{edge_cell}'
            f'<td>{html.escape(r["domains"])}</td>'
            f'<td>{html.escape(r["search"])}</td>'
            f'<td style="text-align:right">{r["gen_freq"]}</td>'
            f'<td>{html.escape(r["pmatch"])}</td>'
            f'<td>{"Y" if r["missed"] else "N"}</td></tr>'
        )
    edges_table = (
        f'<div style="overflow-x:auto"><table style="border-collapse:collapse;'
        f'font-size:12px;width:100%;font-family:sans-serif">'
        f'<thead><tr style="text-align:left;color:{COL_TEXT_DIM};'
        f'border-bottom:1px solid #e3e4e0">{_e_head}</tr></thead>'
        f'<tbody>{_e_body or ""}</tbody>'
        f'<style>td,th{{padding:4px 10px;border-bottom:1px solid #f0f1f2}}</style>'
        f'</table></div>'
    ) if edge_rows else "<p style='color:#888;font-size:12px'>（該当なし）</p>"

    return {"nodes_html": nodes_table, "edges_html": edges_table}


def render_unified_png(usage, width=880, height=560, dpi=150,
                        show_labels=True):
    """PNG rendering of the unified view via matplotlib. Same color scheme
    as render_unified_svg. Returns raw PNG bytes suitable for
    st.download_button. matplotlib is already a project dependency so no
    new install is needed.

    `show_labels=False` produces a labels-hidden variant used when the
    graph carries sensitive names (e.g. a personal Identity DB during
    demos). Nodes / edges are still drawn — just the text is omitted."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import rcParams
    # Same CJK font the analytics modules use — avoids ▯ boxes on non-ASCII labels
    rcParams["font.family"] = "Noto Sans CJK JP"

    graph = usage["graph"]
    pos = spring_layout(graph)
    seeds = set(usage.get("seeds") or [])
    if not pos:
        # Empty graph — still return a valid PNG rather than raise
        fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
        buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
        return buf.getvalue()

    pad_frac = 0.06
    def sx(nid): return pad_frac + pos[nid][0] * (1 - 2 * pad_frac)
    def sy(nid): return 1 - (pad_frac + pos[nid][1] * (1 - 2 * pad_frac))  # flip Y for image-like display

    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.set_facecolor("#ffffff")

    # Edges (tier-ordered so hot ones sit on top)
    _tier = {"bg": 0, "search": 1, "hi": 2, "lo": 2, "missed": 3}
    ordered_edges = []
    for ei, e in enumerate(graph["edges"]):
        if e["source"] not in pos or e["target"] not in pos:
            continue
        stroke, w, opacity, tier = _unified_edge_style(ei, usage)
        ordered_edges.append((_tier[tier], ei, e, stroke, w, opacity, tier))
    ordered_edges.sort(key=lambda t: t[0])
    for _, ei, e, stroke, w, opacity, tier in ordered_edges:
        x1, y1 = sx(e["source"]), sy(e["source"])
        x2, y2 = sx(e["source"]) + 0, sy(e["source"]) + 0  # placeholder; overwritten below
        x2, y2 = sx(e["target"]), sy(e["target"])
        ax.plot([x1, x2], [y1, y2], color=stroke, linewidth=w, alpha=opacity, zorder=1 + _tier[tier])
        if show_labels and tier in ("hi", "lo", "missed"):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            ax.text(mx, my + 0.008, e.get("relation", ""),
                    ha="center", va="bottom", fontsize=6, color=stroke,
                    zorder=10)

    # Nodes
    ordered_nodes = []
    for nid, n in graph["nodes"].items():
        if nid not in pos:
            continue
        fill, stroke, fop, sop, r, tier = _unified_node_style(nid, usage)
        ordered_nodes.append((_tier[tier], nid, n, fill, stroke, fop, sop, r, tier))
    ordered_nodes.sort(key=lambda t: t[0])
    for _, nid, n, fill, stroke, fop, sop, r, tier in ordered_nodes:
        x, y = sx(nid), sy(nid)
        size = (r * 5) ** 1.4
        ax.scatter([x], [y], s=size, c=fill, edgecolors=stroke, linewidths=1.2,
                    alpha=fop, zorder=5 + _tier[tier])
        if not show_labels:
            continue  # sensitive-name demo mode — skip node labels entirely
        emph = tier in ("hi", "lo", "search", "missed")
        label_color = COL_TEXT if emph else COL_TEXT_DIM
        label_weight = "bold" if emph else "normal"
        label_kwargs = dict(ha="center", va="top", fontsize=7,
                              color=label_color, weight=label_weight,
                              zorder=11)
        # Seeds get underline via a TextPath — matplotlib text-decoration is not
        # supported directly, so approximate by drawing an underline segment
        # below the label bounds after placing the text.
        text = ax.text(x, y - 0.02, n.get("name", nid), **label_kwargs)
        if nid in seeds:
            # Approximate underline: use text renderer to get the extent (in
            # display coords) → convert back to data coords → draw a segment.
            try:
                fig.canvas.draw()
                bb = text.get_window_extent()
                inv = ax.transData.inverted()
                (x0, y0), (x1v, y1v) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y0)])
                ax.plot([x0, x1v], [y0 - 0.005, y0 - 0.005],
                        color=label_color, linewidth=0.8, zorder=12)
            except Exception:
                pass  # underline is nice-to-have; not worth failing the render

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches=None, pad_inches=0,
                 facecolor="#ffffff")
    plt.close(fig)
    return buf.getvalue()


def usage_legend_html(view="retrieval"):
    """External-to-SVG legend for `render_usage_svg` — a compact HTML chip
    row callers can `st.markdown(..., unsafe_allow_html=True)` above the
    figure when they pass `show_legend=False` to the renderer."""
    if view == "retrieval":
        items = [(COL_SKYBLUE, "シード（クエリで選択）"),
                 (COL_BLUE,    "検索で抽出"),
                 (COL_BG_NODE, "未使用")]
    else:
        items = [(COL_BLUE,    "出力に使用（低頻度）"),
                 (COL_SKYBLUE, "出力に使用（高頻度）"),
                 (COL_RED,     "出力にあるが未検索"),
                 (COL_BG_NODE, "未使用")]
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;'
        f'margin:0 12px 6px 0;font-size:12px;color:{COL_TEXT};">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:{c};border:1px solid #8b90a0;margin-right:6px;"></span>{html.escape(l)}'
        f'</span>' for c, l in items)
    return ('<div style="padding:4px 0 8px 0;line-height:1.6;">' + chips + '</div>')


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
                "Kind": "seed" if nid in seeds else "retrieved",
                "Entity": n.get("name", nid),
                "Type": n.get("type", ""),
                "Domain": " / ".join(n.get("domains", [])),
            })
        for ei in usage["retrieved_edges"]:
            edges_rows.append({"Kind": "retrieved", "Edge": triple(ei),
                               "Domain": " / ".join(graph["edges"][ei].get("domains", []))})
    else:
        for nid, freq in sorted(usage["output_nodes"].items(), key=lambda x: -x[1]):
            n = graph["nodes"].get(nid, {})
            nodes_rows.append({
                "Kind": "Missed (red)" if nid in missed_n else "used",
                "Entity": n.get("name", nid),
                "Freq": freq,
                "Also retrieved": "Y" if nid in retrieved_n else "N",
            })
        for h in sorted(usage["output_edges"], key=lambda x: -x["freq"]):
            edges_rows.append({
                "Kind": "Missed (red)" if h["index"] in missed_ei else "used",
                "Edge": triple(h["index"]),
                "Freq": h["freq"],
                "Predicate match": "Y" if h.get("predicate_match") else "N",
                "Also retrieved": "Y" if h["index"] in retrieved_e else "N",
            })
    return {"nodes": nodes_rows, "edges": edges_rows}


def unified_usage_table(usage):
    """Single merged table with per-view flag columns — one row per node /
    edge across both views. Used when the two SVGs are stacked vertically
    and a single flat list of touched elements suffices instead of separate
    per-view tables. Returns {'nodes': [...], 'edges': [...]}."""
    graph = usage["graph"]
    seeds = set(usage["seeds"])
    retrieved_n = set(usage["retrieved_nodes"])
    retrieved_e = set(usage["retrieved_edges"])
    output_n_freq = dict(usage["output_nodes"])          # {nid: freq}
    output_e_map = {h["index"]: h for h in usage["output_edges"]}
    missed_n = set(usage["missed_nodes"])
    missed_ei = {h["index"] for h in usage["missed_edges"]}

    def _node_name(nid):
        return graph["nodes"].get(nid, {}).get("name", nid)

    def _triple(ei):
        e = graph["edges"][ei]
        return f'({_node_name(e["source"])}) --[{e["relation"]}]--> ({_node_name(e["target"])})'

    # --- Nodes: union of retrieved + output ---
    node_ids = list(dict.fromkeys(list(retrieved_n) + list(output_n_freq.keys())))
    node_rows = []
    for nid in node_ids:
        n = graph["nodes"].get(nid, {})
        _is_retrieved = nid in retrieved_n
        _is_output = nid in output_n_freq
        _freq = int(output_n_freq.get(nid, 0))
        if not _is_retrieved and _is_output:
            _view = "gen only (red)"
        elif _is_retrieved and _is_output:
            _view = "retrieval+gen"
        elif _is_retrieved and not _is_output:
            _view = "retrieval only"
        else:
            _view = "-"
        node_rows.append({
            "Entity": n.get("name", nid),
            "Type": n.get("type", ""),
            "Domain": " / ".join(n.get("domains", [])),
            "Retrieval": "seed" if nid in seeds else ("Y" if _is_retrieved else "N"),
            "Gen freq": _freq if _is_output else 0,
            "Missed (red)": "Y" if nid in missed_n else "N",
            "View": _view,
        })
    # Sort: red (missed) first, then by generation freq desc, then by name
    node_rows.sort(key=lambda r: (0 if r["Missed (red)"] == "Y" else 1,
                                     -r["Gen freq"], r["Entity"]))

    # --- Edges: union of retrieved + output ---
    edge_ids = list(dict.fromkeys(list(retrieved_e) + list(output_e_map.keys())))
    edge_rows = []
    for ei in edge_ids:
        e = graph["edges"][ei]
        _is_retrieved = ei in retrieved_e
        _out = output_e_map.get(ei)
        _freq = int(_out["freq"]) if _out else 0
        _pmatch = "Y" if (_out and _out.get("predicate_match")) else "N"
        if not _is_retrieved and _out:
            _view = "gen only (red)"
        elif _is_retrieved and _out:
            _view = "retrieval+gen"
        elif _is_retrieved and not _out:
            _view = "retrieval only"
        else:
            _view = "-"
        edge_rows.append({
            "Edge": _triple(ei),
            "Domain": " / ".join(e.get("domains", [])),
            "Retrieval": "Y" if _is_retrieved else "N",
            "Gen freq": _freq,
            "Predicate match": _pmatch,
            "Missed (red)": "Y" if ei in missed_ei else "N",
            "View": _view,
        })
    edge_rows.sort(key=lambda r: (0 if r["Missed (red)"] == "Y" else 1,
                                     -r["Gen freq"], r["Edge"]))
    return {"nodes": node_rows, "edges": edge_rows}


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


# ============================================================================
# Static "graph state" helpers (Knowledge Explorer, not per-turn).
# ============================================================================

# 8 soft pastel fills for type-based coloring (assigned deterministically by
# md5(type_name) so the same type maps to the same color across sessions).
_TYPE_PALETTE = [
    "#c9e6ff", "#ffe0c9", "#d6f0d0", "#e5d6f0",
    "#ffe6f0", "#d9edf0", "#f0ecd6", "#e0e0e0",
]


def _type_color(type_name):
    """Deterministic soft color per node type — same across sessions."""
    if not type_name:
        return "#f2f2f2"
    idx = int(hashlib.md5(type_name.encode()).hexdigest()[:8], 16) % len(_TYPE_PALETTE)
    return _TYPE_PALETTE[idx]


def render_graph_neutral_svg(graph, width=1200, height=800, font_size=10,
                              color_by_type=True, label_top_hubs=25,
                              highlight_node_ids=None, show_legend=True,
                              interactive=True):
    """Static whole-graph SVG (no per-turn overlay). Optionally color nodes
    by type; labels only the top-degree hubs to avoid text clutter on large
    graphs. If highlight_node_ids is given, those nodes get a blue ring +
    always show their label (used by the drill-down tab). Pass
    show_legend=False when rendering an external legend via
    `neutral_legend_html(graph)` above the figure.

    `interactive=True` (default) attaches CSS + inline JS so hovering a
    node dims all edges except those incident to it, plus reveals the
    node's name label if it wasn't already labeled. This requires
    embedding via `st.components.v1.html(...)` — Streamlit's plain
    `st.markdown(unsafe_allow_html=True)` strips inline `<script>`. Set
    interactive=False for the offline preview HTML path.
    """
    highlight_node_ids = set(highlight_node_ids or [])
    pos = spring_layout(graph)
    pad = 60

    def sx(nid): return pad + pos[nid][0] * (width - 2 * pad)
    def sy(nid): return pad + pos[nid][1] * (height - 2 * pad)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'viewBox="0 0 {width} {height}" style="background:#ffffff;font-family:sans-serif;'
             f'max-width:100%;">']

    # Compute degree first (used for label prioritization AND for the hub-set
    # tooltip on each node).
    degree = {nid: 0 for nid in graph["nodes"]}
    for e in graph["edges"]:
        if e["source"] in degree: degree[e["source"]] += 1
        if e["target"] in degree: degree[e["target"]] += 1
    _hub_ids = set(nid for nid, _d in sorted(degree.items(), key=lambda x: -x[1])[:label_top_hubs])

    # Interactive styles: edges start faded → hover on any node reveals its
    # incident edges (blue). Nodes flagged as "picked" (highlight_node_ids)
    # show their edges permanently in sky-blue. Label opacity is boosted on
    # hover regardless of hub status.
    if interactive:
        parts.append(
            "<style>"
            ".ge{opacity:0.10;transition:opacity 0.12s,stroke 0.12s,stroke-width 0.12s;}"
            ".ge.picked{opacity:0.85;stroke:#7ec8ff;stroke-width:1.8;}"
            ".ge.hl{opacity:1;stroke:#1f4fd8;stroke-width:2.4;}"
            ".gn{cursor:pointer;}"
            ".gn:hover circle{stroke:#1f4fd8;stroke-width:2.8;}"
            ".glbl{opacity:0.65;pointer-events:none;transition:opacity 0.12s;}"
            ".gn:hover .glbl{opacity:1;font-weight:600;fill:#20242e;}"
            ".gn.picked .glbl{opacity:1;font-weight:700;fill:#20242e;}"
            "</style>"
        )

    # Edges
    for e in graph["edges"]:
        if e["source"] not in pos or e["target"] not in pos:
            continue
        x1, y1, x2, y2 = sx(e["source"]), sy(e["source"]), sx(e["target"]), sy(e["target"])
        _cls = "ge"
        if e["source"] in highlight_node_ids or e["target"] in highlight_node_ids:
            _cls += " picked"
        _static_style = f' stroke="{COL_BG_EDGE}" stroke-width="1"'
        _static_opacity = ' opacity="0.6"' if not interactive else ""
        parts.append(f'<line class="{_cls}" data-src="{html.escape(e["source"])}" '
                     f'data-tgt="{html.escape(e["target"])}" '
                     f'x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}"'
                     f'{_static_style}{_static_opacity}>'
                     f'<title>{html.escape(e["relation"])}</title></line>')

    # Nodes
    for nid, n in graph["nodes"].items():
        x, y = sx(nid), sy(nid)
        _is_hub = nid in _hub_ids
        _is_hl = nid in highlight_node_ids
        _fill = _type_color(n.get("type", "")) if color_by_type else COL_BG_NODE
        _stroke = COL_BLUE if _is_hl else "#8b90a0"
        _r = 8 if _is_hl else (6 if _is_hub else 4)
        _sw = 2.4 if _is_hl else 1.0
        _grp_cls = "gn"
        if _is_hl:
            _grp_cls += " picked"
        parts.append(f'<g class="{_grp_cls}" data-nid="{html.escape(nid)}">'
                     f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{_r}" fill="{_fill}" '
                     f'stroke="{_stroke}" stroke-width="{_sw}">'
                     f'<title>{html.escape(n["name"])} ({html.escape(n.get("type", ""))})'
                     f' - degree {degree[nid]}</title></circle>')
        if _is_hub or _is_hl:
            _fill_txt = COL_TEXT if (_is_hl or _is_hub) else COL_TEXT_DIM
            _weight = "600" if _is_hl else "500"
            parts.append(f'<text class="glbl" x="{x:.0f}" y="{y + _r + font_size:.0f}" '
                         f'font-size="{font_size}" fill="{_fill_txt}" '
                         f'font-weight="{_weight}" text-anchor="middle">'
                         f'{html.escape(n["name"])}</text>')
        elif interactive:
            # Add a hidden label that reveals on hover (opacity 0 in CSS).
            parts.append(f'<text class="glbl" x="{x:.0f}" y="{y + _r + font_size:.0f}" '
                         f'font-size="{font_size}" fill="{COL_TEXT_DIM}" '
                         f'text-anchor="middle" style="opacity:0;">'
                         f'{html.escape(n["name"])}</text>')
        parts.append('</g>')

    # Type legend (only when color_by_type is on AND show_legend requested).
    # Callers that render the legend outside the figure via
    # `neutral_legend_html(graph)` should pass show_legend=False.
    if color_by_type and show_legend:
        _types_present = sorted({n.get("type", "") for n in graph["nodes"].values() if n.get("type")})
        _shown = _types_present[:12]  # cap legend rows
        plate_h = len(_shown) * 18 + 14
        parts.append(f'<rect x="6" y="4" width="230" height="{plate_h}" rx="6" '
                     f'fill="#ffffff" fill-opacity="0.92" stroke="#e3e4e0"/>')
        _lx, _ly = 18, 22
        for _t in _shown:
            parts.append(f'<circle cx="{_lx}" cy="{_ly}" r="5" fill="{_type_color(_t)}" stroke="#8b90a0"/>')
            parts.append(f'<text x="{_lx + 10}" y="{_ly + 4}" font-size="{font_size}" '
                         f'fill="{COL_TEXT}">{html.escape(_t)}</text>')
            _ly += 18
    # Inline interaction script: on mouseover of a node, add .hl class to
    # every edge whose data-src OR data-tgt matches that node's data-nid.
    # Runs once when the SVG is first parsed (via IIFE inside SVG scripting).
    if interactive:
        parts.append(
            "<script><![CDATA["
            "(function(){"
            "var svg=document.currentScript.parentNode;"
            "if(!svg||svg.tagName.toLowerCase()!=='svg'){return;}"
            "var edges=svg.querySelectorAll('.ge');"
            "var nodes=svg.querySelectorAll('.gn');"
            "var byEnd={};"
            "edges.forEach(function(e){"
            "var s=e.getAttribute('data-src'),t=e.getAttribute('data-tgt');"
            "(byEnd[s]=byEnd[s]||[]).push(e);(byEnd[t]=byEnd[t]||[]).push(e);"
            "});"
            "nodes.forEach(function(n){"
            "var nid=n.getAttribute('data-nid');"
            "n.addEventListener('mouseover',function(){"
            "(byEnd[nid]||[]).forEach(function(e){e.classList.add('hl');});"
            "});"
            "n.addEventListener('mouseout',function(){"
            "(byEnd[nid]||[]).forEach(function(e){e.classList.remove('hl');});"
            "});"
            "});"
            "})();"
            "]]></script>"
        )
    parts.append("</svg>")
    return "".join(parts)


def seed_provenance_html(usage):
    """Render the seed-generation trace + dictionary alias resolution as
    a compact HTML block for the Analytics Results Graph section. Shows
    every query fed to entity linking, each raw substring match, and
    (when different) the canonical node it resolved to via dictionary /
    node-alias mapping. Returns "" when no trace is available."""
    trace = usage.get("seed_trace") or []
    queries = usage.get("queries") or []
    seed_names = usage.get("seed_names") or []
    if not (trace or queries or seed_names):
        return ""
    _rows = []
    for _tr in trace:
        _q = html.escape(str(_tr.get("query", "")))
        _raw = _tr.get("matches_raw") or []
        if _raw:
            _hits = []
            for _m in _raw:
                _mention = html.escape(_m.get("mention", ""))
                _mapped  = html.escape(_m.get("mapped_to_name", ""))
                if _mention == _mapped:
                    _hits.append(
                        f'<span style="display:inline-block;padding:2px 8px;'
                        f'background:#e8f0ff;border-radius:4px;margin:0 6px 4px 0;'
                        f'color:#20242e;">{_mention}</span>')
                else:
                    _hits.append(
                        f'<span style="display:inline-block;padding:2px 8px;'
                        f'background:#fff3e0;border-radius:4px;margin:0 6px 4px 0;'
                        f'color:#20242e;">{_mention} <span style="color:#8a8f98;">→</span> '
                        f'<b>{_mapped}</b></span>')
            _hits_html = "".join(_hits)
        else:
            _hits_html = '<span style="color:#8a8f98;">(該当なし)</span>'
        _rows.append(
            f'<div style="margin-bottom:6px;line-height:1.7;font-size:12px;">'
            f'<span style="color:#8a8f98;">クエリ:</span> '
            f'<code style="background:#f5f5f7;padding:1px 6px;border-radius:3px;">{_q}</code><br/>'
            f'<span style="color:#8a8f98;margin-left:8px;">シード検出 (辞書変換):</span> {_hits_html}'
            f'</div>')
    _final = html.escape(", ".join(seed_names)) if seed_names else '<span style="color:#8a8f98;">(なし)</span>'
    return (
        f'<div style="border-left:3px solid #1f4fd8;background:#f9fafb;'
        f'padding:8px 12px;margin:0 0 10px 0;border-radius:0 6px 6px 0;">'
        f'<div style="font-size:12px;color:#20242e;font-weight:600;margin-bottom:6px;">'
        f'シード生成トレース</div>'
        + "".join(_rows) +
        f'<div style="margin-top:4px;font-size:12px;">'
        f'<span style="color:#8a8f98;">最終シード ({len(seed_names)}件):</span> '
        f'<b>{_final}</b></div>'
        f'</div>'
    )


def neutral_legend_html(graph, top_n=12):
    """External-to-SVG legend for `render_graph_neutral_svg` — shows the
    top-N types by node count with their assigned soft colors. Rendered as
    a wrap-friendly chip row above/below the figure."""
    from collections import Counter
    _cnt = Counter((n.get("type") or "") for n in (graph.get("nodes") or {}).values())
    _rows = [(t, c) for t, c in _cnt.most_common() if t]
    _rows = _rows[:top_n]
    if not _rows:
        return ""
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;'
        f'margin:0 12px 6px 0;font-size:12px;color:{COL_TEXT};">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;'
        f'background:{_type_color(t)};border:1px solid #8b90a0;margin-right:6px;"></span>'
        f'{html.escape(t)} <span style="color:#8a8f98;margin-left:4px;">({c})</span></span>'
        for t, c in _rows)
    return (f'<div style="padding:4px 0 8px 0;line-height:1.6;">'
              f'<span style="color:#666;font-size:11px;margin-right:8px;">凡例 (型 top {len(_rows)})</span>'
              + chips + '</div>')


def graph_overview_stats(graph, top_n=10):
    """Structural summary of the graph — counts, distributions, top hubs.
    Returns a dict of pre-formatted rows / values ready for st.dataframe /
    st.metric consumption."""
    from collections import Counter
    nodes = graph.get("nodes") or {}
    edges = graph.get("edges") or []

    type_counter = Counter(n.get("type", "") or "(unspecified)" for n in nodes.values())
    domain_counter = Counter()
    for n in nodes.values():
        for d in (n.get("domains") or []):
            domain_counter[d] += 1
    for e in edges:
        for d in (e.get("domains") or []):
            domain_counter[d] += 1
    pred_counter = Counter(e.get("relation", "") for e in edges)

    degree = Counter()
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    hubs = []
    for nid, dg in degree.most_common(top_n):
        n = nodes.get(nid, {})
        hubs.append({
            "Entity":  n.get("name", nid),
            "Type":    n.get("type", ""),
            "Domain":  " / ".join(n.get("domains", [])),
            "Degree":  dg,
        })

    _avg_degree = round((sum(degree.values()) / len(nodes)) if nodes else 0.0, 2)
    _isolated = [nid for nid in nodes if degree.get(nid, 0) == 0]

    return {
        "totals": {
            "Nodes": len(nodes),
            "Edges": len(edges),
            "Type kinds": len(type_counter),
            "Domain kinds": len(domain_counter),
            "Relation kinds": len(pred_counter),
            "Avg degree": _avg_degree,
            "Isolated nodes": len(_isolated),
        },
        "types":      [{"Type": k, "Count": v} for k, v in type_counter.most_common(top_n * 3)],
        "domains":    [{"Domain": k, "Count": v} for k, v in domain_counter.most_common(top_n * 3)],
        "predicates": [{"Relation": k, "Count": v} for k, v in pred_counter.most_common(top_n * 2)],
        "hubs":       hubs,
    }


def graph_quality_report(graph, dictionary=None, dup_threshold=1):
    """Data-quality checks — surfaces cleanup candidates:
      - isolated_nodes: nodes with zero incident edges
      - missing_type:   nodes with empty type field
      - missing_domain: nodes with no domains
      - dup_name_candidates: nodes whose names differ only by a
        surface-level normalization (case/whitespace/simple hiragana-
        katakana difference) — potential alias merge candidates
      - predicate_variants: predicates that share a normalized form
        (e.g. "関連する" / "関連" / "関連付ける" → suggest a canonical)
    dup_threshold: minimum group size to report (default 2 = pairs).
    Returns a dict of list-of-dict rows."""
    from collections import defaultdict
    nodes = graph.get("nodes") or {}
    edges = graph.get("edges") or []
    dictionary = dictionary or {}

    # Isolated
    incident = {nid: 0 for nid in nodes}
    for e in edges:
        if e["source"] in incident: incident[e["source"]] += 1
        if e["target"] in incident: incident[e["target"]] += 1
    _isolated = [
        {"Entity": n.get("name", nid), "Type": n.get("type", ""),
         "Domain": " / ".join(n.get("domains", []))}
        for nid, n in nodes.items() if incident.get(nid, 0) == 0
    ]

    # Missing type / domain
    _no_type = [
        {"Entity": n.get("name", nid), "Degree": incident.get(nid, 0)}
        for nid, n in nodes.items() if not (n.get("type") or "").strip()
    ]
    _no_domain = [
        {"Entity": n.get("name", nid), "Type": n.get("type", ""),
         "Degree": incident.get(nid, 0)}
        for nid, n in nodes.items() if not (n.get("domains") or [])
    ]

    # Duplicate-name candidates (simple normalization)
    def _norm(s):
        s = (s or "").strip().lower().replace(" ", "").replace("　", "")
        # optional kana fold could be added
        return s
    dup_map = defaultdict(list)
    for nid, n in nodes.items():
        dup_map[_norm(n.get("name", ""))].append((nid, n.get("name", ""), n.get("type", "")))
    _dup_rows = []
    for _key, entries in dup_map.items():
        if len(entries) > dup_threshold:
            for nid, name, typ in entries:
                _dup_rows.append({
                    "グループ": _key,
                    "Entity": name,
                    "Type": typ,
                    "同グループ内の他候補": ", ".join(n for _i, n, _t in entries if n != name),
                })

    # Predicate variants (basic normalization: strip trailing verb suffixes)
    def _pred_norm(p):
        for suf in ("する", "した", "される", "した。", "する。"):
            if p.endswith(suf):
                return p[: -len(suf)]
        return p
    pred_map = defaultdict(list)
    for e in edges:
        pred = e.get("relation", "")
        pred_map[_pred_norm(pred)].append(pred)
    _pred_var_rows = []
    for norm_p, variants in pred_map.items():
        _distinct = sorted(set(variants))
        if len(_distinct) > 1:
            _pred_var_rows.append({
                "基本形候補": norm_p,
                "バリアント": " / ".join(_distinct),
                "登場回数": len(variants),
            })

    return {
        "isolated_nodes":       _isolated,
        "missing_type":         _no_type,
        "missing_domain":       _no_domain,
        "dup_name_candidates":  _dup_rows,
        "predicate_variants":   sorted(_pred_var_rows, key=lambda r: -r["登場回数"]),
    }


def build_subgraph_around(graph, center_node_id, hops=1, edge_limit=60):
    """Ego-network view — BFS TRAVERSAL edges only.

    Contains the center node + every node reachable within `hops` steps,
    and every edge TRAVERSED during that BFS. Explicitly excludes "back
    edges" — edges between two visited nodes that were not on the
    traversal path (e.g. an edge between two direct neighbors of the
    center at hops=1). Rationale: the drill-down UI lists adjacency per
    picked seed only; showing induced-subgraph edges that don't touch a
    picked seed causes a mismatch ("phantom" lines in the SVG that don't
    appear in any adjacency list).

    At hops=1 this is exactly the star of the center (all incident
    edges). At hops=2 it also traverses each direct neighbor's edges to
    reach further nodes."""
    from collections import deque
    if center_node_id not in (graph.get("nodes") or {}):
        return {"nodes": {}, "edges": []}
    node_adj = {nid: [] for nid in graph["nodes"]}
    for ei, e in enumerate(graph["edges"]):
        if e["source"] in node_adj: node_adj[e["source"]].append(ei)
        if e["target"] in node_adj: node_adj[e["target"]].append(ei)
    keep_nodes = {center_node_id}
    keep_edges = []
    seen_edges = set()
    frontier = deque([(center_node_id, 0)])
    while frontier:
        nid, dep = frontier.popleft()
        if dep >= hops:
            continue
        for ei in node_adj.get(nid, []):
            if ei in seen_edges:
                continue
            if len(keep_edges) >= edge_limit:
                break
            seen_edges.add(ei)
            keep_edges.append(ei)
            e = graph["edges"][ei]
            other = e["target"] if e["source"] == nid else e["source"]
            if other not in keep_nodes:
                keep_nodes.add(other)
                frontier.append((other, dep + 1))
        if len(keep_edges) >= edge_limit:
            break
    return {
        "nodes": {nid: graph["nodes"][nid] for nid in keep_nodes if nid in graph["nodes"]},
        "edges": [graph["edges"][ei] for ei in keep_edges],
    }
