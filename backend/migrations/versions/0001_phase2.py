"""Install Phase 1 schema and Phase 2 authentication/control-plane restrictions."""

from pathlib import Path
from alembic import op

revision = "0001_phase2"
down_revision = None


def upgrade():
    root = Path(__file__).resolve().parents[1] / "sql"
    schema = (root / "0001_schema.sql").read_text()
    schema = schema.replace("\nBEGIN;\n", "\n").removesuffix("COMMIT;\n")
    # psycopg executes this migration SQL as a trusted script; not user input.
    op.get_bind().connection.driver_connection.execute(schema)
    op.get_bind().connection.driver_connection.execute((root / "0001_phase2.sql").read_text())


def downgrade():
    raise RuntimeError("Destructive downgrade disabled: restore a verified backup into an isolated database")
