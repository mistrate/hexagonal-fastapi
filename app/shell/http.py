"""HTTP delivery mechanism (FastAPI) — an imperative shell.

Each route reads the world, hands values to the pure core, and performs the
effect the core's result describes. Pydantic parses bodies at the boundary (§8);
the HTTP-specific mapping (status codes) lives only here.

Watch how the "≥1 admin" invariant lands in the shell: creating a team now loads
the founding admin first, and removing/updating a member loads the *whole team's*
memberships and passes that aggregate to the pure decision. The core stays
one-liners; the multi-table coordination accretes here.
"""

from typing import assert_never

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.core.accounts import decide_user_deletion, describe_sole_admin
from app.core.membership import (
    LastAdmin,
    Membership,
    MembershipRole,
    NotAMember,
    add_member,
    admin_count,
    change_role,
    describe_change_error,
    found_team,
    remove_member,
)
from app.core.result import Err, Ok
from app.core.team import TeamId
from app.core.user import User, UserId, change_display_name, create_user, describe
from app.shell.stores import Store

# --- boundary models (§8) ---


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


class CreateTeamRequest(BaseModel):
    id: str
    name: str
    admin_user_id: str  # the founding admin — a team is created with ≥1 admin


class TeamResponse(BaseModel):
    id: str
    name: str


class AddMemberRequest(BaseModel):
    user_id: str
    role: str


class UpdateRoleRequest(BaseModel):
    role: str


class MembershipResponse(BaseModel):
    user_id: str
    team_id: str
    role: str


def _user_response(user: User) -> UserResponse:
    return UserResponse(id=user.id, email=user.email.value, display_name=user.display_name.value)


def _membership_response(membership: Membership) -> MembershipResponse:
    return MembershipResponse(
        user_id=membership.user_id, team_id=membership.team_id, role=membership.role.value
    )


def _parse_role(raw: str) -> MembershipRole:
    """Parse the role at the boundary (§8); the one domain error → 422."""
    match MembershipRole.parse(raw):
        case Ok(role):
            return role
        case Err(_):
            raise HTTPException(status_code=422, detail="role must be 'member' or 'admin'")


def _change_error_http(error: NotAMember | LastAdmin) -> HTTPException:
    """Map a change/remove error to a status code (404 vs 409); the message comes
    from the core's describe (§5). Exhaustive, so a new error variant is a type
    error here until handled."""
    match error:
        case NotAMember():
            status = 404
        case LastAdmin():
            status = 409
        case _ as unreachable:
            assert_never(unreachable)
    return HTTPException(status_code=status, detail=describe_change_error(error))


def create_app(store: Store) -> FastAPI:
    app = FastAPI(title="Users & Teams — functional core / imperative shell")

    # --- users ---

    @app.post("/users", status_code=201, response_model=UserResponse)
    def add_user(body: CreateUserRequest) -> UserResponse:
        if store.get_user(UserId(body.id)) is not None:
            raise HTTPException(status_code=409, detail="user already exists")
        match create_user(body.id, body.email, body.display_name):
            case Ok(user):
                store.save_user(user)
                return _user_response(user)
            case Err(problems):
                raise HTTPException(status_code=422, detail=[describe(p) for p in problems])

    @app.put("/users/{user_id}/profile", response_model=UserResponse)
    def update_profile(user_id: str, body: UpdateProfileRequest) -> UserResponse:
        user = store.get_user(UserId(user_id))
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        match change_display_name(user, body.display_name):
            case Ok(updated):
                store.save_user(updated)
                return _user_response(updated)
            case Err(_):
                raise HTTPException(status_code=422, detail="display_name cannot be empty")

    @app.get("/users/{user_id}/memberships", response_model=list[MembershipResponse])
    def list_memberships(user_id: str) -> list[MembershipResponse]:
        if store.get_user(UserId(user_id)) is None:
            raise HTTPException(status_code=404, detail="user not found")
        return [_membership_response(m) for m in store.list_memberships_for_user(UserId(user_id))]

    @app.delete("/users/{user_id}", status_code=204)
    def delete_user_route(user_id: str) -> None:
        uid = UserId(user_id)
        user = store.get_user(uid)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        memberships = store.list_memberships_for_user(uid)
        sole_admin_of = tuple(
            m.team_id
            for m in memberships
            if m.role is MembershipRole.ADMIN
            and admin_count(store.list_memberships_for_team(m.team_id)) == 1
        )
        match decide_user_deletion(user, sole_admin_of):
            case Ok(deleted_id):
                # Cascade in one transaction — a mid-cascade failure rolls the whole
                # thing back (atomic), uniform across backends; the FK is a backstop.
                with store.unit_of_work() as tx:
                    for membership in memberships:
                        tx.delete_membership(deleted_id, membership.team_id)
                    tx.delete_user(deleted_id)
            case Err(error):
                raise HTTPException(status_code=409, detail=describe_sole_admin(error))

    # --- teams ---

    @app.post("/teams", status_code=201, response_model=TeamResponse)
    def add_team(body: CreateTeamRequest) -> TeamResponse:
        if store.get_team(TeamId(body.id)) is not None:
            raise HTTPException(status_code=409, detail="team already exists")
        founder = store.get_user(UserId(body.admin_user_id))  # the team's first admin must exist
        if founder is None:
            raise HTTPException(status_code=404, detail="admin user not found")
        match found_team(body.id, body.name, founder):
            case Ok(founding):  # binding the pair (not `Ok((team, admin))`) keeps the
                team, admin = founding  # match provably exhaustive for ty
                # Team + founding admin commit together — never a team with no admin.
                with store.unit_of_work() as tx:
                    tx.save_team(team)
                    tx.save_membership(admin)
                return TeamResponse(id=team.id, name=team.name.value)
            case Err(_):
                raise HTTPException(status_code=422, detail="team name cannot be empty")

    # --- memberships (the new dimension) ---

    @app.post("/teams/{team_id}/members", status_code=201, response_model=MembershipResponse)
    def add_member_route(team_id: str, body: AddMemberRequest) -> MembershipResponse:
        role = _parse_role(body.role)
        user = store.get_user(UserId(body.user_id))  # FK existence — a shell concern
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        team = store.get_team(TeamId(team_id))
        if team is None:
            raise HTTPException(status_code=404, detail="team not found")
        existing = store.get_membership(user.id, team.id)
        match add_member(user, team, role, existing):
            case Ok(membership):
                store.save_membership(membership)
                return _membership_response(membership)
            case Err(_):
                raise HTTPException(status_code=409, detail="already a member of this team")

    @app.put("/teams/{team_id}/members/{user_id}", response_model=MembershipResponse)
    def update_role_route(
        team_id: str, user_id: str, body: UpdateRoleRequest
    ) -> MembershipResponse:
        role = _parse_role(body.role)
        existing = store.get_membership(UserId(user_id), TeamId(team_id))
        team_members = store.list_memberships_for_team(TeamId(team_id))
        match change_role(existing, role, team_members):
            case Ok(membership):
                store.save_membership(membership)
                return _membership_response(membership)
            case Err(error):
                raise _change_error_http(error)

    @app.delete("/teams/{team_id}/members/{user_id}", status_code=204)
    def remove_member_route(team_id: str, user_id: str) -> None:
        existing = store.get_membership(UserId(user_id), TeamId(team_id))
        team_members = store.list_memberships_for_team(TeamId(team_id))
        match remove_member(existing, team_members):
            case Ok(membership):
                store.delete_membership(membership.user_id, membership.team_id)
            case Err(error):
                raise _change_error_http(error)

    return app
