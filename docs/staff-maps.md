# Creating Your Own Staff Map

The staff hierarchy is not hardcoded. Any set of roles works — the game engine reads whatever is in `config/roles.yaml` and runs it.

## How it works

Each role declares:

| Field | What it means | Example |
|-------|--------------|---------|
| `id` | Stable identifier | `force_commander` |
| `name` | Display name | `Force Commander` |
| `rank` | Hierarchy level (1=top) | `1` |
| `description` | What this role does | `Sets campaign objectives...` |
| `responsibilities` | What it is accountable for | `Define intent, allocate forces` |
| `inputs` | Deliverable names it needs from upstream roles | `["commander_intent"]` |
| `outputs` | Deliverable names it produces for downstream roles | `["targets", "threat_assessment"]` |
| `doctrine_focus` | Which doctrine guides it | `["AFDP 3-01 Counterair"]` |
| `task_prompt` | What it is asked each turn (optional — auto-generated if empty) | `Nominate targets given the intent...` |
| `expected_keys` | JSON keys it should return | `["targets", "doctrine_refs"]` |
| `reports_to` | Parent for hierarchy display | `force_commander` |

**Execution order is derived from the wiring**, not from `rank` or `reports_to`:

```
Level 0: roles with no inputs (e.g. Force Commander) — run first
Level 1: roles whose inputs are all produced by level 0 — run when ready
Level N: roles whose inputs are all produced by earlier levels
```

Roles within a level run in parallel. The engine validates that every input has a producer and warns about gaps.

## Example: 6-role default

```yaml
roles:
  - id: force_commander
    inputs: []
    outputs: [commander_intent, objectives]
  - id: intelligence_officer
    inputs: [commander_intent]
    outputs: [targets, threat_assessment]
  - id: targeteer
    inputs: [targets]
    outputs: [targeting_plan, deferred_targets]
  - id: support_planner
    inputs: [targeting_plan]
    outputs: [support_plan]
  - id: air_wing_commander
    inputs: [targeting_plan, support_plan, threat_assessment]
    outputs: [air_sorties]
  - id: maritime_commander
    inputs: [targeting_plan]
    outputs: [maritime_taskings]
```

Execution levels:

```
Level 0: force_commander
Level 1: intelligence_officer
Level 2: targeteer
Level 3: support_planner + maritime_commander (parallel)
Level 4: air_wing_commander (waits for support + threat)
```

## Example: minimal 3-role map

See `config/roles.example-minimal.yaml` — a Commander → Planner → Executor chain. Copy it over the default to try:

```bash
cp config/roles.example-minimal.yaml config/roles.yaml
python scripts/build_staff_bundle.py
pytest tests/ -k custom_hierarchy  # verifies it runs
python -m wm_staff_agents.cli run --turns 3  # play with it
```

## Creating your own

1. Write `config/roles.yaml` with your roles. Any number (2–12 recommended), any names, any wiring.
2. Regenerate the StaffEngine bundle: `python scripts/build_staff_bundle.py`
3. Open `staff_engine/south-china-sea-conflict.foundry.json` in StaffEngine to visualise and get approval.
4. Run: `python -m wm_staff_agents.cli run --turns 6`

The ITO builder collects any deliverables that look like sorties (`sorties`, `air_sorties`, `taskings`, `maritime_taskings`, `support_sorties`) regardless of which role produced them.

## Validation

```bash
# Check wiring is consistent
python -c "
from pathlib import Path
from wm_staff_agents.roles.hierarchy import load_hierarchy
h = load_hierarchy(Path('config/roles.yaml'))
for w in h.validate_wiring(): print(f'WARN: {w}')
for i, level in enumerate(h.execution_levels()): print(f'Level {i}: {[r.id for r in level]}')
"
```
