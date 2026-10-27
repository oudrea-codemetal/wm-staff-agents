"""CLI for wm-staff-agents: run games, serve the UI, manage setup."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def cmd_run(args: argparse.Namespace) -> None:
    """Run the wargame for N turns (all-agent or with human overrides)."""
    asyncio.run(_run_game(args))


async def _run_game(args: argparse.Namespace) -> None:
    from wm_staff_agents.doctrine.corpus import load_doctrine_corpus
    from wm_staff_agents.game.engine import GameEngine
    from wm_staff_agents.game.scenario import load_scenario
    from wm_staff_agents.roles.hierarchy import load_hierarchy

    hierarchy = load_hierarchy(Path(args.roles) if args.roles else None)
    scenario = load_scenario(Path(args.scenario) if args.scenario else None)
    corpus = load_doctrine_corpus()

    # LLM config from env
    llm_config = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "base_url": os.environ.get("OPENAI_BASE_URL", ""),
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
    }

    # Optional: WarMatrix MCP client
    wm_client = None
    if args.warmatrix and os.environ.get("WM_API_URL"):
        from wm_staff_agents.warmatrix.client import WarMatrixMCPClient, WarMatrixConfig
        wm_client = WarMatrixMCPClient(WarMatrixConfig.from_env())
        await wm_client.connect()
        logger.info("WarMatrix MCP connected: %s", wm_client.tool_names())

    jev_url = os.environ.get("JEV_URL", "http://100.111.138.48:8012")

    engine = GameEngine(
        scenario=scenario,
        hierarchy=hierarchy,
        doctrine_corpus=corpus,
        llm_config=llm_config,
        warmatrix_client=wm_client,
        jev_url=jev_url,
        dice_seed=args.seed,
    )

    turns = args.turns or scenario.max_turns
    print(f"Running {scenario.name} for {turns} turns...")

    for turn in range(1, turns + 1):
        print(f"\n{'='*60}")
        print(f"  TURN {turn}")
        print(f"{'='*60}")
        report = await engine.run_turn(turn)
        print(f"\n{report.narrative}")
        print(f"\n--- Red ITO ---")
        red_ito = report.red_outputs.get("_ito", {})
        for s in red_ito.get("sorties", []):
            print(f"  {s.get('callsign')}: {s.get('quantity')}x {s.get('platform_code')} {s.get('mission_type')} from {s.get('base')}")
        print(f"--- Blue ITO ---")
        blue_ito = report.blue_outputs.get("_ito", {})
        for s in blue_ito.get("sorties", []):
            print(f"  {s.get('callsign')}: {s.get('quantity')}x {s.get('platform_code')} {s.get('mission_type')} from {s.get('base')}")
        print(f"\n--- Doctrine checks ---")
        for side, jev in [("Red", report.red_jev), ("Blue", report.blue_jev)]:
            for role, verdicts in jev.items():
                for v in verdicts:
                    status = "PASS" if v.get("passed") else "FAIL"
                    print(f"  {side}/{role}: {status} ({v.get('source')}) — {v.get('reasoning', '')[:150]}")

    out = Path(args.output) if args.output else Path("data/reports/game_report.json")
    engine.save_reports(out)
    print(f"\nReports saved to {out}")

    if wm_client:
        await wm_client.disconnect()


def cmd_serve(args: argparse.Namespace) -> None:
    """Serve the web UI for human slot in/out and game control."""
    import uvicorn

    from wm_staff_agents.doctrine.corpus import load_doctrine_corpus
    from wm_staff_agents.game.engine import GameEngine
    from wm_staff_agents.game.scenario import load_scenario
    from wm_staff_agents.roles.hierarchy import load_hierarchy
    from wm_staff_agents.ui.app import create_app

    hierarchy = load_hierarchy(Path(args.roles) if args.roles else None)
    scenario = load_scenario(Path(args.scenario) if args.scenario else None)
    corpus = load_doctrine_corpus()

    llm_config = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "base_url": os.environ.get("OPENAI_BASE_URL", ""),
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
    }

    jev_url = os.environ.get("JEV_URL", "http://100.111.138.48:8012")

    engine = GameEngine(
        scenario=scenario,
        hierarchy=hierarchy,
        doctrine_corpus=corpus,
        llm_config=llm_config,
        jev_url=jev_url,
    )

    app = create_app(engine)
    print(f"Serving on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


def cmd_demo(args: argparse.Namespace) -> None:
    """Run a demo with human intervention example."""
    print("Demo: South China Sea Conflict — 6 turns with human slot-in on turn 3")
    print("(Use --record to save outputs for README)")
    asyncio.run(_run_demo(args))


async def _run_demo(args: argparse.Namespace) -> None:
    from wm_staff_agents.doctrine.corpus import load_doctrine_corpus
    from wm_staff_agents.game.engine import GameEngine
    from wm_staff_agents.game.scenario import load_scenario
    from wm_staff_agents.roles.hierarchy import load_hierarchy

    hierarchy = load_hierarchy(Path(args.roles) if args.roles else None)
    scenario = load_scenario(Path(args.scenario) if args.scenario else None)
    corpus = load_doctrine_corpus()
    llm_config = {"model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini")}

    engine = GameEngine(
        scenario=scenario, hierarchy=hierarchy, doctrine_corpus=corpus,
        llm_config=llm_config, jev_url=os.environ.get("JEV_URL", "http://100.111.138.48:8012"),
    )

    for turn in range(1, 7):
        if turn == 3:
            print(f"\n--- Human slots into Blue Force Commander on turn {turn} ---")
            engine.slot_in("blue", "force_commander", "demo-human",
                           "Prioritise defence of the strait chokepoint; hold air superiority as main effort.")
            # Also provide explicit human action for that role
            engine.human_act("blue", "force_commander", json.dumps({
                "intent": "Hold the strait and attrit Red amphibious forces. Air superiority is the main effort; maritime interdiction is supporting.",
                "objectives": ["Deny strait transit to Red surface forces", "Maintain CAP over partner territory"],
                "priority": "Air superiority over the strait",
                "constraints": "Minimise collateral risk to civilian shipping",
                "doctrine_refs": ["counterair/oca_dca_balance", "counterair/layered_defence"],
            }))

        report = await engine.run_turn(turn)
        print(f"\nTurn {turn}: {report.narrative[:300]}")

        if turn == 3:
            print("--- Human slots out ---")
            engine.slot_out("blue", "force_commander", "Returning to agent; maintain strait denial posture.")

    out = Path("data/reports/demo_report.json")
    engine.save_reports(out)
    print(f"\nDemo complete. Reports: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="South China Sea Conflict — Staff Wargame")
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Run the wargame")
    p_run.add_argument("--turns", type=int, default=None, help="Number of turns")
    p_run.add_argument("--roles", type=str, default=None)
    p_run.add_argument("--scenario", type=str, default=None)
    p_run.add_argument("--warmatrix", action="store_true", help="Connect to WarMatrix via MCP")
    p_run.add_argument("--seed", type=int, default=42)
    p_run.add_argument("--output", type=str, default=None)
    p_run.set_defaults(func=cmd_run)

    # serve
    p_serve = sub.add_parser("serve", help="Serve the web UI")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.add_argument("--roles", type=str, default=None)
    p_serve.add_argument("--scenario", type=str, default=None)
    p_serve.set_defaults(func=cmd_serve)

    # demo
    p_demo = sub.add_parser("demo", help="Run a demo with human intervention")
    p_demo.add_argument("--roles", type=str, default=None)
    p_demo.add_argument("--scenario", type=str, default=None)
    p_demo.add_argument("--record", action="store_true")
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
