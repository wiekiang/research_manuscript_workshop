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
    check_table,
    check_tables,
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


def tcodes(table, **over):
    return {i["code"] for i in check_table(table, ctx(**over))}


def test_table_result_keys_must_be_committed_results():
    assert tcodes(TableRef(caption="Acc", result_keys=["RES-001"])) == set()
    assert tcodes(TableRef(caption="Acc", result_keys=["RES-404"])) == {"unknown_table_result"}
    # A known key alongside an unknown one still reports the unknown one.
    assert tcodes(TableRef(caption="Acc", result_keys=["RES-001", "RES-404"])) == {"unknown_table_result"}
    bad = check_table(TableRef(caption="Acc", result_keys=["RES-404"]), ctx())
    assert bad[0]["severity"] == "blocker" and "RES-404" in bad[0]["message"]


def test_table_that_would_render_no_rows_is_reported():
    """The silent failure this check exists for: render_document emits a captioned table with zero rows."""
    empty = TableRef(caption="Acc", result_keys=[])
    assert tcodes(empty) == {"empty_table"}
    assert tcodes(TableRef(caption="Acc", result_keys=["RES-002"]),
                  results={**RES, "RES-002": {"metrics": [], "assurance": "self_reported"}}) == {"empty_table"}
    # An unknown key already explains the empty render; do not pile on a second issue for the same table.
    assert tcodes(TableRef(caption="Acc", result_keys=["RES-404"])) == {"unknown_table_result"}
    doc = render_document(
        ManuscriptContent(title="T", sections=[ManuscriptSection(key="results", heading="Results",
                                                                 tables=[TableRef(caption="Acc", result_keys=["RES-404"])])]),
        claim_citations={}, results=RES, authors=[], bibtex="", anonymous=True)
    assert [b for s in doc.sections for b in s.blocks if b.type == "table"][0].rows == [], "the silent render we flag"


def test_tables_cannot_report_results_in_proposal_mode():
    assert tcodes(TableRef(caption="Acc", result_keys=["RES-001"]), mode="proposal") == {"result_in_proposal"}


def test_table_issues_are_located_and_shaped_like_span_issues():
    content = ManuscriptContent(title="T", sections=[
        ManuscriptSection(key="results", heading="Results", tables=[TableRef(caption="Good", result_keys=["RES-001"]),
                                                                    TableRef(caption="Bad", result_keys=["RES-404"])]),
    ])
    found = check_tables(content, ctx())
    assert len(found) == 1, "only the offending table is reported"
    i = found[0]
    # Locating fields: tables have no span_id, so consumers need section + index + caption to point at one.
    assert (i["section"], i["table_index"], i["caption"]) == ("results", 1, "Bad")
    # Superset of the span-issue shape, so existing issue renderers (severity/code/message) work unchanged.
    assert {"code", "severity", "message"} <= set(i)
    assert i["severity"] in {"blocker", "major", "minor"}
    assert check_tables(ManuscriptContent(title="T", sections=[]), ctx()) == []


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


def annotated(text, **over):
    return ManuscriptContent(title="T", sections=[ManuscriptSection(key="results", heading="R", paragraphs=[
        Paragraph(spans=[sp(text, over.pop("kind", "observed_result"), over.pop("claims", ["CLM-0001"]),
                            over.pop("results", ["RES-001"]))])], **over)])


def only_diff(a, b):
    d = diff_sections(a, b)
    assert len(d) == 1 and d[0]["section"] == "results", d
    return d[0]["diff"]


def test_annotation_only_edits_are_recorded_in_the_diff():
    """Re-pointing a sentence's evidence changes no prose; the diff must still show it."""
    base = annotated("Accuracy held across pipelines.")
    assert diff_sections(base, base.model_copy(deep=True)) == []

    relinked = annotated("Accuracy held across pipelines.", claims=["CLM-0002"])
    d = only_diff(base, relinked)
    assert "-Accuracy held across pipelines. [observed_result; claims CLM-0001; results RES-001]" in d
    assert "+Accuracy held across pipelines. [observed_result; claims CLM-0002; results RES-001]" in d

    # Dropping the result link, and re-kinding, are each visible on their own.
    assert "+Accuracy held across pipelines. [observed_result; claims CLM-0001]" in only_diff(base, annotated("Accuracy held across pipelines.", results=[]))
    assert "+Accuracy held across pipelines. [interpretation; claims CLM-0001; results RES-001]" in only_diff(base, annotated("Accuracy held across pipelines.", kind="interpretation"))


def test_table_result_key_edits_are_recorded_in_the_diff():
    base = annotated("Accuracy held across pipelines.", tables=[TableRef(caption="Acc", result_keys=["RES-404"])])
    fixed = annotated("Accuracy held across pipelines.", tables=[TableRef(caption="Acc", result_keys=["RES-001"])])
    d = only_diff(base, fixed)
    assert "-[table] Acc <- RES-404" in d and "+[table] Acc <- RES-001" in d


def test_ordinary_text_edits_still_read_sensibly():
    """A one-sentence change must not redline the whole paragraph, and must carry its provenance."""
    def two(first):
        return ManuscriptContent(title="T", sections=[ManuscriptSection(key="results", heading="R", paragraphs=[
            Paragraph(spans=[sp(first, "observed_result", ["CLM-0001"], ["RES-001"]),
                             sp("The second sentence is untouched.", "framing")])])])

    d = only_diff(two("The first sentence changed."), two("The first sentence now reads differently."))
    assert "-The first sentence changed. [observed_result; claims CLM-0001; results RES-001]" in d
    assert "+The first sentence now reads differently. [observed_result; claims CLM-0001; results RES-001]" in d
    # The untouched neighbour is context at most, never a -/+ line.
    assert "-The second sentence is untouched." not in d and "+The second sentence is untouched." not in d
    # Lines stay newline-terminated, so the hunk is readable rather than run together.
    assert "] -" not in d and d.endswith("\n")


def test_diff_reports_changed_sections_only():
    a = ManuscriptContent(title="T", sections=[ManuscriptSection(key="intro", heading="I", paragraphs=[Paragraph(spans=[sp("A", "framing")])])])
    b = a.model_copy(deep=True)
    assert diff_sections(a, b) == []
    b.sections[0].paragraphs[0].spans[0].text = "B"
    d = diff_sections(a, b)
    assert len(d) == 1 and "-A" in d[0]["diff"] and "+B" in d[0]["diff"]
