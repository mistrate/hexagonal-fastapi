"""The shell, tested through its real seam — `create_app` around a fresh store.

Contrast the original `tests/test_api.py`, which mutated
`app.dependency_overrides` to inject a fake past the port. Here it is ordinary
composition: build an app around an in-memory store and drive it.
"""
from fastapi.testclient import TestClient

from app.core.user import DisplayName, Email, User, UserId
from app.shell.http import create_app
from app.shell.memory_store import InMemoryUserStore


def fresh_client() -> TestClient:
    return TestClient(create_app(InMemoryUserStore()))


def client_with_seeded_user() -> TestClient:
    store = InMemoryUserStore()
    store.save(
        User(
            id=UserId("1"),
            email=Email.parse("a@b.com").unwrap(),
            display_name=DisplayName.parse("old").unwrap(),
        )
    )
    return TestClient(create_app(store))


# --- POST /users (create) ---


def test_post_user_creates() -> None:
    resp = fresh_client().post(
        "/users", json={"id": "7", "email": "ada@example.com", "display_name": "Ada"}
    )
    assert resp.status_code == 201
    assert resp.json() == {"id": "7", "email": "ada@example.com", "display_name": "Ada"}


def test_post_user_422_collects_all_problems() -> None:
    resp = fresh_client().post(
        "/users", json={"id": "7", "email": "nope", "display_name": "   "}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == ["invalid email: 'nope'", "display name cannot be empty"]


def test_post_user_409_when_already_exists() -> None:
    client = fresh_client()
    body = {"id": "7", "email": "ada@example.com", "display_name": "Ada"}
    assert client.post("/users", json=body).status_code == 201
    assert client.post("/users", json=body).status_code == 409


def test_create_then_rename_flow() -> None:
    client = fresh_client()
    client.post("/users", json={"id": "7", "email": "ada@example.com", "display_name": "Ada"})
    resp = client.put("/users/7/profile", json={"display_name": "Ada Lovelace"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Ada Lovelace"


# --- PUT /users/{id}/profile (rename) ---


def test_put_profile_ok() -> None:
    resp = client_with_seeded_user().put("/users/1/profile", json={"display_name": "new"})
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "new"


def test_put_profile_404_when_user_missing() -> None:
    resp = client_with_seeded_user().put("/users/999/profile", json={"display_name": "new"})
    assert resp.status_code == 404


def test_put_profile_422_on_empty_name() -> None:
    resp = client_with_seeded_user().put("/users/1/profile", json={"display_name": "  "})
    assert resp.status_code == 422
