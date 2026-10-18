"""Deterministic manuscript span checks and rendering (no model involved)."""

from __future__ import annotations

from rp_contracts.latexdoc import Author
from rp_contracts.manuscript import (
    ManuscriptContent,
    ManuscriptSection,
    Paragraph,
    Span,
    TableRef,
    check_span,
    diff_sections,
    render_document,
)

RES = {"RES-001": {"metrics": [{"name": "accuracy", "value": 0.75, "n": 8, "numerator": 6, "denominator": 8,
                                "unit": "proportion"}], "assurance": "independently_checked"}}
CLAIMS = {"CLM-0001": {"status": "verified", "gate_eligible": True, "category": "descriptive", "critical": False,
                       "proposition": "Version records restored most pipelines."},
          "CLM-0003": {"status": "unverified", "gate_eligible": False, "category": "novelty", "critical": True,
                       "proposition": "This is the first study."},
          "CLM-0004": {"status": "verified", "gate_eligible": True, "category": "causal", "critical": True,
                       "proposition": "Pinning causes restoration."}}


def ctx(**over):
    return {"claims": CLAIMS, "results": RES, "h3_rows_supported": True, "gap_status": "partially_addressed",
            "mode": "paper", **over}


def codes(sp, **over):
    return {i["code"] for i in check_span(sp, ctx(**over))}


def sp(text, kind="observed_result", claims=(), results=()):
    return Span(span_id="x", text=text, kind=kind, claim_ids=list(claims), result_keys=list(results))


def test_factual_spans_need_links_and_known_ids():
    assert codes(sp("Most tools are popular.", "prior_work")) == {"unsupported_factual_span"}
    assert codes(sp("It is popular.", "interpretation")) == set()
    assert "unknown_claim" in codes(sp("X.", "prior_work", ["CLM-9999"]))
    assert "unknown_result" in codes(sp("X.", results=["RES-404"]))
    blocker = check_span(sp("First study.", "prior_work", ["CLM-0003"]), ctx())
    assert blocker[0]["code"] == "unverified_claim" and blocker[0]["severity"] == "blocker", "critical unverified claim"


def test_numbers_must_come_from_cited_results():
    assert codes(sp("Accuracy was 0.75 (6/8).", results=["RES-001"])) == set()
    assert codes(sp("Accuracy was 75% on 8 pipelines.", results=["RES-001"])) == set()
    assert codes(sp("Accuracy was 0.82.", results=["RES-001"])) == {"number_mismatch"}


def test_proposal_mode_blocks_observed_results():
    c = codes(sp("Accuracy was 0.75.", results=["RES-001"]), mode="proposal")
    assert {"result_in_proposal", "observed_before_h3"} <= c


def test_contribution_and_gap_claims_follow_h3_and_gap_assessment():
    assert "gap_overstated" in codes(sp("Our study fills the gap.", "contribution_statement"))
    assert codes(sp("Our study fills the gap.", "contribution_statement"), gap_status="addressed") == set()
    assert "demonstrated_contribution_without_h3" in codes(sp("We demonstrate a new method.", "contribution_statement"),
                                                           h3_rows_supported=False)


def test_causal_wording_needs_verified_causal_claim():
    assert "causal_language" in codes(sp("Pinning leads to restoration.", "prior_work", ["CLM-0001"]))
    assert "causal_language" not in codes(sp("Pinning leads to restoration.", "prior_work", ["CLM-0004"]))


def test_render_derives_citations_and_tables_and_anonymises():
    content = ManuscriptContent(title="T", sections=[
        ManuscriptSection(key="abstract", heading="Abstract", paragraphs=[Paragraph(spans=[sp("Short.", "framing")])]),
        ManuscriptSection(key="related_work", heading="Related Work",
                          paragraphs=[Paragraph(spans=[sp("Records helped.", "prior_work", ["CLM-0001"])])]),
        ManuscriptSection(key="results", heading="Results", tables=[TableRef(caption="Acc", result_keys=["RES-001"])]),
    ], acknowledgments="Thanks to Ada.")
    doc = render_document(content, claim_citations={"CLM-0001": ["smith2020records"]}, results=RES,
                          authors=[Author(name="Ada Lovelace")], bibtex="@article{smith2020records, title={x}}", anonymous=True)
    assert doc.abstract == "Short." and doc.authors == [] and doc.acknowledgments is None
    rel = next(s for s in doc.sections if s.heading == "Related Work")
    assert rel.blocks[0].text == "Records helped. [@smith2020records]"
    table = next(b for s in doc.sections for b in s.blocks if b.type == "table")
    assert table.rows == [["RES-001", "", "accuracy", "0.75", "proportion", "8"]]


def test_diff_reports_changed_sections_only():
    a = ManuscriptContent(title="T", sections=[ManuscriptSection(key="intro", heading="I", paragraphs=[Paragraph(spans=[sp("A", "framing")])])])
    b = a.model_copy(deep=True)
    assert diff_sections(a, b) == []
    b.sections[0].paragraphs[0].spans[0].text = "B"
    d = diff_sections(a, b)
    assert len(d) == 1 and "-A" in d[0]["diff"] and "+B" in d[0]["diff"]
