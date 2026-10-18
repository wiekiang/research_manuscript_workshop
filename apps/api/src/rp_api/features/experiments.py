"""M9 - approved, sandboxed computational runs bound to the frozen protocol; independent recomputation; reruns.

A plan names the exact code, inputs (by hash), image digest, argv, seed and limits. Only the project owner approves
a plan, after the budget check; only approved plans of the frozen protocol run. Failed, timed-out or unrecomputable
runs are recorded and visible, and can never be promoted to a result.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from rp_contracts.contribution import RESULT_ATTESTATION, MetricValue, ResultFile, ResultManifest
from rp_contracts.enums import Gate, LedgerCategory, ProjectState
from rp_contracts.experiments import (
    ExperimentPlanIn,
    argv_for,
    compare_metrics,
    estimate_cents,
    plan_problems,
    rerun_command,
)
from rp_contracts.hashing import content_hash

from ..config import get_settings
from ..db.base import utcnow
from ..db.models.contribution import ResultManifestRecord
from ..db.models.experiment import ExperimentPlan, ExperimentRun
from ..deps import EDIT_ROLES, OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import ApiError, conflict, not_found, unprocessable
from ..routers.internal import require_task_kind
from ..routers.projects import task_out
from ..services import approvals as approval_svc
from ..services import artifacts as art_svc
from ..services import budget as budget_svc
from ..services import ledger
from ..services.tasks import create_task
from .method import active_instance, frozen_protocol

router = APIRouter(tags=["experiments"])
RUNNABLE = {ProjectState.RESEARCH_ACTIVE, ProjectState.OUTCOME_REVIEW}
PROPORTIONS = {"accuracy", "precision", "recall"}
PLAN_DECLARATION = ("I approve running exactly this code, these inputs, this image, seed and resource budget under the "
                    "frozen protocol. Results count only if the run succeeds and its metrics are independently "
                    "recomputed; a failed run is reported as failed.")


def plan_out(p: ExperimentPlan, runs: list[ExperimentRun] | None = None) -> dict:
    return {"id": str(p.id), "plan_number": p.plan_number, "title": p.title, "status": p.status, "run_type": p.run_type,
            "synthetic": p.synthetic, "image_ref": p.image_ref, "code_hash": p.code_hash, "input_hashes": p.input_hashes,
            "protocol_hash": p.protocol_hash, "estimate_cents": p.estimate_cents, "spec": p.spec,
            "artifact_id": str(p.artifact_id), "approved_at": p.approved_at, "rerun_command": rerun_command(str(p.id)),
            "declaration": PLAN_DECLARATION, "runs": [run_out(r) for r in (runs or [])]}


def run_out(r: ExperimentRun) -> dict:
    s = lambda x: str(x) if x else None  # noqa: E731
    return {"id": str(r.id), "status": r.status, "rerun_of": s(r.rerun_of), "task_id": str(r.task_id),
            "exit_code": r.exit_code, "duration_s": r.duration_s, "reported_metrics": r.reported_metrics,
            "recomputation": r.recomputation, "reproduction": r.reproduction, "failure_reason": r.failure_reason,
            "run_manifest_artifact_id": s(r.run_manifest_artifact_id), "raw_output_artifact_id": s(r.raw_output_artifact_id),
            "predictions_artifact_id": s(r.predictions_artifact_id), "log_artifact_id": s(r.log_artifact_id),
            "recomputation_artifact_id": s(r.recomputation_artifact_id), "result_manifest_id": s(r.result_manifest_id),
            "created_at": r.created_at, "promotable": r.status == "succeeded" and (r.recomputation or {}).get("status") == "passed"
            and r.result_manifest_id is None}


async def _frozen(ctx: Ctx, project_id: uuid.UUID):
    inst = await active_instance(ctx.db, project_id)
    fp = await frozen_protocol(ctx.db, inst.id) if inst else None
    if fp is None:
        raise unprocessable("h2_required", "experiments run only under an H2-frozen protocol")
    appr, problems = await approval_svc.current_approval(ctx.db, project_id, Gate.H2)
    if appr is None or problems:
        raise conflict("h2_not_current", "the H2 approval is not current", {"problems": problems})
    return inst, fp


@router.post("/projects/{project_id}/experiment-plans", status_code=201)
async def create_plan(project_id: uuid.UUID, body: ExperimentPlanIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, EDIT_ROLES)
    inst, fp = await _frozen(ctx, project_id)
    images = get_settings().experiment_images
    problems = plan_problems(body, images)
    try:
        ids = [uuid.UUID(body.code_artifact_id)] + [uuid.UUID(i.artifact_id) for i in body.inputs]
    except ValueError as exc:
        raise ApiError(422, "invalid_plan", "the experiment plan is not runnable",
                       {"problems": problems + ["code and input artifact IDs must be committed artifact IDs"]}) from exc
    try:
        arts = {str(a.id): a for a in await art_svc.require_committed(ctx.db, ids, project_id)}
    except ApiError as exc:
        problems += [str(x) for x in (exc.details or {}).get("problems", [exc.message])] if isinstance(exc.details, dict) else [exc.message]
        arts = {}
    if problems:
        raise ApiError(422, "invalid_plan", "the experiment plan is not runnable", {"problems": problems})
    n = (await ctx.db.execute(select(func.count()).select_from(ExperimentPlan).where(
        ExperimentPlan.project_id == project_id))).scalar_one()
    spec = body.model_dump(mode="json")
    record = {**spec, "plan_number": n + 1, "image_ref": images[body.image], "argv": argv_for(body),
              "protocol": {"version": fp.version_number, "hash": fp.content_hash},
              "code_hash": arts[body.code_artifact_id].content_hash,
              "input_hashes": {i.path: arts[i.artifact_id].content_hash for i in body.inputs}}
    art = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, project_id, "experiment_plan", record,
                                      depends_on=[fp.artifact_id, *ids], label=f"Experiment plan {n + 1}: {body.title}"[:300])).artifact
    p = ExperimentPlan(tenant_id=ctx.tenant_id, project_id=project_id, method_instance_id=inst.id, protocol_id=fp.id,
                       protocol_hash=fp.content_hash, plan_number=n + 1, title=body.title, spec=spec,
                       image_ref=images[body.image], code_hash=record["code_hash"], input_hashes=record["input_hashes"],
                       run_type=body.run_type, synthetic=any(i.data_nature != "empirical" for i in body.inputs),
                       estimate_cents=estimate_cents(body.limits), artifact_id=art.id)
    ctx.db.add(p)
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.METHODOLOGY_EDIT, f"Drafted experiment plan {n + 1}",
                         source_action="experiment.plan", artifact_id=art.id, rationale_requested=False)
    await ctx.db.commit()
    return plan_out(p)


class ApproveIn(BaseModel):
    declaration_accepted: bool
    declaration_text: str
    rationale: str | None = Field(default=None, max_length=4000)


@router.post("/experiment-plans/{plan_id}/approve")
async def approve_plan(plan_id: uuid.UUID, body: ApproveIn, ctx: Ctx = Depends(user_ctx)):
    p = await _plan(ctx, plan_id)
    project, _ = await project_for(ctx, p.project_id, OWNER_ONLY, lock=True)
    if p.status != "draft":
        raise conflict("not_draft", f"plan is {p.status}")
    if not body.declaration_accepted or body.declaration_text != PLAN_DECLARATION:
        raise unprocessable("declaration_required", "accept the exact declaration", {"declaration": PLAN_DECLARATION})
    _, fp = await _frozen(ctx, p.project_id)
    if fp.content_hash != p.protocol_hash:
        raise conflict("protocol_changed", "the frozen protocol changed since this plan was drafted; draft a new plan")
    # Two runs (initial + reproduction) are budgeted; above the cap the owner must raise it explicitly first.
    await budget_svc.authorize(ctx.db, ctx.principal, project, 2 * p.estimate_cents, f"experiment plan {p.plan_number}")
    p.status, p.approved_by, p.approved_at, p.approval_rationale = "approved", ctx.principal.user_id, utcnow(), body.rationale
    await ledger.capture(ctx.db, ctx.principal, project, LedgerCategory.METHODOLOGY_EDIT,
                         f"Approved experiment plan {p.plan_number} ({p.run_type})", source_action="experiment.approve",
                         artifact_id=p.artifact_id, rationale=body.rationale, rationale_requested=False)
    await ctx.db.commit()
    return plan_out(p)


async def _plan(ctx: Ctx, plan_id: uuid.UUID) -> ExperimentPlan:
    p = (await ctx.db.execute(select(ExperimentPlan).where(ExperimentPlan.id == plan_id))).scalar_one_or_none()
    if p is None:
        raise not_found("experiment plan")
    return p


class RunIn(BaseModel):
    rerun_of: uuid.UUID | None = None


@router.post("/experiment-plans/{plan_id}/runs", status_code=202)
async def start_run(plan_id: uuid.UUID, body: RunIn, ctx: Ctx = Depends(user_ctx)):
    p = await _plan(ctx, plan_id)
    project, _ = await project_for(ctx, p.project_id, EDIT_ROLES)
    if p.status != "approved":
        raise conflict("plan_not_approved", "only an approved plan can run")
    if ProjectState(project.state) not in RUNNABLE:
        raise conflict("wrong_state", f"runs happen during research (project is {project.state})")
    _, fp = await _frozen(ctx, p.project_id)
    if fp.content_hash != p.protocol_hash:
        raise conflict("protocol_changed", "the frozen protocol changed; this plan no longer applies")
    if body.rerun_of:
        prev = (await ctx.db.execute(select(ExperimentRun).where(ExperimentRun.id == body.rerun_of,
                                                                 ExperimentRun.plan_id == p.id))).scalar_one_or_none()
        if prev is None or prev.status != "succeeded":
            raise unprocessable("bad_rerun", "a reproduction rerun needs a succeeded run of the same plan")
    await budget_svc.authorize(ctx.db, ctx.principal, project, p.estimate_cents, f"run of plan {p.plan_number}")
    run_id = uuid.uuid4()
    n = (await ctx.db.execute(select(func.count()).select_from(ExperimentRun).where(ExperimentRun.plan_id == p.id))).scalar_one()
    task, _ = await create_task(ctx.db, ctx.principal, project, "experiment_run", {"run_id": str(run_id)},
                                input_manifest={"plan": str(p.artifact_id), "n": n}, estimated_cost_cents=p.estimate_cents)
    ctx.db.add(ExperimentRun(id=run_id, tenant_id=ctx.tenant_id, project_id=p.project_id, plan_id=p.id, task_id=task.id,
                             rerun_of=body.rerun_of))
    await ctx.db.commit()
    return {"task": task_out(task), "run_id": str(run_id)}


@router.get("/projects/{project_id}/experiments")
async def list_experiments(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    await project_for(ctx, project_id)
    plans = list((await ctx.db.execute(select(ExperimentPlan).where(ExperimentPlan.project_id == project_id)
                                       .order_by(ExperimentPlan.plan_number))).scalars())
    out = []
    for p in plans:
        runs = list((await ctx.db.execute(select(ExperimentRun).where(ExperimentRun.plan_id == p.id)
                                          .order_by(ExperimentRun.created_at))).scalars())
        out.append(plan_out(p, runs))
    return {"items": out, "images": sorted(get_settings().experiment_images), "plan_declaration": PLAN_DECLARATION}


@router.post("/experiment-runs/{run_id}/promote", status_code=201)
async def promote(run_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Register a succeeded, independently recomputed run as a platform result (assessed like any other result)."""
    r = (await ctx.db.execute(select(ExperimentRun).where(ExperimentRun.id == run_id).with_for_update())).scalar_one_or_none()
    if r is None:
        raise not_found("run")
    project, _ = await project_for(ctx, r.project_id, EDIT_ROLES)
    if r.status != "succeeded":
        raise conflict("run_not_succeeded", f"a {r.status} run cannot populate results")
    if (r.recomputation or {}).get("status") != "passed":
        raise conflict("not_recomputed", "metrics must be independently recomputed from raw outputs first")
    if r.result_manifest_id:
        raise conflict("already_promoted", "this run is already a result")
    p = (await ctx.db.execute(select(ExperimentPlan).where(ExperimentPlan.id == r.plan_id))).scalar_one()
    spec = ExperimentPlanIn.model_validate(p.spec)
    _, fp = await _frozen(ctx, r.project_id)
    if fp.content_hash != p.protocol_hash:
        raise conflict("protocol_changed", "the frozen protocol changed since this run")
    rerun = (await ctx.db.execute(select(ExperimentRun).where(ExperimentRun.rerun_of == r.id,
                                                              ExperimentRun.status == "succeeded")
                                  .order_by(ExperimentRun.created_at.desc()))).scalars().first()
    rerun_record = None
    if rerun and rerun.reproduction:
        rerun_record = {"values": rerun.reported_metrics, "tolerance": spec.tolerance, "run_id": str(rerun.id),
                        "comparison": rerun.reproduction}
    # Counts come from the independent validator's recomputation over the raw predictions, not from the run's report.
    counts = {}
    for c in r.recomputation.get("checks", []):
        ev = c.get("evidence") or {}
        if c["id"].startswith("recompute:") and "n" in ev and "recomputed" in ev:
            counts[c["id"].split(":", 1)[1].split("[")[0]] = (int(round(ev["recomputed"] * ev["n"])), int(ev["n"]))
    files = [ResultFile(role="code", artifact_id=spec.code_artifact_id),
             ResultFile(role="predictions", artifact_id=str(r.predictions_artifact_id)),
             ResultFile(role="raw_data", artifact_id=str(r.raw_output_artifact_id)),
             ResultFile(role="environment", artifact_id=str(r.run_manifest_artifact_id))]
    synthetic_note = " SYNTHETIC/SIMULATED inputs." if p.synthetic else ""
    manifest = ResultManifest(
        title=f"{p.title} (platform run)", protocol_version=fp.version_number, protocol_hash=fp.content_hash,
        data_origin=spec.data_origin + synthetic_note, data_rights=spec.data_rights,
        methods=f"Sandboxed platform run of plan {p.plan_number}: image {p.image_ref}, seed {spec.seed}, argv {argv_for(spec)}",
        metrics=[MetricValue(name=m.name, value=r.reported_metrics[m.name], unit="proportion", condition=m.condition,
                             n=counts.get(m.name, (None, spec.sample_size))[1],
                             numerator=counts[m.name][0] if m.name in PROPORTIONS and m.name in counts else None,
                             denominator=counts[m.name][1] if m.name in PROPORTIONS and m.name in counts else None)
                 for m in spec.metrics],
        sample_size=spec.sample_size, limitations=spec.limitations, files=files, run_type=p.run_type,
        synthetic_or_simulated=p.synthetic, rerun_record=rerun_record, attestation_accepted=True)
    count = (await ctx.db.execute(select(func.count()).select_from(ResultManifestRecord).where(
        ResultManifestRecord.project_id == r.project_id))).scalar_one()
    key = f"RES-{count + 1:03d}"
    data = {**manifest.model_dump(mode="json"), "result_key": key, "attested_by": str(ctx.principal.user_id),
            "attestation_text": RESULT_ATTESTATION, "submitted_at": utcnow().isoformat(), "experiment_run_id": str(r.id),
            "origin": "platform_run"}
    deps = [fp.artifact_id, p.artifact_id] + [a for a in (r.run_manifest_artifact_id, r.raw_output_artifact_id,
                                                          r.predictions_artifact_id, r.recomputation_artifact_id) if a]
    pub = (await art_svc.publish_json(ctx.db, ctx.principal, ctx.tenant_id, r.project_id, "result_manifest", data,
                                      depends_on=deps, label=f"Result {key}: {p.title} (platform run)"[:300])).artifact
    inst = await active_instance(ctx.db, r.project_id)
    rec = ResultManifestRecord(tenant_id=ctx.tenant_id, project_id=r.project_id, method_instance_id=inst.id, protocol_id=fp.id,
                               result_key=key, title=manifest.title, manifest=data, artifact_id=pub.id,
                               attested_by=ctx.principal.user_id, origin="platform_run")
    ctx.db.add(rec)
    await ctx.db.flush()
    r.result_manifest_id = rec.id
    task, _ = await create_task(ctx.db, ctx.principal, project, "result_assessment", {"result_id": str(rec.id)},
                                input_manifest={"result": pub.content_hash})
    await ctx.db.commit()
    return {"result_key": key, "result_id": str(rec.id), "task": task_out(task), "rerun_documented": rerun_record is not None}


# --------------------------------------------------------------------------- internal (experiment worker)
async def _run_internal(ctx: Ctx, run_id: uuid.UUID, write: bool = False) -> tuple[ExperimentRun, ExperimentPlan]:
    require_task_kind(ctx, "experiment_run")
    r = (await ctx.db.execute(select(ExperimentRun).where(ExperimentRun.id == run_id))).scalar_one_or_none()
    if r is None:
        raise not_found("run")
    require_service_scope(ctx, r.project_id, "domain.write" if write else "domain.read")
    p = (await ctx.db.execute(select(ExperimentPlan).where(ExperimentPlan.id == r.plan_id))).scalar_one()
    return r, p


@router.get("/internal/experiment-runs/{run_id}")
async def run_spec(run_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    r, p = await _run_internal(ctx, run_id)
    fp_version = None
    from ..db.models.contribution import Protocol

    fp = (await ctx.db.execute(select(Protocol).where(Protocol.id == p.protocol_id))).scalar_one()
    fp_version = fp.version_number
    prior = None
    if r.rerun_of:
        prev = (await ctx.db.execute(select(ExperimentRun).where(ExperimentRun.id == r.rerun_of))).scalar_one()
        prior = {"run_id": str(prev.id), "reported_metrics": prev.reported_metrics}
    return {"run_id": str(r.id), "status": r.status, "plan_id": str(p.id), "plan_status": p.status, "spec": p.spec,
            "image_ref": p.image_ref, "code_hash": p.code_hash, "input_hashes": p.input_hashes,
            "plan_artifact_id": str(p.artifact_id), "protocol": {"version": fp_version, "hash": p.protocol_hash},
            "synthetic": p.synthetic, "rerun_of": prior}


class RunResultIn(BaseModel):
    status: str = Field(pattern="^(running|succeeded|failed|timed_out|sandbox_unavailable)$")
    exit_code: int | None = None
    duration_s: float | None = None
    run_manifest_artifact_id: uuid.UUID | None = None
    raw_output_artifact_id: uuid.UUID | None = None
    predictions_artifact_id: uuid.UUID | None = None
    log_artifact_id: uuid.UUID | None = None
    reported_metrics: dict[str, float] | None = None
    failure_reason: str | None = None


@router.post("/internal/experiment-runs/{run_id}/status")
async def run_status(run_id: uuid.UUID, body: RunResultIn, ctx: Ctx = Depends(service_ctx)):
    r, _ = await _run_internal(ctx, run_id, write=True)
    if r.status not in ("queued", "running"):
        return run_out(r)  # terminal states never change (no backfilling)
    ids = [i for i in (body.run_manifest_artifact_id, body.raw_output_artifact_id, body.predictions_artifact_id,
                       body.log_artifact_id) if i]
    await art_svc.require_committed(ctx.db, ids, r.project_id)
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(r, k, v)
    if body.status != "succeeded":
        r.reported_metrics = None if body.status != "running" else r.reported_metrics
    await ctx.db.commit()
    return run_out(r)


@router.get("/internal/experiment-runs/{run_id}/outputs")
async def run_outputs(run_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    r, _ = await _run_internal(ctx, run_id)
    return {"status": r.status, "raw_output_artifact_id": str(r.raw_output_artifact_id) if r.raw_output_artifact_id else None}


class RecomputeIn(BaseModel):
    artifact_id: uuid.UUID
    report: dict[str, Any]


@router.post("/internal/experiment-runs/{run_id}/recomputation")
async def record_recompute(run_id: uuid.UUID, body: RecomputeIn, ctx: Ctx = Depends(service_ctx)):
    r, p = await _run_internal(ctx, run_id, write=True)
    await art_svc.require_committed(ctx.db, [body.artifact_id], r.project_id)
    if r.recomputation is None:
        r.recomputation, r.recomputation_artifact_id = body.report, body.artifact_id
        if r.rerun_of and r.status == "succeeded":
            prev = (await ctx.db.execute(select(ExperimentRun).where(ExperimentRun.id == r.rerun_of))).scalar_one()
            r.reproduction = compare_metrics(prev.reported_metrics or {}, r.reported_metrics or {},
                                             ExperimentPlanIn.model_validate(p.spec).tolerance)
    await ctx.db.commit()
    return run_out(r)


_ = content_hash
