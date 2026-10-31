"""M6 - evidence-grounded manuscript generation, versioning, human edits, concurrency-safe merge, bibliography."""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import Gate, LedgerCategory, ProjectState
from rp_contracts.hashing import content_hash, sha256_hex
from rp_contracts.latexdoc import Author
from rp_contracts.manuscript import (
    GAP_SECTIONS,
    ManuscriptContent,
    ManuscriptSection,
    Paragraph,
    check_span,
    check_tables,
    diff_sections,
    plan_for,
    render_document,
    section_text,
    word_count,
)

from ..db.models.cfp import CfpRule
from ..db.models.contribution import (
    ContributionValidationRow,
    GapResolutionAssessment,
    ResultAssessmentRecord,
    ResultManifestRecord,
)
from ..db.models.core import Artifact, Project, ProjectMember, User
from ..db.models.literature import Claim, ClaimSupport, EvidencePassage, TenantPaperRecord
from ..db.models.manuscript import (
    BibliographyEntry,
    GenerationCandidate,
    Manuscript,
    ManuscriptSpan,
    ManuscriptVersion,
)
from ..deps import EDIT_ROLES, READ_ROLES, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import approvals as approval_svc
from ..services import artifacts as art_svc
from ..services import claims as claim_svc
from ..services import ledger
from ..services.gates import GateResult, gate
from ..services.invalidation import on_stale
from ..services.tasks import create_task
from .method import active_instance, frozen_protocol

router = APIRouter(tags=["manuscript"])
# After H3 the manuscript is a paper; before H3 (research active / outcome review) only a private research proposal may be
# drafted, and observed-result spans are blocked by the span checks.
DRAFTABLE = {ProjectState.RESEARCH_ACTIVE, ProjectState.OUTCOME_REVIEW, ProjectState.DRAFTING,
             ProjectState.SCIENTIFIC_REVIEW, ProjectState.COMPLIANCE_REVIEW}


# --------------------------------------------------------------------------- bibliography
def _bib_escape(s: str | None) -> str:
    return re.sub(r"[{}\\]", "", s or "")


def cite_key_for(p: TenantPaperRecord, taken: set[str]) -> str:
    first = (p.authors[0].split()[-1] if p.authors else "anon")
    word = next((w for w in re.findall(r"[A-Za-z]{4,}", p.title or "")), "work")
    base = re.sub(r"[^a-z0-9]", "", f"{first}{p.year or 'nd'}{word}".lower())[:40] or "ref"
    key, i = base, 2
    while key in taken:
        key, i = f"{base}{chr(96 + i)}", i + 1
    return key


def bibtex_for(p: TenantPaperRecord, key: str) -> str:
    fields = {"title": p.title, "author": " and ".join(p.authors[:30]), "year": str(p.year or ""),
              "journal" if p.venue else "note": p.venue or "", "doi": p.doi or ""}
    body = ",\n".join(f"  {k} = {{{_bib_escape(v)}}}" for k, v in fields.items() if v)
    return f"@article{{{key},\n{body}\n}}\n"


async def ensure_bibliography(db: AsyncSession, project: Project) -> dict[str, list[str]]:
    """Bibliography entries exist only for identity-verified papers that support a cited claim.
    Returns claim_key -> cite keys. Unverified papers can never be cited (the writer cannot mint entries)."""
    claims = {c.id: c for c in (await db.execute(select(Claim).where(Claim.project_id == project.id))).scalars()}
    sups = list((await db.execute(select(ClaimSupport).where(ClaimSupport.claim_id.in_(list(claims)),
                                                             ClaimSupport.is_current.is_(True),
                                                             ClaimSupport.relation.in_(["supports", "qualifies"]))))
                .scalars()) if claims else []
    pas = {p.id: p for p in (await db.execute(select(EvidencePassage).where(
        EvidencePassage.id.in_([s.passage_id for s in sups if s.passage_id])))).scalars()} if sups else {}
    paper_ids = {s.paper_id for s in sups if s.paper_id} | {pas[s.passage_id].paper_id for s in sups if s.passage_id in pas}
    papers = {p.id: p for p in (await db.execute(select(TenantPaperRecord).where(TenantPaperRecord.id.in_(paper_ids)))).scalars()} if paper_ids else {}
    entries = {e.paper_id: e for e in (await db.execute(select(BibliographyEntry).where(
        BibliographyEntry.project_id == project.id))).scalars()}
    taken = {e.cite_key for e in entries.values()}
    for pid, p in papers.items():
        ih = content_hash([p.doi, p.title, p.authors, p.year, p.identity_status])
        e = entries.get(pid)
        if p.identity_status != "verified":
            if e:
                e.is_current = False
            continue
        if e is None:
            key = cite_key_for(p, taken)
            taken.add(key)
            e = BibliographyEntry(tenant_id=project.tenant_id, project_id=project.id, paper_id=pid, cite_key=key,
                                  bibtex=bibtex_for(p, key), identity_status=p.identity_status, identity_hash=ih)
            db.add(e)
            entries[pid] = e
        elif e.identity_hash != ih:
            e.bibtex, e.identity_hash, e.is_current = bibtex_for(p, e.cite_key), ih, True
    await db.flush()
    out: dict[str, list[str]] = {}
    for s in sups:
        c = claims[s.claim_id]
        pid = s.paper_id or (pas[s.passage_id].paper_id if s.passage_id in pas else None)
        e = entries.get(pid)
        if e is not None and e.is_current and c.kind == "literature":
            out.setdefault(c.claim_key, []).append(e.cite_key)
    return {k: sorted(set(v)) for k, v in out.items()}


# --------------------------------------------------------------------------- check context and brief
async def check_context(db: AsyncSession, project: Project) -> dict[str, Any]:
    claims = list((await db.execute(select(Claim).where(Claim.project_id == project.id, Claim.superseded_by.is_(None)))).scalars())
    cmap = {}
    for c in claims:
        cmap[c.claim_key] = {"status": c.status, "gate_eligible": await claim_svc.gate_eligible(db, c), "category": c.category,
                             "critical": c.critical, "proposition": c.proposition, "kind": c.kind}
    inst = await active_instance(db, project.id)
    results = {}
    rows_ok, gap_status = False, None
    if inst:
        for r in (await db.execute(select(ResultManifestRecord).where(ResultManifestRecord.method_instance_id == inst.id,
                                                                      ResultManifestRecord.is_current.is_(True)))).scalars():
            a = (await db.execute(select(ResultAssessmentRecord).where(ResultAssessmentRecord.result_manifest_id == r.id,
                                                                       ResultAssessmentRecord.is_current.is_(True)))).scalars().first()
            results[r.result_key] = {"title": r.title, "metrics": r.manifest.get("metrics", []), "assurance": r.assurance_level,
                                     "wording_limits": a.wording_limits if a else [], "artifact_id": str(r.artifact_id)}
        rows = list((await db.execute(select(ContributionValidationRow).where(
            ContributionValidationRow.method_instance_id == inst.id, ContributionValidationRow.is_current.is_(True)))).scalars())
        rows_ok = any(r.outcome in ("supported", "partially_supported") and r.origin == "researcher_reviewed" for r in rows)
        gap = (await db.execute(select(GapResolutionAssessment).where(GapResolutionAssessment.method_instance_id == inst.id,
                                                                      GapResolutionAssessment.is_current.is_(True)))).scalars().first()
        gap_status = gap.status if gap else None
    h3, problems = await approval_svc.current_approval(db, project.id, Gate.H3)
    h3_ok = h3 is not None and not problems
    return {"claims": cmap, "results": results, "h3_rows_supported": rows_ok and h3_ok, "gap_status": gap_status,
            "mode": "paper" if h3_ok else "proposal", "study_type": inst.study_type if inst else None}


async def _rule(db, project, key):
    if not project.target_edition_id:
        return None
    return (await db.execute(select(CfpRule).where(CfpRule.edition_id == project.target_edition_id, CfpRule.rule_key == key,
                                                   CfpRule.is_current.is_(True), CfpRule.status.in_(["confirmed", "validated", "extracted"]),
                                                   (CfpRule.track_id.is_(None)) | (CfpRule.track_id == project.target_track_id)))).scalars().first()


async def build_brief(db: AsyncSession, actor, project: Project) -> tuple[dict, Artifact]:
    ctx = await check_context(db, project)
    cites = await ensure_bibliography(db, project)
    direction_art = (await db.execute(select(Artifact).where(Artifact.project_id == project.id, Artifact.kind == "research_direction",
                                                             Artifact.freshness == "current"))).scalars().first()
    matrix_art = (await db.execute(select(Artifact).where(Artifact.project_id == project.id, Artifact.kind == "contribution_matrix",
                                                          Artifact.freshness == "current").order_by(Artifact.created_at.desc()))).scalars().first()
    inst = await active_instance(db, project.id)
    frozen = await frozen_protocol(db, inst.id) if inst else None
    direction = await art_svc.read_artifact_json(direction_art) if direction_art else {}
    matrix = await art_svc.read_artifact_json(matrix_art) if matrix_art and ctx["mode"] == "paper" else None
    abstract_rule = await _rule(db, project, "abstract.word_limit")
    page_rule = await _rule(db, project, "length.page_limit")
    eligible = [{"key": k, "proposition": v["proposition"], "kind": v["kind"], "category": v["category"],
                 "citations": cites.get(k, [])} for k, v in sorted(ctx["claims"].items()) if v["gate_eligible"]]
    brief = {
        "title": project.title, "topic": project.topic, "mode": ctx["mode"], "study_type": ctx["study_type"],
        "section_plan": [{"key": k, "heading": h} for k, h in plan_for(ctx["study_type"])],
        "research_question": direction.get("research_question"), "intended_contribution": direction.get("intended_contribution"),
        "how_it_differs": direction.get("how_it_differs"), "novelty_caveat": direction.get("novelty_caveat"),
        "protocol": {"version": frozen.version_number, "hash": frozen.content_hash, "sections": frozen.sections} if frozen else None,
        "matrix": matrix, "claims": eligible,
        "results": [{"key": k, **{x: v[x] for x in ("title", "metrics", "assurance", "wording_limits")}} for k, v in sorted(ctx["results"].items())]
        if ctx["mode"] == "paper" else [],
        "rules": {"abstract_word_limit": int(abstract_rule.value) if abstract_rule and (abstract_rule.value or "").isdigit() else None,
                  "page_limit": int(page_rule.value) if page_rule and (page_rule.value or "").isdigit() else None},
        "writing_rules": ["Cite only the claim keys provided; never invent citations or numbers.",
                          "Prior work and observed results must cite claim keys or result keys.",
                          "Respect each result's wording limits and assurance level.",
                          "Do not claim the gap was filled unless the gap resolution is 'addressed'.",
                          "Label interpretation, hypotheses and limitations as such."],
    }
    deps = [a.id for a in (direction_art, matrix_art) if a] + ([frozen.artifact_id] if frozen else []) + \
           [uuid.UUID(v["artifact_id"]) for v in ctx["results"].values()]
    pub = (await art_svc.publish_json(db, actor, project.tenant_id, project.id, "manuscript_brief", brief, depends_on=deps,
                                      label=f"Manuscript brief ({ctx['mode']})")).artifact
    return brief, pub


# --------------------------------------------------------------------------- versions
def _span_id(section: str, text: str, n: int) -> str:
    return "S-" + sha256_hex(f"{section}|{n}|{text}".encode())[:10]


def skeleton(project: Project, study_type: str | None) -> ManuscriptContent:
    return ManuscriptContent(title=project.title, sections=[ManuscriptSection(key=k, heading=h) for k, h in plan_for(study_type)])


async def current_content(db: AsyncSession, m: Manuscript) -> tuple[ManuscriptVersion | None, ManuscriptContent | None]:
    if m.current_version_id is None:
        return None, None
    v = (await db.execute(select(ManuscriptVersion).where(ManuscriptVersion.id == m.current_version_id))).scalar_one()
    data = await art_svc.read_artifact_json(await art_svc.get_artifact(db, v.artifact_id))
    return v, ManuscriptContent.model_validate(data["content"])


async def commit_version(db: AsyncSession, actor, project: Project, m: Manuscript, content: ManuscriptContent, *, origin: str,
                         brief_artifact_id: uuid.UUID | None = None, candidate_id: uuid.UUID | None = None,
                         summary: str | None = None) -> ManuscriptVersion:
    for s in content.sections:
        for i, p in enumerate(s.paragraphs):
            for j, sp in enumerate(p.spans):
                if not sp.span_id:
                    sp.span_id = _span_id(s.key, sp.text, i * 100 + j)
    ctx = await check_context(db, project)
    ctx["mode"] = content.mode if content.mode == "proposal" else ctx["mode"]
    issues_by_span = {sp.span_id: check_span(sp, ctx) for _, sp in content.spans()}
    # Tables have no span row to hang issues on, so they are recorded on the version's checks summary.
    table_issues = check_tables(content, ctx)
    abstract_words = word_count(section_text(content.section("abstract")))
    summary_checks = {"spans": sum(1 for _ in content.spans()),
                      "spans_with_issues": sum(1 for v in issues_by_span.values() if v),
                      "unresolved_claims": sum(1 for v in issues_by_span.values() if any(i["code"] == "unsupported_factual_span" for i in v)),
                      "blockers": sum(1 for v in issues_by_span.values() for i in v if i["severity"] == "blocker")
                      + sum(1 for i in table_issues if i["severity"] == "blocker"),
                      "table_issues": table_issues,
                      "abstract_words": abstract_words}
    prev_id = m.current_version_id
    deps = [brief_artifact_id] if brief_artifact_id else []
    if prev_id:
        prev = (await db.execute(select(ManuscriptVersion).where(ManuscriptVersion.id == prev_id))).scalar_one()
        deps.append(prev.artifact_id)
        from .submission import on_manuscript_version

        await on_manuscript_version(db, actor, project, prev.artifact_id,
                                    f"manuscript changed (v{prev.version_number} -> v{prev.version_number + 1}, {origin})")
    number = m.current_version_number + 1
    pub = (await art_svc.publish_json(db, actor, project.tenant_id, project.id, "manuscript_version",
                                      {"manuscript_id": str(m.id), "version": number, "content": content.model_dump(mode="json")},
                                      depends_on=deps or None, dependency_kind="manuscript_lineage",
                                      label=f"Manuscript v{number} ({origin})")).artifact
    v = ManuscriptVersion(tenant_id=project.tenant_id, manuscript_id=m.id, version_number=number, parent_version_id=prev_id,
                          artifact_id=pub.id, content_hash=pub.content_hash, origin=origin, candidate_id=candidate_id,
                          brief_artifact_id=brief_artifact_id, change_summary=summary, created_by=actor.actor_id,
                          checks_summary=summary_checks)
    db.add(v)
    await db.flush()
    pos = 0
    for s, sp in content.spans():
        iss = issues_by_span.get(sp.span_id, [])
        db.add(ManuscriptSpan(tenant_id=project.tenant_id, version_id=v.id, section_key=s.key, span_id=sp.span_id, position=pos,
                              kind=sp.kind, text=sp.text, claim_ids=sp.claim_ids, result_keys=sp.result_keys,
                              origin=sp.origin, protected=sp.protected, status="issues" if iss else "ok", issues=iss))
        pos += 1
    m.current_version_id = v.id
    m.current_version_number = number
    m.version += 1
    await db.flush()
    return v


async def get_or_create_manuscript(db: AsyncSession, actor, project: Project) -> Manuscript:
    m = (await db.execute(select(Manuscript).where(Manuscript.project_id == project.id))).scalar_one_or_none()
    if m is None:
        inst = await active_instance(db, project.id)
        m = Manuscript(tenant_id=project.tenant_id, project_id=project.id, title=project.title,
                       study_type=inst.study_type if inst else None)
        db.add(m)
        await db.flush()
        await commit_version(db, actor, project, m, skeleton(project, m.study_type), origin="initial",
                             summary="empty section skeleton")
    return m


def version_out(v: ManuscriptVersion, spans: list[ManuscriptSpan] | None = None, content: ManuscriptContent | None = None) -> dict:
    return {"id": str(v.id), "version": v.version_number, "origin": v.origin, "content_hash": v.content_hash,
            "artifact_id": str(v.artifact_id), "change_summary": v.change_summary, "created_by": v.created_by,
            "created_at": v.created_at, "checks": v.checks_summary,
            "content": content.model_dump(mode="json") if content else None,
            "spans": [{"span_id": s.span_id, "section": s.section_key, "kind": s.kind, "text": s.text, "claim_ids": s.claim_ids,
                       "result_keys": s.result_keys, "origin": s.origin, "protected": s.protected, "status": s.status,
                       "issues": s.issues} for s in (spans or [])]}


def candidate_out(c: GenerationCandidate) -> dict:
    return {"id": str(c.id), "status": c.status, "base_version_id": str(c.base_version_id), "sections": c.sections,
            "rationale": c.rationale, "conflicts": c.conflicts, "provenance": c.provenance, "created_at": c.created_at,
            "artifact_id": str(c.artifact_id) if c.artifact_id else None, "task_id": str(c.task_id)}


# --------------------------------------------------------------------------- endpoints
class DraftIn(BaseModel):
    sections: list[str] | None = None
    instructions: str | None = Field(default=None, max_length=4000)


async def start_generation(db: AsyncSession, actor, project: Project, sections: list[str] | None, instructions: str | None,
                           idempotency_key: str | None = None) -> dict:
    """Freeze the brief and base version, then queue a generation task whose output can only become a candidate."""
    if ProjectState(project.state) not in DRAFTABLE:
        raise conflict("wrong_state", f"drafting starts once research is active (project is {project.state})")
    m = await get_or_create_manuscript(db, actor, project)
    base, _ = await current_content(db, m)
    brief, brief_art = await build_brief(db, actor, project)
    plan_keys = [s["key"] for s in brief["section_plan"]]
    chosen = [s for s in (sections or plan_keys) if s in plan_keys]
    if not chosen:
        raise unprocessable("unknown_sections", f"sections must be among {plan_keys}")
    manifest = {"manuscript_version": str(base.id), "manuscript_hash": base.content_hash, "brief": brief_art.content_hash,
                "sections": chosen, "instructions": instructions}
    task, created = await create_task(db, actor, project, "manuscript_generation",
                                      {"manuscript_id": str(m.id), "brief_artifact_id": str(brief_art.id), "sections": chosen,
                                       "instructions": instructions},
                                      idempotency_key=idempotency_key, input_manifest=manifest)
    if created:
        db.add(GenerationCandidate(tenant_id=project.tenant_id, manuscript_id=m.id, task_id=task.id, base_version_id=base.id,
                                   base_content_hash=base.content_hash, input_manifest_hash=content_hash(manifest),
                                   brief_artifact_id=brief_art.id, sections=chosen))
    return {"task": task, "manuscript": m, "mode": brief["mode"], "base_version": base.version_number}


@router.post("/projects/{project_id}/drafts", status_code=202)
async def request_draft(project_id: uuid.UUID, body: DraftIn, ctx: Ctx = Depends(user_ctx),
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    g = await start_generation(ctx.db, ctx.principal, project, body.sections, body.instructions,
                               f"draft:{project_id}:{idempotency_key}" if idempotency_key else None)
    await ctx.db.commit()
    return {"task": task_out(g["task"]), "manuscript_id": str(g["manuscript"].id), "mode": g["mode"],
            "base_version": g["base_version"]}


@router.get("/projects/{project_id}/manuscript")
async def get_manuscript(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id)
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.project_id == project_id))).scalar_one_or_none()
    if m is None:
        return {"manuscript": None}
    v, content = await current_content(ctx.db, m)
    spans = list((await ctx.db.execute(select(ManuscriptSpan).where(ManuscriptSpan.version_id == v.id)
                                       .order_by(ManuscriptSpan.position))).scalars())
    cands = list((await ctx.db.execute(select(GenerationCandidate).where(GenerationCandidate.manuscript_id == m.id)
                                       .order_by(GenerationCandidate.created_at.desc()))).scalars())
    for c in cands:
        if c.status == "ready" and c.base_version_id != m.current_version_id:
            c.status = "stale"
    await ctx.db.commit()
    queue = [{"span_id": s.span_id, "section": s.section_key, "text": s.text} for s in spans
             if any(i["code"] == "unsupported_factual_span" for i in s.issues)]
    gap = {k: bool(section_text(content.section(k)).strip()) for k in GAP_SECTIONS if content.section(k) is not None}
    bib = list((await ctx.db.execute(select(BibliographyEntry).where(BibliographyEntry.project_id == project_id,
                                                                     BibliographyEntry.is_current.is_(True)))).scalars())
    return {"manuscript": {"id": str(m.id), "title": m.title, "study_type": m.study_type,
                           "current_version": version_out(v, spans, content)},
            "unresolved_claim_queue": queue, "gap_argument_sections_present": gap,
            "bibliography": [{"cite_key": b.cite_key, "paper_id": str(b.paper_id), "bibtex": b.bibtex} for b in bib],
            "candidates": [candidate_out(c) for c in cands]}


@router.get("/manuscripts/{manuscript_id}/versions")
async def versions(manuscript_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    m = await _manuscript(ctx, manuscript_id)
    rows = (await ctx.db.execute(select(ManuscriptVersion).where(ManuscriptVersion.manuscript_id == m.id)
                                 .order_by(ManuscriptVersion.version_number.desc()))).scalars()
    return {"items": [version_out(v) for v in rows]}


@router.get("/manuscripts/{manuscript_id}/versions/{number}")
async def version_detail(manuscript_id: uuid.UUID, number: int, ctx: Ctx = Depends(user_ctx)):
    m = await _manuscript(ctx, manuscript_id)
    v = (await ctx.db.execute(select(ManuscriptVersion).where(ManuscriptVersion.manuscript_id == m.id,
                                                              ManuscriptVersion.version_number == number))).scalar_one_or_none()
    if v is None:
        raise not_found("version")
    data = await art_svc.read_artifact_json(await art_svc.get_artifact(ctx.db, v.artifact_id))
    spans = list((await ctx.db.execute(select(ManuscriptSpan).where(ManuscriptSpan.version_id == v.id)
                                       .order_by(ManuscriptSpan.position))).scalars())
    return version_out(v, spans, ManuscriptContent.model_validate(data["content"]))


async def _manuscript(ctx: Ctx, manuscript_id: uuid.UUID, roles=None) -> Manuscript:
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.id == manuscript_id))).scalar_one_or_none()
    if m is None:
        raise not_found("manuscript")
    await project_for(ctx, m.project_id, roles or READ_ROLES)
    return m


class EditIn(BaseModel):
    expected_version: int
    sections: list[ManuscriptSection]
    summary: str | None = Field(default=None, max_length=2000)


@router.patch("/manuscripts/{manuscript_id}")
async def edit_manuscript(manuscript_id: uuid.UUID, body: EditIn, ctx: Ctx = Depends(user_ctx)):
    """Human edit. Changed spans become human-authored and protected from regeneration."""
    m = await _manuscript(ctx, manuscript_id, EDIT_ROLES)
    project, _ = await project_for(ctx, m.project_id, EDIT_ROLES)
    if body.expected_version != m.current_version_number:
        raise conflict("stale_version", "the manuscript changed; reload before saving",
                       {"current_version": m.current_version_number})
    _, content = await current_content(ctx.db, m)
    before = content.model_copy(deep=True)
    old = {sp.span_id: sp for _, sp in content.spans()}
    plan_keys = {k for k, _ in plan_for(m.study_type)} | {s.key for s in content.sections}
    changed, n, relinked = [], 0, []
    for s in body.sections:
        if s.key not in plan_keys:
            raise unprocessable("unknown_section", f"section {s.key} is not part of this manuscript")
        existing = content.section(s.key)
        for p in s.paragraphs:
            for sp in p.spans:
                prev = old.get(sp.span_id)
                if prev is not None and prev.text == sp.text:
                    # Unchanged text keeps its recorded provenance; clients cannot relabel AI text as human or
                    # unprotect it. Re-kinding a sentence or re-pointing its claim/result links is still a human
                    # act on the evidence trail: the prose keeps its author, but the curation is protected from
                    # regeneration and recorded for review.
                    sp.origin = prev.origin
                    changes = [f"{f} {getattr(prev, f)} -> {getattr(sp, f)}"
                               for f in ("kind", "claim_ids", "result_keys") if getattr(prev, f) != getattr(sp, f)]
                    sp.protected = prev.protected or bool(changes)
                    if changes:
                        relinked.append(f"{s.key}/{sp.span_id}: " + "; ".join(changes))
                else:
                    n += 1
                    sp.origin, sp.protected = "human", True
                    sp.span_id = _span_id(s.key, sp.text, 10_000 + n) if prev is not None or not sp.span_id else sp.span_id
        if existing is None:
            content.sections.append(s)
        else:
            content.sections[content.sections.index(existing)] = s
        changed.append(s.key)
    diffs = diff_sections(before, content)
    note = f" ({len(relinked)} sentence(s) relinked)" if relinked else ""
    v = await commit_version(ctx.db, ctx.principal, project, m, content, origin="human_edit",
                             summary=body.summary or f"edited {', '.join(changed)}{note}")
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.MANUSCRIPT_CHANGE,
                         f"Edited manuscript sections: {', '.join(changed)}{note}", source_action="manuscript.edit",
                         diff="\n".join([*(d["diff"] for d in diffs), *(["Relinked:", *relinked] if relinked else [])])[:20000] or None,
                         artifact_id=v.artifact_id, rationale=body.summary)
    await ctx.db.commit()
    return version_out(v)


async def _candidate_content(ctx: Ctx, c: GenerationCandidate) -> ManuscriptContent:
    if c.artifact_id is None:
        raise conflict("candidate_not_ready", f"candidate is {c.status}")
    data = await art_svc.read_artifact_json(await art_svc.get_artifact(ctx.db, c.artifact_id))
    return ManuscriptContent.model_validate(data["content"])


async def _get_candidate(ctx, m, cid) -> GenerationCandidate:
    c = (await ctx.db.execute(select(GenerationCandidate).where(GenerationCandidate.id == cid,
                                                                GenerationCandidate.manuscript_id == m.id))).scalar_one_or_none()
    if c is None:
        raise not_found("candidate")
    return c


def merge_into(current: ManuscriptContent, cand: ManuscriptContent, take: set[str]) -> tuple[ManuscriptContent, list[dict]]:
    """Take candidate sections in `take`, preserving every protected human span of the current version."""
    out = ManuscriptContent.model_validate(current.model_dump())
    conflicts = []
    for key in take:
        new = cand.section(key)
        cur = out.section(key)
        if new is None:
            continue
        protected = [sp for p in (cur.paragraphs if cur else []) for sp in p.spans if sp.protected]
        merged = ManuscriptSection.model_validate(new.model_dump())
        if protected:
            ids = {sp.span_id for p in merged.paragraphs for sp in p.spans}
            missing = [sp for sp in protected if sp.span_id not in ids]
            if missing:
                merged.paragraphs.append(Paragraph(spans=missing))
                conflicts.append({"section": key, "kept_protected_spans": [sp.span_id for sp in missing],
                                  "note": "human-authored text was preserved alongside the regenerated section"})
        if cur is None:
            out.sections.append(merged)
        else:
            out.sections[out.sections.index(cur)] = merged
    return out, conflicts


@router.get("/manuscripts/{manuscript_id}/candidates/{candidate_id}")
async def get_candidate(manuscript_id: uuid.UUID, candidate_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    m = await _manuscript(ctx, manuscript_id)
    c = await _get_candidate(ctx, m, candidate_id)
    _, cur = await current_content(ctx.db, m)
    cand = await _candidate_content(ctx, c)
    return {**candidate_out(c), "content": cand.model_dump(mode="json"), "diff_vs_current": diff_sections(cur, cand),
            "is_stale": c.base_version_id != m.current_version_id}


@router.post("/manuscripts/{manuscript_id}/candidates/{candidate_id}/apply")
async def apply_candidate(manuscript_id: uuid.UUID, candidate_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Apply a generated candidate. Rejected with 409 when the manuscript changed since generation started, or when
    it would touch human-authored spans: those require an explicit merge."""
    m = await _manuscript(ctx, manuscript_id, EDIT_ROLES)
    project, _ = await project_for(ctx, m.project_id, EDIT_ROLES)
    c = await _get_candidate(ctx, m, candidate_id)
    if c.status not in ("ready", "stale"):
        raise conflict("candidate_not_applicable", f"candidate is {c.status}")
    v, cur = await current_content(ctx.db, m)
    cand = await _candidate_content(ctx, c)
    if c.base_version_id != m.current_version_id:
        c.status = "stale"
        await ctx.db.commit()
        raise ApiError(409, "stale_candidate", "the manuscript changed while this draft was generated; review the diff and merge",
                       {"base_version_id": str(c.base_version_id), "current_version": m.current_version_number,
                        "diff_vs_current": diff_sections(cur, cand)})
    touched_protected = [s for s in c.sections for p in (cur.section(s).paragraphs if cur.section(s) else []) for sp in p.spans if sp.protected]
    if touched_protected:
        raise ApiError(409, "merge_required", "the candidate regenerates sections containing human-authored text",
                       {"sections": sorted(set(touched_protected)), "diff_vs_current": diff_sections(cur, cand)})
    merged, _ = merge_into(cur, cand, set(c.sections))
    nv = await commit_version(ctx.db, ctx.principal, project, m, merged, origin="candidate_applied",
                              brief_artifact_id=c.brief_artifact_id, candidate_id=c.id,
                              summary=f"applied generated draft of {', '.join(c.sections)}")
    c.status = "applied"
    await ctx.db.commit()
    return version_out(nv)


class MergeIn(BaseModel):
    expected_version: int
    take_candidate_sections: list[str]


@router.post("/manuscripts/{manuscript_id}/candidates/{candidate_id}/merge")
async def merge_candidate(manuscript_id: uuid.UUID, candidate_id: uuid.UUID, body: MergeIn, ctx: Ctx = Depends(user_ctx)):
    """Researcher-approved merge against the *current* version; protected human spans are always kept."""
    m = await _manuscript(ctx, manuscript_id, EDIT_ROLES)
    project, _ = await project_for(ctx, m.project_id, EDIT_ROLES)
    if body.expected_version != m.current_version_number:
        raise conflict("stale_version", "the manuscript changed again; reload the diff")
    c = await _get_candidate(ctx, m, candidate_id)
    if c.status not in ("ready", "stale"):
        raise conflict("candidate_not_applicable", f"candidate is {c.status}")
    _, cur = await current_content(ctx.db, m)
    cand = await _candidate_content(ctx, c)
    take = set(body.take_candidate_sections) & set(c.sections)
    merged, conflicts = merge_into(cur, cand, take)
    nv = await commit_version(ctx.db, ctx.principal, project, m, merged, origin="merge", brief_artifact_id=c.brief_artifact_id,
                              candidate_id=c.id, summary=f"merged sections {sorted(take)} from a generated draft")
    c.status, c.conflicts = "merged", conflicts
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.MANUSCRIPT_CHANGE,
                         f"Merged generated sections {sorted(take)} (kept human text)", source_action="manuscript.merge",
                         artifact_id=nv.artifact_id, rationale_requested=False)
    await ctx.db.commit()
    return {**version_out(nv), "conflicts": conflicts}


@router.post("/manuscripts/{manuscript_id}/candidates/{candidate_id}/reject")
async def reject_candidate(manuscript_id: uuid.UUID, candidate_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    m = await _manuscript(ctx, manuscript_id, EDIT_ROLES)
    c = await _get_candidate(ctx, m, candidate_id)
    c.status = "rejected"
    await ctx.db.commit()
    return candidate_out(c)


class CompileIn(BaseModel):
    anonymous: bool = True
    bib_mode: str = Field(default="bibtex", pattern="^(bibtex|biber)$")


@router.post("/projects/{project_id}/compile", status_code=202)
async def compile_manuscript(project_id: uuid.UUID, body: CompileIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    from .templates import confirmed_template

    tpl = await confirmed_template(ctx.db, project_id)
    if tpl is None:
        raise unprocessable("no_confirmed_template", "confirm the official submission template first")
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.project_id == project_id))).scalar_one_or_none()
    if m is None or m.current_version_id is None:
        raise unprocessable("no_manuscript", "draft the manuscript first")
    task, _ = await create_task(ctx.db, ctx.principal, project, "manuscript_compile",
                                {"manuscript_version_id": str(m.current_version_id), "template_id": str(tpl.id),
                                 "anonymous": body.anonymous, "bib_mode": body.bib_mode},
                                input_manifest={"version": str(m.current_version_id), "template": tpl.archive_hash,
                                                "anon": body.anonymous, "bib": body.bib_mode})
    await ctx.db.commit()
    return {"task": task_out(task)}


# --------------------------------------------------------------------------- gate
@gate("manuscript.complete")
async def manuscript_complete(db: AsyncSession, project: Project) -> GateResult:
    m = (await db.execute(select(Manuscript).where(Manuscript.project_id == project.id))).scalar_one_or_none()
    if m is None or m.current_version_id is None:
        return GateResult("manuscript.complete", False, ["no manuscript"], next_action="Draft the manuscript")
    v = (await db.execute(select(ManuscriptVersion).where(ManuscriptVersion.id == m.current_version_id))).scalar_one()
    art = (await db.execute(select(Artifact).where(Artifact.id == v.artifact_id))).scalar_one()
    data = await art_svc.read_artifact_json(art)
    content = ManuscriptContent.model_validate(data["content"])
    reasons = []
    if content.mode == "proposal":
        reasons.append("the current version is a research proposal drafted before H3; regenerate it as a paper")
    if art.freshness != "current":
        reasons.append(f"the manuscript version is stale ({art.stale_reason})")
    for k, h in plan_for(m.study_type):
        if k == "limitations":
            continue
        if not section_text(content.section(k)).strip():
            reasons.append(f"section '{h}' is empty")
    spans = list((await db.execute(select(ManuscriptSpan).where(ManuscriptSpan.version_id == v.id))).scalars())
    blockers = [s for s in spans if any(i["severity"] == "blocker" for i in s.issues)]
    if blockers:
        reasons.append(f"{len(blockers)} span(s) have blocking issues (unknown/unverified critical claims, overstated contribution)")
    tbl = [i for i in (v.checks_summary.get("table_issues") or []) if i["severity"] == "blocker"]
    if tbl:
        reasons.append(f"{len(tbl)} table(s) cite results that are not committed: "
                       + ", ".join(sorted({f"{i['section']}/{i['caption']}" for i in tbl})))
    limit = (await _rule(db, project, "abstract.word_limit"))
    if limit is not None and (limit.value or "").isdigit() and word_count(section_text(content.section("abstract"))) > int(limit.value):
        reasons.append(f"abstract exceeds {limit.value} words")
    return GateResult("manuscript.complete", not reasons, reasons,
                      evidence={"version": v.version_number, "unresolved_claims": v.checks_summary.get("unresolved_claims")})


@on_stale
async def _stale_spans(db: AsyncSession, actor, project: Project, affected: set[uuid.UUID], reason: str) -> list[str]:
    """A changed result or source invalidates the manuscript spans that cite it."""
    keys = set((await db.execute(select(ResultManifestRecord.result_key).where(
        ResultManifestRecord.project_id == project.id, ResultManifestRecord.artifact_id.in_(affected)))).scalars().all())
    if not keys:
        return []
    m = (await db.execute(select(Manuscript).where(Manuscript.project_id == project.id))).scalar_one_or_none()
    if m is None or m.current_version_id is None:
        return []
    n = 0
    for s in (await db.execute(select(ManuscriptSpan).where(ManuscriptSpan.version_id == m.current_version_id))).scalars():
        if set(s.result_keys) & keys:
            s.status = "stale"
            s.issues = [*s.issues, {"code": "stale_result", "severity": "blocker", "message": reason}]
            n += 1
    return [f"{n} manuscript spans citing changed results marked stale"] if n else []


# --------------------------------------------------------------------------- internal
class CandidateIn(BaseModel):
    artifact_id: uuid.UUID | None = None
    content: dict[str, Any] | None = None
    rationale: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="ready", pattern="^(ready|failed)$")
    error: str | None = None


@router.post("/internal/manuscripts/{manuscript_id}/candidates/{task_id}")
async def internal_candidate(manuscript_id: uuid.UUID, task_id: uuid.UUID, body: CandidateIn, ctx: Ctx = Depends(service_ctx)):
    require_task_kind(ctx, "manuscript_generation")
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.id == manuscript_id))).scalar_one_or_none()
    if m is None:
        raise not_found("manuscript")
    require_service_scope(ctx, m.project_id, "domain.write")
    c = (await ctx.db.execute(select(GenerationCandidate).where(GenerationCandidate.task_id == task_id,
                                                                GenerationCandidate.manuscript_id == m.id))).scalar_one_or_none()
    if c is None:
        raise not_found("candidate")
    if c.status not in ("pending",):
        return candidate_out(c)
    if body.artifact_id:
        await art_svc.require_committed(ctx.db, [body.artifact_id], m.project_id)
    c.artifact_id = body.artifact_id
    c.rationale = body.rationale
    c.provenance = body.provenance
    # Output generated against a version that is no longer current is a stale candidate (never auto-applied).
    c.status = body.status if body.status == "failed" else ("ready" if c.base_version_id == m.current_version_id else "stale")
    if body.error:
        c.conflicts = [{"error": body.error}]
    await ctx.db.commit()
    return candidate_out(c)


@router.get("/internal/projects/{project_id}/manuscript-render")
async def render_payload(project_id: uuid.UUID, version_id: uuid.UUID, anonymous: bool = True, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.read")
    project, _ = await project_for(ctx, project_id)
    v = (await ctx.db.execute(select(ManuscriptVersion).where(ManuscriptVersion.id == version_id))).scalar_one_or_none()
    if v is None:
        raise not_found("version")
    data = await art_svc.read_artifact_json(await art_svc.get_artifact(ctx.db, v.artifact_id, project_id))
    content = ManuscriptContent.model_validate(data["content"])
    cites = await ensure_bibliography(ctx.db, project)
    bib = list((await ctx.db.execute(select(BibliographyEntry).where(BibliographyEntry.project_id == project_id,
                                                                     BibliographyEntry.is_current.is_(True)))).scalars())
    cc = await check_context(ctx.db, project)
    members = (await ctx.db.execute(select(User, ProjectMember).join(ProjectMember, ProjectMember.user_id == User.id).where(
        ProjectMember.project_id == project_id, ProjectMember.removed_at.is_(None), ProjectMember.role != "reviewer"))).all()
    authors = [Author(name=u.display_name, email=u.email) for u, _ in members]
    try:
        from .submission import author_list  # M8 author records, when present

        authors = await author_list(ctx.db, project_id) or authors
    except ImportError:
        pass
    doc = render_document(content, claim_citations=cites, results=cc["results"], authors=authors,
                          bibtex="\n".join(b.bibtex for b in bib), anonymous=anonymous)
    figs = {f.file_name: f.artifact_id for s in content.sections for f in s.figures}
    page = await _rule(ctx.db, project, "length.page_limit")
    absr = await _rule(ctx.db, project, "abstract.word_limit")
    refs = await _rule(ctx.db, project, "length.reference_pages")
    identity = [a.name for a in authors] + [a.email for a in authors if a.email] + [a.affiliation for a in authors if a.affiliation]
    await ctx.db.commit()
    return {"document": doc.model_dump(mode="json"), "figures": figs, "version_number": v.version_number,
            "content_hash": v.content_hash, "identity_terms": identity,
            "page_limit": int(page.value) if page and (page.value or "").isdigit() else None,
            "page_limit_excludes_references": refs is not None,
            "abstract_word_limit": int(absr.value) if absr and (absr.value or "").isdigit() else None}


@router.get("/internal/manuscripts/{manuscript_id}/generation/{task_id}")
async def generation_context(manuscript_id: uuid.UUID, task_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    """Frozen inputs for a generation task: the brief and the base version it was requested against."""
    require_task_kind(ctx, "manuscript_generation")
    m = (await ctx.db.execute(select(Manuscript).where(Manuscript.id == manuscript_id))).scalar_one_or_none()
    if m is None:
        raise not_found("manuscript")
    require_service_scope(ctx, m.project_id, "domain.read")
    c = (await ctx.db.execute(select(GenerationCandidate).where(GenerationCandidate.task_id == task_id,
                                                                GenerationCandidate.manuscript_id == m.id))).scalar_one_or_none()
    if c is None:
        raise not_found("candidate")
    base = (await ctx.db.execute(select(ManuscriptVersion).where(ManuscriptVersion.id == c.base_version_id))).scalar_one()
    data = await art_svc.read_artifact_json(await art_svc.get_artifact(ctx.db, base.artifact_id, m.project_id))
    brief = await art_svc.read_artifact_json(await art_svc.get_artifact(ctx.db, c.brief_artifact_id, m.project_id))
    return {"candidate_id": str(c.id), "status": c.status, "sections": c.sections, "brief": brief,
            "brief_artifact_id": str(c.brief_artifact_id), "base_version_id": str(base.id),
            "base_version_number": base.version_number, "base_artifact_id": str(base.artifact_id),
            "base_content": data["content"], "input_manifest_hash": c.input_manifest_hash}
