"""M3 - official LaTeX template retrieval, validation, adaptation and sandboxed sample compilation."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from rp_contracts.netpolicy import FetchBlocked, validate_url
from rp_contracts.scanning import sniff

from ..db.base import utcnow
from ..db.models.cfp import CfpRule
from ..db.models.latex import CompileRun, Template, TemplateFile
from ..deps import OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import conflict, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import artifacts as art_svc
from ..services.common import audit
from ..services.tasks import create_task

router = APIRouter(tags=["templates"])
MAX_TEMPLATE = 50 * 1024 * 1024
FAMILY_FROM_RULE = {"acm_acmart": "acmart", "ieee_ieeetran": "ieeetran", "springer_lncs": "llncs"}
TEMPLATE_DECLARATION = ("I confirm that this template comes from the official conference, organizer or publisher source "
                        "shown, that the selected mode (initial submission or camera-ready) matches the track's rules, "
                        "and that the recorded license note reflects what the source states.")


class ImportIn(BaseModel):
    url: str = Field(max_length=2048)
    mode: str = Field(default="submission", pattern="^(submission|camera_ready)$")
    license_note: str | None = Field(default=None, max_length=2000)


@router.post("/projects/{project_id}/templates/import", status_code=202)
async def import_template(project_id: uuid.UUID, body: ImportIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    try:
        url, _, _ = validate_url(body.url)
    except FetchBlocked as exc:
        raise unprocessable("url_not_permitted", f"this URL cannot be fetched: {exc.reason}") from exc
    tpl = Template(tenant_id=ctx.tenant_id, project_id=project.id, mode=body.mode, origin="official_link",
                   source_url=url, license_note=body.license_note, status="analyzing")
    ctx.db.add(tpl)
    await ctx.db.flush()
    task, _ = await create_task(ctx.db, ctx.principal, project, "template_import",
                                {"template_id": str(tpl.id), "url": url, "mode": body.mode},
                                input_manifest={"template": str(tpl.id), "url": url})
    tpl.task_id = task.id
    await audit(ctx.db, ctx.principal, "template.import_requested", project_id=project.id, resource_type="template",
                resource_id=tpl.id, details={"url": url, "mode": body.mode})
    await ctx.db.commit()
    return {"template_id": str(tpl.id), "task": task_out(task)}


@router.post("/projects/{project_id}/templates/upload", status_code=202)
async def upload_template(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx), file: UploadFile = File(...),
                          declared_origin_url: str = Form(..., max_length=2048),
                          origin_statement: str = Form(..., min_length=10, max_length=4000),
                          mode: str = Form("submission", pattern="^(submission|camera_ready)$"),
                          license_note: str | None = Form(None, max_length=2000), attest_official: bool = Form(False)):
    """Researcher-supplied template with declared origin (used when the official link cannot be fetched)."""
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    if not attest_official:
        raise unprocessable("attestation_required", "confirm the declared official origin of this template")
    data = await file.read(MAX_TEMPLATE + 1)
    if len(data) > MAX_TEMPLATE:
        raise unprocessable("file_too_large", "template archives are limited to 50 MB")
    if sniff(data) != "application/zip":
        raise unprocessable("not_a_zip", "upload the template as a ZIP archive")
    tpl = Template(tenant_id=ctx.tenant_id, project_id=project.id, mode=mode, origin="researcher_supplied",
                   source_url=declared_origin_url, declared_origin=origin_statement, license_note=license_note,
                   status="analyzing", retrieved_at=utcnow())
    ctx.db.add(tpl)
    await ctx.db.flush()
    pub = await art_svc.publish_bytes(ctx.db, ctx.principal, ctx.tenant_id, project.id, "template_archive", data,
                                      "application/zip", label=f"Template: {file.filename}"[:300],
                                      metadata={"declared_origin_url": declared_origin_url, "filename": file.filename},
                                      rights={"license_note": license_note, "origin": "researcher_supplied"})
    tpl.archive_artifact_id = pub.artifact.id
    tpl.archive_hash = pub.artifact.content_hash
    task, _ = await create_task(ctx.db, ctx.principal, project, "template_import",
                                {"template_id": str(tpl.id), "archive_artifact_id": str(pub.artifact.id), "mode": mode},
                                input_manifest={"template": str(tpl.id), "archive": pub.artifact.content_hash})
    tpl.task_id = task.id
    await audit(ctx.db, ctx.principal, "template.uploaded", project_id=project.id, resource_type="template",
                resource_id=tpl.id, details={"declared_origin_url": declared_origin_url, "hash": pub.artifact.content_hash})
    await ctx.db.commit()
    return {"template_id": str(tpl.id), "task": task_out(task)}


def template_out(t: Template, files: list[TemplateFile] | None = None, runs: list[CompileRun] | None = None) -> dict:
    return {
        "id": str(t.id), "mode": t.mode, "origin": t.origin, "source_url": t.source_url,
        "declared_origin": t.declared_origin, "license_note": t.license_note,
        "overleaf_export_allowed": t.overleaf_export_allowed, "archive_hash": t.archive_hash,
        "archive_artifact_id": str(t.archive_artifact_id) if t.archive_artifact_id else None,
        "family": t.family, "class_name": t.class_name, "bib_modes": t.bib_modes, "bibtex_style": t.bibtex_style,
        "requires_generation": t.requires_generation, "status": t.status, "supported": t.supported, "issues": t.issues,
        "unsupported_reasons": t.unsupported_reasons, "cfp_consistency": t.cfp_consistency,
        "retrieved_at": t.retrieved_at, "confirmed_at": t.confirmed_at,
        "label": "submission_ready_capable" if t.supported else "not_submission_ready",
        "files": [{"path": f.path, "sha256": f.sha256, "size": f.size, "role": f.role, "protected": f.protected}
                  for f in (files or [])],
        "compile_runs": [compile_run_out(r) for r in (runs or [])],
        "declaration": TEMPLATE_DECLARATION,
    }


def compile_run_out(r: CompileRun) -> dict:
    return {"id": str(r.id), "kind": r.kind, "options": r.options, "status": r.status, "pages": r.pages,
            "checks": r.checks, "errors": r.errors, "freshness": r.freshness, "created_at": r.created_at,
            "pdf_artifact_id": str(r.pdf_artifact_id) if r.pdf_artifact_id else None,
            "report_artifact_id": str(r.report_artifact_id) if r.report_artifact_id else None,
            "log_artifact_id": str(r.log_artifact_id) if r.log_artifact_id else None,
            "source_bundle_artifact_id": str(r.source_bundle_artifact_id) if r.source_bundle_artifact_id else None,
            "manuscript_version_id": str(r.manuscript_version_id) if r.manuscript_version_id else None}


@router.get("/projects/{project_id}/templates")
async def list_templates(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    tpls = list((await ctx.db.execute(select(Template).where(Template.project_id == project_id)
                                      .order_by(Template.created_at.desc()))).scalars())
    out = []
    for t in tpls:
        files = list((await ctx.db.execute(select(TemplateFile).where(TemplateFile.template_id == t.id)
                                           .order_by(TemplateFile.path))).scalars())
        runs = list((await ctx.db.execute(select(CompileRun).where(CompileRun.template_id == t.id)
                                          .order_by(CompileRun.created_at.desc()))).scalars())
        out.append(template_out(t, files, runs))
    return {"items": out}


class SampleIn(BaseModel):
    anonymous: bool = False
    bib_mode: str = Field(default="bibtex", pattern="^(bibtex|biber)$")


@router.post("/projects/{project_id}/templates/{template_id}/compile-sample", status_code=202)
async def compile_sample(project_id: uuid.UUID, template_id: uuid.UUID, body: SampleIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    t = await _template(ctx, project_id, template_id)
    if not t.supported:
        raise unprocessable("template_unsupported", "this template is not supported; see the diagnostics",
                            {"reasons": t.unsupported_reasons})
    task, _ = await create_task(ctx.db, ctx.principal, project, "template_compile",
                                {"template_id": str(t.id), "kind": "sample", "options": body.model_dump()},
                                input_manifest={"template": t.archive_hash, "options": body.model_dump(),
                                                "at": utcnow().isoformat()})
    await ctx.db.commit()
    return {"task": task_out(task)}


class ConfirmIn(BaseModel):
    declaration_accepted: bool
    overleaf_export_allowed: bool | None = None
    license_note: str | None = Field(default=None, max_length=2000)


@router.post("/projects/{project_id}/templates/{template_id}/confirm")
async def confirm_template(project_id: uuid.UUID, template_id: uuid.UUID, body: ConfirmIn, ctx: Ctx = Depends(user_ctx)):
    """Template exit criterion: snapshot recorded, adapter available, clean sample compile, mode confirmed."""
    await project_for(ctx, project_id, OWNER_ONLY)
    t = await _template(ctx, project_id, template_id)
    if not body.declaration_accepted:
        raise unprocessable("declaration_required", "accept the template declaration", {"text": TEMPLATE_DECLARATION})
    if not t.supported:
        raise unprocessable("template_unsupported", "unsupported templates cannot be confirmed for submission",
                            {"reasons": t.unsupported_reasons})
    clean = (await ctx.db.execute(select(CompileRun).where(
        CompileRun.template_id == t.id, CompileRun.kind == "sample", CompileRun.status == "compiled"))).scalars().first()
    if clean is None:
        raise unprocessable("no_clean_compile", "a clean sample compile is required before confirming the template")
    for other in (await ctx.db.execute(select(Template).where(Template.project_id == project_id, Template.mode == t.mode,
                                                              Template.status == "confirmed"))).scalars():
        other.status = "validated"
    t.status = "confirmed"
    t.confirmed_by = ctx.principal.user_id
    t.confirmed_at = utcnow()
    if body.overleaf_export_allowed is not None:
        t.overleaf_export_allowed = body.overleaf_export_allowed
    if body.license_note:
        t.license_note = body.license_note
    await audit(ctx.db, ctx.principal, "template.confirmed", project_id=project_id, resource_type="template",
                resource_id=t.id, details={"mode": t.mode, "family": t.family, "hash": t.archive_hash})
    await ctx.db.commit()
    return template_out(t)


async def _template(ctx: Ctx, project_id: uuid.UUID, template_id: uuid.UUID) -> Template:
    t = (await ctx.db.execute(select(Template).where(Template.id == template_id,
                                                     Template.project_id == project_id))).scalar_one_or_none()
    if t is None:
        raise not_found("template")
    return t


async def confirmed_template(db, project_id: uuid.UUID, mode: str = "submission") -> Template | None:
    return (await db.execute(select(Template).where(Template.project_id == project_id, Template.mode == mode,
                                                    Template.status == "confirmed"))).scalars().first()


# --------------------------------------------------------------------------- internal
@router.get("/internal/projects/{project_id}/templates/{template_id}")
async def internal_template(project_id: uuid.UUID, template_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.read")
    t = await _template(ctx, project_id, template_id)
    files = list((await ctx.db.execute(select(TemplateFile).where(TemplateFile.template_id == t.id))).scalars())
    return template_out(t, files)


class AnalysisIn(BaseModel):
    archive_artifact_id: uuid.UUID
    manifest_artifact_id: uuid.UUID | None = None
    rejected_reasons: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] | None = None
    retrieved_at: str | None = None


@router.post("/internal/projects/{project_id}/templates/{template_id}/analysis")
async def ingest_analysis(project_id: uuid.UUID, template_id: uuid.UUID, body: AnalysisIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "template_import")
    project, _ = await project_for(ctx, project_id)
    t = await _template(ctx, project_id, template_id)
    arts = [body.archive_artifact_id] + ([body.manifest_artifact_id] if body.manifest_artifact_id else [])
    await art_svc.require_committed(ctx.db, arts, project_id)
    arch = await art_svc.get_artifact(ctx.db, body.archive_artifact_id, project_id)
    t.archive_artifact_id = arch.id
    t.archive_hash = arch.content_hash
    t.manifest_artifact_id = body.manifest_artifact_id
    if body.retrieved_at:
        from datetime import datetime

        t.retrieved_at = datetime.fromisoformat(body.retrieved_at)
    if body.rejected_reasons:
        t.status = "rejected"
        t.supported = False
        t.unsupported_reasons = body.rejected_reasons
        await ctx.db.commit()
        return template_out(t)
    m = body.manifest or {}
    t.family = m.get("family")
    t.class_name = m.get("class_name")
    t.bib_modes = m.get("bib_modes") or []
    t.bibtex_style = m.get("bibtex_style")
    t.requires_generation = bool(m.get("requires_generation"))
    t.supported = bool(m.get("supported"))
    t.unsupported_reasons = m.get("unsupported_reasons") or []
    t.issues = m.get("issues") or []
    t.status = "validated" if t.supported else "unsupported"
    existing = {f.path for f in (await ctx.db.execute(select(TemplateFile).where(TemplateFile.template_id == t.id))).scalars()}
    for mem in m.get("members", []):
        if mem["path"] not in existing:
            ctx.db.add(TemplateFile(tenant_id=ctx.tenant_id, template_id=t.id, path=mem["path"], sha256=mem["sha256"],
                                    size=mem["size"], role=mem["role"], protected=mem["protected"]))
    # Consistency with the confirmed CFP's template rule (never silently assumed).
    rule = (await ctx.db.execute(select(CfpRule).where(
        CfpRule.edition_id == project.target_edition_id, CfpRule.rule_key == "template.family",
        CfpRule.is_current.is_(True)))).scalars().first() if project.target_edition_id else None
    if rule is None:
        t.cfp_consistency = {"status": "manual_check", "detail": "the CFP template rule is unknown or not imported"}
    else:
        expected = FAMILY_FROM_RULE.get(rule.value or "")
        ok = expected == t.family
        t.cfp_consistency = {"status": "passed" if ok else ("failed" if expected else "manual_check"),
                             "cfp_rule_id": str(rule.id), "cfp_value": rule.value, "template_family": t.family,
                             "quote": rule.quote}
    await ctx.db.commit()
    return template_out(t)


class CompileRunIn(BaseModel):
    template_id: uuid.UUID
    kind: str = Field(pattern="^(sample|manuscript|package)$")
    options: dict[str, Any]
    status: str
    report_artifact_id: uuid.UUID
    pdf_artifact_id: uuid.UUID | None = None
    log_artifact_id: uuid.UUID | None = None
    source_bundle_artifact_id: uuid.UUID | None = None
    checks: list[dict[str, Any]]
    pages: int | None = None
    errors: list[str] = Field(default_factory=list)
    manuscript_version_id: uuid.UUID | None = None


@router.post("/internal/projects/{project_id}/compile-runs", status_code=201)
async def record_compile(project_id: uuid.UUID, body: CompileRunIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.write")
    require_task_kind(ctx, "template_import", "template_compile", "manuscript_compile", "package_build")
    task_id = uuid.UUID(ctx.principal.scope["task_id"])
    ids = [i for i in (body.report_artifact_id, body.pdf_artifact_id, body.log_artifact_id, body.source_bundle_artifact_id) if i]
    await art_svc.require_committed(ctx.db, ids, project_id)
    dup = (await ctx.db.execute(select(CompileRun).where(CompileRun.task_id == task_id,
                                                         CompileRun.report_artifact_id == body.report_artifact_id))).scalars().first()
    if dup:
        return compile_run_out(dup)
    await _template(ctx, project_id, body.template_id)
    run = CompileRun(tenant_id=ctx.tenant_id, project_id=project_id, task_id=task_id, **body.model_dump())
    ctx.db.add(run)
    await ctx.db.commit()
    return compile_run_out(run)


_ = conflict
