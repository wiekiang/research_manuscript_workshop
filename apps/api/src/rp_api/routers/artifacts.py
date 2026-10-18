from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from rp_contracts.enums import ArtifactStatus, DataClassification

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models.core import Artifact, ArtifactDependency
from ..deps import Ctx, project_for, user_ctx
from ..errors import ApiError, not_found
from ..services.artifacts import get_artifact
from ..services.common import audit
from ..storage import aiter_object, get_store, sign_download, verify_download

router = APIRouter(tags=["artifacts"])


def artifact_out(a: Artifact) -> dict:
    return {"id": str(a.id), "project_id": str(a.project_id) if a.project_id else None, "kind": a.kind,
            "content_hash": a.content_hash, "size_bytes": a.size_bytes, "media_type": a.media_type,
            "status": a.status, "freshness": a.freshness, "classification": a.classification, "label": a.label,
            "rights": a.rights, "metadata": a.meta, "created_by": a.created_by, "created_at": a.created_at,
            "committed_at": a.committed_at, "stale_reason": a.stale_reason,
            "task_id": str(a.task_id) if a.task_id else None}


@router.get("/projects/{project_id}/artifacts")
async def list_artifacts(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx), kind: str | None = None,
                         limit: int = Query(100, le=500)):
    await project_for(ctx, project_id)
    q = select(Artifact).where(Artifact.project_id == project_id, Artifact.status == ArtifactStatus.AVAILABLE)
    if kind:
        q = q.where(Artifact.kind == kind)
    rows = (await ctx.db.execute(q.order_by(Artifact.created_at.desc()).limit(limit))).scalars()
    return {"items": [artifact_out(a) for a in rows]}


@router.get("/artifacts/{artifact_id}")
async def artifact_detail(artifact_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    art = await get_artifact(ctx.db, artifact_id)
    if art.project_id:
        await project_for(ctx, art.project_id)
    parents = (await ctx.db.execute(select(ArtifactDependency).where(ArtifactDependency.child_artifact_id == art.id))).scalars()
    children = (await ctx.db.execute(select(ArtifactDependency).where(ArtifactDependency.parent_artifact_id == art.id))).scalars()
    return {**artifact_out(art),
            "depends_on": [{"artifact_id": str(d.parent_artifact_id), "kind": d.dependency_kind} for d in parents],
            "dependents": [{"artifact_id": str(d.child_artifact_id), "kind": d.dependency_kind} for d in children]}


@router.get("/artifacts/{artifact_id}/download-url")
async def download_url(artifact_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    """Issue a short-lived signed URL after authorization. Restricted artifacts are audited."""
    art = await get_artifact(ctx.db, artifact_id)
    if art.project_id is None:
        raise not_found("artifact")
    await project_for(ctx, art.project_id)
    ttl = get_settings().signed_url_ttl_seconds
    if art.classification == DataClassification.RESTRICTED:
        await audit(ctx.db, ctx.principal, "artifact.restricted_access", project_id=art.project_id,
                    resource_type="artifact", resource_id=art.id, details={"kind": art.kind})
        await ctx.db.commit()
    fname = f"{art.kind}-{art.content_hash[:12]}"
    url = get_store().presigned_get(art.object_key, ttl, fname, art.media_type)
    if url is None:
        url = f"/v1/artifacts/{art.id}/content?t={sign_download(ctx.tenant_id, art.id, ttl)}&tenant={ctx.tenant_id}"
    return {"url": url, "expires_in": ttl, "content_hash": art.content_hash}


@router.get("/artifacts/{artifact_id}/content", include_in_schema=False)
async def content(artifact_id: uuid.UUID, t: str, tenant: uuid.UUID):
    if not verify_download(tenant, artifact_id, t):
        raise ApiError(403, "invalid_signature", "download link is invalid or expired")
    async with session_scope("app", tenant_id=tenant) as db:
        art = await get_artifact(db, artifact_id)
    headers = {"Content-Disposition": f'attachment; filename="{art.kind}-{art.content_hash[:12]}"',
               "X-Content-Hash": art.content_hash}
    return StreamingResponse(aiter_object(get_store(), art.object_key), media_type=art.media_type, headers=headers)
