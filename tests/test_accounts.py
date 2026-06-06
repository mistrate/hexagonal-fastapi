"""The account-deletion decision — pure, no mocks.

The cross-aggregate gate ("can't delete the sole admin of a team") as a pure
function over values; the shell computes which teams the user solely admins.
"""

from app.core.accounts import SoleAdminOf, decide_user_deletion
from app.core.result import Err, Ok
from app.core.team import TeamId
from app.core.user import DisplayName, Email, User, UserId


def a_user() -> User:
    return User(
        id=UserId("u1"),
        email=Email.parse("ada@example.com").unwrap(),
        display_name=DisplayName.parse("Ada").unwrap(),
    )


def test_can_delete_when_not_a_sole_admin() -> None:
    assert decide_user_deletion(a_user(), ()) == Ok(UserId("u1"))


def test_cannot_delete_while_sole_admin_of_a_team() -> None:
    assert decide_user_deletion(a_user(), (TeamId("t1"), TeamId("t2"))) == Err(
        SoleAdminOf((TeamId("t1"), TeamId("t2")))
    )
