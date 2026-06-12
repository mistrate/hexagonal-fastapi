"""Integration tests for `SqlStore` against a real Postgres (testcontainers).

Fast and isolated:

* the container starts and the schema is created **once** per session;
* each test runs in its own transaction on a single connection — the store's
  writes become SAVEPOINTs (it uses `begin_nested` when given a `Connection`), so
  any nested transactions during a test are savepoints too — and the fixture
  rolls that outer transaction back at the end. No schema rebuild between tests,
  no cross-test leakage.

Skipped automatically when the `postgres` extra or Docker is unavailable.
"""

import pytest

pytest.importorskip("psycopg")
pytest.importorskip("testcontainers")

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from testcontainers.postgres import PostgresContainer

from app.core.membership import Membership, MembershipRole
from app.core.team import Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId
from app.shell.sql_store import SqlStore, create_schema


def a_user(user_id: str = "u1", name: str = "Ada") -> User:
    return User(
        id=UserId(user_id),
        email=Email.parse("ada@example.com").unwrap(),
        display_name=DisplayName.parse(name).unwrap(),
    )


def a_team(team_id: str = "t1", name: str = "Core") -> Team:
    return Team(id=TeamId(team_id), name=TeamName.parse(name).unwrap())


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    try:
        postgres = PostgresContainer("postgres:16-alpine", driver="psycopg")
        postgres.start()
    except Exception as exc:  # Docker not running / image unavailable
        pytest.skip(f"Postgres container unavailable: {exc}")
    try:
        eng = create_engine(postgres.get_connection_url())
        create_schema(eng)  # once for the whole suite, committed
        yield eng
        eng.dispose()
    finally:
        postgres.stop()


@pytest.fixture
def store(engine: Engine) -> Iterator[SqlStore]:
    connection = engine.connect()
    transaction = connection.begin()  # one outer transaction per test
    try:
        yield SqlStore(connection)  # writes become savepoints on this connection
    finally:
        transaction.rollback()  # discard everything this test did — the schema stays
        connection.close()


def test_user_roundtrip(store: SqlStore) -> None:
    store.save_user(a_user())
    assert store.get_user(UserId("u1")) == a_user()


def test_team_and_membership_roundtrip(store: SqlStore) -> None:
    store.save_user(a_user())
    store.save_team(a_team())
    membership = Membership(UserId("u1"), TeamId("t1"), MembershipRole.ADMIN)
    store.save_membership(membership)
    assert store.get_membership(UserId("u1"), TeamId("t1")) == membership


def test_membership_delete(store: SqlStore) -> None:
    store.save_user(a_user())
    store.save_team(a_team())
    store.save_membership(Membership(UserId("u1"), TeamId("t1"), MembershipRole.MEMBER))
    store.delete_membership(UserId("u1"), TeamId("t1"))
    assert store.get_membership(UserId("u1"), TeamId("t1")) is None


def test_list_memberships(store: SqlStore) -> None:
    store.save_user(a_user("u1"))
    store.save_user(a_user("u2"))
    store.save_team(a_team("t1"))
    store.save_team(a_team("t2"))
    store.save_membership(Membership(UserId("u1"), TeamId("t1"), MembershipRole.ADMIN))
    store.save_membership(Membership(UserId("u1"), TeamId("t2"), MembershipRole.MEMBER))
    store.save_membership(Membership(UserId("u2"), TeamId("t1"), MembershipRole.MEMBER))
    assert {m.team_id for m in store.list_memberships_for_user(UserId("u1"))} == {
        TeamId("t1"),
        TeamId("t2"),
    }
    assert {m.user_id for m in store.list_memberships_for_team(TeamId("t1"))} == {
        UserId("u1"),
        UserId("u2"),
    }


def test_delete_user(store: SqlStore) -> None:
    store.save_user(a_user())
    store.delete_user(UserId("u1"))
    assert store.get_user(UserId("u1")) is None


def test_rollback_isolates_part1(store: SqlStore) -> None:
    store.save_user(a_user("ghost"))  # rolled back when this test ends


def test_rollback_isolates_part2(store: SqlStore) -> None:
    # If the per-test rollback works, part1's write is gone.
    assert store.get_user(UserId("ghost")) is None
