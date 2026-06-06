"""The business rules, tested as pure functions — no fake repository, no mocks.

This is the headline of the rewrite. The original `tests/test_use_case.py` had
to construct an `InMemoryUserRepository` and inject it just to exercise the rule.
Here the rules are pure functions: pass values, assert on the returned value.
"No mocking code you wrote" (§14.4) falls out of the design, because there is no
I/O in the thing under test.
"""

from app.core.result import Err, Ok
from app.core.user import (
    DisplayName,
    Email,
    EmptyDisplayName,
    MalformedEmail,
    User,
    UserId,
    change_display_name,
    create_user,
    describe,
    rename,
)


def a_user(name: str = "old") -> User:
    return User(
        id=UserId("1"),
        email=Email.parse("a@b.com").unwrap(),
        display_name=DisplayName.parse(name).unwrap(),
    )


# --- create_user: collects every problem at once (§8) ---


def test_create_user_succeeds_and_normalizes() -> None:
    assert create_user("7", "  Ada@Example.COM ", "  Ada  ") == Ok(
        User(id=UserId("7"), email=Email("ada@example.com"), display_name=DisplayName("Ada"))
    )


def test_create_user_collects_all_problems() -> None:
    assert create_user("7", "not-an-email", "   ") == Err(
        [MalformedEmail("not-an-email"), EmptyDisplayName()]
    )


def test_create_user_reports_a_single_problem() -> None:
    assert create_user("7", "ada@example.com", "   ") == Err([EmptyDisplayName()])


def test_describe_renders_each_variant() -> None:
    assert describe(MalformedEmail("nope")) == "invalid email: 'nope'"
    assert describe(EmptyDisplayName()) == "display name cannot be empty"


# --- change_display_name ---


def test_change_display_name_succeeds() -> None:
    assert change_display_name(a_user(), "new name") == Ok(a_user("new name"))


def test_change_display_name_rejects_empty() -> None:
    assert change_display_name(a_user(), "   ") == Err(EmptyDisplayName())


def test_rename_does_not_mutate_input() -> None:
    user = a_user("before")
    renamed = rename(user, DisplayName.parse("after").unwrap())
    assert renamed.display_name == DisplayName("after")
    assert user.display_name == DisplayName("before")  # input untouched (§11)


# --- smart constructors (§8, §9) ---


def test_email_parse_normalizes_and_accepts() -> None:
    assert Email.parse("  Ada@Example.COM ") == Ok(Email("ada@example.com"))


def test_email_parse_rejects_malformed() -> None:
    assert Email.parse("not-an-email") == Err(MalformedEmail("not-an-email"))


def test_display_name_parse_trims() -> None:
    assert DisplayName.parse("  Grace  ") == Ok(DisplayName("Grace"))


def test_display_name_parse_rejects_blank() -> None:
    assert DisplayName.parse("   ") == Err(EmptyDisplayName())
