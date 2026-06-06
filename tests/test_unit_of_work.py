"""Unit-of-work atomicity — a multi-step operation commits or rolls back as one.

Run against both the in-memory store (snapshot/restore) and SQLite (a real
transaction), so the rollback the shell relies on is the same code path in tests
as in production.
"""

from pathlib import Path

import pytest

from app.core.membership import Membership, MembershipRole
from app.core.team import Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId
from app.shell.memory_store import InMemoryStore
from app.shell.sqlite_store import SqliteStore
from app.shell.stores import Store


def a_user(user_id: str = "u1") -> User:
    return User(
        id=UserId(user_id),
        email=Email.parse("ada@example.com").unwrap(),
        display_name=DisplayName.parse("Ada").unwrap(),
    )


def a_team(team_id: str = "t1") -> Team:
    return Team(id=TeamId(team_id), name=TeamName.parse("Core").unwrap())


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Store:
    if request.param == "sqlite":
        return SqliteStore(str(tmp_path / "app.db"))
    return InMemoryStore()


def _seed(store: Store) -> None:
    store.save_user(a_user())
    store.save_team(a_team())
    store.save_membership(Membership(UserId("u1"), TeamId("t1"), MembershipRole.MEMBER))


def test_unit_of_work_commits_on_success(store: Store) -> None:
    _seed(store)
    with store.unit_of_work() as tx:
        tx.delete_membership(UserId("u1"), TeamId("t1"))
        tx.delete_user(UserId("u1"))
    assert store.get_user(UserId("u1")) is None
    assert store.get_membership(UserId("u1"), TeamId("t1")) is None


def test_unit_of_work_rolls_back_on_error(store: Store) -> None:
    _seed(store)
    with pytest.raises(RuntimeError), store.unit_of_work() as tx:
        tx.delete_membership(UserId("u1"), TeamId("t1"))  # first step succeeds...
        raise RuntimeError("connection lost")  # ...then something fails mid-way
    # Nothing was committed: both rows survive — no half-finished state.
    assert store.get_membership(UserId("u1"), TeamId("t1")) is not None
    assert store.get_user(UserId("u1")) is not None
