# Users & Teams — Functional Core / Imperative Shell

A small, working service — create users and teams, and manage a user's
membership (member/admin) in a team, over HTTP or CLI — written as a toy to
reason about [`python_guidelines.md`](./python_guidelines.md).

It started life as a Ports & Adapters (Hexagonal) POC built around a
`UserRepository` port. The guidelines argue that such a port — a `Protocol`
introduced so a pure core can be tested against a fake — is usually an
over-engineering reflex (§2, Corollary 2):

> A pure core never calls the service — the shell does. You don't need a
> `UserRepository` interface to swap CSV for Postgres; you swap the shell function.

So the core has no port; storage lives in the shell. Targets Python 3.14 (PEP 695
generics, PEP 649 deferred annotations).

## The one idea

Split the program in two:

```
        HTTP request / CLI args                  SQLite / memory / Postgres
                 │                                  one Store, 3 tables
                 ▼                                  (users, teams, memberships)
    ┌─────────────────────────┐              ┌───────────────────────────┐
    │   IMPERATIVE SHELL       │  values      │   IMPERATIVE SHELL         │
    │   http.py / cli.py       │ ───────────▶ │   *_store.py               │
    │   reads input, loads,    │ ◀─────────── │   does the I/O             │
    │   performs the effects   │  Result      └───────────────────────────┘
    └─────────────────────────┘
                 │  passes values, gets a value back
                 ▼
    ┌─────────────────────────┐   create_user(...) / change_display_name(...)
    │   FUNCTIONAL CORE        │   create_team(...) / add_member(user, team, role, existing)
    │   app/core/*.py          │   pure: no I/O, no store, no exceptions for
    └─────────────────────────┘   domain outcomes, no mocks to test
```

The **core** computes values and returns them. The **shell** reads input from the
world, hands values to the core, and performs the effects the core's return value
describes. Dependencies point inward — `app/core/` imports nothing from
`app/shell/` or any framework — and there is no port the core depends on.

## Layout

```
app/
  core/                 FUNCTIONAL CORE — pure, no I/O, no framework, no mocks
    result.py           Ok / Err / Result, PEP 695 generics (§6, §7)
    errors.py           DomainError marker (shared once a 2nd domain needed it)
    user.py             Email, DisplayName, User; create_user, change_display_name
    team.py             TeamName, Team; create_team
    membership.py       MembershipRole, Membership; add_member / change_role / remove_member
                        (total transitions over `Membership | None`, §4)
    accounts.py         cross-aggregate rule: can't delete a user who is a team's sole admin
  shell/                IMPERATIVE SHELL — I/O at the edges
    stores.py           UserStore / TeamStore / MembershipStore Protocols + combined Store
                        (incl. unit_of_work for atomic multi-step operations)
    memory_store.py     InMemoryStore   (tests / local; UoW = snapshot/restore)
    db_types.py         typed table schema (SQLAlchemy declarative, metadata only — no Session)
    sql_store.py        SqlStore        (SQLite by default or Postgres — the engine decides;
                                         Engine or Connection; 3 tables, FKs)
    http.py             FastAPI adapter + create_app
    cli.py              Typer CLI — one command per operation
  main.py               composition root (pick a backend, build the app)
tests/
  test_user/team/membership/accounts.py   pure core — no fakes, no mocks
  test_store.py         the SQLite store across all 3 tables (temp file)
  test_unit_of_work.py  atomicity: commit / rollback over memory + sqlite
  test_http.py, test_cli.py   the shell via create_app and Typer's CliRunner
  test_postgres_integration.py   real Postgres via testcontainers (needs Docker; auto-skips)
  test_properties.py    hypothesis property tests on the pure core (§13)
```

## How the store scaled when Teams were added

This is the interesting part. Adding a second entity (`Team`) and an association
(`Membership`) is where a store design either holds up or rots. Two choices kept
it sane:

1. **Segregated interfaces, unified implementation.** `stores.py` defines a
   focused Protocol per entity (`UserStore`, `TeamStore`, `MembershipStore`) and
   composes them into one `Store`. But there is still **one** backend class per
   backend — `SqlStore` owns all three tables, one engine, foreign keys.
   So adding an entity is "a focused Protocol + a few methods on each backend,"
   never a new abstraction the *core* depends on. Methods are entity-prefixed
   (`get_user`, `get_team`, `get_membership`) precisely because one object serves
   all three.

2. **Complexity accretes in the shell, not the core.** The core transition stays
   a one-liner — `add_member(user, team, role, existing)` is pure and total over
   `Membership | None`. What grows is the *shell* orchestration: "add a member"
   now loads the user, loads the team, loads the existing membership (three
   reads across tables) before the pure decision and the write. The core never
   learns that storage got more complicated, so its tests never change.

Two costs worth seeing plainly:

- **The N×M tax.** Every method in `stores.py` must be implemented in *every*
  backend (memory, sql — the sql one at least serves both dialects from one
  typed schema). More operations × more backends = linear
  growth. That is the real price of keeping multiple backends — and the reason
  §2 says to keep a store `Protocol` only when you genuinely have several
  production implementations.
- **Multi-step operations must be atomic.** A cascade delete, or "create team +
  founding admin," is several writes; a failure mid-way must not leave half-written
  state. The shell wraps these in `store.unit_of_work()`: the SQL backends run one
  transaction (all commit, or all roll back), and the in-memory store snapshots
  and restores — so the rollback path is the *same code* in tests and prod.
  (`unit_of_work` is itself one more method on every backend — the N×M tax again.)

See [`MODULARITY.md`](./MODULARITY.md) for the full menu of ways to keep a
boundary swappable in this paradigm.

## Run

```bash
uv sync                       # core + dev tooling (SQLite needs no extra)
uv run uvicorn app.main:app --reload
```

```bash
curl -X POST localhost:8000/users -H 'content-type: application/json' \
  -d '{"id": "u1", "email": "ada@example.com", "display_name": "Ada"}'
curl -X POST localhost:8000/users -H 'content-type: application/json' \
  -d '{"id": "u2", "email": "bob@example.com", "display_name": "Bob"}'
curl -X POST localhost:8000/teams -H 'content-type: application/json' \
  -d '{"id": "t1", "name": "Core", "admin_user_id": "u1"}'   # a team is created with an admin
curl -X POST localhost:8000/teams/t1/members -H 'content-type: application/json' \
  -d '{"user_id": "u2", "role": "member"}'
curl -X PUT  localhost:8000/teams/t1/members/u2 -H 'content-type: application/json' \
  -d '{"role": "admin"}'
curl localhost:8000/users/u2/memberships
curl -X DELETE localhost:8000/teams/t1/members/u2
curl -X DELETE localhost:8000/users/u2     # delete user — cascades memberships, atomically
```

The CLI is the same core, different shell (Typer). SQLite is file-backed, so each
command is a separate, realistic invocation:

```bash
uv run python -m app.shell.cli add-user u1 ada@example.com Ada
uv run python -m app.shell.cli add-user u2 bob@example.com Bob
uv run python -m app.shell.cli add-team t1 Core u1        # u1 is the founding admin
uv run python -m app.shell.cli add-member t1 u2 member
uv run python -m app.shell.cli update-role t1 u2 admin
uv run python -m app.shell.cli memberships u2
uv run python -m app.shell.cli remove-member t1 u2
uv run python -m app.shell.cli delete-user u2            # cascades memberships, atomically
uv run python -m app.shell.cli --help
```

## The quality gate

```bash
uv run ty check                 # type-check (ty — Astral's checker; part of the gate)
uv run ruff check .
uv run --extra postgres pytest  # also runs the real-Postgres integration tests (needs Docker)
```

`uv run pytest` (no extra, no Docker) runs everything except the Postgres
integration tests, which skip cleanly. Those start one throwaway Postgres
container via testcontainers, create the schema **once**, and run each test in a
transaction rolled back at the end (savepoints for nested writes) — fast and
isolated. `uv run ty check` checks the SQL store against SQLAlchemy's real
types (it is a base dependency; the `postgres` extra only adds the driver).

## Swapping the backend

Change the one block in `app/main.py` — `SqlStore` over a SQLite engine
(default) or a Postgres one (install the driver: `uv sync --extra postgres`),
or `InMemoryStore`. No port is
involved in the *core* — you swap one concrete `Store` for another at the
composition root. The segregated Protocols in `app/shell/stores.py` are the
legitimate use of a `Protocol` the guidelines allow (§2, final paragraph):
several real backends, in the shell, never imported by the core.

## Extending

See [`CLAUDE.md`](./CLAUDE.md) for the conventions to follow when adding a feature
so the core stays pure and the discipline holds, and [`MODULARITY.md`](./MODULARITY.md)
for choosing how to make a boundary swappable.
