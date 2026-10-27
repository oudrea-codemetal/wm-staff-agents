"""Integrated Task Order (ITO) builder for WarMatrix game moves.

Each turn, the staff hierarchy collaborates to produce ITOs — the air tasking
orders that tell WarMatrix what each side's forces do. An ITO is a collection
of sorties (who flies, from where, to where, with what weapons, doing what).

This module builds ITOs from agent decisions. It translates high-level
staff intent (e.g. 'strike the amphibious group in the strait') into the
structured ITO JSON that WarMatrix expects.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ITOSortie(BaseModel):
    """One sortie in an ITO."""

    callsign: str
    platform_code: str = Field(description="e.g. F-16C, F-15E, B-52H, DDG-51")
    base: str = Field(description="Origin base name")
    mission_type: str = Field(description="DCA, CAP, STRIKE, SEAD, ISR, etc.")
    target_area: str | None = None
    loadout: str | None = None
    patrol_location: tuple[float, float] | None = Field(
        default=None, description="(lon, lat) for CAP/DCA")
    patrol_length_km: float | None = None
    patrol_width_km: float | None = None
    heading_deg: float | None = None
    on_station_at: str | None = None  # ISO8601
    off_station_at: str | None = None
    quantity: int = Field(default=1, ge=1)
    rationale: str = Field(default="", description="Why this sortie, per doctrine")
    doctrine_refs: list[str] = Field(default_factory=list)


class IntegratedTaskOrder(BaseModel):
    """The full ITO for one team on one turn."""

    team: str = Field(description="'red' or 'blue'")
    turn: int
    mission_name: str
    commander_intent: str = Field(description="Force Commander's intent for this turn")
    sorties: list[ITOSortie] = Field(default_factory=list)
    supporting_notes: str = ""

    def to_warmatrix_json(self) -> dict:
        """Convert to WarMatrix ITO JSON shape (simplified)."""
        return {
            "name": self.mission_name,
            "team": self.team,
            "turn": self.turn,
            "commander_intent": self.commander_intent,
            "elements": [
                {
                    "callsign": s.callsign,
                    "platform_code": s.platform_code,
                    "base": s.base,
                    "mission_type": s.mission_type,
                    "target_area": s.target_area,
                    "loadout": s.loadout,
                    "patrol_location": s.patrol_location,
                    "patrol_geometry": {
                        "length_km": s.patrol_length_km,
                        "width_km": s.patrol_width_km,
                        "heading_deg": s.heading_deg,
                    } if s.patrol_length_km else None,
                    "timing": {
                        "on_station_at": s.on_station_at,
                        "off_station_at": s.off_station_at,
                    },
                    "quantity": s.quantity,
                }
                for s in self.sorties
            ],
            "supporting_notes": self.supporting_notes,
        }

    def summary(self) -> str:
        lines = [f"ITO: {self.mission_name} ({self.team}, turn {self.turn})",
                 f"Intent: {self.commander_intent}",
                 f"Sorties: {len(self.sorties)}"]
        for s in self.sorties:
            lines.append(f"  {s.callsign}: {s.quantity}x {s.platform_code} {s.mission_type} from {s.base}"
                         + (f" → {s.target_area}" if s.target_area else ""))
            if s.rationale:
                lines.append(f"    Rationale: {s.rationale}")
        return "\n".join(lines)


class ITOBuilder:
    """Builds ITOs from staff decisions.

    The builder takes the outputs of each role's deliberation and
    assembles them into a coherent ITO. In the full demo, agents do
    this collaboratively. This builder is the deterministic assembly
    layer that validates and formats the result.
    """

    def build(
        self,
        team: str,
        turn: int,
        commander_intent: str,
        intelligence_targets: list[dict],
        targeting_plan: list[dict],
        support_plan: list[dict],
        air_tasking: list[dict],
        maritime_tasking: list[dict],
    ) -> IntegratedTaskOrder:
        """Assemble an ITO from role outputs.

        Each role output is a list of dicts with at least: platform_code,
        base, mission_type. The builder merges them and deduplicates.
        """
        sorties: list[ITOSortie] = []
        callsign_counter = 1

        for task_list in [air_tasking, maritime_tasking, support_plan]:
            for t in task_list:
                sorties.append(ITOSortie(
                    callsign=f"{team.upper()}-{callsign_counter:02d}",
                    platform_code=t.get("platform_code", "F-16C"),
                    base=t.get("base", "Kadena"),
                    mission_type=t.get("mission_type", "DCA"),
                    target_area=t.get("target_area"),
                    loadout=t.get("loadout"),
                    patrol_location=t.get("patrol_location"),
                    patrol_length_km=t.get("patrol_length_km"),
                    patrol_width_km=t.get("patrol_width_km"),
                    heading_deg=t.get("heading_deg"),
                    on_station_at=t.get("on_station_at"),
                    off_station_at=t.get("off_station_at"),
                    quantity=t.get("quantity", 1),
                    rationale=t.get("rationale", ""),
                    doctrine_refs=t.get("doctrine_refs", []),
                ))
                callsign_counter += 1

        return IntegratedTaskOrder(
            team=team,
            turn=turn,
            mission_name=f"South China Sea Conflict — {team.title()} Turn {turn}",
            commander_intent=commander_intent,
            sorties=sorties,
            supporting_notes=(
                f"Targets nominated: {len(intelligence_targets)} | "
                f"Targeting solutions: {len(targeting_plan)}"
            ),
        )
