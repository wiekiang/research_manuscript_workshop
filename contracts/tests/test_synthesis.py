"""M10 deterministic synthesis: flow reconciliation, pooling, charting maps, tertiary overlap, spec validation."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from rp_contracts.synthesis import (
    ChartingDimension,
    EffectRow,
    ReviewSpec,
    chart_map,
    flow_counts,
    flow_problems,
    overlap,
    pool,
)


def test_flow_counts_reconcile_and_flag_unscreened():
    ta = {"a": {"decision": "include"}, "b": {"decision": "exclude", "reason": "x"}, "c": {"decision": "include"}}
    ft = {"a": {"decision": "include"}, "c": {"decision": "exclude", "reason": "no outcome"}}
    f = flow_counts({"r1": 4, "r2": 2}, {"a", "b", "c", "d"}, ta, ft)
    assert (f["identified"], f["duplicates_removed"], f["screened"], f["included"]) == (6, 2, 4, 1)
    assert f["excluded_full_text_reasons"] == {"no outcome": 1}
    assert flow_problems(f) == ["1 record(s) have no title/abstract decision"]


def test_fixed_effect_pooling_benchmark():
    # y=(0.5,0.3), v=(0.04,0.01): w=(25,100), FE=(12.5+30)/125=0.34, se=sqrt(1/125), Q=0.8, I2=0, tau2=0.
    r = pool([EffectRow(study="a", estimate=0.5, variance=0.04), EffectRow(study="b", estimate=0.3, variance=0.01)], "fixed")
    assert math.isclose(r["estimate"], 0.34) and math.isclose(r["se"], math.sqrt(1 / 125))
    assert math.isclose(r["q"], 0.8) and r["i2"] == 0 and r["tau2"] == 0
    assert pool([EffectRow(study="a", estimate=1, variance=1)], "fixed")["status"] == "not_performed"


def test_chart_map_counts_and_rejects_unknown_categories():
    scheme = [ChartingDimension(key="method", label="Method", categories=["experiment", "survey"])]
    m = chart_map(scheme, {"a": {"method": "experiment"}, "b": {"method": "survey"}, "c": {"method": "essay"}})
    assert m["dimensions"]["method"] == {"experiment": 1, "survey": 1} and len(m["problems"]) == 1


def test_overlap_corrected_covered_area():
    # 3 reviews, primary studies p1..p4, 6 inclusions: CCA = (6-4)/(4*3-4) = 0.25 -> very high overlap.
    o = overlap({"r1": ["p1", "p2"], "r2": ["p2", "p3"], "r3": ["p1", "p4"]})
    assert math.isclose(o["cca"], 0.25) and o["level"] == "very high"
    assert overlap({"r1": ["p1"]})["status"] == "not_performed"


def test_review_spec_consistency_rules():
    base = {"review_type": "mapping_review", "question": "What has been studied about X?", "searches": [
        {"provider": "crossref", "query": "x studies"}], "inclusion_criteria": ["about x"], "exclusion_reasons": ["off topic"],
        "synthesis": "map", "reporting_standard": "Petersen et al. guidelines"}
    with pytest.raises(ValidationError, match="charting scheme"):
        ReviewSpec.model_validate(base)
    ReviewSpec.model_validate({**base, "charting_scheme": [{"key": "m", "label": "M", "categories": ["a"]}]})
    with pytest.raises(ValidationError, match="review_of_reviews"):
        ReviewSpec.model_validate({**base, "review_type": "tertiary_review"})
