"""Agent definitions: one Mercury cm.ai agent per StaffEngine role.

Each role gets an agent that knows its responsibilities, its doctrine,
and how to produce its deliverable. When a human is slotted in, the
agent is bypassed and the human's input is used instead — but the same
Jev doctrine check applies.

Mercury integration: agents are defined as cm.ai AgentDefinitions when
Mercury is installed. When Mercury is not installed (e.g. on a minimal
AWS box), agents degrade to direct LLM calls via OpenAI-compatible API.
Both paths produce the same JSON output and go through the same Jev check.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from wm_staff_agents.agents.prompts import ROLE_PROMPTS
from wm_staff_agents.doctrine.corpus import DoctrineCorpus
from wm_staff_agents.roles.hierarchy import Role

logger = logging.getLogger(__name__)


class RoleAgent:
    """One agent bound to one role. Can call an LLM or be bypassed by a human."""

    def __init__(
        self,
        role: Role,
        team_name: str,
        doctrine_corpus: DoctrineCorpus,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        self.role = role
        self.team_name = team_name
        self.doctrine_corpus = doctrine_corpus
        self.llm_config = llm_config or {}

    def _doctrine_context(self, task_text: str = "") -> str:
        conventions = self.doctrine_corpus.matching(task_text or self.role.description)
        # Also include role-specific doctrine
        role_convs = self.doctrine_corpus.for_role(self.role.doctrine_focus)
        # Merge, dedupe by id
        seen: set[str] = set()
        all_convs: list[Any] = []
        for c in list(conventions) + role_convs:
            if c.id not in seen:
                seen.add(c.id)
                all_convs.append(c)
        return self.doctrine_corpus.format_for_prompt(all_convs)

    def _build_messages(
        self,
        turn: int,
        game_state: str,
        commander_intent: str = "",
        extra_context: dict[str, str] | None = None,
        previous_outcome: str = "",
    ) -> list[dict[str, str]]:
        prompt_def = ROLE_PROMPTS.get(self.role.id, ROLE_PROMPTS["force_commander"])
        doctrine_ctx = self._doctrine_context(extra_context.get("task_hint", "") if extra_context else "")

        system_text = prompt_def["system"].format(
            team_name=self.team_name,
            doctrine_focus=", ".join(self.role.doctrine_focus),
            doctrine_context=doctrine_ctx,
        )
        task_text = prompt_def["task"].format(
            turn=turn,
            team_name=self.team_name,
            game_state=game_state,
            commander_intent=commander_intent,
            previous_outcome=previous_outcome or "No previous turn (game start).",
            nominated_targets=extra_context.get("nominated_targets", "") if extra_context else "",
            targeting_plan=extra_context.get("targeting_plan", "") if extra_context else "",
            support_plan=extra_context.get("support_plan", "") if extra_context else "",
            threat_assessment=extra_context.get("threat_assessment", "") if extra_context else "",
            air_tasking=extra_context.get("air_tasking", "") if extra_context else "",
        )
        return [
            {"role": "system", "content": system_text},
            {"role": "user", "content": task_text},
        ]

    async def generate(
        self,
        turn: int,
        game_state: str,
        commander_intent: str = "",
        extra_context: dict[str, str] | None = None,
        previous_outcome: str = "",
        human_override: str | None = None,
    ) -> dict[str, Any]:
        """Generate this role's output for a turn.

        If human_override is provided, parse it as the role's output
        (human slotted in). Otherwise call the LLM.
        """
        if human_override is not None:
            return self._parse_human_input(human_override)

        messages = self._build_messages(turn, game_state, commander_intent, extra_context, previous_outcome)

        # Try Mercury cm.ai first, fall back to direct OpenAI-compatible call
        result = await self._call_llm(messages)
        return result

    def _parse_human_input(self, text: str) -> dict[str, Any]:
        """Parse human text as role output. Accepts JSON or freeform."""
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            # Freeform: wrap as a generic output
            return {"human_input": text, "raw": text, "doctrine_refs": []}

    async def _call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """Call LLM via Mercury cm.ai or direct OpenAI-compatible API."""
        # Try Mercury first
        try:
            from cm.ai.llm import ChatCompletion  # type: ignore[import-untyped]
            from cm.ai.config import LlmConfig  # type: ignore[import-untyped]
            return await self._call_via_mercury(messages)
        except ImportError:
            pass

        # Fallback: direct OpenAI-compatible HTTP
        return await self._call_via_openai(messages)

    async def _call_via_mercury(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        from cm.ai.llm import ChatCompletion  # type: ignore[import-untyped]

        # Use whatever LlmConfig is globally configured
        completion = ChatCompletion()
        # Mercury's ChatCompletion takes messages in its own format
        result = await completion.complete(messages)  # type: ignore[arg-type]
        text = result.content if hasattr(result, "content") else str(result)
        return self._parse_json_response(text)

    async def _call_via_openai(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        import httpx

        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        api_key = os.environ.get("OPENAI_API_KEY", "sk-test")
        model = os.environ.get("OPENAI_MODEL", self.llm_config.get("model", "gpt-4o-mini"))

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.7,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return self._parse_json_response(text)

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        # Handle markdown-fenced JSON
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # Strip ```json ... ``` fences
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse JSON from %s: %s", self.role.id, text[:500])
            return {"raw_response": text, "parse_error": True, "doctrine_refs": []}


def build_role_agent(
    role: Role,
    team_name: str,
    doctrine_corpus: DoctrineCorpus,
    llm_config: dict[str, Any] | None = None,
) -> RoleAgent:
    return RoleAgent(role=role, team_name=team_name, doctrine_corpus=doctrine_corpus, llm_config=llm_config)


def build_all_agents(
    roles: list[Role],
    team_name: str,
    doctrine_corpus: DoctrineCorpus,
    llm_config: dict[str, Any] | None = None,
) -> dict[str, RoleAgent]:
    return {r.id: build_role_agent(r, team_name, doctrine_corpus, llm_config) for r in roles}
