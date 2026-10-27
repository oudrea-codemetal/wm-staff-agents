"""Game engine: turns, adjudication, and reporting.

The engine runs the full game loop:
  for turn in 1..max_turns:
    red_ito = await red_orchestrator.run_turn(turn, state)
    blue_ito = await blue_orchestrator.run_turn(turn, state)
    result = dice adjudication (or WarMatrix native)
    reports = doctrine checks (Jev) + turn narrative
    state = apply results

Why this shape: The engine is the one place where both teams' outputs
meet. It owns the turn counter, the shared game state, and the report
generation. Individual orchestrators own their team's hierarchy.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from wm_staff_agents.agents.definitions import build_all_agents
from wm_staff_agents.agents.orchestrator import StaffOrchestrator
from wm_staff_agents.doctrine.corpus import DoctrineCorpus
from wm_staff_agents.game.scenario import Scenario
from wm_staff_agents.jev.checker import DoctrineChecker, JevClient
from wm_staff_agents.roles.hierarchy import RoleHierarchy
from wm_staff_agents.roles.team import Team, TeamConfig, default_team_configs
from wm_staff_agents.warmatrix.dice import DiceRoller
from wm_staff_agents.warmatrix.ito import ITOBuilder


class GameState(BaseModel):
    turn: int = 0
    scenario_name: str
    red_losses: int = 0
    blue_losses: int = 0
    red_sorties_flown: int = 0
    blue_sorties_flown: int = 0
    events: list[str] = Field(default_factory=list)

    def describe(self) -> str:
        return (
            f"Scenario: {self.scenario_name}\n"
            f"Turn: {self.turn}\n"
            f"Cumulative losses — Red: {self.red_losses}, Blue: {self.blue_losses}\n"
            f"Sorties flown — Red: {self.red_sorties_flown}, Blue: {self.blue_sorties_flown}\n"
            f"Recent events:\n" + "\n".join(f"  - {e}" for e in self.events[-10:])
        )


class TurnReport(BaseModel):
    turn: int
    timestamp: str
    red_outputs: dict[str, Any] = Field(default_factory=dict)
    blue_outputs: dict[str, Any] = Field(default_factory=dict)
    red_jev: dict[str, Any] = Field(default_factory=dict)
    blue_jev: dict[str, Any] = Field(default_factory=dict)
    dice_result: dict[str, Any] = Field(default_factory=dict)
    narrative: str = ""

    def summary(self) -> str:
        lines = [f"=== Turn {self.turn} Report ===", self.narrative]
        if self.dice_result:
            lines.append(f"Dice: {json.dumps(self.dice_result, indent=2)}")
        return "\n".join(lines)


class GameEngine:
    """Runs the full South China Sea Conflict game."""

    def __init__(
        self,
        scenario: Scenario,
        hierarchy: RoleHierarchy,
        doctrine_corpus: DoctrineCorpus,
        red_team: Team | None = None,
        blue_team: Team | None = None,
        llm_config: dict[str, Any] | None = None,
        warmatrix_client: Any | None = None,
        jev_url: str | None = None,
        dice_seed: int = 42,
    ) -> None:
        self.scenario = scenario
        self.hierarchy = hierarchy
        self.doctrine_corpus = doctrine_corpus
        self.warmatrix_client = warmatrix_client
        self.llm_config = llm_config or {}

        # Teams
        if red_team is None or blue_team is None:
            rc, bc = default_team_configs(hierarchy)
            self.red_team = red_team or Team(hierarchy=hierarchy, config=rc)
            self.blue_team = blue_team or Team(hierarchy=hierarchy, config=bc)
        else:
            self.red_team = red_team
            self.blue_team = blue_team

        # Shared services
        jev_client = JevClient(base_url=jev_url) if jev_url else JevClient()
        self.jev_checker = DoctrineChecker(jev_client=jev_client)
        self.dice_roller = DiceRoller(seed=dice_seed)
        self.ito_builder = ITOBuilder()

        # Agents per team
        self.red_agents = build_all_agents(
            list(hierarchy.roles), self.red_team.config.name, doctrine_corpus, self.llm_config)
        self.blue_agents = build_all_agents(
            list(hierarchy.roles), self.blue_team.config.name, doctrine_corpus, self.llm_config)

        # Orchestrators
        self.red_orch = StaffOrchestrator(
            team=self.red_team, hierarchy=hierarchy, agents=self.red_agents,
            doctrine_corpus=doctrine_corpus, jev_checker=self.jev_checker,
            dice_roller=self.dice_roller, ito_builder=self.ito_builder,
        )
        self.blue_orch = StaffOrchestrator(
            team=self.blue_team, hierarchy=hierarchy, agents=self.blue_agents,
            doctrine_corpus=doctrine_corpus, jev_checker=self.jev_checker,
            dice_roller=self.dice_roller, ito_builder=self.ito_builder,
        )

        self.state = GameState(scenario_name=scenario.name)
        self.reports: list[TurnReport] = []

    async def run_turn(self, turn: int) -> TurnReport:
        """Run one turn: both teams plan, then adjudicate."""
        game_state_text = self.state.describe()
        previous = self.reports[-1].narrative if self.reports else "Game start — no previous outcome."

        # Both teams plan concurrently
        red_out, blue_out = await asyncio.gather(
            self.red_orch.run_turn(turn, self._team_game_state("red"), previous),
            self.blue_orch.run_turn(turn, self._team_game_state("blue"), previous),
        )

        # Doctrine checks (also concurrent)
        red_jev, blue_jev = await asyncio.gather(
            self.red_orch.check_doctrine(red_out),
            self.blue_orch.check_doctrine(blue_out),
        )

        # Dice adjudication
        red_sorties = len(red_out.get("_ito", {}).get("sorties", []))
        blue_sorties = len(blue_out.get("_ito", {}).get("sorties", []))

        # Try WarMatrix native first, fall back to local dice
        dice_result = None
        if self.warmatrix_client and self.scenario.warmatrix_game_id:
            dice_result = await self.dice_roller.adjudicate_via_warmatrix(
                turn, self.scenario.warmatrix_game_id,
                self.scenario.warmatrix_move_id or 7,
                self.warmatrix_client,
            )
        if dice_result is None:
            dice_result = self.dice_roller.adjudicate_turn(
                turn, red_sorties or 4, blue_sorties or 6)

        # Update state
        self.state.turn = turn
        self.state.red_losses += dice_result.red_losses
        self.state.blue_losses += dice_result.blue_losses
        self.state.red_sorties_flown += red_sorties
        self.state.blue_sorties_flown += blue_sorties
        self.state.events.append(
            f"Turn {turn}: Red {dice_result.red_losses} losses, Blue {dice_result.blue_losses} losses")

        narrative = (
            f"Turn {turn} of the South China Sea Conflict.\n"
            f"Red intent: {red_out.get('force_commander', {}).get('intent', 'N/A')}\n"
            f"Blue intent: {blue_out.get('force_commander', {}).get('intent', 'N/A')}\n"
            f"Red sorties: {red_sorties}, Blue sorties: {blue_sorties}\n"
            f"Adjudication: {dice_result.narrative}\n"
            f"Cumulative — Red losses: {self.state.red_losses}, Blue losses: {self.state.blue_losses}"
        )

        report = TurnReport(
            turn=turn,
            timestamp=datetime.now(timezone.utc).isoformat(),
            red_outputs=red_out,
            blue_outputs=blue_out,
            red_jev={k: [v.model_dump() for v in vs] for k, vs in red_jev.items()},
            blue_jev={k: [v.model_dump() for v in vs] for k, vs in blue_jev.items()},
            dice_result=dice_result.__dict__ if hasattr(dice_result, '__dict__') else {},
            narrative=narrative,
        )
        self.reports.append(report)
        return report

    async def run_game(self, turns: int | None = None) -> list[TurnReport]:
        """Run the full game for N turns."""
        n = turns or self.scenario.max_turns
        for t in range(1, n + 1):
            await self.run_turn(t)
        return self.reports

    def save_reports(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([r.model_dump() for r in self.reports], indent=2))

    def _team_game_state(self, side: str) -> str:
        base = self.state.describe()
        force = self.scenario.red if side == "red" else self.scenario.blue
        return (
            f"{base}\n\n"
            f"Your force: {force.name}\n"
            f"Your bases: {', '.join(force.bases)}\n"
            f"Your platforms: {', '.join(force.primary_platforms)}\n"
            f"Your objective: {force.objective}"
        )

    # -- Human slot in/out --

    def slot_in(self, side: str, role_id: str, human_id: str, context_note: str = "") -> None:
        orch = self.red_orch if side == "red" else self.blue_orch
        orch.set_human_input(role_id, context_note)
        if side == "red":
            self.red_team = self.red_team.slot_in(role_id, human_id, context_note)
            self.red_orch.team = self.red_team
        else:
            self.blue_team = self.blue_team.slot_in(role_id, human_id, context_note)
            self.blue_orch.team = self.blue_team

    def slot_out(self, side: str, role_id: str, handover_note: str = "") -> None:
        orch = self.red_orch if side == "red" else self.blue_orch
        orch.clear_human_input(role_id)
        if side == "red":
            self.red_team = self.red_team.slot_out(role_id, handover_note)
            self.red_orch.team = self.red_team
        else:
            self.blue_team = self.blue_team.slot_out(role_id, handover_note)
            self.blue_orch.team = self.blue_team

    def human_act(self, side: str, role_id: str, action_text: str) -> None:
        """A human provides input for their slotted-in role."""
        orch = self.red_orch if side == "red" else self.blue_orch
        orch.set_human_input(role_id, action_text)
