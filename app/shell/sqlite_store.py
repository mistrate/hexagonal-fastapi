"""Default persistence: SQLite via the stdlib `sqlite3` (no extra dependency).

One class, one database file, **three tables** (users, teams, memberships) with
foreign keys and a composite primary key on memberships — the shape a real
project's relational store has. It implements the full `Store`; the core depends
on none of it.

It runs in one of two modes:

* connection-per-op (the default): each operation opens its own connection and
  commits — safe under FastAPI's threadpool.
* bound to a single connection (inside `unit_of_work`): operations share one
  connection and one transaction, so a multi-step shell operation commits or
  rolls back as a whole. This is what makes the delete cascade and team-founding
  atomic — a connection error mid-way leaves nothing half-written.

Parsing happens at this boundary (§8); our own rows are assumed valid, so a
malformed one is a panic — hence `.unwrap()`.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager

from app.core.membership import Membership, MembershipRole
from app.core.team import Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId
from app.shell.stores import Store

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
    def __init__(
        self, path: str = DEFAULT_DB_PATH, *, _connection: sqlite3.Connection | None = None
    ) -> None:
        self._path = path
        self._connection = _connection
        if _connection is None:  # owns the database file → ensure the schema exists
            with closing(self._connect()) as conn, conn:
                conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        if self._connection is not None:  # inside a unit of work — the UoW owns commit/rollback
            yield self._connection
        else:
            with closing(self._connect()) as conn, conn:  # connection-per-op, own transaction
                yield conn

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        if self._connection is not None:
            yield self._connection
        else:
            with closing(self._connect()) as conn:
                yield conn

    @contextmanager
    def unit_of_work(self) -> Iterator[Store]:
        if self._connection is not None:  # nested → group the inner work as a savepoint
            self._connection.execute("SAVEPOINT uow")
            try:
                yield SqliteStore(self._path, _connection=self._connection)
            except BaseException:
                self._connection.execute("ROLLBACK TO uow")
                raise
            else:
                self._connection.execute("RELEASE uow")
            return
        conn = self._connect()
        try:
            with conn:  # one transaction: commit on success, roll back on any exception
                yield SqliteStore(self._path, _connection=conn)
        finally:
            conn.close()

    # --- users ---

    def get_user(self, user_id: UserId) -> User | None:
        with self._read() as conn:
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
        with self._write() as conn:
            conn.execute(
                "INSERT INTO users (id, email, display_name) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET email = excluded.email, "
                "display_name = excluded.display_name",
                (user.id, user.email.value, user.display_name.value),
            )

    def delete_user(self, user_id: UserId) -> None:
        with self._write() as conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # --- teams ---

    def get_team(self, team_id: TeamId) -> Team | None:
        with self._read() as conn:
            row: tuple[str, str] | None = conn.execute(
                "SELECT id, name FROM teams WHERE id = ?", (team_id,)
            ).fetchone()
        if row is None:
            return None
        return Team(id=TeamId(row[0]), name=TeamName.parse(row[1]).unwrap())

    def save_team(self, team: Team) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO teams (id, name) VALUES (?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
                (team.id, team.name.value),
            )

    # --- memberships ---

    def get_membership(self, user_id: UserId, team_id: TeamId) -> Membership | None:
        with self._read() as conn:
            row: tuple[str, str, str] | None = conn.execute(
                "SELECT user_id, team_id, role FROM memberships WHERE user_id = ? AND team_id = ?",
                (user_id, team_id),
            ).fetchone()
        return None if row is None else _row_to_membership(row)

    def save_membership(self, membership: Membership) -> None:
        with self._write() as conn:
            conn.execute(
                "INSERT INTO memberships (user_id, team_id, role) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id, team_id) DO UPDATE SET role = excluded.role",
                (membership.user_id, membership.team_id, membership.role.value),
            )

    def delete_membership(self, user_id: UserId, team_id: TeamId) -> None:
        with self._write() as conn:
            conn.execute(
                "DELETE FROM memberships WHERE user_id = ? AND team_id = ?", (user_id, team_id)
            )

    def list_memberships_for_user(self, user_id: UserId) -> tuple[Membership, ...]:
        with self._read() as conn:
            rows: list[tuple[str, str, str]] = conn.execute(
                "SELECT user_id, team_id, role FROM memberships WHERE user_id = ?", (user_id,)
            ).fetchall()
        return tuple(_row_to_membership(row) for row in rows)

    def list_memberships_for_team(self, team_id: TeamId) -> tuple[Membership, ...]:
        with self._read() as conn:
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
