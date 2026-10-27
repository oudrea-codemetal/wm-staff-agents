"""Role hierarchy: StaffEngine-compatible role definitions."""

from wm_staff_agents.roles.hierarchy import Role, RoleHierarchy, load_hierarchy
from wm_staff_agents.roles.team import Team, TeamConfig

__all__ = ["Role", "RoleHierarchy", "Team", "TeamConfig", "load_hierarchy"]
