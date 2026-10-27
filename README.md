# South China Sea Conflict — Hierarchical Wargame

A demonstration of hierarchical wargaming on the WarMatrix platform. Teams of role-organised agents — and humans who can slot in at any time — play a South China Sea contingency as a turn-based game.

> **Why this exists.** Real military operations are not single-player. A force commander sets objectives, intelligence nominates targets, weaponeers check feasibility, support planners arrange tankers, and wing commanders fly the sorties. This demo shows that structure with AI agents, grounded in doctrine, communicating over Slack, and adjudicated through WarMatrix.

## What it does

- **Configurable staff hierarchy** — any set of roles defined in `config/roles.yaml` by name, mission, inputs (what they receive) and outputs (what they decide). The shipped 6-role example (Force Commander → Intelligence → Targeteer → Support Planner → Air Wing Commander → Maritime Commander) is one possible map; see `config/roles.example-minimal.yaml` for a 3-role alternative and `docs/staff-maps.md` for how to create your own
- **Doctrine-grounded decisions**: every agent choice cites open-source doctrine (AFDP, JP, NTTP, MCDP, NWP) and is checked by a Jev-powered doctrine checker
- **WarMatrix via MCP only**: all game operations go through the WarMatrix MCP server — no direct HTTP calls
- **Dice-roll adjudication**: WarMatrix's `DIE_ROLL` adapter for fast, explainable combat resolution (no AFSIM dependency)
- **Human slot in/out**: anyone can take over any role through the web UI or Slack; the agent resumes with the handover note
- **Slack team channels**: `#wargame-red` and `#wargame-blue` for staff deliberation
- **Turn reports**: every turn produces a doctrine-justified report

## Quick start

```bash
# Prerequisites: Python 3.13+, uv, access to WarMatrix and Jev endpoints
git clone https://github.com/CodeMetalAI/wm-staff-agents.git
cd wm-staff-agents
uv sync --locked

# 1. Configure — see config/ for the three files an administrator edits:
#    config/roles.yaml     — role hierarchy (who does what)
#    config/scenario.yaml  — scenario (forces, objectives, WarMatrix binding)
#    config/doctrine.yaml  — doctrine sources and corpus location

# 2. Generate the StaffEngine bundle for visual editing:
uv run python scripts/build_staff_bundle.py
# Open staff_engine/south-china-sea-conflict.foundry.json in StaffEngine

# 3. Set environment (WarMatrix + LLM + Jev + Slack):
cp .env.example .env  # then edit

# 4. Run the game (all-agent, 6 turns):
uv run python -m wm_staff_agents.cli run --turns 6

# 5. Or run the web UI for human slot in/out:
uv run python -m wm_staff_agents.cli serve --port 8080
# Open http://localhost:8080 — click Slot In on any role to take over

# 6. Record a demo:
uv run python -m wm_staff_agents.cli demo --record
```

## Architecture

```
config/roles.yaml  ──►  StaffEngine bundle  ─┐
config/scenario.yaml ──►  Scenario            │
config/doctrine.yaml ──►  DoctrineCorpus      ├──► GameEngine ──► WarMatrix (MCP)
                                              │         │
Roles × Teams  ──►  RoleAgents (cm.ai)  ──────┘    ┌────┴────┐
                                                    ▼         ▼
                                              SlackBridge  Jev Checker
                                                    │         │
                                              Web UI ◄────┘
```

**Package layout:**

| Path | What it is |
|------|-----------|
| `src/wm_staff_agents/roles/` | Role hierarchy and team/slot management |
| `src/wm_staff_agents/doctrine/` | Doctrine corpus (16 conventions from 12 open-source pubs) |
| `src/wm_staff_agents/warmatrix/` | WarMatrix MCP client, ITO builder, dice roller |
| `src/wm_staff_agents/agents/` | Per-role LLM agents and turn orchestrator |
| `src/wm_staff_agents/jev/` | Jev-backed doctrine checker |
| `src/wm_staff_agents/slack/` | Slack bridge (Socket Mode, with log-only fallback) |
| `src/wm_staff_agents/game/` | Scenario and game engine (turn loop, reports) |
| `src/wm_staff_agents/ui/` | FastAPI web UI for slot in/out and game control |
| `config/` | Administrator-editable YAML (roles, scenario, doctrine) — any staff map works, not just the shipped 6-role one |
| `config/roles.example-minimal.yaml` | 3-role minimal staff map example |
| `data/doctrine/` | Open-source doctrine PDFs and DCF corpus YAML |
| `data/scenarios/` | WarMatrix scenario data (ITO fixtures, laydown) |
| `staff_engine/` | Generated StaffEngine bundle for visual editing |

## Replicating on AWS

All WarMatrix execution must run on AWS (not locally). To replicate:

```bash
# Provision a machine (r6a.4xlarge, Ubuntu 24.04, SSM-only):
# See docs/aws-setup.md for the full provisioning steps
./scripts/provision-aws.sh

# On the AWS box:
git clone https://github.com/CodeMetalAI/wm-staff-agents.git
cd wm-staff-agents
uv sync --locked
cp .env.example .env  # set WM_API_URL, WM_BEARER_TOKEN, OPENAI_API_KEY, etc.
uv run python -m wm_staff_agents.cli run --turns 6
uv run python -m wm_staff_agents.cli serve --port 8080 --host 0.0.0.0
```

## Doctrine sources

All doctrine is open-source and stored in `data/doctrine/sources/`:

| Document | Use |
|----------|-----|
| AFDP 3-01 Counterair | Air superiority, DCA/OCA, ACE dispersal |
| AFDP 3-03 Counterland | Air interdiction |
| AFDP 3-36 Mobility Ops | Tanker and airlift planning |
| AFDP 3-60 Targeting | Weaponeering, target prioritisation, CDE |
| AFDN 1-21 ACE | Agile Combat Employment |
| AFDP 3-0 Operations | Mission command, joint C2 |
| JP 3-02 Amphibious Ops | Ship-to-shore movement |
| JP 3-18 Joint Forcible Entry | Forcible entry planning |
| NTTP 3-02.1 / 3-02.2 | Ship-to-shore, supporting arms |
| NWP 5-01 Navy Planning | Mission analysis, COA development |
| MCDP 1 Warfighting | Friction, tempo, manoeuvre warfare |

## Why each major piece is needed

| Piece | Why |
|-------|-----|
| StaffEngine | Roles need a visual, approvable definition that both operators and engineers can read. StaffEngine is that surface — one document, two projections (canvas + review). The bundle it generates is the contract. |
| Mercury cm.ai | Individual agents need structured LLM orchestration: prompt templates with doctrine injection, tool use, and conversation memory. cm.ai provides that as a typed, testable runtime rather than raw HTTP calls. |
| DCF corpus | Doctrine is not a single document — it is 12 publications with overlapping principles. DCF's convention model (applicability predicates + digest) selects the right doctrine for each role and task, so the Force Commander sees joint planning doctrine while the Targeteer sees weaponeering rules. |
| Jev checker | Regex anti-pattern scans work for code, not for reasoning. Jev evaluates whether an agent's justification actually follows from the doctrine it cites — a language judgment, not a string match. Without it, agents could cite doctrine without applying it. |
| WarMatrix MCP | WarMatrix owns the authoritative game state (laydown, ITO, adjudication). Going through MCP keeps the demo honest — it cannot invent forces or ignore feasibility checks. MCP also scopes access per game/team. |
| Slack | Staff deliberation is inherently multi-party and asynchronous. Slack gives each team a persistent, auditable channel where agents and humans converse in the same place. |
| Dice roll | Full physics simulation (AFSIM) requires classified terrain and platform data. Dice rolls give plausible, fast, explainable outcomes that are sufficient for demonstrating hierarchical decision-making without a simulator dependency. |
