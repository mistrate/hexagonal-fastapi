"""Alembic environment — runs migrations against the configured database.

The URL comes from `sqlalchemy.url` when set programmatically
(`app.shell.database.run_migrations`, the tests' seam) and falls back to the
app's default SQLite file for plain `uv run alembic upgrade head`.
`target_metadata` is the typed schema in `types.py`, so `alembic revision
--autogenerate` diffs migrations straight against the one schema definition.
"""

from alembic import context

from app.shell.database import DEFAULT_DATABASE_URL
from app.shell.database.sql_store import create_engine_for
from app.shell.database.types import Base

config = context.config
target_metadata = Base.metadata

url = config.get_main_option("sqlalchemy.url") or DEFAULT_DATABASE_URL


def run_migrations_offline() -> None:
    """Emit the SQL to stdout instead of executing it (`alembic upgrade --sql`)."""
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine_for(url)  # same engine setup as the app (FK pragma on SQLite)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
