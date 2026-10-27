"""Slack bridge: connects the wargame to Slack channels.

Each team has a Slack channel (e.g. #wargame-red, #wargame-blue) where
role agents post their deliberations and humans can interject. The bridge:

  - Posts agent decisions to the team channel
  - Listens for human messages and routes them as slot-in actions
  - Handles /slot-in and /slot-out slash commands
  - Posts turn reports as threaded summaries

Why Slack: The task says 'a shared chat room, maybe via slack' and notes
access to a slack workspace. Slack's RTM/Socket Mode gives us real-time
bidirectional messaging with minimal infrastructure.

If no Slack token is configured, the bridge runs in log-only mode —
messages go to stdout and the game log. This keeps the demo playable
without Slack.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class SlackConfig:
    def __init__(
        self,
        bot_token: str | None = None,
        app_token: str | None = None,
        red_channel: str = "#wargame-red",
        blue_channel: str = "#wargame-blue",
        enabled: bool | None = None,
    ) -> None:
        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN")
        self.app_token = app_token or os.environ.get("SLACK_APP_TOKEN")
        self.red_channel = red_channel
        self.blue_channel = blue_channel
        self.enabled = enabled if enabled is not None else bool(self.bot_token)

    @classmethod
    def from_env(cls) -> SlackConfig:
        return cls(
            bot_token=os.environ.get("SLACK_BOT_TOKEN"),
            app_token=os.environ.get("SLACK_APP_TOKEN"),
            red_channel=os.environ.get("SLACK_RED_CHANNEL", "#wargame-red"),
            blue_channel=os.environ.get("SLACK_BLUE_CHANNEL", "#wargame-blue"),
        )


class SlackBridge:
    """Bridges game events to Slack channels.

    In enabled mode, uses slack_sdk's async WebClient + Socket Mode.
    In disabled mode, logs to stdout (suitable for demo replay).
    """

    def __init__(self, config: SlackConfig | None = None) -> None:
        self.config = config or SlackConfig.from_env()
        self._client: Any = None
        self._message_handlers: list[Any] = []
        self._running = False
        self.log: list[dict[str, Any]] = []  # always record for replay

    async def start(self) -> None:
        if not self.config.enabled:
            logger.info("Slack disabled — running in log-only mode")
            return

        try:
            from slack_sdk.web.async_client import AsyncWebClient
            from slack_sdk.socket_mode.async_client import AsyncSocketModeClient

            self._client = AsyncWebClient(token=self.config.bot_token)
            # Socket mode for real-time events
            auth = await self._client.auth_test()
            logger.info("Slack connected as %s", auth.get("user"))
            self._running = True
        except ImportError:
            logger.warning("slack_sdk not installed — log-only mode")
            self.config.enabled = False
        except Exception as e:
            logger.warning("Slack connect failed (%s) — log-only mode", e)
            self.config.enabled = False

    async def stop(self) -> None:
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass

    def on_message(self, handler: Any) -> None:
        """Register a callback for incoming Slack messages: handler(channel, user, text)."""
        self._message_handlers.append(handler)

    # -- Outbound: game → Slack --

    async def post_role_decision(
        self,
        side: str,
        role_id: str,
        role_name: str,
        decision: dict[str, Any],
    ) -> None:
        """Post a role agent's decision to the team channel."""
        channel = self._channel_for(side)
        text = f"*{role_name}* ({side}): {self._summarise(decision)}"
        await self._post(channel, text, metadata={"side": side, "role": role_id})

    async def post_turn_report(self, side: str, report_text: str) -> None:
        channel = self._channel_for(side)
        await self._post(channel, f"📋 *Turn Report*\n{report_text}", metadata={"side": side})

    async def post_ito(self, side: str, ito_summary: str) -> None:
        channel = self._channel_for(side)
        await self._post(channel, f"✈️ *ITO — {side.title()}*\n```{ito_summary}```", metadata={"side": side})

    async def post_system(self, side: str, text: str) -> None:
        channel = self._channel_for(side)
        await self._post(channel, f"_{text}_", metadata={"side": side})

    async def _post(self, channel: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        entry = {"channel": channel, "text": text, "metadata": metadata or {}}
        self.log.append(entry)

        if not self.config.enabled or not self._client:
            print(f"[SLACK {channel}] {text}")
            return

        try:
            await self._client.chat_postMessage(channel=channel, text=text)
        except Exception as e:
            logger.warning("Slack post failed: %s", e)

    def _channel_for(self, side: str) -> str:
        return self.config.red_channel if side == "red" else self.config.blue_channel

    def _summarise(self, decision: dict[str, Any]) -> str:
        # Pick the most informative field
        for key in ("intent", "summary", "threat_assessment", "gaps"):
            if key in decision and decision[key]:
                return str(decision[key])[:500]
        # Fallback: first non-meta value
        for k, v in decision.items():
            if not k.startswith("_") and v:
                return f"{k}: {str(v)[:300]}"
        return "(no summary)"

    # -- Inbound: Slack → game (slash commands) --

    def parse_slash_command(self, text: str) -> dict[str, Any] | None:
        """Parse /slot-in and /slot-out commands from Slack.

        Examples:
          /slot-in force_commander
          /slot-out force_commander handover note here
        """
        text = text.strip()
        if text.startswith("/slot-in"):
            parts = text.split(maxsplit=2)
            return {"command": "slot_in", "role_id": parts[1] if len(parts) > 1 else "", "note": parts[2] if len(parts) > 2 else ""}
        if text.startswith("/slot-out"):
            parts = text.split(maxsplit=2)
            return {"command": "slot_out", "role_id": parts[1] if len(parts) > 1 else "", "note": parts[2] if len(parts) > 2 else ""}
        return None
