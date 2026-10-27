"""Doctrine corpus: conventions extracted from open-source doctrine.

Each convention is a DCF-style record: description, applicability, tags,
rationale, and a link back to the source document. The corpus can be
loaded as plain Python or via Mercury's DCF loader if available.

Why this shape: DCF (Dynamic Context Framework) in Mercury selects
context by matching applicability predicates against the current task.
Doctrine conventions work the same way — a targeting convention should
only appear when the agent is doing targeting work. The corpus is the
bridge between doctrine documents and agent context.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class DoctrineSource(BaseModel):
    """Where a convention comes from."""

    model_config = {"frozen": True}

    document: str = Field(description="Short name, e.g. AFDP 3-60 Targeting")
    publication: str = Field(description="Full citation")
    chapter: str = Field(default="", description="Chapter or section reference")
    url: str = Field(default="", description="Public URL if available")


class DoctrineConvention(BaseModel):
    """One doctrine-grounded convention for agent guidance."""

    model_config = {"frozen": True}

    id: str = Field(description="Stable id, e.g. targeting/weaponeering")
    description: str = Field(description="The rule or principle, shown to the agent")
    source: DoctrineSource
    tags: tuple[str, ...] = ()
    applicability: str = Field(
        default="always",
        description="When to surface this: 'always' or a keyword pattern",
    )
    rationale: str = Field(default="")
    caveats: tuple[str, ...] = ()


# ------------------------------------------------------------------ corpus

# Built-in conventions extracted from the 13 doctrine PDFs in data/doctrine/.
# Each was read from the source document and paraphrased as a single
# actionable convention. The source field lets the Jev checker and any
# human reader trace the claim back to the document.

BUILTIN_CONVENTIONS: tuple[DoctrineConvention, ...] = (
    # -- Targeting (AFDP 3-60) --
    DoctrineConvention(
        id="targeting/weaponeering",
        description=(
            "Weaponeering matches weapon effects to target vulnerability: select the minimum "
            "force needed to achieve the desired effect while managing collateral risk. "
            "Consider weapon availability, delivery platform range, and enemy defences."
        ),
        source=DoctrineSource(
            document="AFDP 3-60 Targeting",
            publication="Air Force Doctrine Publication 3-60, Targeting (2021)",
            chapter="Ch 2 - Targeting Process",
        ),
        tags=("targeting", "weaponeering", "effects"),
        applicability="targeting|weaponeering|weapon|strike",
        rationale="Efficient weaponeering preserves sorties and munitions for the broader campaign.",
    ),
    DoctrineConvention(
        id="targeting/prioritisation",
        description=(
            "Prioritise targets by their contribution to enemy centres of gravity and the "
            "commander's intent. A target's military value alone does not determine priority; "
            "consider its role in the enemy's decision cycle."
        ),
        source=DoctrineSource(
            document="AFDP 3-60 Targeting",
            publication="Air Force Doctrine Publication 3-60, Targeting (2021)",
            chapter="Ch 3 - Target Development",
        ),
        tags=("targeting", "prioritisation", "cog"),
        applicability="targeting|priorit|objective|commander.*intent",
    ),
    DoctrineConvention(
        id="targeting/cde",
        description=(
            "Collateral damage estimation is integral to target approval. Assess civilian "
            "presence, dual-use infrastructure, and proximity to protected sites before "
            "recommending a strike. Higher collateral risk requires higher approval authority."
        ),
        source=DoctrineSource(
            document="AFDP 3-60 Targeting",
            publication="Air Force Doctrine Publication 3-60, Targeting (2021)",
            chapter="Ch 4 - CDE Methodology",
        ),
        tags=("targeting", "collateral", "cde", "law-of-war"),
        applicability="collateral|civilian|strike|approval",
    ),
    # -- Counterair (AFDP 3-01) --
    DoctrineConvention(
        id="counterair/oca_dca_balance",
        description=(
            "Counterair requires balancing offensive counterair (OCA) to destroy enemy air "
            "power at its source and defensive counterair (DCA) to protect friendly forces. "
            "OCA is generally more efficient but DCA cannot be neglected when the enemy "
            "retains offensive capability."
        ),
        source=DoctrineSource(
            document="AFDP 3-01 Counterair",
            publication="Air Force Doctrine Publication 3-01, Counterair Operations (2023)",
            chapter="Ch 2 - Counterair Operations",
        ),
        tags=("counterair", "oca", "dca", "air-superiority"),
        applicability="counterair|dca|oca|air.superiority|cap|sweep",
    ),
    DoctrineConvention(
        id="counterair/layered_defence",
        description=(
            "Air defence should be layered: long-range intercept, medium-range engagement, "
            "and point defence. No single system provides complete coverage; integration "
            "across platforms and domains creates overlapping protection."
        ),
        source=DoctrineSource(
            document="AFDP 3-01 Counterair",
            publication="Air Force Doctrine Publication 3-01, Counterair Operations (2023)",
            chapter="Ch 3 - Air Defence Operations",
        ),
        tags=("counterair", "air-defence", "layered", "iads"),
        applicability="air.defen|iads|sam|intercept|layered",
    ),
    DoctrineConvention(
        id="counterair/ace_dispersal",
        description=(
            "Agile Combat Employment disperses air assets across multiple locations to "
            "complicate enemy targeting and sustain sortie generation under attack. "
            "Dispersal trades mass for survivability; commanders must weigh concentration "
            "against resilience."
        ),
        source=DoctrineSource(
            document="AFDN 1-21 ACE",
            publication="Air Force Doctrine Note 1-21, Agile Combat Employment (2022)",
            chapter="ACE Fundamentals",
        ),
        tags=("ace", "dispersal", "survivability", "basing"),
        applicability="dispers|basing|survivab|ace|agile",
    ),
    # -- Counterland (AFDP 3-03) --
    DoctrineConvention(
        id="counterland/interdiction",
        description=(
            "Air interdiction delays, disrupts, or destroys enemy forces before they can "
            "affect friendly operations. Effective interdiction requires timely intelligence, "
            "air superiority in the interdiction area, and coordination with surface manoeuvre."
        ),
        source=DoctrineSource(
            document="AFDP 3-03 Counterland",
            publication="Air Force Doctrine Publication 3-03, Counterland Operations",
            chapter="Ch 2 - Air Interdiction",
        ),
        tags=("counterland", "interdiction", "air-ground"),
        applicability="interdict|counterland|ground.*force|air.interdiction",
    ),
    # -- Mobility (AFDP 3-36) --
    DoctrineConvention(
        id="mobility/tanker_planning",
        description=(
            "Aerial refuelling extends range and endurance but requires careful planning: "
            "tanker orbit geometry, fuel offload calculations, receiver-tanker compatibility, "
            "and protection of the tanker itself in contested airspace."
        ),
        source=DoctrineSource(
            document="AFDP 3-36 Mobility Operations",
            publication="Air Force Doctrine Publication 3-36, Air Mobility Operations",
            chapter="Ch 3 - Air Refuelling",
        ),
        tags=("mobility", "tanker", "refuelling", "support"),
        applicability="tanker|refuel|aerial.*refuel|support.*plan",
    ),
    DoctrineConvention(
        id="mobility/airlift_prioritisation",
        description=(
            "Airlift is a finite resource: prioritise by operational urgency and the "
            "commander's intent. Consider airfield capacity, threat environment, and "
            "the balance between intra-theatre and inter-theatre lift."
        ),
        source=DoctrineSource(
            document="AFDP 3-36 Mobility Operations",
            publication="Air Force Doctrine Publication 3-36, Air Mobility Operations",
            chapter="Ch 2 - Airlift Operations",
        ),
        tags=("mobility", "airlift", "sustainment"),
        applicability="airlift|sustainment|logistics|supply",
    ),
    # -- Joint Operations (JP 3-0 / AFDP 3-0) --
    DoctrineConvention(
        id="joint/mission_command",
        description=(
            "Mission command empowers subordinate leaders to exercise disciplined initiative "
            "within the commander's intent. Orders should state what to achieve and why, "
            "leaving how to the executor where possible."
        ),
        source=DoctrineSource(
            document="AFDP 3-0 Operations",
            publication="Air Force Doctrine Publication 3-0, Operations (2023)",
            chapter="Ch 2 - Command and Control",
        ),
        tags=("command", "mission-command", "intent"),
        applicability="command|intent|mission.command|subordinate",
    ),
    DoctrineConvention(
        id="joint/mass_concentration",
        description=(
            "Concentration of effects matters more than concentration of forces. Mass "
            "combat power at the decisive point and time, accepting risk elsewhere. "
            "Dispersion is the default; concentration is the exception that must be justified."
        ),
        source=DoctrineSource(
            document="JP 3-0",
            publication="Joint Publication 3-0, Joint Operations",
            chapter="Ch 1 - Principles of Joint Operations",
        ),
        tags=("principles-of-war", "mass", "concentration"),
        applicability="mass|concentrat|decisive.point|force.*allocat",
    ),
    # -- Amphibious (JP 3-02, NTTP 3-02.1/3-02.2) --
    DoctrineConvention(
        id="amphibious/ship_to_shore",
        description=(
            "Ship-to-shore movement is the critical vulnerability window in amphibious "
            "operations: landing forces are concentrated, slow, and exposed. It requires "
            "air superiority, naval gunfire support, and rapid build-up of combat power ashore."
        ),
        source=DoctrineSource(
            document="NTTP 3-02.1 Ship-to-Shore Movement",
            publication="NTTP 3-02.1M / MCWP 3-31.5, Ship-to-Shore Movement (2020)",
            chapter="Ch 2 - Planning Considerations",
        ),
        tags=("amphibious", "ship-to-shore", "vulnerability"),
        applicability="amphibious|ship.to.shore|landing|beach|forcible.entry",
    ),
    DoctrineConvention(
        id="amphibious/supporting_arms",
        description=(
            "Supporting arms (naval gunfire, close air support, artillery) must be "
            "integrated through a single coordination agency to avoid fratricide and "
            "maximise effects. Deconfliction of fires in time, space, and purpose is essential."
        ),
        source=DoctrineSource(
            document="NTTP 3-02.2 Supporting Arms",
            publication="NTTP 3-02.2 / MCWP 3-31.6, Supporting Arms Coordination (2019)",
            chapter="Ch 3 - Coordination Procedures",
        ),
        tags=("amphibious", "supporting-arms", "fires", "deconfliction"),
        applicability="supporting.arms|naval.gunfire|cas|fires.*coord|deconflict",
    ),
    # -- Navy Planning (NWP 5-01) --
    DoctrineConvention(
        id="navy/mission_analysis",
        description=(
            "Mission analysis drives all subsequent planning: understand the higher "
            "commander's intent, identify specified and implied tasks, determine constraints "
            "and restraints, and produce a clear mission statement before developing courses of action."
        ),
        source=DoctrineSource(
            document="NWP 5-01 Navy Planning",
            publication="Navy Warfare Publication 5-01, Navy Planning (Apr 2025 Erratum)",
            chapter="Ch 3 - Mission Analysis",
        ),
        tags=("planning", "mission-analysis", "coa"),
        applicability="mission.analysis|planning|coa|course.of.action|commander.*intent",
    ),
    # -- Warfighting (MCDP 1) --
    DoctrineConvention(
        id="warfighting/friction",
        description=(
            "Friction — the gap between plan and reality — is inherent in war. Plans must "
            "be simple, flexible, and account for uncertainty. Success depends on "
            "adaptability more than prediction."
        ),
        source=DoctrineSource(
            document="MCDP 1 Warfighting",
            publication="Marine Corps Doctrinal Publication 1, Warfighting",
            chapter="Ch 1 - The Nature of War",
        ),
        tags=("warfighting", "friction", "uncertainty"),
        applicability="friction|uncertainty|plan.*realit|adaptab",
    ),
    DoctrineConvention(
        id="warfighting/tempo",
        description=(
            "Tempo — operating at a pace the enemy cannot match — creates opportunities "
            "and compounds enemy friction. Rapid decision cycles (OODA) can overwhelm "
            "an opponent even when forces are otherwise balanced."
        ),
        source=DoctrineSource(
            document="MCDP 1 Warfighting",
            publication="Marine Corps Doctrinal Publication 1, Warfighting",
            chapter="Ch 2 - The Theory of War",
        ),
        tags=("warfighting", "tempo", "ooda", "decision-cycle"),
        applicability="tempo|ooda|decision.cycle|rapid.*decision|initiative",
    ),
)


class DoctrineCorpus(BaseModel):
    """A collection of doctrine conventions."""

    name: str
    description: str
    conventions: tuple[DoctrineConvention, ...]

    def matching(self, text: str) -> list[DoctrineConvention]:
        """Return conventions whose applicability matches the text."""
        results: list[DoctrineConvention] = []
        for c in self.conventions:
            if c.applicability == "always":
                results.append(c)
            elif re.search(c.applicability, text, re.IGNORECASE):
                results.append(c)
        return results

    def for_role(self, doctrine_focus: tuple[str, ...]) -> list[DoctrineConvention]:
        """Return conventions relevant to a role's doctrine focus."""
        if not doctrine_focus:
            return list(self.conventions)
        results: list[DoctrineConvention] = []
        for c in self.conventions:
            doc_lower = c.source.document.lower()
            for focus in doctrine_focus:
                if focus.lower() in doc_lower or any(
                    t.lower() in focus.lower() for t in c.tags
                ):
                    results.append(c)
                    break
        return results

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            {"name": self.name, "description": self.description,
             "conventions": [c.model_dump(mode="json") for c in self.conventions]},
            sort_keys=False, allow_unicode=True,
        )

    def to_dcf_dir(self, directory: Path) -> None:
        """Write corpus as DCF-compatible YAML files for Mercury's ConventionLoader."""
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "corpus.yaml").write_text(
            yaml.safe_dump({"name": self.name, "description": self.description}, sort_keys=False)
        )
        for c in self.conventions:
            sub = c.id.split("/")[0]
            (directory / sub).mkdir(parents=True, exist_ok=True)
            (directory / f"{c.id}.yaml").write_text(yaml.safe_dump(
                {
                    "description": c.description,
                    "identifiers": {"standard_rules": {c.source.document: [c.id]}},
                    "applicability": {"type": "pattern_match", "pattern": c.applicability}
                    if c.applicability != "always" else {"type": "always"},
                    "tags": list(c.tags),
                    "rationale": c.rationale,
                    "caveats": list(c.caveats),
                },
                sort_keys=False, allow_unicode=True,
            ))

    def format_for_prompt(self, conventions: list[DoctrineConvention]) -> str:
        """Format conventions as prompt context."""
        if not conventions:
            return "No specific doctrine conventions matched."
        lines: list[str] = []
        for c in conventions:
            lines.append(f"[{c.id}] {c.description}")
            lines.append(f"  Source: {c.source.document} — {c.source.publication}")
            if c.rationale:
                lines.append(f"  Rationale: {c.rationale}")
        return "\n".join(lines)


DEFAULT_CORPUS = DoctrineCorpus(
    name="south_china_sea_doctrine",
    description=(
        "Doctrine conventions for the South China Sea Conflict wargame, "
        "extracted from open-source US joint and service doctrine."
    ),
    conventions=BUILTIN_CONVENTIONS,
)


def load_doctrine_corpus(path: Path | None = None) -> DoctrineCorpus:
    if path is None:
        return DEFAULT_CORPUS
    data = yaml.safe_load(path.read_text())
    return DoctrineCorpus.model_validate(data)
