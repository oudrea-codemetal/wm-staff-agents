"""Role hierarchy: 6 roles in a command structure.

The hierarchy mirrors a real air operations centre:
  Force Commander (top) → Staff layer → Execution layer

StaffEngine note: This hierarchy is stored as both a YAML config (for the
Python runtime) and a StaffEngine .foundry.json bundle (for the StaffEngine
UI). The YAML is authoritative for execution; the bundle is generated from it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class Role(BaseModel):
    """One position in the hierarchy."""

    model_config = {"frozen": True}

    id: str = Field(description="Stable slug, e.g. force_commander")
    name: str = Field(description="Human-readable, e.g. Force Commander")
    rank: int = Field(description="1=top, higher=lower in hierarchy")
    description: str
    responsibilities: tuple[str, ...]
    doctrine_focus: tuple[str, ...] = Field(
        description="Which doctrine corpora this role leans on"
    )
    reports_to: str | None = Field(default=None, description="Parent role id, None=top")
    team_scope: Literal["red", "blue", "both"] = "both"
    context_template: str = Field(
        default="",
        description="Jinja template for this role's context prompt",
    )


# ------------------------------------------------------------------ 6 roles
# These are the roles the demo ships. An administrator configures them
# by editing config/roles.yaml and regenerating the StaffEngine bundle.

DEFAULT_ROLES: tuple[Role, ...] = (
    Role(
        id="force_commander",
        name="Force Commander",
        rank=1,
        description=(
            "Overall commander for the South China Sea Conflict scenario. "
            "Sets campaign objectives, allocates forces, and approves the air tasking order."
        ),
        responsibilities=(
            "Define campaign objectives and commander's intent",
            "Allocate air, maritime, and support assets between lines of effort",
            "Approve or redirect the integrated tasking order each turn",
            "Assess battle damage and adjust strategy",
        ),
        doctrine_focus=("JP 3-0 Joint Operations", "AFDP 3-0 Operations", "NWP 5-01 Navy Planning"),
        reports_to=None,
    ),
    Role(
        id="intelligence_officer",
        name="Intelligence Officer",
        rank=2,
        description=(
            "Produces the intelligence picture: enemy order of battle, target nominations, "
            "and threat assessments. Feeds the targeting cell."
        ),
        responsibilities=(
            "Maintain enemy order of battle and target list",
            "Nominate targets with priority and rationale",
            "Assess enemy air defence and maritime threats",
            "Provide intelligence preparation of the battlespace",
        ),
        doctrine_focus=("AFDP 3-01 Counterair", "JP 3-02 Amphibious Operations", "MCDP 1 Warfighting"),
        reports_to="force_commander",
    ),
    Role(
        id="targeteer",
        name="Targeteer / Weaponeering Cell",
        rank=2,
        description=(
            "Determines whether nominated targets can be struck: weapon-target pairing, "
            "collateral considerations, and feasibility. The bridge between intelligence and operations."
        ),
        responsibilities=(
            "Match weapons to targets (weaponeering)",
            "Check target feasibility: range, defences, weather, timing",
            "Produce the joint target list with desired effects",
            "Coordinate with support planners on tanker and SEAD needs",
        ),
        doctrine_focus=("AFDP 3-60 Targeting", "AFDP 3-01 Counterair", "JP 3-18 Joint Forcible Entry"),
        reports_to="force_commander",
    ),
    Role(
        id="support_planner",
        name="Support Planner",
        rank=2,
        description=(
            "Plans enabling capabilities: aerial refuelling, airlift, sustainment, and basing. "
            "Without support, strike packages do not reach their targets."
        ),
        responsibilities=(
            "Plan tanker tracks and air refuelling support",
            "Coordinate airlift and sustainment flows",
            "Manage basing, dispersal, and force protection for air assets",
            "Identify support gaps that constrain operations",
        ),
        doctrine_focus=("AFDP 3-36 Mobility Operations", "AFDN 1-21 Agile Combat Employment", "NWP 5-01"),
        reports_to="force_commander",
    ),
    Role(
        id="air_wing_commander",
        name="Air Wing Commander",
        rank=3,
        description=(
            "Commands the air wing: fighters, bombers, and ISR. Converts the tasking order "
            "into specific sorties and ITO entries for the WarMatrix game move."
        ),
        responsibilities=(
            "Generate air sorties: CAP, sweep, strike, SEAD, ISR",
            "Assign squadrons and loadouts to ITO taskings",
            "Manage air-to-air and air-to-ground engagements",
            "Report air battle results and attrition",
        ),
        doctrine_focus=("AFDP 3-01 Counterair", "AFDP 3-03 Counterland", "AFDP 3-60 Targeting"),
        reports_to="force_commander",
    ),
    Role(
        id="maritime_commander",
        name="Maritime Commander",
        rank=3,
        description=(
            "Commands surface and subsurface forces: destroyers, amphibious ships, and submarines. "
            "In the South China Sea scenario, the maritime fight is inseparable from the air fight."
        ),
        responsibilities=(
            "Plan surface manoeuvre and naval fires",
            "Coordinate ship-to-shore movement (if amphibious phase active)",
            "Provide air defence from Aegis and coordinate with air wing",
            "Report maritime battle results and sea control status",
        ),
        doctrine_focus=(
            "NTTP 3-02.1 Ship-to-Shore Movement",
            "NTTP 3-02.2 Supporting Arms Coordination",
            "JP 3-02 Amphibious Operations",
        ),
        reports_to="force_commander",
    ),
)


class RoleHierarchy(BaseModel):
    """The full hierarchy for one team."""

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
        """Topological order: commanders before staff before executors."""
        return sorted(self.roles, key=lambda r: r.rank)


DEFAULT_HIERARCHY = RoleHierarchy(
    name="South China Sea Conflict - Joint Task Force",
    description=(
        "Six-role hierarchy for the South China Sea Conflict wargame. "
        "Instantiated for both Red and Blue teams."
    ),
    roles=DEFAULT_ROLES,
)


def load_hierarchy(path: Path | None = None) -> RoleHierarchy:
    """Load hierarchy from YAML, or return the default."""
    if path is None:
        return DEFAULT_HIERARCHY
    data = yaml.safe_load(path.read_text())
    return RoleHierarchy.model_validate(data)


def hierarchy_to_yaml(hierarchy: RoleHierarchy) -> str:
    return yaml.safe_dump(hierarchy.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
