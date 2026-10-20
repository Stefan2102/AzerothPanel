import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from .. import security
from ..acconf import ServerConfig, load_server_config
from ..deps import get_config
from ..services import logs

router = APIRouter(tags=["logs"])
_protected = [Depends(security.require_session)]


def _path(cfg: ServerConfig, source: str):
    try:
        return logs.resolve_source(cfg, source)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Log source not available.") from exc


@router.get("/api/logs", dependencies=_protected)
def list_logs(cfg: ServerConfig = Depends(get_config)):
    return logs.list_sources(cfg)


@router.get("/api/logs/{source}", dependencies=_protected)
async def read_log(source: str, before: int | None = Query(None, ge=0), limit: int = Query(1000, ge=1, le=5000),
                   cfg: ServerConfig = Depends(get_config)):
    return await asyncio.to_thread(logs.read_page, _path(cfg, source), before, limit)


@router.get("/api/logs/{source}/download", dependencies=_protected)
def download_log(source: str, cfg: ServerConfig = Depends(get_config)):
    path = _path(cfg, source)
    return FileResponse(path, filename=path.name, media_type="text/plain")


@router.websocket("/ws/logs/{source}")
async def follow_log(ws: WebSocket, source: str, offset: int = 0):
    if not security.websocket_allowed(ws):
        await ws.close(code=4401)
        return
    settings = ws.app.state.settings
    try:
        path = logs.resolve_source(load_server_config(settings.server_path), source)
    except (FileNotFoundError, ValueError):
        await ws.close(code=4404)
        return
    await ws.accept()
    follower = logs.Follower(path, offset)
    receiver = asyncio.create_task(ws.receive_text())   # completes when the client goes away
    try:
        while not receiver.done():
            truncated, lines = await asyncio.to_thread(follower.poll)
            if truncated:
                await ws.send_text(json.dumps({"t": "reset"}))
            if lines:
                await ws.send_text(json.dumps({"t": "lines", "d": lines, "offset": follower.resume_offset}))
            await asyncio.wait({receiver}, timeout=0.5)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        receiver.cancel()
