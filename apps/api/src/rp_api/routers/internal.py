"""Worker-only routes (relative to /v1/internal). Authenticated by scoped service tokens."""

from __future__ import annotations

import hmac
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from rp_contracts.artifacts import CommitRequest, ReservationRequest
from rp_contracts.enums import ArtifactStatus, DataClassification, ProjectState, TaskState
from rp_contracts.tasks import TASK_KINDS

from ..config import get_settings
from ..db.base import utcnow
from ..db.engine import session_scope
from ..db.models.core import (
    Artifact,
    DataFlowAttestation,
    ModelInvocation,
    Project,
    ProviderDefinition,
    WorkflowTask,
)
from ..deps import (
    Ctx,
    client_ip,
    get_principal,
    project_for,
    rate_limiter,
    require_service_scope,
    service_ctx,
)
from ..errors import ApiError, conflict, forbidden, not_found
from ..security.tokens import issue_service_token
from ..services import artifacts as art_svc
from ..services import budget as budget_svc
from ..services import tasks as task_svc
from ..services.common import audit
from ..services.transitions import TransitionRequest, request_transition
from ..storage import aiter_object, get_store

router = APIRouter(prefix="/internal", tags=["internal"])

TASK_OPERATIONS = ["artifacts.write", "artifacts.read", "tasks.update", "transitions.request", "model.invoke",
                   "usage.record", "domain.read", "domain.write"]


class TokenIn(BaseModel):
    client_id: str
    client_secret: str
    task_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    purpose: str = Field(default="task", pattern="^(task|project|maintenance)$")


@router.post("/auth/token")
async def service_token(body: TokenIn, request: Request):
    rate_limiter.check(f"svc:{client_ip(request)}", 600)
    expected = get_settings().service_clients.get(body.client_id)
    if expected is None or not hmac.compare_digest(expected.get_secret_value(), body.client_secret):
        raise ApiError(401, "invalid_client", "unknown service client or secret")
    if body.purpose == "maintenance":
        token, ttl = issue_service_token(body.client_id, {"operations": ["maintenance.reconcile"]})
        return {"access_token": token, "expires_in": ttl, "scope": {"operations": ["maintenance.reconcile"]}}
    if body.purpose == "project":
        if body.project_id is None:
            raise ApiError(422, "project_required", "project-scoped tokens need a project_id")
        async with session_scope("system") as db:
            proj = (await db.execute(select(Project).where(Project.id == body.project_id))).scalar_one_or_none()
        if proj is None:
            raise not_found("project")
        scope = {"tenant_id": str(proj.tenant_id), "project_id": str(proj.id), "task_id": None,
                 "operations": ["domain.read", "notifications.write"]}
        token, ttl = issue_service_token(body.client_id, scope)
        return {"access_token": token, "expires_in": ttl, "scope": scope}
    if body.task_id is None:
        raise ApiError(422, "task_required", "task-scoped tokens need a task_id")
    async with session_scope("system") as db:
        task = (await db.execute(select(WorkflowTask).where(WorkflowTask.id == body.task_id))).scalar_one_or_none()
    if task is None:
        raise not_found("task")
    if task.state in (TaskState.SUCCEEDED, TaskState.CANCELLED, TaskState.FAILED_TERMINAL):
        raise conflict("task_terminal", f"task is {task.state}; no new credentials are issued")
    scope = {"tenant_id": str(task.tenant_id), "project_id": str(task.project_id) if task.project_id else None,
             "task_id": str(task.id), "task_kind": task.kind, "operations": TASK_OPERATIONS}
    token, ttl = issue_service_token(body.client_id, scope)
    return {"access_token": token, "expires_in": ttl, "scope": scope}


# --------------------------------------------------------------------------- artifacts
def _check_task_scope(ctx: Ctx, task_id: uuid.UUID | None) -> None:
    scoped = ctx.principal.scope.get("task_id")
    if scoped and task_id and str(task_id) != scoped:
        raise forbidden("token is scoped to another task", code="scope_violation")


@router.post("/artifacts/reservations")
async def reserve(body: ReservationRequest, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, body.project_id, "artifacts.write")
    _check_task_scope(ctx, body.task_id)
    res = await art_svc.reserve(ctx.db, ctx.principal, ctx.tenant_id, body)
    await ctx.db.commit()
    return {"reservation_id": str(res.id), "idempotency_key": res.idempotency_key, "status": res.status,
            "upload_url": f"/v1/internal/artifacts/reservations/{res.id}/content", "upload_method": "PUT",
            "artifact_id": str(res.artifact_id) if res.artifact_id else None, "expires_at": res.expires_at}


@router.put("/artifacts/reservations/{reservation_id}/content")
async def upload(reservation_id: uuid.UUID, request: Request, ctx: Ctx = Depends(service_ctx)):
    res = await art_svc.get_reservation(ctx.db, reservation_id, lock=True)
    require_service_scope(ctx, res.project_id, "artifacts.write")
    _check_task_scope(ctx, res.task_id)
    body = await request.body()
    await art_svc.upload(ctx.db, res, iter([body]))
    await ctx.db.commit()
    return {"reservation_id": str(res.id), "status": res.status, "size_bytes": res.uploaded_size}


@router.post("/artifacts/{reservation_id}/commit")
async def commit(reservation_id: uuid.UUID, body: CommitRequest, ctx: Ctx = Depends(service_ctx)):
    res = await art_svc.get_reservation(ctx.db, reservation_id, lock=True)
    require_service_scope(ctx, res.project_id, "artifacts.write")
    _check_task_scope(ctx, res.task_id)
    try:
        art, created = await art_svc.commit(ctx.db, ctx.principal, res, body)
    except ApiError:
        await ctx.db.commit()  # persist conflict details/audit for investigation
        raise
    await ctx.db.commit()
    if created:
        await art_svc.cleanup_temp(res)
    return {"artifact_id": str(art.id), "status": art.status, "content_hash": art.content_hash, "created": created,
            "kind": art.kind}


@router.get("/artifacts/{artifact_id}/content")
async def read_artifact(artifact_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    art = await art_svc.get_artifact(ctx.db, artifact_id)
    require_service_scope(ctx, art.project_id, "artifacts.read")
    return StreamingResponse(aiter_object(get_store(), art.object_key), media_type=art.media_type,
                             headers={"X-Content-Hash": art.content_hash, "X-Artifact-Kind": art.kind,
                                      "X-Classification": art.classification})


@router.get("/artifacts/{artifact_id}")
async def artifact_meta(artifact_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    art = await art_svc.get_artifact(ctx.db, artifact_id)
    require_service_scope(ctx, art.project_id, "artifacts.read")
    return {"id": str(art.id), "kind": art.kind, "content_hash": art.content_hash, "media_type": art.media_type,
            "classification": art.classification, "rights": art.rights, "metadata": art.meta,
            "freshness": art.freshness, "size_bytes": art.size_bytes}


# --------------------------------------------------------------------------- project state / transitions
class TransitionIn(BaseModel):
    requested_state: ProjectState
    expected_project_version: int
    idempotency_key: str = Field(min_length=8, max_length=200)
    method_definition_version: str | None = None
    input_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    output_artifact_ids: list[uuid.UUID] = Field(default_factory=list)
    validator_result_ids: list[str] = Field(default_factory=list)
    human_approval_id: uuid.UUID | None = None


@router.get("/projects/{project_id}")
async def project_state(project_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, project_id, "domain.read")
    project, _ = await project_for(ctx, project_id)
    return {"id": str(project.id), "state": project.state, "version": project.version,
            "resume_state": project.resume_state, "method_instance_id": str(project.method_instance_id)
            if project.method_instance_id else None}


@router.post("/projects/{project_id}/transitions")
async def transition(project_id: uuid.UUID, body: TransitionIn, ctx: Ctx = Depends(service_ctx)):
    """The only path by which workflows advance canonical state. Stale/duplicate requests never overwrite."""
    require_service_scope(ctx, project_id, "transitions.request")
    if body.human_approval_id is not None:
        # Services may reference an approval a human already recorded, never create one.
        from ..db.models.core import Approval

        appr = (await ctx.db.execute(select(Approval).where(Approval.id == body.human_approval_id,
                                                            Approval.project_id == project_id))).scalar_one_or_none()
        if appr is None or appr.status != "valid":
            raise conflict("approval_not_valid", "referenced human approval is not a valid approval of this project")
    res = await request_transition(ctx.db, ctx.principal, project_id, TransitionRequest(
        requested_state=body.requested_state, expected_project_version=body.expected_project_version,
        idempotency_key=body.idempotency_key, input_manifest_hash=body.input_manifest_hash,
        output_artifact_ids=body.output_artifact_ids, validator_result_ids=body.validator_result_ids,
        human_approval_id=body.human_approval_id, method_definition_version=body.method_definition_version))
    await ctx.db.commit()
    return res.as_dict()


# --------------------------------------------------------------------------- tasks
class TaskUpdateIn(BaseModel):
    state: TaskState
    attempt: int | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=4000)
    waiting_reason: str | None = Field(default=None, max_length=4000)
    output_artifact_ids: list[uuid.UUID] | None = None
    result: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


@router.get("/tasks/{task_id}")
async def get_task(task_id: uuid.UUID, ctx: Ctx = Depends(service_ctx)):
    _check_task_scope(ctx, task_id)
    t = await task_svc.get_task(ctx.db, task_id)
    project = None
    if t.project_id:
        project = (await ctx.db.execute(select(Project).where(Project.id == t.project_id))).scalar_one()
    return {"id": str(t.id), "kind": t.kind, "state": t.state, "attempt": t.attempt, "params": t.params,
            "input_manifest_hash": t.input_manifest_hash, "project_id": str(t.project_id) if t.project_id else None,
            "project_state": project.state if project else None, "project_version": project.version if project else None}


@router.patch("/tasks/{task_id}")
async def update_task(task_id: uuid.UUID, body: TaskUpdateIn, ctx: Ctx = Depends(service_ctx)):
    _check_task_scope(ctx, task_id)
    require_service_scope(ctx, None, "tasks.update")
    t = await task_svc.get_task(ctx.db, task_id, lock=True)
    if body.output_artifact_ids and t.project_id:
        await art_svc.require_committed(ctx.db, body.output_artifact_ids, t.project_id)
    await task_svc.update_task(ctx.db, ctx.principal, t, body.state, attempt=body.attempt, error_code=body.error_code,
                               error_message=body.error_message, waiting_reason=body.waiting_reason,
                               output_artifact_ids=body.output_artifact_ids, result=body.result, progress=body.progress)
    await ctx.db.commit()
    return {"id": str(t.id), "state": t.state}


# --------------------------------------------------------------------------- model gateway (policy side)
class AuthorizeIn(BaseModel):
    agent: str = Field(max_length=80)
    purpose: str = Field(default="generation", pattern="^(generation|embedding|review)$")
    provider: str
    model: str
    prompt_version: str
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=200)
    input_artifact_ids: list[uuid.UUID] = Field(default_factory=list)
    data_classification: DataClassification
    data_kinds: list[str] = Field(default_factory=list)
    max_tokens: int = Field(ge=1, le=200_000)
    estimated_cost_cents: int = Field(ge=0)


class CompleteIn(BaseModel):
    status: str = Field(pattern="^(succeeded|failed)$")
    input_tokens: int | None = None
    output_tokens: int | None = None
    actual_cost_cents: int | None = None
    response: dict[str, Any] | None = None
    output_artifact_id: uuid.UUID | None = None
    error: str | None = Field(default=None, max_length=4000)
    latency_ms: int | None = None
    unit_price_snapshot: dict[str, Any] = Field(default_factory=dict)


CLASS_ORDER = {"public": 0, "internal": 1, "restricted": 2}


async def _deny(ctx: Ctx, inv: ModelInvocation, reason: str, code: str = "model_call_denied"):
    inv.status = "denied"
    inv.denial_reason = reason
    await audit(ctx.db, ctx.principal, "model.denied", project_id=inv.project_id, resource_type="model_invocation",
                resource_id=inv.id, details={"reason": reason, "provider": inv.provider})
    await ctx.db.commit()
    raise ApiError(403, code, reason, {"invocation_id": str(inv.id)})


@router.post("/model-invocations/authorize")
async def authorize_model(body: AuthorizeIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, None, "model.invoke")
    scope = ctx.principal.scope
    project_id = uuid.UUID(scope["project_id"]) if scope.get("project_id") else None
    task_id = uuid.UUID(scope["task_id"]) if scope.get("task_id") else None
    existing = (await ctx.db.execute(select(ModelInvocation).where(
        ModelInvocation.tenant_id == ctx.tenant_id, ModelInvocation.idempotency_key == body.idempotency_key))).scalar_one_or_none()
    if existing is not None:
        if existing.status == "succeeded":
            return {"invocation_id": str(existing.id), "status": "cached", "response": existing.response}
        if existing.status == "authorized":
            return {"invocation_id": str(existing.id), "status": "authorized"}
        if existing.status == "denied":
            raise ApiError(403, "model_call_denied", existing.denial_reason or "denied")
        existing.status = "authorized"  # retry of a failed call
        await ctx.db.commit()
        return {"invocation_id": str(existing.id), "status": "authorized"}

    inv = ModelInvocation(tenant_id=ctx.tenant_id, project_id=project_id, task_id=task_id, agent=body.agent,
                          purpose=body.purpose, provider=body.provider, model=body.model,
                          prompt_version=body.prompt_version, prompt_hash=body.prompt_hash,
                          idempotency_key=body.idempotency_key, input_artifact_ids=body.input_artifact_ids,
                          data_classification=body.data_classification.value, status="pending",
                          max_tokens=body.max_tokens, estimated_cost_cents=body.estimated_cost_cents)
    ctx.db.add(inv)
    await ctx.db.flush()
    s = get_settings()
    prov = (await ctx.db.execute(select(ProviderDefinition).where(ProviderDefinition.key == body.provider))).scalar_one_or_none()
    if prov is None or prov.kind != "model":
        await _deny(ctx, inv, f"unknown model provider {body.provider}")
    chosen_project = (await ctx.db.execute(select(Project).where(Project.id == project_id))).scalar_one() if project_id else None
    if chosen_project is not None and chosen_project.model_provider and body.provider != chosen_project.model_provider:
        await _deny(ctx, inv, f"this project's owner selected {chosen_project.model_provider}, not {body.provider}")
    # Outside production, an owner's own connected Anthropic key may be used before the operator clears the
    # provider platform-wide: the owner accepted Anthropic's terms for their own account when connecting it.
    owner_key = False
    if body.provider == "anthropic" and not s.is_production and chosen_project is not None \
            and chosen_project.model_provider == "anthropic" and prov.gate_status != "blocked":
        from ..features.model_settings import owner_connection

        owner_key = await owner_connection(ctx.db, chosen_project.owner_id) is not None
    if not owner_key and (not prov.enabled or prov.gate_status in {"pending", "blocked"}):
        await _deny(ctx, inv, f"model provider {body.provider} is not enabled ({prov.gate_status}); record its terms and "
                              "retention settings first")
    if body.provider == "claude_cli" and s.environment != "local":
        await _deny(ctx, inv, "the Claude CLI provider is personal and local-only; deployments must use an API key")
    if s.is_production and prov.gate_status != "cleared":
        await _deny(ctx, inv, f"provider {body.provider} is not cleared for production use")
    if body.data_classification.value not in (prov.allowed_classifications or []):
        await _deny(ctx, inv, f"{body.data_classification.value} data may not be sent to {body.provider}")
    if project_id is not None:
        project = (await ctx.db.execute(select(Project).where(Project.id == project_id))).scalar_one()
        inputs = await art_svc.require_committed(ctx.db, body.input_artifact_ids, project_id) if body.input_artifact_ids else []
        highest = max([CLASS_ORDER[a.classification] for a in inputs] + [CLASS_ORDER[body.data_classification.value]])
        if highest > CLASS_ORDER[body.data_classification.value]:
            await _deny(ctx, inv, "declared classification is lower than an input artifact's classification")
        prohibited = [str(a.id) for a in inputs if (a.rights or {}).get("model_use") == "prohibited"]
        if prohibited:
            await _deny(ctx, inv, f"license or provider terms prohibit sending artifacts {prohibited} to a model")
        if body.provider != "fixture":
            atts = list((await ctx.db.execute(select(DataFlowAttestation).where(
                DataFlowAttestation.project_id == project_id, DataFlowAttestation.provider_key == body.provider,
                DataFlowAttestation.revoked_at.is_(None)))).scalars())
            covered = set().union(*[set(a.data_kinds) for a in atts]) if atts else set()
            max_cls = max([CLASS_ORDER[a.max_classification] for a in atts], default=-1)
            missing = set(body.data_kinds) - covered
            if not atts or missing or max_cls < highest:
                await _deny(ctx, inv, "the project owner has not attested this data flow to "
                                      f"{body.provider} (missing: {sorted(missing) or 'classification'})",
                            code="data_flow_not_permitted")
        try:
            await budget_svc.authorize(ctx.db, ctx.principal, project, body.estimated_cost_cents, f"model call ({body.agent})")
        except ApiError as exc:
            inv.status = "denied"
            inv.denial_reason = exc.message
            await ctx.db.commit()
            raise
    inv.status = "authorized"
    await ctx.db.commit()
    return {"invocation_id": str(inv.id), "status": "authorized"}


@router.post("/model-invocations/{invocation_id}/complete")
async def complete_model(invocation_id: uuid.UUID, body: CompleteIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, None, "model.invoke")
    inv = (await ctx.db.execute(select(ModelInvocation).where(ModelInvocation.id == invocation_id).with_for_update())).scalar_one_or_none()
    if inv is None:
        raise not_found("invocation")
    if inv.status == "succeeded":
        return {"invocation_id": str(inv.id), "status": inv.status}
    if inv.status != "authorized":
        raise conflict("invocation_not_authorized", f"invocation is {inv.status}")
    inv.status = body.status
    inv.input_tokens = body.input_tokens
    inv.output_tokens = body.output_tokens
    inv.actual_cost_cents = body.actual_cost_cents if body.actual_cost_cents is not None else inv.estimated_cost_cents
    inv.response = body.response if body.status == "succeeded" else None
    inv.output_artifact_id = body.output_artifact_id
    inv.error = body.error
    inv.latency_ms = body.latency_ms
    inv.finished_at = utcnow()
    if inv.project_id is not None:
        project = (await ctx.db.execute(select(Project).where(Project.id == inv.project_id))).scalar_one()
        budget_svc.record_usage(ctx.db, project, category="llm" if inv.purpose != "embedding" else "embeddings",
                                provider=inv.provider, units=(body.input_tokens or 0) + (body.output_tokens or 0),
                                unit="tokens", actual_cost_cents=inv.actual_cost_cents or 0,
                                estimated_cost_cents=inv.estimated_cost_cents, task_id=inv.task_id, stage=inv.agent,
                                unit_price_snapshot=body.unit_price_snapshot, model_invocation_id=inv.id)
        await ctx.db.flush()
        await budget_svc.check_thresholds(ctx.db, ctx.principal, project)
    await ctx.db.commit()
    return {"invocation_id": str(inv.id), "status": inv.status}


class UsageIn(BaseModel):
    category: str = Field(pattern="^(scholarly_api|compute|storage|egress|tex_compile|embeddings)$")
    provider: str
    units: float = Field(ge=0)
    unit: str
    actual_cost_cents: int = Field(ge=0, default=0)
    estimated_cost_cents: int = Field(ge=0, default=0)
    stage: str | None = None
    unit_price_snapshot: dict[str, Any] = Field(default_factory=dict)


@router.post("/usage", status_code=201)
async def record_usage(body: UsageIn, ctx: Ctx = Depends(service_ctx)):
    require_service_scope(ctx, None, "usage.record")
    pid = ctx.principal.scope.get("project_id")
    if not pid:
        raise ApiError(422, "project_required", "usage must be attributed to a project")
    project = (await ctx.db.execute(select(Project).where(Project.id == uuid.UUID(pid)))).scalar_one()
    tid = ctx.principal.scope.get("task_id")
    budget_svc.record_usage(ctx.db, project, category=body.category, provider=body.provider, units=body.units,
                            unit=body.unit, actual_cost_cents=body.actual_cost_cents,
                            estimated_cost_cents=body.estimated_cost_cents, task_id=uuid.UUID(tid) if tid else None,
                            stage=body.stage, unit_price_snapshot=body.unit_price_snapshot)
    await ctx.db.flush()
    await budget_svc.check_thresholds(ctx.db, ctx.principal, project)
    await ctx.db.commit()
    return {"recorded": True}


@router.post("/budget/authorize")
async def budget_authorize(body: dict, ctx: Ctx = Depends(service_ctx)):
    pid = ctx.principal.scope.get("project_id")
    project = (await ctx.db.execute(select(Project).where(Project.id == uuid.UUID(pid)))).scalar_one()
    st = await budget_svc.authorize(ctx.db, ctx.principal, project, int(body.get("estimate_cents", 0)),
                                    str(body.get("what", "billable operation")))
    return st.as_dict()


class ApprovalRequiredIn(BaseModel):
    state: ProjectState
    event_id: uuid.UUID


HUMAN_ACTIONS = {
    ProjectState.TARGET_REVIEW: ("CFP", "Confirm the selected track and every blocking CFP rule"),
    ProjectState.DIRECTION_REVIEW: ("H1", "Review the research direction, rationale and feasibility (H1)"),
    ProjectState.PROTOCOL_REVIEW: ("H2", "Review and freeze the research protocol (H2)"),
    ProjectState.OUTCOME_REVIEW: ("H3", "Validate actual outcomes and interpretation (H3)"),
    ProjectState.FINAL_APPROVAL: ("H4", "Corresponding author final approval of the content manifest (H4)"),
}


@router.post("/projects/{project_id}/approval-required")
async def approval_required(project_id: uuid.UUID, body: ApprovalRequiredIn, ctx: Ctx = Depends(service_ctx)):
    """Called by the project coordinator workflow when the project waits on a human decision."""
    require_service_scope(ctx, project_id, "notifications.write")
    project, _ = await project_for(ctx, project_id)
    if project.state != body.state.value or body.state not in HUMAN_ACTIONS:
        return {"notified": False, "reason": "project is no longer waiting on that gate"}
    from rp_contracts.events import EventType

    from ..db.models.core import ProjectMember
    from ..services.common import emit, notify

    gate_name, action = HUMAN_ACTIONS[body.state]
    recipients = (await ctx.db.execute(select(ProjectMember.user_id).where(
        ProjectMember.project_id == project_id, ProjectMember.removed_at.is_(None),
        (ProjectMember.role == "owner") | (ProjectMember.is_corresponding_author.is_(True))))).scalars().all()
    for uid in set(recipients):
        notify(ctx.db, tenant_id=project.tenant_id, user_id=uid, project_id=project_id, type="approval.required",
               title=f"{project.title}: {action}", body="The workflow is waiting for your decision.",
               link=f"/projects/{project_id}", dedupe_key=f"{project.tenant_id}:{body.event_id}:{uid}")
    emit(ctx.db, tenant_id=project.tenant_id, type=EventType.APPROVAL_REQUIRED, actor_type="service",
         actor_id=ctx.principal.actor_id, project_id=project_id, payload={"gate": gate_name, "state": body.state.value})
    await ctx.db.commit()
    return {"notified": True, "gate": gate_name}


# --------------------------------------------------------------------------- maintenance
@router.post("/maintenance/reconcile-artifacts")
async def reconcile(request: Request, principal=Depends(get_principal)):
    if principal.kind != "service" or "maintenance.reconcile" not in principal.scope.get("operations", []):
        raise forbidden("maintenance token required", code="service_only")
    from ..services.reconciler import reconcile as run

    return (await run()).as_dict()


def task_kind_of(ctx: Ctx) -> str | None:
    return ctx.principal.scope.get("task_kind")


def require_task_kind(ctx: Ctx, *kinds: str) -> None:
    if task_kind_of(ctx) not in kinds:
        raise forbidden(f"this endpoint accepts results only from tasks of kind {kinds}", code="scope_violation")


_ = (TASK_KINDS, Artifact, ArtifactStatus)
