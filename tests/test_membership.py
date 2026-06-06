"""Membership transitions — pure functions, no mocks.

Each transition is total over the two-state machine (absent / present) and, for
the admin-count invariant, over the team's current members. Tests just pick a
starting state and the team's roster, then assert the value or the error.
"""

from app.core.membership import (
    AlreadyMember,
    LastAdmin,
    Membership,
    MembershipRole,
    NotAMember,
    UnknownRole,
    add_member,
    change_role,
    describe_change_error,
    found_team,
    remove_member,
)
from app.core.result import Err, Ok
from app.core.team import EmptyTeamName, Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId


def a_user(user_id: str = "u1") -> User:
    return User(
        id=UserId(user_id),
        email=Email.parse("ada@example.com").unwrap(),
        display_name=DisplayName.parse("Ada").unwrap(),
    )


def a_team(team_id: str = "t1") -> Team:
    return Team(id=TeamId(team_id), name=TeamName.parse("Core").unwrap())


def member(user_id: str, role: MembershipRole = MembershipRole.MEMBER) -> Membership:
    return Membership(user_id=UserId(user_id), team_id=TeamId("t1"), role=role)


def test_role_parse() -> None:
    assert MembershipRole.parse("admin") == Ok(MembershipRole.ADMIN)
    assert MembershipRole.parse("  Member ") == Ok(MembershipRole.MEMBER)
    assert MembershipRole.parse("owner") == Err(UnknownRole("owner"))


# --- found_team establishes the "at least one admin" invariant ---


def test_found_team_makes_the_founder_an_admin() -> None:
    assert found_team("t1", "Core", a_user("u1")) == Ok(
        (
            Team(id=TeamId("t1"), name=TeamName("Core")),
            Membership(user_id=UserId("u1"), team_id=TeamId("t1"), role=MembershipRole.ADMIN),
        )
    )


def test_found_team_rejects_blank_name() -> None:
    assert found_team("t1", "   ", a_user()) == Err(EmptyTeamName())


# --- add ---


def test_add_member_when_absent() -> None:
    assert add_member(a_user(), a_team(), MembershipRole.MEMBER, existing=None) == Ok(
        member("u1", MembershipRole.MEMBER)
    )


def test_add_member_when_already_present() -> None:
    assert add_member(a_user(), a_team(), MembershipRole.ADMIN, member("u1")) == Err(
        AlreadyMember()
    )


# --- change_role (guards demotion of the last admin) ---


def test_promote_member_to_admin() -> None:
    existing = member("u1", MembershipRole.MEMBER)
    assert change_role(existing, MembershipRole.ADMIN, (existing,)) == Ok(
        member("u1", MembershipRole.ADMIN)
    )


def test_change_role_when_absent() -> None:
    assert change_role(None, MembershipRole.ADMIN, ()) == Err(NotAMember())


def test_cannot_demote_the_last_admin() -> None:
    admin = member("u1", MembershipRole.ADMIN)
    assert change_role(admin, MembershipRole.MEMBER, (admin,)) == Err(LastAdmin())


def test_can_demote_an_admin_when_another_exists() -> None:
    a1, a2 = member("u1", MembershipRole.ADMIN), member("u2", MembershipRole.ADMIN)
    demoted = Ok(member("u1", MembershipRole.MEMBER))
    assert change_role(a1, MembershipRole.MEMBER, (a1, a2)) == demoted


# --- remove (guards removal of the last admin) ---


def test_remove_a_plain_member() -> None:
    m, admin = member("u1", MembershipRole.MEMBER), member("u2", MembershipRole.ADMIN)
    assert remove_member(m, (m, admin)) == Ok(m)


def test_remove_an_admin_when_another_exists() -> None:
    a1, a2 = member("u1", MembershipRole.ADMIN), member("u2", MembershipRole.ADMIN)
    assert remove_member(a1, (a1, a2)) == Ok(a1)


def test_cannot_remove_the_last_admin() -> None:
    admin = member("u1", MembershipRole.ADMIN)
    assert remove_member(admin, (admin,)) == Err(LastAdmin())


def test_remove_member_when_absent() -> None:
    assert remove_member(None, ()) == Err(NotAMember())


def test_describe_change_error() -> None:
    assert describe_change_error(NotAMember()) == "not a member of this team"
    assert "last admin" in describe_change_error(LastAdmin())
