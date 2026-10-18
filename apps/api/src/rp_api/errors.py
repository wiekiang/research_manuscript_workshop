"""Stable error codes. Response body: {"error": {"code", "message", "details", "request_id"}}."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers or {}


def not_found(what: str = "resource") -> ApiError:
    # Cross-tenant and missing resources are indistinguishable by design.
    return ApiError(404, "not_found", f"{what} not found")


def forbidden(message: str = "not permitted", code: str = "forbidden") -> ApiError:
    return ApiError(403, code, message)


def conflict(code: str, message: str, details: Any = None) -> ApiError:
    return ApiError(409, code, message, details)


def unprocessable(code: str, message: str, details: Any = None) -> ApiError:
    return ApiError(422, code, message, details)


def too_many(message: str, retry_after: int) -> ApiError:
    return ApiError(429, "rate_limited", message, {"retry_after_seconds": retry_after},
                    headers={"Retry-After": str(retry_after)})
