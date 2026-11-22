"""Turn a TED notice HTML page into plain 'Label: value' text lines.

This is the "unstructured source" step: the output is what the extractor
(rule-based or LLM) reads. Standard library only.
"""

import re
from html.parser import HTMLParser


class _TextCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.chunks: list[str] = []
        self._skip = 0  # depth inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.chunks.append(data.strip())


def html_to_text(html: str) -> str:
    parser = _TextCollector()
    parser.feed(html)
    text = "\n".join(parser.chunks)
    # TED renders "Label", ":", "value" as separate elements -> join them.
    text = re.sub(r"\n:\s*\n", ": ", text)
    # Amounts are rendered as "138 100,00" + newline + "EUR" -> keep them together.
    text = re.sub(r"(\d,\d{2})\n([A-Z]{3})\b", r"\1 \2", text)
    return text


def excerpt(text: str, pattern: str, width: int = 160) -> str:
    """Short evidence snippet around the first match of `pattern` (for provenance)."""
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if not m:
        return ""
    start = max(0, m.start() - 20)
    return " ".join(text[start : m.end() + width].split())
