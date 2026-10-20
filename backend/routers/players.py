from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .. import security
from ..acconf import ServerConfig
from ..deps import get_config, get_manager
from ..services import audit, commands, players
from ..services.server_manager import ServerManager

router = APIRouter(prefix="/api/players", tags=["players"], dependencies=[Depends(security.require_session)])


class ActionBody(BaseModel):
    action: str
    params: dict = {}


@router.get("/characters")
async def characters(search: str = "", online: bool = False, limit: int = Query(100, le=500),
                     offset: int = Query(0, ge=0), cfg: ServerConfig = Depends(get_config)):
    return await players.characters(cfg, search.strip(), online, limit, offset)


@router.get("/accounts")
async def accounts(search: str = "", limit: int = Query(100, le=500), offset: int = Query(0, ge=0),
                   cfg: ServerConfig = Depends(get_config)):
    return await players.accounts(cfg, search.strip(), limit, offset)


@router.post("/action")
async def action(body: ActionBody, request: Request, manager: ServerManager = Depends(get_manager)):
    try:
        command = players.build_command(body.action, body.params)
    except (players.InvalidAction, ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = await commands.run_gm_command(manager, request.app.state.settings, command)
    audit.record(request, f"player.{body.action}", f"{command} (via {result['via']}{'' if result['ok'] else ', failed'})")
    return {"command": command, **result}
