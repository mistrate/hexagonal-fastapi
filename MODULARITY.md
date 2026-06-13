# Modularity in Core / Shell

Ports & Adapters gave you swappable backends and multiple front-ends without the
core knowing. This is how you keep that once the `UserRepository` port is gone and
the code is split into a pure **core** and an imperative **shell**.

It's a companion to [`python_guidelines.md`](./python_guidelines.md) (§2), grounded
in this repo's users-and-teams domain.

---

## The shift in one sentence

> **Hexagonal** keeps the core independent of infrastructure by **inverting** the
> dependency: the core defines a port and infrastructure implements it.
> **Core/Shell** keeps it independent by **removing** the dependency: the core
> never references infrastructure at all.

Both point the dependencies inward; Core/Shell just has fewer of them to point.
There's no `UserRepository` interface for the core to depend on, because the core
(`change_display_name(user, raw) -> Result`) takes a `User` value and returns a
value. There's nothing to invert.

"How does the core not care which shell implementation is used?" has a short
answer: the core doesn't reference any shell implementation, so there's nothing to
care about. The real question is the next one. Given that, how do you organize
multiple interchangeable implementations in the shell? The rest of this doc is that
menu.

### Vocabulary map (coming from Hexagonal)

| Hexagonal concept | Core/Shell equivalent |
|---|---|
| Driven port (`UserRepository`) | usually **nothing**: pass data as values, or return effects as data; a *shell* `Protocol` only if there are ≥2 real backends |
| Driven adapter (`PostgresUserRepository`) | a concrete shell class (`SqlStore`) |
| Driving port (`UpdateUserProfile`) | the **core function's signature** itself |
| Driving adapter (`api.py`, `cli.py`) | a shell entry point that calls the core function |
| Composition root + `dependency_overrides` | `create_app(store)` and ordinary function arguments |

---

## Part 1 - Output modularity ("swap Postgres for memory")

This is what the question is usually about: several implementations of an
*outbound* dependency, interchangeable without the core knowing. The menu below is
**in order of preference** - reach for the lightest option that fits.

### 1a. Pass the data the core needs as a value (the deepest answer)

If the core needs something in order to decide, fetch it in the shell and hand the
core a value. The core takes data, and data carries no backend identity, so there's
nothing to abstract.

```python
# shell - I/O, any backend you like
user = store.get(user_id)                 # InMemory? Postgres? the core can't tell

# core - pure, takes the value
result = change_display_name(user, raw_name)
```

This repo already works this way: `change_display_name` takes a `User` value and
has no idea a store exists. If that data later needs to come from a cache or a CSV
file, that's a change in the shell, and the core signature doesn't move. (A feature
that needed price data would have the shell load a `Catalog` value and pass it in;
guidelines §14.9.)

**When:** the dependency is a *read* the core consumes. Make this your default; it
removes the need for an interface at all.

### 1b. Just use a concrete class (no interface at all)

If there's exactly **one** real backend, write the concrete class and use it. An
interface with a single implementation is the smell the guidelines call out (§2,
Corollary 2). Wait until the second implementation actually exists before reaching
for an abstraction.

```python
# shell
store = InMemoryStore()
user = store.get_user(user_id)
...
store.save_user(updated)
```

**When:** one backend. Or several backends whose orchestration genuinely differs,
in which case you write distinct shell functions instead of one parameterized path.

### 1c. A `Protocol` (in the shell, for real polymorphism)

When you have **two or more real backends** and want one shell code path to work
with any of them, instead of duplicating the load→decide→save orchestration per
backend, define a `Protocol`. That's what this repo does:

```python
# app/shell/database/stores.py - segregated per entity (NOT in the core or HTTP adapter)
class UserStore(Protocol):
    def get_user(self, user_id: UserId) -> User | None: ...
    def save_user(self, user: User) -> None: ...

# ...likewise TeamStore, MembershipStore... composed for the wiring:
class Store(UserStore, TeamStore, MembershipStore, Protocol): ...

# app/shell/http.py  - one code path, any backend
def create_app(store: Store) -> FastAPI:
    ...

# app/main.py  - one backend implements all of it (one DB, several tables)
_store = create_store()   # SQLite URL by default; or create_store(pg_url), or InMemoryStore()
app = create_app(_store)
```

`SqlStore` (one class, where the engine decides SQLite vs Postgres) and
`InMemoryStore` both implement it structurally. This looks like the old
`UserRepository` port, and the difference between them is the whole point:

- The old port was imported by the **use case** (the core), and it existed so the
  core could be tested against a fake. That coupled the logic to an I/O interface.
- These Protocols are imported only by **shell** code, and they exist because there
  genuinely are multiple production backends. The core is tested without them: you
  pass values and assert on a `Result`. The guidelines bless exactly this use (§2,
  final paragraph): "valuable when you genuinely have multiple production
  implementations."

**Litmus test:** if your only reason for the `Protocol` is "so I can inject a fake
in tests," delete it; what you have is 1b. Once the second implementation ships to
production, keep it.

### 1d. A higher-order function (lightweight, one-method boundaries)

When the boundary is a single operation, passing a function is lighter than
declaring a named type, and you get the same swappability:

```python
# shell orchestration parameterized by how to persist
def persist_rename(
    save: Callable[[User], None],   # how to persist; swap without a named interface
    user: User,
    raw_name: str,
) -> Result[User, EmptyDisplayName]:
    result = change_display_name(user, raw_name)
    if isinstance(result, Ok):
        save(result.value)          # shell effect, performed out in the open
    return result

# composition: persist_rename(InMemoryStore().save_user, user, raw)
#              persist_rename(SqlStore(engine).save_user, user, raw)
```

This parameterizes a **shell** orchestrator, and the effect (`save`) happens right
out in the open where you can see it. The pure core (`change_display_name`) still
takes no functions; pushing a callable into the core would drag I/O back into it.

**When:** the boundary is one or two functions and a full `Protocol` feels heavy.

### 1e. Return effects as data; let the shell interpret them

For *write* effects, the core can return a **description** of what should happen and
let the shell carry it out against whatever backend is wired up. This is the
strongest decoupling there is: the core decides what should happen, and the shell
decides how and where (guidelines §2, Corollary 1).

```python
# core - returns commands, performs nothing (illustrative; richer than this repo needs)
@dataclass(frozen=True)
class SaveUser:    user: User
@dataclass(frozen=True)
class SendWelcome: to: Email

Effect = SaveUser | SendWelcome

def change_display_name(user: User, raw: str) -> Result[list[Effect], EmptyDisplayName]:
    return DisplayName.parse(raw).map(lambda n: [SaveUser(rename(user, n))])

# shell - one interpreter per backend / per delivery; swap freely
def interpret(effects: list[Effect], store: UserStore, mailer: Mailer) -> None:
    for e in effects:
        match e:
            case SaveUser(u):    store.save_user(u)
            case SendWelcome(to): mailer.send(to)
```

Different shells can interpret the same command list in different ways: a test
interpreter that just records the calls, a production interpreter that writes to
Postgres and sends the email. The core stays a pure function from input to a list
of intents.

**When:** the effect set genuinely varies ("save *and* email *and* emit a metric"),
or you want to assert on *intended* effects in a pure test. For a lone `save` this
is over-abstraction, and 1a or 1c will do. This repo deliberately doesn't use it.

---

## Part 2 - Input modularity ("HTTP, CLI, and a queue")

Hexagonal needed a *driving port* (`UpdateUserProfile`) for each front-end to call.
Core/Shell skips it, because the core function's signature already **is** the
contract. Each delivery mechanism is a shell that reads its own input, calls the
function, and renders the result.

```python
# app/shell/http.py
match change_display_name(user, body.display_name):
    case Ok(updated): store.save(updated); return _to_response(updated)
    case Err(_):      raise HTTPException(422, "display_name cannot be empty")

# app/shell/cli.py - same call, different I/O (Typer)
match change_display_name(user, new_display_name):
    case Ok(updated): store.save(updated); typer.echo(f"renamed {updated.id}")
    case Err(_):      typer.echo("invalid", err=True); raise typer.Exit(1)
```

A Kafka consumer or a gRPC handler is just one more shell module making the same
call. There's no interface to define: `change_display_name`'s type is the port, and
the type checker enforces it at every call site.

---

## Part 3 - Testing modularity

| | Hexagonal | Core/Shell |
|---|---|---|
| Business logic | inject a **fake** repo into the use case | call the **pure function** with values; no fake, no mock |
| Shell wiring | integration test through the port + override seam | integration test through `create_app(store)` with a real in-memory store |

Two rules carry over from the guidelines:

- **Never mock the core.** It's pure: pass values, assert on the values you get
  back (§14.4). If a test makes you want to patch something inside the core, I/O has
  leaked into it, and the fix is to push that I/O out to the shell.
- **For the shell `Protocol`, use a real in-memory implementation instead of a
  mock.** `InMemoryStore` is the test double, and it's a genuine implementation, so
  the tests exercise real behavior.

---

## Decision guide

| You have… | Use | In this repo |
|---|---|---|
| the core needs data to decide | **pass the data as a value** (1a) | `change_display_name(user, …)` |
| exactly one real backend | **concrete class**, no interface (1b) | n/a (we have three) |
| ≥2 real backends, shared shell path | **`Protocol` in the shell** (1c) | segregated Protocols + `SqlStore`/`InMemoryStore` |
| a one-method boundary, ≥2 impls | **higher-order function** (1d) | n/a |
| a variable set of write effects | **return effect data, shell interprets** (1e) | n/a (deliberately not) |
| multiple front-ends | **a shell per entry point**, same core call (Part 2) | `http.py`, `cli.py` |

---

## The one rule that makes all of this safe

Every technique above lives **in the shell**: the Protocol (1c), the callable (1d),
the interpreter (1e), and the front-end handlers (Part 2). The core (`app/core/`)
imports nothing from `app/shell/`. It touches no storage and performs no effects.

That's the whole reason the core can ignore which shell implementation is wired in.
There's no clever abstraction between them doing the decoupling. There's just
nothing there to decouple in the first place.
