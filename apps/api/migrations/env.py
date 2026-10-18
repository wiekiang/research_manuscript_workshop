"""Alembic environment: migrations run as the owner role; RLS/grants are emitted by each revision."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

from rp_api.config import get_settings
from rp_api.db import models  # noqa: F401  (registers all tables)
from rp_api.db.base import Base

target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get("RP_MIGRATION_URL") or get_settings().database_url_owner.get_secret_value()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
