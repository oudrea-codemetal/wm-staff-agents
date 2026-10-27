#!/usr/bin/env python3
"""Generate a StaffEngine .foundry.json bundle from config/roles.yaml.

The bundle can be opened in StaffEngine (https://github.com/CodeMetalAI/StaffEngine)
for visual editing and approval. The Python runtime reads config/roles.yaml directly;
the bundle is for the StaffEngine UI only.

No role is hardcoded — the bundle is generated from whatever roles are in the YAML.

Usage:
    python scripts/build_staff_bundle.py
    python scripts/build_staff_bundle.py --roles config/roles.yaml --out staff_engine/south-china-sea-conflict.foundry.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

DEFAULT_ROLES = Path(__file__).parent.parent / "config" / "roles.yaml"
DEFAULT_OUT = Path(__file__).parent.parent / "staff_engine" / "south-china-sea-conflict.foundry.json"


def build(roles_path: Path, out_path: Path) -> None:
    data = yaml.safe_load(roles_path.read_text())
    roles = data["roles"]

    # One TypeDoc per deliverable type
    all_outputs: list[str] = []
    for r in roles:
        for o in r.get("outputs", []):
            if o not in all_outputs:
                all_outputs.append(o)

    types = []
    for r in roles:
        types.append({
            "id": f"ty_{r['id']}",
            "name": r["name"],
            "version": 1,
            "fields": [
                {"id": "f0", "key": "summary", "kind": "string", "required": True},
                {"id": "f1", "key": "rationale", "kind": "string", "required": True},
                {"id": "f2", "key": "doctrine_refs", "kind": "array", "required": False},
            ],
        })
    # Also types for each deliverable
    for out in all_outputs:
        tid = f"ty_out_{out}"
        if not any(t["id"] == tid for t in types):
            types.append({
                "id": tid, "name": out, "version": 1,
                "fields": [{"id": "f0", "key": "value", "kind": "string", "required": True}],
            })

    # Positions — one per role
    positions = [
        {"id": f"ps_{r['id']}", "name": r["name"], "version": 1, "note": r["description"][:200]}
        for r in roles
    ]

    # Nodes: one agent per role, laid out by rank
    rank_y = {1: 120, 2: 340, 3: 560, 4: 780}
    # Collect roles by rank for x positioning
    by_rank: dict[int, list[dict]] = {}
    for r in roles:
        by_rank.setdefault(r["rank"], []).append(r)

    nodes: list[dict] = []
    edges: list[dict] = []
    layout: dict[str, list[int]] = {}

    # Source node
    nodes.append({
        "id": "n_source", "label": "GAME STATE", "type": "source",
        "config": {"origin": "WarMatrix game state and previous turn outcome"},
        "outputType": f"ty_{roles[0]['id']}" if roles else "ty_generic",
        "components": [],
    })
    layout["n_source"] = [600, 20]

    for r in roles:
        rank = r["rank"]
        siblings = by_rank[rank]
        idx = siblings.index(r)
        total = len(siblings)
        # Spread evenly across 1200px width
        x = 150 + (900 // max(total, 1)) * idx + (900 // max(total, 1)) // 2 if total > 1 else 600
        y = rank_y.get(rank, 340)

        inputs_desc = f"Needs: {', '.join(r.get('inputs', []))}" if r.get("inputs") else "No dependencies"
        outputs_desc = f"Produces: {', '.join(r.get('outputs', []))}" if r.get("outputs") else ""
        task = r.get("task_prompt", "")[:150] + "..." if r.get("task_prompt", "") else r["description"][:150]

        nodes.append({
            "id": f"n_{r['id']}", "label": r["name"].upper(), "type": "agent",
            "config": {
                "system": f"You are the {r['name']} — {r['description']}",
                "task": task,
                "model": "gpt-4o-mini",
            },
            "inputType": f"ty_{r['id']}", "outputType": f"ty_{r['id']}",
            "components": [],
        })
        layout[f"n_{r['id']}"] = [x, y]

    # Edges from input/output wiring
    output_to_role: dict[str, str] = {}
    for r in roles:
        for o in r.get("outputs", []):
            output_to_role[o] = r["id"]

    for r in roles:
        for inp in r.get("inputs", []):
            producer = output_to_role.get(inp)
            if producer:
                edges.append({
                    "id": f"e_{producer}_to_{r['id']}__{inp}",
                    "from": f"n_{producer}", "to": f"n_{r['id']}",
                    "mods": {"retries": 1, "timeout": 120},
                })

    # Also hierarchy edges (reports_to) as dashed/secondary — use relies-on style
    # For now just use the data-flow edges above plus source→top
    top_roles = [r for r in roles if not r.get("reports_to") and not r.get("inputs")]
    for tr in top_roles:
        edges.append({
            "id": f"e_source_to_{tr['id']}", "from": "n_source", "to": f"n_{tr['id']}",
            "mods": {"retries": 1, "timeout": 30},
        })

    stripped = [{k: v for k, v in n.items() if k not in ("x", "y")} for n in nodes]

    bundle = {
        "kind": "staff-engine.graph",
        "version": 1,
        "savedAt": "2026-10-27T00:00:00.000Z",
        "doc": {"nodes": stripped, "edges": edges},
        "types": types,
        "configs": [],
        "positions": positions,
        "measures": [
            {"id": "ms_time", "name": "Time", "unit": "min", "accrue": "path", "note": "Wall-clock per turn"},
            {"id": "ms_tokens", "name": "Tokens", "unit": "ktok", "accrue": "total", "note": "LLM tokens per turn"},
        ],
        "graphs": [],
        "self": {
            "name": data.get("name", "Staff Map"),
            "budgets": {"ms_time": 30},
            "evals": [],
        },
        "layout": layout,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {out_path}")
    print(f"  {len(nodes)} nodes, {len(edges)} edges, {len(positions)} positions")
    print(f"  Execution levels determined by input/output wiring, not hardcoded")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", type=Path, default=DEFAULT_ROLES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    build(args.roles, args.out)
