"""API test harness: real PostgreSQL (RLS, grants and triggers exercised as in production), local object store."""

from __future__ import annotations

import os

from rp_api.testing import configure_test_env, reset_database

configure_test_env()

import httpx  # noqa: E402
import pytest  # noqa: E402

from rp_api.testing import (  # noqa: E402,F401
    PASSWORD,
    UserHandle,
    make_project,
    make_task,
    make_user,
    service_token,
)


def pytest_sessionstart(session):  # noqa: ARG001
    if os.environ.get("RP_TEST_SKIP_RESET") != "1":
        reset_database()


@pytest.fixture(scope="session")
async def app():
    from rp_api.main import create_app
    from rp_api.services.registry import ensure_registry

    application = create_app()
    await ensure_registry()
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
async def researcher(client) -> UserHandle:
    return await make_user(client)
