"""WarMatrix MCP client wrapper.

Why MCP alone: The task requires that WarMatrix integration go through the
MCP server only. This module wraps the warmatrix-mcp package as an MCP client,
handling the stdio transport and tool dispatch. It does not call WarMatrix
HTTP APIs directly — every game operation goes through an MCP tool.

The client is designed to work both locally (for development) and on the
AWS instance where WarMatrix actually runs. Configuration comes from
environment variables matching warmatrix-mcp's own Settings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass
class WarMatrixConfig:
    """Configuration for connecting to WarMatrix via MCP."""

    api_url: str = "http://127.0.0.1:18000/v2"
    legacy_api_url: str | None = None
    bearer_token: str | None = None
    token_url: str | None = None
    username: str | None = None
    password: str | None = None
    game_ids: list[int] = field(default_factory=list)
    scenario_ids: list[int] = field(default_factory=list)
    native_game_ids: list[int] = field(default_factory=list)
    allow_plan_writes: bool = False
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> WarMatrixConfig:
        return cls(
            api_url=os.environ.get("WM_API_URL", "http://127.0.0.1:18000/v2"),
            legacy_api_url=os.environ.get("WM_V1_API_URL"),
            bearer_token=os.environ.get("WM_BEARER_TOKEN"),
            token_url=os.environ.get("WM_TOKEN_URL"),
            username=os.environ.get("WM_USERNAME"),
            password=os.environ.get("WM_PASSWORD"),
            game_ids=[int(x) for x in os.environ.get("WM_GAME_IDS", "").split(",") if x.strip()],
            scenario_ids=[int(x) for x in os.environ.get("WM_SCENARIO_IDS", "").split(",") if x.strip()],
            native_game_ids=[int(x) for x in os.environ.get("WM_NATIVE_GAME_IDS", "").split(",") if x.strip()],
            allow_plan_writes=os.environ.get("WM_ALLOW_PLAN_WRITES", "false").lower() == "true",
            timeout_seconds=float(os.environ.get("WM_TIMEOUT_SECONDS", "60")),
        )

    def mcp_env(self) -> dict[str, str]:
        """Environment variables for the warmatrix-mcp subprocess."""
        env: dict[str, str] = {}
        if self.api_url:
            env["WM_API_URL"] = self.api_url
        if self.legacy_api_url:
            env["WM_V1_API_URL"] = self.legacy_api_url
        if self.bearer_token:
            env["WM_BEARER_TOKEN"] = self.bearer_token
        if self.token_url:
            env["WM_TOKEN_URL"] = self.token_url
        if self.username:
            env["WM_USERNAME"] = self.username
        if self.password:
            env["WM_PASSWORD"] = self.password
        if self.game_ids:
            env["WM_GAME_IDS"] = ",".join(str(x) for x in self.game_ids)
        if self.scenario_ids:
            env["WM_SCENARIO_IDS"] = ",".join(str(x) for x in self.scenario_ids)
        if self.native_game_ids:
            env["WM_NATIVE_GAME_IDS"] = ",".join(str(x) for x in self.native_game_ids)
        env["WM_ALLOW_PLAN_WRITES"] = str(self.allow_plan_writes).lower()
        env["WM_TIMEOUT_SECONDS"] = str(self.timeout_seconds)
        return env


class MCPToolResult(BaseModel):
    """Result from an MCP tool call."""

    tool: str
    content: list[dict[str, Any]] = []
    is_error: bool = False

    @property
    def text(self) -> str:
        parts: list[str] = []
        for c in self.content:
            if c.get("type") == "text":
                parts.append(c.get("text", ""))
        return "\n".join(parts)

    def as_json(self) -> Any:
        try:
            return json.loads(self.text)
        except (json.JSONDecodeError, ValueError):
            return self.text


class WarMatrixMCPClient:
    """MCP client for WarMatrix. Manages a warmatrix-mcp subprocess over stdio.

    Usage:
        client = WarMatrixMCPClient(config)
        await client.connect()
        result = await client.call_tool("list_legacy_games", {"limit": 10})
        await client.disconnect()
    """

    def __init__(self, config: WarMatrixConfig | None = None) -> None:
        self.config = config or WarMatrixConfig.from_env()
        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._tools: list[dict[str, Any]] = []

    async def connect(self) -> None:
        """Start the warmatrix-mcp subprocess and perform MCP handshake."""
        env = {**os.environ, **self.config.mcp_env()}
        self._proc = await asyncio.create_subprocess_exec(
            "uv", "run", "--env-file", ".env", "warmatrix-mcp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        # Try direct warmatrix-mcp first, fall back to python -m
        if self._proc.returncode is not None:
            self._proc = await asyncio.create_subprocess_exec(
                "warmatrix-mcp",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

        self._reader_task = asyncio.create_task(self._read_loop())

        # MCP initialize handshake
        init_result = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "wm-staff-agents", "version": "0.1.0"},
        })
        logger.info("MCP initialized: %s", init_result)

        # Notifications/initialized
        await self._notify("notifications/initialized", {})

        # List tools
        tools_result = await self._request("tools/list", {})
        self._tools = tools_result.get("tools", [])
        logger.info("MCP tools available: %s", [t["name"] for t in self._tools])

    async def disconnect(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()

    def tool_names(self) -> list[str]:
        return [t["name"] for t in self._tools]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> MCPToolResult:
        """Call an MCP tool and return the result."""
        result = await self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        return MCPToolResult(
            tool=name,
            content=result.get("content", []),
            is_error=result.get("isError", False),
        )

    # -- JSON-RPC framing --

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        rid = self._request_id
        msg = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        assert self._proc and self._proc.stdin
        line = (json.dumps(msg) + "\n").encode()
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=self.config.timeout_seconds)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        assert self._proc and self._proc.stdin
        line = (json.dumps(msg) + "\n").encode()
        self._proc.stdin.write(line)
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            line = await self._proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("MCP non-JSON line: %s", line[:500])
                continue

            rid = msg.get("id")
            if rid is not None and rid in self._pending:
                fut = self._pending.pop(rid)
                if "error" in msg:
                    fut.set_exception(RuntimeError(f"MCP error: {msg['error']}"))
                else:
                    fut.set_result(msg.get("result", {}))
            elif "method" in msg:
                logger.debug("MCP notification: %s", msg.get("method"))


# ------------------------------------------------------------------ mock for offline dev

class MockWarMatrixMCPClient:
    """In-memory mock that mimics WarMatrixMCPClient for local development."""

    def __init__(self, scenario_data_path: Path | None = None) -> None:
        self.scenario_data_path = scenario_data_path
        self._games = [
            {"game_id": 3, "name": "South China Sea Conflict",
             "moves": [
                 {"move_id": 7, "move_number": 1, "starts_at": "2025-01-01T00:00:00Z",
                  "ends_at": "2025-01-01T12:00:00Z", "move_teams": [1, 2]},
                 {"move_id": 8, "move_number": 2, "starts_at": "2025-01-01T12:00:00Z",
                  "ends_at": "2025-01-02T00:00:00Z", "move_teams": [1, 2]},
             ],
             "teams": [{"team_id": 1, "name": "Blue"}, {"team_id": 2, "name": "Red"}]},
        ]
        self._plans: dict[str, Any] = {}

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    def tool_names(self) -> list[str]:
        return [
            "list_legacy_games", "read_legacy_dca_context",
            "prefetch_legacy_regional_context", "propose_legacy_regional_dca",
            "prepare_legacy_dca_plan", "submit_legacy_dca_plan",
            "read_legacy_plan_summaries", "validate_plan_document",
            "list_scenarios", "search_catalog_definitions",
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> MCPToolResult:
        args = arguments or {}
        if name == "list_legacy_games":
            return MCPToolResult(tool=name, content=[
                {"type": "text", "text": json.dumps({"games": self._games})}
            ])
        if name == "read_legacy_dca_context":
            return MCPToolResult(tool=name, content=[
                {"type": "text", "text": json.dumps({
                    "game_id": args.get("game_id", 3),
                    "move_id": args.get("move_id", 7),
                    "context": "SCS theatre: Taiwan Strait, Bashi Channel, ECS",
                    "available_aircraft": 291,
                    "bases": ["Kadena", "Guam", "Taiwan West", "Fujian Coast"],
                })}
            ])
        # Generic echo for other tools
        return MCPToolResult(tool=name, content=[
            {"type": "text", "text": json.dumps({"status": "mock_ok", "tool": name, "args": args})}
        ])
