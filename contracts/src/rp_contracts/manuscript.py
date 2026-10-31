"""Manuscript contracts (PRODUCT_SPEC §2.10): span-level provenance, writer agent IO, deterministic span checks and
rendering to the template-independent LaTeX document model.

Every sentence-level span declares its kind. Factual kinds (prior_work, observed_result) must cite claim IDs or
result keys; interpretation/hypothesis/limitation spans are labelled but need no evidence link. The writer cannot
mint bibliography entries: citations are derived from the papers that support each cited claim.
"""

from __future__ import annotations

import difflib
import re
from typing import Literal

from pydantic import BaseModel, Field

from .latexdoc import Author, Block, ManuscriptDocument, Section

SpanKind = Literal["prior_work", "observed_result", "method", "interpretation", "hypothesis", "limitation",
                   "contribution_statement", "framing"]
FACTUAL = {"prior_work", "observed_result"}

SECTION_PLANS: dict[str, list[tuple[str, str]]] = {
    "default": [("abstract", "Abstract"), ("introduction", "Introduction"), ("related_work", "Related Work"),
                ("method", "Method"), ("results", "Results"), ("discussion", "Discussion"),
                ("limitations", "Limitations"), ("conclusion", "Conclusion")],
    "theoretical": [("abstract", "Abstract"), ("introduction", "Introduction"), ("related_work", "Related Work"),
                    ("framework", "Conceptual Framework"), ("argument", "Argument"), ("evaluation", "Evaluation"),
                    ("discussion", "Discussion"), ("conclusion", "Conclusion")],
    "narrative_review": [("abstract", "Abstract"), ("introduction", "Introduction"), ("scope", "Scope and Selection"),
                         ("synthesis", "Synthesis"), ("argument", "Argument"), ("discussion", "Discussion"),
                         ("conclusion", "Conclusion")],
}
GAP_SECTIONS = ("abstract", "introduction", "discussion", "conclusion")


def plan_for(study_type: str | None) -> list[tuple[str, str]]:
    return SECTION_PLANS.get(study_type or "", SECTION_PLANS["default"])


class Span(BaseModel):
    span_id: str
    text: str
    kind: SpanKind
    claim_ids: list[str] = Field(default_factory=list, description="claim keys, e.g. CLM-0003")
    result_keys: list[str] = Field(default_factory=list, description="result keys, e.g. RES-001")
    origin: Literal["ai", "human"] = "ai"
    protected: bool = False


class Paragraph(BaseModel):
    spans: list[Span]


class TableRef(BaseModel):
    caption: str
    result_keys: list[str]


class FigureRef(BaseModel):
    caption: str
    artifact_id: str
    file_name: str


class ManuscriptSection(BaseModel):
    key: str
    heading: str
    paragraphs: list[Paragraph] = Field(default_factory=list)
    tables: list[TableRef] = Field(default_factory=list)
    figures: list[FigureRef] = Field(default_factory=list)


class ManuscriptContent(BaseModel):
    title: str
    mode: Literal["paper", "proposal"] = "paper"
    sections: list[ManuscriptSection]
    keywords: list[str] = Field(default_factory=list)
    acknowledgments: str | None = None

    def section(self, key: str) -> ManuscriptSection | None:
        return next((s for s in self.sections if s.key == key), None)

    def spans(self):
        for s in self.sections:
            for p in s.paragraphs:
                for sp in p.spans:
                    yield s, sp

    def tables(self):
        for s in self.sections:
            for i, t in enumerate(s.tables):
                yield s, i, t


# --------------------------------------------------------------------------- writer agent IO
class DraftSpan(BaseModel):
    text: str
    kind: SpanKind
    claim_ids: list[str]
    result_keys: list[str]


class DraftParagraph(BaseModel):
    spans: list[DraftSpan]


class SectionDraft(BaseModel):
    key: str
    heading: str
    paragraphs: list[DraftParagraph]
    tables: list[TableRef]
    rationale: str = Field(description="what this draft does and why (shown with the diff)")
    open_questions: list[str]


class WriterOutput(BaseModel):
    sections: list[SectionDraft]


# --------------------------------------------------------------------------- deterministic span checks
DEMONSTRATED = re.compile(r"\b(we (demonstrate|show|establish|prove|confirm)|(fill|close|resolve)[sd]? (this|the) gap|"
                          r"first (study|work|paper) to|novel contribution|definitively)\b", re.I)
GAP_FILLED = re.compile(r"\b(fill|close|resolve)[sd]? (this|the) gap\b", re.I)
CAUSAL = re.compile(r"\b(causes?|caused|leads? to|results? in|due to|because of|drives?)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(%?)")


def _numbers(text: str) -> set[float]:
    out = set()
    for m in NUMBER.finditer(text):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        out.add(round(v, 4))
        if m.group(2) == "%":
            out.add(round(v / 100, 4))
    return out


def check_span(sp: Span, ctx: dict) -> list[dict]:
    """ctx: claims {key: {status, gate_eligible, category, proposition}}, results {key: {metrics, assurance}},
    h3_rows_supported (bool), gap_status (str|None), mode."""
    issues = []
    claims, results = ctx["claims"], ctx["results"]
    if sp.kind in FACTUAL and not (sp.claim_ids or sp.result_keys):
        issues.append({"code": "unsupported_factual_span", "severity": "major",
                       "message": "factual sentence without a claim or result link (unresolved-claim queue)"})
    for cid in sp.claim_ids:
        c = claims.get(cid)
        if c is None:
            issues.append({"code": "unknown_claim", "severity": "blocker", "message": f"{cid} is not a registered claim"})
        elif not c["gate_eligible"]:
            sev = "blocker" if c.get("critical") else "major"
            issues.append({"code": "unverified_claim", "severity": sev,
                           "message": f"{cid} is not verified under the current policy"})
    for rk in sp.result_keys:
        r = results.get(rk)
        if r is None:
            issues.append({"code": "unknown_result", "severity": "blocker", "message": f"{rk} is not a committed result"})
        elif ctx.get("mode") == "proposal":
            issues.append({"code": "result_in_proposal", "severity": "blocker",
                           "message": "results cannot be reported as observed before H3"})
    if sp.kind == "observed_result" and ctx.get("mode") == "proposal":
        issues.append({"code": "observed_before_h3", "severity": "blocker",
                       "message": "the study has no H3-approved results; write a planned analysis instead"})
    nums = _numbers(sp.text)
    if nums and (sp.result_keys or sp.claim_ids) and sp.kind in FACTUAL:
        allowed: set[float] = set()
        for rk in sp.result_keys:
            for m in (results.get(rk) or {}).get("metrics", []):
                for k in ("value", "n", "numerator", "denominator", "ci_low", "ci_high"):
                    if m.get(k) is not None:
                        allowed.add(round(float(m[k]), 4))
                        if k == "value" and float(m[k]) <= 1:
                            allowed.add(round(float(m[k]) * 100, 4))
        for cid in sp.claim_ids:
            allowed |= _numbers((claims.get(cid) or {}).get("proposition", ""))
        unexplained = sorted(n for n in nums if n not in allowed and not (1900 <= n <= 2100))
        if unexplained:
            issues.append({"code": "number_mismatch", "severity": "major",
                           "message": f"numbers not found in the cited results/claims: {unexplained}"})
    if DEMONSTRATED.search(sp.text):
        if not ctx.get("h3_rows_supported"):
            issues.append({"code": "demonstrated_contribution_without_h3", "severity": "blocker",
                           "message": "claims of demonstrated contribution need an H3-approved supported matrix row"})
        if GAP_FILLED.search(sp.text) and ctx.get("gap_status") != "addressed":
            issues.append({"code": "gap_overstated", "severity": "blocker",
                           "message": f"the researcher assessed the gap as {ctx.get('gap_status') or 'unassessed'}"})
    if CAUSAL.search(sp.text) and sp.kind in FACTUAL:
        if not any((claims.get(c) or {}).get("category") == "causal" and (claims.get(c) or {}).get("gate_eligible")
                   for c in sp.claim_ids):
            issues.append({"code": "causal_language", "severity": "major",
                           "message": "causal wording without a verified causal claim; weaken the wording or verify"})
    return issues


def check_table(t: TableRef, ctx: dict) -> list[dict]:
    """Deterministic checks for one result table. Tables are rendered from committed result metrics and never from
    writer prose, so a table naming a key that is not a committed result renders a captioned table with no rows at
    all. Report that instead of emitting the empty table silently. Same ctx as check_span; the issue shape matches
    span issues ({code, severity, message}) so existing consumers can render these unchanged."""
    issues = []
    results = ctx["results"]
    unknown = [rk for rk in t.result_keys if results.get(rk) is None]
    for rk in unknown:
        issues.append({"code": "unknown_table_result", "severity": "blocker",
                       "message": f"{rk} is not a committed result; the table would render with no rows for it"})
    if t.result_keys and ctx.get("mode") == "proposal":
        issues.append({"code": "result_in_proposal", "severity": "blocker",
                       "message": "results cannot be tabulated as observed before H3"})
    # Only worth reporting once the keys themselves check out: an unknown key already explains the empty render.
    if not unknown and not any((results.get(rk) or {}).get("metrics") for rk in t.result_keys):
        issues.append({"code": "empty_table", "severity": "major",
                       "message": "this table cites no result metrics and would render empty; cite a result with "
                                  "metrics or remove the table"})
    return issues


def check_tables(content: ManuscriptContent, ctx: dict) -> list[dict]:
    """Every table issue in the document, each located by section key, table index and caption (tables have no span
    ID to hang issues on)."""
    return [{"section": s.key, "table_index": i, "caption": t.caption, **issue}
            for s, i, t in content.tables() for issue in check_table(t, ctx)]


# --------------------------------------------------------------------------- rendering and diffs
def render_document(content: ManuscriptContent, *, claim_citations: dict[str, list[str]], results: dict[str, dict],
                    authors: list[Author], bibtex: str, anonymous: bool) -> ManuscriptDocument:
    """Convert spans to restricted markup: literature claims become [@citekey] markers from verified papers;
    tables are generated from result artifacts, never from writer prose."""
    abstract = ""
    sections: list[Section] = []
    for s in content.sections:
        paras = []
        for p in s.paragraphs:
            parts = []
            for sp in p.spans:
                keys = sorted({k for cid in sp.claim_ids for k in claim_citations.get(cid, [])})
                parts.append(sp.text.strip() + (f" [{'; '.join('@' + k for k in keys)}]" if keys else ""))
            paras.append(" ".join(parts))
        if s.key == "abstract":
            abstract = "\n\n".join(paras)
            continue
        blocks = [Block(type="paragraph", text=t) for t in paras if t.strip()]
        for t in s.tables:
            rows = []
            for rk in t.result_keys:
                for m in (results.get(rk) or {}).get("metrics", []):
                    rows.append([rk, m.get("condition") or "", m["name"], f"{m['value']:g}", m.get("unit") or "",
                                 str(m.get("n") or "")])
            blocks.append(Block(type="table", caption=t.caption, header=["Result", "Condition", "Metric", "Value", "Unit", "n"],
                                rows=rows, label=f"tab:{s.key}"))
        for f in s.figures:
            blocks.append(Block(type="figure", figure_file=f.file_name, caption=f.caption))
        if s.key == "limitations" and not blocks:
            continue
        sections.append(Section(heading=s.heading, label=f"sec:{s.key}", blocks=blocks or [Block(type="paragraph", text="")]))
    return ManuscriptDocument(title=content.title, abstract=abstract, keywords=content.keywords,
                              authors=[] if anonymous else authors, sections=sections,
                              acknowledgments=None if anonymous else content.acknowledgments, bibtex=bibtex)


def section_text(s: ManuscriptSection | None) -> str:
    """Prose only: what the reader sees. Used for word counts and emptiness checks, never for diffing."""
    if s is None:
        return ""
    return "\n\n".join(" ".join(sp.text for sp in p.spans) for p in s.paragraphs)


def span_line(sp: Span) -> str:
    """One reviewable line per sentence: the prose plus the provenance a reviewer must be able to audit. Re-kinding
    a sentence or re-pointing its claim/result links changes no prose, so without this the edit leaves no diff."""
    bits = [sp.kind]
    if sp.claim_ids:
        bits.append("claims " + ", ".join(sp.claim_ids))
    if sp.result_keys:
        bits.append("results " + ", ".join(sp.result_keys))
    return f"{sp.text} [{'; '.join(bits)}]"


def diff_lines(s: ManuscriptSection | None) -> list[str]:
    """Newline-terminated lines for difflib: one per sentence, a blank line between paragraphs, then the result
    tables (which are part of the section's evidence but carry no prose)."""
    if s is None:
        return []
    out: list[str] = []
    for i, p in enumerate(s.paragraphs):
        if i:
            out.append("\n")
        out += [span_line(sp) + "\n" for sp in p.spans]
    out += [f"[table] {t.caption} <- {', '.join(t.result_keys) or 'no results'}\n" for t in s.tables]
    return out


def diff_sections(a: ManuscriptContent | None, b: ManuscriptContent) -> list[dict]:
    out = []
    keys = [s.key for s in b.sections] + [s.key for s in (a.sections if a else []) if not b.section(s.key)]
    for k in dict.fromkeys(keys):
        before, after = diff_lines(a.section(k) if a else None), diff_lines(b.section(k))
        if before != after:
            out.append({"section": k, "diff": "".join(difflib.unified_diff(
                before, after, fromfile=f"{k} (current)", tofile=f"{k} (proposed)", n=1))})
    return out


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))


EXPORT = [ManuscriptContent, WriterOutput]
