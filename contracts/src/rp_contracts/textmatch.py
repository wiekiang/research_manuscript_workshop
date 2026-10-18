"""Whitespace/case/punctuation-variant tolerant quote matching (used for quote verification and change detection)."""

from __future__ import annotations

import re
import unicodedata

_PUNCT = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "−": "-"}


def normalize_for_match(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    s = "".join(_PUNCT.get(c, c) for c in s)
    return re.sub(r"\s+", " ", s).strip()


def find_span(text: str, quote: str) -> tuple[int, int] | None:
    """Return the (start, end) offsets of `quote` in the original `text`, or None."""
    if not quote or len(quote.strip()) < 8:
        return None
    norm_q = normalize_for_match(quote)
    chars: list[str] = []
    index: list[int] = []
    prev_space = False
    for i, ch in enumerate(unicodedata.normalize("NFKC", text)):
        c = _PUNCT.get(ch.lower(), ch.lower())
        if c.isspace():
            if prev_space:
                continue
            c = " "
            prev_space = True
        else:
            prev_space = False
        chars.append(c)
        index.append(i)
    pos = "".join(chars).find(norm_q)
    if pos < 0:
        return None
    return index[pos], index[min(pos + len(norm_q), len(index)) - 1] + 1
