"""Artifact publication protocol (PRODUCT_SPEC §3).

ARTIFACT_RESERVED -> CONTENT_UPLOADED -> HASH_VERIFIED -> ARTIFACT_COMMITTED -> AVAILABLE_TO_WORKFLOW

* The reservation key is deterministic over (tenant, project, task, input_manifest_hash, output_kind, slot).
* Bytes go to a private temporary key; the API re-hashes them before committing.
* Commit records metadata, dependencies and the outbox event in the caller's transaction.
* Re-committing the same key with the same hash returns the committed artifact; a different hash is a
  conflict that is recorded for investigation.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.artifacts import ARTIFACT_KINDS, CommitRequest, ReservationRequest
from rp_contracts.enums import ArtifactStatus, DataClassification, Freshness, ReservationStatus
from rp_contracts.events import EventType
from rp_contracts.hashing import canonical_json, sha256_hex

from ..config import get_settings
from ..db.base import utcnow
from ..db.models.core import Artifact, ArtifactDependency, ArtifactReservation
from ..errors import ApiError, conflict, not_found, unprocessable
from ..security.tokens import Principal
from ..storage import cas_key, get_store, run_sync, sha256_of_object, temp_key
from .common import audit, emit


def reservation_idempotency_key(
    tenant_id: uuid.UUID, project_id: uuid.UUID | None, task_id: uuid.UUID | None, input_manifest_hash: str,
    output_kind: str, slot: str,
) -> str:
    raw = f"{tenant_id}|{project_id}|{task_id}|{input_manifest_hash}|{output_kind}|{slot}"
    return sha256_hex(raw.encode())


def _kind_spec(kind: str, media_type: str):
    spec = ARTIFACT_KINDS.get(kind)
    if spec is None:
        raise unprocessable("unknown_artifact_kind", f"unknown artifact kind {kind}")
    if media_type.split(";")[0].strip() not in spec.media_types:
        raise unprocessable(
            "media_type_not_permitted", f"{media_type} is not permitted for {kind}", {"allowed": list(spec.media_types)}
        )
    return spec


async def reserve(
    db: AsyncSession, actor: Principal, tenant_id: uuid.UUID, req: ReservationRequest, api_internal: bool = False
) -> ArtifactReservation:
    spec = _kind_spec(req.output_kind, req.media_type)
    if not api_internal and actor.kind == "service" and not spec.worker_producible:
        raise ApiError(403, "kind_not_worker_producible", f"{req.output_kind} can only be created through the API")
    key = reservation_idempotency_key(tenant_id, req.project_id, req.task_id, req.input_manifest_hash, req.output_kind, req.slot)
    existing = (
        await db.execute(
            select(ArtifactReservation).where(
                ArtifactReservation.tenant_id == tenant_id, ArtifactReservation.idempotency_key == key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.status == ReservationStatus.EXPIRED:
            existing.status = ReservationStatus.RESERVED
            existing.expires_at = utcnow() + timedelta(seconds=get_settings().reservation_ttl_seconds)
        return existing
    rid = uuid.uuid4()
    res = ArtifactReservation(
        id=rid,
        tenant_id=tenant_id,
        project_id=req.project_id,
        task_id=req.task_id,
        idempotency_key=key,
        input_manifest_hash=req.input_manifest_hash,
        output_kind=req.output_kind,
        media_type=req.media_type,
        expected_hash=req.expected_hash,
        classification=(req.classification or spec.default_classification).value,
        label=req.label,
        temp_object_key=temp_key(tenant_id, rid),
        status=ReservationStatus.RESERVED,
        actor_id=actor.actor_id,
        expires_at=utcnow() + timedelta(seconds=get_settings().reservation_ttl_seconds),
    )
    db.add(res)
    await db.flush()
    return res


async def get_reservation(db: AsyncSession, reservation_id: uuid.UUID, lock: bool = False) -> ArtifactReservation:
    q = select(ArtifactReservation).where(ArtifactReservation.id == reservation_id)
    if lock:
        q = q.with_for_update()
    res = (await db.execute(q)).scalar_one_or_none()
    if res is None:
        raise not_found("reservation")
    return res


async def upload(db: AsyncSession, res: ArtifactReservation, chunks: Iterator[bytes]) -> ArtifactReservation:
    spec = ARTIFACT_KINDS[res.output_kind]
    if res.status == ReservationStatus.COMMITTED:
        raise conflict("reservation_committed", "content is already committed for this reservation; commit is idempotent")
    limit = spec.max_bytes

    def bounded() -> Iterator[bytes]:
        total = 0
        for c in chunks:
            total += len(c)
            if total > limit:
                raise unprocessable("artifact_too_large", f"{res.output_kind} exceeds {limit} bytes")
            yield c

    size = await run_sync(get_store().put_stream, res.temp_object_key, bounded(), res.media_type)
    res.status = ReservationStatus.CONTENT_UPLOADED
    res.uploaded_size = size
    return res


async def commit(
    db: AsyncSession, actor: Principal, res: ArtifactReservation, req: CommitRequest, rights: dict[str, Any] | None = None
) -> tuple[Artifact, bool]:
    """Verify and commit. Returns (artifact, created)."""
    if res.status == ReservationStatus.COMMITTED:
        art = (await db.execute(select(Artifact).where(Artifact.id == res.artifact_id))).scalar_one()
        if art.content_hash == req.content_hash:
            return art, False
        res.conflict_details = {"reported_hash": req.content_hash, "committed_hash": art.content_hash, "at": utcnow().isoformat()}
        await audit(db, actor, "artifact.commit_conflict", tenant_id=res.tenant_id, project_id=res.project_id,
                    resource_type="artifact_reservation", resource_id=res.id, details=res.conflict_details)
        raise conflict("artifact_hash_conflict", "a different hash was reported for an already committed reservation",
                       {"reservation_id": str(res.id), "artifact_id": str(art.id)})
    store = get_store()
    if not await run_sync(store.exists, res.temp_object_key):
        raise conflict("content_missing", "no uploaded content for this reservation; upload before committing")
    actual_hash, actual_size = await run_sync(sha256_of_object, store, res.temp_object_key)
    mismatch = []
    if actual_hash != req.content_hash:
        mismatch.append("reported hash does not match uploaded bytes")
    if res.expected_hash and actual_hash != res.expected_hash:
        mismatch.append("uploaded bytes do not match the expected hash declared at reservation")
    if actual_size != req.size_bytes:
        mismatch.append("reported size does not match uploaded bytes")
    if mismatch:
        res.conflict_details = {"problems": mismatch, "actual_hash": actual_hash, "reported_hash": req.content_hash}
        await audit(db, actor, "artifact.hash_mismatch", tenant_id=res.tenant_id, project_id=res.project_id,
                    resource_type="artifact_reservation", resource_id=res.id, details=res.conflict_details)
        raise conflict("hash_mismatch", "; ".join(mismatch), {"reservation_id": str(res.id)})
    res.status = ReservationStatus.HASH_VERIFIED
    res.uploaded_hash = actual_hash

    parents = []
    if req.depends_on:
        parents = list((await db.execute(select(Artifact).where(Artifact.id.in_(req.depends_on)))).scalars())
        if len(parents) != len(set(req.depends_on)):
            raise unprocessable("unknown_dependency", "a declared dependency is not a committed artifact in this tenant")

    final_key = cas_key(res.tenant_id, actual_hash)
    await run_sync(store.copy, res.temp_object_key, final_key)
    now = utcnow()
    art = Artifact(
        id=uuid.uuid4(),
        tenant_id=res.tenant_id,
        project_id=res.project_id,
        kind=res.output_kind,
        content_hash=actual_hash,
        size_bytes=actual_size,
        media_type=res.media_type,
        object_key=final_key,
        status=ArtifactStatus.COMMITTED,
        freshness=Freshness.CURRENT,
        classification=res.classification,
        label=res.label,
        rights=rights or {},
        meta=dict(req.metadata),
        task_id=res.task_id,
        reservation_id=res.id,
        input_manifest_hash=res.input_manifest_hash,
        created_by=actor.actor_id,
        committed_at=now,
    )
    db.add(art)
    await db.flush()
    for p in parents:
        db.add(ArtifactDependency(tenant_id=res.tenant_id, parent_artifact_id=p.id, child_artifact_id=art.id,
                                  dependency_kind=req.dependency_kind, validator_version=req.validator_version))
    res.status = ReservationStatus.COMMITTED
    res.artifact_id = art.id
    emit(db, tenant_id=res.tenant_id, type=EventType.ARTIFACT_COMMITTED, actor_type=actor.actor_type,
         actor_id=actor.actor_id, project_id=res.project_id, task_id=res.task_id,
         input_manifest_hash=res.input_manifest_hash, output_artifact_ids=[art.id],
         payload={"kind": art.kind, "content_hash": art.content_hash})
    art.status = ArtifactStatus.AVAILABLE
    art.available_at = now
    await db.flush()
    return art, True


async def cleanup_temp(res: ArtifactReservation) -> None:
    """Best-effort removal after the DB transaction committed; the reconciler handles failures."""
    try:
        await run_sync(get_store().delete, res.temp_object_key)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("rp_api.artifacts").warning("temp cleanup deferred to reconciler: %s", exc)


@dataclass
class Published:
    artifact: Artifact
    created: bool


async def publish_bytes(
    db: AsyncSession,
    actor: Principal,
    tenant_id: uuid.UUID,
    project_id: uuid.UUID | None,
    kind: str,
    data: bytes,
    media_type: str,
    *,
    label: str | None = None,
    depends_on: list[uuid.UUID] | None = None,
    dependency_kind: str = "derived_from",
    classification: DataClassification | None = None,
    task_id: uuid.UUID | None = None,
    input_manifest_hash: str | None = None,
    slot: str = "0",
    metadata: dict[str, Any] | None = None,
    rights: dict[str, Any] | None = None,
) -> Published:
    """API-side publication through the same reserve/upload/verify/commit lifecycle."""
    digest = sha256_hex(data)
    req = ReservationRequest(
        project_id=project_id, task_id=task_id, input_manifest_hash=input_manifest_hash or digest,
        output_kind=kind, media_type=media_type, expected_hash=digest, classification=classification, label=label,
        slot=slot,
    )
    res = await reserve(db, actor, tenant_id, req, api_internal=True)
    if res.status == ReservationStatus.COMMITTED:
        art = (await db.execute(select(Artifact).where(Artifact.id == res.artifact_id))).scalar_one()
        return Published(art, False)
    await upload(db, res, iter([data]))
    art, created = await commit(
        db, actor, res,
        CommitRequest(content_hash=digest, size_bytes=len(data), depends_on=depends_on or [],
                      dependency_kind=dependency_kind, metadata=metadata or {}),
        rights=rights,
    )
    await cleanup_temp(res)
    return Published(art, created)


async def publish_json(db: AsyncSession, actor: Principal, tenant_id: uuid.UUID, project_id: uuid.UUID | None,
                       kind: str, obj: Any, **kw) -> Published:
    return await publish_bytes(db, actor, tenant_id, project_id, kind, canonical_json(obj), "application/json", **kw)


async def get_artifact(db: AsyncSession, artifact_id: uuid.UUID, project_id: uuid.UUID | None = None) -> Artifact:
    q = select(Artifact).where(Artifact.id == artifact_id)
    if project_id is not None:
        q = q.where(Artifact.project_id == project_id)
    art = (await db.execute(q)).scalar_one_or_none()
    if art is None or art.status != ArtifactStatus.AVAILABLE:
        raise not_found("artifact")
    return art


async def read_artifact_bytes(art: Artifact) -> bytes:
    return await run_sync(get_store().get_bytes, art.object_key)


async def read_artifact_json(art: Artifact) -> Any:
    import json

    return json.loads(await read_artifact_bytes(art))


async def require_committed(db: AsyncSession, ids: list[uuid.UUID], project_id: uuid.UUID) -> list[Artifact]:
    if not ids:
        return []
    arts = list((await db.execute(select(Artifact).where(Artifact.id.in_(ids)))).scalars())
    found = {a.id: a for a in arts}
    problems = []
    for i in ids:
        a = found.get(i)
        if a is None:
            problems.append({"artifact_id": str(i), "problem": "not a committed artifact"})
        elif a.project_id != project_id:
            problems.append({"artifact_id": str(i), "problem": "belongs to another project"})
        elif a.status != ArtifactStatus.AVAILABLE:
            problems.append({"artifact_id": str(i), "problem": f"status {a.status}"})
    if problems:
        raise conflict("uncommitted_outputs", "every output must be a committed artifact of this project", problems)
    return arts
