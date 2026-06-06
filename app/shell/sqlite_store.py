"""Default persistence: SQLite via the stdlib `sqlite3` (no extra dependency).

This is the store wired in `main.py`. Because it is file-backed, data survives
between process invocations — which is what makes the CLI realistic: you `add` a
user in one invocation and `rename` it in another, exactly like the HTTP API.
(The in-memory store forgets everything when the process exits, so a CLI built
on it has to conjure a user into existence on every run before it can do
anything — the unrealistic crutch this store removes.)

Like every store it is a concrete shell class — not a port the core depends on.
It satisfies the `UserStore` Protocol (app/shell/user_store.py) structurally. Parsing
happens at this boundary (§8); a row we wrote ourselves is assumed valid, so a
malformed one is a panic, not a domain error (§6) — hence `.unwrap()`.

A fresh connection per operation keeps it safe under FastAPI's threadpool
(sqlite3 connections are single-thread by default). One consequence: a
`:memory:` path would give each operation its own empty database — use a file.
"""
import sqlite3
from contextlib import closing

from app.core.user import DisplayName, Email, User, UserId

DEFAULT_DB_PATH = "users.db"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS users ("
    "id TEXT PRIMARY KEY, email TEXT NOT NULL, display_name TEXT NOT NULL)"
)


class SqliteUserStore:
    def __init__(self, path: str = DEFAULT_DB_PATH) -> None:
        self._path = path
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(_SCHEMA)

    def get(self, user_id: UserId) -> User | None:
        with closing(sqlite3.connect(self._path)) as conn:
            row: tuple[str, str, str] | None = conn.execute(
                "SELECT id, email, display_name FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        return User(
            id=UserId(row[0]),
            email=Email.parse(row[1]).unwrap(),
            display_name=DisplayName.parse(row[2]).unwrap(),
        )

    def save(self, user: User) -> None:
        with closing(sqlite3.connect(self._path)) as conn, conn:
            conn.execute(
                "INSERT INTO users (id, email, display_name) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "email = excluded.email, display_name = excluded.display_name",
                (user.id, user.email.value, user.display_name.value),
            )
