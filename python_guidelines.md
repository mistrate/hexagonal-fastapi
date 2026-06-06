# Python Writing Guidelines

A discipline for writing maintainable, testable Python code. Synthesized from the work of Gary Bernhardt[\[1\]](#ref-1)[\[2\]](#ref-2), Scott Wlaschin[\[3\]](#ref-3)[\[4\]](#ref-4)[\[5\]](#ref-5)[\[6\]](#ref-6)[\[7\]](#ref-7)[\[8\]](#ref-8), and Luis Vaz (Rastrian)[\[9\]](#ref-9).

The goal is not to write F# or Haskell in Python. The goal is to apply the small set of ideas these authors converge on — **separate logic from effects, encode invariants in types, make illegal states unrepresentable, prefer values over mutation** — using Python's native facilities (`dataclasses`, `typing`, `match`, `Enum`, Pydantic, mypy/pyright in strict mode).

---

## Table of Contents

1. [Core Philosophy](#1-core-philosophy) — the two questions to ask of every function and type.
2. [Functional Core, Imperative Shell](#2-functional-core-imperative-shell) — pure functions decide; the shell executes.
3. [Algebraic Data Types](#3-algebraic-data-types) — frozen dataclasses for products, tagged unions for sums; no invalid states.
4. [Make State Explicit](#4-make-state-explicit) — each lifecycle state is its own type carrying its own data.
5. [Pattern Matching and Exhaustiveness](#5-pattern-matching-and-exhaustiveness) — `match` + `assert_never`; new variants are type-checker errors.
6. [Three Classes of Errors](#6-three-classes-of-errors) — domain errors, panics, infrastructure errors; pick the right tool.
7. [Result and Option](#7-result-and-option) — values not exceptions; and when not to use Result.
8. [Parse, Don't Validate](#8-parse-dont-validate) — untyped input becomes typed values at the boundary, once.
9. [Smart Constructors and Branded Types](#9-smart-constructors-and-branded-types) — no primitive obsession.
10. [Pipelines and Composition](#10-pipelines-and-composition) — workflows as typed transformations.
11. [Immutability by Default](#11-immutability-by-default) — replace, don't mutate.
12. [Total Functions](#12-total-functions) — the type signature is the truth.
13. [Tooling and Project Setup](#13-tooling-and-project-setup) — `mypy --strict` is not optional.
14. [Anti-Patterns to Reject](#14-anti-patterns-to-reject) — ten smells with one-line demonstrations.
15. [A Worked Mini-Example](#15-a-worked-mini-example) — everything composed in one small program.
16. [When to Break These Rules](#16-when-to-break-these-rules) — engineering judgment beats dogma.
17. [Sources](#17-sources) — full citations.
18. [Skill Definition](#18-skill-definition) — copy-pasteable SKILL.md block.

---

## 1. Core Philosophy

Example: [`01_core_philosophy.py`](examples/src/python_style_examples/01_core_philosophy.py)

Two questions to ask of every module, function, and type:

1. **Can this thing be in a state it shouldn't?** If yes, change the type until it can't.
2. **Does this function do one of: compute a value, or perform an effect?** If it does both, split it.

The motivating bug, in one line:

```python
# ❌ Compiles. Runs. Wakes you up at 3am.
account = Account(is_active=True, is_suspended=True, is_closed=True)
```

```python
# ✅ The type system refuses to construct nonsense.
account = Account(state=Suspended(reason="kyc-review", until=tomorrow))
```

Most production incidents are not subtle algorithmic mistakes. They are values flowing into states the original author would have called "impossible" — a transaction both `pending` and `settled`, a `None` email reaching code that assumed an address, a config string that was never validated. The rules below push these errors to the place where they can be detected cheaply: the type checker, or the boundary where data enters the system.

---

## 2. Functional Core, Imperative Shell

Example: [`02_functional_core_imperative_shell.py`](examples/src/python_style_examples/02_functional_core_imperative_shell.py)

The single most important architectural rule. Bernhardt named it[\[1\]](#ref-1); Wlaschin refined it[\[8\]](#ref-8).

**Core (pure):** Takes values in, returns values out. No I/O, no mutation of arguments, no time, no randomness, no exceptions for control flow, no `async`. Same inputs → same outputs.

**Shell (imperative):** Reads input from the world (DB, network, files, env, stdin), passes values to the core, takes the core's returned value, and performs the effects the core described.

```python
# ❌ Logic and I/O entangled — untestable without mocking the world
def process_order(order_id: str) -> None:
    order = db.fetch_order(order_id)
    if order.total > 1000 and order.customer.tier == "gold":
        discount = order.total * 0.1
        order.total -= discount
        db.save(order)
        email.send(order.customer.email, f"Discount: {discount}")
```

```python
# ✅ Pure decision + thin shell that executes it
@dataclass(frozen=True)
class DiscountDecision:
    new_total: Decimal
    discount: Decimal
    notify: bool

def decide_discount(order: Order) -> DiscountDecision:        # pure
    if order.total > Decimal(1000) and order.customer.tier is CustomerTier.GOLD:
        d = order.total * Decimal("0.1")
        return DiscountDecision(order.total - d, d, notify=True)
    return DiscountDecision(order.total, Decimal(0), notify=False)

def process_order(order_id: str) -> None:                     # shell
    order = db.fetch_order(order_id)
    decision = decide_discount(order)
    db.save(replace(order, total=decision.new_total))
    if decision.notify:
        email.send(order.customer.email, f"Discount: {decision.discount}")
```

Tests for the core are dense, fast, example-based, and need **no mocks** — there is nothing to mock. The shell gets a small number of integration tests confirming the wiring.

**Three smells that say I/O has leaked into your core** (from Wlaschin's NDC talk[\[8\]](#ref-8)):

- The function uses `try/except` for domain logic. Push exception handling to the shell.
- The function is `async`. Async is an effect; the core is sync.
- The function calls a network/database/filesystem API directly.

**Heuristic:** if you reach for `unittest.mock.patch`, logic has probably leaked into the shell. Push it back.

**Corollary 1 — return data, not actions.** To express "send an email and write to the DB," the core returns a `DiscountDecision` (or a list of `Command` values). The shell interprets it.

**Corollary 2 — no abstraction is needed just to swap I/O.** A common over-engineering reflex is a `Protocol` for every external service so the core can be tested with a fake. But a pure core never calls the service — the shell does. You don't need a `UserRepository` interface to swap CSV for Postgres; you swap the shell function.

```python
# ❌ Protocol introduced solely to abstract I/O for testability
class UserRepository(Protocol):
    def save(self, u: User) -> None: ...

def register(repo: UserRepository, name: str) -> None:
    user = User.new(name)
    repo.save(user)   # the "logic" is one line and the test is now about a mock
```

```python
# ✅ Decide in the core; the shell uses concrete I/O directly
def decide_registration(name: str) -> Result[User, RegistrationError]:
    match Email.parse(derive_email(name)):
        case Ok(email):
            return Ok(User(name=name, email=email))
        case Err(error):
            return Err(error)

def register_shell(name: str) -> None:                # shell, uses concrete DB
    match decide_registration(name):
        case Ok(user): postgres.insert("users", user)
        case Err(reason): logger.warning("rejected: %s", reason)
```

A `Protocol` may still be valuable when you genuinely have multiple production implementations (e.g. a real payment processor and a sandbox), or to formalize a wide service boundary. Use it for those reasons — not as a stand-in for testability.

---

## 3. Algebraic Data Types

Example: [`03_algebraic_data_types.py`](examples/src/python_style_examples/03_algebraic_data_types.py)

Model the domain so invalid states cannot be constructed.

### 3.1 Product types — "and"

Always frozen by default. Make exceptions only with a documented reason.

```python
# ❌ Nothing prevents misuse; mutable; no type information
user = {"id": "42", "name": None, "email": 123}
```

```python
# ✅ Shape is fixed, fields are typed, value is immutable
@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    name: str
    email: Email | None
```

### 3.2 Sum types — "or"

Python has no native discriminated union, but tagged dataclass unions work well with `match` and narrow correctly under mypy/pyright.

```python
# ❌ "Whatever a string can be" — paypal, Card, CARD, credti_card, ""
def charge(amount: int, payment_method: str) -> None:
    if payment_method == "card":
        ...
```

```python
# ✅ The set of payment methods is closed and known to the type checker
@dataclass(frozen=True)
class Cash: pass

@dataclass(frozen=True)
class Card:
    last4: str

@dataclass(frozen=True)
class Pix:
    key: str

Payment = Cash | Card | Pix

def charge(amount: Cents, method: Payment) -> None: ...
```

For closed sets of *value-less* variants, `Enum` is fine:

```python
# ✅ Enum for simple closed sets
class CustomerTier(Enum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
```

### 3.3 Replace boolean combinations with sum types

```python
# ❌ 2³ = 8 states, only 3 of them legal
@dataclass
class Account:
    is_active: bool
    is_suspended: bool
    is_closed: bool
```

```python
# ✅ Exactly 3 states, all legal, each carrying the data it needs
@dataclass(frozen=True)
class Active: pass

@dataclass(frozen=True)
class Suspended:
    reason: str
    until: datetime

@dataclass(frozen=True)
class Closed:
    closed_at: datetime

AccountState = Active | Suspended | Closed

@dataclass(frozen=True)
class Account:
    id: AccountId
    state: AccountState
```

**Rule:** if two booleans on the same object cannot legally both be true (or all be false), they are a sum type wearing a disguise. Replace them.

---

## 4. Make State Explicit

Example: [`04_explicit_state.py`](examples/src/python_style_examples/04_explicit_state.py)

A deeper application of §3, from Wlaschin's "Making State Explicit"[\[4\]](#ref-4): when an entity moves through a lifecycle, **each state is its own type**, carrying only the data that exists at that point.

### 4.1 Excessive optional fields are a hidden state machine

A type with many `Optional` fields is almost always a state machine in disguise. Each combination of "which fields are populated" is a state, but the type system doesn't know that.

```python
# ❌ Implicit state. The shape allows nonsense like
#    (paid_date=Some, paid_amount=None, shipped_date=Some)
@dataclass
class Order:
    id: int
    placed_date: datetime
    paid_date: datetime | None
    paid_amount: Decimal | None
    shipped_date: datetime | None
    shipping_method: str | None
    returned_date: datetime | None
    returned_reason: str | None
```

```python
# ✅ Each state is a type. Each state carries cumulative history. Illegal shapes don't exist.
@dataclass(frozen=True)
class Unpaid:
    id: OrderId
    placed: datetime

@dataclass(frozen=True)
class Paid:
    id: OrderId
    placed: datetime
    paid: PaymentInfo

@dataclass(frozen=True)
class Shipped:
    id: OrderId
    placed: datetime
    paid: PaymentInfo
    shipped: ShippingInfo

@dataclass(frozen=True)
class Returned:
    id: OrderId
    placed: datetime
    paid: PaymentInfo
    shipped: ShippingInfo
    returned: ReturnInfo

Order = Unpaid | Paid | Shipped | Returned
```

### 4.2 Transitions are total functions over the full state

A state-transition function takes the full sum type and returns the full sum type. It exhaustively decides what happens for every starting state — including the illegal ones (e.g. "pay an already-paid order").

```python
# ❌ Takes only the "right" substate; pushes the "what if it's in the wrong state" question to every caller
def make_payment(order: Unpaid, payment: PaymentInfo) -> Paid: ...
```

```python
# ✅ Handles every starting state in one place; callers can't forget
def make_payment(order: Order, payment: PaymentInfo) -> Result[Order, str]:
    match order:
        case Unpaid(id=i, placed=p):
            return Ok(Paid(id=i, placed=p, paid=payment))
        case Paid() | Shipped() | Returned():
            return Err("order is already paid")
```

This is Wlaschin's rule: event handlers accept and return the whole state machine. Sub-functions that operate on a single state are fine internally, but the *public* transition function takes the union type.

### 4.3 When *not* to model state as types

Not every collection of states deserves a state machine. From Wlaschin[\[4\]](#ref-4):

- **States carry no special domain logic.** Blog post `Draft | Published` rarely changes behavior except in the display layer. Don't bother.
- **Transitions happen outside the application.** Customer `Active | Inactive` driven by a nightly batch job that looks at the orders table — model the states, but not the transitions, in the application.
- **Rules change frequently.** If the lifecycle is reconfigured every quarter by product, a static state machine is the wrong tool; use a rules engine.

Apply state-machine modeling when there are mutually exclusive states *with different behavior*, internal transitions, and stable rules.

---

## 5. Pattern Matching and Exhaustiveness

Example: [`05_pattern_matching_exhaustiveness.py`](examples/src/python_style_examples/05_pattern_matching_exhaustiveness.py)

Use `match` on sum types. Always close with `assert_never` so adding a new variant becomes a type-checker error wherever it's unhandled.

```python
# ❌ Adds a new Payment variant later → this function silently returns "unknown"
def describe(p: Payment) -> str:
    if isinstance(p, Cash):
        return "cash"
    elif isinstance(p, Card):
        return f"card ••••{p.last4}"
    return "unknown"
```

```python
# ✅ The type checker refuses to compile if a variant is missed
from typing import assert_never

def describe(p: Payment) -> str:
    match p:
        case Cash():
            return "cash"
        case Card(last4=l):
            return f"card ••••{l}"
        case Pix(key=k):
            return f"pix {k}"
        case _ as unreachable:
            assert_never(unreachable)
```

When `Crypto` is added to `Payment`, every non-exhaustive `match` becomes a type-checker error. This is free guidance from the tooling, and it is the entire reason for using sum types.

---

## 6. Three Classes of Errors

Example: [`06_errors.py`](examples/src/python_style_examples/06_errors.py)

From Wlaschin's "Against Railway-Oriented Programming"[\[6\]](#ref-6). Before reaching for `Result`, classify the error.

| Class | What it is | Tool |
|---|---|---|
| **Domain error** | An expected business outcome. Order rejected by billing. Invalid product code. Insufficient funds. | `Result[T, E]` |
| **Panic** | Programmer or system error. `KeyError` on a key the code thought existed. OOM. Divide by zero. Unreachable branch hit. | Exception, fail fast |
| **Infrastructure error** | Network timeout, auth failure, DB unavailable. Expected, but not part of the business model. | Judgment: usually exception in the shell; sometimes `Result` if the domain cares |

```python
# ❌ Using Result for a panic — the function lies about what it can recover from
def divide(a: int, b: int) -> Result[int, str]:
    if b == 0:
        return Err("cannot divide by zero")
    return Ok(a // b)
```

```python
# ✅ Panic: let it crash. The caller has nothing useful to do with this.
def divide(a: int, b: int) -> int:
    return a // b  # ZeroDivisionError propagates; that's correct behavior
```

```python
# ✅ Domain error: caller can sensibly react
def withdraw(account: Account, amount: Cents) -> Result[Account, InsufficientFunds]:
    if amount > account.balance:
        return Err(InsufficientFunds(available=account.balance, requested=amount))
    return Ok(account.debit(amount))
```

**Rule of thumb:** if a caller has no meaningful recovery, an exception is correct. If the caller will branch on the failure mode (display message, retry, fall back), `Result` is correct.

---

## 7. Result and Option

Example: [`07_result_option.py`](examples/src/python_style_examples/07_result_option.py)

### 7.1 A small Result type

Roll your own (small enough to vendor) or use [`returns`](https://github.com/dry-python/returns).

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

type Result[T, E] = Ok[T] | Err[E]
```

The error track is part of the type. Callers must `match`; they cannot accidentally skip the failure path.

### 7.2 `T | None` only for genuine absence, not for failure

```python
# ❌ None is ambiguous — "no such user"? "lookup failed"? "user has no email"?
def get_user_email(id: int) -> str | None: ...
```

```python
# ✅ Each concept gets its own type
def find_user(id: UserId) -> User | None: ...                # absence
def parse_email(raw: str) -> Result[Email, ParseError]: ...  # failure carries why
def get_user_email(u: User) -> Email | None: ...             # field is optional
```

### 7.3 Don't use exceptions for expected domain failures

```python
# ❌ Signature lies — the function may not return an Account at all
def withdraw(account: Account, amount: Cents) -> Account:
    if amount > account.balance:
        raise InsufficientFundsError()
    return account.debit(amount)
```

```python
# ✅ Failure is part of the type; caller cannot ignore it
def withdraw(account: Account, amount: Cents) -> Result[Account, InsufficientFunds]:
    if amount > account.balance:
        return Err(InsufficientFunds(available=account.balance, requested=amount))
    return Ok(account.debit(amount))
```

### 7.4 When NOT to use Result

Wlaschin's eight cautions[\[6\]](#ref-6), condensed:

- **Diagnostics** — if you need a stack trace, use an exception, not a `Result` with one stuffed inside.
- **Don't reinvent try/except** — Python's exception machinery exists; don't shadow it.
- **Fail fast** — if the workflow can't continue, `raise` or `sys.exit`; don't propagate an unrecoverable `Result`.
- **Hidden control flow** — if the logic is private and no caller sees the error variants, a local exception may be cleaner.
- **Apathy** — if no caller cares *why* it failed, return `T | None`.
- **I/O errors** — model the few the domain cares about; let the rest be exceptions in the shell.
- **Performance** — `Result` allocates. Profile first.
- **Interop** — don't force callers who don't speak the idiom to learn `Result`; `T | None` or raising may be more honest.

In short: `Result` is for domain modeling. If it isn't an expected, recoverable outcome that callers will branch on, it probably shouldn't be a `Result`.

### 7.5 Chain without nesting

```python
# ❌ The pyramid of doom returns
r1 = parse_request(raw)
if isinstance(r1, Ok):
    r2 = load_accounts(r1.value)
    if isinstance(r2, Ok):
        r3 = transfer(*r2.value, r1.value.amount)
        if isinstance(r3, Ok):
            return Ok(receipt_of(r3.value))
        return r3
    return r2
return r1
```

```python
# ✅ Early-return with match flattens the chain
def run(raw: bytes) -> Result[Receipt, ParseError | TransferError]:
    match parse_request(raw):
        case Err(e): return Err(e)
        case Ok(req): pass
    match load_accounts(req):
        case Err(e): return Err(e)
        case Ok((src, dst)): pass
    match transfer(src, dst, req.amount):
        case Err(e): return Err(e)
        case Ok((src2, dst2)):
            return Ok(receipt_of(src2, dst2, req))
```

Or use `returns`'s `bind`/`flow`. Either way: no nested ladders.

---

## 8. Parse, Don't Validate

Example: [`08_parse_dont_validate.py`](examples/src/python_style_examples/08_parse_dont_validate.py)

Wlaschin's slogan[\[4\]](#ref-4); the highest-leverage rule in this document.

**Validate** = check that some data is OK, then continue using the same untyped data and hope downstream code remembers it was checked.

**Parse** = convert untyped input into a typed domain value once, at the boundary. From then on, the type system guarantees the constraint.

```python
# ❌ The string keeps traveling; every consumer must re-trust or re-check
def send_welcome(email: str) -> None:
    if not EMAIL_RE.match(email):
        raise ValueError(...)
    smtp.send(email)

def archive(email: str) -> None:
    # was this already validated? who knows.
    db.insert(email)
```

```python
# ✅ Validation happens once at construction; downstream code is type-safe
@dataclass(frozen=True)
class Email:
    value: str

    @classmethod
    def parse(cls, raw: str) -> Result["Email", str]:
        if not EMAIL_RE.match(raw):
            return Err(f"invalid email: {raw!r}")
        return Ok(cls(value=raw.lower().strip()))

def send_welcome(email: Email) -> None:   # cannot be called with an unparsed string
    smtp.send(email.value)

def archive(email: Email) -> None:        # same guarantee, for free
    db.insert(email.value)
```

**At system boundaries** (HTTP handlers, queue consumers, CLI arg parsing, config loading), use Pydantic v2 or `attrs` with validators to parse once. Inside the core, only typed domain values circulate. Untyped `str` and `dict` should not appear in core function signatures.

**Collecting validation errors.** When parsing structured input, prefer collecting all errors at once over short-circuiting on the first. The user shouldn't have to fix-and-resubmit five times to discover five problems.

```python
# ❌ Tells the user about one problem at a time
def parse_signup(raw: dict) -> Result[Signup, str]:
    match Email.parse(raw["email"]):
        case Err(e): return Err(e)
        case Ok(email): pass
    match Age.parse(raw["age"]):
        case Err(e): return Err(e)
        ...
```

```python
# ✅ Collect every problem, then either fail with all of them or succeed
from collections.abc import Mapping

def parse_signup(raw: Mapping[str, object]) -> Result[Signup, list[str]]:
    errors: list[str] = []
    email: Email | None = None
    age: Age | None = None
    name: NonEmptyString | None = None

    email_raw = raw.get("email")
    age_raw = raw.get("age")
    name_raw = raw.get("name")

    email_r = (
        Email.parse(email_raw)
        if isinstance(email_raw, str)
        else Err("email must be a string")
    )
    age_r = (
        Age.parse(age_raw)
        if isinstance(age_raw, int)
        else Err("age must be an int")
    )
    name_r = (
        NonEmptyString.parse(name_raw)
        if isinstance(name_raw, str)
        else Err("name must be a string")
    )

    match email_r:
        case Ok(email):
            pass
        case Err(error):
            errors.append(error)

    match age_r:
        case Ok(age):
            pass
        case Err(error):
            errors.append(error)

    match name_r:
        case Ok(name):
            pass
        case Err(error):
            errors.append(error)

    if errors:
        return Err(errors)

    assert email is not None and age is not None and name is not None
    return Ok(Signup(email=email, age=age, name=name))
```

---

## 9. Smart Constructors and Branded Types

Example: [`09_smart_constructors.py`](examples/src/python_style_examples/09_smart_constructors.py)

Eliminate "primitive obsession." A `Decimal` is not a `Price`; an `int` is not a `UserId`.

```python
# ❌ Argument order is a footgun; units are documented in comments only
def transfer_funds(amount: int, source: int, destination: int) -> None: ...

transfer_funds(source_id, dest_id, 1000)   # silently wrong, no type error
```

```python
# ✅ NewType — no wrapper object at runtime, type-checker enforced
from typing import NewType

UserId = NewType("UserId", int)
AccountId = NewType("AccountId", int)
Cents = NewType("Cents", int)

def transfer_funds(amount: Cents, source: AccountId, dest: AccountId) -> None: ...

transfer_funds(source_id, dest_id, Cents(1000))  # type error: AccountId given where Cents expected
```

For values with **invariants** (non-negative cents, well-formed emails, ISO country codes), use a frozen dataclass with a smart constructor:

```python
# ❌ Anyone can construct a nonsensical price
@dataclass(frozen=True)
class Price:
    cents: int

bad = Price(cents=-500)   # accepted; will explode somewhere far from here
```

```python
# ✅ The class enforces the invariant; `parse` turns untrusted input into Result
@dataclass(frozen=True, slots=True)
class Price:
    cents: int

    def __post_init__(self) -> None:
        if self.cents < 0:
            raise ValueError(f"price must be non-negative, got {self.cents!r}")

    @classmethod
    def parse(cls, n: int) -> Result["Price", str]:
        if not isinstance(n, int) or n < 0:
            return Err(f"price must be a non-negative int, got {n!r}")
        return Ok(cls(cents=n))

    def __add__(self, other: "Price") -> "Price":
        return Price(cents=self.cents + other.cents)
```

**A standard kit** worth defining once and reusing across a codebase:

- `NonEmptyString` — a string known to be non-empty.
- `PositiveInt`, `NonNegativeInt` — natural numbers.
- `Email`, `URL`, `PhoneNumber`, `ISOCountryCode`, `ISOCurrencyCode` — structured strings.
- `UserId`, `OrderId`, `TransactionId`, … — identifiers.
- `Cents`, `Millis`, `Seconds`, `Meters` — values with units.

**Rule:** any value with a unit, any identifier, and any string with structural constraints gets its own type. `parse` handles untrusted input; the class still enforces its invariant if someone calls the constructor directly.

---

## 10. Pipelines and Composition

Example: [`10_pipelines.py`](examples/src/python_style_examples/10_pipelines.py)

A business workflow is rarely a single function. It is a sequence of typed transformations. Make that sequence visible in the types.

The pattern: each stage maps from one type to a **different** type. The type system tracks where you are in the workflow.

```python
# A signup workflow as a chain of typed stages:
#   bytes → UnvalidatedSignup → ValidatedSignup → PricedSignup → SavedSignup
#         ^ parse              ^ validate         ^ price        ^ persist
def parse(raw: bytes) -> Result[UnvalidatedSignup, ParseError]: ...
def validate(s: UnvalidatedSignup) -> Result[ValidatedSignup, ValidationError]: ...
def price(s: ValidatedSignup) -> Result[PricedSignup, PricingError]: ...
def persist(s: PricedSignup) -> Result[SavedSignup, PersistError]: ...
```

Each stage's input type cannot be confused with a downstream stage's input. You cannot accidentally call `persist` on an `UnvalidatedSignup`. You cannot accidentally skip `validate`.

```python
# ❌ Same type all the way through; nothing prevents skipping a step
def process(s: Signup) -> Result[Signup, Error]:
    return persist(s)  # forgot to validate. Type-checks. Wrong.
```

```python
# ✅ Each stage is a function on a different type. The type checker enforces the order.
def process(raw: bytes) -> Result[SavedSignup, Error]:
    return (
        parse(raw)
        .bind(validate)
        .bind(price)
        .bind(persist)
    )
```

If your `Result` type doesn't have `.bind`, use the `match` chain from §7.5 or `returns.flow`.

**Naming convention.** When a stage refines its input, name the output to reflect the new knowledge: `UnvalidatedSignup → ValidatedSignup`, `ParsedConfig → CheckedConfig`, `DraftEmail → SentEmail`. Reusing the same name (`Signup → Signup`) discards the information the workflow added.

---

## 11. Immutability by Default

Example: [`11_immutability.py`](examples/src/python_style_examples/11_immutability.py)

```python
# ❌ Silent mutation; the caller's User is changed under their feet
def add_tag(user: User, tag: str) -> User:
    user.tags.append(tag)
    return user
```

```python
# ✅ Return a new value; the input is untouched
from dataclasses import replace

def add_tag(user: User, tag: str) -> User:
    return replace(user, tags=(*user.tags, tag))
```

Rules of thumb:

- `@dataclass(frozen=True, slots=True)` on all domain types.
- No in-place mutation of arguments. "Update" = `dataclasses.replace(obj, field=new)`.
- No mutable default arguments — classic Python footgun.
- No module-level mutable state. If you need a registry, build it in a function and pass it explicitly.

```python
# ❌ Mutable default; every call shares the same list
def append_item(item: str, items: list[str] = []) -> list[str]:
    items.append(item)
    return items
```

```python
# ✅ No shared state across calls
def append_item(item: str, items: tuple[str, ...] = ()) -> tuple[str, ...]:
    return (*items, item)
```

---

## 12. Total Functions

Example: [`12_total_functions.py`](examples/src/python_style_examples/12_total_functions.py)

A total function returns a meaningful value for every input of its declared type. Partial functions throw, return `None` to signal failure, or work only on a subset of their type.

```python
# ❌ Signature claims to always return int; actually raises on missing birthdate
def get_user_age(user: User) -> int:
    if user.birthdate is None:
        raise ValueError("no birthdate")
    return years_between(user.birthdate, today())
```

```python
# ✅ Signature is honest about the absent case
def get_user_age(user: User) -> int | None:
    if user.birthdate is None:
        return None
    return years_between(user.birthdate, today())
```

- Expected failure → `Result[T, E]`.
- Legitimately absent → `T | None`.
- Declared `-> T` → always returns a `T`. No raising for domain reasons, no `None` sneaking out.

---

## 13. Tooling and Project Setup

Example project: [`examples/pyproject.toml`](examples/pyproject.toml)

Treat the type checker as part of the language, not a linter.

- **mypy `--strict`** or **pyright** in strict mode. Non-negotiable for new code. CI fails on type errors.
- **Python 3.13** as the project target. Use stdlib `typing.Self` and `typing.assert_never`, plus PEP 695 `type` aliases and generic syntax where they make examples clearer.
- **`ruff`** for linting and formatting. Enable at minimum: `E`, `F`, `B`, `UP`, `SIM`, `RET`, `TCH`.
- **Pydantic v2** at boundaries (HTTP, config, queues). Not in the pure core.
- **`pytest`** with **`hypothesis`** for property tests on the pure core (the kind of testing Bernhardt's core enables — examples plus generative).
- **Optional but recommended:** [`returns`](https://github.com/dry-python/returns) for `Result`/`Maybe`/do-notation; [`attrs`](https://www.attrs.org/) if you prefer it to `dataclasses` (richer validators).

`pyproject.toml` should pin the type-checker and linter target:

```toml
[tool.mypy]
strict = true
python_version = "3.13"

[tool.ruff]
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "B", "UP", "SIM", "RET", "TCH"]
```

---

## 14. Anti-Patterns to Reject

Example: [`14_anti_patterns.py`](examples/src/python_style_examples/14_anti_patterns.py)

Each with a one-line demonstration of the smell.

### 14.1 Stringly-typed code

```python
# ❌
status: str  # "pending"? "Pending"? "pendng"? Who knows.
# ✅
status: OrderStatus  # closed set, type-checked
```

### 14.2 `Dict[str, Any]` in core signatures

```python
# ❌ "No types" with extra steps
def price_quote(order: dict[str, Any]) -> dict[str, Any]: ...
# ✅
def price_quote(order: Order) -> Quote: ...
```

### 14.3 Exceptions for domain control flow

```python
# ❌
def find_user(id: int) -> User:
    raise UserNotFoundError()
# ✅
def find_user(id: UserId) -> User | None: ...
```

### 14.4 Mocking code you wrote

```python
# ❌ Mocking your own class to test another of your classes
with patch("myapp.pricing.PricingService.compute") as m:
    m.return_value = 100
    ...
# ✅ The thing you want to test is a pure function; pass a value, assert a value
assert compute_price(order, rules) == Price(cents=100)
```

### 14.5 Mutable shared state

```python
# ❌
CACHE: dict[str, Any] = {}   # module-level mutation hazard
# ✅
def make_cache() -> Cache:    # explicit, passed where needed
    return Cache()
```

### 14.6 Scattered validation

```python
# ❌ Same constraint checked in the handler, the service, the repository
def handler(req): assert "@" in req["email"]; service(req)
def service(req): assert "@" in req["email"]; repo(req)
# ✅ Parse once at the edge; the rest of the system takes Email
```

### 14.7 `None` as success/failure signal

```python
# ❌
def save() -> bool | None: ...   # what does None mean here?
# ✅
def save() -> Result[SavedRecord, SaveError]: ...
```

### 14.8 Comments where types should be

```python
# ❌
def sleep(d):  # d is in milliseconds
    ...
# ✅
def sleep(d: Millis) -> None:
    ...
```

### 14.9 Hidden I/O in pure-looking functions

```python
# ❌ Called "calculate" but secretly does I/O
def calculate_quote(order: Order) -> Quote:
    rates = requests.get("https://rates.example.com").json()  # surprise!
    return ...
# ✅ Take effects as values
def calculate_quote(order: Order, rates: Rates) -> Quote: ...
```

### 14.10 Boolean parameters

```python
# ❌ At the call site, nobody knows what `True` means
send_email(user, True, False)
# ✅ Use enums or keyword-only args with explicit names
send_email(user, urgency=Urgency.HIGH, html=False)
```

---

## 15. A Worked Mini-Example

Example: [`15_worked_mini_example.py`](examples/src/python_style_examples/15_worked_mini_example.py)

A payment-state transition, with the pieces separated so each rule is visible.

First, define the tiny shared building blocks and branded primitives:

```python
from dataclasses import dataclass, replace
from typing import NewType, assert_never

TxnId = NewType("TxnId", str)
LedgerId = NewType("LedgerId", str)
Cents = NewType("Cents", int)

@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

type Result[T, E] = Ok[T] | Err[E]
```

Then model the lifecycle as data. Each state carries exactly the fields that exist in that state:

```python
@dataclass(frozen=True, slots=True)
class CardDeclined:
    reason: str

@dataclass(frozen=True, slots=True)
class ComplianceHold:
    case_id: str

type FailureReason = CardDeclined | ComplianceHold

@dataclass(frozen=True, slots=True)
class Pending:
    pass

@dataclass(frozen=True, slots=True)
class Settled:
    ledger_id: LedgerId

@dataclass(frozen=True, slots=True)
class Failed:
    reason: FailureReason

@dataclass(frozen=True, slots=True)
class Reversed:
    original_ledger_id: LedgerId

type TxnState = Pending | Settled | Failed | Reversed
type FinalTxnState = Failed | Reversed

@dataclass(frozen=True, slots=True)
class Txn:
    id: TxnId
    amount: Cents
    state: TxnState
```

The core transition is pure: it accepts values, returns values, and handles every starting state:

```python
@dataclass(frozen=True, slots=True)
class AlreadySettled:
    ledger_id: LedgerId

@dataclass(frozen=True, slots=True)
class CannotSettleFinalState:
    state: FinalTxnState

type SettleError = AlreadySettled | CannotSettleFinalState

def settle(txn: Txn, ledger_id: LedgerId) -> Result[Txn, SettleError]:
    match txn.state:
        case Pending():
            return Ok(replace(txn, state=Settled(ledger_id=ledger_id)))
        case Settled(ledger_id=existing):
            return Err(AlreadySettled(ledger_id=existing))
        case (Failed() | Reversed()) as final_state:
            return Err(CannotSettleFinalState(state=final_state))
        case _ as unreachable:
            assert_never(unreachable)
```

The shell is where I/O happens. Raw request strings should already have been parsed into `TxnId` and `LedgerId` before this function is called:

```python
def handle_settle_request(txn_id: TxnId, ledger_id: LedgerId) -> None:
    txn = db.fetch_txn(txn_id)

    match settle(txn, ledger_id):
        case Ok(value=new_txn):
            db.save_txn(new_txn)
            metrics.incr("settled")
        case Err(error=error):
            match error:
                case AlreadySettled(ledger_id=existing):
                    logger.info("settle ignored: already settled at %s", existing)
                case CannotSettleFinalState(state=state):
                    logger.warning("settle rejected from state: %s", state)
                    metrics.incr("settle_rejected")
                case _ as unreachable:
                    assert_never(unreachable)
```

What this example demonstrates:

- `settle` is pure. Test it with `assert settle(txn, LedgerId("L1")) == Ok(...)`. No mocks.
- Adding `Chargeback` to `TxnState` fails type-checking at the `match` until handled.
- Errors are typed values (`SettleError`), not exceptions or strings.
- The shell does I/O and delegates the decision to the core.
- Invalid transactions like `Settled` without a `ledger_id` cannot be constructed.

---

## 16. When to Break These Rules

Engineering judgment beats dogma. Defensible reasons to deviate:

- **Performance hot paths** where allocation of frozen dataclasses is measurably too expensive. Profile first. Document the deviation.
- **Interop with libraries** that expect mutable objects or raise exceptions (ORMs, asyncio internals, some scientific libraries). Wrap them at the edge; don't let their idioms infect the core.
- **Throwaway scripts** under ~100 lines. The discipline pays off when code is read and changed; one-shot scripts don't qualify.
- **Prototypes** where the domain is not yet understood. Sketch first, then harden by applying these rules once the shape is clear.

The discipline exists to reduce the cost of change over time. If a rule is not buying that, drop it.

---

## 17. Sources

<a id="ref-1"></a>**[1]** Gary Bernhardt, *Boundaries*, talk at SCNA 2012. <https://www.destroyallsoftware.com/talks/boundaries>

<a id="ref-2"></a>**[2]** Gary Bernhardt, *Functional Core, Imperative Shell*, Destroy All Software screencast. <https://www.destroyallsoftware.com/screencasts/catalog/functional-core-imperative-shell>

<a id="ref-3"></a>**[3]** Scott Wlaschin, *F# for Fun and Profit* (site index). <https://fsharpforfunandprofit.com/>

<a id="ref-4"></a>**[4]** Scott Wlaschin, *Designing with Types* series. <https://fsharpforfunandprofit.com/series/designing-with-types/> — particularly *Single case union types*, *Making illegal states unrepresentable*, *Discovering new concepts*, *Making state explicit*, *Constrained strings*, *Non-string types*.

<a id="ref-5"></a>**[5]** Scott Wlaschin, *Railway Oriented Programming*. <https://fsharpforfunandprofit.com/rop/>

<a id="ref-6"></a>**[6]** Scott Wlaschin, *Against Railway-Oriented Programming (when used thoughtlessly)*, 20 Dec 2019. <https://fsharpforfunandprofit.com/posts/against-railway-oriented-programming/>

<a id="ref-7"></a>**[7]** Scott Wlaschin, *Functional Programming Design Patterns*. <https://fsharpforfunandprofit.com/fppatterns/>

<a id="ref-8"></a>**[8]** Scott Wlaschin, *Moving IO to the edges of your app: Functional Core, Imperative Shell*, NDC London 2024. <https://www.youtube.com/watch?v=P1vES9AgfC4>

<a id="ref-9"></a>**[9]** Luis Vaz (Rastrian), *Why Reliability Demands Functional Programming: ADTs, Safety, and Critical Infrastructure*, 16 Sep 2025. <https://blog.rastrian.dev/post/why-reliability-demands-functional-programming-adts-safety-and-critical-infrastructure>

**Companion documents:**

- [`python-style-migration-guide`](./python-style-migration-guide.md) — step-by-step playbook for applying these rules to an existing codebase.

---

## 18. Skill Definition

The block below is a ready-to-use `SKILL.md` for agent use. Copy into the appropriate skill directory.

````markdown
---
name: python-functional-style
description: Use this skill for any task that involves writing, reviewing, or refactoring Python code. Applies a functional-core/imperative-shell architecture, algebraic data types via frozen dataclasses and tagged unions, parse-don't-validate at boundaries, Result and Option types for expected failures, smart constructors and branded types to eliminate primitive obsession, immutability by default, exhaustive pattern matching with assert_never, and total function signatures. Triggers on: writing Python code, designing dataclasses or domain types, modeling business workflows or state lifecycles, handling errors, designing function signatures, refactoring legacy Python, designing APIs, or any task where Python code is the deliverable. Also triggers on requests phrased as "design X", "model the domain for X", "write a Python module that X", "refactor this Python", "fix the types in this Python file", or similar.
---

# Python Functional Style

Apply the principles in `python-style-guide.md` to all Python code written, reviewed, or refactored in this session.

## Hard rules

1. **Functional core, imperative shell.** Pure functions decide; the shell executes. No I/O, no `async`, no `try/except` for domain logic, no time/randomness in the core.
2. **No invalid states.** Replace boolean combinations with sum types. Replace optional-field combinations with state-explicit types (one type per lifecycle state).
3. **Frozen dataclasses by default.** `@dataclass(frozen=True, slots=True)`. No in-place mutation. `dataclasses.replace` to "update."
4. **Tagged unions for "or" types.** With `match` + `typing.assert_never` for exhaustiveness.
5. **Parse, don't validate.** Untyped input becomes typed domain values at the boundary, once. Pydantic v2 or smart-constructor `classmethod`s. No `str` or `dict[str, Any]` in core signatures.
6. **Result for domain errors, exceptions for panics, judgment for infrastructure errors.** Don't `raise` for expected business outcomes. Don't return `Result` for unrecoverable failures.
7. **Smart constructors and branded types** for any identifier, any unit-bearing value, and any string with structural constraints (`UserId`, `Cents`, `Email`, `NonEmptyString`).
8. **Total functions.** The declared return type is honest. No hidden `raise`, no sneaky `None`.
9. **`mypy --strict` clean.** Treat type errors as build failures.
10. **No mocks of your own code.** If a test requires patching internal functions, the design has mixed logic with I/O — refactor to a pure function instead.

## Heuristics

- If you reach for `unittest.mock.patch` on internal code, you have a design smell. Push logic into a pure function.
- If a type has three or more `Optional` fields, it is probably a hidden state machine. Make the states explicit.
- If two `bool` fields cannot legally be true together, they are a sum type in disguise.
- If a function's name suggests purity ("calculate," "compute," "decide") but it touches the network/DB/clock, the function is lying. Either rename or extract.
- Workflow stages should map between *different* types (`Raw → Parsed → Validated → Priced`) so the type checker tracks position in the workflow.

## Forbidden patterns

- `def f(x=[])` and any mutable default argument.
- `Dict[str, Any]` in core function signatures.
- `raise SomeDomainError(...)` for expected failures (use `Result`).
- Module-level mutable state.
- Stringly-typed enums (`status: str`).
- Positional boolean arguments at call sites (`send(user, True, False)`).
- Comments describing units when a type would do (`# in milliseconds`).
````
