"""The shell, tested through its real seam — `create_app` around a fresh store.

Ordinary composition (no `dependency_overrides`). Covers the user routes, team
creation (which now requires a founding admin), and the membership routes —
including the "at least one admin" invariant.
"""

from fastapi.testclient import TestClient

from app.core.user import DisplayName, Email, User, UserId
from app.shell.http import create_app
from app.shell.memory_store import InMemoryStore


def fresh_client() -> TestClient:
    return TestClient(create_app(InMemoryStore()))


def client_with_seeded_user() -> TestClient:
    store = InMemoryStore()
    store.save_user(
        User(
            id=UserId("1"),
            email=Email.parse("a@b.com").unwrap(),
            display_name=DisplayName.parse("old").unwrap(),
        )
    )
    return TestClient(create_app(store))


def _client_with_team() -> TestClient:
    """A user `admin` who is the founding (and only) admin of team `t1`."""
    client = fresh_client()
    client.post("/users", json={"id": "admin", "email": "boss@example.com", "display_name": "Boss"})
    client.post("/teams", json={"id": "t1", "name": "Core", "admin_user_id": "admin"})
    return client


# --- users ---


def test_post_user_creates() -> None:
    resp = fresh_client().post(
        "/users", json={"id": "7", "email": "ada@example.com", "display_name": "Ada"}
    )
    assert resp.status_code == 201
    assert resp.json() == {"id": "7", "email": "ada@example.com", "display_name": "Ada"}


def test_post_user_422_collects_all_problems() -> None:
    resp = fresh_client().post("/users", json={"id": "7", "email": "nope", "display_name": "   "})
    assert resp.status_code == 422
    assert resp.json()["detail"] == ["invalid email: 'nope'", "display name cannot be empty"]


def test_put_profile_ok() -> None:
    resp = client_with_seeded_user().put("/users/1/profile", json={"display_name": "new"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "new"


def test_put_profile_404_when_user_missing() -> None:
    resp = client_with_seeded_user().put("/users/999/profile", json={"display_name": "new"})
    assert resp.status_code == 404


# --- teams (created with a founding admin) ---


def test_post_team_creates_and_makes_founder_admin() -> None:
    client = _client_with_team()
    assert client.get("/users/admin/memberships").json() == [
        {"user_id": "admin", "team_id": "t1", "role": "admin"}
    ]


def test_post_team_404_when_admin_user_missing() -> None:
    resp = fresh_client().post(
        "/teams", json={"id": "t1", "name": "Core", "admin_user_id": "ghost"}
    )
    assert resp.status_code == 404


def test_post_team_422_on_blank_name() -> None:
    client = fresh_client()
    client.post("/users", json={"id": "admin", "email": "boss@example.com", "display_name": "Boss"})
    resp = client.post("/teams", json={"id": "t1", "name": "  ", "admin_user_id": "admin"})
    assert resp.status_code == 422


# --- memberships ---


def test_membership_full_flow() -> None:
    client = _client_with_team()
    client.post("/users", json={"id": "u1", "email": "ada@example.com", "display_name": "Ada"})

    added = client.post("/teams/t1/members", json={"user_id": "u1", "role": "member"})
    assert added.status_code == 201
    assert added.json() == {"user_id": "u1", "team_id": "t1", "role": "member"}

    promoted = client.put("/teams/t1/members/u1", json={"role": "admin"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    assert client.get("/users/u1/memberships").json() == [
        {"user_id": "u1", "team_id": "t1", "role": "admin"}
    ]

    assert client.delete("/teams/t1/members/u1").status_code == 204
    assert client.get("/users/u1/memberships").json() == []


def test_add_member_unknown_user_404() -> None:
    resp = _client_with_team().post(
        "/teams/t1/members", json={"user_id": "ghost", "role": "member"}
    )
    assert resp.status_code == 404


def test_add_member_unknown_team_404() -> None:
    resp = _client_with_team().post(
        "/teams/ghost/members", json={"user_id": "admin", "role": "member"}
    )
    assert resp.status_code == 404


def test_add_member_bad_role_422() -> None:
    resp = _client_with_team().post("/teams/t1/members", json={"user_id": "admin", "role": "owner"})
    assert resp.status_code == 422


def test_add_member_twice_409() -> None:
    client = _client_with_team()
    client.post("/users", json={"id": "u1", "email": "ada@example.com", "display_name": "Ada"})
    client.post("/teams/t1/members", json={"user_id": "u1", "role": "member"})
    resp = client.post("/teams/t1/members", json={"user_id": "u1", "role": "admin"})
    assert resp.status_code == 409


def test_update_role_not_member_404() -> None:
    resp = _client_with_team().put("/teams/t1/members/ghost", json={"role": "admin"})
    assert resp.status_code == 404


# --- the "at least one admin" invariant ---


def test_cannot_remove_the_last_admin_409() -> None:
    resp = _client_with_team().delete("/teams/t1/members/admin")
    assert resp.status_code == 409


def test_cannot_demote_the_last_admin_409() -> None:
    resp = _client_with_team().put("/teams/t1/members/admin", json={"role": "member"})
    assert resp.status_code == 409


def test_can_remove_an_admin_when_another_exists() -> None:
    client = _client_with_team()
    client.post("/users", json={"id": "u1", "email": "ada@example.com", "display_name": "Ada"})
    client.post("/teams/t1/members", json={"user_id": "u1", "role": "admin"})
    assert client.delete("/teams/t1/members/admin").status_code == 204


def test_list_memberships_unknown_user_404() -> None:
    assert fresh_client().get("/users/ghost/memberships").status_code == 404
