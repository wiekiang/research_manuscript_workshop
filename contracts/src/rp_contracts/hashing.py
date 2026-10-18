"""Canonical hashing used for content manifests, artifact identity and approval binding.

All hashes are lowercase hex SHA-256. Canonical JSON: UTF-8, sorted keys, no insignificant
whitespace, no NaN/Infinity. The same function must be used everywhere a hash is compared.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


def _default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed in hashed content")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"unhashable type for canonical JSON: {type(value).__name__}")


def canonical_json(obj: Any) -> bytes:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=_default
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(obj: Any) -> str:
    return sha256_hex(canonical_json(obj))


def manifest_hash(entries: Iterable[tuple[str, str]]) -> str:
    """Hash of a manifest of (name, content_hash) pairs, independent of order."""
    return content_hash(sorted({name: digest for name, digest in entries}.items()))


def is_sha256_hex(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)
