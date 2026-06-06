"""HTTP delivery mechanism (FastAPI) — an imperative shell.

Each route reads the world, hands a value to the pure core (`create_user`,
`change_display_name`), and performs the effect the core's result describes
(save, or translate a domain error to a status code). Pydantic parses request
bodies at the boundary (§8); domain values never leave the core as framework
types, and the HTTP-specific mapping (status codes) lives only here.

The persistence abstraction (`UserStore`) lives in `app/shell/user_store.py`,
not here — it is shared shell infrastructure, used by the CLI too, not an HTTP
detail. `create_app` takes a store and wires it in directly; tests build their
own app around a fresh store, so there is no `dependency_overrides` ceremony.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.result import Err, Ok
from app.core.user import User, UserId, change_display_name, create_user, describe
from app.shell.user_store import UserStore


class CreateUserRequest(BaseModel):
    id: str
    email: str
    display_name: str


class UpdateProfileRequest(BaseModel):
    display_name: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str


def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id, email=user.email.value, display_name=user.display_name.value
    )


def create_app(store: UserStore) -> FastAPI:
    app = FastAPI(title="User Profile — functional core / imperative shell")

    @app.post("/users", status_code=201, response_model=UserResponse)
    def add_user(body: CreateUserRequest) -> UserResponse:
        if store.get(UserId(body.id)) is not None:  # shell: read the world
            raise HTTPException(status_code=409, detail="user already exists")
        match create_user(body.id, body.email, body.display_name):  # core: pure decision
            case Ok(user):
                store.save(user)  # shell: perform the effect
                return _to_response(user)
            case Err(problems):
                # Every field problem at once (§8), each rendered by the core's
                # describe; the 422 status is the shell's call.
                raise HTTPException(status_code=422, detail=[describe(p) for p in problems])

    @app.put("/users/{user_id}/profile", response_model=UserResponse)
    def update_profile(user_id: str, body: UpdateProfileRequest) -> UserResponse:
        user = store.get(UserId(user_id))  # shell: read the world
        if user is None:
            # Absence, discovered where the I/O happens — never reaches the core (§7.2).
            raise HTTPException(status_code=404, detail="user not found")
        match change_display_name(user, body.display_name):  # core: pure decision
            case Ok(updated):
                store.save(updated)  # shell: perform the effect
                return _to_response(updated)
            case Err(_):
                raise HTTPException(status_code=422, detail="display_name cannot be empty")

    return app
