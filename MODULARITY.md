# Modularity in Core / Shell

How to get the modularity that Ports & Adapters gave you — swappable backends,
multiple front-ends, isolated testing — now that the `UserRepository` port is
gone and the code is split into a pure **core** and an imperative **shell**.

This is a companion to [`python_guidelines.md`](./python_guidelines.md) (§2),
grounded in this repo's `User` domain.

---

## The shift in one sentence

> **Hexagonal** keeps the core independent of infrastructure by **inverting** the
> dependency: the core defines a port, infrastructure implements it.
> **Core/Shell** keeps the core independent by **eliminating** the dependency:
> the core never references infrastructure at all.

Both keep the arrows pointing inward. The difference is that Core/Shell does it
with *fewer arrows*. There is no `UserRepository` interface for the core to
depend on, because the core (`change_display_name(user, raw) -> Result`) takes a
`User` value and returns a value — it has nothing to invert.

So "how does the core not care which shell implementation is used?" has a blunt
first answer: **the core doesn't reference any shell implementation, so there is
nothing to care about.** The interesting question is the next one down: *given
that, how do you organize multiple interchangeable implementations in the
shell?* That's a menu, below.

### Vocabulary map (coming from Hexagonal)

| Hexagonal concept | Core/Shell equivalent |
|---|---|
| Driven port (`UserRepository`) | usually **nothing** — pass data as values, or return effects as data; a *shell* `Protocol` only if there are ≥2 real backends |
| Driven adapter (`PostgresUserRepository`) | a concrete shell class (`PostgresUserStore`) |
| Driving port (`UpdateUserProfile`) | the **core function's signature** itself |
| Driving adapter (`api.py`, `cli.py`) | a shell entry point that calls the core function |
| Composition root + `dependency_overrides` | `create_app(store)` and ordinary function arguments |

---

## Part 1 — Output modularity ("swap Postgres for memory")

This is the case the question is really about: multiple implementations of an
*outbound* dependency, interchangeable without the core knowing. Here is the
menu, **in order of preference** — reach for the lightest one that fits.

### 1a. Pass the data the core needs as a value (the deepest answer)

If the core needs something *to decide*, fetch it in the shell and hand the core
a value. The core takes data; data has no backend identity, so there is nothing
to abstract.

```python
# shell — I/O, any backend you like
user = store.get(user_id)                 # InMemory? Postgres? the core can't tell

# core — pure, takes the value
result = change_display_name(user, raw_name)
```

This repo already works this way: `change_display_name` accepts a `User`, never
a store. Want the data to come from a cache, a CSV, an HTTP call? That's a pure
shell change; the core signature doesn't move. (If a feature needed price data,
the shell would load a `Catalog` value and pass it — guidelines §14.9.)

**When:** the dependency is a *read* the core consumes. This should be your
default; it removes the need for an interface entirely.

### 1b. Just use a concrete class — no interface at all

If there is exactly **one** real backend, write the concrete class and use it.
An interface with a single implementation is the smell the guidelines call out
(§2, Corollary 2). Add the abstraction the day the second implementation is
real, not before.

```python
# shell
store = InMemoryUserStore()
user = store.get(user_id)
...
store.save(updated)
```

**When:** one backend; or several backends whose orchestration genuinely differs
(then write distinct shell functions rather than one parameterized path).

### 1c. A `Protocol` — but in the shell, for real polymorphism

When you have **two or more real backends** *and* want a single shell code path
to work with any of them (instead of duplicating the load→decide→save
orchestration per backend), define a `Protocol`. This is what this repo does:

```python
# app/shell/user_store.py  — the Protocol lives in the shell, NOT the core,
# and not inside the HTTP adapter (the CLI builds on the same stores).
class UserStore(Protocol):
    def get(self, user_id: UserId) -> User | None: ...
    def save(self, user: User) -> None: ...

# app/shell/http.py  — one code path, any backend
def create_app(store: UserStore) -> FastAPI:
    ...

# app/main.py  — composition picks one
_store = SqliteUserStore()          # or InMemoryUserStore(), or PostgresUserStore(dsn=...)
app = create_app(_store)
```

`SqliteUserStore`, `InMemoryUserStore`, and `PostgresUserStore` satisfy it
structurally. This *looks* like the old `UserRepository` port, and the
distinction is the whole point:

- The old port was imported by the **use case** (the core) and existed so the
  core could be tested against a fake. That coupled logic to an I/O interface.
- `UserStore` is imported only by **shell** code, exists because there are three
  production backends, and the core is tested *without* it (pass a `User`,
  assert a `Result`). The guidelines explicitly bless this use (§2, final
  paragraph): "valuable when you genuinely have multiple production
  implementations."

**Litmus test:** if your only reason for the `Protocol` is "so I can inject a
fake in tests," delete it — you have 1b, not 1c. If the second implementation
ships to production, keep it.

### 1d. A higher-order function (lightweight, one-method boundaries)

When the boundary is a single operation, passing a function is lighter than
declaring a named type and gives the same swappability:

```python
# shell orchestration parameterized by how to persist
def persist_rename(
    save: Callable[[User], None],   # how to persist — swap without a named interface
    user: User,
    raw_name: str,
) -> Result[User, EmptyDisplayName]:
    result = change_display_name(user, raw_name)
    if isinstance(result, Ok):
        save(result.value)          # shell effect, explicit — not buried in a .map
    return result

# composition: persist_rename(InMemoryUserStore().save, user, raw)
#              persist_rename(PostgresUserStore(dsn).save, user, raw)
```

Note this parameterizes a **shell** orchestrator, and the effect (`save`) is
performed explicitly, not hidden inside a transformation. The pure core
(`change_display_name`) still takes no functions — pushing a callable into the
core would put I/O back into it.

**When:** the boundary is one or two functions; a full `Protocol` feels heavy.

### 1e. Return effects as data; let the shell interpret them

For *write* effects, the core can return a **description** of what should happen,
and the shell interprets it against whatever backend. This is the strongest
decoupling: the core decides *what*, the shell owns *how* and *where*
(guidelines §2, Corollary 1).

```python
# core — returns commands, performs nothing (illustrative; richer than this repo needs)
@dataclass(frozen=True)
class SaveUser:    user: User
@dataclass(frozen=True)
class SendWelcome: to: Email

Effect = SaveUser | SendWelcome

def change_display_name(user: User, raw: str) -> Result[list[Effect], EmptyDisplayName]:
    return DisplayName.parse(raw).map(lambda n: [SaveUser(rename(user, n))])

# shell — one interpreter per backend / per delivery; swap freely
def interpret(effects: list[Effect], store: UserStore, mailer: Mailer) -> None:
    for e in effects:
        match e:
            case SaveUser(u):    store.save(u)
            case SendWelcome(to): mailer.send(to)
```

Multiple shells can interpret the same command list differently (a test
interpreter that records calls; a prod interpreter that writes Postgres and
sends email). The core stays a pure function from input to a list of intents.

**When:** the effect set is genuinely variable ("save *and* email *and* emit a
metric") or you want to assert on *intended* effects in a pure test. For a lone
`save`, this is over-abstraction — 1a/1c are enough. This repo deliberately does
**not** use it.

---

## Part 2 — Input modularity ("HTTP, CLI, and a queue")

Hexagonal needed a *driving port* (`UpdateUserProfile`) that each front-end
called. Core/Shell doesn't: **the core function's signature is the contract.**
Every delivery mechanism is just a shell that reads its input, calls the
function, and renders the result.

```python
# app/shell/http.py
match change_display_name(user, body.display_name):
    case Ok(updated): store.save(updated); return _to_response(updated)
    case Err(_):      raise HTTPException(422, "display_name cannot be empty")

# app/shell/cli.py — same call, different I/O (Typer)
match change_display_name(user, new_display_name):
    case Ok(updated): store.save(updated); typer.echo(f"renamed {updated.id}")
    case Err(_):      typer.echo("invalid", err=True); raise typer.Exit(1)
```

Adding a Kafka consumer or a gRPC handler is another shell module making the
same call. There is no interface to define — `change_display_name`'s type *is*
the port, and the type checker enforces it at every call site.

---

## Part 3 — Testing modularity

| | Hexagonal | Core/Shell |
|---|---|---|
| Business logic | inject a **fake** repo into the use case | call the **pure function** with values; no fake, no mock |
| Shell wiring | integration test through the port + override seam | integration test through `create_app(store)` with a real in-memory store |

Two rules carry over from the guidelines:

- **Never mock the core.** It's pure; pass values, assert values (§14.4). If a
  test tempts you to patch something inside the core, the design has leaked I/O
  into it — push that I/O out to the shell.
- **For the shell `Protocol`, prefer a real in-memory implementation over a
  mock.** `InMemoryUserStore` *is* the test double — it's a genuine
  implementation, not a stand-in, so tests exercise real behavior.

---

## Decision guide

| You have… | Use | In this repo |
|---|---|---|
| the core needs data to decide | **pass the data as a value** (1a) | `change_display_name(user, …)` |
| exactly one real backend | **concrete class**, no interface (1b) | — (we have three) |
| ≥2 real backends, shared shell path | **`Protocol` in the shell** (1c) | `UserStore` + three stores |
| a one-method boundary, ≥2 impls | **higher-order function** (1d) | — |
| a variable set of write effects | **return effect data, shell interprets** (1e) | — (deliberately not) |
| multiple front-ends | **a shell per entry point**, same core call (Part 2) | `http.py`, `cli.py` |

---

## The one rule that makes all of this safe

Every technique above lives **in the shell**. The Protocol (1c), the callable
(1d), the interpreter (1e), the front-end handlers (Part 2) — all of them sit on
the shell side of the line. The core (`app/core/`) imports nothing from
`app/shell/`, references no storage, and performs no effect.

That invariant is what lets the core "not care" about any shell implementation:
not because of a clever abstraction between them, but because there is no
dependency there at all. The most modular boundary is the one that isn't there.
