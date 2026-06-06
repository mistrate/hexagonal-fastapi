"""Property tests on the pure core (§13: pytest + hypothesis).

A functional core is exactly the code property testing rewards: total functions
over values, no I/O, no setup, nothing to mock. These assert invariants that
should hold for *every* input, not just the handful in the example tests.
"""
from hypothesis import given
from hypothesis import strategies as st

from app.core.result import Err, Ok
from app.core.user import (
    DisplayName,
    Email,
    EmptyDisplayName,
    User,
    UserId,
    change_display_name,
)


def a_user() -> User:
    return User(
        id=UserId("1"),
        email=Email.parse("a@b.com").unwrap(),
        display_name=DisplayName.parse("seed").unwrap(),
    )


@given(st.text())
def test_display_name_parse_is_total(raw: str) -> None:
    # Defined for every string: either a trimmed, non-empty name or the one error.
    match DisplayName.parse(raw):
        case Ok(name):
            assert name.value == raw.strip()
            assert name.value != ""
        case Err(EmptyDisplayName()):
            assert raw.strip() == ""


@given(st.text(min_size=1).filter(lambda s: s.strip() != ""))
def test_change_display_name_succeeds_for_any_nonblank(raw: str) -> None:
    user = a_user()
    expected = User(id=user.id, email=user.email, display_name=DisplayName(raw.strip()))
    assert change_display_name(user, raw) == Ok(expected)
    assert user.display_name.value == "seed"  # purity: input never mutated (§11)
