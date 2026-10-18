"""Human Approval Engine (H1–H4 and the CFP confirmation gate).

Approvals are version-bound: each binds approver, role, declaration text/version, the exact committed
artifact hashes it covers and a content-manifest hash. They are never edited; invalidation flips status and
a fresh approval must be recorded. The contribution ledger is a separate service and table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import ApprovalStatus, ArtifactStatus, Freshness, Gate, ProjectRole
from rp_contracts.events import EventType
from rp_contracts.hashing import manifest_hash

from ..db.base import utcnow
from ..db.models.core import Approval, ApprovalDependency, Artifact, Project, ProjectMember
from ..errors import ApiError, conflict, forbidden, unprocessable
from ..security.tokens import Principal
from .common import audit, emit
from .gates import GateResult, gate


@dataclass(frozen=True)
class GateDeclaration:
    gate: Gate
    version: str
    text: str
    approver: str  # owner | corresponding_author


H4_DECLARATION = (
    "I have critically reviewed the scientific content, verified key findings and references, considered the "
    "documented literature coverage and access limits, made a substantive intellectual contribution, checked "
    "applicable venue policies and disclosures, and accept responsibility for this submission."
)

DECLARATIONS: dict[Gate, GateDeclaration] = {
    Gate.CFP: GateDeclaration(Gate.CFP, "cfp-1", (
        "I confirm the selected conference track and that I have checked each blocking rule against the official "
        "source snapshot shown, including the resolution of every ambiguous or conflicting rule."), "owner"),
    Gate.H1: GateDeclaration(Gate.H1, "h1-1", (
        "I have critically reviewed the research question, intended contribution, nearest prior work, novelty "
        "caveats, feasibility assessment and study-type choice. This research direction reflects my own scientific "
        "judgment; novelty remains a hypothesis supported by the documented literature search."), "owner"),
    Gate.H2: GateDeclaration(Gate.H2, "h2-1", (
        "I have substantively reviewed this research protocol, including ethics, rights and cost considerations, "
        "and approve freezing this exact version. Any change after data inspection will be recorded as a dated "
        "amendment with a rationale."), "owner"),
    Gate.H3: GateDeclaration(Gate.H3, "h3-1", (
        "I have reviewed the actual outcomes, anomalies, statistics, assurance levels, interpretation and "
        "limitations. The recorded interpretation and contribution assessment are my own scientific judgment and "
        "do not overstate what the evidence supports."), "owner"),
    Gate.H4: GateDeclaration(Gate.H4, "h4-1", H4_DECLARATION, "corresponding_author"),
}


async def _member(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> ProjectMember | None:
    return (
        await db.execute(
            select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id,
                                        ProjectMember.removed_at.is_(None))
        )
    ).scalar_one_or_none()


async def record_approval(
    db: AsyncSession,
    actor: Principal,
    project: Project,
    gate_name: Gate,
    bound: list[Artifact],
    *,
    declaration_accepted: bool,
    declaration_text: str,
    rationale: str | None = None,
    extra_manifest: list[tuple[str, str]] | None = None,
) -> Approval:
    if actor.kind != "user" or actor.user_id is None:
        raise forbidden("only a human researcher can record an approval", code="human_required")
    decl = DECLARATIONS[gate_name]
    if not declaration_accepted or declaration_text.strip() != decl.text:
        raise unprocessable("declaration_required", "the exact declaration must be shown and accepted",
                            {"declaration_version": decl.version, "declaration_text": decl.text})
    member = await _member(db, project.id, actor.user_id)
    if member is None:
        raise forbidden("not a project member")
    if decl.approver == "owner" and member.role != ProjectRole.OWNER:
        raise forbidden(f"{gate_name.value} must be approved by the project owner")
    if decl.approver == "corresponding_author" and not member.is_corresponding_author:
        raise forbidden(f"{gate_name.value} must be signed by the corresponding author")
    if not bound:
        raise unprocessable("nothing_to_approve", "an approval must bind at least one committed artifact")
    for a in bound:
        if a.project_id != project.id or a.status != ArtifactStatus.AVAILABLE:
            raise conflict("uncommitted_artifact", f"artifact {a.id} is not a committed artifact of this project")
        if a.freshness != Freshness.CURRENT:
            raise conflict("stale_artifact", f"artifact {a.id} ({a.kind}) is stale; approve the current version")
    entries = [(f"{a.kind}:{a.id}", a.content_hash) for a in bound] + list(extra_manifest or [])
    mhash = manifest_hash(entries)

    previous = list(
        (await db.execute(select(Approval).where(Approval.project_id == project.id, Approval.gate == gate_name.value,
                                                 Approval.status == ApprovalStatus.VALID))).scalars()
    )
    approval = Approval(
        id=uuid.uuid4(), tenant_id=project.tenant_id, project_id=project.id, gate=gate_name.value,
        status=ApprovalStatus.VALID, approver_id=actor.user_id, approver_role=member.role,
        declaration_text=decl.text, declaration_version=decl.version, rationale=rationale,
        content_manifest_hash=mhash,
        bound_artifacts=[{"id": str(a.id), "kind": a.kind, "hash": a.content_hash} for a in bound]
        + [{"name": n, "hash": h} for n, h in (extra_manifest or [])],
        project_version=project.version, decided_at=utcnow(),
    )
    db.add(approval)
    await db.flush()
    for p in previous:
        p.status = ApprovalStatus.SUPERSEDED
        p.superseded_by = approval.id
    for a in bound:
        db.add(ApprovalDependency(tenant_id=project.tenant_id, approval_id=approval.id, artifact_id=a.id,
                                  artifact_hash=a.content_hash))
    emit(db, tenant_id=project.tenant_id, type=EventType.APPROVAL_RECORDED, actor_type="user", actor_id=actor.actor_id,
         project_id=project.id, output_artifact_ids=[a.id for a in bound],
         payload={"gate": gate_name.value, "approval_id": str(approval.id), "content_manifest_hash": mhash})
    await audit(db, actor, "approval.recorded", tenant_id=project.tenant_id, project_id=project.id,
                resource_type="approval", resource_id=approval.id,
                details={"gate": gate_name.value, "content_manifest_hash": mhash, "declaration_version": decl.version})
    return approval


async def current_approval(db: AsyncSession, project_id: uuid.UUID, gate_name: Gate) -> tuple[Approval | None, list[str]]:
    """Latest valid approval and, if it no longer matches current committed artifacts, the reasons why."""
    appr = (
        await db.execute(
            select(Approval).where(Approval.project_id == project_id, Approval.gate == gate_name.value,
                                   Approval.status == ApprovalStatus.VALID).order_by(Approval.decided_at.desc())
        )
    ).scalars().first()
    if appr is None:
        return None, [f"no valid {gate_name.value} approval"]
    deps = list((await db.execute(select(ApprovalDependency).where(ApprovalDependency.approval_id == appr.id))).scalars())
    arts = {a.id: a for a in (await db.execute(select(Artifact).where(Artifact.id.in_([d.artifact_id for d in deps])))).scalars()}
    problems = []
    for d in deps:
        a = arts.get(d.artifact_id)
        if a is None or a.status != ArtifactStatus.AVAILABLE:
            problems.append(f"bound artifact {d.artifact_id} missing")
        elif a.content_hash != d.artifact_hash:
            problems.append(f"bound artifact {a.kind} hash changed")
        elif a.freshness != Freshness.CURRENT:
            problems.append(f"bound artifact {a.kind} is stale ({a.stale_reason or 'dependency changed'})")
    return appr, problems


async def invalidate_approval(db: AsyncSession, actor: Principal, approval: Approval, reason: str,
                              event_id: uuid.UUID | None = None) -> None:
    if approval.status != ApprovalStatus.VALID:
        return
    approval.status = ApprovalStatus.INVALIDATED
    approval.invalidated_at = utcnow()
    approval.invalidation_reason = reason
    approval.invalidated_by_event = event_id
    emit(db, tenant_id=approval.tenant_id, type=EventType.APPROVAL_INVALIDATED, actor_type=actor.actor_type,
         actor_id=actor.actor_id, project_id=approval.project_id,
         payload={"gate": approval.gate, "approval_id": str(approval.id), "reason": reason})
    await audit(db, actor, "approval.invalidated", tenant_id=approval.tenant_id, project_id=approval.project_id,
                resource_type="approval", resource_id=approval.id, details={"gate": approval.gate, "reason": reason})


def _approval_gate(gate_name: Gate):
    async def evaluator(db: AsyncSession, project: Project) -> GateResult:
        appr, problems = await current_approval(db, project.id, gate_name)
        gid = f"{gate_name.value.lower()}.approved"
        if appr is None or problems:
            return GateResult(gid, False, problems, next_action=f"Complete the {gate_name.value} approval")
        return GateResult(gid, True, evidence={"approval_id": str(appr.id), "content_manifest_hash": appr.content_manifest_hash})

    return evaluator


for _g in (Gate.H1, Gate.H2, Gate.H3):
    gate(f"{_g.value.lower()}.approved")(_approval_gate(_g))


@gate("approvals.h1_to_h4_current")
async def _all_current(db: AsyncSession, project: Project) -> GateResult:
    reasons = []
    for g in (Gate.H1, Gate.H2, Gate.H3, Gate.H4):
        appr, problems = await current_approval(db, project.id, g)
        reasons += [f"{g.value}: {p}" for p in problems]
    return GateResult("approvals.h1_to_h4_current", not reasons, reasons)


async def require_role(db: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID, roles: set[str]) -> ProjectMember:
    m = await _member(db, project_id, user_id)
    if m is None or m.role not in roles:
        raise ApiError(403, "forbidden", f"requires project role {sorted(roles)}")
    return m
