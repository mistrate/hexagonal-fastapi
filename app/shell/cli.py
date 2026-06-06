"""CLI delivery mechanism (Typer): a shell around the *same* pure core as the API.

Two commands over the persistent SQLite store, so the demo is realistic — `add`
a user in one invocation, `rename` it in another, the data survives in between:

    python -m app.shell.cli add 1 ada@example.com Ada
    python -m app.shell.cli rename 1 "Ada Lovelace"
    python -m app.shell.cli --help

Typer owns argument parsing and exit codes; each command body is the imperative
shell: load -> decide (pure) -> save/render. No use-case object, no port.
"""
from typing import Annotated

import typer

from app.core.result import Err, Ok
from app.core.user import UserId, change_display_name, create_user, describe
from app.shell.sqlite_store import DEFAULT_DB_PATH, SqliteUserStore

cli = typer.Typer(
    help="Manage users — a CLI shell around the same pure core as the HTTP API.",
    no_args_is_help=True,
)


@cli.command()
def add(
    user_id: Annotated[str, typer.Argument(help="ID for the new user.")],
    email: Annotated[str, typer.Argument(help="Email address.")],
    display_name: Annotated[str, typer.Argument(help="Display name.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Add a user (the inputs are validated, then persisted)."""
    store = SqliteUserStore(db)
    if store.get(UserId(user_id)) is not None:
        typer.echo(f"error: user {user_id!r} already exists", err=True)
        raise typer.Exit(code=1)
    match create_user(user_id, email, display_name):
        case Ok(user):
            store.save(user)
            typer.echo(f"added {user.id} -> {user.email.value} / {user.display_name.value!r}")
        case Err(problems):
            for problem in problems:  # report every problem at once (§8)
                typer.echo(f"invalid: {describe(problem)}", err=True)
            raise typer.Exit(code=1)


@cli.command()
def rename(
    user_id: Annotated[str, typer.Argument(help="ID of an existing user.")],
    new_display_name: Annotated[str, typer.Argument(help="The new display name.")],
    db: Annotated[str, typer.Option(help="SQLite database file.")] = DEFAULT_DB_PATH,
) -> None:
    """Change an existing user's display name."""
    store = SqliteUserStore(db)
    user = store.get(UserId(user_id))
    if user is None:
        typer.echo(f"error: user {user_id!r} not found (add it first)", err=True)
        raise typer.Exit(code=1)
    match change_display_name(user, new_display_name):
        case Ok(updated):
            store.save(updated)
            typer.echo(f"renamed {updated.id} -> {updated.display_name.value!r}")
        case Err(_):
            typer.echo("invalid: display_name cannot be empty", err=True)
            raise typer.Exit(code=1)


if __name__ == "__main__":
    cli()
