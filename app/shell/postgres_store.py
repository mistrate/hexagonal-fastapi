"""A third backend (optional; needs the `postgres` extra).

It exists partly to make the point: implementing the full `Store` here, too, is
the N×M tax of keeping multiple backends — every method in `stores.py` reappears
in every backend. That cost is exactly why §2 says to keep a store `Protocol`
only when you genuinely have multiple production implementations; for a toy with
one real backend you would not pay it.

Same three tables as `sqlite_store`, same upsert-on-conflict shape. SQLAlchemy is
imported at module top (the module requires the `postgres` extra); parsing
happens at this boundary (§8), and our own rows are assumed valid, so a
malformed one is a panic — hence `.unwrap()`.
"""

from sqlalchemy import create_engine, text

from app.core.membership import Membership, MembershipRole
from app.core.team import Team, TeamId, TeamName
from app.core.user import DisplayName, Email, User, UserId

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS users "
    "(id TEXT PRIMARY KEY, email TEXT NOT NULL, display_name TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS teams (id TEXT PRIMARY KEY, name TEXT NOT NULL);"
    "CREATE TABLE IF NOT EXISTS memberships ("
    "user_id TEXT NOT NULL REFERENCES users(id), "
    "team_id TEXT NOT NULL REFERENCES teams(id), "
    "role TEXT NOT NULL, PRIMARY KEY (user_id, team_id));"
)


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self._engine = create_engine(dsn)
        with self._engine.begin() as conn:
            conn.execute(text(_SCHEMA))

    # --- users ---

    def get_user(self, user_id: UserId) -> User | None:
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

    def save_user(self, user: User) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, display_name) "
                    "VALUES (:id, :email, :name) ON CONFLICT (id) DO UPDATE "
                    "SET email = excluded.email, display_name = excluded.display_name"
                ),
                {"id": user.id, "email": user.email.value, "name": user.display_name.value},
            )

    # --- teams ---

    def get_team(self, team_id: TeamId) -> Team | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT id, name FROM teams WHERE id = :id"), {"id": team_id}
            ).fetchone()
        if row is None:
            return None
        return Team(id=TeamId(row.id), name=TeamName.parse(row.name).unwrap())

    def save_team(self, team: Team) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO teams (id, name) VALUES (:id, :name) "
                    "ON CONFLICT (id) DO UPDATE SET name = excluded.name"
                ),
                {"id": team.id, "name": team.name.value},
            )

    # --- memberships ---

    def get_membership(self, user_id: UserId, team_id: TeamId) -> Membership | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT user_id, team_id, role FROM memberships "
                    "WHERE user_id = :u AND team_id = :t"
                ),
                {"u": user_id, "t": team_id},
            ).fetchone()
        if row is None:
            return None
        return Membership(
            user_id=UserId(row.user_id),
            team_id=TeamId(row.team_id),
            role=MembershipRole.parse(row.role).unwrap(),
        )

    def save_membership(self, membership: Membership) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO memberships (user_id, team_id, role) "
                    "VALUES (:u, :t, :r) ON CONFLICT (user_id, team_id) "
                    "DO UPDATE SET role = excluded.role"
                ),
                {"u": membership.user_id, "t": membership.team_id, "r": membership.role.value},
            )

    def delete_membership(self, user_id: UserId, team_id: TeamId) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM memberships WHERE user_id = :u AND team_id = :t"),
                {"u": user_id, "t": team_id},
            )

    def list_memberships_for_user(self, user_id: UserId) -> tuple[Membership, ...]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT user_id, team_id, role FROM memberships WHERE user_id = :u"),
                {"u": user_id},
            ).fetchall()
        return tuple(
            Membership(
                user_id=UserId(row.user_id),
                team_id=TeamId(row.team_id),
                role=MembershipRole.parse(row.role).unwrap(),
            )
            for row in rows
        )

    def list_memberships_for_team(self, team_id: TeamId) -> tuple[Membership, ...]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT user_id, team_id, role FROM memberships WHERE team_id = :t"),
                {"t": team_id},
            ).fetchall()
        return tuple(
            Membership(
                user_id=UserId(row.user_id),
                team_id=TeamId(row.team_id),
                role=MembershipRole.parse(row.role).unwrap(),
            )
            for row in rows
        )
