"""Add operational evidence storage and configuration without rewriting frozen DDL."""

from pathlib import Path
from alembic import op

revision = "0003_phase3_operations"
down_revision = "0002_rate_retention"


def upgrade():
    sql = Path(__file__).resolve().parents[1] / "sql" / "0003_phase3_operations.sql"
    op.get_bind().connection.driver_connection.execute(sql.read_text())


def downgrade():
    raise RuntimeError("Evidence-preserving forward migration required")
