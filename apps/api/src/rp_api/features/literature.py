"""M4 - literature discovery, evidence, claim registry, policy-based verification and coverage reporting."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.copy import COVERAGE_TEMPLATE, LITERATURE_SETUP_MESSAGE
from rp_contracts.enums import ClaimCategory, ClaimKind, LedgerCategory
from rp_contracts.hashing import content_hash, sha256_hex
from rp_contracts.literature import normalize_doi, rights_for
from rp_contracts.ranking import EMBEDDING_MODEL, embed
from rp_contracts.scanning import scan
from rp_contracts.textmatch import find_span
from rp_contracts.verification import REQUIREMENTS, VerificationPolicy

from ..db.base import utcnow
from ..db.engine import session_scope
from ..db.models.core import ProviderDefinition
from ..db.models.literature import (
    Claim,
    ClaimDecision,
    ClaimSupport,
    EvidencePassage,
    GlobalPaper,
    GlobalPaperIdentifier,
    LiteratureCoverageAssessment,
    ScreeningDecision,
    SearchResult,
    SearchRun,
    TenantPaperRecord,
    VerificationRecord,
)
from ..deps import EDIT_ROLES, OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import artifacts as art_svc
from ..services import claims as claim_svc
from ..services import ledger
from ..services.common import audit
from ..services.tasks import create_task

router = APIRouter(tags=["literature"])
MAX_PAPER = 50 * 1024 * 1024
BASE_PROVIDERS = ["openaire", "crossref"]


# --------------------------------------------------------------------------- searches
class SearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    providers: list[str] = Field(default_factory=lambda: list(BASE_PROVIDERS))
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    max_results: int = Field(default=25, ge=1, le=100)
    purpose: str = Field(default="scoping", pattern="^(scoping|method_stage|systematic)$")


async def provider_states() -> dict[str, ProviderDefinition]:
    async with session_scope("app") as db:
        return {p.key: p for p in (await db.execute(select(ProviderDefinition).where(
            ProviderDefinition.kind == "scholarly"))).scalars()}


@router.get("/literature/setup")
async def literature_setup(ctx: Ctx = Depends(user_ctx)):
    states = await provider_states()
    return {"message": LITERATURE_SETUP_MESSAGE,
            "enabled_sources": [{"key": k, "name": p.display_name, "attribution": p.attribution}
                                for k, p in states.items() if p.enabled and p.gate_status != "blocked"],
            "optional_connections": [{"key": k, "name": p.display_name, "gate_status": p.gate_status}
                                     for k, p in states.items() if p.requires_user_connection and p.gate_status == "cleared"]}


@router.post("/projects/{project_id}/searches", status_code=202)
async def create_search(project_id: uuid.UUID, body: SearchIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    states = await provider_states()
    usable, refused = [], []
    for p in dict.fromkeys(body.providers):
        st = states.get(p)
        if st is None or not st.enabled or st.gate_status in ("blocked", "pending"):
            refused.append({"provider": p, "reason": f"not available ({st.gate_status if st else 'unknown'})"})
        else:
            usable.append(p)
    if not usable:
        raise unprocessable("no_enabled_providers", "none of the requested sources is available", {"refused": refused})
    run = SearchRun(tenant_id=ctx.tenant_id, project_id=project.id, purpose=body.purpose, query=body.query,
                    filters={"year_from": body.year_from, "year_to": body.year_to, "max_results": body.max_results},
                    providers_requested=usable, provider_status={r["provider"]: {"status": "refused", **r} for r in refused})
    ctx.db.add(run)
    await ctx.db.flush()
    task, _ = await create_task(ctx.db, ctx.principal, project, "literature_search",
                                {"mode": "search", "search_run_id": str(run.id)},
                                input_manifest={"run": str(run.id)})
    run.task_id = task.id
    await audit(ctx.db, ctx.principal, "literature.search_requested", project_id=project.id, resource_type="search_run",
                resource_id=run.id, details={"query": body.query, "providers": usable})
    await ctx.db.commit()
    return {"search_run_id": str(run.id), "task": task_out(task), "refused": refused}


def run_out(r: SearchRun) -> dict:
    return {"id": str(r.id), "query": r.query, "filters": r.filters, "providers": r.providers_requested,
            "provider_status": r.provider_status, "status": r.status, "executed_at": r.executed_at,
            "retrieved_count": r.retrieved_count, "purpose": r.purpose, "created_at": r.created_at,
            "record_artifact_id": str(r.record_artifact_id) if r.record_artifact_id else None}


@router.get("/projects/{project_id}/searches")
async def list_searches(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    rows = (await ctx.db.execute(select(SearchRun).where(SearchRun.project_id == project_id)
                                 .order_by(SearchRun.created_at.desc()))).scalars()
    return {"items": [run_out(r) for r in rows]}


# --------------------------------------------------------------------------- papers
def paper_out(p: TenantPaperRecord, screening: list[ScreeningDecision] | None = None) -> dict:
    return {"id": str(p.id), "doi": p.doi, "title": p.title, "authors": p.authors, "year": p.year, "venue": p.venue,
            "abstract": p.abstract, "abstract_rights": p.abstract_rights, "license": p.license,
            "open_access": p.open_access, "fulltext_status": p.fulltext_status, "fulltext_locations": p.fulltext_locations,
            "rights": p.rights, "identity_status": p.identity_status, "identity_verification": p.identity_verification,
            "sources": p.sources, "origin": p.origin, "notes": p.notes, "retracted": p.retracted,
            "global_paper_id": str(p.global_paper_id) if p.global_paper_id else None,
            "fulltext_artifact_id": str(p.fulltext_artifact_id) if p.fulltext_artifact_id else None,
            "screening": [{"stage": s.stage, "decision": s.decision, "reason": s.reason, "method": s.method,
                           "at": s.created_at} for s in (screening or []) if s.is_current]}


@router.get("/projects/{project_id}/papers")
async def list_papers(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    papers = list((await ctx.db.execute(select(TenantPaperRecord).where(TenantPaperRecord.project_id == project_id)
                                        .order_by(TenantPaperRecord.created_at))).scalars())
    scr = list((await ctx.db.execute(select(ScreeningDecision).where(ScreeningDecision.project_id == project_id))).scalars())
    by: dict[uuid.UUID, list] = {}
    for s in scr:
        by.setdefault(s.paper_id, []).append(s)
    return {"items": [paper_out(p, by.get(p.id)) for p in papers]}


class ManualPaperIn(BaseModel):
    doi: str | None = None
    title: str | None = Field(default=None, max_length=1000)
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    notes: str | None = Field(default=None, max_length=10000)


@router.post("/projects/{project_id}/papers", status_code=201)
async def add_paper(project_id: uuid.UUID, body: ManualPaperIn, ctx: Ctx = Depends(user_ctx)):
    """Manual citation entry. Identity stays unverified until a deterministic lookup confirms it."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    doi = normalize_doi(body.doi)
    if body.doi and not doi:
        raise unprocessable("invalid_doi", "that is not a syntactically valid DOI")
    if not doi and not body.title:
        raise unprocessable("doi_or_title_required", "enter a DOI or the bibliographic details")
    if doi:
        dup = (await ctx.db.execute(select(TenantPaperRecord).where(TenantPaperRecord.project_id == project_id,
                                                                    TenantPaperRecord.doi == doi))).scalar_one_or_none()
        if dup:
            return paper_out(dup)
    p = TenantPaperRecord(tenant_id=ctx.tenant_id, project_id=project_id, doi=doi, title=body.title or f"[DOI {doi}]",
                          authors=body.authors, year=body.year, venue=body.venue, notes=body.notes, origin="manual",
                          added_by=ctx.principal.actor_id, sources=["manual"])
    ctx.db.add(p)
    await ctx.db.flush()
    task, _ = await create_task(ctx.db, ctx.principal, project, "literature_search",
                                {"mode": "verify_identity", "paper_ids": [str(p.id)]},
                                input_manifest={"verify": str(p.id)})
    await ctx.db.commit()
    return {**paper_out(p), "identity_task": task_out(task)}


@router.post("/projects/{project_id}/papers/upload", status_code=202)
async def upload_paper(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx), file: UploadFile = File(...),
                       doi: str | None = Form(None), title: str | None = Form(None, max_length=1000),
                       rights_statement: str = Form(..., min_length=10, max_length=2000),
                       attest_rights: bool = Form(False)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    if not attest_rights:
        raise unprocessable("attestation_required", "confirm you have the right to use this file for the project")
    data = await file.read(MAX_PAPER + 1)
    if len(data) > MAX_PAPER:
        raise unprocessable("file_too_large", "papers are limited to 50 MB")
    report = scan(data, file.content_type or "application/pdf")
    if report.sniffed_type not in ("application/pdf", "text/plain", "text/html") or report.verdict == "rejected":
        raise unprocessable("file_rejected", "upload a PDF, HTML or text file that passes scanning", report.to_dict())
    nd = normalize_doi(doi)
    p = None
    if nd:
        p = (await ctx.db.execute(select(TenantPaperRecord).where(TenantPaperRecord.project_id == project_id,
                                                                  TenantPaperRecord.doi == nd))).scalar_one_or_none()
    if p is None:
        p = TenantPaperRecord(tenant_id=ctx.tenant_id, project_id=project_id, doi=nd, title=title or file.filename or "Uploaded paper",
                              origin="upload", added_by=ctx.principal.actor_id, sources=["upload"])
        ctx.db.add(p)
        await ctx.db.flush()
    rights = rights_for(None, None, researcher_attested=True)
    pub = await art_svc.publish_bytes(ctx.db, ctx.principal, ctx.tenant_id, project_id, "paper_fulltext", data,
                                      report.sniffed_type, label=f"Uploaded paper: {file.filename}"[:300],
                                      rights={"model_use": "allowed_researcher_attested", "statement": rights_statement,
                                              "redistribution": "not_permitted"},
                                      metadata={"scan": report.to_dict(), "filename": file.filename})
    p.fulltext_artifact_id = pub.artifact.id
    p.fulltext_status = "retrieved"
    p.rights = {**rights.model_dump(), "statement": rights_statement}
    task, _ = await create_task(ctx.db, ctx.principal, project, "evidence_extraction", {"paper_id": str(p.id)},
                                input_manifest={"paper": str(p.id), "fulltext": pub.artifact.content_hash})
    tasks = [task_out(task)]
    if nd and p.identity_status == "unverified":
        t2, _ = await create_task(ctx.db, ctx.principal, project, "literature_search",
                                  {"mode": "verify_identity", "paper_ids": [str(p.id)]}, input_manifest={"verify": str(p.id)})
        tasks.append(task_out(t2))
    await audit(ctx.db, ctx.principal, "literature.paper_uploaded", project_id=project_id, resource_type="paper",
                resource_id=p.id, details={"hash": pub.artifact.content_hash})
    await ctx.db.commit()
    return {"paper": paper_out(p), "tasks": tasks}


class ScreenIn(BaseModel):
    stage: str = Field(pattern="^(title_abstract|full_text)$")
    decision: str = Field(pattern="^(include|exclude|maybe)$")
    reason: str = Field(min_length=3, max_length=4000)
    criteria: list[str] = Field(default_factory=list)


@router.post("/projects/{project_id}/papers/{paper_id}/screen", status_code=201)
async def screen(project_id: uuid.UUID, paper_id: uuid.UUID, body: ScreenIn, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id, EDIT_ROLES)
    p = await _paper(ctx.db, project_id, paper_id)
    for old in (await ctx.db.execute(select(ScreeningDecision).where(
            ScreeningDecision.paper_id == p.id, ScreeningDecision.stage == body.stage, ScreeningDecision.is_current.is_(True)))).scalars():
        old.is_current = False
    ctx.db.add(ScreeningDecision(tenant_id=ctx.tenant_id, project_id=project_id, paper_id=p.id, stage=body.stage,
                                 decision=body.decision, reason=body.reason, criteria=body.criteria, method="human",
                                 decided_by=ctx.principal.actor_id))
    await ctx.db.commit()
    return {"paper_id": str(p.id), "stage": body.stage, "decision": body.decision}


class NotesIn(BaseModel):
    notes: str = Field(max_length=20000)


@router.patch("/projects/{project_id}/papers/{paper_id}")
async def paper_notes(project_id: uuid.UUID, paper_id: uuid.UUID, body: NotesIn, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id, EDIT_ROLES)
    p = await _paper(ctx.db, project_id, paper_id)
    p.notes = body.notes
    await ctx.db.commit()
    return paper_out(p)


@router.post("/projects/{project_id}/papers/{paper_id}/fulltext", status_code=202)
async def request_fulltext(project_id: uuid.UUID, paper_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    p = await _paper(ctx.db, project_id, paper_id)
    task, _ = await create_task(ctx.db, ctx.principal, project, "evidence_extraction", {"paper_id": str(p.id)},
                                input_manifest={"paper": str(p.id), "at": utcnow().isoformat()})
    await ctx.db.commit()
    return {"task": task_out(task)}


class ManualPassageIn(BaseModel):
    quote: str = Field(min_length=8, max_length=4000)
    role: str = Field(default="claim", pattern="^(claim|method|result|limitation|population|dataset|definition|table)$")
    page: int | None = None
    section: str | None = Field(default=None, max_length=300)


@router.post("/projects/{project_id}/papers/{paper_id}/passages", status_code=201)
async def add_passage(project_id: uuid.UUID, paper_id: uuid.UUID, body: ManualPassageIn, ctx: Ctx = Depends(user_ctx)):
    """Researcher-entered passage. Verified verbatim against stored text when the licence allowed storage;
    otherwise recorded as a researcher quote that machine checks cannot confirm."""
    await project_for(ctx, project_id, EDIT_ROLES)
    p = await _paper(ctx.db, project_id, paper_id)
    verified, span, src_kind, src_art, src_hash = False, None, "researcher_quote", None, None
    if p.fulltext_text_artifact_id:
        art = await art_svc.get_artifact(ctx.db, p.fulltext_text_artifact_id, project_id)
        span = find_span((await art_svc.read_artifact_json(art))["text"], body.quote)
        if span:
            verified, src_kind, src_art, src_hash = True, "fulltext", art.id, art.content_hash
    if not verified and p.abstract and find_span(p.abstract, body.quote):
        verified, src_kind, src_hash = True, "abstract", sha256_hex(p.abstract.encode())
        span = find_span(p.abstract, body.quote)
    ep = EvidencePassage(tenant_id=ctx.tenant_id, project_id=project_id, paper_id=p.id, quote=body.quote,
                         quote_hash=sha256_hex(body.quote.encode()), role=body.role, summary=None,
                         locator={"char_start": span[0] if span else None, "char_end": span[1] if span else None,
                                  "page": body.page, "section": body.section},
                         source_kind=src_kind, source_artifact_id=src_art, source_hash=src_hash,
                         verified_in_source=verified, extraction_method="human", extracted_by=ctx.principal.actor_id)
    ctx.db.add(ep)
    await ctx.db.commit()
    return passage_out(ep)


async def _paper(db: AsyncSession, project_id: uuid.UUID, paper_id: uuid.UUID) -> TenantPaperRecord:
    p = (await db.execute(select(TenantPaperRecord).where(TenantPaperRecord.id == paper_id,
                                                          TenantPaperRecord.project_id == project_id))).scalar_one_or_none()
    if p is None:
        raise not_found("paper")
    return p


# --------------------------------------------------------------------------- evidence graph and claims
def passage_out(p: EvidencePassage) -> dict:
    return {"id": str(p.id), "paper_id": str(p.paper_id), "quote": p.quote, "role": p.role, "summary": p.summary,
            "locator": p.locator, "source_kind": p.source_kind, "verified_in_source": p.verified_in_source,
            "extraction_method": p.extraction_method, "extracted_by": p.extracted_by, "freshness": p.freshness}


def claim_out(c: Claim, supports=None, records=None, decisions=None) -> dict:
    return {"id": str(c.id), "claim_key": c.claim_key, "proposition": c.proposition, "normalized": c.normalized,
            "kind": c.kind, "category": c.category, "critical": c.critical, "status": c.status,
            "gate_eligible": c.gate_eligible, "decision": c.decision, "origin": c.origin, "version": c.version,
            "supersedes_id": str(c.supersedes_id) if c.supersedes_id else None,
            "supports": [{"id": str(s.id), "passage_id": str(s.passage_id) if s.passage_id else None,
                          "paper_id": str(s.paper_id) if s.paper_id else None, "relation": s.relation,
                          "result_ref": s.result_ref, "is_current": s.is_current} for s in (supports or [])],
            "verifications": [{"id": str(r.id), "check": r.check, "outcome": r.outcome, "method": r.method,
                               "verifier": r.verifier, "verifier_version": r.verifier_version, "evidence": r.evidence,
                               "uncertainty": r.uncertainty, "requires_human_confirmation": r.requires_human_confirmation,
                               "at": r.created_at, "is_current": r.is_current} for r in (records or [])],
            "decisions": [{"policy_version": d.policy_version, "rule_id": d.rule_id, "status": d.status,
                           "satisfied": d.satisfied, "outstanding": d.outstanding, "state": d.state,
                           "human_required": d.human_required, "at": d.created_at} for d in (decisions or [])]}


@router.get("/projects/{project_id}/evidence")
async def evidence(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    passages = list((await ctx.db.execute(select(EvidencePassage).where(EvidencePassage.project_id == project_id))).scalars())
    claims = list((await ctx.db.execute(select(Claim).where(Claim.project_id == project_id).order_by(Claim.claim_key))).scalars())
    ids = [c.id for c in claims]
    sup = list(await ctx.db.execute(select(ClaimSupport).where(ClaimSupport.claim_id.in_(ids)))) if ids else []
    recs = list(await ctx.db.execute(select(VerificationRecord).where(VerificationRecord.claim_id.in_(ids)))) if ids else []
    decs = list(await ctx.db.execute(select(ClaimDecision).where(ClaimDecision.claim_id.in_(ids))
                                      .order_by(ClaimDecision.created_at))) if ids else []
    group = lambda rows, key: {k: [r[0] for r in rows if getattr(r[0], key) == k] for k in ids}  # noqa: E731
    gs, gr, gd = group(sup, "claim_id"), group(recs, "claim_id"), group(decs, "claim_id")
    policy = await claim_svc.active_policy(ctx.db)
    return {"passages": [passage_out(p) for p in passages],
            "claims": [claim_out(c, gs.get(c.id), gr.get(c.id), gd.get(c.id)) for c in claims],
            "policy": {"version": policy.version, "requirements": REQUIREMENTS},
            "labels": {"deterministic": "Deterministic check", "model_assisted": "Model-assisted (not human verification)",
                       "human": "Human"}}


class ClaimIn(BaseModel):
    proposition: str = Field(min_length=5, max_length=4000)
    kind: ClaimKind = ClaimKind.LITERATURE
    category: ClaimCategory = ClaimCategory.DESCRIPTIVE
    subject: str | None = None
    population_or_dataset: str | None = None
    measure: str | None = None
    comparison: str | None = None
    time: str | None = None
    scope: str | None = None
    critical: bool | None = None


def normalize_claim(body: ClaimIn) -> dict:
    return {k: getattr(body, k) for k in ("subject", "population_or_dataset", "measure", "comparison", "time", "scope")}


@router.post("/projects/{project_id}/claims", status_code=201)
async def create_claim(project_id: uuid.UUID, body: ClaimIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    norm = normalize_claim(body)
    sig = content_hash({"p": " ".join(body.proposition.lower().split()), "n": norm, "k": body.kind.value,
                        "c": body.category.value})
    existing = (await ctx.db.execute(select(Claim).where(Claim.project_id == project_id,
                                                         Claim.normalized["signature"].astext == sig))).scalars().first()
    if existing:
        return claim_out(existing)
    c = Claim(tenant_id=ctx.tenant_id, project_id=project_id, claim_key=await claim_svc.next_claim_key(ctx.db, project_id),
              proposition=body.proposition, normalized={**norm, "signature": sig}, kind=body.kind.value,
              category=body.category.value,
              critical=body.critical if body.critical is not None else claim_svc.is_critical(body.category.value),
              created_by=ctx.principal.actor_id, origin="researcher")
    ctx.db.add(c)
    await ctx.db.flush()
    await claim_svc.reevaluate(ctx.db, ctx.principal, c)
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.INTERPRETATION if body.kind != ClaimKind.LITERATURE
                         else LedgerCategory.ANALYSIS, f"Registered claim {c.claim_key}: {body.proposition[:200]}",
                         source_action="claim.create", source_ref=c.claim_key)
    await ctx.db.commit()
    return claim_out(c)


class ClaimEditIn(BaseModel):
    proposition: str = Field(min_length=5, max_length=4000)
    category: ClaimCategory | None = None
    scope: str | None = None


@router.post("/claims/{claim_id}/revise", status_code=201)
async def revise_claim(claim_id: uuid.UUID, body: ClaimEditIn, ctx: Ctx = Depends(user_ctx)):
    """A changed qualifier, number, population or causal strength is a new claim; verification reopens."""
    c = await _claim(ctx.db, claim_id)
    project, _ = await project_for(ctx, c.project_id, EDIT_ROLES)
    new = Claim(tenant_id=c.tenant_id, project_id=c.project_id, claim_key=await claim_svc.next_claim_key(ctx.db, c.project_id),
                proposition=body.proposition, normalized={**c.normalized, "scope": body.scope or c.normalized.get("scope"),
                                                          "signature": content_hash([body.proposition, c.id.hex])},
                kind=c.kind, category=(body.category.value if body.category else c.category), critical=c.critical,
                created_by=ctx.principal.actor_id, origin="researcher", supersedes_id=c.id)
    ctx.db.add(new)
    await ctx.db.flush()
    c.superseded_by = new.id
    c.gate_eligible = False
    await claim_svc.reevaluate(ctx.db, ctx.principal, new)
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.INTERPRETATION,
                         f"Revised {c.claim_key} as {new.claim_key}", source_action="claim.revise",
                         diff=ledger.text_diff(c.proposition, body.proposition, "claim"))
    await ctx.db.commit()
    return claim_out(new)


async def _claim(db: AsyncSession, claim_id: uuid.UUID) -> Claim:
    c = (await db.execute(select(Claim).where(Claim.id == claim_id))).scalar_one_or_none()
    if c is None:
        raise not_found("claim")
    return c


class SupportIn(BaseModel):
    passage_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None
    result_ref: str | None = Field(default=None, max_length=200)
    relation: str = Field(default="supports", pattern="^(supports|contradicts|qualifies|closest_work)$")


@router.post("/claims/{claim_id}/support", status_code=201)
async def link_support(claim_id: uuid.UUID, body: SupportIn, ctx: Ctx = Depends(user_ctx)):
    c = await _claim(ctx.db, claim_id)
    await project_for(ctx, c.project_id, EDIT_ROLES)
    if not (body.passage_id or body.paper_id or body.result_ref):
        raise unprocessable("evidence_required", "link a passage, a paper or a committed result")
    paper_id = body.paper_id
    passage = None
    if body.passage_id:
        passage = (await ctx.db.execute(select(EvidencePassage).where(EvidencePassage.id == body.passage_id,
                                                                      EvidencePassage.project_id == c.project_id))).scalar_one_or_none()
        if passage is None:
            raise not_found("passage")
        paper_id = passage.paper_id
    paper = await _paper(ctx.db, c.project_id, paper_id) if paper_id else None
    s = ClaimSupport(tenant_id=c.tenant_id, claim_id=c.id, passage_id=body.passage_id, paper_id=paper_id,
                     result_ref=body.result_ref, relation=body.relation,
                     bibliographic_identity_verified=bool(paper and paper.identity_status == "verified"),
                     passage_verified=bool(passage and passage.verified_in_source))
    ctx.db.add(s)
    await ctx.db.flush()
    if paper is not None:
        ctx.db.add(VerificationRecord(tenant_id=c.tenant_id, project_id=c.project_id, claim_id=c.id, support_id=s.id,
                                      paper_id=paper.id, check="identity", outcome=paper.identity_status,
                                      method="deterministic", verifier="crossref-identity-check", verifier_version="1",
                                      evidence=paper.identity_verification))
    if passage is not None:
        ctx.db.add(VerificationRecord(tenant_id=c.tenant_id, project_id=c.project_id, claim_id=c.id, support_id=s.id,
                                      paper_id=paper_id, check="passage",
                                      outcome="verified" if passage.verified_in_source else "unverified",
                                      method="deterministic", verifier="verbatim-quote-locator", verifier_version="1",
                                      evidence={"locator": passage.locator, "source_kind": passage.source_kind},
                                      source_version_hash=passage.source_hash))
    if body.relation == "closest_work":
        ctx.db.add(VerificationRecord(tenant_id=c.tenant_id, project_id=c.project_id, claim_id=c.id, support_id=s.id,
                                      paper_id=paper_id, check="closest_work", outcome="linked", method="human",
                                      verifier=ctx.principal.actor_id, verifier_version="ui-1"))
    await claim_svc.reevaluate(ctx.db, ctx.principal, c)
    await ctx.db.commit()
    return {"support_id": str(s.id), "claim": claim_out(c)}


class VerifyIn(BaseModel):
    human_support: bool | None = None
    human_support_note: str | None = Field(default=None, max_length=4000)
    human_judgment: str | None = Field(default=None, max_length=8000, description="the researcher's own assessment")
    closest_work_note: str | None = Field(default=None, max_length=8000)
    units: str | None = Field(default=None, max_length=400)
    authoritative_source_url: str | None = Field(default=None, max_length=2048)
    authoritative_source_note: str | None = Field(default=None, max_length=4000)
    resolve_contradiction: str | None = Field(default=None, max_length=4000)
    resolve_strength_mismatch: str | None = Field(default=None, max_length=4000)
    request_model_assessment: bool = False


@router.post("/claims/{claim_id}/verify")
async def verify_claim(claim_id: uuid.UUID, body: VerifyIn, ctx: Ctx = Depends(user_ctx)):
    """Record human checks and/or request a model-assisted support assessment, then re-evaluate under policy."""
    c = await _claim(ctx.db, claim_id)
    project, _ = await project_for(ctx, c.project_id, EDIT_ROLES)
    who = ctx.principal.actor_id

    def human(check, outcome, evidence=None):
        ctx.db.add(VerificationRecord(tenant_id=c.tenant_id, project_id=c.project_id, claim_id=c.id, check=check,
                                      outcome=outcome, method="human", verifier=who, verifier_version="ui-1",
                                      evidence=evidence or {}))
    if body.human_support is not None:
        human("support", "supports" if body.human_support else "does_not_support", {"note": body.human_support_note})
    if body.human_judgment:
        human("human_judgment", "recorded", {"statement": body.human_judgment})
        await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.INTERPRETATION,
                             f"Scientific judgment on {c.claim_key}", source_action="claim.judgment",
                             rationale=body.human_judgment, rationale_requested=False)
    if body.closest_work_note:
        human("closest_work", "assessed", {"note": body.closest_work_note})
    if body.units:
        human("units", "recorded", {"units": body.units})
    if body.authoritative_source_url:
        human("authoritative_source", "recorded", {"url": body.authoritative_source_url,
                                                   "note": body.authoritative_source_note})
    if body.resolve_contradiction:
        human("contradiction", "resolved", {"note": body.resolve_contradiction})
    if body.resolve_strength_mismatch:
        human("strength", "resolved_by_human", {"note": body.resolve_strength_mismatch})
    task = None
    if body.request_model_assessment:
        sups = list((await ctx.db.execute(select(ClaimSupport).where(ClaimSupport.claim_id == c.id,
                                                                     ClaimSupport.passage_id.is_not(None),
                                                                     ClaimSupport.is_current.is_(True)))).scalars())
        if not sups:
            raise unprocessable("no_passage", "link an evidence passage before requesting a support assessment")
        t, _ = await create_task(ctx.db, ctx.principal, project, "claim_support_check",
                                 {"claim_id": str(c.id), "support_ids": [str(s.id) for s in sups]},
                                 input_manifest={"claim": str(c.id), "v": c.version, "supports": sorted(str(s.id) for s in sups)})
        task = task_out(t)
    await ctx.db.flush()
    await claim_svc.reevaluate(ctx.db, ctx.principal, c)
    await ctx.db.commit()
    return {"claim": claim_out(c), "task": task}


# --------------------------------------------------------------------------- coverage
async def compute_coverage(db: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    runs = list((await db.execute(select(SearchRun).where(SearchRun.project_id == project_id,
                                                          SearchRun.status.in_(["succeeded", "partial"])))).scalars())
    results = list((await db.execute(select(SearchResult).join(SearchRun, SearchRun.id == SearchResult.search_run_id)
                                     .where(SearchRun.project_id == project_id))).scalars())
    papers = list((await db.execute(select(TenantPaperRecord).where(TenantPaperRecord.project_id == project_id))).scalars())
    screening = list((await db.execute(select(ScreeningDecision).where(ScreeningDecision.project_id == project_id,
                                                                       ScreeningDecision.is_current.is_(True)))).scalars())
    passages = list((await db.execute(select(EvidencePassage).where(EvidencePassage.project_id == project_id,
                                                                    EvidencePassage.verified_in_source.is_(True)))).scalars())
    verified_claims = list((await db.execute(select(Claim).where(Claim.project_id == project_id,
                                                                 Claim.status == "verified"))).scalars())
    sup_papers = set()
    if verified_claims:
        sups = list((await db.execute(select(ClaimSupport).where(ClaimSupport.claim_id.in_([c.id for c in verified_claims]),
                                                                 ClaimSupport.relation == "supports"))).scalars())
        pas = {p.id: p for p in passages}
        sup_papers = {s.paper_id for s in sups if s.paper_id} | {pas[s.passage_id].paper_id for s in sups if s.passage_id in pas}
    sources = sorted({p for r in runs for p, st in (r.provider_status or {}).items() if st.get("status") in ("ok", "partial")})
    failed = sorted({f"{p}: {st.get('error') or st.get('status')}" for r in runs for p, st in (r.provider_status or {}).items()
                     if st.get("status") not in ("ok", "partial")})
    fulltext_reviewed = [p for p in papers if p.fulltext_status in ("parsed",)]
    abstract_only = [p for p in papers if p.fulltext_status != "parsed" and p.abstract]
    meta_only = [p for p in papers if p.fulltext_status != "parsed" and not p.abstract]
    inaccessible = [p for p in papers if p.fulltext_status in ("not_permitted", "inaccessible")]
    excluded = [s for s in screening if s.decision == "exclude"]
    counts = {
        "sources_queried": sources, "unavailable_sources": failed,
        "queries": [{"query": r.query, "filters": r.filters, "executed_at": r.executed_at.isoformat() if r.executed_at else None,
                     "providers": r.provider_status} for r in runs],
        "retrieved_records": len(results), "unique_records": len({r.paper_id for r in results}),
        "papers_total": len(papers), "manual_or_uploaded": sum(1 for p in papers if p.origin in ("manual", "upload")),
        "fulltext_reviewed": len(fulltext_reviewed), "abstract_only": len(abstract_only),
        "metadata_only": len(meta_only), "fulltext_inaccessible_or_not_permitted": len(inaccessible),
        "screened": len({s.paper_id for s in screening}),
        "included": len({s.paper_id for s in screening if s.decision == "include"}),
        "excluded": len({s.paper_id for s in excluded}),
        "exclusion_reasons": sorted({s.reason for s in excluded}),
        "papers_contributing_verified_evidence": len(sup_papers),
        "identity_verified": sum(1 for p in papers if p.identity_status == "verified"),
        "identity_problems": sum(1 for p in papers if p.identity_status in ("mismatch", "not_found")),
    }
    limitations = ["Only the listed sources were searched; other databases were not queried."]
    if failed:
        limitations.append("Some sources were unavailable: " + "; ".join(failed))
    if counts["abstract_only"] + counts["metadata_only"]:
        limitations.append(f"{counts['abstract_only'] + counts['metadata_only']} records were not reviewed in full text.")
    if counts["fulltext_inaccessible_or_not_permitted"]:
        limitations.append(f"{counts['fulltext_inaccessible_or_not_permitted']} papers had no accessible or permitted full text.")
    if not counts["screened"]:
        limitations.append("No screening decisions have been recorded.")
    if counts["fulltext_reviewed"] >= 20 and len(sources) >= 2:
        level, why = "moderate", "two or more sources and at least 20 full texts reviewed"
    elif counts["fulltext_reviewed"] >= 5:
        level, why = "limited", "few full texts reviewed"
    else:
        level, why = "minimal", "almost no full-text review"
    date = max((r.executed_at for r in runs if r.executed_at), default=None)
    message = COVERAGE_TEMPLATE.format(sources=", ".join(sources) or "no sources", date=date.date().isoformat() if date else "—",
                                       n=counts["unique_records"], m=counts["fulltext_reviewed"],
                                       k=counts["abstract_only"] + counts["metadata_only"])
    return {"counts": counts, "coverage_level": level, "rationale": f"{level}: {why}. Coverage is never labelled comprehensive.",
            "limitations": limitations, "message": message}


@router.get("/projects/{project_id}/literature-coverage")
async def literature_coverage(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Versioned coverage assessment derived only from stored search, screening and evidence records."""
    project, _ = await project_for(ctx, project_id)
    cov = await compute_coverage(ctx.db, project_id)
    ih = content_hash(cov)
    last = (await ctx.db.execute(select(LiteratureCoverageAssessment).where(
        LiteratureCoverageAssessment.project_id == project_id).order_by(
        LiteratureCoverageAssessment.assessment_version.desc()))).scalars().first()
    if last is None or last.inputs_hash != ih:
        pub = await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "coverage_assessment", cov,
                                         label="Literature coverage assessment")
        last = LiteratureCoverageAssessment(tenant_id=ctx.tenant_id, project_id=project_id,
                                            assessment_version=(last.assessment_version + 1) if last else 1,
                                            counts=cov["counts"], coverage_level=cov["coverage_level"],
                                            rationale=cov["rationale"], limitations=cov["limitations"],
                                            message=cov["message"], artifact_id=pub.artifact.id, inputs_hash=ih)
        ctx.db.add(last)
        await ctx.db.commit()
    return {"version": last.assessment_version, "artifact_id": str(last.artifact_id), **cov}


# --------------------------------------------------------------------------- verification policies
@router.get("/verification-policies")
async def policies(ctx: Ctx = Depends(user_ctx)):
    from ..db.models.literature import VerificationPolicyRecord

    rows = (await ctx.db.execute(select(VerificationPolicyRecord).order_by(VerificationPolicyRecord.created_at))).scalars()
    return {"items": [{"version": r.version, "active": r.active, "rules": r.rules, "published_by": r.published_by,
                       "supersedes": r.supersedes, "at": r.created_at} for r in rows], "requirements": REQUIREMENTS}


@router.post("/verification-policies", status_code=201)
async def publish_policy(body: VerificationPolicy, ctx: Ctx = Depends(user_ctx)):
    from .discovery import require_operator

    operator = await require_operator(ctx)
    unknown = {r for rule in body.rules for r in rule.requires if r not in REQUIREMENTS}
    if unknown:
        raise unprocessable("unknown_requirement", f"unknown requirements: {sorted(unknown)}")
    try:
        res = await claim_svc.publish_policy(body, operator)
    except ValueError as exc:
        raise conflict("policy_exists", str(exc)) from exc
    await audit(ctx.db, ctx.principal, "policy.published", details=res)
    await ctx.db.commit()
    return res


@router.post("/projects/{project_id}/claims/reassess")
async def reassess(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id, EDIT_ROLES)
    res = await claim_svc.reassess_project(ctx.db, ctx.principal, project_id)
    await ctx.db.commit()
    return res


# --------------------------------------------------------------------------- internal (workers)
class RecordIn(BaseModel):
    provider: str
    rank: int
    record: dict[str, Any]


class ProviderStatusIn(BaseModel):
    status: str
    total_reported: int | None = None
    retrieved: int = 0
    error: str | None = None
    notes: list[str] = Field(default_factory=list)


class ResultsIn(BaseModel):
    provider_status: dict[str, ProviderStatusIn]
    results: list[RecordIn]
    record_artifact_id: uuid.UUID


@router.post("/internal/projects/{project_id}/search-runs/{run_id}/results")
async def ingest_results(project_id: uuid.UUID, run_id: uuid.UUID, body: ResultsIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "literature_search")
    run = (await ctx.db.execute(select(SearchRun).where(SearchRun.id == run_id, SearchRun.project_id == project_id)
                                .with_for_update())).scalar_one_or_none()
    if run is None:
        raise not_found("search run")
    if run.status in ("succeeded", "partial", "failed"):
        return {"replayed": True, "status": run.status}
    await art_svc.require_committed(ctx.db, [body.record_artifact_id], project_id)
    created = 0
    for item in body.results:
        rec = item.record
        doi = normalize_doi(rec.get("doi"))
        p = None
        if doi:
            p = (await ctx.db.execute(select(TenantPaperRecord).where(TenantPaperRecord.project_id == project_id,
                                                                      TenantPaperRecord.doi == doi))).scalar_one_or_none()
        if p is None:
            p = (await ctx.db.execute(select(TenantPaperRecord).where(
                TenantPaperRecord.project_id == project_id, TenantPaperRecord.doi.is_(None),
                func.lower(TenantPaperRecord.title) == (rec.get("title") or "").lower()))).scalars().first()
        if p is None:
            r = rights_for(rec.get("license"), rec.get("open_access"))
            p = TenantPaperRecord(tenant_id=ctx.tenant_id, project_id=project_id, doi=doi, title=rec.get("title") or "",
                                  authors=rec.get("authors") or [], year=rec.get("year"), venue=rec.get("venue"),
                                  abstract=rec.get("abstract"), abstract_rights=rec.get("abstract_rights") or "unknown",
                                  license=rec.get("license"), open_access=rec.get("open_access"),
                                  fulltext_locations=rec.get("fulltext") or [],
                                  fulltext_status="located" if rec.get("fulltext") else "none", rights=r.model_dump(),
                                  sources=[item.provider], origin="search", added_by=ctx.principal.actor_id,
                                  embedding=embed(f"{rec.get('title') or ''} {rec.get('abstract') or ''}"),
                                  embedding_model=EMBEDDING_MODEL)
            ctx.db.add(p)
            await ctx.db.flush()
            created += 1
        else:
            if item.provider not in (p.sources or []):
                p.sources = [*(p.sources or []), item.provider]
            p.abstract = p.abstract or rec.get("abstract")
            known = {loc["url"] for loc in p.fulltext_locations or []}
            p.fulltext_locations = (p.fulltext_locations or []) + [loc for loc in rec.get("fulltext") or [] if loc["url"] not in known]
            if p.license is None and rec.get("license"):
                p.license = rec.get("license")
                p.rights = rights_for(p.license, p.open_access).model_dump()
        if doi and p.global_paper_id is None and rec.get("metadata_license", "").startswith(("CC0", "CC-BY")):
            p.global_paper_id = await upsert_global(rec, doi)
        ctx.db.add(SearchResult(tenant_id=ctx.tenant_id, search_run_id=run.id, provider=item.provider, rank=item.rank,
                                external_id=str(rec.get("external_id") or "")[:400], doi=doi, title=rec.get("title") or "",
                                paper_id=p.id))
    run.provider_status = {**(run.provider_status or {}), **{k: v.model_dump() for k, v in body.provider_status.items()}}
    statuses = {v.status for v in body.provider_status.values()}
    run.status = "succeeded" if statuses <= {"ok"} else ("failed" if not (statuses & {"ok", "partial"}) else "partial")
    run.executed_at = utcnow()
    run.retrieved_count = len(body.results)
    run.record_artifact_id = body.record_artifact_id
    await ctx.db.commit()
    unverified = (await ctx.db.execute(select(TenantPaperRecord.id).where(
        TenantPaperRecord.project_id == project_id, TenantPaperRecord.identity_status == "unverified",
        TenantPaperRecord.doi.is_not(None)))).scalars().all()
    return {"status": run.status, "created": created, "unverified_paper_ids": [str(i) for i in unverified]}


async def upsert_global(rec: dict, doi: str) -> uuid.UUID:
    """Share only rights-cleared bibliographic metadata across tenants (never abstracts or private fields)."""
    async with session_scope("ingest") as idb:
        ident = (await idb.execute(select(GlobalPaperIdentifier).where(GlobalPaperIdentifier.scheme == "doi",
                                                                       GlobalPaperIdentifier.value == doi))).scalar_one_or_none()
        if ident:
            return ident.paper_id
        meta = {k: rec.get(k) for k in ("title", "authors", "year", "venue", "publisher", "type")}
        gp = GlobalPaper(title=rec.get("title") or "", authors=rec.get("authors") or [], year=rec.get("year"),
                         venue=rec.get("venue"), publisher=rec.get("publisher"), type=rec.get("type"),
                         metadata_license=rec.get("metadata_license") or "unknown", attribution=rec.get("attribution"),
                         source_provider=rec.get("provider") or "unknown", source_record_hash=content_hash(meta),
                         retrieved_at=utcnow())
        idb.add(gp)
        await idb.flush()
        idb.add(GlobalPaperIdentifier(paper_id=gp.id, scheme="doi", value=doi))
        try:
            await idb.commit()
        except Exception:  # noqa: BLE001 - concurrent insert by another tenant: reuse theirs
            await idb.rollback()
            ident = (await idb.execute(select(GlobalPaperIdentifier).where(GlobalPaperIdentifier.scheme == "doi",
                                                                           GlobalPaperIdentifier.value == doi))).scalar_one()
            return ident.paper_id
        return gp.id


@router.get("/internal/projects/{project_id}/search-runs/{run_id}")
async def internal_run(project_id: uuid.UUID, run_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.read")
    run = (await ctx.db.execute(select(SearchRun).where(SearchRun.id == run_id, SearchRun.project_id == project_id))).scalar_one_or_none()
    if run is None:
        raise not_found("search run")
    return run_out(run)


@router.get("/internal/projects/{project_id}/papers/{paper_id}")
async def internal_paper(project_id: uuid.UUID, paper_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.read")
    return paper_out(await _paper(ctx.db, project_id, paper_id))


class IdentityIn(BaseModel):
    status: str = Field(pattern="^(verified|mismatch|not_found|unavailable)$")
    evidence: dict[str, Any]


@router.post("/internal/projects/{project_id}/papers/{paper_id}/identity")
async def record_identity(project_id: uuid.UUID, paper_id: uuid.UUID, body: IdentityIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "literature_search")
    p = await _paper(ctx.db, project_id, paper_id)
    if body.status != "unavailable":
        p.identity_status = body.status
    p.identity_verification = {**body.evidence, "method": "deterministic", "checked_at": utcnow().isoformat(),
                               "verifier": "crossref-identity-check/1", "outcome": body.status}
    if body.status == "verified" and body.evidence.get("record"):
        r = body.evidence["record"]
        if p.origin == "manual" and p.title.startswith("[DOI"):
            p.title = r.get("title") or p.title
            p.authors = r.get("authors") or p.authors
            p.year = r.get("year") or p.year
            p.venue = r.get("venue") or p.venue
    # Identity changes propagate to claims that cite the paper.
    sups = list((await ctx.db.execute(select(ClaimSupport).where(ClaimSupport.paper_id == p.id))).scalars())
    for s in sups:
        s.bibliographic_identity_verified = body.status == "verified"
        c = await _claim(ctx.db, s.claim_id)
        await claim_svc.reevaluate(ctx.db, ctx.principal, c)
    await ctx.db.commit()
    return paper_out(p)


class FulltextIn(BaseModel):
    status: str = Field(pattern="^(retrieved|parsed|not_permitted|inaccessible)$")
    fulltext_artifact_id: uuid.UUID | None = None
    text_artifact_id: uuid.UUID | None = None
    detail: str | None = None
    license: str | None = None
    rights: dict[str, Any] | None = None


@router.post("/internal/projects/{project_id}/papers/{paper_id}/fulltext")
async def record_fulltext(project_id: uuid.UUID, paper_id: uuid.UUID, body: FulltextIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "evidence_extraction")
    p = await _paper(ctx.db, project_id, paper_id)
    ids = [i for i in (body.fulltext_artifact_id, body.text_artifact_id) if i]
    await art_svc.require_committed(ctx.db, ids, project_id)
    p.fulltext_status = body.status
    if body.fulltext_artifact_id:
        p.fulltext_artifact_id = body.fulltext_artifact_id
    if body.text_artifact_id:
        p.fulltext_text_artifact_id = body.text_artifact_id
    if body.license:
        p.license = body.license
    if body.rights:
        p.rights = body.rights
    p.identity_verification = {**(p.identity_verification or {}), "fulltext_detail": body.detail}
    await ctx.db.commit()
    return paper_out(p)


class PassageIn(BaseModel):
    quote: str
    role: str
    summary: str | None = None
    section_hint: str | None = None
    source_kind: str = Field(pattern="^(fulltext|abstract)$")


class ExtractedClaimIn(BaseModel):
    proposition: str
    category: str
    passage_indices: list[int]
    population_or_dataset: str | None = None
    measure: str | None = None
    comparison: str | None = None
    scope: str | None = None


class ExtractionIn(BaseModel):
    source_artifact_id: uuid.UUID | None = None
    extraction_artifact_id: uuid.UUID
    method: str = Field(pattern="^(model_assisted|deterministic)$")
    extractor: str
    passages: list[PassageIn]
    claims: list[ExtractedClaimIn] = Field(default_factory=list)
    study: dict[str, Any] = Field(default_factory=dict)


@router.post("/internal/projects/{project_id}/papers/{paper_id}/extraction")
async def record_extraction(project_id: uuid.UUID, paper_id: uuid.UUID, body: ExtractionIn, ctx: Ctx = Depends(service_ctx)):
    """Persist passages; the API re-verifies every quote verbatim against the committed source text."""
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "evidence_extraction")
    p = await _paper(ctx.db, project_id, paper_id)
    await art_svc.require_committed(ctx.db, [body.extraction_artifact_id], project_id)
    full_text, src_hash = "", None
    if body.source_artifact_id:
        src = await art_svc.get_artifact(ctx.db, body.source_artifact_id, project_id)
        full_text = (await art_svc.read_artifact_json(src))["text"]
        src_hash = src.content_hash
    created, dropped = [], 0
    for ps in body.passages:
        text = full_text if ps.source_kind == "fulltext" else (p.abstract or "")
        span = find_span(text, ps.quote) if text else None
        if span is None:
            dropped += 1
            continue
        qh = sha256_hex(ps.quote.encode())
        existing = (await ctx.db.execute(select(EvidencePassage).where(EvidencePassage.paper_id == p.id,
                                                                       EvidencePassage.quote_hash == qh))).scalars().first()
        if existing:
            created.append(existing)
            continue
        ep = EvidencePassage(tenant_id=ctx.tenant_id, project_id=project_id, paper_id=p.id, quote=ps.quote, quote_hash=qh,
                             role=ps.role, summary=ps.summary,
                             locator={"char_start": span[0], "char_end": span[1], "section": ps.section_hint},
                             source_kind=ps.source_kind, source_artifact_id=body.source_artifact_id if ps.source_kind == "fulltext" else None,
                             source_hash=src_hash if ps.source_kind == "fulltext" else sha256_hex((p.abstract or "").encode()),
                             verified_in_source=True, extraction_method=body.method, extracted_by=body.extractor,
                             extraction_artifact_id=body.extraction_artifact_id)
        ctx.db.add(ep)
        await ctx.db.flush()
        created.append(ep)
    claim_ids = []
    for cl in body.claims:
        idx = [i for i in cl.passage_indices if 0 <= i < len(body.passages)]
        quotes = {sha256_hex(body.passages[i].quote.encode()) for i in idx}
        linked = [e for e in created if e.quote_hash in quotes]
        if not linked:
            continue  # a claim without a verified passage is not registered from extraction
        category = cl.category if cl.category in claim_svc.CATEGORIES else "descriptive"
        norm = {"population_or_dataset": cl.population_or_dataset, "measure": cl.measure, "comparison": cl.comparison,
                "scope": cl.scope, "signature": content_hash([cl.proposition.lower(), str(p.id)])}
        c = Claim(tenant_id=ctx.tenant_id, project_id=project_id, claim_key=await claim_svc.next_claim_key(ctx.db, project_id),
                  proposition=cl.proposition, normalized=norm, kind="literature", category=category,
                  critical=claim_svc.is_critical(category), created_by=ctx.principal.actor_id, origin="extracted")
        ctx.db.add(c)
        await ctx.db.flush()
        for e in linked:
            s = ClaimSupport(tenant_id=ctx.tenant_id, claim_id=c.id, passage_id=e.id, paper_id=p.id, relation="supports",
                             bibliographic_identity_verified=p.identity_status == "verified", passage_verified=True)
            ctx.db.add(s)
            await ctx.db.flush()
            ctx.db.add(VerificationRecord(tenant_id=ctx.tenant_id, project_id=project_id, claim_id=c.id, support_id=s.id,
                                          paper_id=p.id, check="passage", outcome="verified", method="deterministic",
                                          verifier="verbatim-quote-locator", verifier_version="1",
                                          evidence={"locator": e.locator}, source_version_hash=e.source_hash))
        await claim_svc.reevaluate(ctx.db, ctx.principal, c)
        claim_ids.append(str(c.id))
    if full_text and p.fulltext_status != "parsed":
        p.fulltext_status = "parsed"
    await ctx.db.commit()
    return {"passages": len(created), "dropped_unverified_quotes": dropped, "claims": claim_ids}


class AssessmentIn(BaseModel):
    support_id: uuid.UUID
    verdict: str
    strength_mismatch: bool
    scope_notes: str | None = None
    uncertainty: str
    provenance: dict[str, Any]


@router.post("/internal/claims/{claim_id}/support-assessment")
async def record_assessment(claim_id: uuid.UUID, body: AssessmentIn, ctx: Ctx = Depends(service_ctx)):
    c = await _claim(ctx.db, claim_id)
    require_service_scope(ctx, c.project_id, "domain.write")
    require_task_kind(ctx, "claim_support_check")
    s = (await ctx.db.execute(select(ClaimSupport).where(ClaimSupport.id == body.support_id,
                                                         ClaimSupport.claim_id == c.id))).scalar_one_or_none()
    if s is None:
        raise not_found("support")
    outcome = {"supports": "supports", "partially_supports": "partial", "does_not_support": "does_not_support",
               "contradicts": "contradicts"}.get(body.verdict, "unclear")
    for old in (await ctx.db.execute(select(VerificationRecord).where(VerificationRecord.support_id == s.id,
                                                                      VerificationRecord.check.in_(["support", "strength"]),
                                                                      VerificationRecord.method == "model_assisted"))).scalars():
        old.is_current = False
    label = body.provenance.get("label", "model-assisted")
    ctx.db.add(VerificationRecord(tenant_id=c.tenant_id, project_id=c.project_id, claim_id=c.id, support_id=s.id,
                                  check="support", outcome=outcome, method="model_assisted",
                                  verifier=f"{body.provenance.get('provider')}:{body.provenance.get('model')}",
                                  verifier_version=body.provenance.get("prompt_version", ""),
                                  evidence={"scope_notes": body.scope_notes, "label": label, **body.provenance},
                                  uncertainty=body.uncertainty, requires_human_confirmation=claim_svc.is_critical(c.category)))
    ctx.db.add(VerificationRecord(tenant_id=c.tenant_id, project_id=c.project_id, claim_id=c.id, support_id=s.id,
                                  check="strength", outcome="mismatch" if body.strength_mismatch else "ok",
                                  method="model_assisted", verifier=str(body.provenance.get("provider")),
                                  verifier_version=body.provenance.get("prompt_version", ""), evidence={"label": label}))
    s.claim_support_validated = outcome == "supports" and not body.strength_mismatch
    await ctx.db.flush()
    await claim_svc.reevaluate(ctx.db, ctx.principal, c)
    await ctx.db.commit()
    return claim_out(c)


@router.get("/internal/claims/{claim_id}")
async def internal_claim(claim_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    c = await _claim(ctx.db, claim_id)
    require_service_scope(ctx, c.project_id, "domain.read")
    sups = list((await ctx.db.execute(select(ClaimSupport).where(ClaimSupport.claim_id == c.id))).scalars())
    pids = [s.passage_id for s in sups if s.passage_id]
    passages = list(await ctx.db.execute(select(EvidencePassage).where(EvidencePassage.id.in_(pids)))) if pids else []
    return {**claim_out(c, sups), "passages": [passage_out(p[0]) for p in passages]}


_ = (ApiError, OWNER_ONLY, datetime)
