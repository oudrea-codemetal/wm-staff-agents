"""Staff orchestrator: runs the hierarchical turn loop.

The turn loop is the heart of the demo. Each turn:

  1. Force Commander sets intent (top-down)
  2. Intelligence nominates targets (feeds targeteer)
  3. Targeteer produces feasible strikes (feeds support + executors)
  4. Support Planner plans enablers (feeds executors)
  5. Air Wing + Maritime Commanders generate ITO sorties (parallel)
  6. ITO Builder assembles the integrated task order
  7. Dice roller adjudicates engagements
  8. Doctrine checker (Jev) validates each role's justification
  9. Turn report is produced

Context flows down (intent → targets → tasking) and up (results → next intent).
Each role sees what it needs: commander sees everything, staff sees intent,
executors see the full staff picture.

Human slot-in/out: any role can be occupied by a human via the UI or Slack.
When slotted in, that role's agent is skipped and the human's input is used.
When slotted out, the agent resumes with the handover note as context.
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
from wm_staff_agents.warmatrix.ito import ITOBuilder, IntegratedTaskOrder

logger = logging.getLogger(__name__)


class StaffOrchestrator:
    """Orchestrates one team's turn through the role hierarchy."""

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
        """Run one full turn for this team.

        Returns a dict with all role outputs, the ITO, and Jev verdicts.
        """
        role_outputs: dict[str, Any] = {}

        # 1. Force Commander — sets intent
        fc_output = await self._run_role(
            "force_commander", turn, game_state,
            previous_outcome=previous_outcome,
        )
        role_outputs["force_commander"] = fc_output
        commander_intent = fc_output.get("intent", "")

        # 2. Intelligence Officer — nominates targets
        intel_output = await self._run_role(
            "intelligence_officer", turn, game_state,
            commander_intent=commander_intent,
            previous_outcome=previous_outcome,
        )
        role_outputs["intelligence_officer"] = intel_output

        # 3. Targeteer — weaponeering
        nominated = json.dumps(intel_output.get("targets", []), indent=2)
        targeteer_output = await self._run_role(
            "targeteer", turn, game_state,
            commander_intent=commander_intent,
            extra_context={"nominated_targets": nominated},
            previous_outcome=previous_outcome,
        )
        role_outputs["targeteer"] = targeteer_output

        # 4. Support Planner
        targeting_plan = json.dumps(targeteer_output.get("solutions", []), indent=2)
        support_output = await self._run_role(
            "support_planner", turn, game_state,
            commander_intent=commander_intent,
            extra_context={"targeting_plan": targeting_plan},
            previous_outcome=previous_outcome,
        )
        role_outputs["support_planner"] = support_output

        # 5. Air Wing + Maritime — parallel
        support_plan = json.dumps(support_output.get("support_sorties", support_output), indent=2)
        threat = intel_output.get("threat_assessment", "")

        air_task, maritime_task = await asyncio.gather(
            self._run_role(
                "air_wing_commander", turn, game_state,
                commander_intent=commander_intent,
                extra_context={
                    "targeting_plan": targeting_plan,
                    "support_plan": support_plan,
                    "threat_assessment": threat,
                },
                previous_outcome=previous_outcome,
            ),
            self._run_role(
                "maritime_commander", turn, game_state,
                commander_intent=commander_intent,
                extra_context={
                    "targeting_plan": targeting_plan,
                    "air_tasking": "",  # maritime runs in parallel, no air tasking yet
                },
                previous_outcome=previous_outcome,
            ),
        )
        role_outputs["air_wing_commander"] = air_task
        role_outputs["maritime_commander"] = maritime_task

        # 6. Build ITO
        ito = self.ito_builder.build(
            team=self.team.config.side,
            turn=turn,
            commander_intent=commander_intent,
            intelligence_targets=intel_output.get("targets", []),
            targeting_plan=targeteer_output.get("solutions", []),
            support_plan=support_output.get("support_sorties", []),
            air_tasking=air_task.get("sorties", []),
            maritime_tasking=maritime_task.get("taskings", []),
        )
        role_outputs["_ito"] = ito.model_dump()

        return role_outputs

    async def _run_role(
        self,
        role_id: str,
        turn: int,
        game_state: str,
        commander_intent: str = "",
        extra_context: dict[str, str] | None = None,
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
            extra_context=extra_context,
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
            # Resolve refs to convention objects
            conventions = [c for c in self.doctrine_corpus.conventions if c.id in refs]
            # Build decision text from the output
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
