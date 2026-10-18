"""Object storage for immutable, content-addressed artifacts.

Keys:
  tmp/{tenant}/{reservation_id}          private temporary upload (never served)
  cas/{tenant}/{sha256[:2]}/{sha256}     committed content (tenant-scoped content addressing)

Downloads use short-lived signed URLs issued after authorization: S3 presigned GET for the S3 backend,
or an HMAC-signed API URL for the local backend.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import anyio

from .config import get_settings

CHUNK = 1024 * 1024


def temp_key(tenant_id: uuid.UUID, reservation_id: uuid.UUID) -> str:
    return f"tmp/{tenant_id}/{reservation_id}"


def cas_key(tenant_id: uuid.UUID, digest: str) -> str:
    return f"cas/{tenant_id}/{digest[:2]}/{digest}"


@dataclass
class ObjectInfo:
    key: str
    size: int
    last_modified: float


class ObjectStore(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...
    def put_stream(self, key: str, chunks: Iterator[bytes], content_type: str) -> int: ...
    def exists(self, key: str) -> bool: ...
    def iter_chunks(self, key: str) -> Iterator[bytes]: ...
    def get_bytes(self, key: str) -> bytes: ...
    def copy(self, src: str, dst: str) -> None: ...
    def delete(self, key: str) -> None: ...
    def list_prefix(self, prefix: str) -> list[ObjectInfo]: ...
    def presigned_get(self, key: str, ttl: int, filename: str | None, content_type: str) -> str | None: ...


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not p.is_relative_to(self.root):
            raise ValueError("object key escapes storage root")
        return p

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.put_stream(key, iter([data]), content_type)

    def put_stream(self, key: str, chunks: Iterator[bytes], content_type: str) -> int:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".part")
        n = 0
        with open(tmp, "wb") as fh:
            for c in chunks:
                fh.write(c)
                n += len(c)
        os.replace(tmp, p)
        return n

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def iter_chunks(self, key: str) -> Iterator[bytes]:
        with open(self._path(key), "rb") as fh:
            while chunk := fh.read(CHUNK):
                yield chunk

    def get_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def copy(self, src: str, dst: str) -> None:
        d = self._path(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        if not d.exists():
            shutil.copyfile(self._path(src), d)

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def list_prefix(self, prefix: str) -> list[ObjectInfo]:
        base = self._path(prefix)
        if not base.exists():
            return []
        out = []
        for p in base.rglob("*"):
            if p.is_file() and not p.name.endswith(".part"):
                st = p.stat()
                out.append(ObjectInfo(str(p.relative_to(self.root)), st.st_size, st.st_mtime))
        return out

    def presigned_get(self, key: str, ttl: int, filename: str | None, content_type: str) -> str | None:
        return None  # served through the API's signed download route


class S3ObjectStore:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        s = get_settings()
        self.bucket = s.object_store_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key.get_secret_value(),
            aws_secret_access_key=s.s3_secret_key.get_secret_value(),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def put_stream(self, key: str, chunks: Iterator[bytes], content_type: str) -> int:
        data = b"".join(chunks)  # bounded by the per-kind size limit enforced by the caller
        self.put_bytes(key, data, content_type)
        return len(data)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def iter_chunks(self, key: str) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        yield from body.iter_chunks(CHUNK)

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def copy(self, src: str, dst: str) -> None:
        if not self.exists(dst):
            self.client.copy_object(Bucket=self.bucket, Key=dst, CopySource={"Bucket": self.bucket, "Key": src})

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def list_prefix(self, prefix: str) -> list[ObjectInfo]:
        out: list[ObjectInfo] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                out.append(ObjectInfo(obj["Key"], obj["Size"], obj["LastModified"].timestamp()))
        return out

    def presigned_get(self, key: str, ttl: int, filename: str | None, content_type: str) -> str | None:
        params = {"Bucket": self.bucket, "Key": key, "ResponseContentType": content_type}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        return self.client.generate_presigned_url("get_object", Params=params, ExpiresIn=ttl)


_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = S3ObjectStore() if s.object_store_backend == "s3" else LocalObjectStore(s.object_store_local_path)
    return _store


def set_store(store: ObjectStore | None) -> None:
    global _store
    _store = store


def sha256_of_object(store: ObjectStore, key: str) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    for chunk in store.iter_chunks(key):
        h.update(chunk)
        n += len(chunk)
    return h.hexdigest(), n


async def run_sync(fn, *args):
    return await anyio.to_thread.run_sync(lambda: fn(*args))


async def aiter_object(store: ObjectStore, key: str) -> AsyncIterator[bytes]:
    it = store.iter_chunks(key)
    while True:
        chunk = await anyio.to_thread.run_sync(lambda: next(it, None))
        if chunk is None:
            break
        yield chunk


# ----------------------------------------------------------------------------- signed local download URLs
def _sign_key() -> bytes:
    return hashlib.sha256(b"download-url:" + get_settings().master_key.get_secret_value().encode()).digest()


def sign_download(tenant_id: uuid.UUID, artifact_id: uuid.UUID, ttl: int) -> str:
    exp = int(time.time()) + ttl
    msg = f"{tenant_id}:{artifact_id}:{exp}".encode()
    sig = base64.urlsafe_b64encode(hmac.new(_sign_key(), msg, hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{exp}.{sig}"


def verify_download(tenant_id: uuid.UUID, artifact_id: uuid.UUID, token: str) -> bool:
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < time.time():
        return False
    msg = f"{tenant_id}:{artifact_id}:{exp}".encode()
    expected = base64.urlsafe_b64encode(hmac.new(_sign_key(), msg, hashlib.sha256).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(expected, sig)
