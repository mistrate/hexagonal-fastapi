"""Team domain — pure functions, no mocks."""

from app.core.result import Err, Ok
from app.core.team import EmptyTeamName, Team, TeamId, TeamName, create_team


def test_create_team_succeeds_and_trims() -> None:
    assert create_team("t1", "  Platform  ") == Ok(Team(id=TeamId("t1"), name=TeamName("Platform")))


def test_create_team_rejects_blank_name() -> None:
    assert create_team("t1", "   ") == Err(EmptyTeamName())


def test_team_name_parse_trims() -> None:
    assert TeamName.parse("  Core  ") == Ok(TeamName("Core"))
