"""Scenario: South China Sea Conflict.

The scenario is generic by design — it does not name a specific operation.
It describes a South China Sea contingency where Red (an expeditionary force)
seeks to establish control over maritime chokepoints while Blue (a combined
defence force) must maintain freedom of navigation and protect partner territory.

WarMatrix data: the SCS theatre from WarMatrix's available games is used
when a live WarMatrix is present. Otherwise, synthetic laydown data provides
a playable baseline.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ScenarioForce(BaseModel):
    side: str
    name: str
    bases: list[str]
    primary_platforms: list[str]
    objective: str


class Scenario(BaseModel):
    name: str
    description: str
    warmatrix_game_id: int | None = None
    warmatrix_move_id: int | None = None
    warmatrix_team_ids: dict[str, int] = Field(default_factory=dict)
    red: ScenarioForce
    blue: ScenarioForce
    max_turns: int = 6
    turn_duration_hours: int = 12

    @property
    def title(self) -> str:
        return self.name


DEFAULT_SCENARIO = Scenario(
    name="South China Sea Conflict",
    description=(
        "A South China Sea contingency: Red expeditionary forces seek control of "
        "maritime chokepoints and partner territory. Blue combined forces must "
        "maintain freedom of navigation, defend partner positions, and interdict "
        "Red's power projection. The scenario is played as a turn-based wargame "
        "with integrated air and maritime operations."
    ),
    warmatrix_game_id=3,
    warmatrix_move_id=7,
    warmatrix_team_ids={"red": 2, "blue": 1},
    red=ScenarioForce(
        side="red",
        name="Red Expeditionary Force",
        bases=["Fujian Coast", "Hainan", "Woody Island", "Subi Reef"],
        primary_platforms=["J-16", "J-20", "H-6K", "Type 055 DDG", "Type 071 LPD", "KJ-500"],
        objective=(
            "Establish control over the Taiwan Strait and Bashi Channel chokepoints, "
            "neutralise Blue air defences, and secure lodgment for follow-on forces."
        ),
    ),
    blue=ScenarioForce(
        side="blue",
        name="Blue Combined Defence Force",
        bases=["Kadena", "Guam Andersen", "Taiwan West", "Clark", "Iwakuni"],
        primary_platforms=["F-15C", "F-16C", "F-22A", "F-35A", "B-52H", "E-3G", "KC-135", "Arleigh Burke DDG"],
        objective=(
            "Defend partner territory, maintain air superiority over the strait, "
            "interdict Red amphibious and strike forces, and preserve freedom of navigation."
        ),
    ),
    max_turns=6,
    turn_duration_hours=12,
)


def load_scenario(path: Path | None = None) -> Scenario:
    if path is None:
        return DEFAULT_SCENARIO
    data = yaml.safe_load(path.read_text())
    return Scenario.model_validate(data)
