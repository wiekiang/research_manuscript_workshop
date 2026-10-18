"""Row-level security, grants and integrity triggers, generated per table scope.

Migrations call `policy_sql(table, scope)` for every table they create so that isolation rules are
part of versioned SQL migrations rather than runtime schema mutation.
"""

from __future__ import annotations

FUNCTIONS_SQL = r"""
CREATE OR REPLACE FUNCTION rp_current_tenant() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION rp_current_user() RETURNS uuid LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION rp_forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN RAISE EXCEPTION 'table % is append-only', TG_TABLE_NAME USING ERRCODE = 'P0001'; END $$;

CREATE OR REPLACE FUNCTION rp_artifact_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
  IF TG_OP = 'DELETE' THEN
    IF current_user <> 'rp_system' THEN
      RAISE EXCEPTION 'artifacts are immutable; only the retention purge may delete' USING ERRCODE = 'P0001';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.object_key IS DISTINCT FROM OLD.object_key
     OR NEW.kind IS DISTINCT FROM OLD.kind OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
     OR NEW.media_type IS DISTINCT FROM OLD.media_type OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.project_id IS DISTINCT FROM OLD.project_id OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'artifact content metadata is immutable' USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION rp_approval_binding_immutable() RETURNS trigger LANGUAGE plpgsql AS
$$ BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'approvals cannot be deleted' USING ERRCODE = 'P0001';
  END IF;
  IF NEW.content_manifest_hash IS DISTINCT FROM OLD.content_manifest_hash
     OR NEW.bound_artifacts IS DISTINCT FROM OLD.bound_artifacts OR NEW.gate IS DISTINCT FROM OLD.gate
     OR NEW.approver_id IS DISTINCT FROM OLD.approver_id OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
     OR NEW.declaration_text IS DISTINCT FROM OLD.declaration_text THEN
    RAISE EXCEPTION 'approval binding is immutable' USING ERRCODE = 'P0001';
  END IF;
  IF OLD.status <> 'valid' AND NEW.status = 'valid' THEN
    RAISE EXCEPTION 'an invalidated approval cannot be revalidated; record a new approval' USING ERRCODE = 'P0001';
  END IF;
  RETURN NEW;
END $$;
"""

TENANT_POLICY = "tenant_id = rp_current_tenant()"


def policy_sql(table: str, scope: str) -> list[str]:
    s: list[str] = []
    if scope == "tenant":
        s += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {table} USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})",
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO rp_app",
            f"GRANT ALL ON {table} TO rp_system",
        ]
    elif scope == "tenant_append_only":
        s += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {table} USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})",
            f"GRANT SELECT, INSERT ON {table} TO rp_app",
            f"GRANT SELECT, INSERT ON {table} TO rp_system",
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION rp_forbid_mutation()",
        ]
    elif scope == "audit":
        s += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_read ON {table} FOR SELECT USING ({TENANT_POLICY})",
            f"CREATE POLICY tenant_insert ON {table} FOR INSERT WITH CHECK "
            f"(tenant_id IS NULL OR {TENANT_POLICY})",
            f"GRANT SELECT, INSERT ON {table} TO rp_app",
            f"GRANT SELECT, INSERT ON {table} TO rp_system",
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION rp_forbid_mutation()",
        ]
    elif scope == "outbox":
        s += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {table} USING ({TENANT_POLICY}) WITH CHECK ({TENANT_POLICY})",
            f"GRANT SELECT, INSERT ON {table} TO rp_app",
            f"GRANT ALL ON {table} TO rp_system",
        ]
    elif scope == "identity":
        if table == "tenants":
            using = (
                "id = rp_current_tenant() OR id IN "
                "(SELECT m.tenant_id FROM memberships m WHERE m.user_id = rp_current_user() AND m.status = 'active')"
            )
        else:  # users
            using = (
                "id = rp_current_user() OR id IN "
                "(SELECT m.user_id FROM memberships m WHERE m.tenant_id = rp_current_tenant())"
            )
        s += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY identity_visibility ON {table} FOR SELECT USING ({using})",
            f"CREATE POLICY identity_self_update ON {table} FOR UPDATE USING ("
            + ("id = rp_current_tenant()" if table == "tenants" else "id = rp_current_user()")
            + ")",
            f"GRANT SELECT, UPDATE ON {table} TO rp_app",
            f"GRANT ALL ON {table} TO rp_system",
        ]
    elif scope == "membership":
        s += [
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY membership_visibility ON {table} FOR SELECT "
            f"USING ({TENANT_POLICY} OR user_id = rp_current_user())",
            f"CREATE POLICY membership_write ON {table} FOR INSERT WITH CHECK ({TENANT_POLICY})",
            f"CREATE POLICY membership_update ON {table} FOR UPDATE USING ({TENANT_POLICY})",
            f"GRANT SELECT, INSERT, UPDATE ON {table} TO rp_app",
            f"GRANT ALL ON {table} TO rp_system",
        ]
    elif scope == "identity_private":
        s += [f"REVOKE ALL ON {table} FROM rp_app", f"GRANT ALL ON {table} TO rp_system"]
    elif scope == "global":
        s += [
            f"GRANT SELECT ON {table} TO rp_app",
            f"GRANT SELECT ON {table} TO rp_system",
            f"GRANT SELECT, INSERT, UPDATE ON {table} TO rp_ingest",
        ]
    else:
        raise ValueError(f"unknown scope {scope} for {table}")
    return s


def table_scope(table) -> str:
    """Resolve the scope of a SQLAlchemy Table from its mapped class marker."""
    return table.info.get("scope", "tenant")
