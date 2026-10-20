"""Build & Deploy API: toolchain detection, path overrides, build/deploy jobs and their logs."""
import asyncio
import os
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..deps import get_manager
from ..services import audit, build, jobs, mysql_setup, source as source_info
from ..services.server_manager import ServerManager
from ..settings import Settings, save_settings
from .job_routes import add_job_routes

router = APIRouter(prefix="/api/build", tags=["build"], dependencies=[Depends(security.require_session)])

# Requirements row -> settings field holding the user's choice. Source and build folder have fixed places
# in the AzerothCore folder and can't be changed here. MySQL is never detected: it is always the chosen folder.
PATH_FIELDS = {"cmake": "cmake_exe", "vs": "vs_instance", "boost": "boost_dir", "openssl": "openssl_dir",
               "mysql": "mysql_dir"}
# Jobs that use the MySQL folder (its tools or the running server); its folder can't change while one runs.
MYSQL_JOB_SLOTS = ("dbsetup_slot", "sqlimport_slot")


class PathBody(BaseModel):
    key: str
    path: str = Field(default="", max_length=400)     # empty = back to the detected path


class RunBody(BaseModel):
    config: str = "RelWithDebInfo"
    jobs: int = Field(default=4, ge=1, le=256)
    TOOLS_BUILD: str | None = None
    SCRIPTS: str | None = None
    MODULES: str | None = None
    clean: bool = False
    deploy: bool = True


class DeployBody(BaseModel):
    config: str = "RelWithDebInfo"


def slot(request: Request) -> jobs.JobSlot:
    return request.app.state.build_slot


def _busy(request: Request) -> bool:
    return slot(request).busy()


add_job_routes(router, slot, "build")


# ---- detection ------------------------------------------------------------------------------------------

@router.get("/toolchain")
async def toolchain_state(request: Request):
    settings: Settings = request.app.state.settings
    plan, problems, found = await asyncio.to_thread(build.resolve, settings)
    deploy_plan, _, _ = build.resolve(settings, deploy_only=True, found=found)
    ws = found["workspace"]
    items = {i.key: i for i in found["items"]}
    git = items["git"].path if items["git"].status == "ok" else None
    src = Path(ws["source"]) if ws["source_valid"] else None

    def details() -> dict:
        return {
            "revision": source_info.revision(git, src) if src else None,
            "modules": source_info.modules(src, git) if src else [],
            "choices": build.toolchain.build_options(src) if src else {},
        }

    extra = await asyncio.to_thread(details)
    return {
        "workspace": {**ws, **extra},
        "items": [i.public() for i in found["items"]],
        "ready": plan is not None,
        "deploy_ready": deploy_plan is not None,
        "problems": problems,
        "options": build.default_options(settings, found["cache"], src),
        "configs": build.CONFIGS,
        "cpu_threads": os.cpu_count(),
        "built": sorted(p.name for p in (Path(ws["build"]) / "bin").iterdir()) if ws["build"] and (Path(ws["build"]) / "bin").is_dir() else [],
        "busy": _busy(request),
    }


def _vs_installation(path: Path) -> str:
    found = build.toolchain.vs_instances()
    match = build.toolchain.vs_installation_for(path, found)
    if match is None:
        listed = "; ".join(i["path"] for i in found) or "none"
        raise HTTPException(status_code=422, detail="That folder isn't a Visual Studio installation with the C++ tools. "
                                                    f"Installed: {listed}.")
    return match["path"]


def _mysql_in_use(request: Request, manager: ServerManager) -> str | None:
    """Why the MySQL folder can't change now, or None."""
    if manager.services["mysql"].proc is not None:
        return "Stop MySQL on Server Control first (it runs from the current folder)."
    backup_task = getattr(request.app.state, "backup_task", None)
    if any(getattr(request.app.state, name).busy() for name in MYSQL_JOB_SLOTS) or (backup_task and not backup_task.done()):
        return "Wait until the running database setup, SQL import, backup or restore has finished."
    return None


@router.put("/paths")
def set_path(body: PathBody, request: Request, manager: ServerManager = Depends(get_manager)):
    if body.key not in PATH_FIELDS:
        raise HTTPException(status_code=404, detail="Unknown item.")
    if _busy(request):
        raise HTTPException(status_code=409, detail="Wait until the running build has finished.")
    if body.key == "mysql" and (reason := _mysql_in_use(request, manager)):
        raise HTTPException(status_code=409, detail=reason)
    value = body.path.strip().strip('"')
    if value:
        path = Path(value)
        if not path.is_absolute():
            raise HTTPException(status_code=422, detail="Use a full path, e.g. C:\\local\\boost_1_91_0.")
        if body.key == "cmake":
            if not path.is_file():
                raise HTTPException(status_code=422, detail="That file does not exist.")
        elif not path.is_dir():
            raise HTTPException(status_code=422, detail="That folder does not exist.")
        if body.key == "vs":
            value = _vs_installation(path)
        elif body.key == "mysql":
            try:
                value = str(mysql_setup.find_mysql_home(path))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
    current: Settings = request.app.state.settings
    new = replace(current, **{PATH_FIELDS[body.key]: value})
    save_settings(new)
    request.app.state.settings = new
    audit.record(request, "build.path", f"{body.key}: {value or 'reset to detected'}")
    return {"ok": True}


# ---- jobs -------------------------------------------------------------------------------------------------

async def _start(request: Request, manager: ServerManager, steps: list[str], options: dict, kind: str) -> int:
    plan, problems, _ = await asyncio.to_thread(build.resolve, request.app.state.settings, steps == ["deploy"])
    if plan is None:
        raise HTTPException(status_code=409, detail=" ".join(problems))
    if _busy(request):          # another request started a job while this one was resolving
        raise HTTPException(status_code=409, detail="A build is already running.")
    if request.app.state.modules_slot.busy():
        raise HTTPException(status_code=409, detail="A module is being installed, updated or removed; build after it.")
    if request.app.state.source_slot.busy():
        raise HTTPException(status_code=409, detail="The source is being cloned; build after it.")
    if options["config"] not in build.CONFIGS:
        raise HTTPException(status_code=422, detail="Unknown build configuration.")
    backup_task = getattr(request.app.state, "backup_task", None)
    if "deploy" in steps and backup_task is not None and not backup_task.done():
        raise HTTPException(status_code=409, detail="A backup or restore is running; deploy after it has finished.")
    if "deploy" in steps and request.app.state.data_slot.busy():
        raise HTTPException(status_code=409, detail="Client data is being downloaded or extracted; deploy after it has finished.")
    st = slot(request).store
    job_id = st.new_job(type=kind, options=options, step=None, progress=0, projects_done=0, projects_total=0,
                        files_done=0, files_total=0, warnings=0, errors=0, deployed=False, duration=None)
    job = build.BuildJob(plan, options, steps, lambda line: st.log(job_id, line),
                         lambda state: st.update_job(job_id, save=False, **state),
                         lambda: build.running_servers(manager))

    async def work(_log):
        return await job.run()

    slot(request).start(job_id, job, work)
    return job_id


@router.post("/run", status_code=202)
async def run(body: RunBody, request: Request, manager: ServerManager = Depends(get_manager)):
    if _busy(request):
        raise HTTPException(status_code=409, detail="A build is already running.")
    options = body.model_dump()
    current: Settings = request.app.state.settings
    new = replace(current, build_options=options)
    save_settings(new)
    request.app.state.settings = new
    steps = ["configure", "build"] + (["deploy"] if body.deploy else [])
    job_id = await _start(request, manager, steps, options, "build")
    audit.record(request, "build.run", f"job #{job_id}: {body.config}, {', '.join(steps)}"
                 f"{', clean' if body.clean else ''}")
    return {"job_id": job_id}


@router.post("/deploy", status_code=202)
async def deploy(body: DeployBody, request: Request, manager: ServerManager = Depends(get_manager)):
    if _busy(request):
        raise HTTPException(status_code=409, detail="A build is already running.")
    running = build.running_servers(manager)
    if running:
        raise HTTPException(status_code=409, detail=f"Stop {' and '.join(running)} first.")
    job_id = await _start(request, manager, ["deploy"], body.model_dump(), "deploy")
    audit.record(request, "build.deploy", f"job #{job_id}: {body.config}")
    return {"job_id": job_id}


@router.post("/pull", status_code=202)
async def pull(request: Request):
    """Update the core source (git pull --ff-only) as its own job."""
    if _busy(request):
        raise HTTPException(status_code=409, detail="A build is already running.")
    found = await asyncio.to_thread(build.toolchain.detect_all, request.app.state.settings)
    ws, git = found["workspace"], next(i for i in found["items"] if i.key == "git")
    if not ws["source_valid"]:
        raise HTTPException(status_code=409, detail="Choose the AzerothCore source folder first.")
    if git.status != "ok":
        raise HTTPException(status_code=409, detail="Git was not found. See Setup -> Requirements.")
    source = Path(ws["source"])
    if not (source / ".git").exists():
        raise HTTPException(status_code=409, detail="The source folder is not a git checkout, so it can't be pulled.")
    if request.app.state.modules_slot.busy():
        raise HTTPException(status_code=409, detail="A module is being installed, updated or removed; pull after it.")
    if _busy(request):
        raise HTTPException(status_code=409, detail="A build is already running.")
    st = slot(request).store
    job_id = st.new_job(type="pull", options={}, step=None, progress=0, projects_done=0, projects_total=0,
                        files_done=0, files_total=0, warnings=0, errors=0, deployed=False, duration=None, commits=0)
    job = build.PullJob(Path(git.path), source, lambda line: st.log(job_id, line),
                        lambda state: st.update_job(job_id, save=False, **state))

    async def work(_log):
        return await job.run()

    slot(request).start(job_id, job, work)
    audit.record(request, "build.pull", f"job #{job_id}: {source}")
    return {"job_id": job_id}
