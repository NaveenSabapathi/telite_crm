import os
from alembic import context
from sqlalchemy import create_engine

url = os.environ["MIGRATION_DATABASE_URL"]
with create_engine(url).connect() as connection:
    context.configure(connection=connection, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()
