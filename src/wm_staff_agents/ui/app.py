"""Web UI: slot in/out dashboard and game control.

A minimal FastAPI app that serves:
  GET  /              — dashboard HTML (role slots, game state, turn reports)
  GET  /api/state     — JSON game state (for polling / WebSocket clients)
  POST /api/slot-in   — {side, role_id, human_id, note}
  POST /api/slot-out  — {side, role_id, note}
  POST /api/human-act — {side, role_id, text}
  POST /api/run-turn  — {turn}
  POST /api/run-game  — {turns}
  GET  /api/reports   — turn reports
  WS   /ws            — live updates

Why a custom UI alongside Slack: Slack is for team communication.
The web UI is for game management — an administrator configures roles,
starts turns, and anyone can slot in/out without needing Slack. Both
surfaces stay in sync via the shared GameEngine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


class SlotInRequest(BaseModel):
    side: str
    role_id: str
    human_id: str = "human"
    note: str = ""


class SlotOutRequest(BaseModel):
    side: str
    role_id: str
    note: str = ""


class HumanActRequest(BaseModel):
    side: str
    role_id: str
    text: str


class RunTurnRequest(BaseModel):
    turn: int | None = None


DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>South China Sea Conflict — Staff Wargame</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, system-ui, sans-serif; background: #0f1117; color: #e0e0e0; padding: 20px; }
  h1 { font-size: 1.4em; margin-bottom: 4px; }
  .subtitle { color: #888; margin-bottom: 20px; }
  .teams { display: flex; gap: 20px; flex-wrap: wrap; }
  .team { flex: 1; min-width: 320px; background: #1a1d27; border-radius: 8px; padding: 16px; }
  .team h2 { font-size: 1.1em; margin-bottom: 12px; }
  .team.red h2 { color: #e74c3c; } .team.blue h2 { color: #3498db; }
  .role { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #2a2d3a; }
  .role:last-child { border-bottom: none; }
  .role-name { font-weight: 600; }
  .role-rank { color: #888; font-size: 0.85em; }
  .holder { padding: 4px 10px; border-radius: 12px; font-size: 0.85em; }
  .holder.agent { background: #2a2d3a; color: #aaa; }
  .holder.human { background: #27ae60; color: #fff; }
  .controls { margin-top: 20px; display: flex; gap: 10px; flex-wrap: wrap; }
  button { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }
  button.primary { background: #3498db; color: #fff; }
  button.danger { background: #e74c3c; color: #fff; }
  #log { margin-top: 20px; background: #1a1d27; border-radius: 8px; padding: 16px; max-height: 400px; overflow-y: auto; font-family: monospace; font-size: 0.85em; white-space: pre-wrap; }
  select, input { background: #2a2d3a; color: #e0e0e0; border: 1px solid #3a3d4a; border-radius: 4px; padding: 6px 10px; }
</style>
</head>
<body>
<h1>South China Sea Conflict — Staff Wargame</h1>
<p class="subtitle">Hierarchical wargaming via WarMatrix · StaffEngine roles · Doctrine-grounded agents</p>

<div class="teams">
  <div class="team red" id="red-team"><h2>🔴 Red Team</h2><div class="roles"></div></div>
  <div class="team blue" id="blue-team"><h2>🔵 Blue Team</h2><div class="roles"></div></div>
</div>

<div class="controls">
  <button class="primary" onclick="runTurn()">▶ Run Next Turn</button>
  <button class="primary" onclick="runGame()">▶▶ Run Full Game</button>
  <select id="slot-side"><option value="red">Red</option><option value="blue">Blue</option></select>
  <select id="slot-role"></select>
  <input id="slot-human" placeholder="Your name" value="human">
  <button onclick="slotIn()">Slot In</button>
  <button onclick="slotOut()">Slot Out</button>
</div>

<div id="log">Connecting...</div>

<script>
let ws = null;
function connect() {
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
  ws.onopen = () => log('Connected.');
  ws.onmessage = (e) => { const d = JSON.parse(e.data); if (d.type === 'state') render(d); if (d.type === 'log') log(d.text); };
  ws.onclose = () => { log('Disconnected. Reconnecting...'); setTimeout(connect, 2000); };
}
function log(t) { const el = document.getElementById('log'); el.textContent += '\\n' + t; el.scrollTop = el.scrollHeight; }
async function api(path, body) {
  const r = await fetch(path, {method: body ? 'POST' : 'GET', headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
  return r.json();
}
async function render(state) {
  if (!state) state = await api('/api/state');
  for (const side of ['red', 'blue']) {
    const team = state.teams[side];
    if (!team) continue;
    const container = document.querySelector(`#${side}-team .roles`);
    container.innerHTML = '';
    for (const slot of team.slots) {
      const div = document.createElement('div');
      div.className = 'role';
      const holder = slot.holder === 'agent' ? '<span class="holder agent">Agent</span>' : `<span class="holder human">${slot.holder}</span>`;
      div.innerHTML = `<span><span class="role-name">${slot.role_name}</span> <span class="role-rank">#${slot.rank}</span></span>${holder}`;
      container.appendChild(div);
    }
  }
  // Fill role selector
  const sel = document.getElementById('slot-role');
  if (sel.options.length === 0 && state.hierarchy) {
    for (const r of state.hierarchy.roles) {
      const o = document.createElement('option'); o.value = r.id; o.textContent = r.name; sel.appendChild(o);
    }
  }
  if (state.game) log(`Turn ${state.game.turn} | Red losses: ${state.game.red_losses} Blue losses: ${state.game.blue_losses}`);
}
async function runTurn() { log('Running turn...'); const r = await api('/api/run-turn', {}); log(r.narrative || JSON.stringify(r)); render(); }
async function runGame() { log('Running full game...'); const r = await api('/api/run-game', {turns: 6}); log(`Game complete: ${r.length} turns`); render(); }
async function slotIn() {
  const side = document.getElementById('slot-side').value;
  const role_id = document.getElementById('slot-role').value;
  const human_id = document.getElementById('slot-human').value || 'human';
  const r = await api('/api/slot-in', {side, role_id, human_id}); log(`Slotted in: ${JSON.stringify(r)}`); render();
}
async function slotOut() {
  const side = document.getElementById('slot-side').value;
  const role_id = document.getElementById('slot-role').value;
  const r = await api('/api/slot-out', {side, role_id}); log(`Slotted out: ${JSON.stringify(r)}`); render();
}
connect();
fetch('/api/state').then(r => r.json()).then(render);
</script>
</body>
</html>
"""


def create_app(game_engine: Any | None = None) -> FastAPI:
    app = FastAPI(title="South China Sea Conflict — Staff Wargame")
    app.state.engine = game_engine
    app.state.ws_clients: list[WebSocket] = []

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        return DASHBOARD_HTML

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        eng = app.state.engine
        if eng is None:
            return {"status": "no game loaded", "teams": {}, "hierarchy": None, "game": None}
        h = eng.hierarchy
        return {
            "status": "ready",
            "hierarchy": {"name": h.name, "roles": [r.model_dump() for r in h.roles]},
            "teams": {
                "red": {
                    "name": eng.red_team.config.name,
                    "slots": [
                        {"role_id": s.role_id, "role_name": h.get(s.role_id).name,
                         "rank": h.get(s.role_id).rank, "holder": s.holder}
                        for s in eng.red_team.config.slots
                    ],
                },
                "blue": {
                    "name": eng.blue_team.config.name,
                    "slots": [
                        {"role_id": s.role_id, "role_name": h.get(s.role_id).name,
                         "rank": h.get(s.role_id).rank, "holder": s.holder}
                        for s in eng.blue_team.config.slots
                    ],
                },
            },
            "game": eng.state.model_dump(),
            "reports": len(eng.reports),
        }

    @app.post("/api/slot-in")
    async def slot_in(req: SlotInRequest) -> dict[str, Any]:
        eng = app.state.engine
        if eng is None:
            return {"error": "no game loaded"}
        eng.slot_in(req.side, req.role_id, req.human_id, req.note)
        await _broadcast({"type": "log", "text": f"{req.human_id} slotted into {req.side}/{req.role_id}"})
        return {"ok": True, "side": req.side, "role": req.role_id, "holder": req.human_id}

    @app.post("/api/slot-out")
    async def slot_out(req: SlotOutRequest) -> dict[str, Any]:
        eng = app.state.engine
        if eng is None:
            return {"error": "no game loaded"}
        eng.slot_out(req.side, req.role_id, req.note)
        await _broadcast({"type": "log", "text": f"Agent resumed {req.side}/{req.role_id}"})
        return {"ok": True, "side": req.side, "role": req.role_id, "holder": "agent"}

    @app.post("/api/human-act")
    async def human_act(req: HumanActRequest) -> dict[str, Any]:
        eng = app.state.engine
        if eng is None:
            return {"error": "no game loaded"}
        eng.human_act(req.side, req.role_id, req.text)
        return {"ok": True}

    @app.post("/api/run-turn")
    async def run_turn(req: RunTurnRequest) -> dict[str, Any]:
        eng = app.state.engine
        if eng is None:
            return {"error": "no game loaded"}
        turn = req.turn or (eng.state.turn + 1)
        report = await eng.run_turn(turn)
        await _broadcast({"type": "log", "text": report.narrative})
        return report.model_dump()

    @app.post("/api/run-game")
    async def run_game(req: RunTurnRequest) -> list[dict[str, Any]]:
        eng = app.state.engine
        if eng is None:
            return [{"error": "no game loaded"}]
        n = req.turn or eng.scenario.max_turns
        reports = await eng.run_game(n)
        for r in reports:
            await _broadcast({"type": "log", "text": r.narrative})
        return [r.model_dump() for r in reports]

    @app.get("/api/reports")
    async def get_reports() -> list[dict[str, Any]]:
        eng = app.state.engine
        if eng is None:
            return []
        return [r.model_dump() for r in eng.reports]

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        app.state.ws_clients.append(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if ws in app.state.ws_clients:
                app.state.ws_clients.remove(ws)

    async def _broadcast(msg: dict[str, Any]) -> None:
        dead: list[Any] = []
        for ws in app.state.ws_clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for d in dead:
            app.state.ws_clients.remove(d)

    return app
