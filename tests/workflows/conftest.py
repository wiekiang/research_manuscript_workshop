"""Workflow orchestration tests: the in-process API (real Postgres) + Temporal's time-skipping test server.

Activities reach the API through an ASGI transport, so the full worker -> API contract is exercised.
"""

from __future__ import annotations

import os

from rp_api.testing import configure_test_env, reset_database

configure_test_env()

import httpx  # noqa: E402
import pytest  # noqa: E402

from rp_api.testing import make_project, make_user  # noqa: E402,F401


def pytest_sessionstart(session):  # noqa: ARG001
    if os.environ.get("RP_TEST_SKIP_RESET") != "1":
        reset_database()


@pytest.fixture(scope="session")
async def app():
    from rp_api.main import create_app
    from rp_api.services.registry import ensure_registry

    application = create_app()
    await ensure_registry()
    from rp_research.api_client import use_transport

    use_transport(httpx.ASGITransport(app=application), "http://testserver")
    yield application
    from rp_api.db.engine import dispose_engines

    await dispose_engines()


@pytest.fixture
async def client(app):
    from rp_api.deps import rate_limiter

    rate_limiter.reset()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def temporal_env():
    """A fresh time-skipping server per test: lingering workflows from other tests cannot block time skipping."""
    from temporalio.testing import WorkflowEnvironment

    env = await WorkflowEnvironment.start_time_skipping()
    yield env
    await env.shutdown()


async def drain_outbox(temporal_env, rounds: int = 3) -> None:
    from rp_api.relay import TemporalDispatcher, drain_once

    d = TemporalDispatcher(temporal_env.client)
    for _ in range(rounds):
        if await drain_once(d) == 0:
            break
