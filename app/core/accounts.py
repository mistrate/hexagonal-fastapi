"""Account lifecycle — a pure coordination module above the aggregates.

Deleting a user is not a `user`-aggregate operation: whether it's allowed depends
on the user's *team memberships*. You can't delete the sole admin of a team
without orphaning it, which would break the "at least one admin" invariant. So
the decision lives here, above `user`/`team`, and takes the facts as values; the
shell gathers them. `user.py` stays a leaf (see the import-direction discussion).

The *cascade* (removing the deleted user's memberships) is deliberately NOT
modelled here: it is a uniform shell orchestration over the store's single-row
deletes — not a rule, and not a database feature we lean on (see app/shell/http.py).
"""

from dataclasses import dataclass

from app.core.errors import DomainError
from app.core.result import Err, Ok, Result
from app.core.team import TeamId
from app.core.user import User, UserId


@dataclass(frozen=True, slots=True)
class SoleAdminOf(DomainError):
    teams: tuple[TeamId, ...]


def decide_user_deletion(
    user: User, sole_admin_of: tuple[TeamId, ...]
) -> Result[UserId, SoleAdminOf]:
    """A user may be deleted unless they are the only admin of some team — that
    would leave those teams admin-less. The shell computes `sole_admin_of`."""
    if sole_admin_of:
        return Err(SoleAdminOf(sole_admin_of))
    return Ok(user.id)


def describe_sole_admin(error: SoleAdminOf) -> str:
    teams = ", ".join(error.teams)
    return f"cannot delete: sole admin of {teams} — hand off admin in those teams first"
