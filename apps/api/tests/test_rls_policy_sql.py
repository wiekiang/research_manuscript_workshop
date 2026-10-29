"""Every table in ``Base.metadata`` must carry a scope and get the right policy SQL for it.

``Base.__init_subclass__`` (db/base.py) stamps ``table.info["scope"]`` from the class's ``__scope__``;
migrations feed that scope to ``policy_sql`` (db/rls.py). This module asserts, without a database:

* every table has a scope in ``table.info`` (no silent fall-through to a default);
* ``tenant`` / ``tenant_append_only`` / ``outbox`` tables get ENABLE + FORCE RLS, the ``tenant_isolation``
  policy and ``rp_app`` grants, and the append-only variant gets its ``rp_forbid_mutation`` trigger;
* ``audit`` (``audit_log``) gets ENABLE + FORCE RLS, split ``tenant_read`` / ``tenant_insert`` policies
  (insert tolerates a NULL tenant_id), SELECT+INSERT grants and the append-only trigger;
* ``global`` tables get no RLS at all and exactly the global-branch grants.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Table

from rp_api.db import models  # noqa: F401  (imports every model module → fills Base.metadata)
from rp_api.db.base import Base
from rp_api.db.rls import TENANT_POLICY, policy_sql

# Scopes whose tables are tenant-owned: non-null tenant_id and a full tenant_isolation policy.
# "outbox" (outbox_events) qualifies; "audit" does not (nullable tenant_id, split policies).
TENANT_FAMILY = frozenset({"tenant", "tenant_append_only", "outbox"})


def all_tables() -> list[Table]:
    return sorted(Base.metadata.tables.values(), key=lambda t: t.name)


def missing_scope_tables() -> list[str]:
    """Names of tables whose ``info`` dict carries no ``scope`` key (read directly, no default)."""
    return [t.name for t in all_tables() if "scope" not in t.info]


def scope_of(table: Table) -> str:
    if "scope" not in table.info:
        pytest.fail(
            f"table {table.name!r} has no 'scope' in table.info; every mapped class must inherit "
            "Base.__init_subclass__ (db/base.py) or set __scope__ explicitly"
        )
    return table.info["scope"]


def statements_for(table: Table) -> list[str]:
    return policy_sql(table.name, scope_of(table))


# --------------------------------------------------------------------------- guard: no scope-less tables
def test_every_table_declares_a_scope() -> None:
    """Fails with the offending table names if any table reaches policy generation without a scope."""
    missing = missing_scope_tables()
    assert not missing, (
        f"{len(missing)} table(s) in Base.metadata have no 'scope' in table.info and would be skipped "
        f"or defaulted by the RLS helper: {', '.join(missing)}"
    )


@pytest.mark.parametrize("table", all_tables(), ids=lambda t: t.name)
def test_scope_is_known_to_policy_sql(table: Table) -> None:
    scope = scope_of(table)
    try:
        stmts = policy_sql(table.name, scope)
    except ValueError as exc:  # rls.py raises for unknown scopes
        pytest.fail(f"table {table.name!r}: {exc}")
    assert stmts, f"table {table.name!r} (scope {scope!r}) produced no policy SQL"
    assert all(f" {table.name} " in s or s.endswith(f" {table.name}") for s in stmts), (
        f"table {table.name!r}: a generated statement does not reference the table: {stmts}"
    )


# --------------------------------------------------------------------------- tenant family
def _tenant_family_tables() -> list[Table]:
    return [t for t in all_tables() if t.info.get("scope") in TENANT_FAMILY]


@pytest.mark.parametrize("table", _tenant_family_tables(), ids=lambda t: t.name)
def test_tenant_family_has_rls_policy_and_grants(table: Table) -> None:
    name = table.name
    stmts = statements_for(table)

    assert f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY" in stmts, f"{name}: RLS not enabled"
    assert f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY" in stmts, f"{name}: RLS not forced"
    assert (
        f"CREATE POLICY tenant_isolation ON {name} USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})" in stmts
    ), f"{name}: tenant_isolation policy missing or not the USING/WITH CHECK form"

    grants_to_app = [s for s in stmts if s.startswith("GRANT ") and s.endswith(f" ON {name} TO rp_app")]
    assert grants_to_app, f"{name}: no GRANT statement for rp_app"

    # The policy references tenant_id; CREATE POLICY would fail at migration time without the column.
    assert "tenant_id" in table.c, f"{name}: tenant_isolation policy requires a tenant_id column"


@pytest.mark.parametrize(
    "table", [t for t in all_tables() if t.info.get("scope") == "tenant"], ids=lambda t: t.name
)
def test_tenant_grants_are_full_crud_for_app(table: Table) -> None:
    name = table.name
    stmts = statements_for(table)
    assert f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO rp_app" in stmts
    assert f"GRANT ALL ON {name} TO rp_system" in stmts
    assert not any(s.startswith("CREATE TRIGGER") for s in stmts), f"{name}: tenant scope must not add a trigger"


@pytest.mark.parametrize(
    "table", [t for t in all_tables() if t.info.get("scope") == "tenant_append_only"], ids=lambda t: t.name
)
def test_append_only_tables_get_integrity_trigger_and_restricted_grants(table: Table) -> None:
    name = table.name
    stmts = statements_for(table)
    assert (
        f"CREATE TRIGGER {name}_append_only BEFORE UPDATE OR DELETE ON {name} "
        f"FOR EACH ROW EXECUTE FUNCTION rp_forbid_mutation()" in stmts
    ), f"{name}: append-only integrity trigger missing"
    assert f"GRANT SELECT, INSERT ON {name} TO rp_app" in stmts
    assert f"GRANT SELECT, INSERT ON {name} TO rp_system" in stmts
    for s in stmts:
        if s.startswith("GRANT "):
            assert "UPDATE" not in s and "DELETE" not in s and "ALL" not in s.split(" ON ")[0], (
                f"{name}: append-only table grants mutation rights: {s}"
            )


# --------------------------------------------------------------------------- outbox (tenant-owned, system-dispatched)
@pytest.mark.parametrize(
    "table", [t for t in all_tables() if t.info.get("scope") == "outbox"], ids=lambda t: t.name
)
def test_outbox_tables_have_tenant_isolation_and_dispatcher_grants(table: Table) -> None:
    name = table.name
    stmts = statements_for(table)
    assert f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY" in stmts, f"{name}: RLS not enabled"
    assert f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY" in stmts, f"{name}: RLS not forced"
    assert (
        f"CREATE POLICY tenant_isolation ON {name} USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})" in stmts
    ), f"{name}: tenant_isolation policy missing"
    assert f"GRANT SELECT, INSERT ON {name} TO rp_app" in stmts, f"{name}: app role must be insert/select only"
    assert f"GRANT ALL ON {name} TO rp_system" in stmts, f"{name}: dispatcher (rp_system) needs full access"
    assert not any(s.startswith("CREATE TRIGGER") for s in stmts), f"{name}: outbox scope must not add a trigger"
    assert not table.c.tenant_id.nullable, f"{name}: tenant-owned outbox rows must always carry a tenant_id"


# --------------------------------------------------------------------------- audit log
@pytest.mark.parametrize(
    "table", [t for t in all_tables() if t.info.get("scope") == "audit"], ids=lambda t: t.name
)
def test_audit_tables_have_split_policies_grants_and_append_only_trigger(table: Table) -> None:
    name = table.name
    stmts = statements_for(table)

    assert f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY" in stmts, f"{name}: RLS not enabled"
    assert f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY" in stmts, f"{name}: RLS not forced"

    assert f"CREATE POLICY tenant_read ON {name} FOR SELECT USING ({TENANT_POLICY})" in stmts, (
        f"{name}: tenant_read policy missing"
    )
    insert_policy = f"CREATE POLICY tenant_insert ON {name} FOR INSERT WITH CHECK (tenant_id IS NULL OR {TENANT_POLICY})"
    assert insert_policy in stmts, f"{name}: tenant_insert policy missing or does not allow NULL tenant_id"
    assert "tenant_id IS NULL OR" in insert_policy  # identity events (login/registration) have no tenant yet
    assert table.c.tenant_id.nullable, f"{name}: tenant_insert allows NULL but the column is NOT NULL"
    assert not any(s.startswith("CREATE POLICY tenant_isolation") for s in stmts), (
        f"{name}: audit tables use split read/insert policies, not tenant_isolation"
    )

    assert f"GRANT SELECT, INSERT ON {name} TO rp_app" in stmts
    assert f"GRANT SELECT, INSERT ON {name} TO rp_system" in stmts
    for s in stmts:
        if s.startswith("GRANT "):
            assert "UPDATE" not in s and "DELETE" not in s and "ALL" not in s.split(" ON ")[0], (
                f"{name}: audit table grants mutation rights: {s}"
            )

    assert (
        f"CREATE TRIGGER {name}_append_only BEFORE UPDATE OR DELETE ON {name} "
        f"FOR EACH ROW EXECUTE FUNCTION rp_forbid_mutation()" in stmts
    ), f"{name}: append-only integrity trigger missing"


# --------------------------------------------------------------------------- global reference tables
@pytest.mark.parametrize(
    "table", [t for t in all_tables() if t.info.get("scope") == "global"], ids=lambda t: t.name
)
def test_global_tables_have_no_rls_and_exact_global_grants(table: Table) -> None:
    name = table.name
    stmts = statements_for(table)

    assert not any("ROW LEVEL SECURITY" in s for s in stmts), f"{name}: global table must not enable RLS"
    assert not any(s.startswith("CREATE POLICY") for s in stmts), f"{name}: global table must not get a policy"
    assert not any(s.startswith("CREATE TRIGGER") for s in stmts), f"{name}: global table must not get a trigger"
    assert stmts == [
        f"GRANT SELECT ON {name} TO rp_app",
        f"GRANT SELECT ON {name} TO rp_system",
        f"GRANT SELECT, INSERT, UPDATE ON {name} TO rp_ingest",
    ], f"{name}: grants differ from the global branch of policy_sql"
    assert "tenant_id" not in table.c, f"{name}: a global table should not carry tenant_id"


# --------------------------------------------------------------------------- migration wiring
# Each revision under migrations/versions embeds a literal ``TABLE_SCOPES = {...}`` and applies it via
# ``for table, scope in TABLE_SCOPES.items(): for stmt in policy_sql(table, scope): op.execute(stmt)``
# (block appended by scripts/finalize_migration.py). ENABLE/FORCE RLS, GRANTs and the append-only trigger
# are all emitted by policy_sql, so a table is RLS-wired iff it appears in some revision's TABLE_SCOPES
# *and* that revision contains the policy_sql loop.
import ast
import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"
POLICY_LOOP = re.compile(
    r"for table, scope in TABLE_SCOPES\.items\(\):\s*\n\s*for stmt in policy_sql\(table, scope\):\s*\n\s*op\.execute\(stmt\)"
)


def migration_table_scopes() -> dict[str, tuple[str, str]]:
    """table name -> (scope literal, revision filename) for every table a revision passes to policy_sql."""
    wired: dict[str, tuple[str, str]] = {}
    files = sorted(MIGRATIONS_DIR.glob("*.py"))
    assert files, f"no migration files found under {MIGRATIONS_DIR}"
    for path in files:
        src = path.read_text()
        tree = ast.parse(src, filename=str(path))
        literal: dict[str, str] | None = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "TABLE_SCOPES" for t in node.targets
            ):
                literal = ast.literal_eval(node.value)
        assert literal is not None, f"{path.name}: no module-level TABLE_SCOPES literal"
        assert POLICY_LOOP.search(src), (
            f"{path.name}: TABLE_SCOPES is declared but the policy_sql loop that applies it is missing"
        )
        for table, scope in literal.items():
            assert table not in wired, f"{table!r} appears in both {wired[table][1]} and {path.name}"
            wired[table] = (scope, path.name)
    return wired


def test_every_tenant_family_table_is_wired_into_a_migration() -> None:
    wired = migration_table_scopes()
    expected = {t.name: t.info.get("scope") for t in all_tables() if t.info.get("scope") in TENANT_FAMILY}

    missing = sorted(name for name in expected if name not in wired)
    assert not missing, (
        f"{len(missing)} tenant-family table(s) exist in Base.metadata but no migration passes them to "
        f"policy_sql, so they would get no RLS, policy, grants or triggers: {', '.join(missing)}"
    )

    mismatched = sorted(
        f"{name}: metadata={expected[name]!r} migration={wired[name][0]!r} ({wired[name][1]})"
        for name in expected
        if wired[name][0] != expected[name]
    )
    assert not mismatched, "scope literal in migration disagrees with the model:\n  " + "\n  ".join(mismatched)


def test_every_metadata_table_is_wired_into_a_migration() -> None:
    """Broader guard: global and identity/ops tables must also reach policy_sql (for their grants)."""
    wired = migration_table_scopes()
    missing = sorted(t.name for t in all_tables() if t.name not in wired)
    assert not missing, f"table(s) in Base.metadata never passed to policy_sql by any migration: {', '.join(missing)}"
    stale = sorted(name for name in wired if name not in Base.metadata.tables)
    assert not stale, f"migration TABLE_SCOPES names table(s) that no longer exist in Base.metadata: {', '.join(stale)}"
