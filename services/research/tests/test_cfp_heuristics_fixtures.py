"""Deterministic deadline extraction (cfp_heuristics) against every HTML page in fixtures/cfp.

The expected values below were transcribed by reading each HTML page, not from the extractor's
output. Each page's "Important Dates" list states:

icrds2027.html
  - Abstract registration (mandatory): Thursday, January 14, 2027 (AoE)
  - Full paper submission: January 21, 2027 (AoE)
  - Author response (rebuttal) period: March 3-5, 2027        (no time, no timezone)
  - Notification of acceptance: March 20, 2027                (no time, no timezone)
  - Camera-ready deadline: April 15, 2027 at 23:59 PDT
  - Author registration deadline: May 1, 2027                 (no time, no timezone)
chem2027.html
  - Abstract submission deadline: March 1, 2027 (UTC)
dataprov2026.html
  - Paper submission deadline: September 1, 2026 (AoE)
mlsys2027.html
  - Paper submission deadline: February 10, 2027 (AoE)
  - Notification: April 2, 2027                               (no time, no timezone)

Where a page states a timezone, the parsed timezone must match it verbatim. Where a page states
none, the result must carry no timezone and no time: the deterministic pass never fills defaults
(resolve_deadline later refuses to compute due_at without one).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rp_research.agents import cfp_heuristics
from rp_research.fetch.text import extract_html

FIX = Path(__file__).resolve().parents[1] / "src" / "rp_research" / "fixtures" / "cfp"


@pytest.fixture(scope="module")
def extractions() -> dict[str, cfp_heuristics.CfpExtraction]:
    return {f.name: cfp_heuristics.extract(extract_html(f.read_bytes())) for f in sorted(FIX.glob("*.html"))}


def rows(ex) -> set[tuple]:
    return {(d.deadline_kind.value, d.date, d.time, d.timezone, d.mandatory) for d in ex.deadlines}


def by_kind(ex, kind: str):
    found = [d for d in ex.deadlines if d.deadline_kind.value == kind]
    assert len(found) == 1, f"expected exactly one {kind} deadline, got {found}"
    return found[0]


def test_all_fixture_pages_are_covered(extractions):
    assert set(extractions) == {"chem2027.html", "dataprov2026.html", "icrds2027.html", "mlsys2027.html"}


# --------------------------------------------------------------------------- icrds2027.html
def test_icrds_deadlines_match_the_page(extractions):
    ex = extractions["icrds2027.html"]
    assert rows(ex) == {
        # The page marks only abstract registration "(mandatory)".
        ("abstract_registration", "2027-01-14", None, "AoE", True),
        ("full_paper", "2027-01-21", None, "AoE", None),
        # The page states the period "March 3-5, 2027"; the extractor records the first date
        # (see the xfail below for the period end) with no time or timezone, as stated.
        ("rebuttal", "2027-03-03", None, None, None),
        ("notification", "2027-03-20", None, None, None),
        ("camera_ready", "2027-04-15", "23:59", "PDT", None),
        ("author_registration", "2027-05-01", None, None, None),
    }


def test_icrds_stated_timezones_are_kept_verbatim(extractions):
    ex = extractions["icrds2027.html"]
    assert by_kind(ex, "abstract_registration").timezone == "AoE"
    assert by_kind(ex, "full_paper").timezone == "AoE"
    assert by_kind(ex, "camera_ready").timezone == "PDT"
    assert by_kind(ex, "camera_ready").time == "23:59"


def test_icrds_unstated_timezones_are_not_defaulted(extractions):
    ex = extractions["icrds2027.html"]
    for kind in ("rebuttal", "notification", "author_registration"):
        d = by_kind(ex, kind)
        assert d.timezone is None, f"{kind}: page states no timezone, none may be filled in"
        assert d.time is None, f"{kind}: page states no time, none may be filled in"


def test_icrds_rebuttal_range_is_flagged_as_uncertain(extractions):
    d = by_kind(extractions["icrds2027.html"], "rebuttal")
    assert d.uncertainty == "date range: first date used"


@pytest.mark.xfail(
    reason="cfp_heuristics._find_dates keeps only the first date of the stated range "
           "'March 3-5, 2027' (the DATE_PATTERNS regexes consume '3-5' as one day group), so the "
           "stated end of the rebuttal period, 2027-03-05, is never extracted; only the "
           "'date range: first date used' uncertainty note survives",
    strict=True,
)
def test_icrds_rebuttal_period_end_date_is_extracted(extractions):
    ex = extractions["icrds2027.html"]
    assert "2027-03-05" in {d.date for d in ex.deadlines if d.deadline_kind.value == "rebuttal"}


# --------------------------------------------------------------------------- chem2027.html
def test_chem_single_deadline_matches_the_page(extractions):
    ex = extractions["chem2027.html"]
    assert rows(ex) == {("abstract_registration", "2027-03-01", None, "UTC", None)}
    assert by_kind(ex, "abstract_registration").timezone == "UTC"


# --------------------------------------------------------------------------- dataprov2026.html
def test_dataprov_single_deadline_matches_the_page(extractions):
    ex = extractions["dataprov2026.html"]
    assert rows(ex) == {("full_paper", "2026-09-01", None, "AoE", None)}
    assert by_kind(ex, "full_paper").timezone == "AoE"


# --------------------------------------------------------------------------- mlsys2027.html
def test_mlsys_deadlines_match_the_page(extractions):
    ex = extractions["mlsys2027.html"]
    assert rows(ex) == {
        ("full_paper", "2027-02-10", None, "AoE", None),
        ("notification", "2027-04-02", None, None, None),
    }
    assert by_kind(ex, "full_paper").timezone == "AoE"
    n = by_kind(ex, "notification")
    assert n.timezone is None and n.time is None, "page states no timezone or time for notification"
