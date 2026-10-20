"""Setup -> Source code: clone AzerothCore (official, playerbots fork or any URL) into <AzerothCore folder>\\source."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..services import audit, clone, jobs, toolchain
from ..settings import Settings
from .job_routes import add_job_routes

router = APIRouter(prefix="/api/source", tags=["source"], dependencies=[Depends(security.require_session)])


class CloneBody(BaseModel):
    preset: str = "custom"                    # official | playerbots | custom
    url: str = Field(min_length=10, max_length=300)
    branch: str = Field(min_length=1, max_length=100)


def slot(request: Request) -> jobs.JobSlot:
    return request.app.state.source_slot


add_job_routes(router, slot, "source")


def _git(settings: Settings) -> str:
    item = next(i for i in toolchain.detect_all(settings)["items"] if i.key == "git")
    if item.status != "ok":
        raise HTTPException(status_code=409, detail="Git was not found. See Setup -> Requirements.")
    return item.path


def _guard(fn, *args):
    try:
        return fn(*args)
    except jobs.JobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/presets")
def presets():
    return clone.PRESETS


@router.get("/branches")
async def branches(url: str, request: Request):
    git = await asyncio.to_thread(_git, request.app.state.settings)
    url = _guard(clone.check_url, url)
    try:
        return await asyncio.to_thread(clone.remote_branches, git, url)
    except jobs.JobError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/clone", status_code=202)
async def start_clone(body: CloneBody, request: Request):
    if slot(request).busy():
        raise HTTPException(status_code=409, detail="A clone is already running.")
    if request.app.state.build_slot.busy() or request.app.state.modules_slot.busy():
        raise HTTPException(status_code=409, detail="A build or module operation is running; clone after it.")
    url = _guard(clone.check_url, body.url)
    branch = _guard(clone.check_branch, body.branch)
    target = request.app.state.settings.source_path        # fixed: <AzerothCore folder>\source
    if target is None:
        raise HTTPException(status_code=409, detail="Choose your AzerothCore folder first.")
    target = _guard(clone.check_target, str(target))
    git = await asyncio.to_thread(_git, request.app.state.settings)
    preset = next((p for p in clone.PRESETS if p["key"] == body.preset and p["url"] == url), None)
    modules = preset["modules"] if preset else []

    store = slot(request).store
    job_id = store.new_job(type="clone", url=url, branch=branch, folder=str(target),
                           modules=[m["name"] for m in modules], step=None, progress=0, detail=None, duration=None)
    job = clone.CloneJob(Path(git), url, branch, target, modules,
                         lambda line: store.log(job_id, line), lambda state: store.update_job(job_id, save=False, **state))

    async def work(_log):
        return await asyncio.to_thread(job.run_sync)

    slot(request).start(job_id, job, work)
    audit.record(request, "source.clone", f"job #{job_id}: {url} ({branch}) -> {target}"
                 f"{' + ' + ', '.join(m['name'] for m in modules) if modules else ''}")
    return {"job_id": job_id}
