"""Researcher-chosen AI provider: per-project choice between the local Claude CLI login (local installs only), the
owner's own Anthropic API key, or recorded test responses (never in production).

The API key is stored encrypted (SecretsService, owner-scoped) and is released only to a worker holding a service
token scoped to one of the owner's projects that selected it. Calls to any other provider are refused for that project.
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.base import utcnow
from ..db.models.core import DataFlowAttestation, Project, ProviderDefinition
from ..db.models.literature import ProviderConnection
from ..deps import OWNER_ONLY, Ctx, project_for, require_service_scope, service_ctx, user_ctx
from ..errors import not_found, unprocessable
from ..security.secrets import secrets_service
from ..services.common import audit

router = APIRouter(tags=["model-settings"])
SECRET_PURPOSE = "anthropic_api_key"
KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$")
CONNECT_CONSENT = (
    "I am connecting my own Anthropic API key. Calls made for my projects are billed to my Anthropic account and are "
    "governed by my agreement with Anthropic, including its retention settings. The key is stored encrypted and used "
    "only for projects I own that select it; I can disconnect it at any time."
)
LABELS = {"claude_cli": "Claude login on this computer (local CLI)", "anthropic": "My Anthropic API key",
          "fixture": "Recorded test responses (demo only)"}


async def owner_connection(db: AsyncSession, user_id: uuid.UUID) -> ProviderConnection | None:
    return (await db.execute(select(ProviderConnection).where(
        ProviderConnection.user_id == user_id, ProviderConnection.provider == "anthropic",
        ProviderConnection.status == "active").order_by(ProviderConnection.created_at.desc()))).scalars().first()


async def options_for(db: AsyncSession, project: Project) -> list[dict]:
    s = get_settings()
    conn = await owner_connection(db, project.owner_id)
    rows = {p.key: p for p in (await db.execute(select(ProviderDefinition).where(ProviderDefinition.kind == "model"))).scalars()}
    attested = {a.provider_key for a in (await db.execute(select(DataFlowAttestation).where(
        DataFlowAttestation.project_id == project.id, DataFlowAttestation.revoked_at.is_(None)))).scalars()}
    out = []
    for key in ("claude_cli", "anthropic", "fixture"):
        reason = None
        if key == "claude_cli" and s.environment != "local":
            reason = "available only when the platform runs locally on your own computer"
        elif key == "anthropic":
            if conn is None:
                reason = "connect your Anthropic API key in account settings first"
            elif s.is_production and (rows.get(key) is None or rows[key].gate_status != "cleared"):
                reason = "the platform operator has not cleared Anthropic for production use"
        elif key == "fixture" and s.is_production:
            reason = "recorded test responses are never used in production"
        if key in rows and rows[key].gate_status == "blocked":
            reason = rows[key].gate_notes or "blocked"
        out.append({"key": key, "label": LABELS[key], "available": reason is None, "reason": reason,
                    "data_flow_attested": key == "fixture" or key in attested})
    return out


def effective_provider(project: Project, default: str | None = None) -> str | None:
    return project.model_provider or default


# --------------------------------------------------------------------------- account: API key connection
class KeyIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=400)
    consent_accepted: bool
    consent_text: str


def _conn_out(c: ProviderConnection | None) -> dict:
    if c is None:
        return {"connected": False, "consent_text": CONNECT_CONSENT}
    return {"connected": True, "key_hint": (c.quota or {}).get("key_hint"), "connected_at": c.created_at,
            "status": c.status, "consent_text": CONNECT_CONSENT}


@router.get("/me/model-connections")
async def my_connections(ctx: Ctx = Depends(user_ctx)):
    return {"anthropic": _conn_out(await owner_connection(ctx.db, ctx.principal.user_id)),
            "environment": get_settings().environment}


@router.put("/me/model-connections/anthropic")
async def connect_key(body: KeyIn, ctx: Ctx = Depends(user_ctx)):
    if not body.consent_accepted or body.consent_text != CONNECT_CONSENT:
        raise unprocessable("consent_required", "accept the exact connection statement", {"text": CONNECT_CONSENT})
    key = body.api_key.strip()
    if not KEY_RE.match(key):
        raise unprocessable("invalid_key_format", "this does not look like an Anthropic API key (it starts with sk-ant-)")
    old = await owner_connection(ctx.db, ctx.principal.user_id)
    sid = await secrets_service.store(SECRET_PURPOSE, key, tenant_id=ctx.tenant_id, owner_user_id=ctx.principal.user_id)
    c = ProviderConnection(tenant_id=ctx.tenant_id, user_id=ctx.principal.user_id, provider="anthropic",
                           credential_secret_id=sid, scopes=["model.invoke"], consent_text=CONNECT_CONSENT,
                           status="active", quota={"key_hint": f"…{key[-4:]}"})
    ctx.db.add(c)
    if old is not None:
        old.status, old.revoked_at = "revoked", utcnow()
    await audit(ctx.db, ctx.principal, "model_connection.connected", details={"provider": "anthropic", "hint": key[-4:]})
    await ctx.db.commit()
    if old is not None and old.credential_secret_id:
        await secrets_service.destroy(old.credential_secret_id)
    return _conn_out(c)


@router.delete("/me/model-connections/anthropic")
async def disconnect_key(ctx: Ctx = Depends(user_ctx)):
    c = await owner_connection(ctx.db, ctx.principal.user_id)
    if c is None:
        raise not_found("connection")
    c.status, c.revoked_at = "revoked", utcnow()
    await audit(ctx.db, ctx.principal, "model_connection.revoked", details={"provider": "anthropic"})
    await ctx.db.commit()
    if c.credential_secret_id:
        await secrets_service.destroy(c.credential_secret_id)
    return {"connected": False}


# --------------------------------------------------------------------------- project choice
class ChoiceIn(BaseModel):
    provider: str = Field(pattern="^(claude_cli|anthropic|fixture)$")


@router.get("/projects/{project_id}/model-provider")
async def get_choice(project_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    project, role = await project_for(ctx, project_id)
    return {"selected": project.model_provider, "options": await options_for(ctx.db, project),
            "can_change": role == "owner",
            "note": "Each choice still needs the project owner's data-flow approval for that provider."}


@router.put("/projects/{project_id}/model-provider")
async def set_choice(project_id: uuid.UUID, body: ChoiceIn, ctx: Ctx = Depends(user_ctx)):
    project, _ = await project_for(ctx, project_id, OWNER_ONLY)
    opt = next(o for o in await options_for(ctx.db, project) if o["key"] == body.provider)
    if not opt["available"]:
        raise unprocessable("provider_unavailable", opt["reason"])
    project.model_provider = body.provider
    await audit(ctx.db, ctx.principal, "project.model_provider_set", project_id=project_id,
                details={"provider": body.provider})
    await ctx.db.commit()
    return await get_choice(project_id, ctx)


# --------------------------------------------------------------------------- internal (worker)
@router.get("/internal/model-provider")
async def worker_provider(ctx: Ctx = Depends(service_ctx)):
    """Which provider the token's project selected; for 'anthropic', the owner's key (audited, never logged)."""
    pid = ctx.principal.scope.get("project_id")
    if not pid:
        return {"provider": None}
    require_service_scope(ctx, uuid.UUID(pid), "model.invoke")
    project = (await ctx.db.execute(select(Project).where(Project.id == uuid.UUID(pid)))).scalar_one()
    out: dict = {"provider": project.model_provider}
    if project.model_provider == "anthropic":
        conn = await owner_connection(ctx.db, project.owner_id)
        if conn is None or conn.credential_secret_id is None:
            return {"provider": "anthropic", "error": "the project owner's Anthropic key is not connected"}
        out["api_key"] = await secrets_service.read(conn.credential_secret_id, SECRET_PURPOSE, owner_user_id=project.owner_id)
        await audit(ctx.db, ctx.principal, "model_connection.key_released", project_id=project.id,
                    details={"task_id": ctx.principal.scope.get("task_id")})
        await ctx.db.commit()
    return out
