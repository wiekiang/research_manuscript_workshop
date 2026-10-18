"""Located text extraction for quarantined sources. Every segment keeps its character span in the joined text,
its heading path and (for PDFs) its page, so extracted rules and evidence can cite an exact locator."""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import asdict, dataclass, field

from rp_contracts.textmatch import find_span, normalize_for_match  # noqa: F401

BLOCKS = "h1,h2,h3,h4,h5,h6,p,li,td,th,dt,dd,pre,blockquote,caption,figcaption,div,section,article,summary"
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
STRIP = "script,style,noscript,template,iframe,svg,canvas,object,embed,form,nav,footer"


@dataclass
class Segment:
    start: int
    end: int
    kind: str
    section: list[str]
    page: int | None = None


@dataclass
class LocatedText:
    text: str
    segments: list[Segment] = field(default_factory=list)
    title: str | None = None
    media_type: str = "text/plain"
    extractor: str = "rp-located-text/1"

    def to_dict(self) -> dict:
        return {"text": self.text, "segments": [asdict(s) for s in self.segments], "title": self.title,
                "media_type": self.media_type, "extractor": self.extractor}

    @classmethod
    def from_dict(cls, d: dict) -> LocatedText:
        return cls(text=d["text"], segments=[Segment(**s) for s in d["segments"]], title=d.get("title"),
                   media_type=d.get("media_type", "text/plain"), extractor=d.get("extractor", "rp-located-text/1"))

    def segment_at(self, offset: int) -> Segment | None:
        for s in self.segments:
            if s.start <= offset < s.end:
                return s
        return None

    def locator(self, start: int, end: int) -> dict:
        seg = self.segment_at(start)
        return {"char_start": start, "char_end": end, "section": " > ".join(seg.section) if seg else None,
                "page": seg.page if seg else None}


def _clean(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    return re.sub(r"\s+", " ", s).strip()


def find_quote(lt: LocatedText, quote: str) -> tuple[int, int] | None:
    """Locate a quote in the text, tolerant to whitespace/case/punctuation-variant differences only."""
    return find_span(lt.text, quote)


def extract_html(data: bytes) -> LocatedText:
    from selectolax.lexbor import LexborHTMLParser as HTMLParser

    tree = HTMLParser(data.decode("utf-8", "replace"))
    for node in tree.css(STRIP):
        node.decompose()
    title_node = tree.css_first("title")
    title = _clean(title_node.text()) if title_node else None
    root = tree.body or tree.root
    parts: list[str] = []
    segments: list[Segment] = []
    path: list[tuple[int, str]] = []
    offset = 0
    for node in root.css(BLOCKS):
        # Emit headings and leaf blocks only, so nested blocks are never duplicated.
        if node.tag not in HEADINGS and any(d.mem_id != node.mem_id for d in node.css(BLOCKS)):
            continue
        txt = _clean(node.text(separator=" "))
        if not txt:
            continue
        if node.tag in HEADINGS:
            level = int(node.tag[1])
            path = [p for p in path if p[0] < level] + [(level, txt[:200])]
        seg_section = [p[1] for p in path]
        start = offset
        parts.append(txt)
        offset += len(txt)
        segments.append(Segment(start, offset, node.tag, seg_section))
        parts.append("\n")
        offset += 1
    return LocatedText("".join(parts), segments, title, "text/html")


def extract_pdf(data: bytes) -> LocatedText:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("encrypted PDF cannot be parsed")
    parts: list[str] = []
    segments: list[Segment] = []
    offset = 0
    section: list[str] = []
    for pno, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        for para in re.split(r"\n\s*\n|\n(?=[A-Z0-9][^\n]{0,80}\n)", raw):
            txt = _clean(para)
            if not txt:
                continue
            if len(txt) < 80 and not txt.endswith(".") and txt[:1].isupper():
                section = [txt]
                kind = "heading"
            else:
                kind = "para"
            start = offset
            parts.append(txt)
            offset += len(txt)
            segments.append(Segment(start, offset, kind, list(section), pno))
            parts.append("\n")
            offset += 1
    return LocatedText("".join(parts), segments, None, "application/pdf")


def extract_plain(data: bytes) -> LocatedText:
    parts, segments, offset = [], [], 0
    section: list[str] = []
    for para in re.split(r"\n\s*\n", data.decode("utf-8", "replace")):
        txt = _clean(para)
        if not txt:
            continue
        if txt.startswith("#"):
            section = [txt.lstrip("# ")]
        segments.append(Segment(offset, offset + len(txt), "para", list(section)))
        parts.append(txt + "\n")
        offset += len(txt) + 1
    return LocatedText("".join(parts), segments, None, "text/plain")


def extract(data: bytes, media_type: str) -> LocatedText:
    if media_type in ("text/html", "application/xhtml+xml"):
        return extract_html(data)
    if media_type == "application/pdf":
        return extract_pdf(data)
    return extract_plain(data)
