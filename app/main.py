"""Composition root.

The one place that picks concrete implementations and wires them together.
Everything depends on this; this depends on everything below it; nothing imports
it (except a process launcher).

    uvicorn app.main:app --reload

Users are created via `POST /users` (or the CLI `add` command), not seeded here —
the store is persistent, so there is nothing to seed on every boot.
"""
from app.shell.http import create_app
from app.shell.sqlite_store import SqliteUserStore

# --- choose the backend here (swap this block; no port required) ---
# Default: SQLite, file-backed so data persists across runs and is shared with
# the CLI (app/shell/cli.py), which defaults to the same file.
_store = SqliteUserStore()
# from app.shell.memory_store import InMemoryUserStore
# _store = InMemoryUserStore()
# from app.shell.postgres_store import PostgresUserStore
# _store = PostgresUserStore(dsn="postgresql://localhost/app")

app = create_app(_store)
