"""Helpers shared by feature activities."""

from __future__ import annotations

from datetime import timedelta

from temporalio.exceptions import ApplicationError

from rp_contracts.netpolicy import FetchBlocked

from ..api_client import ApiCallError
from ..fetch.fetcher import FetchFailed
from ..gateway import GatewayError
from ..gateway.providers import ProviderError


def app_error(exc: Exception) -> ApplicationError:
    if isinstance(exc, ApiCallError):
        from ..activities.common import to_app_error

        return to_app_error(exc)
    if isinstance(exc, FetchBlocked):
        return ApplicationError(f"blocked by egress policy: {exc.reason}", {"url": exc.url}, type="fetch_blocked",
                                non_retryable=True)
    if isinstance(exc, FetchFailed):
        return ApplicationError(f"fetch failed: {exc.reason} (status {exc.status})", {"url": exc.url},
                                type="fetch_failed", non_retryable=not exc.retryable,
                                next_retry_delay=timedelta(seconds=exc.retry_after) if exc.retry_after else None)
    if isinstance(exc, (GatewayError, ProviderError)):
        code = getattr(exc, "code", "model_error")
        return ApplicationError(str(exc), type=code, non_retryable=not getattr(exc, "retryable", False))
    return ApplicationError(str(exc), type=type(exc).__name__)


MODEL_UNAVAILABLE = {"provider_not_configured", "model_call_denied", "data_flow_not_permitted", "fixture_missing",
                     "budget_exceeded", "provider_auth_failed", "model_refusal"}


def model_unavailable_reason(exc: Exception) -> str | None:
    """Return a reason when a model pass should be recorded as not_performed instead of failing the task."""
    code = getattr(exc, "code", None)
    if code in MODEL_UNAVAILABLE:
        return f"not_performed: {code}"
    return None
