# User Profile — Functional Core / Imperative Shell

A tiny, working service (create a user and change their display name, over HTTP
or CLI), written as a toy to reason about
[`python_guidelines.md`](./python_guidelines.md).

It started life as a Ports & Adapters (Hexagonal) POC built around a
`UserRepository` port. The guidelines argue that such a port — a `Protocol`
introduced so a pure core can be tested against a fake — is usually an
over-engineering reflex (§2, Corollary 2):

> A pure core never calls the service — the shell does. You don't need a
> `UserRepository` interface to swap CSV for Postgres; you swap the shell function.

So this version keeps the **same feature** but moves the repository anti-pattern
out and follows the rules that apply at this size. Targets Python 3.14 (PEP 695
generics, PEP 649 deferred annotations).

## The one idea

Split the program in two:

```
            HTTP request / CLI args                    SQLite / memory / Postgres
                     │                                            ▲
                     ▼                                            │
        ┌─────────────────────────┐                  ┌───────────────────────────┐
        │   IMPERATIVE SHELL       │   User value     │   IMPERATIVE SHELL         │
        │   app/shell/http.py      │ ───────────────▶ │   app/shell/sqlite_store.py│
        │   app/shell/cli.py       │ ◀─────────────── │   does the I/O             │
        │   reads input, performs  │   Result value   └───────────────────────────┘
        │   the effects            │
        └─────────────────────────┘
                     │  passes a value, gets a value back
                     ▼
        ┌─────────────────────────┐    create_user(id, email, name) -> Result
        │   FUNCTIONAL CORE        │    change_display_name(user, raw) -> Result
        │   app/core/user.py       │    pure: no I/O, no store, no exceptions
        └─────────────────────────┘        for domain outcomes, no mocks to test
```

The **core** computes values and returns them. The **shell** reads input from
the world, hands values to the core, and performs the effects the core's return
value describes. Dependencies still point inward — `app/core/` imports nothing
from `app/shell/` or any framework — but there is no port the core depends on.

## What changed from the Hexagonal version, and why

| Hexagonal POC | This version | Guideline |
|---|---|---|
| `UpdateUserProfileService` calls `repo.get`/`repo.save` | `create_user` / `change_display_name` are pure functions over values | §2 functional core |
| `UserRepository` **port** the use case depends on | no port in the core; a `UserStore` Protocol lives in the *shell* (`user_store.py`), only because there are real backends | §2 Corollary 2 + the §2 carve-out |
| `update_profile` mutates the user, raises `ValueError`/`LookupError` | frozen `User`; bad input → `Err(...)`; missing user → `None` | §3.1, §7.3, §7.2, §11 |
| `email: str`, `display_name: str` | `Email`, `DisplayName` — parsed at the edge, invariant enforced by `__post_init__` | §8, §9 |
| Test builds a fake `InMemoryUserRepository` to test the rule | core test passes values, asserts a `Result` value | §14.4 |
| `app.dependency_overrides[...]` seam in prod and tests | `create_app(store)` — ordinary composition | (the seam only existed to inject past the port) |

The headline is in the tests: **`tests/test_user.py` constructs no fake and
patches nothing.** That is the payoff of moving I/O to the edges.

## Layout

```
app/
  core/                 FUNCTIONAL CORE — pure, no I/O, no framework, no mocks
    result.py           Ok / Err / Result, PEP 695 generics (§6, §7)
    user.py             Email, DisplayName (smart constructors §8/§9), frozen User,
                        create_user (collect-all §8), describe (assert_never §5),
                        change_display_name (pure §2/§12)
  shell/                IMPERATIVE SHELL — I/O at the edges
    user_store.py       UserStore Protocol — the shared persistence seam (§2 carve-out)
    memory_store.py     InMemoryUserStore   (tests / local)
    sqlite_store.py     SqliteUserStore     (default; stdlib sqlite3, file-backed)
    postgres_store.py   PostgresUserStore   (optional `postgres` extra)
    http.py             FastAPI adapter + create_app (POST /users, PUT …/profile)
    cli.py              Typer CLI — `add` and `rename`, same core
  main.py               composition root (pick a backend, build the app)
tests/
  test_user.py          the rules as pure functions — no fakes, no mocks
  test_sqlite_store.py  the store's real persistence, against a temp file
  test_http.py          the shell via create_app — no override seam
  test_properties.py    hypothesis property tests on the pure core (§13)
```

## Run

```bash
uv sync                       # core + dev tooling (SQLite needs no extra)
uv run uvicorn app.main:app --reload
```

Create a user, then rename them (the store is persistent — no seed):

```bash
curl -X POST localhost:8000/users \
  -H 'content-type: application/json' \
  -d '{"id": "1", "email": "ada@example.com", "display_name": "Ada"}'

curl -X PUT localhost:8000/users/1/profile \
  -H 'content-type: application/json' \
  -d '{"display_name": "Ada Lovelace"}'
```

The CLI is the same core, different shell (Typer). Because the SQLite store is
file-backed, `add` and `rename` are separate invocations — realistic, not a
fake-a-user-then-rename script:

```bash
uv run python -m app.shell.cli add 1 ada@example.com Ada
uv run python -m app.shell.cli rename 1 "Ada Lovelace"
uv run python -m app.shell.cli --help
```

## The quality gate

The guidelines treat the type checker as part of the language (§13), so the gate
is type-check + lint + test:

```bash
uv run --extra postgres mypy   # strict; --extra so the Postgres store is checked against real types
uv run ruff check .
uv run pytest
```

(`uv run mypy` without the extra also passes — the `sqlalchemy.*` override
tolerates the missing import — but you only get real type-checking of the
Postgres store when the extra is installed.)

## Swapping the backend

Change the one block in `app/main.py` — `SqliteUserStore` (default),
`InMemoryUserStore`, or `PostgresUserStore` (install the extra:
`uv sync --extra postgres`). No port is involved in the *core* — you swap one
concrete class for another at the composition root. `UserStore` (a `Protocol` in
`app/shell/user_store.py`) exists *only* because there are several real backends
to choose between; that is the legitimate use of a `Protocol` the guidelines
allow (§2, final paragraph), it lives in the shell, and the core never imports it.

For the full menu — passing data as values, shell-level Protocols, higher-order
functions, returning effects as data, and multiple front-ends — see
[`MODULARITY.md`](./MODULARITY.md): how to get every kind of modularity Ports &
Adapters gave you, in the core/shell paradigm.

## Extending

See [`CLAUDE.md`](./CLAUDE.md) for the conventions to follow when adding a
feature so the core stays pure and the discipline holds, and
[`MODULARITY.md`](./MODULARITY.md) for choosing how to make a boundary swappable.
