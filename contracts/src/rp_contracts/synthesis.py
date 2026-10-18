"""Evidence-synthesis and qualitative method contracts (PRODUCT_SPEC §2.5, §2.7, §3 method table; M10).

The review specification is part of the frozen protocol (section ``review_specification``), so H2 binds the exact
queries, sources, criteria, extraction form, appraisal tool and synthesis plan. Counts in the flow diagram and the
reproducibility appendix derive from stored search/screening records only. Pooling is deterministic
(inverse-variance fixed effect and DerSimonian-Laird random effects) and is recomputed at validation time.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SYNTHESIS_ENGINE = "rp-synthesis/1"
REVIEW_TYPES = ("systematic_review", "meta_analysis", "mapping_review", "scoping_review", "tertiary_review")


class SearchSpec(BaseModel):
    provider: str
    query: str = Field(min_length=3, description="exact query string as executed")
    year_from: int | None = None
    year_to: int | None = None
    max_results: int = Field(default=50, ge=1, le=200)


class ExtractionField(BaseModel):
    key: str
    label: str
    required: bool = True


class AppraisalItem(BaseModel):
    key: str
    label: str
    ratings: list[str] = Field(default_factory=lambda: ["low", "some_concerns", "high", "unclear"])


class ChartingDimension(BaseModel):
    key: str
    label: str
    categories: list[str] = Field(min_length=1)


class ReviewSpec(BaseModel):
    review_type: Literal["systematic_review", "meta_analysis", "mapping_review", "scoping_review", "tertiary_review"]
    question: str = Field(min_length=10)
    searches: list[SearchSpec] = Field(min_length=1)
    inclusion_criteria: list[str] = Field(min_length=1)
    exclusion_reasons: list[str] = Field(min_length=1, description="the only reasons a record may be excluded with")
    extraction_form: list[ExtractionField] = Field(default_factory=list)
    appraisal_tool: str | None = None
    appraisal_items: list[AppraisalItem] = Field(default_factory=list)
    synthesis: Literal["narrative", "meta_analysis", "map", "review_of_reviews"]
    effect_measure: str | None = None
    pooling_model: Literal["fixed", "random_dl"] | None = None
    charting_scheme: list[ChartingDimension] = Field(default_factory=list)
    reporting_standard: str

    @model_validator(mode="after")
    def _consistent(self) -> ReviewSpec:
        need = {"systematic_review": "narrative", "meta_analysis": "meta_analysis", "mapping_review": "map",
                "scoping_review": "map", "tertiary_review": "review_of_reviews"}
        if self.review_type == "systematic_review" and self.synthesis not in ("narrative", "meta_analysis"):
            raise ValueError("a systematic review synthesises narratively or by meta-analysis")
        if self.review_type != "systematic_review" and self.synthesis != need[self.review_type]:
            raise ValueError(f"{self.review_type} requires synthesis '{need[self.review_type]}'")
        if self.synthesis == "meta_analysis" and (not self.effect_measure or not self.pooling_model):
            raise ValueError("meta-analysis needs an effect measure and a pooling model")
        if self.synthesis == "map" and not self.charting_scheme:
            raise ValueError("mapping/scoping reviews need a charting scheme")
        if self.review_type in ("systematic_review", "meta_analysis", "tertiary_review") and not self.appraisal_items:
            raise ValueError("appraisal items (risk of bias / quality) are required")
        return self


# --------------------------------------------------------------------------- flow (PRISMA-style) from records
def flow_counts(identified_by_run: dict[str, int], unique_ids: set[str], ta: dict[str, dict], ft: dict[str, dict]) -> dict:
    """identified_by_run: run -> retrieved count; unique_ids: deduplicated record ids; ta/ft: id -> {decision, reason}."""
    identified = sum(identified_by_run.values())
    ta_ex = {k: v for k, v in ta.items() if v["decision"] == "exclude"}
    ta_in = {k for k, v in ta.items() if v["decision"] == "include"}
    ft_ex = {k: v for k, v in ft.items() if v["decision"] == "exclude" and k in ta_in}
    ft_in = {k for k, v in ft.items() if v["decision"] == "include" and k in ta_in}
    reasons: dict[str, int] = {}
    for v in ft_ex.values():
        reasons[v["reason"]] = reasons.get(v["reason"], 0) + 1
    return {"identified": identified, "duplicates_removed": identified - len(unique_ids), "screened": len(unique_ids),
            "screened_out": len(ta_ex), "awaiting_screening": len(unique_ids - set(ta)),
            "full_text_assessed": len(ta_in & set(ft)), "awaiting_full_text": len(ta_in - set(ft)),
            "excluded_full_text": len(ft_ex), "excluded_full_text_reasons": reasons, "included": len(ft_in),
            "included_ids": sorted(ft_in)}


def flow_problems(flow: dict) -> list[str]:
    p = []
    if flow["awaiting_screening"]:
        p.append(f"{flow['awaiting_screening']} record(s) have no title/abstract decision")
    if flow["awaiting_full_text"]:
        p.append(f"{flow['awaiting_full_text']} record(s) included at title/abstract have no full-text decision")
    if flow["screened"] != flow["screened_out"] + flow["full_text_assessed"] + flow["awaiting_full_text"] + flow["awaiting_screening"]:
        p.append("flow counts do not reconcile")
    if flow["full_text_assessed"] != flow["excluded_full_text"] + flow["included"]:
        p.append("full-text counts do not reconcile")
    return p


# --------------------------------------------------------------------------- meta-analysis
class EffectRow(BaseModel):
    study: str
    estimate: float
    variance: float = Field(gt=0)


def pool(rows: list[EffectRow], model: str) -> dict:
    """Inverse-variance fixed effect; DerSimonian-Laird random effects with tau^2, Q and I^2."""
    if len(rows) < 2:
        return {"status": "not_performed", "detail": "pooling needs at least two studies with an estimate and variance"}
    w = [1 / r.variance for r in rows]
    sw = sum(w)
    fe = sum(wi * r.estimate for wi, r in zip(w, rows, strict=True)) / sw
    q = sum(wi * (r.estimate - fe) ** 2 for wi, r in zip(w, rows, strict=True))
    df = len(rows) - 1
    c = sw - sum(wi * wi for wi in w) / sw
    tau2 = max(0.0, (q - df) / c) if c > 0 else 0.0
    i2 = max(0.0, (q - df) / q) * 100 if q > 0 else 0.0
    if model == "fixed":
        est, se = fe, math.sqrt(1 / sw)
    else:
        wr = [1 / (r.variance + tau2) for r in rows]
        est = sum(wi * r.estimate for wi, r in zip(wr, rows, strict=True)) / sum(wr)
        se = math.sqrt(1 / sum(wr))
    return {"status": "computed", "model": model, "k": len(rows), "estimate": est, "se": se,
            "ci_low": est - 1.959964 * se, "ci_high": est + 1.959964 * se, "q": q, "df": df, "tau2": tau2, "i2": i2,
            "engine": SYNTHESIS_ENGINE}


# --------------------------------------------------------------------------- mapping / scoping
def chart_map(scheme: list[ChartingDimension], charted: dict[str, dict[str, str]]) -> dict:
    problems, table = [], {}
    for d in scheme:
        counts = dict.fromkeys(d.categories, 0)
        for sid, row in charted.items():
            v = row.get(d.key)
            if v not in counts:
                problems.append(f"{sid}: '{d.key}' value {v!r} is not a category of the scheme")
                continue
            counts[v] += 1
        table[d.key] = counts
    return {"dimensions": table, "studies": len(charted), "problems": problems, "engine": SYNTHESIS_ENGINE}


# --------------------------------------------------------------------------- tertiary: overlap of primary studies
def overlap(reviews: dict[str, list[str]]) -> dict:
    """Corrected covered area (Pieper et al. 2014): CCA = (N - r) / (r*c - r), N = total inclusions, r = unique
    primary studies, c = reviews."""
    c = len(reviews)
    prim = {p for v in reviews.values() for p in v}
    n = sum(len(set(v)) for v in reviews.values())
    r = len(prim)
    if c < 2 or r == 0:
        return {"status": "not_performed", "detail": "overlap needs at least two reviews with listed primary studies"}
    cca = (n - r) / (r * c - r) if r * c - r else 0.0
    level = "slight" if cca < 0.05 else "moderate" if cca < 0.10 else "high" if cca < 0.15 else "very high"
    return {"status": "computed", "reviews": c, "primary_studies": r, "inclusions": n, "cca": cca, "level": level,
            "engine": SYNTHESIS_ENGINE}


EXPORT = [ReviewSpec, EffectRow]
