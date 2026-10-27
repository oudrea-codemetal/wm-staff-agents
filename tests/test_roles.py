from pathlib import Path

from wm_staff_agents.roles.hierarchy import DEFAULT_HIERARCHY, load_hierarchy


def test_default_hierarchy_has_six_roles():
    assert len(DEFAULT_HIERARCHY.roles) == 6


def test_hierarchy_from_yaml():
    h = load_hierarchy(Path("config/roles.yaml"))
    assert len(h.roles) == 6
    assert h.top().id == "force_commander"


def test_children_of_commander():
    h = load_hierarchy(Path("config/roles.yaml"))
    children = h.children_of("force_commander")
    assert len(children) == 5  # everyone else reports to FC


def test_no_taiwan_in_scenario_title():
    from wm_staff_agents.game.scenario import DEFAULT_SCENARIO
    assert "taiwan" not in DEFAULT_SCENARIO.name.lower()
    assert "invasion" not in DEFAULT_SCENARIO.name.lower()
