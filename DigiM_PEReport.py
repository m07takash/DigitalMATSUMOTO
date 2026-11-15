"""Performance Explorer: record what the screen draws and write it as one HTML file.

The screen is ordinary Streamlit code spread over tabs, columns, expanders and
shared helpers. Rather than building a second report next to it (which would
drift from the screen), each Performance Explorer function starts with
`st = ui()`: while a recording is active that is a thin proxy which forwards
every call to Streamlit and keeps a copy of what was drawn; otherwise it is the
streamlit module itself, so nothing changes for normal reruns.

Streamlit runs every tab body on every rerun, so one recorded run holds all
tabs, in screen order. Recording is per script thread (each browser session
runs in its own), and only from `arm()` on: the condition widgets above the
results describe the next run, not the one being exported.
"""
from __future__ import annotations

import base64
import html
import io
import json
import logging
import numbers
import re
import threading
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

_local = threading.local()

# Pinned so a report opens the same way later; the Vega-Lite version is the
# one this Altair writes its specs for.
_VEGA = "https://cdn.jsdelivr.net/npm/vega@5.30.0"
_VEGA_LITE = "https://cdn.jsdelivr.net/npm/vega-lite@5.20.1"
_VEGA_EMBED = "https://cdn.jsdelivr.net/npm/vega-embed@6.26.0"
_MAX_ROWS = 1000


class Recorder:
    def __init__(self):
        self.items: list = []
        self.armed = False

    def add(self, what: str, /, **kw):
        if self.armed:
            self.items.append((what, kw))

    def arm(self, title: str, subtitle: str = ""):
        self.armed = True
        self.items.append(("title", {"text": title, "sub": subtitle}))


def start() -> Recorder:
    _local.rec = Recorder()
    return _local.rec


def stop():
    _local.rec = None


def active():
    return getattr(_local, "rec", None)


def arm(title: str, subtitle: str = ""):
    rec = active()
    if rec is not None:
        rec.arm(title, subtitle)


def ui():
    import streamlit
    rec = active()
    return streamlit if rec is None else _Proxy(streamlit, rec)


# ------------------------------------------------------------- recording ---
def _frame(data):
    if isinstance(data, pd.DataFrame):
        return data.copy()
    if hasattr(data, "data") and isinstance(getattr(data, "data"), pd.DataFrame):  # Styler
        return data.data.copy()
    try:
        return pd.DataFrame(data)
    except Exception:
        return None


def _image_uri(img):
    """data: URI for what st.image accepts here: bytes, a path, PIL, ndarray."""
    raw = None
    if isinstance(img, (bytes, bytearray)):
        raw = bytes(img)
    elif isinstance(img, str):
        with open(img, "rb") as f:
            raw = f.read()
    else:
        try:
            from PIL import Image
            if not isinstance(img, Image.Image):
                import numpy as np
                img = Image.fromarray(np.asarray(img))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            raw = buf.getvalue()
        except Exception:
            return None
    mime = ("image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else
            "image/jpeg" if raw[:3] == b"\xff\xd8\xff" else
            "image/svg+xml" if raw.lstrip()[:5] in (b"<?xml", b"<svg ") else "image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _r_text(kind):
    def f(rec, out, body="", *a, **k):
        body = k.get("body", body)
        if not isinstance(body, str):
            return
        if kind == "md" and k.get("unsafe_allow_html") and body.lstrip().startswith("<"):
            return  # layout spacers
        if body:
            rec.add(kind, text=body)
    return f


def _r_note(level):
    def f(rec, out, body="", *a, **k):
        rec.add("note", level=level, text=str(k.get("body", body) or ""))
    return f


def _r_heading(prefix):
    def f(rec, out, body="", *a, **k):
        rec.add("md", text=prefix + str(k.get("body", body) or ""))
    return f


def _r_metric(rec, out, label="", value="", *a, **k):
    rec.add("metric", label=str(k.get("label", label)), value=str(k.get("value", value)))


def _r_table(rec, out, data=None, *a, **k):
    df = _frame(k.get("data", data))
    if df is not None:
        rec.add("table", df=df, cfg=k.get("column_config") or {}, hide_index=k.get("hide_index"))


def _r_editor(rec, out, data=None, *a, **k):
    df = _frame(out if out is not None else k.get("data", data))
    if df is not None:
        rec.add("table", df=df, cfg=k.get("column_config") or {}, hide_index=k.get("hide_index"))


def _r_chart(rec, out, chart=None, *a, **k):
    chart = k.get("altair_chart", chart)
    spec = chart.to_dict()
    if k.get("use_container_width", True) and "width" not in spec:
        spec["width"] = "container"
    rec.add("chart", spec=spec)


def _r_image(rec, out, image=None, *a, **k):
    imgs = k.get("image", image)
    for img in (imgs if isinstance(imgs, list) else [imgs]):
        uri = _image_uri(img)
        if uri:
            rec.add("image", uri=uri, caption=str(k.get("caption") or ""))


def _r_pyplot(rec, fig=None, *a, **k):
    import matplotlib.pyplot as plt
    fig = k.get("fig", fig) or plt.gcf()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    rec.add("image", uri="data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), caption="")


def _r_choice(rec, out, label="", *a, **k):
    label = str(k.get("label", label))
    fmt = k.get("format_func") or str
    if out is None or out == "" or out == []:
        return
    try:
        shown = ", ".join(map(str, map(fmt, out))) if isinstance(out, (list, tuple)) else str(fmt(out))
    except Exception:
        shown = str(out)
    rec.add("choice", label=label.rstrip(":"), value=shown)


_RECORDERS = {
    "markdown": _r_text("md"), "write": _r_text("md"), "caption": _r_text("caption"), "code": _r_text("code"),
    "info": _r_note("info"), "warning": _r_note("warning"), "success": _r_note("success"), "error": _r_note("error"),
    "title": _r_heading("# "), "header": _r_heading("## "), "subheader": _r_heading("### "),
    "metric": _r_metric, "dataframe": _r_table, "table": _r_table, "data_editor": _r_editor,
    "altair_chart": _r_chart, "image": _r_image,
    "selectbox": _r_choice, "radio": _r_choice, "number_input": _r_choice, "slider": _r_choice,
    "text_input": _r_choice,
}
# Before the call: st.pyplot clears the global figure once it has drawn it.
_PRE_RECORDERS = {"pyplot": _r_pyplot}


class _Proxy:
    __slots__ = ("_t", "_r", "_kind", "_label")

    def __init__(self, target, rec, kind=None, label=None):
        self._t, self._r, self._kind, self._label = target, rec, kind, label

    def __getattr__(self, name):
        attr = getattr(self._t, name)
        rec = self._r
        if name == "columns":
            return lambda *a, **k: [_Proxy(c, rec) for c in attr(*a, **k)]
        if name == "tabs":
            def _tabs(tabs, *a, **k):
                return [_Proxy(t, rec, "tab", str(lbl)) for t, lbl in zip(attr(tabs, *a, **k), tabs)]
            return _tabs
        if name == "expander":
            # The report opens every expander so nothing is hidden; `_fold=True`
            # (report only, not a Streamlit argument) keeps one closed.
            return lambda label, *a, _fold=False, **k: _Proxy(attr(label, *a, **k), rec, "fold" if _fold else "expander",
                                                                str(label).lstrip("# "))
        if name in ("container", "empty"):
            return lambda *a, **k: _Proxy(attr(*a, **k), rec)
        pre, post = _PRE_RECORDERS.get(name), _RECORDERS.get(name)
        if pre is None and post is None:
            return attr

        def _call(*a, **k):
            if pre is not None:
                try:
                    pre(rec, *a, **k)
                except Exception as e:
                    logger.warning("PE report: could not record %s (%s)", name, e)
            out = attr(*a, **k)
            if post is not None:
                try:
                    post(rec, out, *a, **k)
                except Exception as e:
                    logger.warning("PE report: could not record %s (%s)", name, e)
            return out
        return _call

    # A failure to record must never break the screen it is recording.
    def __enter__(self):
        self._t.__enter__()
        if self._kind:
            try:
                self._r.add("open", kind=self._kind, label=self._label)
            except Exception as e:
                logger.warning("PE report: could not record %s (%s)", self._kind, e)
        return self

    def __exit__(self, *exc):
        if self._kind:
            try:
                self._r.add("close", kind=self._kind)
            except Exception as e:
                logger.warning("PE report: could not record %s (%s)", self._kind, e)
        return self._t.__exit__(*exc)


# ---------------------------------------------------------------- output ---
def _md():
    from markdown_it import MarkdownIt
    # Inputs and answers can carry markup; the screen shows them as text, so
    # raw HTML stays text here too.
    return MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")


_MOMENT = (("YYYY", "%Y"), ("MM", "%m"), ("DD", "%d"), ("HH", "%H"), ("mm", "%M"), ("ss", "%S"))


def _is_num(v) -> bool:
    return isinstance(v, numbers.Real) and not isinstance(v, bool)


def _fmt_cell(v, tc: dict):
    if hasattr(v, "tolist") and not isinstance(v, (pd.Timestamp, numbers.Number)):
        v = v.tolist()  # ndarray cells (bar charts)
    if v is None or (not isinstance(v, (list, tuple, dict, set)) and pd.isna(v)):
        return ""
    t = (tc or {}).get("type")
    fmt = (tc or {}).get("format")
    if isinstance(v, set):
        v = sorted(map(str, v))
    if isinstance(v, (list, tuple)):
        if t == "bar_chart":
            return _spark(v)
        return html.escape(", ".join(map(str, v)))
    if isinstance(v, (pd.Timestamp, datetime)):
        f = fmt or "YYYY-MM-DD HH:mm"
        for a, b in _MOMENT:
            f = f.replace(a, b)
        return html.escape(v.strftime(f))
    if isinstance(v, bool):
        return "✓" if v else ""
    if _is_num(v):
        try:
            if fmt and fmt.startswith("%"):
                s = fmt % (int(round(v)) if fmt.endswith("d") else float(v))
            elif isinstance(v, numbers.Integral) or float(v).is_integer():
                s = f"{int(v):,}"
            else:
                s = f"{v:,.4g}" if abs(v) >= 1000 else f"{v:.4g}"
        except (TypeError, ValueError):
            s = str(v)
        if t == "progress":
            lo, hi = tc.get("min_value") or 0, tc.get("max_value") or 1
            pct = max(0.0, min(100.0, 100.0 * (float(v) - lo) / ((hi - lo) or 1)))
            return f'<span class="prog"><span style="width:{pct:.0f}%"></span></span> {html.escape(s)}'
        return html.escape(s)
    return html.escape(str(v))


def _spark(vals) -> str:
    vals = [float(x) for x in vals if x is not None and not pd.isna(x)]
    if not vals:
        return ""
    hi = max(vals) or 1.0
    w = 4
    bars = "".join(f'<rect x="{i * w}" y="{20 - 20 * v / hi:.1f}" width="{w - 1}" height="{20 * v / hi:.1f}"/>'
                   for i, v in enumerate(vals))
    return f'<svg class="spark" width="{len(vals) * w}" height="20" viewBox="0 0 {len(vals) * w} 20">{bars}</svg>'


def _table_html(df: pd.DataFrame, cfg: dict, hide_index) -> str:
    cols, heads, tcs = [], [], []
    for c in df.columns:
        cc = cfg.get(c, "") if isinstance(cfg, dict) else ""
        if c in (cfg or {}) and cc is None:
            continue  # hidden on screen
        if isinstance(cc, str):
            cc = {"label": cc} if cc else {}
        cols.append(c)
        heads.append((cc or {}).get("label") or str(c))
        tcs.append((cc or {}).get("type_config") or {})
    n = len(df)
    body = []
    for _, row in df.head(_MAX_ROWS).iterrows():
        tds = []
        for c, tc in zip(cols, tcs):
            v = row[c]
            num = _is_num(v)
            tds.append(f'<td class="{"num" if num else ""}">{_fmt_cell(v, tc)}</td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    note = f'<p class="caption">First {_MAX_ROWS:,} of {n:,} rows.</p>' if n > _MAX_ROWS else ""
    return ('<div class="tbl"><table><thead><tr>' + "".join(f"<th>{html.escape(h)}</th>" for h in heads)
            + "</tr></thead><tbody>" + "".join(body) + "</tbody></table></div>" + note)


_CSS = """
:root{--bg:#ffffff;--fg:#1f2328;--muted:#656d76;--line:#d8dee4;--soft:#f6f8fa;--accent:#2f6fdb;
--info:#e8f1fd;--warn:#fff6db;--ok:#e7f6ec;--err:#fde8e8}
@media (prefers-color-scheme: dark){:root{--bg:#0e1117;--fg:#e6edf3;--muted:#9198a1;--line:#30363d;
--soft:#161b22;--accent:#6ea8fe;--info:#13233b;--warn:#332a10;--ok:#11281a;--err:#3a1717}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
header h1{font-size:1.6rem;margin:0 0 4px}
header p{margin:0;color:var(--muted)}
section.tab{border-top:2px solid var(--line);margin-top:32px;padding-top:8px}
section.tab>h2{font-size:1.35rem;margin:8px 0 12px}
details{border:1px solid var(--line);border-radius:8px;padding:4px 12px;margin:12px 0}
summary{cursor:pointer;font-weight:600;padding:4px 0}
h3,h4{margin:20px 0 8px}
.caption{color:var(--muted);font-size:.86rem;margin:4px 0 10px}
.choice{display:inline-block;font-size:.85rem;color:var(--muted);background:var(--soft);border:1px solid var(--line);
border-radius:6px;padding:1px 8px;margin:6px 6px 6px 0}
.choice b{color:var(--fg);font-weight:600}
.metrics{display:flex;flex-wrap:wrap;gap:12px;margin:12px 0}
.metric{flex:1 1 140px;border:1px solid var(--line);border-radius:8px;padding:8px 12px}
.metric .l{font-size:.8rem;color:var(--muted)}.metric .v{font-size:1.5rem;font-weight:600}
.note{border-radius:8px;padding:8px 12px;margin:10px 0}
.note.info{background:var(--info)}.note.warning{background:var(--warn)}.note.success{background:var(--ok)}.note.error{background:var(--err)}
pre{background:var(--soft);border:1px solid var(--line);border-radius:6px;padding:8px 10px;white-space:pre-wrap;word-break:break-word;font-size:.85rem}
.tbl{overflow-x:auto;margin:8px 0 12px;max-height:640px;overflow-y:auto;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:.85rem}
th,td{padding:4px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{position:sticky;top:0;background:var(--soft);font-weight:600}
td.num{text-align:right;white-space:nowrap}
.prog{display:inline-block;width:60px;height:8px;background:var(--line);border-radius:4px;vertical-align:middle;overflow:hidden}
.prog span{display:block;height:100%;background:var(--accent)}
.spark rect{fill:var(--accent)}
.chart{width:100%;margin:8px 0 12px}
figure{margin:8px 0}figure img{max-width:100%;height:auto}
hr{border:0;border-top:1px solid var(--line);margin:20px 0}
"""


def render_html(rec: Recorder, title: str) -> bytes:
    md = _md()
    out, specs = [], []
    metrics: list = []

    def flush_metrics():
        if metrics:
            out.append('<div class="metrics">' + "".join(
                f'<div class="metric"><div class="l">{html.escape(l)}</div><div class="v">{html.escape(v)}</div></div>'
                for l, v in metrics) + "</div>")
            metrics.clear()

    for kind, kw in rec.items:
        if kind != "metric":
            flush_metrics()
        if kind == "title":
            out.append(f'<header><h1>{html.escape(kw["text"])}</h1>'
                       + (f'<p>{html.escape(kw["sub"])}</p>' if kw["sub"] else "") + "</header>")
        elif kind == "open":
            out.append(f'<section class="tab"><h2>{html.escape(kw["label"])}</h2>' if kw["kind"] == "tab"
                       else f'<details><summary>{html.escape(kw["label"])}</summary>' if kw["kind"] == "fold"
                       else f'<details open><summary>{html.escape(kw["label"])}</summary>')
        elif kind == "close":
            out.append("</section>" if kw["kind"] == "tab" else "</details>")
        elif kind == "md":
            out.append(md.render(kw["text"]))
        elif kind == "caption":
            out.append(f'<p class="caption">{md.renderInline(kw["text"])}</p>')
        elif kind == "note":
            out.append(f'<div class="note {kw["level"]}">{md.render(kw["text"])}</div>')
        elif kind == "code":
            out.append(f"<pre>{html.escape(kw['text'])}</pre>")
        elif kind == "metric":
            metrics.append((kw["label"], kw["value"]))
        elif kind == "choice":
            out.append(f'<span class="choice">{html.escape(kw["label"])}: <b>{html.escape(kw["value"])}</b></span>')
        elif kind == "table":
            out.append(_table_html(kw["df"], kw["cfg"], kw["hide_index"]))
        elif kind == "chart":
            out.append(f'<div class="chart" id="vis{len(specs)}"></div>')
            specs.append(kw["spec"])
        elif kind == "image":
            out.append(f'<figure><img src="{kw["uri"]}" alt="">'
                       + (f"<figcaption class=\"caption\">{html.escape(kw['caption'])}</figcaption>" if kw["caption"] else "")
                       + "</figure>")
        elif kind == "hr":
            out.append("<hr>")
    flush_metrics()

    made = datetime.now().strftime("%Y-%m-%d %H:%M")
    # "</" inside a spec (a title, an input in a tooltip) would end the script element.
    spec_js = json.dumps(specs, ensure_ascii=False, default=str).replace("</", "<\\/")
    script = ""
    if specs:
        script = f"""
<script src="{_VEGA}"></script>
<script src="{_VEGA_LITE}"></script>
<script src="{_VEGA_EMBED}"></script>
<script>
const SPECS = {spec_js};
const dark = window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches;
SPECS.forEach((s, i) => {{
  const el = document.getElementById('vis' + i);
  if (typeof vegaEmbed === 'undefined') {{ el.textContent = 'Chart not shown: the Vega libraries could not be loaded (offline?).'; return; }}
  vegaEmbed(el, s, {{actions: {{export: true, source: false, compiled: false, editor: false}}, theme: dark ? 'dark' : undefined}})
    .catch(e => {{ el.textContent = 'Chart error: ' + e; }});
}});
</script>"""
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body><main>"
           + "".join(out)
           + f'<hr><p class="caption">Exported from DigitalMATSUMOTO Performance Explorer on {made}. '
             "Charts load the Vega libraries from cdn.jsdelivr.net; tables and text work offline.</p>"
           + "</main>" + script + "</body></html>")
    return doc.encode("utf-8")


def file_name(view: str) -> str:
    return "performance_explorer_" + re.sub(r"\W+", "_", view.lower()).strip("_") + "_" \
        + datetime.now().strftime("%Y%m%d_%H%M") + ".html"
