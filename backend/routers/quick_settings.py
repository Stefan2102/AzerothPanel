"""Config Files -> Quick settings: common worldserver.conf values as a form."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import security
from ..deps import get_manager
from ..services import audit, quick_settings
from ..services.server_manager import ServerManager
from ..settings import Settings

router = APIRouter(prefix="/api/quick-settings", tags=["configs"], dependencies=[Depends(security.require_session)])


class SaveBody(BaseModel):
    values: dict[str, str]


def _server(request: Request):
    settings: Settings = request.app.state.settings
    if not settings.root_dir:
        raise HTTPException(status_code=409, detail="Choose your AzerothCore folder first.")
    return settings.server_path


@router.get("")
async def get_quick(request: Request, manager: ServerManager = Depends(get_manager)):
    state = await asyncio.to_thread(quick_settings.state, _server(request))
    return {**state, "world_running": manager.services["world"].is_up()}


@router.put("")
async def save_quick(body: SaveBody, request: Request, manager: ServerManager = Depends(get_manager)):
    server = _server(request)
    try:
        changed = await asyncio.to_thread(quick_settings.save, server, body.values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record(request, "config.quick", ", ".join(f"{k} = {body.values[k]}" for k in changed) or "no change")
    state = await asyncio.to_thread(quick_settings.state, server)
    return {**state, "changed": changed, "world_running": manager.services["world"].is_up()}
