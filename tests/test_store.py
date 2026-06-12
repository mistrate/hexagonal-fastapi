"""The SQL store (SQLite engine) across all three tables, against a temp file.

No mocking — a real backend, real persistence, foreign keys on. Exercises the
multi-table shape: user/team roundtrips, the composite-key membership, upsert,
the filtered list query, and survival across instances.
"""

from pathlib import Path

from app.core.membership import Membership, MembershipRole
from app.core.team import Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId
from app.shell.database import Store, create_store, run_migrations


def sqlite_store(path: str) -> Store:
    url = f"sqlite:///{path}"
    run_migrations(url)  # the store performs no DDL — migrate the temp file first
    return create_store(url)


def a_user(user_id: str = "u1", name: str = "Ada") -> User:
    return User(
        id=UserId(user_id),
        email=Email.parse("ada@example.com").unwrap(),
        display_name=DisplayName.parse(name).unwrap(),
    )


def a_team(team_id: str = "t1", name: str = "Core") -> Team:
    return Team(id=TeamId(team_id), name=TeamName.parse(name).unwrap())


def test_user_roundtrip(tmp_path: Path) -> None:
    store = sqlite_store(str(tmp_path / "app.db"))
    store.save_user(a_user())
    assert store.get_user(UserId("u1")) == a_user()


def test_team_roundtrip(tmp_path: Path) -> None:
    store = sqlite_store(str(tmp_path / "app.db"))
    store.save_team(a_team())
    assert store.get_team(TeamId("t1")) == a_team()


def test_membership_roundtrip_and_delete(tmp_path: Path) -> None:
    store = sqlite_store(str(tmp_path / "app.db"))
    store.save_user(a_user())
    store.save_team(a_team())
    membership = Membership(UserId("u1"), TeamId("t1"), MembershipRole.ADMIN)
    store.save_membership(membership)
    assert store.get_membership(UserId("u1"), TeamId("t1")) == membership
    store.delete_membership(UserId("u1"), TeamId("t1"))
    assert store.get_membership(UserId("u1"), TeamId("t1")) is None


def test_save_membership_upserts_role(tmp_path: Path) -> None:
    store = sqlite_store(str(tmp_path / "app.db"))
    store.save_user(a_user())
    store.save_team(a_team())
    store.save_membership(Membership(UserId("u1"), TeamId("t1"), MembershipRole.MEMBER))
    store.save_membership(Membership(UserId("u1"), TeamId("t1"), MembershipRole.ADMIN))
    got = store.get_membership(UserId("u1"), TeamId("t1"))
    assert got is not None
    assert got.role == MembershipRole.ADMIN


def test_list_memberships_for_user_filters(tmp_path: Path) -> None:
    store = sqlite_store(str(tmp_path / "app.db"))
    store.save_user(a_user("u1"))
    store.save_user(a_user("u2"))
    store.save_team(a_team("t1"))
    store.save_team(a_team("t2"))
    store.save_membership(Membership(UserId("u1"), TeamId("t1"), MembershipRole.ADMIN))
    store.save_membership(Membership(UserId("u1"), TeamId("t2"), MembershipRole.MEMBER))
    store.save_membership(Membership(UserId("u2"), TeamId("t1"), MembershipRole.MEMBER))
    teams = {m.team_id for m in store.list_memberships_for_user(UserId("u1"))}
    assert teams == {TeamId("t1"), TeamId("t2")}


def test_data_persists_across_instances(tmp_path: Path) -> None:
    path = str(tmp_path / "app.db")
    sqlite_store(path).save_user(a_user())
    assert sqlite_store(path).get_user(UserId("u1")) == a_user()


def test_delete_user_removes_only_the_user(tmp_path: Path) -> None:
    # The store does a single-row delete; cascading is the shell's job, not the store's.
    store = sqlite_store(str(tmp_path / "app.db"))
    store.save_user(a_user())
    store.delete_user(UserId("u1"))
    assert store.get_user(UserId("u1")) is None
