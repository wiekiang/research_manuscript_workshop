"""Literature contracts (PRODUCT_SPEC §2.5): normalized scholarly records, provider capabilities, item-level
rights, evidence-extraction and opportunity agent IO, and coverage reporting."""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field


class Capability(StrEnum):
    SEARCH = "search"
    LOOKUP_IDENTIFIER = "lookup_identifier"
    RETRIEVE_METADATA = "retrieve_metadata"
    LOCATE_FULL_TEXT = "locate_full_text"
    RETRIEVE_PERMITTED_FULL_TEXT = "retrieve_permitted_full_text"
    REPORT_QUOTA = "report_quota"


class FullTextLocation(BaseModel):
    url: str
    license: str | None = None
    access: str | None = None  # open | restricted | embargoed | closed | unknown
    content_type: str | None = None
    source: str


class PaperRecord(BaseModel):
    provider: str
    external_id: str
    doi: str | None = None
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    publisher: str | None = None
    type: str | None = None
    abstract: str | None = None
    abstract_rights: str = "unknown"  # cc_by_openaire | publisher_copyright | unknown
    license: str | None = None
    open_access: bool | None = None
    fulltext: list[FullTextLocation] = Field(default_factory=list)
    metadata_license: str = "unknown"  # e.g. CC0 (Crossref metadata), CC-BY-4.0 (OpenAIRE)
    attribution: str | None = None


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)
    return d if re.match(r"^10\.\d{4,9}/\S+$", d) else None


PERMISSIVE = ["cc0", "cc-0", "public domain", "cc by", "cc-by", "creativecommons.org/licenses/by/",
              "creativecommons.org/publicdomain", "cc by-sa", "cc-by-sa", "creativecommons.org/licenses/by-sa/"]
NON_COMMERCIAL = ["nc", "non-commercial", "noncommercial", "/by-nc"]


class Rights(BaseModel):
    storage_permitted: bool
    model_use_permitted: bool
    redistribution_permitted: bool
    basis: str


def rights_for(license_text: str | None, open_access: bool | None, researcher_attested: bool = False) -> Rights:
    """Item-level rights. Open access to read never implies permission to store, redistribute or send to a model."""
    if researcher_attested:
        return Rights(storage_permitted=True, model_use_permitted=True, redistribution_permitted=False,
                      basis="researcher attested rights to use this file for the project")
    lic = (license_text or "").lower()
    if lic and any(p in lic for p in PERMISSIVE):
        nc = any(n in lic for n in NON_COMMERCIAL) and "cc0" not in lic
        return Rights(storage_permitted=True, model_use_permitted=not nc, redistribution_permitted=not nc,
                      basis=f"item license {license_text}" + ("; non-commercial clause blocks model use" if nc else ""))
    if open_access:
        return Rights(storage_permitted=False, model_use_permitted=False, redistribution_permitted=False,
                      basis="open access without a recorded reuse license: read via link, do not store or send to models")
    return Rights(storage_permitted=False, model_use_permitted=False, redistribution_permitted=False,
                  basis="no reuse license recorded")


# --------------------------------------------------------------------------- evidence extraction agent
class ExtractedPassage(BaseModel):
    quote: str = Field(description="verbatim sentence(s) copied from the paper text")
    role: str = Field(description="claim | method | result | limitation | population | dataset | definition")
    section_hint: str | None
    summary: str = Field(description="neutral paraphrase of what the passage states")


class ExtractedClaim(BaseModel):
    proposition: str = Field(description="one distinct proposition stated by the paper")
    category: str = Field(description="descriptive | numerical | comparative | causal | novelty | ethics_policy")
    passage_indices: list[int]
    population_or_dataset: str | None
    measure: str | None
    comparison: str | None
    scope: str | None


class EvidenceExtraction(BaseModel):
    methods: str | None
    population_or_dataset: str | None
    results: str | None
    limitations: str | None
    passages: list[ExtractedPassage]
    claims: list[ExtractedClaim]


class SupportAssessment(BaseModel):
    verdict: str = Field(description="supports | partially_supports | does_not_support | contradicts | unclear")
    scope_notes: str | None
    strength_mismatch: bool = Field(description="true if the claim states more (causality, generality, numbers) than the passage")
    uncertainty: str


# --------------------------------------------------------------------------- opportunity / gap agent
class StudyTypeProposal(BaseModel):
    study_type: str
    venue_category: str
    fit_rationale: str
    required_inputs: list[str]
    reporting_standard: str | None
    blockers: list[str]


class RationaleProposal(BaseModel):
    problem: str
    gap: str
    gap_evidence_passage_ids: list[str] = Field(description="ids of provided evidence passages that show the gap")
    importance_to_venue: str
    intended_contribution: str
    success_criterion: str


class OpportunityProposal(BaseModel):
    title: str
    research_question: str
    cfp_alignment: str
    potential_contribution: str
    closest_work_paper_ids: list[str] = Field(description="ids of provided papers that are the nearest prior work")
    how_it_differs: str
    boundary_conditions: str
    data_availability: str
    time_estimate_weeks_low: int
    time_estimate_weeks_high: int
    compute_estimate: str
    ethics_constraints: str | None
    threats_to_novelty: list[str]
    novelty_caveat: str
    study_types: list[StudyTypeProposal]
    rationale: RationaleProposal


class OpportunitySet(BaseModel):
    proposals: list[OpportunityProposal]
    negative_findings: list[str] = Field(description="searches or angles that found no gap or found it already addressed")


EXPORT = [PaperRecord, EvidenceExtraction, SupportAssessment, OpportunitySet]
