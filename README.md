# Users & Teams - Functional Core / Imperative Shell

A small but working service: create users and teams, and manage a user's
membership in a team as either a member or an admin, over HTTP or a CLI. It's a
toy for working through the ideas in
[`python_guidelines.md`](./python_guidelines.md).

It started as a Ports & Adapters (Hexagonal) POC built around a `UserRepository`
port. The guidelines treat that kind of port - a `Protocol` you add so a pure core
can be tested against a fake - as over-engineering (§2, Corollary 2):

> A pure core never calls the service - the shell does. You don't need a
> `UserRepository` interface to swap CSV for Postgres; you swap the shell function.

So the core has no port, and storage lives in the shell. The code targets Python
3.14 and uses PEP 695 generics and PEP 649 deferred annotations.

## The one idea

Split the program in two:

```
        HTTP request / CLI args                  SQLite / memory / Postgres
                 │                                  one Store, 3 tables
                 ▼                                  (users, teams, memberships)
    ┌─────────────────────────┐               ┌────────────────────────────┐
    │   IMPERATIVE SHELL      │  values       │   IMPERATIVE SHELL         │
    │   http.py / cli.py      │ ────────────▶ │   *_store.py               │
    │   reads input, loads,   │ ◀──────────── │   does the I/O             │
    │   performs the effects  │  Result       └────────────────────────────┘
    └─────────────────────────┘
                 │  passes values, gets a value back
                 ▼
    ┌─────────────────────────┐   create_user(...) / change_display_name(...)
    │   FUNCTIONAL CORE       │   create_team(...) / add_member(user, team, role, existing)
    │   app/core/*.py         │   pure: no I/O, no store, no exceptions for
    └─────────────────────────┘   domain outcomes, no mocks to test
```

The core takes values and returns values. The shell reads input from the world,
hands those values to the core, and carries out whatever effects the core's return
value asks for. Dependencies point inward: `app/core/` imports nothing from
`app/shell/` and nothing from any framework, and there's no port for the core to
depend on.

## Layout

```
app/
  core/                 FUNCTIONAL CORE - pure, no I/O, no framework, no mocks
    result.py           Ok / Err / Result, PEP 695 generics (§6, §7)
    errors.py           DomainError marker (shared once a 2nd domain needed it)
    user.py             Email, DisplayName, User; create_user, change_display_name
    team.py             TeamName, Team; create_team
    membership.py       MembershipRole, Membership; add_member / change_role / remove_member
                        (total transitions over `Membership | None`, §4)
    accounts.py         cross-aggregate rule: can't delete a user who is a team's sole admin
  shell/                IMPERATIVE SHELL - I/O at the edges
    database/           the persistence package - create_store(url) + run_migrations(url)
      stores.py         UserStore / TeamStore / MembershipStore Protocols + combined Store
                        (incl. unit_of_work for atomic multi-step operations)
      memory_store.py   InMemoryStore   (tests / local; UoW = snapshot/restore)
      types.py          typed table schema (SQLAlchemy declarative, metadata only - no Session)
      sql_store.py      SqlStore        (SQLite by default or Postgres - the engine decides;
                                         Engine or Connection; 3 tables, FKs; no DDL)
      migrations/       alembic env + versions - the schema's single owner
    http.py             FastAPI adapter + create_app
    cli.py              Typer CLI - one command per operation
  main.py               composition root (pick a backend, build the app)
tests/
  test_user/team/membership/accounts.py   pure core - no fakes, no mocks
  test_store.py         the SQLite store across all 3 tables (temp file)
  test_unit_of_work.py  atomicity: commit / rollback over memory + sqlite
  test_http.py, test_cli.py   the shell via create_app and Typer's CliRunner
  test_postgres_integration.py   real Postgres via testcontainers (needs Docker; auto-skips)
  test_properties.py    hypothesis property tests on the pure core (§13)
```

## How the store scaled when Teams were added

This is the interesting part. Adding a second entity (`Team`) and an association
(`Membership`) is the moment a store design shows whether it was any good. Two
decisions kept it manageable.

1. **Segregated interfaces, one implementation.** `stores.py` defines a focused
   Protocol per entity (`UserStore`, `TeamStore`, `MembershipStore`) and composes
   them into a single `Store`. There's still one backend class per backend, though:
   `SqlStore` owns all three tables, one engine, and the foreign keys between them.
   Adding an entity means writing a focused Protocol and a few methods on each
   backend, and the core never gains an abstraction to depend on. The methods carry
   an entity prefix (`get_user`, `get_team`, `get_membership`) because one object
   serves all three.

2. **Complexity accretes in the shell.** The core transition stays a one-liner:
   `add_member(user, team, role, existing)` is pure and total over `Membership |
   None`. What grows is the shell orchestration. "Add a member" now loads the user,
   the team, and any existing membership - three reads across tables - before the
   pure decision and the write. The core never finds out that storage got more
   complicated, so its tests don't change.

Two costs come with this:

- **The N×M tax.** Every method in `stores.py` has to be implemented in *every*
  backend (memory and sql, with the sql one at least covering both dialects from a
  single typed schema). More operations times more backends is linear growth, and
  that's the real price of keeping multiple backends. It's also why §2 says to keep
  a store `Protocol` only when you actually ship several production implementations.
- **Multi-step operations have to be atomic.** A cascade delete, or "create team
  plus founding admin," is several writes, and a failure partway through must not
  leave half-written state. The shell wraps these in `store.unit_of_work()`: the
  SQL backends run one transaction that commits or rolls back as a unit, and the
  in-memory store snapshots and restores. The rollback path is the same code in
  tests and in production. (`unit_of_work` is one more method on every backend -
  the N×M tax again.)

See [`MODULARITY.md`](./MODULARITY.md) for the full menu of ways to keep a
boundary swappable in this paradigm.

## Run

```bash
# core plus dev tooling (SQLite needs no extra)
uv sync

# migrations own the schema, so set it up before first run
uv run alembic upgrade head

# start the API with autoreload
uv run uvicorn app.main:app --reload
```

```bash
# create two users
curl -X POST localhost:8000/users -H 'content-type: application/json' \
  -d '{"id": "u1", "email": "ada@example.com", "display_name": "Ada"}'

curl -X POST localhost:8000/users -H 'content-type: application/json' \
  -d '{"id": "u2", "email": "bob@example.com", "display_name": "Bob"}'

# create a team; it comes with its first admin
curl -X POST localhost:8000/teams -H 'content-type: application/json' \
  -d '{"id": "t1", "name": "Core", "admin_user_id": "u1"}'

# add u2 to the team as a plain member
curl -X POST localhost:8000/teams/t1/members -H 'content-type: application/json' \
  -d '{"user_id": "u2", "role": "member"}'

# promote u2 to admin
curl -X PUT localhost:8000/teams/t1/members/u2 -H 'content-type: application/json' \
  -d '{"role": "admin"}'

# list u2's memberships
curl localhost:8000/users/u2/memberships

# remove u2 from the team
curl -X DELETE localhost:8000/teams/t1/members/u2

# delete u2 entirely; their memberships cascade in one transaction
curl -X DELETE localhost:8000/users/u2
```

The CLI runs the same core through a different shell (Typer). SQLite is
file-backed, so each command is a separate, realistic invocation against the same
migrated database as the API:

```bash
# create two users
uv run hex add-user u1 ada@example.com Ada
uv run hex add-user u2 bob@example.com Bob

# create a team with u1 as its founding admin
uv run hex add-team t1 Core u1

# add u2 as a member, then promote them to admin
uv run hex add-member t1 u2 member
uv run hex update-role t1 u2 admin

# inspect u2's memberships, then remove them from the team
uv run hex memberships u2
uv run hex remove-member t1 u2

# delete u2; memberships cascade in one transaction
uv run hex delete-user u2

# see every command
uv run hex --help
```

## The quality gate

```bash
# type-check with ty (Astral's checker)
uv run ty check

# lint
uv run ruff check .

# run the suite, including the real-Postgres integration tests (needs Docker)
uv run --extra postgres pytest
```

`uv run pytest` on its own (no extra, no Docker) runs everything except the
Postgres integration tests, which skip cleanly. Those tests spin up a throwaway
Postgres container with testcontainers, run the alembic migrations once - the same
way production sets the database up - and run each test inside a transaction that's
rolled back at the end, with savepoints for nested writes. That keeps them fast and
isolated. `uv run ty check` checks the SQL store against SQLAlchemy's real types;
SQLAlchemy is a base dependency, and the `postgres` extra only adds the driver.

## Swapping the backend

Change the one block in `app/main.py`. The choices are `SqlStore` over a SQLite
engine (the default), `SqlStore` over a Postgres engine (install the driver with
`uv sync --extra postgres`), or `InMemoryStore`. The core has no port in this, so
you're just swapping one concrete `Store` for another at the composition root. The
segregated Protocols in `app/shell/database/stores.py` are the one use of a
`Protocol` the guidelines bless (§2, final paragraph): they sit in the shell and
exist only because there really are several production backends. The core never
imports them.

## Extending

See [`CLAUDE.md`](./CLAUDE.md) for the conventions to follow when adding a feature
so the core stays pure and the discipline holds, and
[`MODULARITY.md`](./MODULARITY.md) for choosing how to make a boundary swappable.
