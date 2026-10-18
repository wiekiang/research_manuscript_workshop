"""Request dependencies: principal resolution, CSRF, tenant-scoped sessions and project authorization."""

from __future__ import annotations

import hmac
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rp_contracts.enums import ProjectRole, TenantRole

from .config import get_settings
from .db.engine import session_scope
from .db.models.core import Membership, Project, ProjectMember, User
from .errors import ApiError, forbidden, not_found, too_many
from .security.tokens import Principal, TokenError, decode_token

ACCESS_COOKIE = "rp_at"
REFRESH_COOKIE = "rp_rt"
CSRF_COOKIE = "rp_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


# --------------------------------------------------------------------------- rate limiting
class RateLimiter:
    """Per-process sliding-window limiter. Deployments with several API replicas may back this with Redis."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 60.0) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            retry = int(window - (now - q[0])) + 1
            raise too_many("too many requests; retry later", retry)
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------- principal
async def _external_user(claims: dict) -> tuple[uuid.UUID, str]:
    """Just-in-time provisioning for users authenticated by a trusted external OIDC issuer."""
    subject = f"{claims['iss']}|{claims['sub']}"
    async with session_scope("system") as db:
        user = (await db.execute(select(User).where(User.external_subject == subject))).scalar_one_or_none()
        if user is None:
            email = (claims.get("email") or f"{claims['sub']}@external.invalid").lower()
            user = User(email=email, display_name=claims.get("name") or email, external_subject=subject)
            db.add(user)
            await db.commit()
        return user.id, user.email


async def get_principal(request: Request) -> Principal:
    auth = request.headers.get("authorization", "")
    token = None
    method = "bearer"
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    elif ACCESS_COOKIE in request.cookies:
        token = request.cookies[ACCESS_COOKIE]
        method = "cookie"
    if not token:
        raise ApiError(401, "unauthenticated", "authentication required")
    try:
        claims = decode_token(token)
    except TokenError as exc:
        raise ApiError(401, "invalid_token", str(exc)) from exc

    if method == "cookie" and request.method in UNSAFE:
        header = request.headers.get(CSRF_HEADER, "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not header or not cookie or not hmac.compare_digest(header, cookie):
            raise ApiError(403, "csrf_failed", "missing or invalid CSRF token")

    typ = claims.get("typ")
    if typ == "service":
        scope = claims.get("scope") or {}
        return Principal(
            kind="service", subject=claims["sub"], service_name=claims.get("svc"),
            tenant_id=uuid.UUID(scope["tenant_id"]) if scope.get("tenant_id") else None,
            scope=scope, token_id=claims.get("jti"), auth_method=method,
        )
    if typ == "external":
        uid, _ = await _external_user(claims)
        tid = request.headers.get("x-tenant-id")
        return Principal(kind="user", subject=str(uid), user_id=uid, tenant_id=uuid.UUID(tid) if tid else None,
                         mfa="mfa" in (claims.get("amr") or []), token_id=claims.get("jti"), auth_method=method)
    if typ != "access":
        raise ApiError(401, "invalid_token", "unsupported token type")
    return Principal(
        kind="user", subject=claims["sub"], user_id=uuid.UUID(claims["sub"]),
        tenant_id=uuid.UUID(claims["tid"]) if claims.get("tid") else None, tenant_role=claims.get("trole"),
        mfa="otp" in (claims.get("amr") or []), token_id=claims.get("jti"), auth_method=method,
    )


@dataclass
class Ctx:
    principal: Principal
    db: AsyncSession
    request: Request

    @property
    def tenant_id(self) -> uuid.UUID:
        assert self.principal.tenant_id is not None
        return self.principal.tenant_id


async def user_ctx(request: Request, principal: Principal = Depends(get_principal)) -> AsyncIterator[Ctx]:
    """Authenticated user with an active workspace membership; DB session is tenant-scoped (RLS)."""
    if principal.kind != "user":
        raise forbidden("user credentials required")
    if principal.tenant_id is None:
        raise ApiError(403, "no_workspace", "select or create a workspace first")
    rate_limiter.check(f"user:{principal.user_id}", get_settings().rate_limit_default_per_minute)
    async with session_scope("app", tenant_id=principal.tenant_id, user_id=principal.user_id) as db:
        m = (
            await db.execute(
                select(Membership).where(
                    Membership.tenant_id == principal.tenant_id, Membership.user_id == principal.user_id
                )
            )
        ).scalar_one_or_none()
        if m is None or m.status != "active":
            raise ApiError(403, "membership_inactive", "you are not an active member of this workspace")
        principal.tenant_role = m.role
        yield Ctx(principal=principal, db=db, request=request)


async def identity_ctx(request: Request, principal: Principal = Depends(get_principal)) -> AsyncIterator[Ctx]:
    """Authenticated user who may not yet belong to a workspace (onboarding)."""
    if principal.kind != "user":
        raise forbidden("user credentials required")
    async with session_scope("app", tenant_id=principal.tenant_id, user_id=principal.user_id) as db:
        yield Ctx(principal=principal, db=db, request=request)


async def service_ctx(request: Request, principal: Principal = Depends(get_principal)) -> AsyncIterator[Ctx]:
    """Temporal worker identity; DB session is scoped to the token's tenant."""
    if principal.kind != "service" or principal.tenant_id is None:
        raise forbidden("service credentials required", code="service_only")
    async with session_scope("app", tenant_id=principal.tenant_id) as db:
        yield Ctx(principal=principal, db=db, request=request)


def require_admin(ctx: Ctx) -> None:
    if ctx.principal.tenant_role != TenantRole.WORKSPACE_ADMIN:
        raise forbidden("workspace admin role required")
    if not ctx.principal.mfa:
        raise ApiError(403, "mfa_required", "workspace administration requires multi-factor authentication")


def require_service_scope(ctx: Ctx, project_id: uuid.UUID | None, operation: str) -> None:
    scope = ctx.principal.scope
    if project_id is not None and scope.get("project_id") not in (None, str(project_id)):
        raise forbidden("service token is not scoped to this project", code="scope_violation")
    ops = scope.get("operations") or []
    if operation not in ops and "*" not in ops:
        raise forbidden(f"service token lacks operation {operation}", code="scope_violation")


# --------------------------------------------------------------------------- project authorization
READ_ROLES = {ProjectRole.OWNER, ProjectRole.COAUTHOR, ProjectRole.REVIEWER}
EDIT_ROLES = {ProjectRole.OWNER, ProjectRole.COAUTHOR}
OWNER_ONLY = {ProjectRole.OWNER}


async def project_for(ctx: Ctx, project_id: uuid.UUID, roles: set[ProjectRole] = READ_ROLES,
                      lock: bool = False, allow_admin_read: bool = False) -> tuple[Project, str]:
    q = select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
    if lock:
        q = q.with_for_update()
    project = (await ctx.db.execute(q)).scalar_one_or_none()
    if project is None:
        raise not_found("project")
    if ctx.principal.kind == "service":
        if ctx.principal.scope.get("project_id") not in (None, str(project_id)):
            raise not_found("project")
        return project, "service_agent"
    member = (
        await ctx.db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id, ProjectMember.user_id == ctx.principal.user_id,
                ProjectMember.removed_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if member is None:
        if allow_admin_read and ctx.principal.tenant_role == TenantRole.WORKSPACE_ADMIN:
            return project, "workspace_admin"
        raise not_found("project")
    if member.role not in {r.value for r in roles}:
        raise forbidden(f"requires project role: {', '.join(sorted(r.value for r in roles))}")
    return project, member.role
