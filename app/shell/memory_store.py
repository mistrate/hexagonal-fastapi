"""Concrete in-memory persistence — for local dev and tests.

It satisfies the `UserStore` Protocol (`app/shell/user_store.py`) structurally,
but it is just a concrete class; the core depends on no abstraction it provides.
Swapping backends means writing another concrete store (`sqlite_store.py`,
`postgres_store.py`) and changing one line in `main.py` — the swap the old
`UserRepository` port enabled, without the port (§2, Corollary 2).
"""
from app.core.user import User, UserId


class InMemoryUserStore:
    def __init__(self) -> None:
        self._by_id: dict[UserId, User] = {}

    def get(self, user_id: UserId) -> User | None:
        return self._by_id.get(user_id)

    def save(self, user: User) -> None:
        self._by_id[user.id] = user
