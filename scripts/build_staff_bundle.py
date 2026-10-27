#!/usr/bin/env python3
"""Generate a StaffEngine .foundry.json bundle from config/roles.yaml.

The bundle can be opened in StaffEngine (https://github.com/CodeMetalAI/StaffEngine)
for visual editing and approval. The Python runtime reads config/roles.yaml directly;
the bundle is for the StaffEngine UI only.

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

    # One TypeDoc per role output — the contract that the next step relies on
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

    # Positions — one per role (StaffEngine: who is accountable)
    positions = [
        {"id": f"ps_{r['id']}", "name": r["name"], "version": 1, "note": r["description"][:200]}
        for r in roles
    ]

    # Nodes: one agent per role, arranged in hierarchy
    # Layout: Force Commander at top, staff in middle, executors at bottom
    nodes = []
    edges = []

    # Position helpers
    rank_y = {1: 120, 2: 340, 3: 560}
    rank_x_offsets = {1: [600], 2: [200, 600, 1000], 3: [350, 850]}

    # Assign x positions within each rank
    rank_counters: dict[int, int] = {}
    for r in roles:
        rank = r["rank"]
        idx = rank_counters.get(rank, 0)
        xs = rank_x_offsets.get(rank, [600])
        x = xs[min(idx, len(xs) - 1)] if xs else 600
        y = rank_y.get(rank, 340)
        rank_counters[rank] = idx + 1

        nodes.append({
            "id": f"n_{r['id']}",
            "label": r["name"].upper(),
            "type": "agent",
            "config": {
                "system": f"You are the {r['name']} in the South China Sea Conflict wargame. {r['description']}",
                "task": "{{input}}",
                "model": "gpt-4o-mini",
            },
            "inputType": f"ty_{r['id']}",
            "outputType": f"ty_{r['id']}",
            "components": [],
        })

    # Edges: reports_to relationships
    for r in roles:
        if r.get("reports_to"):
            parent_id = r["reports_to"]
            edges.append({
                "id": f"e_{r['id']}_to_{parent_id}",
                "from": f"n_{parent_id}",
                "to": f"n_{r['id']}",
                "mods": {"retries": 1, "timeout": 120},
            })

    # Also add a source node for game state input
    nodes.insert(0, {
        "id": "n_source",
        "label": "GAME STATE",
        "type": "source",
        "config": {"origin": "WarMatrix game state and previous turn outcome"},
        "outputType": "ty_force_commander",
        "components": [],
    })
    edges.insert(0, {
        "id": "e_source_to_fc",
        "from": "n_source",
        "to": "n_force_commander",
        "mods": {"retries": 1, "timeout": 30},
    })

    # Layout
    layout: dict[str, list[int]] = {}
    for n in nodes:
        # Find matching role for position
        role_match = next((r for r in roles if f"n_{r['id']}" == n["id"]), None)
        if role_match:
            rank = role_match["rank"]
            idx = [r for r in roles if r["rank"] == rank].index(role_match)
            xs = rank_x_offsets.get(rank, [600])
            x = xs[min(idx, len(xs) - 1)]
            y = rank_y.get(rank, 340)
            layout[n["id"]] = [x, y]
        elif n["id"] == "n_source":
            layout[n["id"]] = [600, 20]

    # Strip x/y from nodes for bundle format
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
            "name": data.get("name", "South China Sea Conflict"),
            "budgets": {"ms_time": 30},
            "evals": [],
        },
        "layout": layout,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {out_path}")
    print(f"  {len(nodes)} nodes, {len(edges)} edges, {len(positions)} positions")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", type=Path, default=DEFAULT_ROLES)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    build(args.roles, args.out)
