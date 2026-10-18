from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from rp_contracts.copy import RESPONSIBILITY_MESSAGE, RESPONSIBILITY_VERSION

from ..config import get_settings
from ..db.base import utcnow
from ..db.models.core import Membership, Tenant, User
from ..deps import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    REFRESH_COOKIE,
    Ctx,
    client_ip,
    identity_ctx,
    rate_limiter,
    require_admin,
    user_ctx,
)
from ..errors import ApiError, not_found, unprocessable
from ..security.tokens import new_csrf_token
from ..services import identity
from ..services.common import audit

router = APIRouter(prefix="/auth", tags=["auth"])
ws_router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=200)
    workspace_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=256)
    totp_code: str | None = Field(default=None, max_length=12)


class SwitchIn(BaseModel):
    tenant_id: uuid.UUID


class AckIn(BaseModel):
    version: str


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)


def _set_cookies(response: Response, issued: identity.IssuedSession) -> None:
    s = get_settings()
    response.set_cookie(ACCESS_COOKIE, issued.access_token, max_age=issued.expires_in, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    response.set_cookie(REFRESH_COOKIE, issued.refresh_token, max_age=s.refresh_token_ttl_seconds, httponly=True,
                        secure=s.cookie_secure, samesite="strict", path="/v1/auth")
    response.set_cookie(CSRF_COOKIE, new_csrf_token(), max_age=s.refresh_token_ttl_seconds, httponly=False,
                        secure=s.cookie_secure, samesite="strict", path="/")


def _token_body(issued: identity.IssuedSession) -> dict:
    return {
        "access_token": issued.access_token, "token_type": "Bearer", "expires_in": issued.expires_in,
        "user": {"id": str(issued.user.id), "email": issued.user.email, "display_name": issued.user.display_name},
        "tenant_id": str(issued.tenant_id) if issued.tenant_id else None, "tenant_role": issued.tenant_role,
    }


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request, response: Response):
    rate_limiter.check(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    issued = await identity.register(body.email, body.password, body.display_name, body.workspace_name,
                                     request.headers.get("user-agent"), client_ip(request))
    _set_cookies(response, issued)
    return _token_body(issued)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    rate_limiter.check(f"auth:{client_ip(request)}", get_settings().rate_limit_auth_per_minute)
    rate_limiter.check(f"auth-email:{body.email.lower()}", get_settings().rate_limit_auth_per_minute)
    issued = await identity.login(body.email, body.password, body.totp_code, request.headers.get("user-agent"),
                                  client_ip(request))
    _set_cookies(response, issued)
    return _token_body(issued)


@router.post("/refresh")
async def refresh(request: Request, response: Response, body: SwitchIn | None = None):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ApiError(401, "invalid_refresh", "no session")
    issued = await identity.refresh(raw, body.tenant_id if body else None, request.headers.get("user-agent"),
                                    client_ip(request))
    _set_cookies(response, issued)
    return _token_body(issued)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response):
    await identity.logout(request.cookies.get(REFRESH_COOKIE))
    for c, path in ((ACCESS_COOKIE, "/"), (REFRESH_COOKIE, "/v1/auth"), (CSRF_COOKIE, "/")):
        response.delete_cookie(c, path=path)
    response.status_code = 204
    return response


@router.get("/me")
async def me(ctx: Ctx = Depends(identity_ctx)):
    user = (await ctx.db.execute(select(User).where(User.id == ctx.principal.user_id))).scalar_one()
    rows = (await ctx.db.execute(
        select(Membership, Tenant).join(Tenant, Tenant.id == Membership.tenant_id).where(
            Membership.user_id == user.id, Membership.status == "active"))).all()
    return {
        "user": {"id": str(user.id), "email": user.email, "display_name": user.display_name,
                 "mfa_enabled": user.mfa_enabled,
                 "responsibility_acknowledged": user.responsibility_ack_version == RESPONSIBILITY_VERSION,
                 "responsibility_ack_at": user.responsibility_ack_at},
        "session": {"mfa": ctx.principal.mfa, "tenant_id": str(ctx.principal.tenant_id) if ctx.principal.tenant_id else None},
        "workspaces": [{"tenant_id": str(t.id), "name": t.name, "slug": t.slug, "role": m.role} for m, t in rows],
        "responsibility": {"message": RESPONSIBILITY_MESSAGE, "version": RESPONSIBILITY_VERSION},
    }


@router.post("/responsibility-ack")
async def acknowledge(body: AckIn, ctx: Ctx = Depends(identity_ctx)):
    if body.version != RESPONSIBILITY_VERSION:
        raise unprocessable("stale_acknowledgment", "acknowledge the current responsibility message",
                            {"version": RESPONSIBILITY_VERSION, "message": RESPONSIBILITY_MESSAGE})
    user = (await ctx.db.execute(select(User).where(User.id == ctx.principal.user_id))).scalar_one()
    user.responsibility_ack_at = utcnow()
    user.responsibility_ack_version = RESPONSIBILITY_VERSION
    await audit(ctx.db, ctx.principal, "user.responsibility_acknowledged", details={"version": RESPONSIBILITY_VERSION})
    await ctx.db.commit()
    return {"acknowledged": True, "version": RESPONSIBILITY_VERSION}


@router.post("/switch-workspace")
async def switch(body: SwitchIn, request: Request, response: Response, ctx: Ctx = Depends(identity_ctx)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise ApiError(401, "invalid_refresh", "no session")
    issued = await identity.refresh(raw, body.tenant_id, request.headers.get("user-agent"), client_ip(request))
    _set_cookies(response, issued)
    return _token_body(issued)


@router.post("/mfa/setup")
async def mfa_setup(ctx: Ctx = Depends(identity_ctx)):
    secret, uri = await identity.mfa_begin(ctx.principal.user_id)
    return {"secret": secret, "otpauth_uri": uri,
            "note": "Shown once. Scan it in an authenticator app, then confirm with a code."}


@router.post("/mfa/enable")
async def mfa_enable(body: CodeIn, ctx: Ctx = Depends(identity_ctx)):
    await identity.mfa_enable(ctx.principal.user_id, body.code)
    return {"mfa_enabled": True, "note": "Sign in again to obtain an MFA-verified session."}


# --------------------------------------------------------------------------- workspaces
class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class MemberIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(workspace_admin|member)$")


@ws_router.post("", status_code=201)
async def create_workspace(body: WorkspaceIn, ctx: Ctx = Depends(identity_ctx)):
    m = await identity.create_workspace(ctx.principal.user_id, body.name)
    return {"tenant_id": str(m.tenant_id), "role": m.role, "note": "Switch to the new workspace to use it."}


@ws_router.get("/current/members")
async def list_members(ctx: Ctx = Depends(user_ctx)):
    rows = (await ctx.db.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(
        Membership.tenant_id == ctx.tenant_id))).all()
    return [{"user_id": str(u.id), "email": u.email, "display_name": u.display_name, "role": m.role,
             "status": m.status, "mfa_enabled": u.mfa_enabled} for m, u in rows]


@ws_router.post("/current/members", status_code=201)
async def add_member(body: MemberIn, ctx: Ctx = Depends(user_ctx)):
    """Add an existing account to this workspace (admin with MFA only)."""
    require_admin(ctx)
    from ..db.engine import session_scope

    async with session_scope("system") as sys_db:
        user = (await sys_db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if user is None:
        raise not_found("account")
    existing = (await ctx.db.execute(select(Membership).where(Membership.tenant_id == ctx.tenant_id,
                                                              Membership.user_id == user.id))).scalar_one_or_none()
    if existing:
        existing.role = body.role
        existing.status = "active"
    else:
        ctx.db.add(Membership(tenant_id=ctx.tenant_id, user_id=user.id, role=body.role))
    await audit(ctx.db, ctx.principal, "workspace.member_added", resource_type="user", resource_id=user.id,
                details={"role": body.role})
    await ctx.db.commit()
    return {"user_id": str(user.id), "role": body.role}


@ws_router.delete("/current/members/{user_id}", status_code=204)
async def remove_member(user_id: uuid.UUID, ctx: Ctx = Depends(user_ctx)):
    require_admin(ctx)
    m = (await ctx.db.execute(select(Membership).where(Membership.tenant_id == ctx.tenant_id,
                                                       Membership.user_id == user_id))).scalar_one_or_none()
    if m is None:
        raise not_found("member")
    if user_id == ctx.principal.user_id:
        raise unprocessable("cannot_remove_self", "admins cannot remove themselves")
    m.status = "removed"
    await audit(ctx.db, ctx.principal, "workspace.member_removed", resource_type="user", resource_id=user_id)
    await ctx.db.commit()
    return Response(status_code=204)

