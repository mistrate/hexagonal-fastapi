"""The persistence contracts shared across the shell.

As the domain grew (User, then Team, then Membership), the store grew with it.
Two choices keep it from becoming a god-object:

* **Interfaces are segregated by entity** (`UserStore`, `TeamStore`,
  `MembershipStore`) — interface segregation, so a consumer can depend on just
  the slice it needs. `Store` composes them for the composition root.
* **The implementation stays unified**: one backend class (e.g. `SqliteStore`)
  implements all of them over one database with several tables. Adding an entity
  is "a focused Protocol here + a few methods on each backend," not a new
  abstraction the core depends on.

Methods are entity-prefixed (`get_user`, `get_team`, …) precisely because one
object provides all of them — a single `get` cannot serve three entities.

These live in the SHELL; the core never imports them (§2). And note the real
cost: every method here must be implemented in *every* backend
(`memory_store`, `sqlite_store`, `postgres_store`). That N×M growth is the price
of keeping multiple backends, and the reason §2 says to keep a store `Protocol`
only when you genuinely have multiple production implementations.
"""

from typing import Protocol

from app.core.membership import Membership
from app.core.team import Team, TeamId
from app.core.user import User, UserId


class UserStore(Protocol):
    def get_user(self, user_id: UserId) -> User | None: ...
    def save_user(self, user: User) -> None: ...


class TeamStore(Protocol):
    def get_team(self, team_id: TeamId) -> Team | None: ...
    def save_team(self, team: Team) -> None: ...


class MembershipStore(Protocol):
    def get_membership(self, user_id: UserId, team_id: TeamId) -> Membership | None: ...
    def save_membership(self, membership: Membership) -> None: ...
    def delete_membership(self, user_id: UserId, team_id: TeamId) -> None: ...
    def list_memberships_for_user(self, user_id: UserId) -> tuple[Membership, ...]: ...
    def list_memberships_for_team(self, team_id: TeamId) -> tuple[Membership, ...]: ...


class Store(UserStore, TeamStore, MembershipStore, Protocol):
    """Every capability a delivery mechanism needs; one backend object satisfies
    all of it. A helper that needs only one slice can still take the narrower
    Protocol above."""
