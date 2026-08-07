# DigiM_Guardrail.py
# ============================================================================
# Outbound guardrail for third-party web-search APIs.
#
# The search query is assembled from the user's chat input (directly, or via
# the LLM-generated search query), so anything confidential the user typed can
# leave the system when that query is posted to Perplexity / OpenAI / Google /
# Anthropic. This module redacts it at that boundary.
#
# Scope is deliberately narrow: it guards the *web-search* egress only. The
# main LLM call and RAG retrieval are untouched.
#
# Detection is pure regex + Luhn — deterministic, offline, no API cost, so it
# cannot itself leak the text it is inspecting.
#
# Config: user/common/mst/web_search_guard.json (falls back to
# sample_web_search_guard.json, then to DEFAULT_CONFIG below).
#
#   MODE: "mask"  redact matches and continue searching (default)
#         "block" abort the search when anything matches
#         "off"   disable the guard
#
# Findings never carry the matched text — only rule name and hit count — so
# logs stay safe to keep.
# ============================================================================

import os
import re
import logging

logger = logging.getLogger(__name__)

_MST_DIR = "user/common/mst"
_CONFIG_NAME = "web_search_guard.json"
_SAMPLE_NAME = "sample_web_search_guard.json"

# Built-in rules. Ordered most-specific first so a provider key is labelled as
# that provider rather than by the generic assignment rule.
DEFAULT_RULES = [
    # --- credentials / secrets (high confidence) ---
    {"name": "anthropic_api_key", "pattern": r"sk-ant-[A-Za-z0-9_\-]{20,}"},
    {"name": "openai_api_key", "pattern": r"sk-(?!ant-)[A-Za-z0-9_\-]{20,}"},
    {"name": "github_token", "pattern": r"gh[pousr]_[A-Za-z0-9]{30,}"},
    {"name": "aws_access_key_id", "pattern": r"AKIA[0-9A-Z]{16}"},
    {"name": "google_api_key", "pattern": r"AIza[0-9A-Za-z_\-]{35}"},
    {"name": "slack_token", "pattern": r"xox[baprs]-[0-9A-Za-z\-]{10,}"},
    {"name": "jwt", "pattern": r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"},
    {"name": "private_key_block",
     "pattern": r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"},
    {"name": "bearer_token", "pattern": r"[Bb]earer\s+[A-Za-z0-9._\-]{20,}"},
    # Generic `key: value` secrets. Requires a secret-ish name on the left so
    # ordinary prose ("password" alone) does not trip it.
    {"name": "credential_assignment",
     "pattern": r"(?i)\b(api[_\-]?key|secret[_\-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*[\"']?[^\s\"',;]{6,}"},

    # --- personal data ---
    {"name": "email", "pattern": r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"},
    {"name": "jp_mobile", "pattern": r"\b0[789]0[-\s]?\d{4}[-\s]?\d{4}\b"},
    {"name": "jp_landline", "pattern": r"\b0\d{1,4}-\d{1,4}-\d{4}\b"},
    # Luhn-validated below; the regex only nominates candidates.
    {"name": "credit_card", "pattern": r"\b(?:\d[ \-]?){13,19}\b", "validator": "luhn"},
    # 12 consecutive digits. Off by default: too many false positives
    # (order numbers, IDs). Enable in the config when it matters.
    {"name": "jp_mynumber", "pattern": r"\b\d{12}\b", "enabled": False},
]

DEFAULT_CONFIG = {
    "MODE": "mask",
    "REPLACEMENT": "[REDACTED:{name}]",
    "RULES": DEFAULT_RULES,
    # Literal strings to redact — project codenames, client names, etc.
    "KEYWORDS": [],
    "KEYWORD_RULE_NAME": "custom_keyword",
}

_BLOCK_MESSAGE = (
    "【Web検索を中止しました】検索クエリに秘匿情報が含まれる可能性があるため、"
    "外部APIへの送信を行いませんでした。入力内容を確認してください。"
)


def _luhn_ok(value):
    digits = [int(c) for c in re.sub(r"\D", "", value)]
    if not 13 <= len(digits) <= 19:
        return False
    total, parity = 0, len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


_VALIDATORS = {"luhn": _luhn_ok}


def load_config(path=None):
    """Operational config -> bundled sample -> built-in defaults."""
    import json
    candidates = [path] if path else [
        os.path.join(_MST_DIR, _CONFIG_NAME),
        os.path.join(_MST_DIR, _SAMPLE_NAME),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            try:
                with open(p, encoding="utf-8") as f:
                    cfg = json.load(f)
                merged = dict(DEFAULT_CONFIG)
                merged.update(cfg or {})
                return merged
            except Exception as e:
                logger.warning(f"[guardrail] config load failed ({p}): {e}")
    return dict(DEFAULT_CONFIG)


def redact(text, config=None):
    """Return (redacted_text, findings).

    findings: [{"rule": <name>, "count": <int>}] — never the matched value.
    """
    if not text or not isinstance(text, str):
        return text, []
    cfg = config or load_config()
    replacement_tpl = cfg.get("REPLACEMENT") or DEFAULT_CONFIG["REPLACEMENT"]
    counts = {}
    out = text

    for rule in cfg.get("RULES") or []:
        if not rule.get("enabled", True):
            continue
        name, pattern = rule.get("name"), rule.get("pattern")
        if not name or not pattern:
            continue
        validator = _VALIDATORS.get(rule.get("validator"))
        try:
            compiled = re.compile(pattern)
        except re.error as e:
            logger.warning(f"[guardrail] invalid pattern for {name}: {e}")
            continue

        def _sub(m, _name=name, _validator=validator):
            if _validator and not _validator(m.group(0)):
                return m.group(0)          # candidate failed validation: keep
            counts[_name] = counts.get(_name, 0) + 1
            return replacement_tpl.format(name=_name)

        out = compiled.sub(_sub, out)

    # Literal keywords last so they still catch anything left in place.
    kw_name = cfg.get("KEYWORD_RULE_NAME") or "custom_keyword"
    for kw in cfg.get("KEYWORDS") or []:
        if not kw:
            continue
        hits = out.count(kw)
        if hits:
            counts[kw_name] = counts.get(kw_name, 0) + hits
            out = out.replace(kw, replacement_tpl.format(name=kw_name))

    findings = [{"rule": k, "count": v} for k, v in sorted(counts.items())]
    return out, findings


def guard_web_query(text, config=None):
    """Guard one outbound web-search query.

    Returns (safe_text, findings, blocked). When blocked is True the caller
    must not call the external API.
    """
    cfg = config or load_config()
    mode = (cfg.get("MODE") or "mask").lower()
    if mode == "off":
        return text, [], False

    redacted, findings = redact(text, cfg)
    if not findings:
        return text, [], False

    summary = ", ".join(f"{f['rule']}x{f['count']}" for f in findings)
    if mode == "block":
        logger.warning(f"[guardrail] web search blocked: {summary}")
        return text, findings, True
    logger.info(f"[guardrail] web search query redacted: {summary}")
    return redacted, findings, False


def block_message(findings=None):
    """User-facing text returned in place of search results when blocked."""
    if not findings:
        return _BLOCK_MESSAGE
    detected = ", ".join(f"{f['rule']}({f['count']})" for f in findings)
    return f"{_BLOCK_MESSAGE}\n検出: {detected}"
