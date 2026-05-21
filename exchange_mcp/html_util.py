"""Convert HTML mail bodies to plain text for notifications."""
from __future__ import annotations

import re
from html import unescape


_BLOCK_BREAK_RE = re.compile(r"(?i)</(?:p|div|tr|li|h[1-6])>")
_TAG_RE = re.compile(r"<[^>]+>")


def html_to_plain_text(html: str) -> str:
    if not html:
        return ""
    text = html.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
