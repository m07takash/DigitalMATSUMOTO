"""URL取得ユーティリティ: ユーザー入力からURLを抽出し、安全性チェックの上でページ本文を取得する。

- SSRF対策: プライベート/ループバック/リンクローカルIPを拒否（DNS解決後も再確認）
- スキーム・拡張子・ブロックリスト・サイズ・タイムアウト制御
- 同一ドメイン内のサブページを幅優先で追加クロール可能
- 結果はテキストとしてtempフォルダに保存、ファイルパスのリストを返す
"""

import ipaddress
import os
import re
import socket
import time
from html import unescape
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

import DigiM_Util as dmu


DEFAULTS = {
    "TIMEOUT": 10,
    "MAX_BYTES": 2 * 1024 * 1024,
    "MAX_SUBPAGES": 5,
    "MAX_DEPTH": 1,
    "USER_AGENT": "DigiMatsuAgent/1.0 (+URL fetch; respects robots intent)",
    "BLOCKED_DOMAINS": [],
    "ALLOWED_DOMAINS": [],  # 非空ならホワイトリストモード（列挙されたドメインのみ許可）
    "BLOCKLIST_FILE": "",   # hosts形式 or 1行1ドメインの外部ブロックリスト
    "BLOCKED_EXTENSIONS": [
        ".exe", ".bat", ".cmd", ".msi", ".scr", ".dll",
        ".vbs", ".ps1", ".jar", ".apk", ".dmg",
    ],
}

# ダークウェブ/匿名ネットワーク系TLD（通常のHTTPでは解決不可／SSRF/プロキシ悪用抑止のため明示ブロック）
DARK_WEB_TLDS = (
    ".onion", ".i2p", ".bit", ".loki", ".exit",
)

# 主要アダルト系ドメインの最小ビルトインリスト。より広範なブロックは BLOCKLIST_FILE で提供される
# 公開カテゴリ別ブロックリスト（StevenBlack/hosts, UT1 "adult" 等）を指定してください
BUILTIN_ADULT_DOMAINS = frozenset({
    "pornhub.com", "xvideos.com", "xnxx.com", "xhamster.com", "redtube.com",
    "youporn.com", "tube8.com", "spankbang.com", "brazzers.com",
    "chaturbate.com", "livejasmin.com", "stripchat.com", "bongacams.com",
    "cam4.com", "camsoda.com", "myfreecams.com",
    "onlyfans.com", "fansly.com",
    "dmm.co.jp", "fanza.co.jp",
    "adultfriendfinder.com", "ashleymadison.com",
})

_BLOCKLIST_CACHE = {"path": None, "mtime": 0.0, "domains": frozenset()}


def _load_blocklist_file(path):
    """hosts形式 (`0.0.0.0 domain`) や 1行1ドメインのブロックリストをロード。更新時刻でキャッシュ。"""
    if not path:
        return frozenset()
    try:
        st = os.stat(path)
    except OSError:
        return frozenset()
    if _BLOCKLIST_CACHE["path"] == path and _BLOCKLIST_CACHE["mtime"] == st.st_mtime:
        return _BLOCKLIST_CACHE["domains"]
    domains = set()
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                # コメントを剥がしてからトークナイズ
                s = line.split("#", 1)[0].strip()
                if not s:
                    continue
                parts = s.split()
                # hosts形式: "0.0.0.0 example.com" / "127.0.0.1 example.com" / "::1 example.com"
                if len(parts) >= 2 and parts[0] in ("0.0.0.0", "127.0.0.1", "::", "::1"):
                    cand = parts[1]
                else:
                    cand = parts[0]
                cand = cand.lower().lstrip(".")
                if cand and "." in cand and not cand.startswith(("0.0.0.0", "127.0.0.1", "::")):
                    domains.add(cand)
    except Exception:
        return frozenset()
    result = frozenset(domains)
    _BLOCKLIST_CACHE.update({"path": path, "mtime": st.st_mtime, "domains": result})
    return result


def _host_matches(host, domains):
    """host が domains のいずれかと一致、またはそのサブドメインなら True。"""
    host = host.lower().lstrip(".")
    for d in domains:
        d = d.lower().lstrip(".")
        if not d:
            continue
        if host == d or host.endswith("." + d):
            return True
    return False

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def _get_settings():
    try:
        cfg = dmu.read_yaml_file("setting.yaml") or {}
    except Exception:
        cfg = {}
    raw = cfg.get("URL_FETCH", {}) or {}
    merged = dict(DEFAULTS)
    for k, v in raw.items():
        if v is not None:
            merged[k] = v
    return merged


def extract_urls(text):
    if not text:
        return []
    seen = set()
    urls = []
    for m in _URL_RE.finditer(text):
        u = m.group(0).rstrip(").,;:!?")
        u, _ = urldefrag(u)
        if u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def _is_private_ip(host):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _resolution_status(host):
    """('ok', '') / ('unresolvable', msg) / ('private', msg) を返す。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as e:
        return "unresolvable", f"DNS resolution failed: {e}"
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            return "private", f"host resolves to non-public IP: {addr}"
    return "ok", ""


def is_safe_url(url, settings=None):
    """URLが安全かを判定し、(ok: bool, reason: str) を返す。"""
    settings = settings or _get_settings()
    try:
        p = urlparse(url)
    except Exception as e:
        return False, f"URL parse error: {e}"

    if p.scheme.lower() not in ("http", "https"):
        return False, f"unsupported scheme: {p.scheme}"

    host = (p.hostname or "").strip().lower()
    if not host:
        return False, "hostname missing"

    if host in ("localhost",) or host.endswith(".localhost"):
        return False, "localhost is blocked"

    # ダークウェブ/匿名ネットワーク系TLD
    for tld in DARK_WEB_TLDS:
        if host == tld.lstrip(".") or host.endswith(tld):
            return False, f"dark-web TLD blocked: {tld}"

    # ホワイトリストモード（非空のときのみ有効）
    allowed = [d for d in (settings.get("ALLOWED_DOMAINS") or []) if d and str(d).strip()]
    if allowed and not _host_matches(host, allowed):
        return False, "not in ALLOWED_DOMAINS (whitelist mode)"

    # ビルトイン・アダルトドメイン
    if _host_matches(host, BUILTIN_ADULT_DOMAINS):
        return False, "adult content domain blocked (builtin)"

    # setting.yaml の BLOCKED_DOMAINS
    blocked_domains = [str(b).lower().strip() for b in (settings.get("BLOCKED_DOMAINS") or []) if b]
    if _host_matches(host, blocked_domains):
        return False, "domain blocked (configured)"

    # 外部ブロックリストファイル（hosts形式等）
    external = _load_blocklist_file(settings.get("BLOCKLIST_FILE") or "")
    if external and _host_matches(host, external):
        return False, "domain blocked (external blocklist)"

    if _is_private_ip(host):
        return False, "private/loopback IP is blocked"

    # 拡張子チェック（DNSより先に軽量判定）
    path = (p.path or "").lower()
    for ext in settings.get("BLOCKED_EXTENSIONS", []) or []:
        if path.endswith(ext.lower()):
            return False, f"blocked file extension: {ext}"

    # 解決先のIPも再確認（DNS rebinding / SSRF対策）
    status, msg = _resolution_status(host)
    if status != "ok":
        return False, msg

    return True, ""


def _read_limited(resp, max_bytes):
    total = 0
    chunks = []
    for chunk in resp.iter_content(chunk_size=8192):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            chunks.append(chunk[: max(0, max_bytes - (total - len(chunk)))])
            return b"".join(chunks), True
        chunks.append(chunk)
    return b"".join(chunks), False


def _extract_text(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    title = (soup.title.string.strip() if soup.title and soup.title.string else "")
    # 本文抽出は <main>/<article> を優先、なければ body
    body = soup.find("main") or soup.find("article") or soup.body or soup
    text = body.get_text(separator="\n", strip=True)
    text = unescape(text)
    # リンク一覧
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute, _ = urldefrag(urljoin(base_url, href))
        links.append(absolute)
    return title, text, links


def fetch_page(url, settings=None):
    """単一URLを取得し、{ok, url, final_url, title, text, links, error, truncated} を返す。"""
    settings = settings or _get_settings()
    ok, reason = is_safe_url(url, settings)
    if not ok:
        return {"ok": False, "url": url, "error": f"blocked: {reason}"}
    headers = {
        "User-Agent": settings["USER_AGENT"],
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
        "Accept-Language": "ja,en;q=0.7",
    }
    try:
        with requests.get(
            url, headers=headers, timeout=settings["TIMEOUT"],
            stream=True, allow_redirects=True,
        ) as resp:
            # リダイレクト先も安全性を再チェック
            final_url = resp.url
            ok2, reason2 = is_safe_url(final_url, settings)
            if not ok2:
                return {"ok": False, "url": url, "final_url": final_url,
                        "error": f"redirect blocked: {reason2}"}
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "text" not in ctype:
                return {"ok": False, "url": url, "final_url": final_url,
                        "error": f"unsupported content-type: {ctype}"}
            data, truncated = _read_limited(resp, settings["MAX_BYTES"])
    except requests.RequestException as e:
        return {"ok": False, "url": url, "error": f"request error: {e}"}

    encoding = resp.encoding or "utf-8"
    try:
        html = data.decode(encoding, errors="replace")
    except LookupError:
        html = data.decode("utf-8", errors="replace")
    title, text, links = _extract_text(html, final_url)
    return {
        "ok": True, "url": url, "final_url": final_url,
        "title": title, "text": text, "links": links,
        "truncated": truncated, "error": "",
    }


def fetch_with_subpages(url, settings=None):
    """入力URLから同一ドメイン内のサブページをBFSで追加取得し、ページ結果のリストを返す。"""
    settings = settings or _get_settings()
    max_pages = int(settings.get("MAX_SUBPAGES", 5)) + 1
    max_depth = int(settings.get("MAX_DEPTH", 1))

    seed = fetch_page(url, settings)
    results = [seed]
    if not seed.get("ok") or max_depth < 1 or max_pages <= 1:
        return results

    seed_host = (urlparse(seed.get("final_url") or url).hostname or "").lower()
    visited = {seed.get("final_url") or url}
    queue = [(l, 1) for l in seed.get("links", [])]

    while queue and len(results) < max_pages:
        next_url, depth = queue.pop(0)
        if next_url in visited:
            continue
        if depth > max_depth:
            continue
        host = (urlparse(next_url).hostname or "").lower()
        if host != seed_host:
            continue
        visited.add(next_url)
        page = fetch_page(next_url, settings)
        results.append(page)
        if page.get("ok") and depth < max_depth:
            for l in page.get("links", []):
                if l not in visited:
                    queue.append((l, depth + 1))
    return results


def _format_page(page):
    header = [
        f"URL: {page.get('url','')}",
    ]
    if page.get("final_url") and page["final_url"] != page.get("url"):
        header.append(f"Final-URL: {page['final_url']}")
    if page.get("title"):
        header.append(f"Title: {page['title']}")
    if page.get("truncated"):
        header.append("Note: content was truncated (size limit)")
    header.append("-" * 40)
    return "\n".join(header) + "\n" + (page.get("text") or "")


def fetch_urls_from_text(text, temp_folder, include_subpages=False, settings=None):
    """テキスト中のURLを取得し、一時フォルダに.txtで保存。
    戻り値: {"saved_paths": [...], "summaries": [...], "blocked": [...]}
    """
    settings = settings or _get_settings()
    urls = extract_urls(text)
    out_paths = []
    summaries = []
    blocked = []
    if not urls:
        return {"saved_paths": out_paths, "summaries": summaries, "blocked": blocked}

    os.makedirs(temp_folder, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    for i, url in enumerate(urls):
        ok, reason = is_safe_url(url, settings)
        if not ok:
            blocked.append({"url": url, "reason": reason})
            continue
        pages = fetch_with_subpages(url, settings) if include_subpages else [fetch_page(url, settings)]
        good_pages = [p for p in pages if p.get("ok")]
        failed_pages = [p for p in pages if not p.get("ok")]
        for fp in failed_pages:
            blocked.append({"url": fp.get("url"), "reason": fp.get("error", "failed")})
        if not good_pages:
            continue

        body = "\n\n".join(_format_page(p) for p in good_pages)
        host = urlparse(good_pages[0].get("final_url") or url).hostname or "site"
        safe_host = dmu.sanitize_filename(host, replacement="_", keep_unicode=False)
        file_name = f"url_{ts}_{i+1:02d}_{safe_host}.txt"
        file_path = os.path.join(temp_folder, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(body)
        out_paths.append(file_path)
        summaries.append({
            "url": url,
            "pages": len(good_pages),
            "file": file_name,
            "title": good_pages[0].get("title", ""),
        })

    return {"saved_paths": out_paths, "summaries": summaries, "blocked": blocked}
