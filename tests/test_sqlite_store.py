"""The SQLite store: real persistence, exercised against a temp file.

No mocking — it's a real implementation, so we test the real thing. A temp file
(not `:memory:`) is required because the store opens a fresh connection per
operation, which is also why it survives across instances (the realism point).
"""
from pathlib import Path

from app.core.user import DisplayName, Email, User, UserId
from app.shell.sqlite_store import SqliteUserStore


def a_user(user_id: str = "1", name: str = "Ada") -> User:
    return User(
        id=UserId(user_id),
        email=Email.parse("ada@example.com").unwrap(),
        display_name=DisplayName.parse(name).unwrap(),
    )


def test_save_then_get_roundtrips(tmp_path: Path) -> None:
    store = SqliteUserStore(str(tmp_path / "users.db"))
    store.save(a_user())
    assert store.get(UserId("1")) == a_user()


def test_get_missing_returns_none(tmp_path: Path) -> None:
    store = SqliteUserStore(str(tmp_path / "users.db"))
    assert store.get(UserId("404")) is None


def test_data_persists_across_instances(tmp_path: Path) -> None:
    path = str(tmp_path / "users.db")
    SqliteUserStore(path).save(a_user(name="Ada"))
    # A fresh instance (a new process, in effect) sees the persisted row.
    assert SqliteUserStore(path).get(UserId("1")) == a_user(name="Ada")


def test_save_upserts(tmp_path: Path) -> None:
    store = SqliteUserStore(str(tmp_path / "users.db"))
    store.save(a_user(name="Ada"))
    store.save(a_user(name="Ada Lovelace"))
    got = store.get(UserId("1"))
    assert got is not None
    assert got.display_name == DisplayName("Ada Lovelace")
