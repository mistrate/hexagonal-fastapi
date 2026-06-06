"""A third concrete store (optional; needs the `postgres` extra).

Its existence is part of why `UserStore` in `user_store.py` is a justified
Protocol rather than a smell: there really are three production implementations.

SQLAlchemy is imported at module top, so importing this module requires the
`postgres` extra. That is fine: nothing on the default code path imports it
(`main.py` wires it only when you uncomment that block), and the type-checking
path installs the extra (`uv run --extra postgres mypy`), so mypy checks the
calls below against SQLAlchemy's real types rather than treating them as `Any`.

Parsing happens at this boundary too (§8): a database row becomes typed domain
values before it enters the program. Data we wrote ourselves is assumed valid,
so a malformed row is a panic, not a domain error (§6) — hence `.unwrap()`,
which raises rather than returning an error a caller could mishandle.
"""
from sqlalchemy import create_engine, text

from app.core.user import DisplayName, Email, User, UserId


class PostgresUserStore:
    def __init__(self, dsn: str) -> None:
        self._engine = create_engine(dsn)

    def get(self, user_id: UserId) -> User | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, email, display_name FROM users WHERE id = :id"),
                {"id": user_id},
            ).fetchone()
        if row is None:
            return None
        return User(
            id=UserId(row.id),
            email=Email.parse(row.email).unwrap(),
            display_name=DisplayName.parse(row.display_name).unwrap(),
        )

    def save(self, user: User) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, display_name) "
                    "VALUES (:id, :email, :name) "
                    "ON CONFLICT (id) DO UPDATE SET display_name = :name"
                ),
                {"id": user.id, "email": user.email.value, "name": user.display_name.value},
            )
