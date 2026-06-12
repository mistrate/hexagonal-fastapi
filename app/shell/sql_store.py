"""The SQL backend — one store for SQLite (default) and Postgres.

Queries are built from the typed row models in `db_types.py` (column typos are
type errors; `select(...)` results are typed) and executed on plain Core
connections — no `Session`, so every write is a visible `conn.execute(...)`
right here. The dialect comes from the connectable; the only per-dialect code
is which `insert` provides `ON CONFLICT` (SQLite's vs Postgres's, same API).

It accepts a SQLAlchemy **connectable** — an `Engine` or a `Connection`:

* Given an `Engine` (production), each operation checks a pooled connection out
  and runs in its own transaction — connection-per-op, safe under FastAPI's
  threadpool.
* Given a `Connection` (inside `unit_of_work`, or an integration test's outer
  transaction), each write runs in a SAVEPOINT (`begin_nested`) on that one
  connection, so a multi-step shell operation commits or rolls back as a whole.

`create_sqlite_engine` exists because pysqlite's default transaction handling
never emits BEGIN for SAVEPOINT-only blocks; the two event hooks hand control
of transactions to SQLAlchemy (the documented recipe), and turn foreign-key
enforcement on per connection.

Parsing happens at this boundary (§8); our own rows are assumed valid, so a
malformed one is a panic — hence `.unwrap()`.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, Row, create_engine, delete, event, select
from sqlalchemy.dialects.postgresql import Insert as PostgresInsert, insert as postgres_insert
from sqlalchemy.dialects.sqlite import Insert as SqliteInsert, insert as sqlite_insert

from app.core.membership import Membership, MembershipRole
from app.core.team import Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId
from app.shell.db_types import Base, MembershipRow, TeamRow, UserRow
from app.shell.stores import Store

DEFAULT_DB_PATH = "app.db"


def create_sqlite_engine(path: str = DEFAULT_DB_PATH) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: sqlite3.Connection, _record: object) -> None:
        # autocommit mode: SQLAlchemy emits BEGIN itself (below), so SAVEPOINTs
        # inside `unit_of_work` sit in a real transaction instead of pysqlite's
        # implicit one.
        dbapi_connection.isolation_level = None
        dbapi_connection.execute("PRAGMA foreign_keys = ON")

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Connection) -> None:
        conn.exec_driver_sql("BEGIN")

    return engine


def create_schema(connectable: Engine | Connection) -> None:
    """Create the tables once (a real app would use migrations). Kept out of the
    store so integration tests run it a single time, committed, then wrap each
    test in a transaction they roll back."""
    Base.metadata.create_all(connectable)


class SqlStore:
    def __init__(self, connectable: Engine | Connection) -> None:
        self._connectable = connectable

    def _insert(self, entity: type[Base]) -> SqliteInsert | PostgresInsert:
        if self._connectable.dialect.name == "sqlite":
            return sqlite_insert(entity)
        return postgres_insert(entity)

    @contextmanager
    def _write(self) -> Iterator[Connection]:
        if isinstance(self._connectable, Engine):
            with self._connectable.begin() as conn:  # pooled connection, real transaction
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
                yield SqlStore(conn)
        else:
            with self._connectable.begin_nested():  # already in a transaction → savepoint
                yield SqlStore(self._connectable)

    # --- users ---

    def get_user(self, user_id: UserId) -> User | None:
        stmt = select(UserRow.id, UserRow.email, UserRow.display_name).where(UserRow.id == user_id)
        with self._read() as conn:
            row = conn.execute(stmt).first()
        if row is None:
            return None
        return User(
            id=UserId(row.id),
            email=Email.parse(row.email).unwrap(),
            display_name=DisplayName.parse(row.display_name).unwrap(),
        )

    def save_user(self, user: User) -> None:
        ins = self._insert(UserRow).values(
            id=user.id, email=user.email.value, display_name=user.display_name.value
        )
        stmt = ins.on_conflict_do_update(
            index_elements=[UserRow.id],
            set_={"email": ins.excluded.email, "display_name": ins.excluded.display_name},
        )
        with self._write() as conn:
            conn.execute(stmt)

    def delete_user(self, user_id: UserId) -> None:
        with self._write() as conn:
            conn.execute(delete(UserRow).where(UserRow.id == user_id))

    # --- teams ---

    def get_team(self, team_id: TeamId) -> Team | None:
        stmt = select(TeamRow.id, TeamRow.name).where(TeamRow.id == team_id)
        with self._read() as conn:
            row = conn.execute(stmt).first()
        if row is None:
            return None
        return Team(id=TeamId(row.id), name=TeamName.parse(row.name).unwrap())

    def save_team(self, team: Team) -> None:
        ins = self._insert(TeamRow).values(id=team.id, name=team.name.value)
        stmt = ins.on_conflict_do_update(
            index_elements=[TeamRow.id], set_={"name": ins.excluded.name}
        )
        with self._write() as conn:
            conn.execute(stmt)

    # --- memberships ---

    def get_membership(self, user_id: UserId, team_id: TeamId) -> Membership | None:
        stmt = select(MembershipRow.user_id, MembershipRow.team_id, MembershipRow.role).where(
            MembershipRow.user_id == user_id, MembershipRow.team_id == team_id
        )
        with self._read() as conn:
            row = conn.execute(stmt).first()
        return None if row is None else _row_to_membership(row)

    def save_membership(self, membership: Membership) -> None:
        ins = self._insert(MembershipRow).values(
            user_id=membership.user_id, team_id=membership.team_id, role=membership.role.value
        )
        stmt = ins.on_conflict_do_update(
            index_elements=[MembershipRow.user_id, MembershipRow.team_id],
            set_={"role": ins.excluded.role},
        )
        with self._write() as conn:
            conn.execute(stmt)

    def delete_membership(self, user_id: UserId, team_id: TeamId) -> None:
        stmt = delete(MembershipRow).where(
            MembershipRow.user_id == user_id, MembershipRow.team_id == team_id
        )
        with self._write() as conn:
            conn.execute(stmt)

    def list_memberships_for_user(self, user_id: UserId) -> tuple[Membership, ...]:
        stmt = select(MembershipRow.user_id, MembershipRow.team_id, MembershipRow.role).where(
            MembershipRow.user_id == user_id
        )
        with self._read() as conn:
            rows = conn.execute(stmt).all()
        return tuple(_row_to_membership(row) for row in rows)

    def list_memberships_for_team(self, team_id: TeamId) -> tuple[Membership, ...]:
        stmt = select(MembershipRow.user_id, MembershipRow.team_id, MembershipRow.role).where(
            MembershipRow.team_id == team_id
        )
        with self._read() as conn:
            rows = conn.execute(stmt).all()
        return tuple(_row_to_membership(row) for row in rows)


def _row_to_membership(row: Row[tuple[str, str, str]]) -> Membership:
    return Membership(
        user_id=UserId(row.user_id),
        team_id=TeamId(row.team_id),
        role=MembershipRole.parse(row.role).unwrap(),
    )
