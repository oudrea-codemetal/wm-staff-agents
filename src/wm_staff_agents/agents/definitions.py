"""Agent definitions: one LLM agent per staff role.

Each role gets an agent that knows its mission, doctrine, and what it must
produce. The agent's behaviour is driven entirely by the Role definition
in YAML — no role ID is hardcoded. When a human is slotted in, the agent
is bypassed and the human's input is used instead, with the same Jev check.

Mercury integration: agents are cm.ai AgentDefinitions when Mercury is
installed. Otherwise they degrade to direct OpenAI-compatible HTTP calls.
Both paths produce the same JSON and go through the same Jev check.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from wm_staff_agents.agents.prompts import build_system_prompt, build_task_prompt
from wm_staff_agents.doctrine.corpus import DoctrineCorpus
from wm_staff_agents.roles.hierarchy import Role

logger = logging.getLogger(__name__)


class RoleAgent:
    """One agent bound to one role. Driven entirely by the Role's YAML definition."""

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
        role_convs = self.doctrine_corpus.for_role(self.role.doctrine_focus)
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
        available_inputs: dict[str, Any] | None = None,
        previous_outcome: str = "",
    ) -> list[dict[str, str]]:
        doctrine_ctx = self._doctrine_context(
            self.role.task_prompt or self.role.description
        )
        system_text = build_system_prompt(self.role, self.team_name, doctrine_ctx)
        task_text = build_task_prompt(
            self.role, turn, game_state, commander_intent, available_inputs, previous_outcome,
        )
        # Prepend game state / intent context to task
        full_task = (
            f"Turn {turn} — Game state:\n{game_state}\n\n"
            f"Previous outcome: {previous_outcome or 'Game start — no previous outcome.'}\n\n"
            f"{task_text}"
        )
        if commander_intent and self.role.id != self._commander_id():
            full_task = (
                f"Commander intent: {commander_intent}\n\n" + full_task
            )
        return [
            {"role": "system", "content": system_text},
            {"role": "user", "content": full_task},
        ]

    def _commander_id(self) -> str:
        # The top-ranked role is the commander — no hardcoded ID
        return ""  # set externally if needed; for now just check rank

    async def generate(
        self,
        turn: int,
        game_state: str,
        commander_intent: str = "",
        available_inputs: dict[str, Any] | None = None,
        previous_outcome: str = "",
        human_override: str | None = None,
    ) -> dict[str, Any]:
        """Generate this role's output for a turn."""
        if human_override is not None:
            return self._parse_human_input(human_override)

        messages = self._build_messages(turn, game_state, commander_intent, available_inputs, previous_outcome)
        return await self._call_llm(messages)

    def _parse_human_input(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"human_input": text, "raw": text, "doctrine_refs": []}

    async def _call_llm(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        try:
            return await self._call_via_mercury(messages)
        except ImportError:
            pass
        return await self._call_via_openai(messages)

    async def _call_via_mercury(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        from cm.ai.llm import ChatCompletion  # type: ignore[import-untyped]
        completion = ChatCompletion()
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
        cleaned = text.strip()
        if cleaned.startswith("```"):
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
