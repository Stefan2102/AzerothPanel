import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..deps import get_config, get_manager
from ..services import audit, commands, players
from ..services.db import DbError
from ..services.server_manager import ORDER, ServerManager

router = APIRouter(prefix="/api", tags=["server"], dependencies=[Depends(security.require_session)])

_counts_cache: dict = {"at": 0.0, "value": None}


class StopBody(BaseModel):
    delay: int | None = Field(default=None, ge=0, le=3600)


class KillBody(BaseModel):
    confirm: bool = False


class CommandBody(BaseModel):
    command: str = Field(min_length=1, max_length=1000)


def _key(key: str) -> str:
    if key not in ORDER:
        raise HTTPException(status_code=404, detail="Unknown service.")
    return key


@router.get("/status")
async def status(request: Request, manager: ServerManager = Depends(get_manager)):
    snap = manager.snapshot()
    settings = request.app.state.settings
    snap["configured"] = settings.configured
    snap["counts"] = None
    try:
        cfg = manager.config() if settings.configured else None
    except ValueError:
        cfg = None
    snap["commands"] = commands.availability(manager, cfg, settings)
    # Running build / client-data / module jobs, for the header indicator.
    for key, slot in (("build", request.app.state.build_slot), ("data", request.app.state.data_slot),
                      ("modules", request.app.state.modules_slot), ("source", request.app.state.source_slot),
                      ("sqlimport", request.app.state.sqlimport_slot)):
        job = slot.running()
        snap[key] = {k: job.get(k) for k in ("id", "type", "step", "progress", "detail", "name")} if job else None
    if snap["configured"] and manager.services["mysql"].state != "starting":
        now = time.monotonic()
        if now - _counts_cache["at"] > 5:
            _counts_cache["at"] = now
            try:
                _counts_cache["value"] = await players.counts(get_config(request))
            except (DbError, HTTPException):
                _counts_cache["value"] = None
        snap["counts"] = _counts_cache["value"]
    return snap


@router.post("/server/{key}/start", status_code=202)
async def start(key: str, request: Request, manager: ServerManager = Depends(get_manager)):
    key = _key(key)
    manager.run_job(f"Start {manager.services[key].label}", lambda: manager.start(key))
    audit.record(request, "server.start", manager.services[key].label)
    return {"ok": True}


@router.post("/server/{key}/stop", status_code=202)
async def stop(key: str, body: StopBody, request: Request, manager: ServerManager = Depends(get_manager)):
    key = _key(key)
    manager.run_job(f"Stop {manager.services[key].label}", lambda: manager.stop(key, body.delay))
    audit.record(request, "server.stop", manager.services[key].label)
    return {"ok": True}


@router.post("/server/{key}/restart", status_code=202)
async def restart(key: str, body: StopBody, request: Request, manager: ServerManager = Depends(get_manager)):
    key = _key(key)
    manager.run_job(f"Restart {manager.services[key].label}", lambda: manager.restart(key, body.delay))
    audit.record(request, "server.restart", manager.services[key].label)
    return {"ok": True}


@router.post("/server/{key}/kill")
async def kill(key: str, body: KillBody, request: Request, manager: ServerManager = Depends(get_manager)):
    key = _key(key)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Force kill must be confirmed.")
    manager.force_kill(key)
    audit.record(request, "server.kill", manager.services[key].label, "WARN")
    return {"ok": True}


@router.post("/server/start-all", status_code=202)
async def start_all(request: Request, manager: ServerManager = Depends(get_manager)):
    manager.run_job("Start all", manager.start_all)
    audit.record(request, "server.start-all")
    return {"ok": True}


@router.post("/server/stop-all", status_code=202)
async def stop_all(body: StopBody, request: Request, manager: ServerManager = Depends(get_manager)):
    manager.run_job("Safe stop all", lambda: manager.stop_all(body.delay))
    audit.record(request, "server.stop-all")
    return {"ok": True}


@router.post("/server/command")
async def command(body: CommandBody, request: Request, manager: ServerManager = Depends(get_manager)):
    result = await commands.run_gm_command(manager, request.app.state.settings, body.command)
    audit.record(request, "gm.command", f"{body.command.strip()} (via {result['via']}{'' if result['ok'] else ', failed'})")
    return result


@router.post("/panel/shutdown", status_code=202)
async def panel_shutdown(request: Request):
    """Safely stop the servers the panel started, then exit the panel."""
    audit.record(request, "panel.shutdown")
    request.app.state.request_exit()
    return {"ok": True}
