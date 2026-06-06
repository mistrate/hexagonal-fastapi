"""A third backend (optional; needs the `postgres` extra).

Implementing the full `Store` here too is the N×M tax of keeping multiple
backends — every method in `stores.py` reappears. That cost is exactly why §2
says to keep a store `Protocol` only when you genuinely have multiple production
implementations.

It accepts a SQLAlchemy **connectable** — an `Engine` or a `Connection`:

* Given an `Engine` (production), each operation opens its own connection and
  runs in its own transaction — connection-per-op, safe under FastAPI's
  threadpool.
* Given a `Connection` (integration tests), each write runs in a SAVEPOINT
  (`begin_nested`) on that one connection. A test wraps everything in an outer
  transaction and rolls it back for fast, schema-preserving isolation. So
  `create_schema` is deliberately separate from construction: the suite runs it
  once, committed, before any test transaction.

Parsing happens at this boundary (§8); our own rows are assumed valid, so a
malformed one is a panic — hence `.unwrap()`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, Engine, text

from app.core.membership import Membership, MembershipRole
from app.core.team import Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId
from app.shell.stores import Store

_SCHEMA: tuple[str, ...] = (
    "CREATE TABLE IF NOT EXISTS users "
    "(id TEXT PRIMARY KEY, email TEXT NOT NULL, display_name TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS memberships ("
    "user_id TEXT NOT NULL REFERENCES users(id), "
    "team_id TEXT NOT NULL REFERENCES teams(id), "
    "role TEXT NOT NULL, PRIMARY KEY (user_id, team_id))",
)


def create_schema(connectable: Engine | Connection) -> None:
    """Create the tables once (a real app would use migrations). Kept out of the
    store so integration tests run it a single time, committed, then wrap each
    test in a transaction they roll back."""
    if isinstance(connectable, Engine):
        with connectable.begin() as conn:
            for statement in _SCHEMA:
                conn.execute(text(statement))
    else:
        for statement in _SCHEMA:
            connectable.execute(text(statement))


class PostgresStore:
    def __init__(self, connectable: Engine | Connection) -> None:
        self._connectable = connectable

    @contextmanager
    def _write(self) -> Iterator[Connection]:
        if isinstance(self._connectable, Engine):
            with self._connectable.begin() as conn:  # new connection, real transaction
                yield conn
        else:
            with self._connectable.begin_nested():  # savepoint on the caller's connection
                yield self._connectable

    @contextmanager
    def _read(self) -> Iterator[Connection]:
        if isinstance(self._connectable, Engine):
            with self._connectable.connect() as conn:
                yield conn
        else:
            yield self._connectable

    @contextmanager
    def unit_of_work(self) -> Iterator[Store]:
        if isinstance(self._connectable, Engine):
            with self._connectable.connect() as conn, conn.begin():
                # one transaction for the block; each op is a savepoint within it,
                # so a failure rolls the whole thing back.
                yield PostgresStore(conn)
        else:
            with self._connectable.begin_nested():  # already in a transaction → savepoint
                yield PostgresStore(self._connectable)

    # --- users ---

    def get_user(self, user_id: UserId) -> User | None:
        with self._read() as conn:
            row = conn.execute(
                text("SELECT id, email, display_name FROM users WHERE id = :id"),
                {"id": user_id},
            ).fetchone()
        if row is None:
            return None
        return User(
            id=UserId(row.id),
            email=Email.parse(row.email).unwrap(),
            display_name=DisplayName.parse(row.display_name).unwrap(),
        )

    def save_user(self, user: User) -> None:
        with self._write() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, display_name) "
                    "VALUES (:id, :email, :name) ON CONFLICT (id) DO UPDATE "
                    "SET email = excluded.email, display_name = excluded.display_name"
                ),
                {"id": user.id, "email": user.email.value, "name": user.display_name.value},
            )

    def delete_user(self, user_id: UserId) -> None:
        with self._write() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

    # --- teams ---

    def get_team(self, team_id: TeamId) -> Team | None:
        with self._read() as conn:
            row = conn.execute(
                text("SELECT id, name FROM teams WHERE id = :id"), {"id": team_id}
            ).fetchone()
        if row is None:
            return None
        return Team(id=TeamId(row.id), name=TeamName.parse(row.name).unwrap())

    def save_team(self, team: Team) -> None:
        with self._write() as conn:
            conn.execute(
                text(
                    "INSERT INTO teams (id, name) VALUES (:id, :name) "
                    "ON CONFLICT (id) DO UPDATE SET name = excluded.name"
                ),
                {"id": team.id, "name": team.name.value},
            )

    # --- memberships ---

    def get_membership(self, user_id: UserId, team_id: TeamId) -> Membership | None:
        with self._read() as conn:
            row = conn.execute(
                text(
                    "SELECT user_id, team_id, role FROM memberships "
                    "WHERE user_id = :u AND team_id = :t"
                ),
                {"u": user_id, "t": team_id},
            ).fetchone()
        return None if row is None else _row_to_membership(row)

    def save_membership(self, membership: Membership) -> None:
        with self._write() as conn:
            conn.execute(
                text(
                    "INSERT INTO memberships (user_id, team_id, role) "
                    "VALUES (:u, :t, :r) ON CONFLICT (user_id, team_id) "
                    "DO UPDATE SET role = excluded.role"
                ),
                {"u": membership.user_id, "t": membership.team_id, "r": membership.role.value},
            )

    def delete_membership(self, user_id: UserId, team_id: TeamId) -> None:
        with self._write() as conn:
            conn.execute(
                text("DELETE FROM memberships WHERE user_id = :u AND team_id = :t"),
                {"u": user_id, "t": team_id},
            )

    def list_memberships_for_user(self, user_id: UserId) -> tuple[Membership, ...]:
        with self._read() as conn:
            rows = conn.execute(
                text("SELECT user_id, team_id, role FROM memberships WHERE user_id = :u"),
                {"u": user_id},
            ).fetchall()
        return tuple(_row_to_membership(row) for row in rows)

    def list_memberships_for_team(self, team_id: TeamId) -> tuple[Membership, ...]:
        with self._read() as conn:
            rows = conn.execute(
                text("SELECT user_id, team_id, role FROM memberships WHERE team_id = :t"),
                {"t": team_id},
            ).fetchall()
        return tuple(_row_to_membership(row) for row in rows)


def _row_to_membership(row: Any) -> Membership:
    return Membership(
        user_id=UserId(row.user_id),
        team_id=TeamId(row.team_id),
        role=MembershipRole.parse(row.role).unwrap(),
    )
