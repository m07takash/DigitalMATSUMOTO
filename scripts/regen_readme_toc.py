#!/usr/bin/env python3
"""
Regenerate the collapsible table of contents in README.md and README.en.md.

Idempotent: detects and replaces an existing <details>…TOC…</details> block
right after the H1 title. Add new H2/H3 sections to the README and re-run
this script — the TOC stays in sync without touching anything else.

Usage:
    python3 scripts/regen_readme_toc.py
    python3 scripts/regen_readme_toc.py --check        # exit non-zero if a refresh would change anything (CI-friendly)
    python3 scripts/regen_readme_toc.py path/to/README.md "📑 Custom label"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Targets refreshed by default. (file_path, summary_label) pairs.
DEFAULT_TARGETS = [
    ("README.md", "📑 目次（クリックで展開）"),
    ("README.en.md", "📑 Table of Contents (click to expand)"),
]


def github_anchor(text: str) -> str:
    """Reproduce GitHub's auto-anchor scheme for a header.

    Lowercase, whitespace → hyphens, drop punctuation that GitHub strips
    (but keep alphanumerics, hyphens, underscores, and unicode word chars
    so Japanese / CJK headers anchor correctly).
    """
    t = text.replace("`", "")
    t = t.lower()
    t = re.sub(r"\s+", "-", t)
    t = re.sub(r"[^\w\-　-鿿぀-ゟ゠-ヿ]", "", t)
    return t


def extract_headers(src: str) -> list[tuple[int, str]]:
    """Return (level, title) for every H2/H3 outside fenced code blocks."""
    in_fence = False
    fence_marker = None
    headers: list[tuple[int, str]] = []
    for line in src.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            m = re.match(r"^(```+|~~~+)", stripped)
            if m:
                tok = m.group(1)
                if not in_fence:
                    in_fence = True
                    fence_marker = tok
                elif tok.startswith(fence_marker[0]) and len(tok) >= len(fence_marker):
                    in_fence = False
                    fence_marker = None
            continue
        if in_fence:
            continue
        if line.startswith("## ") and not line.startswith("### "):
            headers.append((2, line[3:].strip()))
        elif line.startswith("### ") and not line.startswith("#### "):
            headers.append((3, line[4:].strip()))
    return headers


def build_toc(headers: list[tuple[int, str]]) -> str:
    """Render a nested markdown list, H2 at top, H3 indented under it."""
    lines = []
    for lvl, title in headers:
        indent = "  " * (lvl - 2)
        lines.append(f"{indent}- [{title}](#{github_anchor(title)})")
    return "\n".join(lines)


def build_toc_block(headers: list[tuple[int, str]], summary_label: str) -> str:
    """Wrap the TOC in a <details> block so it collapses by default."""
    return (
        f"<details>\n"
        f"<summary><strong>{summary_label}</strong></summary>\n\n"
        f"{build_toc(headers)}\n\n"
        f"</details>\n"
    )


def regenerate(file_path: Path, summary_label: str) -> tuple[bool, int]:
    """Refresh the TOC in `file_path`. Returns (changed, header_count)."""
    if not file_path.exists():
        raise FileNotFoundError(file_path)
    src = file_path.read_text(encoding="utf-8")
    original = src

    # Remove an existing TOC (if any) so we can reinsert a fresh one.
    src = re.sub(
        r"<details>\s*\n<summary>[\s\S]*?</summary>\s*\n\n[\s\S]*?</details>\s*\n+",
        "", src, count=1,
    )

    headers = extract_headers(src)
    block = build_toc_block(headers, summary_label)

    # Insert right after the H1 title with exactly one blank line on either side.
    # Any existing blank lines between the title and the next real content are
    # consumed so repeated runs produce a byte-identical file (idempotency).
    lines = src.split("\n")
    title_index = None
    next_content_index = None
    for i, line in enumerate(lines):
        if line.startswith("# ") and not line.startswith("## "):
            title_index = i
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            next_content_index = j
            break
    if title_index is None:
        raise RuntimeError(f"No H1 title found in {file_path}")

    block_lines = block.rstrip().split("\n")
    new_lines = (
        lines[: title_index + 1]
        + [""]
        + block_lines
        + [""]
        + lines[next_content_index:]
    )
    new_src = "\n".join(new_lines)
    changed = new_src != original
    if changed:
        file_path.write_text(new_src, encoding="utf-8")
    return changed, len(headers)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="*",
                        help="Optional file path(s) to refresh. Pairs of (path label) are "
                             "supported; if a single path is given without a label, the "
                             "default label is used.")
    parser.add_argument("--check", action="store_true",
                        help="Exit non-zero if any TOC would have been updated.")
    args = parser.parse_args()

    if args.files:
        # Pair up: every two positional args = (path, label); odd-out single path uses default label.
        targets = []
        i = 0
        while i < len(args.files):
            path = args.files[i]
            if i + 1 < len(args.files) and not args.files[i + 1].endswith((".md", ".markdown")):
                targets.append((path, args.files[i + 1]))
                i += 2
            else:
                targets.append((path, "📑 Table of Contents (click to expand)"))
                i += 1
    else:
        targets = DEFAULT_TARGETS

    any_changed = False
    for path_str, label in targets:
        path = Path(path_str)
        if args.check:
            # Dry-run: compare without writing
            original = path.read_text(encoding="utf-8")
            # Use a temp approach: regenerate writes; we'll restore if check mode.
            changed, n_headers = regenerate(path, label)
            if changed:
                # Revert so check mode doesn't mutate files
                path.write_text(original, encoding="utf-8")
                print(f"[stale] {path} (would refresh {n_headers} headers)")
                any_changed = True
            else:
                print(f"[ok]    {path} ({n_headers} headers)")
        else:
            changed, n_headers = regenerate(path, label)
            verb = "refreshed" if changed else "no change"
            print(f"[{verb}] {path} ({n_headers} headers)")

    if args.check and any_changed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
