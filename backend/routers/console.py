"""Live, read-only server consoles over WebSocket.

The ConPTY stream is interpreted server-side (console_screen.py); browsers get lines:
  {"t": "init",   "run": n, "lines": [...], "screen": [...]}  full state (connect / new run / fell behind)
  {"t": "update", "lines": [...new scrolled-off lines...], "screen": [...current screen...]}
A line is a list of [text, colour, bold] segments. Nothing is accepted from the client.
"""
import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import security
from ..services.server_manager import ORDER, ServerManager, Service

router = APIRouter()
THROTTLE = 0.1   # seconds; coalesces bursts (world startup prints thousands of lines)


def _init(svc: Service) -> tuple[dict, int]:
    con = svc.console
    if con is None:
        return {"t": "init", "run": svc.run_id, "lines": [], "screen": []}, 0
    return {"t": "init", "run": svc.run_id, "lines": list(con.lines), "screen": con.screen_lines()}, con.total


@router.websocket("/ws/console/{key}")
async def console(ws: WebSocket, key: str):
    if key not in ORDER or not security.websocket_allowed(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    manager: ServerManager = ws.app.state.manager
    svc = manager.services[key]
    changed = asyncio.Event()
    svc.watchers.add(changed)

    async def pump() -> None:
        msg, sent = _init(svc)
        run = svc.run_id
        await ws.send_text(json.dumps(msg))
        while True:
            await changed.wait()
            changed.clear()
            await asyncio.sleep(THROTTLE)
            con = svc.console
            new = (con.total - sent) if con else 0
            if svc.run_id != run or con is None or new > len(con.lines):
                msg, sent = _init(svc)          # new run, or this client fell behind the buffer
                run = svc.run_id
                await ws.send_text(json.dumps(msg))
                continue
            lines = [con.lines[i] for i in range(-new, 0)]   # deque: cheap access near the end
            sent = con.total
            await ws.send_text(json.dumps({"t": "update", "lines": lines, "screen": con.screen_lines()}))

    sender = asyncio.create_task(pump())
    try:
        while True:
            await ws.receive_text()   # ignored; only used to notice the client leaving
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        svc.watchers.discard(changed)
        sender.cancel()
