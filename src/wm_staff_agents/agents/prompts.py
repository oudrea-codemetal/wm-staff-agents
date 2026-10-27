"""Prompt building: constructs LLM prompts from role definitions.

No role-specific prompts are hardcoded here. Each Role carries its own
task_prompt; this module renders it with the current turn's context.

For backwards compatibility, ROLE_PROMPTS is kept as a fallback for any
role that has no task_prompt — but new staff maps should define task_prompt
directly in their YAML.
"""

from __future__ import annotations

from typing import Any

from wm_staff_agents.roles.hierarchy import Role


# Legacy fallback prompts — used only when a role has no task_prompt in YAML.
# New staff maps define task_prompt per-role in config/roles.yaml.
ROLE_PROMPTS: dict[str, dict[str, str]] = {}


def build_system_prompt(role: Role, team_name: str, doctrine_context: str) -> str:
    """Build the system prompt for a role."""
    return (
        f"You are the {role.name} for the {team_name} in the South China Sea Conflict wargame.\n"
        f"{role.description}\n\n"
        f"Your doctrine focus: {', '.join(role.doctrine_focus)}\n\n"
        f"Doctrine guidance for this turn:\n{doctrine_context}\n\n"
        f"Your decisions must cite doctrine — explain which principle supports each choice."
    )


def build_task_prompt(
    role: Role,
    turn: int,
    game_state: str,
    commander_intent: str = "",
    available_inputs: dict[str, Any] | None = None,
    previous_outcome: str = "",
) -> str:
    """Build the task prompt for a role from its declared inputs and task_prompt."""
    available_inputs = available_inputs or {}

    if role.task_prompt:
        # Render the role's own task_prompt with available context
        context_parts: dict[str, str] = {
            "turn": str(turn),
            "game_state": game_state,
            "commander_intent": commander_intent,
            "previous_outcome": previous_outcome or "No previous turn (game start).",
        }
        # Add each input deliverable as a variable
        for inp_name, inp_value in available_inputs.items():
            if isinstance(inp_value, (dict, list)):
                import json
                context_parts[inp_name] = json.dumps(inp_value, indent=2)
            else:
                context_parts[inp_name] = str(inp_value)

        # Try to format the task_prompt with available variables
        try:
            return role.task_prompt.format(**context_parts)
        except KeyError:
            # Prompt references a variable not yet available — include what we have
            header = (
                f"Turn {turn} — Game state:\n{game_state}\n\n"
                f"Commander intent: {commander_intent}\n\n"
                f"Previous outcome: {previous_outcome or 'Game start.'}\n\n"
            )
            if available_inputs:
                import json
                header += "Inputs from upstream roles:\n"
                for k, v in available_inputs.items():
                    header += f"  {k}: {json.dumps(v, indent=2) if isinstance(v, (dict, list)) else v}\n"
                header += "\n"
            header += f"Your task: {role.task_prompt}"
            return header

    # Fallback: legacy ROLE_PROMPTS dict
    fallback = ROLE_PROMPTS.get(role.id)
    if fallback:
        return fallback["task"].format(
            turn=turn, game_state=game_state,
            commander_intent=commander_intent,
            previous_outcome=previous_outcome or "No previous turn.",
            **{k: str(v) for k, v in available_inputs.items()},
        )

    # Auto-generated prompt
    return role.prompt_for_turn()
