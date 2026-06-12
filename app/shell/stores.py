"""The persistence contracts shared across the shell.

As the domain grew (User, then Team, then Membership), the store grew with it.
Two choices keep it from becoming a god-object:

* **Interfaces are segregated by entity** (`UserStore`, `TeamStore`,
  `MembershipStore`) — interface segregation, so a consumer can depend on just
  the slice it needs. `Store` composes them for the composition root.
* **The implementation stays unified**: one backend class (e.g. `SqlStore`)
  implements all of them over one database with several tables. Adding an entity
  is "a focused Protocol here + a few methods on each backend," not a new
  abstraction the core depends on.

Methods are entity-prefixed (`get_user`, `get_team`, …) precisely because one
object provides all of them — a single `get` cannot serve three entities.

These live in the SHELL; the core never imports them (§2). And note the real
cost: every method here must be implemented in *every* backend (`memory_store`,
`sql_store` — the SQL one at least covers both dialects from a single typed
schema). That N×M growth is the price of keeping multiple backends, and the
reason §2 says to keep a store `Protocol` only when you genuinely have multiple
production implementations.
"""

from contextlib import AbstractContextManager
from typing import Protocol

from app.core.membership import Membership
from app.core.team import Team, TeamId
from app.core.user import User, UserId


class UserStore(Protocol):
    def get_user(self, user_id: UserId) -> User | None: ...
    def save_user(self, user: User) -> None: ...
    def delete_user(self, user_id: UserId) -> None: ...  # deletes the user row only


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
    Protocol above.

    `unit_of_work` makes a multi-step shell operation atomic: the yielded store's
    writes all commit together when the block exits normally, or all roll back if
    it raises (a connection error included). The SQL backends use one transaction;
    the in-memory store snapshots and restores. So the shell never has to leave
    half-finished state behind, on any backend."""

    def unit_of_work(self) -> AbstractContextManager[Store]: ...
