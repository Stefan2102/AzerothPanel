"""Data Extraction API: client data status, download of the pre-extracted release, extraction from a client."""
import asyncio
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..acconf import ServerConfig
from ..deps import get_config, get_manager
from ..services import audit, client_data, jobs, toolchain
from ..services.server_manager import ServerManager
from ..settings import Settings, save_settings
from .job_routes import add_job_routes

router = APIRouter(prefix="/api/client-data", tags=["client-data"], dependencies=[Depends(security.require_session)])


class ExtractBody(BaseModel):
    client_dir: str = Field(min_length=1, max_length=400)
    types: list[str] = Field(min_length=1)


def slot(request: Request) -> jobs.JobSlot:
    return request.app.state.data_slot


add_job_routes(router, slot, "client-data")


def _pinned(settings: Settings) -> str | None:
    source = toolchain.workspace(settings)["source"]
    return client_data.pinned_version(Path(source)) if source else None


def _check_free(request: Request) -> None:
    if slot(request).busy():
        raise HTTPException(status_code=409, detail="Client data is already being downloaded or extracted.")


def _world_running(manager: ServerManager):
    return lambda: manager.services["world"].is_up()


def _new_job(request: Request, kind: str, **fields) -> int:
    return slot(request).store.new_job(type=kind, step=None, progress=0, duration=None, **fields)


def _progress(request: Request, job_id: int):
    store = slot(request).store
    return lambda state: store.update_job(job_id, save=False, **state)


@router.get("")
async def get_status(request: Request, cfg: ServerConfig = Depends(get_config),
                     manager: ServerManager = Depends(get_manager)):
    settings: Settings = request.app.state.settings
    state = await asyncio.to_thread(client_data.status, cfg.data_dir)
    return {
        **state,
        "pinned_version": await asyncio.to_thread(_pinned, settings),
        "tools": client_data.tools_present(settings.server_path),
        "client_dir": settings.client_dir,
        "world_running": manager.services["world"].is_up(),
        "busy": slot(request).busy(),
    }


@router.post("/download", status_code=202)
async def download(request: Request, cfg: ServerConfig = Depends(get_config),
                   manager: ServerManager = Depends(get_manager)):
    _check_free(request)
    settings: Settings = request.app.state.settings
    version = await asyncio.to_thread(_pinned, settings) or await asyncio.to_thread(client_data.latest_release)
    if not version:
        raise HTTPException(status_code=502, detail="Couldn't find which client-data release to download "
                                                    "(no source folder and GitHub didn't answer).")
    if manager.services["world"].is_up():
        raise HTTPException(status_code=409, detail="Stop Worldserver first; its data folders get replaced.")
    _check_free(request)
    job_id = _new_job(request, "download", version=version)
    store = slot(request).store
    job = client_data.DownloadJob(version, cfg.data_dir, lambda line: store.log(job_id, line),
                                  _progress(request, job_id), _world_running(manager))
    slot(request).start(job_id, job, lambda _log: client_data.run(job))
    audit.record(request, "client-data.download", f"job #{job_id}: {version} -> {cfg.data_dir}")
    return {"job_id": job_id}


@router.post("/extract", status_code=202)
async def extract(body: ExtractBody, request: Request, cfg: ServerConfig = Depends(get_config),
                  manager: ServerManager = Depends(get_manager)):
    _check_free(request)
    settings: Settings = request.app.state.settings
    types = [t for t in client_data.TYPES if t in body.types]
    if not types:
        raise HTTPException(status_code=422, detail="Choose at least one data type.")
    client = Path(body.client_dir.strip().strip('"'))
    if not client.is_absolute() or not client.is_dir():
        raise HTTPException(status_code=422, detail="Enter the full path of your WoW 3.3.5a folder.")
    _, problems = await asyncio.to_thread(client_data.check_client, client)
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    tools = client_data.tools_present(settings.server_path)
    needed = (["map_extractor.exe"] if {"dbc", "maps"} & set(types) else []) \
        + (["vmap4_extractor.exe", "vmap4_assembler.exe"] if "vmaps" in types else []) \
        + (["mmaps_generator.exe"] if "mmaps" in types else [])
    missing = [t for t in needed if not tools[t]]
    if missing:
        raise HTTPException(status_code=409, detail=f"{', '.join(missing)} not in the server folder. "
                                                    "Compile with Tools = all and deploy first.")
    if manager.services["world"].is_up():
        raise HTTPException(status_code=409, detail="Stop Worldserver first; its data folders get replaced.")
    if request.app.state.build_slot.busy():
        raise HTTPException(status_code=409, detail="A build is running; the extractor tools may be replaced. Try again after it.")
    _check_free(request)
    new = replace(settings, client_dir=str(client))
    save_settings(new)
    request.app.state.settings = new
    job_id = _new_job(request, "extract", types=types, client_dir=str(client))
    store = slot(request).store
    job = client_data.ExtractJob(client, settings.server_path, types, cfg.data_dir,
                                 lambda line: store.log(job_id, line), _progress(request, job_id), _world_running(manager))
    slot(request).start(job_id, job, lambda _log: client_data.run(job))
    audit.record(request, "client-data.extract", f"job #{job_id}: {', '.join(types)} from {client}")
    return {"job_id": job_id}
