"""Token issuance and verification.

The API includes an OIDC-compatible issuer (discovery + JWKS + RS256 access tokens) so that local and
pilot deployments work without an external IdP; production may instead trust an external OIDC issuer
(RP_EXTERNAL_OIDC_*). Both paths produce the same `Principal`.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from ..config import get_settings


@dataclass
class Principal:
    kind: str  # user | service
    subject: str
    user_id: uuid.UUID | None = None
    tenant_id: uuid.UUID | None = None
    tenant_role: str | None = None
    mfa: bool = False
    service_name: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    token_id: str | None = None
    auth_method: str = "bearer"  # bearer | cookie

    @property
    def actor_id(self) -> str:
        return str(self.user_id) if self.user_id else f"service:{self.service_name}"

    @property
    def actor_type(self) -> str:
        return "user" if self.kind == "user" else "service"


class TokenError(Exception):
    pass


def _load_or_create_key(path: Path) -> rsa.RSAPrivateKey:
    settings = get_settings()
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)  # type: ignore[return-value]
    if settings.is_production:
        raise RuntimeError(f"signing key missing at {path}; provision it through the secrets manager")
    path.parent.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    return key


@lru_cache
def signing_key() -> rsa.RSAPrivateKey:
    return _load_or_create_key(get_settings().signing_key_path)


def key_id() -> str:
    pub = signing_key().public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return hashlib.sha256(pub).hexdigest()[:16]


def _b64(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def jwks() -> dict[str, Any]:
    nums = signing_key().public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "use": "sig", "alg": "RS256", "kid": key_id(), "n": _b64(nums.n), "e": _b64(nums.e)}]}


def issue_access_token(
    user_id: uuid.UUID, tenant_id: uuid.UUID | None, tenant_role: str | None, mfa: bool, email: str
) -> tuple[str, int]:
    s = get_settings()
    now = int(time.time())
    claims = {
        "iss": s.oidc_issuer,
        "aud": s.oidc_audience,
        "sub": str(user_id),
        "email": email,
        "tid": str(tenant_id) if tenant_id else None,
        "trole": tenant_role,
        "amr": ["pwd", "otp"] if mfa else ["pwd"],
        "iat": now,
        "nbf": now,
        "exp": now + s.access_token_ttl_seconds,
        "jti": str(uuid.uuid4()),
        "typ": "access",
    }
    token = jwt.encode(claims, signing_key(), algorithm="RS256", headers={"kid": key_id()})
    return token, s.access_token_ttl_seconds


def issue_service_token(service_name: str, scope: dict[str, Any]) -> tuple[str, int]:
    """Short-lived token for a Temporal worker, scoped to one tenant/project/task."""
    s = get_settings()
    now = int(time.time())
    claims = {
        "iss": s.oidc_issuer,
        "aud": f"{s.oidc_audience}:internal",
        "sub": f"service:{service_name}",
        "svc": service_name,
        "scope": scope,
        "iat": now,
        "exp": now + s.service_token_ttl_seconds,
        "jti": str(uuid.uuid4()),
        "typ": "service",
    }
    return jwt.encode(claims, signing_key(), algorithm="RS256", headers={"kid": key_id()}), s.service_token_ttl_seconds


@lru_cache
def _external_jwk_client() -> jwt.PyJWKClient | None:
    s = get_settings()
    if not s.external_oidc_jwks_url:
        return None
    return jwt.PyJWKClient(s.external_oidc_jwks_url, cache_keys=True)


def decode_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        unverified = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise TokenError("malformed token") from exc
    iss = unverified.get("iss")
    try:
        if iss == s.oidc_issuer and header.get("kid") == key_id():
            typ = unverified.get("typ")
            audience = f"{s.oidc_audience}:internal" if typ == "service" else s.oidc_audience
            return jwt.decode(
                token, signing_key().public_key(), algorithms=["RS256"], audience=audience, issuer=s.oidc_issuer,
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        client = _external_jwk_client()
        if client is not None and iss == s.external_oidc_issuer:
            key = client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token, key.key, algorithms=["RS256", "ES256"], audience=s.external_oidc_audience,
                issuer=s.external_oidc_issuer, options={"require": ["exp", "sub", "iss"]},
            )
            claims["typ"] = "external"
            return claims
    except jwt.PyJWTError as exc:
        raise TokenError(f"invalid token: {exc.__class__.__name__}") from exc
    raise TokenError("untrusted issuer")


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
