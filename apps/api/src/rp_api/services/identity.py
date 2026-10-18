"""Identity: registration, password login with lockout, MFA (TOTP), refresh-token rotation and workspaces.

Credential lookups happen before a tenant/user context exists, so this module alone uses the system DB role
for them. All other request handling runs under the RLS-constrained app role.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

import pyotp
from sqlalchemy import select, update

from rp_contracts.enums import TenantRole

from ..config import get_settings
from ..db.base import utcnow
from ..db.engine import session_scope
from ..db.models.core import AuditLog, AuthSession, Membership, Tenant, User
from ..errors import ApiError, conflict, unprocessable
from ..security.passwords import hash_password, needs_rehash, password_problems, verify_password
from ..security.secrets import secrets_service
from ..security.tokens import hash_refresh_token, issue_access_token, new_refresh_token

MAX_FAILED = 10
LOCK_MINUTES = 15


@dataclass
class IssuedSession:
    access_token: str
    expires_in: int
    refresh_token: str
    user: User
    tenant_id: uuid.UUID | None
    tenant_role: str | None


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "workspace"
    return f"{s}-{uuid.uuid4().hex[:6]}"


def _log(db, action: str, actor_id: str, tenant_id=None, details=None, ip=None) -> None:
    db.add(AuditLog(tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action=action, ip=ip,
                    details=details or {}))


async def _default_membership(db, user_id: uuid.UUID, preferred: uuid.UUID | None = None) -> Membership | None:
    rows = list((await db.execute(select(Membership).where(Membership.user_id == user_id,
                                                           Membership.status == "active"))).scalars())
    if preferred:
        for m in rows:
            if m.tenant_id == preferred:
                return m
    return sorted(rows, key=lambda m: m.created_at)[0] if rows else None


async def _issue(db, user: User, membership: Membership | None, mfa: bool, user_agent: str | None,
                 ip: str | None) -> IssuedSession:
    s = get_settings()
    raw, digest = new_refresh_token()
    db.add(AuthSession(user_id=user.id, tenant_id=membership.tenant_id if membership else None,
                       refresh_token_hash=digest, expires_at=utcnow() + timedelta(seconds=s.refresh_token_ttl_seconds),
                       mfa_verified=mfa, user_agent=(user_agent or "")[:400], ip=ip))
    token, ttl = issue_access_token(user.id, membership.tenant_id if membership else None,
                                    membership.role if membership else None, mfa, user.email)
    return IssuedSession(token, ttl, raw, user, membership.tenant_id if membership else None,
                         membership.role if membership else None)


async def register(email: str, password: str, display_name: str, workspace_name: str | None,
                   user_agent: str | None, ip: str | None) -> IssuedSession:
    s = get_settings()
    if not s.allow_self_registration:
        raise ApiError(403, "registration_closed", "self registration is disabled; ask a workspace admin for an invite")
    problems = password_problems(password, s.password_min_length)
    if problems:
        raise unprocessable("weak_password", "password " + "; ".join(problems), {"problems": problems})
    email = email.strip().lower()
    async with session_scope("system") as db:
        if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
            raise conflict("email_taken", "an account with this email already exists")
        user = User(email=email, display_name=display_name.strip()[:200], password_hash=hash_password(password))
        db.add(user)
        await db.flush()
        membership = None
        if workspace_name:
            tenant = Tenant(name=workspace_name.strip()[:200], slug=_slugify(workspace_name))
            db.add(tenant)
            await db.flush()
            membership = Membership(tenant_id=tenant.id, user_id=user.id, role=TenantRole.WORKSPACE_ADMIN)
            db.add(membership)
            _log(db, "workspace.created", str(user.id), tenant.id, {"name": tenant.name}, ip)
        _log(db, "auth.registered", str(user.id), membership.tenant_id if membership else None, {"email": email}, ip)
        issued = await _issue(db, user, membership, False, user_agent, ip)
        await db.commit()
        return issued


async def login(email: str, password: str, totp_code: str | None, user_agent: str | None, ip: str | None) -> IssuedSession:
    email = email.strip().lower()
    async with session_scope("system") as db:
        user = (await db.execute(select(User).where(User.email == email).with_for_update())).scalar_one_or_none()
        now = utcnow()
        if user is not None and user.locked_until and user.locked_until > now:
            raise ApiError(423, "account_locked", "too many failed attempts; try again later")
        ok = verify_password(password, user.password_hash if user else None)
        if not ok or user is None or user.status != "active":
            if user is not None:
                user.failed_login_count += 1
                if user.failed_login_count >= MAX_FAILED:
                    user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                    user.failed_login_count = 0
                _log(db, "auth.login_failed", str(user.id), details={"reason": "bad_credentials"}, ip=ip)
                await db.commit()
            raise ApiError(401, "invalid_credentials", "email or password is incorrect")
        mfa = False
        if user.mfa_enabled:
            if not totp_code:
                raise ApiError(401, "mfa_required", "enter the code from your authenticator app")
            secret = await secrets_service.read(user.mfa_secret_id, "mfa_totp", owner_user_id=user.id)
            if not pyotp.TOTP(secret).verify(totp_code.strip(), valid_window=1):
                user.failed_login_count += 1
                _log(db, "auth.login_failed", str(user.id), details={"reason": "bad_totp"}, ip=ip)
                await db.commit()
                raise ApiError(401, "invalid_mfa_code", "the authentication code is not valid")
            mfa = True
        user.failed_login_count = 0
        user.last_login_at = now
        if needs_rehash(user.password_hash or ""):
            user.password_hash = hash_password(password)
        membership = await _default_membership(db, user.id)
        _log(db, "auth.login", str(user.id), membership.tenant_id if membership else None, {"mfa": mfa}, ip)
        issued = await _issue(db, user, membership, mfa, user_agent, ip)
        await db.commit()
        return issued


async def refresh(raw: str, tenant_id: uuid.UUID | None, user_agent: str | None, ip: str | None) -> IssuedSession:
    digest = hash_refresh_token(raw)
    async with session_scope("system") as db:
        sess = (await db.execute(select(AuthSession).where(AuthSession.refresh_token_hash == digest)
                                 .with_for_update())).scalar_one_or_none()
        now = utcnow()
        if sess is None:
            raise ApiError(401, "invalid_refresh", "session expired; sign in again")
        if sess.revoked_at is not None:
            if sess.rotated_to is not None:
                # Reuse of a rotated token: treat as theft and revoke every session of this user.
                await db.execute(update(AuthSession).where(AuthSession.user_id == sess.user_id,
                                                           AuthSession.revoked_at.is_(None)).values(revoked_at=now))
                _log(db, "auth.refresh_reuse_detected", str(sess.user_id), details={}, ip=ip)
                await db.commit()
            raise ApiError(401, "invalid_refresh", "session expired; sign in again")
        if sess.expires_at < now:
            raise ApiError(401, "invalid_refresh", "session expired; sign in again")
        user = (await db.execute(select(User).where(User.id == sess.user_id))).scalar_one()
        if user.status != "active":
            raise ApiError(401, "invalid_refresh", "account disabled")
        membership = await _default_membership(db, user.id, tenant_id or sess.tenant_id)
        if tenant_id and (membership is None or membership.tenant_id != tenant_id):
            raise ApiError(403, "membership_inactive", "you are not an active member of that workspace")
        issued = await _issue(db, user, membership, sess.mfa_verified, user_agent, ip)
        await db.flush()
        new = (await db.execute(select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_refresh_token(issued.refresh_token)))).scalar_one()
        sess.revoked_at = now
        sess.rotated_to = new.id
        await db.commit()
        return issued


async def logout(raw: str | None) -> None:
    if not raw:
        return
    async with session_scope("system") as db:
        sess = (await db.execute(select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_refresh_token(raw)))).scalar_one_or_none()
        if sess and sess.revoked_at is None:
            sess.revoked_at = utcnow()
            _log(db, "auth.logout", str(sess.user_id))
            await db.commit()


async def create_workspace(user_id: uuid.UUID, name: str) -> Membership:
    async with session_scope("system") as db:
        tenant = Tenant(name=name.strip()[:200], slug=_slugify(name))
        db.add(tenant)
        await db.flush()
        m = Membership(tenant_id=tenant.id, user_id=user_id, role=TenantRole.WORKSPACE_ADMIN)
        db.add(m)
        _log(db, "workspace.created", str(user_id), tenant.id, {"name": tenant.name})
        await db.commit()
        return m


async def mfa_begin(user_id: uuid.UUID) -> tuple[str, str]:
    async with session_scope("system") as db:
        u = (await db.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
        if u.mfa_enabled:
            raise conflict("mfa_already_enabled", "multi-factor authentication is already enabled")
        secret = pyotp.random_base32()
        old = u.mfa_secret_id
        u.mfa_secret_id = await secrets_service.store("mfa_totp_pending", secret, owner_user_id=u.id)
        await db.commit()
        email = u.email
    if old:
        await secrets_service.destroy(old)
    return secret, pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().product_name)


async def mfa_enable(user_id: uuid.UUID, code: str) -> None:
    async with session_scope("system") as db:
        u = (await db.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one()
        if u.mfa_enabled or u.mfa_secret_id is None:
            raise conflict("mfa_not_started", "start MFA setup first")
        try:
            secret = await secrets_service.read(u.mfa_secret_id, "mfa_totp_pending", owner_user_id=user_id)
        except KeyError as exc:
            raise conflict("mfa_not_started", "start MFA setup first") from exc
        if not pyotp.TOTP(secret).verify(code.strip(), valid_window=1):
            raise unprocessable("invalid_mfa_code", "the authentication code is not valid")
        pending = u.mfa_secret_id
        u.mfa_secret_id = await secrets_service.store("mfa_totp", secret, owner_user_id=user_id)
        u.mfa_enabled = True
        _log(db, "auth.mfa_enabled", str(user_id))
        await db.commit()
    await secrets_service.destroy(pending)
