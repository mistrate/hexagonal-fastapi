"""A small `Result` type — §7 of python_guidelines.md.

The error track is part of the type, so a caller cannot accidentally skip the
failure path: there is no value to read until they `match` (or supply a default).

This is the "roll your own, it's small enough to vendor" option from §7.1. The
methods (`map`, `and_then`) let a workflow read as a pipeline (§10); the frozen
dataclasses let callers `match` instead (§7.5). Both styles are used here.

`Result` is for *domain errors* — expected outcomes a caller will branch on
(§6). It is NOT for panics (let those raise) nor for plain absence (use
`T | None`, §7.2).

Generics use PEP 695 syntax (`class Ok[T]`, `type Result[T, E] = ...`), which
this project relies on since it targets Python 3.14.
"""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NoReturn


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    def map[U](self, f: Callable[[T], U]) -> Ok[U]:
        """Transform the success value; leave the (absent) error untouched."""
        return Ok(f(self.value))

    def map_err(self, f: Callable[[Any], Any]) -> Ok[T]:
        return self

    def and_then[U, F](self, f: Callable[[T], Result[U, F]]) -> Result[U, F]:
        """Monadic bind: chain a step that may itself fail (§10)."""
        return f(self.value)

    def unwrap_or(self, default: Any) -> T:
        return self.value

    def unwrap(self) -> T:
        return self.value


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

    def map(self, f: Callable[[Any], Any]) -> Err[E]:
        return self

    def map_err[F](self, f: Callable[[E], F]) -> Err[F]:
        return Err(f(self.error))

    def and_then(self, f: Callable[[Any], Any]) -> Err[E]:
        return self

    def unwrap_or[U](self, default: U) -> U:
        return default

    def unwrap(self) -> NoReturn:
        # Unwrapping an Err is a programmer error (a panic, §6), not a domain
        # outcome. Production code should `match`; this exists for the rare
        # "cannot fail here" site and for test ergonomics.
        raise ValueError(f"called unwrap() on an Err: {self.error!r}")


# A generic alias (PEP 695): `Result[int, str]` is `Ok[int] | Err[str]`. `match`
# narrows it and mypy tracks both tracks.
type Result[T, E] = Ok[T] | Err[E]
