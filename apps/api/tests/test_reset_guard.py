"""The test-database reset refuses every target except the local throwaway cluster, before touching anything."""

from __future__ import annotations

import pytest

from rp_api import testing
from rp_api.testing import _require_throwaway_target

GOOD_HOST, GOOD_DB = "localhost:5433", "research_platform_test"


def owner_url(host: str, db: str) -> str:
    return f"postgresql+psycopg://rp_owner:rp_owner_dev@{host}/{db}"


@pytest.fixture
def no_side_effects(monkeypatch):
    """Make any connection or migration attempt fail the test loudly, and record whether one happened."""
    import psycopg

    calls: list[str] = []

    def connect(*a, **kw):
        calls.append("connect")
        raise AssertionError(f"psycopg.connect must not be called for a refused target: {a} {kw}")

    def run(*a, **kw):
        calls.append("alembic")
        raise AssertionError(f"alembic must not run for a refused target: {a}")

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(testing.subprocess, "run", run)
    return calls


@pytest.fixture
def target(monkeypatch):
    """Point reset_database at a host/database pair, with a consistent owner URL unless a test overrides it."""
    def _set(host: str, db: str):
        monkeypatch.setattr(testing, "HOST", host)
        monkeypatch.setattr(testing, "TEST_DB", db)
        monkeypatch.setenv("RP_DATABASE_URL_OWNER", owner_url(host, db))
    return _set


def test_guard_accepts_the_throwaway_database(target):
    target(GOOD_HOST, GOOD_DB)
    _require_throwaway_target(GOOD_HOST, owner_url(GOOD_HOST, GOOD_DB))  # must not raise


@pytest.mark.parametrize(("host", "db"), [
    pytest.param(GOOD_HOST, "research_platform", id="non-test-name"),
    pytest.param("ep-cool-name.neon.tech:5433", GOOD_DB, id="remote-host"),
    pytest.param("127.0.0.1:5433", GOOD_DB, id="loopback-ip-is-not-localhost"),
    pytest.param("localhost:5432", GOOD_DB, id="wrong-port"),
    pytest.param("localhost", GOOD_DB, id="missing-port"),
])
def test_reset_refuses_bad_targets_without_connecting(target, no_side_effects, host, db):
    target(host, db)
    with pytest.raises(RuntimeError) as exc:
        testing.reset_database()
    message = str(exc.value)
    assert host in message and db in message, message
    assert no_side_effects == [], "a refused reset must not open a connection or run migrations"


def test_reset_refuses_when_owner_url_names_another_database(target, no_side_effects, monkeypatch):
    """DSN values look right, but RP_DATABASE_URL_OWNER would migrate a different database: refuse both steps."""
    target(GOOD_HOST, GOOD_DB)
    monkeypatch.setenv("RP_DATABASE_URL_OWNER", owner_url(GOOD_HOST, "research_platform"))
    with pytest.raises(RuntimeError) as exc:
        testing.reset_database()
    message = str(exc.value)
    assert "'research_platform'" in message and GOOD_HOST in message, message
    assert no_side_effects == []


def test_reset_refuses_when_owner_url_points_at_a_remote_host(target, no_side_effects, monkeypatch):
    target(GOOD_HOST, GOOD_DB)
    monkeypatch.setenv("RP_DATABASE_URL_OWNER", owner_url("ep-cool-name.neon.tech:5433", GOOD_DB))
    with pytest.raises(RuntimeError) as exc:
        testing.reset_database()
    message = str(exc.value)
    assert "ep-cool-name.neon.tech:5433" in message and GOOD_DB in message, message
    assert no_side_effects == []


def test_reset_refuses_when_owner_url_is_missing(target, no_side_effects, monkeypatch):
    target(GOOD_HOST, GOOD_DB)
    monkeypatch.delenv("RP_DATABASE_URL_OWNER")
    with pytest.raises(RuntimeError) as exc:
        testing.reset_database()
    message = str(exc.value)
    assert GOOD_HOST in message and "RP_DATABASE_URL_OWNER" in message, message
    assert no_side_effects == []


def test_guard_rejects_a_test_database_that_is_not_the_configured_one(target, no_side_effects):
    """A *_test name is not enough: the owner URL has to name the database configure_test_env points the app at."""
    target(GOOD_HOST, GOOD_DB)
    other = "someone_elses_project_test"
    with pytest.raises(RuntimeError) as exc:
        _require_throwaway_target(GOOD_HOST, owner_url(GOOD_HOST, other))
    assert other in str(exc.value) and GOOD_HOST in str(exc.value)
    assert no_side_effects == []


def test_reset_proceeds_only_after_the_guard_passes(target, monkeypatch):
    """With a valid target the reset reaches the connection step; the drop is the first statement it issues."""
    import psycopg

    executed: list[str] = []

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql):
            executed.append(sql)

    connected: list[str] = []
    monkeypatch.setattr(psycopg, "connect", lambda dsn, **kw: connected.append(dsn) or FakeConn())
    monkeypatch.setattr(testing.subprocess, "run",
                        lambda *a, **kw: type("P", (), {"returncode": 0, "stderr": ""})())
    target(GOOD_HOST, GOOD_DB)
    testing.reset_database()
    assert connected == [f"postgresql://rp_owner:rp_owner_dev@{GOOD_HOST}/{GOOD_DB}"]
    assert executed[0].startswith("DROP SCHEMA IF EXISTS public")
