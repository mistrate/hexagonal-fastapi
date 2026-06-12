"""CLI delivery mechanism (Typer): the same pure core as the API, more commands.

Each command is a thin shell: build the store, load, call the pure core, render,
exit. Data persists in SQLite between invocations, so `add-team` → `add-member`
→ `memberships` across separate calls is realistic.

    python -m app.shell.cli --help
"""

from typing import Annotated

import typer

from app.core.accounts import decide_user_deletion, describe_sole_admin
from app.core.membership import (
    MembershipRole,
    add_member as add_member_to_team,
    admin_count,
    change_role,
    describe_change_error,
    found_team,
    remove_member as remove_member_from_team,
)
from app.core.result import Err, Ok
from app.core.team import TeamId
from app.core.user import UserId, change_display_name, create_user, describe
from app.shell.sql_store import DEFAULT_DB_PATH, SqlStore, create_schema, create_sqlite_engine

cli = typer.Typer(
    help="Manage users and teams — a CLI shell around the same pure core as the API.",
    no_args_is_help=True,
)


def _store(db: str) -> SqlStore:
    engine = create_sqlite_engine(db)
    create_schema(engine)
    return SqlStore(engine)


def _parse_role_or_exit(raw: str) -> MembershipRole:
    match MembershipRole.parse(raw):
        case Ok(role):
            return role
        case Err(_):
            typer.echo("invalid: role must be 'member' or 'admin'", err=True)
            raise typer.Exit(code=1)


# --- users ---


@cli.command()
def add_user(
    user_id: Annotated[str, typer.Argument(help="ID for the new user.")],
    email: Annotated[str, typer.Argument(help="Email address.")],
    display_name: Annotated[str, typer.Argument(help="Display name.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Add a user."""
    store = _store(db)
    if store.get_user(UserId(user_id)) is not None:
        typer.echo(f"error: user {user_id!r} already exists", err=True)
        raise typer.Exit(code=1)
    match create_user(user_id, email, display_name):
        case Ok(user):
            store.save_user(user)
            typer.echo(f"added user {user.id} -> {user.email.value} / {user.display_name.value!r}")
        case Err(problems):
            for problem in problems:
                typer.echo(f"invalid: {describe(problem)}", err=True)
            raise typer.Exit(code=1)


@cli.command()
def rename_user(
    user_id: Annotated[str, typer.Argument(help="ID of an existing user.")],
    new_display_name: Annotated[str, typer.Argument(help="The new display name.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Change a user's display name."""
    store = _store(db)
    user = store.get_user(UserId(user_id))
    if user is None:
        typer.echo(f"error: user {user_id!r} not found (add it first)", err=True)
        raise typer.Exit(code=1)
    match change_display_name(user, new_display_name):
        case Ok(updated):
            store.save_user(updated)
            typer.echo(f"renamed {updated.id} -> {updated.display_name.value!r}")
        case Err(_):
            typer.echo("invalid: display_name cannot be empty", err=True)
            raise typer.Exit(code=1)


@cli.command()
def delete_user(
    user_id: Annotated[str, typer.Argument(help="ID of the user to delete.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Delete a user, cascading their team memberships."""
    store = _store(db)
    uid = UserId(user_id)
    user = store.get_user(uid)
    if user is None:
        typer.echo(f"error: user {user_id!r} not found", err=True)
        raise typer.Exit(code=1)
    memberships = store.list_memberships_for_user(uid)
    sole_admin_of = tuple(
        m.team_id
        for m in memberships
        if m.role is MembershipRole.ADMIN
        and admin_count(store.list_memberships_for_team(m.team_id)) == 1
    )
    match decide_user_deletion(user, sole_admin_of):
        case Ok(deleted_id):
            with store.unit_of_work() as tx:  # cascade atomically
                for membership in memberships:
                    tx.delete_membership(deleted_id, membership.team_id)
                tx.delete_user(deleted_id)
            typer.echo(f"deleted user {user_id!r} ({len(memberships)} membership(s) removed)")
        case Err(error):
            typer.echo(f"error: {describe_sole_admin(error)}", err=True)
            raise typer.Exit(code=1)


# --- teams ---


@cli.command()
def add_team(
    team_id: Annotated[str, typer.Argument(help="ID for the new team.")],
    name: Annotated[str, typer.Argument(help="Team name.")],
    admin_user_id: Annotated[str, typer.Argument(help="User ID of the team's first admin.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Add a team with its founding admin (a team is created with >=1 admin)."""
    store = _store(db)
    if store.get_team(TeamId(team_id)) is not None:
        typer.echo(f"error: team {team_id!r} already exists", err=True)
        raise typer.Exit(code=1)
    founder = store.get_user(UserId(admin_user_id))
    if founder is None:
        typer.echo(f"error: admin user {admin_user_id!r} not found", err=True)
        raise typer.Exit(code=1)
    match found_team(team_id, name, founder):
        case Ok((team, admin)):
            with store.unit_of_work() as tx:  # team + founding admin commit together
                tx.save_team(team)
                tx.save_membership(admin)
            typer.echo(f"added team {team.id} -> {team.name.value!r} (admin: {admin.user_id})")
        case Err(_):
            typer.echo("invalid: team name cannot be empty", err=True)
            raise typer.Exit(code=1)


# --- memberships (the new dimension) ---


@cli.command()
def add_member(
    team_id: Annotated[str, typer.Argument(help="Team ID.")],
    user_id: Annotated[str, typer.Argument(help="User ID.")],
    role: Annotated[str, typer.Argument(help="'member' or 'admin'.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Add a user to a team with a role."""
    store = _store(db)
    parsed_role = _parse_role_or_exit(role)
    user = store.get_user(UserId(user_id))
    if user is None:
        typer.echo(f"error: user {user_id!r} not found", err=True)
        raise typer.Exit(code=1)
    team = store.get_team(TeamId(team_id))
    if team is None:
        typer.echo(f"error: team {team_id!r} not found", err=True)
        raise typer.Exit(code=1)
    existing = store.get_membership(user.id, team.id)
    match add_member_to_team(user, team, parsed_role, existing):
        case Ok(membership):
            store.save_membership(membership)
            typer.echo(f"added {user_id!r} to {team_id!r} as {membership.role.value}")
        case Err(_):
            typer.echo(f"error: {user_id!r} is already a member of {team_id!r}", err=True)
            raise typer.Exit(code=1)


@cli.command()
def update_role(
    team_id: Annotated[str, typer.Argument(help="Team ID.")],
    user_id: Annotated[str, typer.Argument(help="User ID.")],
    role: Annotated[str, typer.Argument(help="'member' or 'admin'.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Change a user's role in a team."""
    store = _store(db)
    parsed_role = _parse_role_or_exit(role)
    existing = store.get_membership(UserId(user_id), TeamId(team_id))
    team_members = store.list_memberships_for_team(TeamId(team_id))
    match change_role(existing, parsed_role, team_members):
        case Ok(membership):
            store.save_membership(membership)
            typer.echo(f"updated {user_id!r} in {team_id!r} to {membership.role.value}")
        case Err(error):
            typer.echo(f"error: {describe_change_error(error)}", err=True)
            raise typer.Exit(code=1)


@cli.command()
def remove_member(
    team_id: Annotated[str, typer.Argument(help="Team ID.")],
    user_id: Annotated[str, typer.Argument(help="User ID.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Remove a user from a team."""
    store = _store(db)
    existing = store.get_membership(UserId(user_id), TeamId(team_id))
    team_members = store.list_memberships_for_team(TeamId(team_id))
    match remove_member_from_team(existing, team_members):
        case Ok(membership):
            store.delete_membership(membership.user_id, membership.team_id)
            typer.echo(f"removed {user_id!r} from {team_id!r}")
        case Err(error):
            typer.echo(f"error: {describe_change_error(error)}", err=True)
            raise typer.Exit(code=1)


@cli.command()
def memberships(
    user_id: Annotated[str, typer.Argument(help="User ID.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """List the teams a user belongs to."""
    store = _store(db)
    if store.get_user(UserId(user_id)) is None:
        typer.echo(f"error: user {user_id!r} not found", err=True)
        raise typer.Exit(code=1)
    rows = store.list_memberships_for_user(UserId(user_id))
    if not rows:
        typer.echo(f"{user_id!r} is not a member of any team")
        return
    for membership in rows:
        typer.echo(f"{membership.team_id} -> {membership.role.value}")


if __name__ == "__main__":
    cli()
