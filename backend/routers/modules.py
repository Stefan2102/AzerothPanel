"""Modules API: catalogue, installed modules, install / update / remove jobs."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..services import audit, jobs, modules, toolchain
from .job_routes import add_job_routes

router = APIRouter(prefix="/api/modules", tags=["modules"], dependencies=[Depends(security.require_session)])


class InstallBody(BaseModel):
    full_name: str = Field(min_length=3, max_length=200)      # owner/repo from the catalogue


class UrlBody(BaseModel):
    url: str = Field(min_length=10, max_length=300)           # any https git URL (modules not in the catalogue)


def slot(request: Request) -> jobs.JobSlot:
    return request.app.state.modules_slot


add_job_routes(router, slot, "modules")


def _workspace(request: Request) -> tuple[Path, str | None]:
    """(source folder, git.exe) or 409 when there is no usable source folder."""
    found = toolchain.detect_all(request.app.state.settings)
    ws = found["workspace"]
    if not ws["source_valid"]:
        raise HTTPException(status_code=409, detail="Choose the AzerothCore source folder on the Compilation page first.")
    git = next(i for i in found["items"] if i.key == "git")
    return Path(ws["source"]), git.path if git.status == "ok" else None


def _check_free(request: Request) -> None:
    if slot(request).busy():
        raise HTTPException(status_code=409, detail="Another module operation is still running.")
    if request.app.state.build_slot.busy() or request.app.state.source_slot.busy():
        raise HTTPException(status_code=409, detail="A build, source update or clone is running; change modules after it.")


@router.get("/catalogue")
async def get_catalogue(refresh: bool = False):
    try:
        return await asyncio.to_thread(modules.catalogue, refresh)
    except jobs.JobError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/installed")
async def get_installed(request: Request):
    source, git = await asyncio.to_thread(_workspace, request)
    items = await asyncio.to_thread(modules.installed, source, git)
    build = toolchain.workspace(request.app.state.settings)["build"]
    build_dir = Path(build) if build else None
    return {
        "source": str(source), "modules": items, "git": bool(git), "busy": slot(request).busy(),
        "rebuild_needed": modules.rebuild_needed(items, request.app.state.build_slot.store, build_dir),
    }


async def _start(request: Request, kind: str, name: str | None = None, url: str | None = None) -> int:
    _check_free(request)
    source, git = await asyncio.to_thread(_workspace, request)
    if git is None and kind != "remove":
        raise HTTPException(status_code=409, detail="Git was not found. See Setup -> Requirements.")
    if name is not None:
        try:
            folder = modules.module_dir(source, name)
        except jobs.JobError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        exists = folder.exists() or folder.is_junction()
        if kind == "install" and exists:
            raise HTTPException(status_code=409, detail=f"modules\\{name} already exists.")
        if kind != "install" and not exists:
            raise HTTPException(status_code=404, detail=f"modules\\{name} does not exist.")
    _check_free(request)
    store = slot(request).store
    job_id = store.new_job(type=kind, name=name, step=None, progress=0, changed=False, duration=None)
    job = modules.ModuleJob(kind, Path(git) if git else None, source, lambda line: store.log(job_id, line),
                            lambda state: store.update_job(job_id, save=False, **state), name=name, url=url)
    slot(request).start(job_id, job, lambda _log: asyncio.to_thread(job.run_sync))
    return job_id


@router.post("/install", status_code=202)
async def install(body: InstallBody, request: Request):
    data = await asyncio.to_thread(modules.catalogue)
    item = next((i for i in data["categories"]["modules"] if (i["full_name"] or "").lower() == body.full_name.lower()), None)
    if item is None:
        raise HTTPException(status_code=404, detail="That module is not in the AzerothCore catalogue.")
    url = f"https://github.com/{item['full_name']}.git"
    job_id = await _start(request, "install", item["name"], url)
    audit.record(request, "modules.install", f"job #{job_id}: {item['full_name']}")
    return {"job_id": job_id}


@router.post("/install-url", status_code=202)
async def install_url(body: UrlBody, request: Request):
    url = body.url.strip()
    try:
        name = modules.name_from_url(url)
    except jobs.JobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job_id = await _start(request, "install", name, url)
    audit.record(request, "modules.install", f"job #{job_id}: {url}")
    return {"job_id": job_id}


@router.post("/update-all", status_code=202)
async def update_all(request: Request):
    job_id = await _start(request, "update-all")
    audit.record(request, "modules.update-all", f"job #{job_id}")
    return {"job_id": job_id}


@router.post("/{name}/update", status_code=202)
async def update(name: str, request: Request):
    job_id = await _start(request, "update", name)
    audit.record(request, "modules.update", f"job #{job_id}: {name}")
    return {"job_id": job_id}


@router.delete("/{name}", status_code=202)
async def remove(name: str, request: Request):
    job_id = await _start(request, "remove", name)
    audit.record(request, "modules.remove", f"job #{job_id}: {name}", "WARN")
    return {"job_id": job_id}
