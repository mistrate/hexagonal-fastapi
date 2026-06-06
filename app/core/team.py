"""The team domain — pure. A team has an id and a non-empty name.

Mirrors `user.py`: a `NewType` id, a smart-constructor name (parse at the edge,
invariant enforced by `__post_init__`), a frozen entity, and a pure constructor
returning a `Result`.
"""

from dataclasses import dataclass
from typing import NewType

from app.core.errors import DomainError
from app.core.result import Err, Ok, Result

TeamId = NewType("TeamId", str)


@dataclass(frozen=True, slots=True)
class EmptyTeamName(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class TeamName:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("team name cannot be empty")

    @classmethod
    def parse(cls, raw: str) -> Result[TeamName, EmptyTeamName]:
        trimmed = raw.strip()
        if not trimmed:
            return Err(EmptyTeamName())
        return Ok(cls(trimmed))


@dataclass(frozen=True, slots=True)
class Team:
    id: TeamId
    name: TeamName


def create_team(team_id: str, raw_name: str) -> Result[Team, EmptyTeamName]:
    """Pure: parse the name, then build the team. The id is a system-supplied
    identifier (a `NewType`), so it carries no invariant to check."""
    return TeamName.parse(raw_name).map(lambda name: Team(id=TeamId(team_id), name=name))
