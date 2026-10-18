"""Scheduled reconciler for the artifact protocol (PRODUCT_SPEC §3, §9).

PostgreSQL and object storage share no transaction. This sweeper (system role, all tenants):
  * expires stale reservations that never committed and removes their temporary objects after retention;
  * deletes temporary objects that have no reservation (orphans) after retention;
  * removes leftover temporary objects of committed reservations;
  * reports committed artifacts whose content-addressed object is missing (never auto-fixed).
It never publishes or exposes an uncommitted object.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select

from rp_contracts.enums import ReservationStatus

from ..config import get_settings
from ..db.base import utcnow
from ..db.engine import session_scope
from ..db.models.core import Artifact, ArtifactReservation, AuditLog
from ..storage import get_store, run_sync


@dataclass
class ReconcileReport:
    expired_reservations: list[str] = field(default_factory=list)
    deleted_orphans: list[str] = field(default_factory=list)
    cleaned_committed_temps: list[str] = field(default_factory=list)
    pending_uploads: list[str] = field(default_factory=list)
    missing_committed_objects: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


async def reconcile(retention_seconds: int | None = None, now: float | None = None) -> ReconcileReport:
    s = get_settings()
    retention = s.temp_object_retention_seconds if retention_seconds is None else retention_seconds
    now_ts = now or time.time()
    store = get_store()
    report = ReconcileReport()
    async with session_scope("system") as db:
        reservations = {r.temp_object_key: r for r in (await db.execute(select(ArtifactReservation))).scalars()}
        temps = await run_sync(store.list_prefix, "tmp/")
        for obj in temps:
            res = reservations.get(obj.key)
            old_enough = now_ts - obj.last_modified >= retention
            if res is None:
                if old_enough:
                    await run_sync(store.delete, obj.key)
                    report.deleted_orphans.append(obj.key)
            elif res.status == ReservationStatus.COMMITTED:
                await run_sync(store.delete, obj.key)
                report.cleaned_committed_temps.append(obj.key)
            elif res.status in (ReservationStatus.RESERVED, ReservationStatus.CONTENT_UPLOADED,
                                ReservationStatus.HASH_VERIFIED, ReservationStatus.CONFLICT):
                if old_enough and res.expires_at <= utcnow():
                    await run_sync(store.delete, obj.key)
                    res.status = ReservationStatus.EXPIRED
                    report.expired_reservations.append(str(res.id))
                else:
                    report.pending_uploads.append(str(res.id))
        cutoff = utcnow() - timedelta(seconds=retention)
        for res in reservations.values():
            if res.status == ReservationStatus.RESERVED and res.expires_at <= utcnow() and res.created_at <= cutoff:
                res.status = ReservationStatus.EXPIRED
                if str(res.id) not in report.expired_reservations:
                    report.expired_reservations.append(str(res.id))
        arts = (await db.execute(select(Artifact.id, Artifact.object_key))).all()
        for aid, key in arts:
            if not await run_sync(store.exists, key):
                report.missing_committed_objects.append(str(aid))
        db.add(AuditLog(tenant_id=None, actor_type="system", actor_id="reconciler", action="artifacts.reconciled",
                        details={k: len(v) for k, v in report.as_dict().items()} | {"run": str(uuid.uuid4())}))
        await db.commit()
    return report
