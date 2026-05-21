"""Convert HTML mail bodies to plain text for notifications."""
from __future__ import annotations

import re
from html import unescape

_BLOCK_BREAK_RE = re.compile(r"(?i)</(?:p|div|tr|li|h[1-6]|table|td|th|blockquote)>")
_HEAD_RE = re.compile(r"(?i)<head[\s\S]*?</head>")
_STYLE_RE = re.compile(r"(?i)<style[\s\S]*?</style>")
_SCRIPT_RE = re.compile(r"(?i)<script[\s\S]*?</script>")
_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")
_CDATA_RE = re.compile(r"<!\[CDATA\[([\s\S]*?)\]\]>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_CSS_LINE_RE = re.compile(
    r"^\s*(?:@media\b|[.#][\w-]+\s*\{|\{[^}]*\})",
    re.IGNORECASE,
)
_CSS_PROP_RE = re.compile(
    r"!important|(?:^|[;\s])(?:margin|padding|font-size|line-height|display|width|height)\s*:",
    re.IGNORECASE,
)


def _drop_css_artifact_lines(text: str) -> str:
    kept_lines: list[str] = []
    for line in text.split("\n"):
        trimmed = line.strip()
        if not trimmed:
            kept_lines.append(line)
            continue
        if _CSS_LINE_RE.search(trimmed) and _CSS_PROP_RE.search(trimmed):
            continue
        if trimmed.lower().startswith("@media"):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def html_to_plain_text(html: str) -> str:
    if not html:
        return ""
    text = html.replace("\r\n", "\n").replace("\r", "\n")
    text = _HEAD_RE.sub("", text)
    text = _STYLE_RE.sub("", text)
    text = _SCRIPT_RE.sub("", text)
    text = _COMMENT_RE.sub("", text)
    text = _CDATA_RE.sub(r"\1", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = unescape(text)
    text = _drop_css_artifact_lines(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def looks_like_html(text: str) -> bool:
    sample = (text or "")[:8000]
    return bool(re.search(r"<\s*(?:html|head|body|style|table|div|p|span)\b", sample, re.I))
