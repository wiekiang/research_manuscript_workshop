"""Cost controls (PRODUCT_SPEC §9, §10).

Spend = actual (or estimated when actual is unknown) usage-ledger cost + outstanding authorized model
invocations. Alerts at 50/80/100% of the project cap. A billable operation is refused when its estimate
would exceed the cap; the ceiling is never raised automatically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.events import EventType

from ..config import get_settings
from ..db.models.core import BudgetAlert, ModelInvocation, Project, ProjectMember, UsageLedgerEntry
from ..errors import ApiError
from ..security.tokens import Principal
from .common import emit, notify


@dataclass
class BudgetStatus:
    cap_cents: int
    spent_cents: int
    reserved_cents: int
    currency: str

    @property
    def remaining_cents(self) -> int:
        return self.cap_cents - self.spent_cents - self.reserved_cents

    def as_dict(self) -> dict:
        return {"cap_cents": self.cap_cents, "spent_cents": self.spent_cents, "reserved_cents": self.reserved_cents,
                "remaining_cents": self.remaining_cents, "currency": self.currency,
                "percent_used": round(100 * (self.spent_cents + self.reserved_cents) / self.cap_cents, 1)
                if self.cap_cents else 100.0}


async def status(db: AsyncSession, project: Project) -> BudgetStatus:
    spent = (await db.execute(
        select(func.coalesce(func.sum(func.greatest(UsageLedgerEntry.actual_cost_cents, 0)), 0)).where(
            UsageLedgerEntry.project_id == project.id, UsageLedgerEntry.billing_source == "platform")
    )).scalar_one()
    reserved = (await db.execute(
        select(func.coalesce(func.sum(ModelInvocation.estimated_cost_cents), 0)).where(
            ModelInvocation.project_id == project.id, ModelInvocation.status == "authorized")
    )).scalar_one()
    return BudgetStatus(project.budget_cap_cents, int(spent), int(reserved), project.currency)


async def authorize(db: AsyncSession, actor: Principal, project: Project, estimate_cents: int, what: str) -> BudgetStatus:
    st = await status(db, project)
    if estimate_cents > st.remaining_cents:
        await check_thresholds(db, actor, project, force_at_cap=True)
        raise ApiError(
            422, "budget_exceeded",
            f"{what} is estimated at {estimate_cents} cents but only {max(st.remaining_cents, 0)} cents remain under the "
            "project cap. A project owner must explicitly raise the cap before further paid work runs.",
            {"budget": st.as_dict(), "estimate_cents": estimate_cents},
        )
    return st


async def check_thresholds(db: AsyncSession, actor: Principal, project: Project, force_at_cap: bool = False) -> list[int]:
    st = await status(db, project)
    used = st.spent_cents + st.reserved_cents
    pct = 100 * used / st.cap_cents if st.cap_cents else 100
    fired = []
    for threshold in get_settings().budget_alert_thresholds:
        if pct >= threshold or (force_at_cap and threshold == 100):
            existing = (await db.execute(select(BudgetAlert).where(
                BudgetAlert.project_id == project.id, BudgetAlert.threshold_pct == threshold,
                BudgetAlert.cap_cents == st.cap_cents))).scalar_one_or_none()
            if existing is None:
                db.add(BudgetAlert(tenant_id=project.tenant_id, project_id=project.id, threshold_pct=threshold,
                                   cap_cents=st.cap_cents, spent_cents=used))
                emit(db, tenant_id=project.tenant_id, type=EventType.BUDGET_THRESHOLD, actor_type=actor.actor_type,
                     actor_id=actor.actor_id, project_id=project.id,
                     payload={"threshold_pct": threshold, "budget": st.as_dict()})
                owners = (await db.execute(select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project.id, ProjectMember.role == "owner"))).scalars().all()
                for uid in owners:
                    notify(db, tenant_id=project.tenant_id, user_id=uid, project_id=project.id, type="budget.threshold",
                           title=f"Project spend reached {threshold}% of its cost cap",
                           body=f"{used} of {st.cap_cents} cents ({st.currency}) used or reserved.",
                           link=f"/projects/{project.id}/costs",
                           dedupe_key=f"{project.tenant_id}:budget:{project.id}:{threshold}:{st.cap_cents}")
                fired.append(threshold)
    return fired


def record_usage(db: AsyncSession, project: Project, *, category: str, provider: str, units: float, unit: str,
                 actual_cost_cents: int, estimated_cost_cents: int = 0, task_id: uuid.UUID | None = None,
                 stage: str | None = None, unit_price_snapshot: dict | None = None, billing_source: str = "platform",
                 connection_id: uuid.UUID | None = None, model_invocation_id: uuid.UUID | None = None) -> UsageLedgerEntry:
    entry = UsageLedgerEntry(
        tenant_id=project.tenant_id, project_id=project.id, task_id=task_id, category=category, stage=stage,
        provider=provider, units=units, unit=unit, unit_price_snapshot=unit_price_snapshot or {},
        estimated_cost_cents=estimated_cost_cents, actual_cost_cents=actual_cost_cents, billing_source=billing_source,
        connection_id=connection_id, currency=project.currency, model_invocation_id=model_invocation_id,
    )
    db.add(entry)
    return entry
