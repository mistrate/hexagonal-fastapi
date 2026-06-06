"""The persistence boundary shared across the shell.

`UserStore` is the one abstraction the shell keeps over storage. It lives here —
not inside the HTTP adapter — because it is not HTTP-specific: the API
(`http.create_app`) builds on it, and the CLI builds on the same concrete stores.
The implementations (`memory_store`, `sqlite_store`, `postgres_store`) satisfy it
structurally.

Why a Protocol is justified here (and was an anti-pattern in the core): the
guidelines reject a Protocol introduced solely so a pure core can be tested
against a fake (§2, Corollary 2), but permit one "when you genuinely have
multiple production implementations" (§2, final paragraph). There are three.

Crucially this lives in the SHELL; the core (`app.core`) never imports it. The
business rules take `User` values and have no idea storage exists — the whole
difference from the old `UserRepository` port the use case itself depended on.
"""
from typing import Protocol

from app.core.user import User, UserId


class UserStore(Protocol):
    def get(self, user_id: UserId) -> User | None: ...
    def save(self, user: User) -> None: ...
