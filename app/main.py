"""Composition root.

The one place that picks a concrete backend and wires it. Everything depends on
this; this depends on everything below it; nothing imports it (except a launcher).

    uvicorn app.main:app --reload

Users and teams are created via the API/CLI, not seeded here — the store is
persistent, so there is nothing to seed on every boot.
"""

from app.shell.http import create_app
from app.shell.sqlite_store import SqliteStore

# --- choose the backend here (swap this block; no port required) ---
# One concrete `Store` for every entity (users, teams, memberships); SQLite by
# default, file-backed so data persists across runs and is shared with the CLI.
_store = SqliteStore()
# from app.shell.memory_store import InMemoryStore
# _store = InMemoryStore()
# from sqlalchemy import create_engine
# from app.shell.postgres_store import PostgresStore, create_schema
# _engine = create_engine("postgresql+psycopg://localhost/app")
# create_schema(_engine)  # once — a real app runs migrations instead
# _store = PostgresStore(_engine)

app = create_app(_store)
