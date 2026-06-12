"""Composition root.

The one place that picks a concrete backend and wires it. Everything depends on
this; this depends on everything below it; nothing imports it (except a launcher).

    uvicorn app.main:app --reload

Users and teams are created via the API/CLI, not seeded here — the store is
persistent, so there is nothing to seed on every boot.
"""

from app.shell.database import create_store
from app.shell.http import create_app

# --- choose the backend here (swap this block; no port required) ---
# One concrete `Store` for every entity (users, teams, memberships); the URL
# decides the backend. SQLite by default, file-backed so data persists across
# runs and is shared with the CLI. The schema comes from migrations, not the
# store — run `uv run alembic upgrade head` before first boot.
_store = create_store()
# _store = create_store("postgresql+psycopg://localhost/app")  # needs --extra postgres
# from app.shell.database.memory_store import InMemoryStore
# _store = InMemoryStore()

app = create_app(_store)
