"""Team: one side in the game (Red or Blue)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from wm_staff_agents.roles.hierarchy import RoleHierarchy


class TeamSlot(BaseModel):
    """One seat in a team: a role that may be held by a human or an agent."""

    model_config = {"frozen": True}

    role_id: str
    holder: str = Field(
        default="agent",
        description="'agent' or a human identifier (e.g. slack user id)",
    )
    context_note: str = Field(
        default="",
        description="Free-text handover note left when a human slots out",
    )

    @property
    def is_human(self) -> bool:
        return self.holder != "agent"

    @property
    def is_agent(self) -> bool:
        return self.holder == "agent"


class TeamConfig(BaseModel):
    """Configuration for one team."""

    name: str
    side: str = Field(description="'red' or 'blue'")
    colour: str = Field(description="Display colour")
    slack_channel: str | None = Field(default=None, description="Slack channel id or name")
    slots: list[TeamSlot]


class Team(BaseModel):
    """A live team with its hierarchy and slot assignments."""

    hierarchy: RoleHierarchy
    config: TeamConfig

    def slot_for(self, role_id: str) -> TeamSlot:
        for s in self.config.slots:
            if s.role_id == role_id:
                return s
        raise KeyError(f"No slot for role {role_id}")

    def slot_in(self, role_id: str, human_id: str, context_note: str = "") -> Team:
        """Return a new Team with a human occupying the role."""
        new_slots = [
            TeamSlot(role_id=s.role_id, holder=human_id if s.role_id == role_id else s.holder,
                      context_note=context_note if s.role_id == role_id else s.context_note)
            for s in self.config.slots
        ]
        return Team(hierarchy=self.hierarchy, config=TeamConfig(
            name=self.config.name, side=self.config.side,
            colour=self.config.colour, slack_channel=self.config.slack_channel,
            slots=new_slots,
        ))

    def slot_out(self, role_id: str, handover_note: str = "") -> Team:
        """Return a new Team with the human leaving and agent taking over."""
        new_slots = [
            TeamSlot(role_id=s.role_id, holder="agent",
                      context_note=handover_note if s.role_id == role_id else s.context_note)
            for s in self.config.slots
        ]
        return Team(hierarchy=self.hierarchy, config=TeamConfig(
            name=self.config.name, side=self.config.side,
            colour=self.config.colour, slack_channel=self.config.slack_channel,
            slots=new_slots,
        ))


def default_team_configs(hierarchy: RoleHierarchy) -> tuple[TeamConfig, TeamConfig]:
    """Create the default Red and Blue team configs (all-agent)."""
    red = TeamConfig(
        name="Red Team",
        side="red",
        colour="#c0392b",
        slack_channel="#wargame-red",
        slots=[TeamSlot(role_id=r.id) for r in hierarchy.roles],
    )
    blue = TeamConfig(
        name="Blue Team",
        side="blue",
        colour="#2980b9",
        slack_channel="#wargame-blue",
        slots=[TeamSlot(role_id=r.id) for r in hierarchy.roles],
    )
    return red, blue
