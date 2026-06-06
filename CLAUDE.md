# CLAUDE.md

Guidance for Claude Code working in this repo. This is a small toy that applies
[`python_guidelines.md`](./python_guidelines.md) — **functional core / imperative
shell**, algebraic data types, parse-don't-validate, `Result` for domain errors.
`python_guidelines.md` is the source of truth; this file is the project-specific
distillation. When the two disagree, the guidelines win.

> History: this began as a Ports & Adapters POC built around a `UserRepository`
> port. That port was the "Protocol-for-testability" anti-pattern the guidelines
> reject (§2, Corollary 2). It has been removed. **Do not reintroduce it.**

## Architecture rules (do not break these)

1. **Functional core, imperative shell.**
   - `app/core/` is pure. It imports only stdlib and other `app.core` modules.
     No `fastapi`, no `sqlalchemy`, no `pydantic`, no I/O, no `async`, no clock,
     no randomness, and no `try/except` for domain logic.
   - `app/shell/` does all I/O. It reads the world, calls the core with values,
     and performs the effects the core's return value describes.
   - `app/main.py` is the composition root: it picks concrete implementations
     and wires them. Nothing imports `app.main`.
   - Dependencies point inward: shell → core, never core → shell.

2. **No repository port in the core.** The business rule is a pure function that
   takes domain *values* (`change_display_name(user, raw) -> Result[...]`). It
   does not take a store, a repository, or any I/O interface. Loading and saving
   happen in the shell, around the call. A `Protocol` is allowed **only** in the
   shell (`app/shell/user_store.py`) and **only** to choose between
   genuinely-multiple production backends (`SqliteUserStore` (default),
   `InMemoryUserStore`, `PostgresUserStore`) — never to make the core testable.
   If you can test it by passing a value, you don't need the Protocol. For the
   full menu of ways to make a boundary swappable in this paradigm, see
   [`MODULARITY.md`](./MODULARITY.md).

3. **Parse, don't validate.** Untyped input (`str`, request bodies, DB rows)
   becomes a typed domain value once, at the boundary, via a smart constructor
   (`Email.parse`, `DisplayName.parse`) or Pydantic. Core function signatures
   take `Email`/`DisplayName`/`User`, never bare `str`/`dict`. A smart
   constructor's `parse` returns a `Result` for untrusted input; its
   `__post_init__` raises (a panic) so direct construction can't bypass the
   invariant either (§9).

4. **Pick the right error tool (§6).**
   - Expected domain outcome the caller branches on → `Result[T, E]` with a
     typed error (e.g. `EmptyDisplayName`). Never `raise` for these.
   - Plain absence ("no such user") → `T | None`, handled in the shell.
   - Programmer/data error that's "impossible" → let it raise (panic). `.unwrap()`
     a `Result` only where a failure would be a bug (e.g. parsing data we wrote).

5. **Immutability.** `@dataclass(frozen=True, slots=True)` for all domain types.
   "Update" is `dataclasses.replace`, returning a new value. No mutation of
   arguments, no module-level mutable state.

6. **Framework types stay in the shell.** Pydantic models, `HTTPException`, SQL,
   status codes — all live under `app/shell/`. The core never sees them.

7. **Python 3.14 idioms.** PEP 695 generics (`class Ok[T]`, `type Result[T, E] =
   …`). No `from __future__ import annotations` — PEP 649 defers evaluation, so
   forward references already work. Do **not** hide type-only imports behind
   `if TYPE_CHECKING` when Pydantic/Typer may read annotations at runtime (that
   is why ruff's `TCH` is deliberately off, and why `Result` is a runtime import
   in `app/core/user.py`).

## How to add a feature (recipe)

To add, say, a "change email" capability:

1. If there's a new constrained value, add a smart constructor in
   `app/core/user.py` (you already have `Email.parse`).
2. Express the rule as a **pure function** in `app/core/` returning a `Result`
   with a typed error for each expected failure. No store parameter.
3. Add a route to `app/shell/http.py` (and/or a CLI command): load the entity
   (I/O), call the pure function, `match` the `Result`, save on success (I/O),
   map errors to status codes. Add the request/response Pydantic models here.
4. If persistence changed, update the concrete stores (`memory_store.py`,
   `sqlite_store.py`, `postgres_store.py`) and keep the `UserStore` Protocol in
   `app/shell/user_store.py` in sync.
5. Tests: one for the pure function passing **values** (no fake, no mock —
   mirror `tests/test_user.py`); one for the shell via `create_app` (mirror
   `tests/test_http.py`). Add a hypothesis property if the core invariant is
   worth stating for all inputs.

## Commands

- Run: `uv run uvicorn app.main:app --reload`
- CLI: `uv run python -m app.shell.cli add <id> <email> <name>` and
  `uv run python -m app.shell.cli rename <id> <new_name>`
- Test: `uv run pytest`
- Type-check (part of the gate, not optional — §13): `uv run --extra postgres mypy`
  (the extra installs SQLAlchemy so the Postgres store is checked against real types)
- Lint: `uv run ruff check .`
- Postgres backend deps: `uv sync --extra postgres`

## Anti-patterns to reject

- Reintroducing a repository/store `Protocol` that the **core** depends on, or
  passing a store into a core function "so it can be tested."
- Mocking or faking code you wrote to test it — if a test needs that, push the
  logic into a pure function instead (§14.4).
- `raise` for an expected domain outcome (use `Result`); `Result` for an
  unrecoverable one (let it raise).
- Bare `str`/`dict[str, Any]` in `app/core/` signatures; `bool`/`Optional` field
  combinations that encode a hidden state machine.
- Importing `fastapi`/`sqlalchemy`/`pydantic` anywhere under `app/core/`.
- Business logic in a route handler — the handler is shell; it loads, calls the
  core, and performs effects.
