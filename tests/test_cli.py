"""The CLI shell, tested through Typer's CliRunner against a temp database.

The CLI is a delivery mechanism like the HTTP API — same pure core, different
shell. The `--db` option (which exists for real use) is the test seam: each
invocation targets a throwaway SQLite file, so flows run in-process, persisting
between commands just as on the command line.
"""

from pathlib import Path

from typer.testing import CliRunner, Result

from app.shell.cli import cli

runner = CliRunner()


def _run(tmp_path: Path, *args: str) -> Result:
    return runner.invoke(cli, [*args, "--db", str(tmp_path / "app.db")])


def _seed_team(tmp_path: Path) -> None:
    assert _run(tmp_path, "add-user", "admin", "boss@example.com", "Boss").exit_code == 0
    assert _run(tmp_path, "add-team", "t1", "Core", "admin").exit_code == 0


# --- users ---


def test_add_user_then_rename(tmp_path: Path) -> None:
    assert _run(tmp_path, "add-user", "u1", "ada@example.com", "Ada").exit_code == 0
    renamed = _run(tmp_path, "rename-user", "u1", "Ada Lovelace")
    assert renamed.exit_code == 0
    assert "Ada Lovelace" in renamed.output


def test_add_user_reports_all_problems(tmp_path: Path) -> None:
    result = _run(tmp_path, "add-user", "u1", "nope", "  ")
    assert result.exit_code == 1
    assert "invalid email" in result.stderr
    assert "display name cannot be empty" in result.stderr


def test_add_user_duplicate_fails(tmp_path: Path) -> None:
    assert _run(tmp_path, "add-user", "u1", "ada@example.com", "Ada").exit_code == 0
    assert _run(tmp_path, "add-user", "u1", "x@y.com", "Other").exit_code == 1


# --- teams ---


def test_add_team_requires_existing_admin(tmp_path: Path) -> None:
    assert _run(tmp_path, "add-team", "t1", "Core", "ghost").exit_code == 1


def test_founder_is_admin(tmp_path: Path) -> None:
    _seed_team(tmp_path)
    listed = _run(tmp_path, "memberships", "admin")
    assert listed.exit_code == 0
    assert "t1 -> admin" in listed.output


# --- memberships ---


def test_membership_full_flow(tmp_path: Path) -> None:
    _seed_team(tmp_path)
    assert _run(tmp_path, "add-user", "u1", "ada@example.com", "Ada").exit_code == 0
    assert _run(tmp_path, "add-member", "t1", "u1", "member").exit_code == 0

    promoted = _run(tmp_path, "update-role", "t1", "u1", "admin")
    assert promoted.exit_code == 0
    assert "admin" in promoted.output

    assert "t1 -> admin" in _run(tmp_path, "memberships", "u1").output
    assert _run(tmp_path, "remove-member", "t1", "u1").exit_code == 0
    assert "not a member of any team" in _run(tmp_path, "memberships", "u1").output


def test_add_member_unknown_user_fails(tmp_path: Path) -> None:
    _seed_team(tmp_path)
    assert _run(tmp_path, "add-member", "t1", "ghost", "member").exit_code == 1


def test_add_member_bad_role_fails(tmp_path: Path) -> None:
    _seed_team(tmp_path)
    assert _run(tmp_path, "add-member", "t1", "admin", "owner").exit_code == 1


# --- the "at least one admin" invariant ---


def test_cannot_remove_last_admin(tmp_path: Path) -> None:
    _seed_team(tmp_path)
    result = _run(tmp_path, "remove-member", "t1", "admin")
    assert result.exit_code == 1
    assert "last admin" in result.stderr


def test_cannot_demote_last_admin(tmp_path: Path) -> None:
    _seed_team(tmp_path)
    assert _run(tmp_path, "update-role", "t1", "admin", "member").exit_code == 1


def test_can_remove_admin_when_another_exists(tmp_path: Path) -> None:
    _seed_team(tmp_path)
    assert _run(tmp_path, "add-user", "u1", "ada@example.com", "Ada").exit_code == 0
    assert _run(tmp_path, "add-member", "t1", "u1", "admin").exit_code == 0
    assert _run(tmp_path, "remove-member", "t1", "admin").exit_code == 0
