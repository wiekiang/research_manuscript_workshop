"""sandbox execution details on compile runs and experiment runs

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-03 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: str | Sequence[str] | None = '0012'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE_SCOPES = {
}


def upgrade() -> None:
    """Upgrade schema."""
    # The same ExecutionDetails shape (rp_latex.sandbox) on both sandbox-backed records.
    op.add_column('compile_runs', sa.Column('execution', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('experiment_runs', sa.Column('execution', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    # ### RLS, grants and integrity triggers (scripts/finalize_migration.py) ###
    from rp_api.db.rls import policy_sql

    for table, scope in TABLE_SCOPES.items():
        for stmt in policy_sql(table, scope):
            op.execute(stmt)



def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('experiment_runs', 'execution')
    op.drop_column('compile_runs', 'execution')
