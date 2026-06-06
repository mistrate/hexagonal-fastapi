"""Team membership — pure. A user belongs to a team as MEMBER or ADMIN.

The (user, team) relationship is either **absent** (`None`) or **present** (a
`Membership`). The operations are total transitions over that two-state machine
(§4.2). Each returns a `Result` whose error track is a typed `DomainError` (§6).

This module also owns a **team invariant**: a team always has at least one admin.
It is established at creation (`found_team` makes the founder an admin — the only
way to create a team) and preserved by the transitions: you cannot remove *or
demote* the last admin. Enforcing that needs the team's *other* memberships, so
`change_role`/`remove_member` take `team_members` — the shell loads the
aggregate, the core counts admins and decides. That is the shape a cross-entity
invariant takes here: aggregate data flows into the pure decision; the core still
performs no I/O.

Referential existence (does the user/team exist?) stays a shell concern — a
`User`/`Team` value exists only because it was loaded.
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import assert_never

from app.core.errors import DomainError
from app.core.result import Err, Ok, Result
from app.core.team import EmptyTeamName, Team, TeamId, create_team
from app.core.user import User, UserId


@dataclass(frozen=True, slots=True)
class UnknownRole(DomainError):
    raw: str


class MembershipRole(Enum):
    MEMBER = "member"
    ADMIN = "admin"

    @classmethod
    def parse(cls, raw: str) -> Result[MembershipRole, UnknownRole]:
        try:
            return Ok(cls(raw.strip().lower()))
        except ValueError:
            # Interop with stdlib Enum, whose miss is an exception; convert it to
            # a domain value at this one boundary (§16). The exception never escapes.
            return Err(UnknownRole(raw))


@dataclass(frozen=True, slots=True)
class AlreadyMember(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class NotAMember(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class LastAdmin(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class Membership:
    user_id: UserId
    team_id: TeamId
    role: MembershipRole


def found_team(
    team_id: str, raw_name: str, founder: User
) -> Result[tuple[Team, Membership], EmptyTeamName]:
    """Create a team together with its founding admin. Because this is the only
    way to create a team, the "at least one admin" invariant holds from birth."""
    match create_team(team_id, raw_name):
        case Ok(team):
            admin = Membership(user_id=founder.id, team_id=team.id, role=MembershipRole.ADMIN)
            return Ok((team, admin))
        case Err(error):
            return Err(error)


def add_member(
    user: User, team: Team, role: MembershipRole, existing: Membership | None
) -> Result[Membership, AlreadyMember]:
    if existing is not None:
        return Err(AlreadyMember())
    return Ok(Membership(user_id=user.id, team_id=team.id, role=role))


def change_role(
    existing: Membership | None,
    new_role: MembershipRole,
    team_members: tuple[Membership, ...],
) -> Result[Membership, NotAMember | LastAdmin]:
    if existing is None:
        return Err(NotAMember())
    demoting_admin = existing.role is MembershipRole.ADMIN and new_role is not MembershipRole.ADMIN
    if demoting_admin and admin_count(team_members) <= 1:
        return Err(LastAdmin())
    return Ok(replace(existing, role=new_role))


def remove_member(
    existing: Membership | None, team_members: tuple[Membership, ...]
) -> Result[Membership, NotAMember | LastAdmin]:
    if existing is None:
        return Err(NotAMember())
    if existing.role is MembershipRole.ADMIN and admin_count(team_members) <= 1:
        return Err(LastAdmin())
    return Ok(existing)


def describe_change_error(error: NotAMember | LastAdmin) -> str:
    """Pure, total description of a change/remove failure (§5). Shells decide how
    to present it (status code, stderr); this decides what it says."""
    match error:
        case NotAMember():
            return "not a member of this team"
        case LastAdmin():
            return "cannot remove or demote the last admin of the team"
        case _ as unreachable:
            assert_never(unreachable)


def admin_count(members: tuple[Membership, ...]) -> int:
    return sum(1 for m in members if m.role is MembershipRole.ADMIN)
