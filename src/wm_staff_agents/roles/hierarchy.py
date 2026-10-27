"""Role hierarchy: configurable staff map.

An administrator defines roles in config/roles.yaml. Each role declares:
  - name and mission (who it is, what it does)
  - responsibilities (what it is accountable for)
  - inputs (what information it receives — which other roles' outputs it needs)
  - outputs (what it produces — named deliverables the next roles consume)
  - doctrine_focus (which doctrine guides its decisions)
  - task_prompt (what it is asked to do each turn — optional, has a sensible default)
  - reports_to / rank (hierarchy position for display and ordering)

The orchestrator uses the declared inputs/outputs to order execution:
roles with no dependencies run first, then roles whose dependencies are satisfied,
with independent roles running in parallel.

No role is hardcoded. The 6-role example in config/roles.yaml is just one
possible staff map. An administrator can add, remove, or reorganise roles
entirely through YAML and the StaffEngine bundle regenerates.

StaffEngine note: The hierarchy is stored as both YAML (authoritative for
execution) and a StaffEngine .foundry.json bundle (for visual editing).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Role(BaseModel):
    """One position in the staff hierarchy.

    To create a new staff map, define roles with these fields in config/roles.yaml.
    There are no required role IDs — any set of roles works as long as their
    input/output wiring is consistent.
    """

    model_config = {"frozen": True}

    id: str = Field(description="Stable slug, e.g. force_commander")
    name: str = Field(description="Human-readable, e.g. Force Commander")
    rank: int = Field(default=2, description="1=top, higher=lower — display and tie-break order")
    description: str = Field(description="What this role does — shown in UI and prompts")
    responsibilities: tuple[str, ...] = Field(default=(), description="What this role is accountable for")
    doctrine_focus: tuple[str, ...] = Field(
        default=(), description="Which doctrine documents guide this role")

    # -- Wiring: how this role connects to others --
    inputs: tuple[str, ...] = Field(
        default=(),
        description=(
            "Deliverable names this role needs before it can act. "
            "Each name matches an 'outputs' entry of another role. "
            "Empty = runs first (only needs game state + commander intent if not commander)."
        ),
    )
    outputs: tuple[str, ...] = Field(
        default=(),
        description=(
            "Deliverable names this role produces for downstream roles. "
            "For example, the intelligence officer might produce 'targets' and "
            "'threat_assessment' that the targeteer then consumes."
        ),
    )

    reports_to: str | None = Field(default=None, description="Parent role id for hierarchy display")
    team_scope: Literal["red", "blue", "both"] = "both"

    # -- Prompt: how this role is asked to act each turn --
    task_prompt: str = Field(
        default="",
        description=(
            "What this role is asked to do each turn. Jinja-style variables available: "
            "{team_name}, {turn}, {game_state}, {commander_intent}, {previous_outcome}, "
            "plus one variable per declared input (e.g. {targets}, {threat_assessment}). "
            "If empty, a generic prompt is built from description + responsibilities."
        ),
    )
    # What the JSON response should contain — keys the role must return
    expected_keys: tuple[str, ...] = Field(
        default=("summary", "doctrine_refs"),
        description="JSON keys this role's response should include",
    )

    def prompt_for_turn(self, team_name: str = "") -> str:
        """Build the task prompt — custom or auto-generated."""
        if self.task_prompt:
            return self.task_prompt
        # Auto-generate from description + responsibilities
        lines = [f"You are the {self.name} for {team_name}." if team_name else f"You are the {self.name}.",
                 self.description]
        if self.responsibilities:
            lines.append("Your responsibilities:")
            for r in self.responsibilities:
                lines.append(f"  - {r}")
        if self.inputs:
            lines.append(f"You receive: {', '.join(self.inputs)}")
        if self.outputs:
            lines.append(f"You produce: {', '.join(self.outputs)}")
        lines.append(
            f"Respond as JSON with keys: {', '.join(self.expected_keys)}. "
            f"Include doctrine_refs citing which doctrine supports each decision."
        )
        return "\n".join(lines)


class RoleHierarchy(BaseModel):
    """The full staff hierarchy for one team."""

    model_config = {"frozen": True}

    name: str
    description: str
    roles: tuple[Role, ...]

    def get(self, role_id: str) -> Role:
        for r in self.roles:
            if r.id == role_id:
                return r
        raise KeyError(f"Unknown role: {role_id}")

    def children_of(self, role_id: str) -> list[Role]:
        return [r for r in self.roles if r.reports_to == role_id]

    def top(self) -> Role:
        tops = [r for r in self.roles if r.reports_to is None]
        assert len(tops) == 1, f"Expected 1 top role, got {len(tops)}"
        return tops[0]

    def ordered(self) -> list[Role]:
        """Topological order by rank."""
        return sorted(self.roles, key=lambda r: r.rank)

    def execution_levels(self) -> list[list[Role]]:
        """Group roles into parallel execution levels based on input dependencies.

        Level 0: roles with no inputs (run first, only need game state).
        Level N: roles whose inputs are all produced by earlier levels.
        Roles within a level run in parallel.
        """
        # Map output name → producing role(s)
        output_to_role: dict[str, str] = {}
        for role in self.roles:
            for out in role.outputs:
                output_to_role[out] = role.id

        # Determine level for each role
        levels: dict[str, int] = {}

        def get_level(role_id: str, visiting: set[str] | None = None) -> int:
            if role_id in levels:
                return levels[role_id]
            visiting = visiting or set()
            if role_id in visiting:
                raise ValueError(f"Circular dependency involving role {role_id}")
            visiting.add(role_id)

            role = self.get(role_id)
            if not role.inputs:
                levels[role_id] = 0
                return 0

            max_dep = -1
            for inp in role.inputs:
                producer = output_to_role.get(inp)
                if producer is None:
                    # Input comes from outside (e.g. game_state) — no dependency
                    continue
                dep_level = get_level(producer, visiting)
                max_dep = max(max_dep, dep_level)

            level = max_dep + 1
            levels[role_id] = level
            visiting.remove(role_id)
            return level

        for role in self.roles:
            get_level(role.id)

        # Group by level
        max_level = max(levels.values()) if levels else 0
        result: list[list[Role]] = [[] for _ in range(max_level + 1)]
        for role in self.roles:
            result[levels[role.id]].append(role)

        # Sort within each level by rank for determinism
        for level_roles in result:
            level_roles.sort(key=lambda r: r.rank)

        return result

    def validate_wiring(self) -> list[str]:
        """Check that all inputs have a producer. Return warnings."""
        all_outputs: set[str] = set()
        for r in self.roles:
            all_outputs.update(r.outputs)

        warnings: list[str] = []
        for r in self.roles:
            for inp in r.inputs:
                if inp not in all_outputs:
                    warnings.append(
                        f"Role '{r.id}' needs input '{inp}' but no role produces it"
                    )
        return warnings


def load_hierarchy(path: Path | None = None) -> RoleHierarchy:
    """Load hierarchy from YAML, or return the example default."""
    if path is None:
        # Load from the shipped config file
        default = Path(__file__).parent.parent.parent.parent / "config" / "roles.yaml"
        if default.exists():
            return load_hierarchy(default)
        raise FileNotFoundError("No hierarchy path given and default config/roles.yaml not found")
    data = yaml.safe_load(path.read_text())
    return RoleHierarchy.model_validate(data)


def hierarchy_to_yaml(hierarchy: RoleHierarchy) -> str:
    return yaml.safe_dump(hierarchy.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
