"""Worker -> API client. Workers never touch the database: every state change, artifact commit, model call
authorization and usage record goes through the API's internal routes with a task-scoped service token."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from rp_contracts.hashing import canonical_json

from .config import get_worker_settings


class ApiCallError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details

    @property
    def retryable(self) -> bool:
        return self.status >= 500 or self.status == 429


@dataclass
class Committed:
    artifact_id: str
    content_hash: str
    created: bool


# Tests inject an ASGI transport so activities talk to the in-process API.
_transport: httpx.AsyncBaseTransport | None = None
_base_url_override: str | None = None


def use_transport(transport: httpx.AsyncBaseTransport | None, base_url: str | None = None) -> None:
    global _transport, _base_url_override
    _transport = transport
    _base_url_override = base_url


class ApiClient:
    def __init__(self, task_id: str | None = None, purpose: str = "task", project_id: str | None = None):
        s = get_worker_settings()
        self.task_id = task_id
        self.purpose = purpose
        self.project_id = project_id
        self.base = _base_url_override or s.api_base_url
        self._token: str | None = None
        self._exp = 0.0
        self._client = httpx.AsyncClient(base_url=self.base, transport=_transport, timeout=60.0)

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def _auth(self) -> dict[str, str]:
        if self._token is None or time.time() > self._exp - 30:
            s = get_worker_settings()
            body = {"client_id": s.client_id, "client_secret": s.client_secret.get_secret_value(), "purpose": self.purpose}
            if self.task_id:
                body["task_id"] = self.task_id
            if self.project_id:
                body["project_id"] = self.project_id
            r = await self._client.post("/v1/internal/auth/token", json=body)
            self._raise(r)
            data = r.json()
            self._token = data["access_token"]
            self._exp = time.time() + data["expires_in"]
        return {"Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _raise(r: httpx.Response) -> None:
        if r.status_code >= 400:
            try:
                err = r.json().get("error", {})
            except ValueError:
                err = {}
            raise ApiCallError(r.status_code, err.get("code", "http_error"), err.get("message", r.text[:300]),
                               err.get("details"))

    async def request(self, method: str, path: str, raw: bool = False, **kw) -> Any:
        headers = {**(await self._auth()), **kw.pop("headers", {})}
        r = await self._client.request(method, path, headers=headers, **kw)
        self._raise(r)
        if not raw and r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return r.content

    # ------------------------------------------------------------------ tasks / project
    async def get_task(self) -> dict:
        return await self.request("GET", f"/v1/internal/tasks/{self.task_id}")

    async def update_task(self, state: str, **fields) -> dict:
        return await self.request("PATCH", f"/v1/internal/tasks/{self.task_id}", json={"state": state, **fields})

    async def project(self, project_id: str) -> dict:
        return await self.request("GET", f"/v1/internal/projects/{project_id}")

    async def transition(self, project_id: str, requested_state: str, expected_version: int, idempotency_key: str,
                         **fields) -> dict:
        return await self.request("POST", f"/v1/internal/projects/{project_id}/transitions", json={
            "requested_state": requested_state, "expected_project_version": expected_version,
            "idempotency_key": idempotency_key, **fields})

    # ------------------------------------------------------------------ artifacts
    async def publish(self, project_id: str | None, kind: str, data: bytes, media_type: str, input_manifest_hash: str,
                      *, slot: str = "0", label: str | None = None, depends_on: list[str] | None = None,
                      metadata: dict | None = None, classification: str | None = None,
                      dependency_kind: str = "derived_from") -> Committed:
        """Reserve (deterministic key) -> upload -> commit. Safe to repeat after a crash at any point."""
        digest = hashlib.sha256(data).hexdigest()
        res = await self.request("POST", "/v1/internal/artifacts/reservations", json={
            "project_id": project_id, "task_id": self.task_id, "input_manifest_hash": input_manifest_hash,
            "output_kind": kind, "media_type": media_type, "slot": slot, "label": label,
            "classification": classification})
        if res.get("artifact_id"):
            meta = await self.request("GET", f"/v1/internal/artifacts/{res['artifact_id']}")
            if meta["content_hash"] != digest:
                raise ApiCallError(409, "artifact_hash_conflict",
                                   "this reservation key was committed with different bytes; investigate", res)
            return Committed(res["artifact_id"], digest, False)
        await self.request("PUT", res["upload_url"], content=data, headers={"Content-Type": "application/octet-stream"})
        out = await self.request("POST", f"/v1/internal/artifacts/{res['reservation_id']}/commit", json={
            "content_hash": digest, "size_bytes": len(data), "depends_on": depends_on or [],
            "dependency_kind": dependency_kind, "metadata": metadata or {}})
        return Committed(out["artifact_id"], out["content_hash"], out["created"])

    async def publish_json(self, project_id: str | None, kind: str, obj: Any, input_manifest_hash: str, **kw) -> Committed:
        return await self.publish(project_id, kind, canonical_json(obj), "application/json", input_manifest_hash, **kw)

    async def read_artifact(self, artifact_id: str) -> bytes:
        return await self.request("GET", f"/v1/internal/artifacts/{artifact_id}/content")

    async def read_artifact_bytes(self, artifact_id: str) -> bytes:
        """Exact stored bytes (for hashing/packaging), never parsed."""
        return await self.request("GET", f"/v1/internal/artifacts/{artifact_id}/content", raw=True)

    async def read_json(self, artifact_id: str) -> Any:
        data = await self.read_artifact(artifact_id)
        return json.loads(data) if isinstance(data, (bytes, str)) else data

    async def artifact_meta(self, artifact_id: str) -> dict:
        return await self.request("GET", f"/v1/internal/artifacts/{artifact_id}")

    # ------------------------------------------------------------------ model gateway / usage
    async def authorize_model(self, **body) -> dict:
        return await self.request("POST", "/v1/internal/model-invocations/authorize", json=body)

    async def complete_model(self, invocation_id: str, **body) -> dict:
        return await self.request("POST", f"/v1/internal/model-invocations/{invocation_id}/complete", json=body)

    async def record_usage(self, **body) -> dict:
        return await self.request("POST", "/v1/internal/usage", json=body)

    async def post(self, path: str, body: Any) -> Any:
        return await self.request("POST", path, json=body)

    async def get(self, path: str, **params) -> Any:
        return await self.request("GET", path, params=params or None)


def new_key(prefix: str) -> str:
    return f"{prefix}:{uuid.uuid4()}"
