"""The user domain — pure. Imports nothing but `app.core.result` and stdlib.

A user has an id, an email, and a display name; you can create one and you can
change its display name. Rewritten to follow the guidelines:

* `User` is a frozen dataclass — values, not mutable records (§3.1, §11).
* `email` and `display_name` are parsed once at the boundary and carry their
  invariant in the type thereafter (parse, don't validate — §8, §9). `UserId` is
  a `NewType`: an identifier with no invariant, just a name the checker won't let
  you confuse with a `str`.
* The rules — `create_user` and `change_display_name` — are **pure functions**
  over values. They perform no I/O, touch no store, and raise nothing for
  expected outcomes (§2, §7.3, §12). Loading and saving live in the shell.
* `create_user` parses two fields at once and **collects every problem** rather
  than failing on the first (§8). `describe` renders a problem with an
  exhaustive `match` + `assert_never`, so adding an error variant is a type
  error until handled (§5).

What is deliberately *gone*: the `UserRepository` port. The decision is pure;
the core does not know storage exists (§2, Corollary 2).
"""
import re
from dataclasses import dataclass, replace
from typing import NewType, assert_never

from app.core.result import Err, Ok, Result

# An identifier needs no invariant — a NewType is enough to stop it being mixed
# up with an ordinary str at the type level, at zero runtime cost (§9).
UserId = NewType("UserId", str)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --- Domain errors, as values (§6). Each parse failure is its own type. ---


@dataclass(frozen=True, slots=True)
class MalformedEmail:
    raw: str


@dataclass(frozen=True, slots=True)
class EmptyDisplayName:
    pass


# --- Constrained values, constructible only through `parse` (§8, §9) ---


@dataclass(frozen=True, slots=True)
class Email:
    value: str

    def __post_init__(self) -> None:
        # The invariant the type promises. `parse` turns untrusted input into a
        # Result; this is the backstop for direct construction with bad data — a
        # programmer error, so it raises (a panic, §6/§9), not a Result.
        if not _EMAIL_RE.match(self.value):
            raise ValueError(f"invalid email: {self.value!r}")

    @classmethod
    def parse(cls, raw: str) -> Result[Email, MalformedEmail]:
        candidate = raw.strip().lower()
        if not _EMAIL_RE.match(candidate):
            return Err(MalformedEmail(raw))
        return Ok(cls(candidate))


@dataclass(frozen=True, slots=True)
class DisplayName:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("display name cannot be empty")

    @classmethod
    def parse(cls, raw: str) -> Result[DisplayName, EmptyDisplayName]:
        trimmed = raw.strip()
        if not trimmed:
            return Err(EmptyDisplayName())
        return Ok(cls(trimmed))


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    email: Email
    display_name: DisplayName


# --- Creating a user can fail in more than one way; render exhaustively (§5, §6) ---

CreateUserError = MalformedEmail | EmptyDisplayName


def describe(error: CreateUserError) -> str:
    """Pure, total, presentation-agnostic description of a create error.

    The `match` is exhaustive over `CreateUserError`; `assert_never` makes adding
    a new variant a type error here until it is handled (§5). Shells decide *how*
    to present it (HTTP 422 body, CLI stderr); this decides *what* it says.
    """
    match error:
        case MalformedEmail(raw):
            return f"invalid email: {raw!r}"
        case EmptyDisplayName():
            return "display name cannot be empty"
        case _ as unreachable:
            assert_never(unreachable)


# --- The business rules, pure (§2, §8, §11, §12) ---


def create_user(user_id: str, raw_email: str, raw_name: str) -> Result[User, list[CreateUserError]]:
    """Parse raw input into a `User`, collecting *all* field problems at once
    (§8) rather than stopping at the first. Pure: no store, no I/O."""
    match Email.parse(raw_email), DisplayName.parse(raw_name):
        case Ok(email), Ok(name):
            return Ok(User(id=UserId(user_id), email=email, display_name=name))
        case email_result, name_result:
            problems: list[CreateUserError] = [
                r.error for r in (email_result, name_result) if isinstance(r, Err)
            ]
            return Err(problems)


def rename(user: User, new_name: DisplayName) -> User:
    """Total: a valid name in, a new `User` out. The input is never mutated;
    `replace` returns a fresh value (§11)."""
    return replace(user, display_name=new_name)


def change_display_name(user: User, raw_name: str) -> Result[User, EmptyDisplayName]:
    """The rename use case as a pure decision. Parse the untrusted input once
    (§8); on success, produce the updated user. The empty-name failure is a value
    on the error track, not an exception (§7.3). "User not found" is not handled
    here: that is plain absence the shell discovers when it loads (§7.2)."""
    return DisplayName.parse(raw_name).map(lambda name: rename(user, name))
