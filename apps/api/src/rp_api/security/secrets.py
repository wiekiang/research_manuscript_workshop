"""Secrets manager facade.

Local backend: AES-256-GCM envelope encryption with a key-encryption key supplied by the deployment
(RP_MASTER_KEY, base64). Ciphertext lives in `secret_records`, readable only by the system DB role.
Plaintext is never returned through any HTTP endpoint and is never logged. Production deployments can
swap this for a cloud secrets manager behind the same interface.
"""

from __future__ import annotations

import base64
import os
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select

from ..config import get_settings
from ..db.base import utcnow
from ..db.engine import session_scope
from ..db.models.core import SecretRecord

KEY_VERSION = 1
_DEV_KEY = "ZGV2LW9ubHktbWFzdGVyLWtleS0zMi1ieXRlcy0hISE="


def _kek() -> bytes:
    s = get_settings()
    raw = s.master_key.get_secret_value()
    if s.is_production and raw == _DEV_KEY:
        raise RuntimeError("refusing to use the development master key outside local/test")
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("RP_MASTER_KEY must be 32 bytes, base64 encoded")
    return key


def _aad(record_id: uuid.UUID, purpose: str) -> bytes:
    return f"{record_id}:{purpose}".encode()


class SecretsService:
    async def store(
        self, purpose: str, plaintext: str, tenant_id: uuid.UUID | None = None, owner_user_id: uuid.UUID | None = None
    ) -> uuid.UUID:
        rid = uuid.uuid4()
        nonce = os.urandom(12)
        ct = AESGCM(_kek()).encrypt(nonce, plaintext.encode(), _aad(rid, purpose))
        async with session_scope("system") as db:
            db.add(SecretRecord(id=rid, tenant_id=tenant_id, owner_user_id=owner_user_id, purpose=purpose,
                                key_version=KEY_VERSION, nonce=nonce, ciphertext=ct))
            await db.commit()
        return rid

    async def read(self, secret_id: uuid.UUID, purpose: str, owner_user_id: uuid.UUID | None = None) -> str:
        async with session_scope("system") as db:
            rec = (await db.execute(select(SecretRecord).where(SecretRecord.id == secret_id))).scalar_one_or_none()
        if rec is None or rec.destroyed_at is not None or rec.purpose != purpose:
            raise KeyError("secret not found")
        if owner_user_id is not None and rec.owner_user_id != owner_user_id:
            raise PermissionError("secret is owned by another user")
        return AESGCM(_kek()).decrypt(rec.nonce, rec.ciphertext, _aad(rec.id, rec.purpose)).decode()

    async def destroy(self, secret_id: uuid.UUID) -> None:
        async with session_scope("system") as db:
            rec = (await db.execute(select(SecretRecord).where(SecretRecord.id == secret_id))).scalar_one_or_none()
            if rec is not None and rec.destroyed_at is None:
                rec.destroyed_at = utcnow()
                rec.ciphertext = b""
                rec.nonce = b""
                await db.commit()


secrets_service = SecretsService()
