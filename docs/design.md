# Design: South China Sea Conflict Wargame

## Problem

We want to demonstrate hierarchical wargaming where teams of role-organised agents play WarMatrix. Each team has a command hierarchy, decisions are grounded in doctrine, and humans can slot in at any time.

## Why hierarchical

A single red-vs-blue agent hides the structure of real operations. A force commander, intelligence cell, targeteers, support planners, and wing commanders each have different responsibilities, information needs, and doctrine. The hierarchy makes the game explainable: you can trace any sortie back through targeting, intelligence, and commander's intent.

## Why StaffEngine for roles

Roles need a definition that both operators (who know the work) and engineers (who build the agents) can read and approve. StaffEngine provides one document with two projections — a canvas for the engineer and a review view for the operator. The approved bundle is the contract that the Python runtime honours.

An administrator edits `config/roles.yaml` (6 roles, rank, responsibilities, doctrine focus, reports-to) and regenerates the StaffEngine bundle. No code change needed to add or reconfigure a role.

## Why Mercury cm.ai for agents

Each role needs an LLM agent with structured prompts, doctrine context injection, and conversation memory. Mercury's `cm.ai` provides typed agent definitions, Jinja2 prompt templates with role boundaries, and a session model that supports branching and human override. When Mercury is not installed, agents degrade to direct OpenAI-compatible HTTP — same JSON output, same Jev check.

## Why DCF for doctrine

Doctrine is 12 publications with overlapping principles. A flat prompt dump would overwhelm the context window and surface irrelevant guidance. DCF's convention model uses applicability predicates (regex on task text) to select only the conventions relevant to the current role and task. The Force Commander sees joint planning doctrine; the Targeteer sees weaponeering rules.

## Why Jev instead of regex

The original DCF anti-pattern scanner uses regex matching — good for code patterns, useless for reasoning. "Does this targeting decision follow from AFDP 3-60's weaponeering principle?" is a language judgment. Jev is a language-model judge that evaluates whether a justification actually follows from the cited doctrine. If Jev is down, a keyword-overlap fallback keeps the game playable (marked as unverified).

## Why WarMatrix via MCP only

WarMatrix owns the authoritative game state: laydown, ITO feasibility, and adjudication. Going through MCP (not direct HTTP) keeps the demo honest — it cannot invent forces or skip feasibility checks. MCP also scopes access per game/team and provides provenance on every read.

## Why dice rolls

Full physics simulation (AFSIM) needs classified terrain and platform data. Dice rolls via WarMatrix's `DIE_ROLL` adapter give plausible, fast, explainable outcomes. The probability model is `p_destroyed = pk`, `p_divert = (1-pk)/2`, `p_rtb = (1-pk)/2` per sortie engagement. This is sufficient for demonstrating hierarchical decision-making; the game is about the staff process, not the physics.

## Why Slack

Staff deliberation is multi-party and asynchronous. Each team has a channel (`#wargame-red`, `#wargame-blue`) where agents post decisions and humans interject. Slack's Socket Mode gives real-time bidirectional messaging. Without a Slack token, the bridge logs to stdout — the game remains playable.

## Turn flow

```
Force Commander sets intent (sees full game state)
  → Intelligence nominates targets (sees intent + game state)
    → Targeteer checks feasibility (sees targets + intent)
      → Support Planner arranges enablers (sees targeting plan)
        → Air Wing + Maritime Commanders generate sorties (parallel, see full staff picture)
          → ITO Builder assembles integrated task order
            → Dice roller adjudicates engagements
              → Jev checker validates doctrine grounding
                → Turn report generated
```

Both teams plan concurrently. Context flows down (intent → targets → tasking) and up (results → next intent).

## Human slot in/out

Any role can be held by a human or an agent. The web UI (`/`) shows all slots with their current holder. Clicking "Slot In" assigns a human; "Slot Out" returns the role to its agent with an optional handover note that becomes the agent's context. Slack slash commands (`/slot-in`, `/slot-out`) do the same.

When a human is slotted in, that role's agent is skipped and the human's input (JSON or freeform) is used directly. The Jev doctrine check still applies — humans must also justify with doctrine.

## What is not in scope

- Authentication: all MCP commands come from a single user regardless of team. No per-player auth.
- Real-time WarMatrix map: the demo produces ITO JSON and turn reports. Rendering on the WarMatrix map requires a live WarMatrix with map frontend.
- Persistent game hosting: the game engine is in-process. Durable hosting would need a database and WarMatrix move advancement (which requires write permissions and specific game state).
