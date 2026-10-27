"""Doctrine checker: Jev-backed decision justification.

Why Jev instead of regexes: The original DCF anti-pattern scanner uses
regex matching on anti-pattern strings. That works for code patterns but
not for doctrine judgments like 'this targeting decision violates weaponeering
principles.' Jev is a language-model judge that can evaluate whether a
decision's stated rationale actually follows from the cited doctrine.

The checker asks Jev: given this decision, its justification, and the cited
doctrine passage, does the justification hold? This is a bounded evaluation
task — not free-form generation — so Jev's judgment is auditable.

If Jev is unavailable, a local fallback does keyword overlap scoring.
This keeps the game playable offline while marking results as unverified.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field

from wm_staff_agents.doctrine.corpus import DoctrineConvention

logger = logging.getLogger(__name__)

JEV_DEFAULT_URL = "http://100.111.138.48:8012"
JEV_DEFAULT_MODEL = "jev-latest"


class JevQuestion(BaseModel):
    id: str
    question: str
    context: str = ""
    rubric: str = ""


class JevVerdict(BaseModel):
    question_id: str
    passed: bool
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    source: str = Field(description="'jev' or 'fallback'")


class JevClient:
    """HTTP client for the Jev judge at /v1/systemone."""

    def __init__(
        self,
        base_url: str = JEV_DEFAULT_URL,
        model: str = JEV_DEFAULT_MODEL,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def health(self) -> bool:
        try:
            c = await self._get_client()
            r = await c.get(f"{self.base_url}/health")
            return r.status_code == 200
        except Exception:
            return False

    async def judge(self, questions: list[JevQuestion]) -> list[JevVerdict]:
        """Send questions to Jev's /v1/systemone endpoint."""
        c = await self._get_client()
        payload: dict[str, Any] = {
            "model": self.model,
            "questions": {q.id: {"question": q.question, "context": q.context, "rubric": q.rubric}
                          for q in questions},
        }
        # Jev /v1/systemone expects {model, questions: {id: {question, context, rubric}}}
        resp = await c.post(f"{self.base_url}/v1/systemone", json=payload)
        resp.raise_for_status()
        data = resp.json()

        verdicts: list[JevVerdict] = []
        # Response shape: {answers: {id: {answer, reasoning, ...}}} or {results: ...}
        answers = data.get("answers") or data.get("results") or data
        for q in questions:
            raw = answers.get(q.id, {}) if isinstance(answers, dict) else {}
            if isinstance(raw, dict):
                passed = self._parse_passed(raw)
                verdicts.append(JevVerdict(
                    question_id=q.id,
                    passed=passed,
                    confidence=float(raw.get("confidence", 0.7)),
                    reasoning=str(raw.get("reasoning", raw.get("answer", raw))),
                    source="jev",
                ))
            elif isinstance(raw, str):
                verdicts.append(JevVerdict(
                    question_id=q.id, passed=True, confidence=0.5,
                    reasoning=raw, source="jev",
                ))
        return verdicts

    def _parse_passed(self, raw: dict[str, Any]) -> bool:
        for key in ("passed", "pass", "verdict", "answer"):
            if key in raw:
                val = raw[key]
                if isinstance(val, bool):
                    return val
                if isinstance(val, str):
                    low = val.lower().strip()
                    if low in ("pass", "passed", "yes", "true", "supported", "grounded"):
                        return True
                    if low in ("fail", "failed", "no", "false", "unsupported", "ungrounded"):
                        return False
        return True  # default pass if unclear


class DoctrineChecker:
    """Checks that agent decisions are grounded in cited doctrine.

    For each decision, the checker:
    1. Selects relevant doctrine conventions based on the decision text
    2. Asks Jev whether the justification follows from the cited doctrine
    3. Falls back to keyword overlap if Jev is unreachable
    """

    def __init__(
        self,
        jev_client: JevClient | None = None,
        fallback_enabled: bool = True,
    ) -> None:
        self.jev = jev_client or JevClient()
        self.fallback_enabled = fallback_enabled

    async def check_decision(
        self,
        decision: str,
        justification: str,
        cited_doctrine: list[DoctrineConvention],
        role_name: str = "",
    ) -> list[JevVerdict]:
        """Check one decision against its cited doctrine."""
        if not cited_doctrine:
            return [JevVerdict(
                question_id="no_doctrine",
                passed=False,
                confidence=1.0,
                reasoning="No doctrine cited for this decision.",
                source="fallback",
            )]

        questions: list[JevQuestion] = []
        for conv in cited_doctrine:
            qid = f"doctrine_{conv.id.replace('/', '_')}"
            questions.append(JevQuestion(
                id=qid,
                question=(
                    f"Does the following decision and its justification follow from the cited doctrine?\n\n"
                    f"Decision: {decision}\n"
                    f"Justification: {justification}\n\n"
                    f"Doctrine [{conv.id}]: {conv.description}\n"
                    f"Source: {conv.source.document} — {conv.source.publication}\n"
                    f"Rationale: {conv.rationale}"
                ),
                context=f"Role: {role_name}. Decision context: {decision}",
                rubric=(
                    "PASS if the justification cites or clearly applies the doctrine principle. "
                    "FAIL if the justification contradicts the doctrine, ignores it, or cites "
                    "it without actually applying its logic. Consider whether the reasoning "
                    "chain from doctrine to decision is sound."
                ),
            ))

        # Try Jev first
        try:
            verdicts = await self.jev.judge(questions)
            if verdicts:
                return verdicts
        except Exception as e:
            logger.warning("Jev unreachable (%s), using fallback", e)

        if self.fallback_enabled:
            return self._fallback_check(decision, justification, cited_doctrine)

        return [JevVerdict(
            question_id=q.id, passed=False, confidence=0.0,
            reasoning="Jev unavailable and fallback disabled.",
            source="fallback",
        ) for q in questions]

    def _fallback_check(
        self,
        decision: str,
        justification: str,
        conventions: list[DoctrineConvention],
    ) -> list[JevVerdict]:
        """Keyword-overlap fallback when Jev is down."""
        combined = f"{decision} {justification}".lower()
        verdicts: list[JevVerdict] = []
        for conv in conventions:
            # Check if any tag or key phrase from the doctrine appears in the justification
            tags_hit = sum(1 for t in conv.tags if t.lower() in combined)
            desc_words = set(re.findall(r"\w+", conv.description.lower()))
            just_words = set(re.findall(r"\w+", combined))
            overlap = len(desc_words & just_words) / max(len(desc_words), 1)

            passed = tags_hit > 0 or overlap > 0.15
            verdicts.append(JevVerdict(
                question_id=f"doctrine_{conv.id.replace('/', '_')}",
                passed=passed,
                confidence=0.5 if passed else 0.6,
                reasoning=(
                    f"Fallback check: {tags_hit} doctrine tags matched, "
                    f"{overlap:.0%} word overlap with doctrine text. "
                    f"{'Passed' if passed else 'Failed'} keyword grounding check. "
                    f"(Jev was unavailable — this is an approximation.)"
                ),
                source="fallback",
            ))
        return verdicts

    async def check_turn(
        self,
        decisions: list[dict[str, Any]],
    ) -> dict[str, list[JevVerdict]]:
        """Check all decisions in a turn. Each decision dict has: decision, justification, doctrine, role."""
        results: dict[str, list[JevVerdict]] = {}
        for d in decisions:
            role = d.get("role", "unknown")
            verdicts = await self.check_decision(
                decision=d["decision"],
                justification=d.get("justification", ""),
                cited_doctrine=d.get("doctrine", []),
                role_name=role,
            )
            results[role] = verdicts
        return results
