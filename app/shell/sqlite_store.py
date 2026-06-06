"""Default persistence: SQLite via the stdlib `sqlite3` (no extra dependency).

One class, one database file, **three tables** (users, teams, memberships) with
foreign keys and a composite primary key on memberships — the shape a real
project's relational store has. It implements the full `Store` (every entity);
the core depends on none of it.

This is where "multiple tables" shows up concretely:

* schema creation lists every table in one place (`_SCHEMA`);
* `save_membership` upserts on the composite `(user_id, team_id)` key;
* `list_memberships_for_user` is a filtered query returning many rows;
* foreign keys declare that a membership references a real user and team.

A fresh connection per operation keeps it safe under FastAPI's threadpool. The
trade-off, and a genuine scaling concern: each operation is its own
transaction, so a shell flow that reads-then-writes across operations (e.g.
"add member" = check-then-insert) is not atomic. A real system that needs that
atomicity would pass a transaction/session down instead of a connection-per-op
store. Parsing happens at this boundary (§8); our own rows are assumed valid, so
a malformed one is a panic — hence `.unwrap()`.
"""

import sqlite3
from contextlib import closing

from app.core.membership import Membership, MembershipRole
from app.core.team import Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId

DEFAULT_DB_PATH = "app.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
    user_id TEXT NOT NULL REFERENCES users(id),
    team_id TEXT NOT NULL REFERENCES teams(id),
    role TEXT NOT NULL,
    PRIMARY KEY (user_id, team_id)
);
"""


class SqliteStore:
    def __init__(self, path: str = DEFAULT_DB_PATH) -> None:
        self._path = path
        with closing(self._connect()) as conn, conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # --- users ---

    def get_user(self, user_id: UserId) -> User | None:
        with closing(self._connect()) as conn:
            row: tuple[str, str, str] | None = conn.execute(
                "SELECT id, email, display_name FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        return User(
            id=UserId(row[0]),
            email=Email.parse(row[1]).unwrap(),
            display_name=DisplayName.parse(row[2]).unwrap(),
        )

    def save_user(self, user: User) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO users (id, email, display_name) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET email = excluded.email, "
                "display_name = excluded.display_name",
                (user.id, user.email.value, user.display_name.value),
            )

    # --- teams ---

    def get_team(self, team_id: TeamId) -> Team | None:
        with closing(self._connect()) as conn:
            row: tuple[str, str] | None = conn.execute(
                "SELECT id, name FROM teams WHERE id = ?", (team_id,)
            ).fetchone()
        if row is None:
            return None
        return Team(id=TeamId(row[0]), name=TeamName.parse(row[1]).unwrap())

    def save_team(self, team: Team) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO teams (id, name) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
                (team.id, team.name.value),
            )

    # --- memberships ---

    def get_membership(self, user_id: UserId, team_id: TeamId) -> Membership | None:
        with closing(self._connect()) as conn:
            row: tuple[str, str, str] | None = conn.execute(
                "SELECT user_id, team_id, role FROM memberships WHERE user_id = ? AND team_id = ?",
                (user_id, team_id),
            ).fetchone()
        if row is None:
            return None
        return _row_to_membership(row)

    def save_membership(self, membership: Membership) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, team_id) DO UPDATE SET role = excluded.role",
                (membership.user_id, membership.team_id, membership.role.value),
            )

    def delete_membership(self, user_id: UserId, team_id: TeamId) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "DELETE FROM memberships WHERE user_id = ? AND team_id = ?", (user_id, team_id)
            )

    def list_memberships_for_user(self, user_id: UserId) -> tuple[Membership, ...]:
        with closing(self._connect()) as conn:
            rows: list[tuple[str, str, str]] = conn.execute(
                "SELECT user_id, team_id, role FROM memberships WHERE user_id = ?", (user_id,)
            ).fetchall()
        return tuple(_row_to_membership(row) for row in rows)

    def list_memberships_for_team(self, team_id: TeamId) -> tuple[Membership, ...]:
        with closing(self._connect()) as conn:
            rows: list[tuple[str, str, str]] = conn.execute(
                "SELECT user_id, team_id, role FROM memberships WHERE team_id = ?", (team_id,)
            ).fetchall()
        return tuple(_row_to_membership(row) for row in rows)


def _row_to_membership(row: tuple[str, str, str]) -> Membership:
    return Membership(
        user_id=UserId(row[0]),
        team_id=TeamId(row[1]),
        role=MembershipRole.parse(row[2]).unwrap(),
    )
