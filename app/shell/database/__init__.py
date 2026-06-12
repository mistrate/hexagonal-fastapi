"""The persistence package: typed schema, stores, and migrations.

Public surface:

* `create_store(database_url)` — the one factory every delivery mechanism
  (HTTP, CLI) uses to build a production `Store`. It only wires an engine to
  `SqlStore`; it performs **no DDL**.
* `run_migrations(database_url)` — bring a database to the current schema
  (alembic `upgrade head`, programmatically). The schema is owned by the
  migration scripts under `migrations/versions/`, not by the stores. From a
  terminal, `uv run alembic upgrade head` does the same for the default URL.
* `Store` (and the per-entity Protocols) — the contracts, from `stores.py`.

`InMemoryStore` is deliberately not built by `create_store`: it has no URL and
no schema; tests and local wiring construct it directly.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.shell.database.sql_store import SqlStore, create_engine_for
from app.shell.database.stores import MembershipStore, Store, TeamStore, UserStore

DEFAULT_DATABASE_URL = "sqlite:///app.db"

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def create_store(database_url: str = DEFAULT_DATABASE_URL) -> Store:
    """Build the production store for a database URL (SQLite or Postgres —
    the URL decides). Assumes a migrated database; never creates schema."""
    return SqlStore(create_engine_for(database_url))


def run_migrations(database_url: str = DEFAULT_DATABASE_URL) -> None:
    """Apply pending migrations up to head. Idempotent; safe on a fresh or
    already-migrated database. The programmatic twin of
    `uv run alembic upgrade head`, with the URL as the test seam."""
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


__all__ = [
    "DEFAULT_DATABASE_URL",
    "MembershipStore",
    "Store",
    "TeamStore",
    "UserStore",
    "create_store",
    "run_migrations",
]
