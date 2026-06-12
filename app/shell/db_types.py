"""Typed table definitions — SQLAlchemy declarative models used as schema only.

This is the repo's one sanctioned ORM exception (guidelines §16: wrap libraries
at the edge). The `*Row` classes exist for what the declarative layer gives the
type checker — column references that can't be typo'd (`UserRow.email`, not
`"email"`) and typed result rows from `select(...)` — and for defining the
schema once for every SQL dialect (`Base.metadata` replaces per-backend DDL
strings). What we deliberately do NOT use is the ORM's mutation machinery:

* **No `Session`, ever.** Statements built from these classes are executed on
  plain Core connections; every write is a visible `conn.execute(...)` in
  `sql_store.py`. No identity map, no autoflush, no dirty tracking.
* **Never instantiated.** `UserRow(...)` is never constructed, so no mutable
  mapped object exists. The only values that travel are the frozen domain types
  in `app.core`.
* **Shell-only.** Imported by `sql_store.py` (and `main.py` for schema
  creation); never by `app/core/`, `http.py`, or `cli.py`.

Columns are plain TEXT: parsing rows into domain values (`Email.parse`, …)
happens in the store, at the boundary (§8) — the database stays as untyped as
any other edge.
"""

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)


class TeamRow(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)


class MembershipRow(Base):
    __tablename__ = "memberships"

    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id"), primary_key=True)
    team_id: Mapped[str] = mapped_column(Text, ForeignKey("teams.id"), primary_key=True)
    role: Mapped[str] = mapped_column(Text)
