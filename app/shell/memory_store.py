"""Concrete in-memory store — for local dev and tests.

It satisfies the `UserStore`/`TeamStore`/`MembershipStore` Protocols structurally;
the core depends on no abstraction it provides. Swapping backends means writing
another concrete store and changing one line in `main.py` (§2, Corollary 2).

`unit_of_work` snapshots the dicts and restores them if the block raises, giving
the same all-or-nothing rollback the SQL backends get from a transaction. That
keeps the shell's atomic flows behaving identically on every backend — and means
the in-memory-backed tests exercise the *real* rollback path, not a stand-in.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from app.core.membership import Membership
from app.core.team import Team, TeamId
from app.core.user import User, UserId
from app.shell.stores import Store


class InMemoryStore:
    def __init__(self) -> None:
        self._users: dict[UserId, User] = {}
        self._teams: dict[TeamId, Team] = {}
        self._memberships: dict[tuple[UserId, TeamId], Membership] = {}

    @contextmanager
    def unit_of_work(self) -> Iterator[Store]:
        snapshot = (dict(self._users), dict(self._teams), dict(self._memberships))
        try:
            yield self
        except BaseException:
            self._users, self._teams, self._memberships = snapshot  # roll back
            raise

    def get_user(self, user_id: UserId) -> User | None:
        return self._users.get(user_id)

    def save_user(self, user: User) -> None:
        self._users[user.id] = user

    def delete_user(self, user_id: UserId) -> None:
        self._users.pop(user_id, None)

    def get_team(self, team_id: TeamId) -> Team | None:
        return self._teams.get(team_id)

    def save_team(self, team: Team) -> None:
        self._teams[team.id] = team

    def get_membership(self, user_id: UserId, team_id: TeamId) -> Membership | None:
        return self._memberships.get((user_id, team_id))

    def save_membership(self, membership: Membership) -> None:
        self._memberships[(membership.user_id, membership.team_id)] = membership

    def delete_membership(self, user_id: UserId, team_id: TeamId) -> None:
        self._memberships.pop((user_id, team_id), None)

    def list_memberships_for_user(self, user_id: UserId) -> tuple[Membership, ...]:
        return tuple(m for m in self._memberships.values() if m.user_id == user_id)

    def list_memberships_for_team(self, team_id: TeamId) -> tuple[Membership, ...]:
        return tuple(m for m in self._memberships.values() if m.team_id == team_id)
