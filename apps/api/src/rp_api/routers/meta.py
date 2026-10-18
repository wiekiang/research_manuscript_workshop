from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select, text

from rp_contracts import CONTRACTS_VERSION
from rp_contracts.copy import all_copy
from rp_contracts.state_machine import transition_table

from ..config import get_settings
from ..db.engine import session_scope
from ..db.models.core import ProviderDefinition
from ..security.tokens import jwks

root_router = APIRouter()
router = APIRouter(tags=["meta"])


@root_router.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}


@root_router.get("/readyz", include_in_schema=False)
async def readyz():
    async with session_scope("app") as db:
        await db.execute(text("SELECT 1"))
    return {"status": "ready"}


@root_router.get("/.well-known/openid-configuration", include_in_schema=False)
async def openid_configuration():
    s = get_settings()
    return {
        "issuer": s.oidc_issuer,
        "jwks_uri": f"{s.oidc_issuer}/v1/auth/jwks",
        "token_endpoint": f"{s.oidc_issuer}/v1/auth/login",
        "id_token_signing_alg_values_supported": ["RS256"],
        "subject_types_supported": ["public"],
        "response_types_supported": ["token"],
        "claims_supported": ["sub", "email", "tid", "trole", "amr"],
    }


@router.get("/meta")
async def meta():
    """Contract version, required product copy and the canonical transition table."""
    return {"contracts_version": CONTRACTS_VERSION, "copy": all_copy(), "transitions": transition_table(),
            "environment": get_settings().environment}


@router.get("/providers")
async def providers():
    """Provider rights registry (public metadata only; never credentials)."""
    async with session_scope("app") as db:
        rows = (await db.execute(select(ProviderDefinition).order_by(ProviderDefinition.kind, ProviderDefinition.key))).scalars()
        return [
            {"key": p.key, "display_name": p.display_name, "kind": p.kind, "enabled": p.enabled,
             "gate_status": p.gate_status, "gate_notes": p.gate_notes, "docs_url": p.docs_url, "terms_url": p.terms_url,
             "attribution": p.attribution, "capabilities": p.capabilities,
             "requires_user_connection": p.requires_user_connection, "terms_reviewed_at": p.terms_reviewed_at}
            for p in rows
        ]


@router.get("/auth/jwks", tags=["auth"])
async def get_jwks():
    return jwks()
