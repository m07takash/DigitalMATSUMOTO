"""Regenerate the DigiMPGSystemGuide PageIndex from README.md.

Parses the README into H2 (chapter) + H3 (section) pages, writes one .md per
section, builds `_index.json`, and writes a parallel Excel snapshot under
`user/common/csv/pageindex/DigiMPGSystemGuide/`.

ID scheme:
  - H2  → "<chapter>"           (e.g. "1", "2", "3", ...)
  - H3  → "<chapter>-<sub>"     (e.g. "1-1", "1-2", ...)
This matches the breadcrumb logic in DigiM_Context._build_page_breadcrumb,
so PageIndex retrieval renders "[Path] Parent > Child > Self" cleanly.

The TOC block (`<details>...</details>`) at the top of the README is skipped
so its inline H4 entries don't pollute the page list.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from datetime import datetime

import pandas as pd


README_PATH = "README.md"
BOOK_TITLE  = "DigiMPGシステムガイド"
RAG_DIR     = Path("user/common/rag/pages/DigiMPGSystemGuide")
XLSX_PATH   = Path("user/common/csv/pageindex/DigiMPGSystemGuide/DigiMPGSystemGuide.xlsx")
SHEET_NAME  = "pages"


def _read_readme() -> list[str]:
    text = Path(README_PATH).read_text(encoding="utf-8")
    # Strip the leading TOC block so its inline anchors don't get parsed.
    text = re.sub(r"<details>.*?</details>", "", text, flags=re.DOTALL, count=1)
    return text.split("\n")


def _strip_fences(lines: list[str]) -> list[str]:
    """Blank-out the body of fenced code blocks so heading-like lines inside
    ``` ``` aren't misread as section markers."""
    out: list[str] = []
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return out


def _parse_sections(lines_for_headings: list[str], lines_for_body: list[str]) -> list[dict]:
    """Return a list of {level, title, body_start_line, body_end_line} for
    every H2/H3 in the (de-fenced) document.

    Heading detection uses lines_for_headings (fences stripped); body slices
    use lines_for_body (original lines, fences intact)."""
    hits = []
    for i, line in enumerate(lines_for_headings):
        m = re.match(r"^(#{2,3})\s+(.+)$", line)
        if m and len(m.group(1)) in (2, 3):
            hits.append({"level": len(m.group(1)),
                          "title": m.group(2).strip(),
                          "line": i})
    # Compute body ranges: from line+1 to the next H2/H3 (or EOF)
    for j, s in enumerate(hits):
        s["body_start"] = s["line"] + 1
        s["body_end"]   = hits[j + 1]["line"] if j + 1 < len(hits) else len(lines_for_body)
    return hits


def _derive_summary(body_lines: list[str]) -> str:
    """Pick the first 1-2 narrative lines (skip blanks, bullet lists, tables,
    code fences) — used for `_index.json.PAGES[*].summary` and the Excel."""
    para: list[str] = []
    for ln in body_lines:
        s = ln.strip()
        if not s:
            if para:
                break
            continue
        if s.startswith(("#", "|", "-", "*", "> ", "```", "<", ">")):
            if para:
                break
            continue
        para.append(s)
        if sum(len(p) for p in para) > 240:
            break
    out = " ".join(para)
    return out[:240]


def _derive_tags(title: str, body_lines: list[str]) -> str:
    """Naive tag extraction: title tokens + a few notable upper-case identifiers
    from the body (LLM / RAG / etc.). Comma-separated, no spaces."""
    title_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]+", title)
    body_text = " ".join(body_lines[:30])
    body_idents = re.findall(r"\b([A-Z][A-Za-z0-9_]{2,}|[A-Z]{2,})\b", body_text)
    seen = []
    for t in title_tokens + body_idents:
        if t not in seen:
            seen.append(t)
        if len(seen) >= 6:
            break
    if not seen:
        # Fall back to the title's first CJK-ish word
        seen = [title.split()[0] if title.split() else title[:8]]
    return ",".join(seen)


def main():
    lines_orig = _read_readme()
    lines_for_headings = _strip_fences(lines_orig)
    sections = _parse_sections(lines_for_headings, lines_orig)
    if not sections:
        raise SystemExit("No H2/H3 headings found in README.md")

    RAG_DIR.mkdir(parents=True, exist_ok=True)
    XLSX_PATH.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    # Wipe stale .md files (keep _index.json — we'll rewrite it)
    for f in RAG_DIR.glob("*.md"):
        f.unlink()

    pages_meta: list[dict] = []
    xlsx_rows: list[dict] = []
    chapter = 0
    sub = 0
    cur_h2_title = ""

    for sec in sections:
        if sec["level"] == 2:
            chapter += 1
            sub = 0
            pid = str(chapter)
            cur_h2_title = sec["title"]
            category = cur_h2_title
        else:  # H3
            sub += 1
            pid = f"{chapter}-{sub}"
            category = cur_h2_title or sec["title"]

        body_lines = lines_orig[sec["body_start"]:sec["body_end"]]
        # Drop leading blank lines for the rendered .md
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()

        summary = _derive_summary(body_lines)
        tags = _derive_tags(sec["title"], body_lines)

        # Write the page body
        md_name = f"{pid}.md"
        md_text = f"{'###' if sec['level'] == 3 else '##'} {sec['title']}\n\n"
        md_text += "\n".join(body_lines).rstrip() + "\n"
        (RAG_DIR / md_name).write_text(md_text, encoding="utf-8")

        pages_meta.append({
            "id":         pid,
            "title":      sec["title"],
            "category":   category,
            "summary":    summary,
            "tags":       tags.split(",") if tags else [],
            "sort_order": len(pages_meta) + 1,
            "timestamp":  today,
        })
        xlsx_rows.append({
            "ブック名":  BOOK_TITLE,
            "ID":       pid,
            "タイトル":  sec["title"],
            "サマリー":  summary,
            "タグ":     tags,
            "カテゴリ": category,
            "本文":     md_name,
        })

    # Write _index.json
    index_payload = {
        "BOOK":  {"title": BOOK_TITLE},
        "PAGES": pages_meta,
    }
    (RAG_DIR / "_index.json").write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Write Excel
    df = pd.DataFrame(xlsx_rows,
                       columns=["ブック名", "ID", "タイトル", "サマリー", "タグ", "カテゴリ", "本文"])
    df.to_excel(XLSX_PATH, sheet_name=SHEET_NAME, index=False)

    print(f"[regen-pageindex] wrote {len(pages_meta)} pages")
    print(f"  → {RAG_DIR}")
    print(f"  → {XLSX_PATH}")


if __name__ == "__main__":
    main()
