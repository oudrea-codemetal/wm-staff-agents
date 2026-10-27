import asyncio

from wm_staff_agents.doctrine.corpus import DEFAULT_CORPUS
from wm_staff_agents.game.engine import GameEngine
from wm_staff_agents.game.scenario import DEFAULT_SCENARIO
from wm_staff_agents.roles.hierarchy import DEFAULT_HIERARCHY


def test_dice_roller_deterministic():
    from wm_staff_agents.warmatrix.dice import DiceRoller
    r1 = DiceRoller(seed=42).adjudicate_turn(1, 6, 6)
    r2 = DiceRoller(seed=42).adjudicate_turn(1, 6, 6)
    assert r1.red_losses == r2.red_losses
    assert r1.blue_losses == r2.blue_losses


def test_slot_in_out():
    from wm_staff_agents.roles.team import Team, default_team_configs
    rc, bc = default_team_configs(DEFAULT_HIERARCHY)
    team = Team(hierarchy=DEFAULT_HIERARCHY, config=rc)
    assert team.slot_for("force_commander").is_agent

    team2 = team.slot_in("force_commander", "alice", "hold the strait")
    assert team2.slot_for("force_commander").is_human
    assert team2.slot_for("force_commander").holder == "alice"

    team3 = team2.slot_out("force_commander", "returning to agent")
    assert team3.slot_for("force_commander").is_agent


def test_game_engine_runs_one_turn_no_llm():
    """Runs one turn with human overrides (no LLM needed)."""
    engine = GameEngine(
        scenario=DEFAULT_SCENARIO,
        hierarchy=DEFAULT_HIERARCHY,
        doctrine_corpus=DEFAULT_CORPUS,
    )
    # Provide human input for all roles so no LLM call happens
    for role in DEFAULT_HIERARCHY.roles:
        engine.red_orch.set_human_input(role.id, '{"summary": "test", "doctrine_refs": []}')
        engine.blue_orch.set_human_input(role.id, '{"summary": "test", "doctrine_refs": []}')

    async def run():
        report = await engine.run_turn(1)
        assert report.turn == 1
        assert report.narrative
        assert engine.state.turn == 1

    asyncio.run(run())


def test_ito_builder():
    from wm_staff_agents.warmatrix.ito import ITOBuilder
    builder = ITOBuilder()
    ito = builder.build(
        team="blue", turn=1, commander_intent="Defend the strait",
        intelligence_targets=[{"name": "Red DDG"}],
        targeting_plan=[{"target": "Red DDG", "weapon": "Harpoon"}],
        support_plan=[],
        air_tasking=[{"platform_code": "F-16C", "base": "Kadena", "mission_type": "DCA", "quantity": 4}],
        maritime_tasking=[],
    )
    assert len(ito.sorties) == 1
    assert ito.sorties[0].platform_code == "F-16C"
    assert "South China Sea Conflict" in ito.mission_name
