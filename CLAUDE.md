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
   happen in the shell, around the call. Store `Protocol`s are allowed **only** in
   the shell (`app/shell/stores.py`: `UserStore`/`TeamStore`/`MembershipStore`,
   composed into `Store`) and **only** to choose between genuinely-multiple
   production backends (`SqliteStore` (default), `InMemoryStore`, `PostgresStore`)
   — never to make the core testable. If you can test it by passing a value, you
   don't need the Protocol. For the full menu, see [`MODULARITY.md`](./MODULARITY.md).

3. **Parse, don't validate.** Untyped input (`str`, request bodies, DB rows)
   becomes a typed domain value once, at the boundary, via a smart constructor
   (`Email.parse`, `DisplayName.parse`) or Pydantic. Core function signatures
   take `Email`/`DisplayName`/`User`, never bare `str`/`dict`. A smart
   constructor's `parse` returns a `Result` for untrusted input; its
   `__post_init__` raises (a panic) so direct construction can't bypass the
   invariant either (§9).

4. **Pick the right error tool (§6).**
   - Expected domain outcome the caller branches on → `Result[T, E]` with a
     typed error value that subclasses the `DomainError` marker (e.g.
     `EmptyDisplayName`; a plain marker, never `Exception`). Don't `raise` these.
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
   in the core modules).

8. **Store layout (how it scales).** Interfaces segregated by entity in
   `app/shell/stores.py`; one backend class implements them all over one database
   (entity-prefixed methods: `get_user`, `get_team`, …). One core module per
   entity (`user.py`, `team.py`, `membership.py`), sharing `errors.py` and
   `result.py`. Adding an entity = a new core module + a focused Protocol + its
   methods in *every* backend. Let coordination (multi-table loads) accrete in
   the shell; the core stays values-in, values-out.

9. **Atomicity for multi-step operations.** If a shell operation does more than
   one write (a cascade delete, "create team + founding admin"), wrap it in
   `with store.unit_of_work() as tx:` and write through `tx` — all writes commit
   together or roll back together (SQL backends use one transaction; the in-memory
   store snapshots/restores). A cross-table policy like cascade is shell work done
   uniformly, **not** a DB feature (`ON DELETE CASCADE`) you lean on — the FK stays
   a backstop, and the rollback path is the same code in tests and prod.

## How to add a feature (recipe)

To add, say, a "change email" capability:

1. If there's a new constrained value, add a smart constructor in
   `app/core/user.py` (you already have `Email.parse`).
2. Express the rule as a **pure function** in `app/core/` returning a `Result`
   with a typed error for each expected failure. No store parameter.
3. Add a route to `app/shell/http.py` (and/or a CLI command): load the entity
   (I/O), call the pure function, `match` the `Result`, save on success (I/O),
   map errors to status codes. Add the request/response Pydantic models here. If
   success means more than one write, wrap them in `with store.unit_of_work():`.
4. If persistence changed, add the method to the right Protocol in
   `app/shell/stores.py` and implement it in **every** backend (`memory_store.py`,
   `sqlite_store.py`, `postgres_store.py`). A whole new entity = a new
   `app/core/<entity>.py` + a focused Protocol in `stores.py` + its methods in
   each backend.
5. Tests: one for the pure function passing **values** (no fake, no mock —
   mirror `tests/test_user.py`); one for the shell via `create_app` (mirror
   `tests/test_http.py`). Add a hypothesis property if the core invariant is
   worth stating for all inputs.

## Commands

- Run: `uv run uvicorn app.main:app --reload`
- CLI: `uv run python -m app.shell.cli --help` (commands: `add-user`,
  `rename-user`, `delete-user`, `add-team`, `add-member`, `update-role`,
  `remove-member`, `memberships`)
- Test: `uv run pytest` — add `--extra postgres` to also run the real-Postgres
  integration tests (testcontainers; needs Docker; they skip cleanly otherwise)
- Type-check (part of the gate, not optional — §13): `uv run --extra postgres mypy`
  (the extra installs SQLAlchemy so the Postgres store is checked against real types)
- Format & organize imports: `uv run ruff format . && uv run ruff check --fix .`
  — let ruff wrap long lines and sort imports; don't hand-wrap or hand-sort.
- Lint (gate, check-only): `uv run ruff check .`
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
