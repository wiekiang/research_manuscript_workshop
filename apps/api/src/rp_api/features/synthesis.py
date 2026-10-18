"""M10 - validated evidence-synthesis (systematic, meta-analysis, mapping, scoping, tertiary) and qualitative methods.

Everything a validator checks comes from stored records: protocol-bound search runs with exact query strings, human
screening decisions with reasons from the frozen list, extraction/appraisal records linked to verified passages,
and deterministic synthesis results whose inputs hash must still match the current extraction set.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from rp_contracts.contribution import EthicsRightsDeclaration, ethics_blockers
from rp_contracts.enums import LedgerCategory
from rp_contracts.hashing import content_hash
from rp_contracts.synthesis import EffectRow, ReviewSpec, chart_map, flow_counts, flow_problems, overlap, pool
from rp_contracts.textmatch import find_span

from ..db.models.contribution import Contribution, Protocol
from ..db.models.literature import (
    EvidencePassage,
    ScreeningDecision,
    SearchResult,
    SearchRun,
    TenantPaperRecord,
)
from ..db.models.synthesis import ExtractionRecord, QualCode, QualSegment, QualTheme, SynthesisRecord
from ..deps import EDIT_ROLES, Ctx, project_for, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..routers.projects import task_out
from ..services import artifacts as art_svc
from ..services import ledger
from ..services.common import audit
from ..services.tasks import create_task
from . import method as method_mod
from .method import active_instance, frozen_protocol

router = APIRouter(tags=["synthesis"])


async def spec_of(db, project_id: uuid.UUID) -> tuple[Protocol, ReviewSpec]:
    inst = await active_instance(db, project_id)
    fp = await frozen_protocol(db, inst.id) if inst else None
    if fp is None:
        raise unprocessable("h2_required", "the review specification is used only from the H2-frozen protocol")
    raw = fp.sections.get("review_specification")
    if not raw:
        raise unprocessable("no_review_spec", "the frozen protocol has no review_specification section")
    try:
        return fp, ReviewSpec.model_validate_json(raw) if isinstance(raw, str) else ReviewSpec.model_validate(raw)
    except ValidationError as exc:
        raise unprocessable("invalid_review_spec", "the review specification does not validate", {"errors": exc.errors()}) from exc


def spec_problems(raw: str | None, study_type: str) -> list[str]:
    if not raw:
        return ["review_specification is empty"]
    try:
        s = ReviewSpec.model_validate_json(raw)
    except ValidationError as exc:
        return [f"review_specification: {e['msg']} at {'.'.join(str(x) for x in e['loc'])}" for e in exc.errors()]
    return [] if s.review_type == study_type else [f"review_specification.review_type must be {study_type}"]


async def _runs(db, fp: Protocol) -> list[SearchRun]:
    return list((await db.execute(select(SearchRun).where(SearchRun.protocol_id == fp.id, SearchRun.purpose == "systematic")
                                  .order_by(SearchRun.created_at))).scalars())


async def records(db, fp: Protocol) -> tuple[list[SearchRun], dict[str, int], set[str]]:
    runs = await _runs(db, fp)
    ids = [r.id for r in runs]
    res = list((await db.execute(select(SearchResult).where(SearchResult.search_run_id.in_(ids)))).scalars()) if ids else []
    return runs, {str(r.id): r.retrieved_count or 0 for r in runs}, {str(x.paper_id) for x in res if x.paper_id}


async def decisions(db, project_id: uuid.UUID, inst_id: uuid.UUID, stage: str) -> dict[str, dict]:
    rows = (await db.execute(select(ScreeningDecision).where(ScreeningDecision.project_id == project_id,
                                                             ScreeningDecision.method_instance_id == inst_id,
                                                             ScreeningDecision.stage == stage,
                                                             ScreeningDecision.is_current.is_(True)))).scalars()
    return {str(d.paper_id): {"decision": d.decision, "reason": d.reason, "method": d.method, "by": d.decided_by} for d in rows}


async def flow_for(db, project_id: uuid.UUID) -> tuple[Protocol, ReviewSpec, dict]:
    fp, spec = await spec_of(db, project_id)
    _, ident, unique = await records(db, fp)
    ta = await decisions(db, project_id, fp.method_instance_id, "title_abstract")
    ft = await decisions(db, project_id, fp.method_instance_id, "full_text")
    return fp, spec, flow_counts(ident, unique, {k: v for k, v in ta.items() if k in unique}, ft)


async def current_extractions(db, fp: Protocol) -> dict[str, ExtractionRecord]:
    return {str(e.paper_id): e for e in (await db.execute(select(ExtractionRecord).where(
        ExtractionRecord.protocol_id == fp.id, ExtractionRecord.is_current.is_(True)))).scalars()}


def extraction_inputs_hash(ex: dict[str, ExtractionRecord], included: list[str]) -> str:
    return content_hash([[pid, ex[pid].values, ex[pid].appraisal, ex[pid].effect, ex[pid].charting,
                          sorted(ex[pid].primary_studies)] for pid in sorted(included) if pid in ex])


# --------------------------------------------------------------------------- searches and screening
@router.post("/projects/{project_id}/review/searches", status_code=202)
async def run_review_searches(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Execute every search of the frozen specification exactly as written (query, provider, dates)."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    fp, spec = await spec_of(ctx.db, project_id)
    from .literature import provider_states

    states = await provider_states()
    out = []
    for s in spec.searches:
        st = states.get(s.provider)
        if st is None or not st.enabled or st.gate_status in ("blocked", "pending"):
            raise unprocessable("provider_unavailable", f"{s.provider} is not available ({st.gate_status if st else 'unknown'}); "
                                "amend the protocol to use an enabled source")
        run = SearchRun(tenant_id=ctx.tenant_id, project_id=project_id, purpose="systematic", query=s.query,
                        protocol_id=fp.id, filters={"year_from": s.year_from, "year_to": s.year_to, "max_results": s.max_results},
                        providers_requested=[s.provider], provider_status={})
        ctx.db.add(run)
        await ctx.db.flush()
        task, _ = await create_task(ctx.db, ctx.principal, project, "literature_search",
                                    {"mode": "search", "search_run_id": str(run.id)}, input_manifest={"run": str(run.id)})
        run.task_id = task.id
        out.append({"search_run_id": str(run.id), "provider": s.provider, "query": s.query, "task": task_out(task)})
    await audit(ctx.db, ctx.principal, "review.searches_executed", project_id=project_id, resource_type="protocol",
                resource_id=fp.id, details={"n": len(out)})
    await ctx.db.commit()
    return {"runs": out}


class ScreenIn(BaseModel):
    paper_id: uuid.UUID
    stage: str = Field(pattern="^(title_abstract|full_text)$")
    decision: str = Field(pattern="^(include|exclude)$")
    reason: str | None = Field(default=None, max_length=500)


@router.post("/projects/{project_id}/review/screening", status_code=201)
async def screen(project_id: uuid.UUID, body: ScreenIn, ctx: Ctx = Depends(user_ctx)):
    """Screening decisions are human decisions; an exclusion must use a reason from the frozen protocol."""
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    fp, spec = await spec_of(ctx.db, project_id)
    _, _, unique = await records(ctx.db, fp)
    pid = str(body.paper_id)
    if pid not in unique:
        raise unprocessable("not_a_record", "the paper is not a record of the protocol's searches")
    if body.decision == "exclude" and body.reason not in spec.exclusion_reasons:
        raise unprocessable("reason_not_in_protocol", "use one of the protocol's exclusion reasons",
                            {"allowed": spec.exclusion_reasons})
    if body.stage == "full_text":
        ta = await decisions(ctx.db, project_id, fp.method_instance_id, "title_abstract")
        if ta.get(pid, {}).get("decision") != "include":
            raise unprocessable("not_included_at_title_abstract", "only records included at title/abstract are assessed in full text")
    for old in (await ctx.db.execute(select(ScreeningDecision).where(
            ScreeningDecision.project_id == project_id, ScreeningDecision.method_instance_id == fp.method_instance_id,
            ScreeningDecision.paper_id == body.paper_id, ScreeningDecision.stage == body.stage,
            ScreeningDecision.is_current.is_(True)))).scalars():
        old.is_current = False
    d = ScreeningDecision(tenant_id=ctx.tenant_id, project_id=project_id, method_instance_id=fp.method_instance_id,
                          paper_id=body.paper_id, stage=body.stage, decision=body.decision,
                          reason=body.reason if body.decision == "exclude" else "meets the protocol's inclusion criteria",
                          criteria=[f"protocol:{fp.content_hash}"], method="human", decided_by=ctx.principal.actor_id)
    ctx.db.add(d)
    await ctx.db.commit()
    return {"paper_id": pid, "stage": body.stage, "decision": body.decision, "reason": body.reason}


class ValueIn(BaseModel):
    value: str | None = None
    passage_id: uuid.UUID | None = None
    not_reported: bool = False


class ExtractIn(BaseModel):
    paper_id: uuid.UUID
    values: dict[str, ValueIn] = Field(default_factory=dict)
    appraisal: dict[str, dict[str, str]] = Field(default_factory=dict)
    effect: dict[str, float] | None = None
    charting: dict[str, str] = Field(default_factory=dict)
    primary_studies: list[str] = Field(default_factory=list)


@router.post("/projects/{project_id}/review/extractions", status_code=201)
async def extract(project_id: uuid.UUID, body: ExtractIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    fp, spec, flow = await flow_for(ctx.db, project_id)
    pid = str(body.paper_id)
    if pid not in flow["included_ids"]:
        raise unprocessable("not_included", "extract only from studies included after full-text screening")
    problems = []
    for k, v in body.values.items():
        if v.passage_id:
            p = (await ctx.db.execute(select(EvidencePassage).where(EvidencePassage.id == v.passage_id))).scalar_one_or_none()
            if p is None or p.paper_id != body.paper_id or not p.verified_in_source:
                problems.append(f"{k}: the passage must be a verified passage of this study")
        elif not v.not_reported and v.value:
            problems.append(f"{k}: link the value to a verified passage of the study, or mark it not reported")
    for item, a in body.appraisal.items():
        spec_item = next((x for x in spec.appraisal_items if x.key == item), None)
        if spec_item is None or a.get("rating") not in spec_item.ratings or len(a.get("rationale", "")) < 5:
            problems.append(f"appraisal {item}: use a protocol item, one of its ratings and a rationale")
    if body.effect is not None and not ("estimate" in body.effect and body.effect.get("variance", 0) > 0):
        problems.append("effect needs an estimate and a positive variance")
    if problems:
        raise ApiError(422, "invalid_extraction", "the extraction record is not valid", {"problems": problems})
    for old in (await ctx.db.execute(select(ExtractionRecord).where(ExtractionRecord.protocol_id == fp.id,
                                                                    ExtractionRecord.paper_id == body.paper_id,
                                                                    ExtractionRecord.is_current.is_(True)))).scalars():
        old.is_current = False
    ctx.db.add(ExtractionRecord(tenant_id=ctx.tenant_id, project_id=project_id, protocol_id=fp.id, paper_id=body.paper_id,
                                values={k: v.model_dump(mode="json") for k, v in body.values.items()},
                                appraisal=body.appraisal, effect=body.effect, charting=body.charting,
                                primary_studies=body.primary_studies, recorded_by=ctx.principal.user_id))
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.ANALYSIS, "Recorded a study extraction/appraisal",
                         source_action="review.extract", rationale_requested=False)
    await ctx.db.commit()
    return {"paper_id": pid, "recorded": True}


# --------------------------------------------------------------------------- synthesis and appendix
async def _publish(ctx, project_id, fp, kind, result, inputs_hash) -> SynthesisRecord:
    art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "synthesis_record",
                                      {"kind": kind, "result": result, "inputs_hash": inputs_hash, "protocol": fp.content_hash},
                                      depends_on=[fp.artifact_id], label=f"Synthesis: {kind}")).artifact
    for old in (await ctx.db.execute(select(SynthesisRecord).where(SynthesisRecord.protocol_id == fp.id, SynthesisRecord.kind == kind,
                                                                   SynthesisRecord.is_current.is_(True)))).scalars():
        old.is_current = False
    rec = SynthesisRecord(tenant_id=ctx.tenant_id, project_id=project_id, protocol_id=fp.id, kind=kind, result=result,
                          inputs_hash=inputs_hash, artifact_id=art.id)
    ctx.db.add(rec)
    return rec


@router.post("/projects/{project_id}/review/synthesis", status_code=201)
async def synthesize(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Deterministic synthesis computed by the platform from the current extraction records."""
    await project_for(ctx, project_id, EDIT_ROLES)
    fp, spec, flow = await flow_for(ctx.db, project_id)
    ex = await current_extractions(ctx.db, fp)
    inc = flow["included_ids"]
    h = extraction_inputs_hash(ex, inc)
    out = {"flow": flow}
    await _publish(ctx, project_id, fp, "flow", flow, h)
    if spec.synthesis == "meta_analysis":
        rows = [EffectRow(study=pid, estimate=ex[pid].effect["estimate"], variance=ex[pid].effect["variance"])
                for pid in inc if pid in ex and ex[pid].effect]
        out["meta_analysis"] = pool(rows, spec.pooling_model or "random_dl") | {"effect_measure": spec.effect_measure}
        await _publish(ctx, project_id, fp, "meta_analysis", out["meta_analysis"], h)
    elif spec.synthesis == "map":
        out["map"] = chart_map(spec.charting_scheme, {pid: ex[pid].charting for pid in inc if pid in ex})
        await _publish(ctx, project_id, fp, "map", out["map"], h)
    elif spec.synthesis == "review_of_reviews":
        out["overlap"] = overlap({pid: ex[pid].primary_studies for pid in inc if pid in ex})
        await _publish(ctx, project_id, fp, "overlap", out["overlap"], h)
    await ctx.db.commit()
    return {**out, "inputs_hash": h}


@router.get("/projects/{project_id}/review")
async def review_workspace(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    fp, spec, flow = await flow_for(ctx.db, project_id)
    runs, _, unique = await records(ctx.db, fp)
    papers = {str(p.id): p for p in (await ctx.db.execute(select(TenantPaperRecord).where(
        TenantPaperRecord.id.in_([uuid.UUID(x) for x in unique])))).scalars()} if unique else {}
    ta = await decisions(ctx.db, project_id, fp.method_instance_id, "title_abstract")
    ft = await decisions(ctx.db, project_id, fp.method_instance_id, "full_text")
    ex = await current_extractions(ctx.db, fp)
    syn = {s.kind: {"result": s.result, "inputs_hash": s.inputs_hash, "artifact_id": str(s.artifact_id)} for s in (
        await ctx.db.execute(select(SynthesisRecord).where(SynthesisRecord.protocol_id == fp.id,
                                                           SynthesisRecord.is_current.is_(True)))).scalars()}
    return {"specification": spec.model_dump(), "protocol_hash": fp.content_hash, "flow": flow,
            "searches": [{"id": str(r.id), "query": r.query, "providers": r.providers_requested, "status": r.status,
                          "executed_at": r.executed_at, "retrieved": r.retrieved_count, "filters": r.filters} for r in runs],
            "records": [{"paper_id": pid, "title": papers[pid].title if pid in papers else None,
                         "doi": papers[pid].doi if pid in papers else None, "title_abstract": ta.get(pid),
                         "full_text": ft.get(pid), "extracted": pid in ex} for pid in sorted(unique)],
            "syntheses": syn, "current_inputs_hash": extraction_inputs_hash(ex, flow["included_ids"])}


@router.post("/projects/{project_id}/review/appendix", status_code=201)
async def appendix(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Reproducibility appendix: exact queries, sources, dates, counts, decisions with reasons, forms, amendments."""
    await project_for(ctx, project_id, EDIT_ROLES)
    fp, spec, flow = await flow_for(ctx.db, project_id)
    runs, _, _ = await records(ctx.db, fp)
    ta = await decisions(ctx.db, project_id, fp.method_instance_id, "title_abstract")
    ft = await decisions(ctx.db, project_id, fp.method_instance_id, "full_text")
    protos = list((await ctx.db.execute(select(Protocol).where(Protocol.method_instance_id == fp.method_instance_id)
                                        .order_by(Protocol.version_number))).scalars())
    syn = {s.kind: s.result for s in (await ctx.db.execute(select(SynthesisRecord).where(
        SynthesisRecord.protocol_id == fp.id, SynthesisRecord.is_current.is_(True)))).scalars()}
    data = {"reporting_standard": spec.reporting_standard, "protocol": {"version": fp.version_number, "hash": fp.content_hash},
            "searches": [{"provider": r.providers_requested, "query": r.query, "filters": r.filters, "executed_at":
                          r.executed_at.isoformat() if r.executed_at else None, "status": r.status,
                          "provider_status": r.provider_status, "retrieved": r.retrieved_count,
                          "record_artifact_id": str(r.record_artifact_id) if r.record_artifact_id else None} for r in runs],
            "flow": flow, "inclusion_criteria": spec.inclusion_criteria, "exclusion_reasons": spec.exclusion_reasons,
            "screening": {"title_abstract": ta, "full_text": ft}, "extraction_form": [f.model_dump() for f in spec.extraction_form],
            "appraisal_tool": spec.appraisal_tool, "appraisal_items": [i.model_dump() for i in spec.appraisal_items],
            "amendments": [{"version": p.version_number, "rationale": p.amendment_rationale,
                            "after_data_inspection": p.after_data_inspection} for p in protos if p.is_amendment],
            "synthesis": syn}
    art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "review_appendix", data,
                                      depends_on=[fp.artifact_id], label="Reproducibility appendix")).artifact
    await ctx.db.commit()
    return {"artifact_id": str(art.id), **json.loads(json.dumps(data, default=str))}


# --------------------------------------------------------------------------- qualitative coding audit trail
class CodeIn(BaseModel):
    code: str = Field(min_length=2, max_length=120)
    definition: str = Field(min_length=10, max_length=4000)


async def _qual_protocol(ctx: Ctx, project_id: uuid.UUID) -> Protocol:
    inst = await active_instance(ctx.db, project_id)
    fp = await frozen_protocol(ctx.db, inst.id) if inst else None
    if fp is None:
        raise unprocessable("h2_required", "coding happens under the H2-frozen protocol")
    return fp


@router.post("/projects/{project_id}/qual/codes", status_code=201)
async def add_code(project_id: uuid.UUID, body: CodeIn, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id, EDIT_ROLES)
    fp = await _qual_protocol(ctx, project_id)
    c = QualCode(tenant_id=ctx.tenant_id, project_id=project_id, protocol_id=fp.id, code=body.code, definition=body.definition,
                 created_by=ctx.principal.user_id)
    ctx.db.add(c)
    await ctx.db.commit()
    return {"id": str(c.id), "code": c.code}


class SegmentIn(BaseModel):
    code_id: uuid.UUID
    contribution_id: uuid.UUID
    quote: str = Field(min_length=5, max_length=5000)
    memo: str | None = Field(default=None, max_length=4000)


async def _source_text(ctx: Ctx, c: Contribution) -> str | None:
    if c.text:
        return c.text
    if c.artifact_id:
        art = await art_svc.get_artifact(ctx.db, c.artifact_id, c.project_id)
        if art.media_type.startswith("text/"):
            return (await art_svc.read_artifact_bytes(art)).decode("utf-8", errors="replace")
    return None


@router.post("/projects/{project_id}/qual/segments", status_code=201)
async def add_segment(project_id: uuid.UUID, body: SegmentIn, ctx: Ctx = Depends(user_ctx)):
    """A coded segment must quote its source verbatim (source-to-code trace)."""
    await project_for(ctx, project_id, EDIT_ROLES)
    code = (await ctx.db.execute(select(QualCode).where(QualCode.id == body.code_id, QualCode.project_id == project_id))).scalar_one_or_none()
    c = (await ctx.db.execute(select(Contribution).where(Contribution.id == body.contribution_id,
                                                         Contribution.project_id == project_id))).scalar_one_or_none()
    if code is None or c is None:
        raise not_found("code or source")
    text = await _source_text(ctx, c)
    span = find_span(text, body.quote) if text else None
    if span is None:
        raise unprocessable("quote_not_in_source", "the quote was not found verbatim in the source; copy it exactly")
    seg = QualSegment(tenant_id=ctx.tenant_id, project_id=project_id, code_id=code.id, contribution_id=c.id, quote=body.quote,
                      locator={"start": span[0], "end": span[1]} if isinstance(span, tuple) else None, verified=True,
                      memo=body.memo, coded_by=ctx.principal.user_id)
    ctx.db.add(seg)
    await ctx.db.commit()
    return {"id": str(seg.id), "verified": True}


class ThemeIn(BaseModel):
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=10, max_length=4000)
    code_ids: list[uuid.UUID] = Field(min_length=1)
    interpretation: str = Field(min_length=80, max_length=8000)


@router.post("/projects/{project_id}/qual/themes", status_code=201)
async def add_theme(project_id: uuid.UUID, body: ThemeIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    fp = await _qual_protocol(ctx, project_id)
    codes = {c.id for c in (await ctx.db.execute(select(QualCode).where(QualCode.id.in_(body.code_ids),
                                                                       QualCode.project_id == project_id))).scalars()}
    if codes != set(body.code_ids):
        raise unprocessable("unknown_code", "every theme code must exist in this project's codebook")
    t = QualTheme(tenant_id=ctx.tenant_id, project_id=project_id, protocol_id=fp.id, name=body.name, description=body.description,
                  code_ids=[str(i) for i in body.code_ids], interpretation=body.interpretation, created_by=ctx.principal.user_id)
    ctx.db.add(t)
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.INTERPRETATION, f"Defined theme '{body.name}'",
                         source_action="qual.theme", rationale=body.interpretation, rationale_requested=False)
    await ctx.db.commit()
    return {"id": str(t.id), "name": t.name}


@router.get("/projects/{project_id}/qual")
async def qual_workspace(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    codes = list((await ctx.db.execute(select(QualCode).where(QualCode.project_id == project_id))).scalars())
    segs = list((await ctx.db.execute(select(QualSegment).where(QualSegment.project_id == project_id))).scalars())
    themes = list((await ctx.db.execute(select(QualTheme).where(QualTheme.project_id == project_id))).scalars())
    return {"codes": [{"id": str(c.id), "code": c.code, "definition": c.definition,
                       "segments": sum(1 for s in segs if s.code_id == c.id)} for c in codes],
            "segments": [{"id": str(s.id), "code_id": str(s.code_id), "contribution_id": str(s.contribution_id),
                          "quote": s.quote, "verified": s.verified, "memo": s.memo} for s in segs],
            "themes": [{"id": str(t.id), "name": t.name, "description": t.description, "code_ids": t.code_ids,
                        "interpretation": t.interpretation} for t in themes]}


# --------------------------------------------------------------------------- DB-backed stage validators
async def v_review_spec_valid(db, project, fp, content, x):
    inst = await active_instance(db, project.id)
    probs = spec_problems(fp.sections.get("review_specification"), inst.study_type)
    return not probs, "; ".join(probs) or "the frozen protocol contains a valid review specification"


async def v_search_reproducible(db, project, fp, content, x):
    _, spec = await spec_of(db, project.id)
    runs = await _runs(db, fp)
    missing = []
    for s in spec.searches:
        r = next((r for r in runs if r.query == s.query and s.provider in (r.providers_requested or [])
                  and r.status == "succeeded" and r.record_artifact_id), None)
        if r is None:
            missing.append(f"{s.provider}: '{s.query}'")
    return not missing, (f"searches not executed exactly as specified: {missing}" if missing
                         else f"{len(spec.searches)} specified searches executed with recorded queries, dates and records")


async def v_screening_complete(db, project, fp, content, x):
    _, spec, flow = await flow_for(db, project.id)
    probs = flow_problems(flow)
    if flow["screened"] == 0:
        probs.append("no records to screen")
    if flow["included"] == 0:
        probs.append("no study was included")
    return not probs, "; ".join(probs) or (f"{flow['screened']} records screened, {flow['included']} included; "
                                            "every exclusion has a protocol reason")


async def v_extraction_complete(db, project, fp, content, x):
    _, spec, flow = await flow_for(db, project.id)
    ex = await current_extractions(db, fp)
    probs = []
    for pid in flow["included_ids"]:
        e = ex.get(pid)
        if e is None:
            probs.append(f"{pid[:8]}: no extraction record")
            continue
        for f in spec.extraction_form:
            v = e.values.get(f.key)
            if f.required and not (v and (v.get("passage_id") or v.get("not_reported"))):
                probs.append(f"{pid[:8]}: '{f.key}' needs a passage-linked value or 'not reported'")
        for item in spec.appraisal_items:
            if item.key not in e.appraisal:
                probs.append(f"{pid[:8]}: appraisal item '{item.key}' missing")
        if spec.synthesis == "meta_analysis" and not e.effect:
            probs.append(f"{pid[:8]}: effect estimate and variance missing")
        if spec.synthesis == "map":
            probs += [f"{pid[:8]}: charting '{d.key}' missing" for d in spec.charting_scheme if d.key not in e.charting]
        if spec.synthesis == "review_of_reviews" and not e.primary_studies:
            probs.append(f"{pid[:8]}: list the review's primary studies")
    return not probs, "; ".join(probs[:10]) or f"{len(flow['included_ids'])} included studies extracted and appraised"


async def _synthesis_current(db, project, fp, kind):
    _, spec, flow = await flow_for(db, project.id)
    ex = await current_extractions(db, fp)
    h = extraction_inputs_hash(ex, flow["included_ids"])
    rec = (await db.execute(select(SynthesisRecord).where(SynthesisRecord.protocol_id == fp.id, SynthesisRecord.kind == kind,
                                                          SynthesisRecord.is_current.is_(True)))).scalars().first()
    if rec is None:
        return None, "run the synthesis"
    if rec.inputs_hash != h:
        return None, "the synthesis is not current: extraction records changed since it was computed; re-run it"
    return rec, None


async def v_meta_analysis_recomputed(db, project, fp, content, x):
    rec, why = await _synthesis_current(db, project, fp, "meta_analysis")
    if rec is None:
        return False, why
    _, spec, flow = await flow_for(db, project.id)
    ex = await current_extractions(db, fp)
    rows = [EffectRow(study=p, estimate=ex[p].effect["estimate"], variance=ex[p].effect["variance"])
            for p in flow["included_ids"] if p in ex and ex[p].effect]
    again = pool(rows, spec.pooling_model or "random_dl")
    ok = rec.result.get("status") == "computed" and abs(again["estimate"] - rec.result["estimate"]) < 1e-12
    return ok, (f"pooled {spec.effect_measure} recomputed: {again['estimate']:.4f} (I²={again['i2']:.1f}%)" if ok
                else "pooling could not be recomputed or disagrees with the stored result")


async def v_map_computed(db, project, fp, content, x):
    rec, why = await _synthesis_current(db, project, fp, "map")
    if rec is None:
        return False, why
    return not rec.result["problems"], "; ".join(rec.result["problems"]) or "charting map computed from current records"


async def v_overlap_assessed(db, project, fp, content, x):
    rec, why = await _synthesis_current(db, project, fp, "overlap")
    if rec is None:
        return False, why
    ok = rec.result.get("status") == "computed"
    return ok and len(content.get("description") or "") >= 200, (
        f"overlap CCA={rec.result.get('cca', 0):.3f} ({rec.result.get('level')}); synthesis of reviews recorded"
        if ok else rec.result.get("detail", "overlap not computed"))


async def v_narrative_synthesis(db, project, fp, content, x):
    rec, why = await _synthesis_current(db, project, fp, "flow")
    if rec is None:
        return False, why
    return len((content.get("description") or "").strip()) >= 200, "narrative synthesis recorded against the current flow"


async def v_ethics_approval_recorded(db, project, fp, content, x):
    eth = EthicsRightsDeclaration.model_validate(fp.ethics_rights) if fp.ethics_rights else None
    b = ethics_blockers(eth)
    if eth and eth.involves_human_participants and not eth.consent_procedure:
        b.append("describe the consent procedure")
    return not b, "; ".join(b) or "ethics approval and consent are recorded (the platform does not grant approval)"


async def v_collection_documented(db, project, fp, content, x):
    contribs = list((await db.execute(select(Contribution).where(Contribution.id.in_([uuid.UUID(i) for i in x["contributions"]]))))
                    .scalars()) if x["contributions"] else []
    ok = bool(contribs) and all(c.pii_classification for c in contribs) and len(content.get("description") or "") >= 80
    return ok, "collected sources attached with personal-data classification and a collection account"


async def v_codebook_trace(db, project, fp, content, x):
    codes = list((await db.execute(select(QualCode).where(QualCode.protocol_id == fp.id))).scalars())
    segs = list((await db.execute(select(QualSegment).where(QualSegment.project_id == project.id))).scalars())
    probs = [f"code '{c.code}' has no coded segment" for c in codes if not any(s.code_id == c.id for s in segs)]
    probs += ["a segment is not verified against its source" for s in segs if not s.verified][:1]
    if not codes:
        probs.append("the codebook is empty")
    return not probs, "; ".join(probs) or f"{len(codes)} codes, {len(segs)} verbatim-verified segments (source-to-code trace)"


async def v_themes_traced(db, project, fp, content, x):
    themes = list((await db.execute(select(QualTheme).where(QualTheme.protocol_id == fp.id))).scalars())
    seg_codes = {str(s.code_id) for s in (await db.execute(select(QualSegment).where(QualSegment.project_id == project.id))).scalars()}
    probs = [f"theme '{t.name}' has no code with coded segments" for t in themes if not set(t.code_ids) & seg_codes]
    if not themes:
        probs.append("no themes recorded")
    return not probs, "; ".join(probs) or f"{len(themes)} themes trace to coded, verified source segments"


method_mod.ASYNC_VALIDATORS.update({
    "v.review_spec_valid": v_review_spec_valid, "v.search_reproducible": v_search_reproducible,
    "v.screening_complete": v_screening_complete, "v.extraction_complete": v_extraction_complete,
    "v.meta_analysis_recomputed": v_meta_analysis_recomputed, "v.map_computed": v_map_computed,
    "v.overlap_assessed": v_overlap_assessed, "v.narrative_synthesis": v_narrative_synthesis,
    "v.ethics_approval_recorded": v_ethics_approval_recorded, "v.collection_documented": v_collection_documented,
    "v.codebook_trace": v_codebook_trace, "v.themes_traced": v_themes_traced,
})
method_mod.PROTOCOL_CHECKS.append(lambda p, d: spec_problems(p.sections.get("review_specification"), d.study_type)
                                  if "review_specification" in d.protocol_sections else [])

_ = (conflict, Any)
