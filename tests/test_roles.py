from pathlib import Path

from wm_staff_agents.roles.hierarchy import load_hierarchy


def test_yaml_has_six_roles():
    h = load_hierarchy(Path("config/roles.yaml"))
    assert len(h.roles) == 6


def test_hierarchy_top():
    h = load_hierarchy(Path("config/roles.yaml"))
    assert h.top().id == "force_commander"


def test_children_of_commander():
    h = load_hierarchy(Path("config/roles.yaml"))
    children = h.children_of("force_commander")
    assert len(children) == 5


def test_execution_levels():
    h = load_hierarchy(Path("config/roles.yaml"))
    levels = h.execution_levels()
    # Level 0: force_commander (no inputs)
    assert levels[0][0].id == "force_commander"
    # Should have multiple levels based on input wiring
    assert len(levels) >= 3
    # All roles covered
    assert sum(len(l) for l in levels) == 6


def test_no_hardcoded_wiring():
    h = load_hierarchy(Path("config/roles.yaml"))
    # Every role with inputs should have those inputs wired to another role's outputs
    warnings = h.validate_wiring()
    assert warnings == [], f"Wiring warnings: {warnings}"


def test_custom_hierarchy():
    """An administrator can define any roles — not just the 6 shipped ones."""
    from wm_staff_agents.roles.hierarchy import Role, RoleHierarchy
    custom = RoleHierarchy(
        name="Custom",
        description="Test",
        roles=(
            Role(id="alpha", name="Alpha", rank=1, description="First", outputs=("intel",)),
            Role(id="bravo", name="Bravo", rank=2, description="Second", inputs=("intel",), outputs=("action",)),
            Role(id="charlie", name="Charlie", rank=2, description="Third", inputs=("intel",), outputs=("support",)),
        ),
    )
    levels = custom.execution_levels()
    assert len(levels) == 2
    assert levels[0][0].id == "alpha"
    assert {r.id for r in levels[1]} == {"bravo", "charlie"}


def test_no_taiwan_in_scenario_title():
    from wm_staff_agents.game.scenario import DEFAULT_SCENARIO
    assert "taiwan" not in DEFAULT_SCENARIO.name.lower()
    assert "invasion" not in DEFAULT_SCENARIO.name.lower()
