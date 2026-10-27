"""Staff orchestrator: runs the hierarchical turn loop.

No role is hardcoded. The orchestrator reads the hierarchy's input/output
wiring and executes roles in dependency order:
  - Level 0: roles with no inputs (e.g. Force Commander) — run first
  - Level N: roles whose inputs are all produced by earlier levels — run when ready
  - Roles within a level run in parallel (asyncio.gather)

Each role's outputs become available as inputs to downstream roles.
After all roles have run, the deliverables tagged as sorties/taskings
are collected into an ITO and adjudicated.

Human slot-in/out: any role can be held by a human via the UI or Slack.
When slotted in, that role's agent is skipped and the human's input is used.
The Jev doctrine check still applies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from wm_staff_agents.agents.definitions import RoleAgent
from wm_staff_agents.doctrine.corpus import DoctrineCorpus
from wm_staff_agents.jev.checker import DoctrineChecker, JevClient
from wm_staff_agents.roles.hierarchy import RoleHierarchy
from wm_staff_agents.roles.team import Team
from wm_staff_agents.warmatrix.dice import DiceRoller
from wm_staff_agents.warmatrix.ito import ITOBuilder

logger = logging.getLogger(__name__)


class StaffOrchestrator:
    """Orchestrates one team's turn through whatever roles are configured."""

    def __init__(
        self,
        team: Team,
        hierarchy: RoleHierarchy,
        agents: dict[str, RoleAgent],
        doctrine_corpus: DoctrineCorpus,
        jev_checker: DoctrineChecker | None = None,
        dice_roller: DiceRoller | None = None,
        ito_builder: ITOBuilder | None = None,
        human_inputs: dict[str, str] | None = None,
    ) -> None:
        self.team = team
        self.hierarchy = hierarchy
        self.agents = agents
        self.doctrine_corpus = doctrine_corpus
        self.jev_checker = jev_checker or DoctrineChecker(JevClient())
        self.dice_roller = dice_roller or DiceRoller(seed=42)
        self.ito_builder = ito_builder or ITOBuilder()
        self.human_inputs = human_inputs or {}

        warnings = hierarchy.validate_wiring()
        for w in warnings:
            logger.warning("Hierarchy wiring: %s", w)

    def set_human_input(self, role_id: str, text: str) -> None:
        self.human_inputs[role_id] = text

    def clear_human_input(self, role_id: str) -> None:
        self.human_inputs.pop(role_id, None)

    async def run_turn(
        self,
        turn: int,
        game_state: str,
        previous_outcome: str = "",
    ) -> dict[str, Any]:
        """Run one turn: execute roles level by level, then build ITO."""
        role_outputs: dict[str, Any] = {}
        deliverables: dict[str, Any] = {}  # output_name → value
        commander_intent = ""

        levels = self.hierarchy.execution_levels()
        logger.info("Turn %d: %d execution levels", turn, len(levels))

        for level_idx, level_roles in enumerate(levels):
            logger.info("  Level %d: %s", level_idx, [r.id for r in level_roles])

            # Gather inputs for each role in this level from deliverables
            tasks: list[Any] = []
            task_role_ids: list[str] = []

            for role in level_roles:
                # Collect this role's declared inputs from deliverables
                role_inputs: dict[str, Any] = {}
                for inp in role.inputs:
                    if inp in deliverables:
                        role_inputs[inp] = deliverables[inp]

                tasks.append(self._run_role(
                    role.id, turn, game_state,
                    commander_intent=commander_intent,
                    available_inputs=role_inputs,
                    previous_outcome=previous_outcome,
                ))
                task_role_ids.append(role.id)

            results = await asyncio.gather(*tasks)

            for role_id, result in zip(task_role_ids, results):
                role_outputs[role_id] = result
                # Publish this role's outputs as deliverables
                role = self.hierarchy.get(role_id)
                for out_name in role.outputs:
                    # Deliverable value is the matching key in the result, or the whole result
                    if out_name in result:
                        deliverables[out_name] = result[out_name]
                    elif out_name == "commander_intent" and "intent" in result:
                        deliverables[out_name] = result["intent"]

                # Track commander intent specially (used as context for all downstream roles)
                if "intent" in result and not commander_intent:
                    commander_intent = result["intent"]

        # Build ITO from whatever sortie/tasking deliverables exist
        ito = self._build_ito(turn, commander_intent, deliverables, role_outputs)
        role_outputs["_ito"] = ito.model_dump()
        role_outputs["_deliverables"] = deliverables

        return role_outputs

    def _build_ito(
        self,
        turn: int,
        commander_intent: str,
        deliverables: dict[str, Any],
        role_outputs: dict[str, Any],
    ) -> Any:
        """Assemble ITO from deliverables. Looks for sortie-like outputs generically."""
        # Collect anything that looks like sorties
        air_sorties: list[dict] = []
        maritime: list[dict] = []
        support: list[dict] = []

        for key, val in deliverables.items():
            if not isinstance(val, list):
                continue
            if key in ("air_sorties", "sorties"):
                air_sorties.extend(val if isinstance(val, list) else [])
            elif key in ("maritime_taskings", "taskings"):
                maritime.extend(val if isinstance(val, list) else [])
            elif key in ("support_plan", "support_sorties"):
                support.extend(val if isinstance(val, list) else [])

        # Also check role outputs directly for sorties
        for role_id, output in role_outputs.items():
            if role_id.startswith("_"):
                continue
            for sk in ("sorties", "taskings", "support_sorties"):
                if sk in output and isinstance(output[sk], list):
                    if sk == "sorties" and output[sk] not in [air_sorties]:
                        # Only add if not already in deliverables
                        for item in output[sk]:
                            if item not in air_sorties:
                                air_sorties.append(item)

        return self.ito_builder.build(
            team=self.team.config.side,
            turn=turn,
            commander_intent=commander_intent,
            intelligence_targets=deliverables.get("targets", []),
            targeting_plan=deliverables.get("targeting_plan", []),
            support_plan=support,
            air_tasking=air_sorties,
            maritime_tasking=maritime,
        )

    async def _run_role(
        self,
        role_id: str,
        turn: int,
        game_state: str,
        commander_intent: str = "",
        available_inputs: dict[str, Any] | None = None,
        previous_outcome: str = "",
    ) -> dict[str, Any]:
        agent = self.agents.get(role_id)
        if agent is None:
            logger.warning("No agent for role %s", role_id)
            return {"error": f"No agent for {role_id}", "doctrine_refs": []}

        human_override = self.human_inputs.get(role_id)
        if human_override is not None:
            logger.info("Role %s using human input", role_id)

        result = await agent.generate(
            turn=turn,
            game_state=game_state,
            commander_intent=commander_intent,
            available_inputs=available_inputs,
            previous_outcome=previous_outcome,
            human_override=human_override,
        )
        result["_holder"] = self.team.slot_for(role_id).holder
        result["_role"] = role_id
        return result

    async def check_doctrine(
        self,
        role_outputs: dict[str, Any],
    ) -> dict[str, Any]:
        """Run Jev doctrine checks on all role outputs."""
        decisions: list[dict[str, Any]] = []
        for role_id, output in role_outputs.items():
            if role_id.startswith("_"):
                continue
            refs = output.get("doctrine_refs", [])
            conventions = [c for c in self.doctrine_corpus.conventions if c.id in refs]
            decision = json.dumps({k: v for k, v in output.items() if not k.startswith("_")}, indent=2)
            justification = output.get("rationale", output.get("summary", output.get("intent", decision[:500])))
            decisions.append({
                "role": role_id,
                "decision": decision,
                "justification": str(justification),
                "doctrine": conventions,
            })
        if self.jev_checker:
            return await self.jev_checker.check_turn(decisions)
        return {}
