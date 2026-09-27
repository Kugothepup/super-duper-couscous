"""Text normalisation and comparison shared by ingest, verify and the analysis steps."""
from __future__ import annotations

import difflib
import html
import re
import unicodedata
from html.parser import HTMLParser

QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})


def clean_quotes(s: str) -> str:
    """Curly quotes to straight ones (the skill applies this to every transcription)."""
    return s.translate(QUOTES)


def loose(s: str | None) -> str:
    """The skill's `norm`: lowercase, straight quotes, punctuation removed, spaces collapsed.
    Used for duplicate detection and OCR word matching, never to accept a quote."""
    s = unicodedata.normalize("NFKC", clean_quotes(s or "")).lower()
    s = s.replace("'", "")
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tidy(s: str | None) -> str:
    """Whitespace and quote-mark normalisation only: case, words and punctuation are kept."""
    s = unicodedata.normalize("NFKC", clean_quotes(s or ""))
    return re.sub(r"\s+", " ", s).strip()


def shingles(text: str, k: int = 5) -> set[str]:
    w = loose(text).split()
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def word_diff(said: str, source: str) -> str:
    """Word-level difference: [-source words dropped-] {+words added+}."""
    a, b = source.split(), said.split()
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(" ".join(a[i1:i2]))
            continue
        if i2 > i1:
            out.append("[-" + " ".join(a[i1:i2]) + "-]")
        if j2 > j1:
            out.append("{+" + " ".join(b[j1:j2]) + "+}")
    return " ".join(out)


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_text(page: str) -> str:
    p = _Text()
    p.feed(page)
    return html.unescape(" ".join(p.parts))
