"""Backup & Restore API. Long operations run as one background job at a time; the browser
polls /jobs/{id} for status and log lines."""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..acconf import ServerConfig
from ..deps import get_config, get_manager, get_settings
from ..services import audit, backup, jobs
from ..services.server_manager import ServerManager
from ..settings import Settings

router = APIRouter(prefix="/api/backups", tags=["backups"], dependencies=[Depends(security.require_session)])


class DestinationBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    path: str = Field(min_length=1, max_length=400)
    enabled: bool = True


class BackupBody(BaseModel):
    destination_id: int = backup.DEFAULT_DEST_ID
    include_configs: bool = True
    include_databases: bool = True
    include_binaries: bool = False
    notes: str = Field(default="", max_length=300)


class RestoreBody(BaseModel):
    job_id: int
    restore_configs: bool = True
    restore_databases: bool = True
    restore_binaries: bool = False


def _store(request: Request) -> backup.BackupStore:
    return request.app.state.backup_store


def _guard(fn, *args):
    try:
        return fn(*args)
    except jobs.JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _start_job(request: Request, job_id: int, work) -> None:
    """Run the blocking `work(log)` in a thread as the single active backup/restore job."""
    async def run(log):
        return await asyncio.to_thread(work, log)

    request.app.state.backup_task = jobs.start(_store(request), job_id, run)


def _busy(request: Request) -> bool:
    task = getattr(request.app.state, "backup_task", None)
    return task is not None and not task.done()


# ---- destinations -------------------------------------------------------------------------

@router.get("/destinations")
def list_destinations(request: Request):
    return _store(request).destinations()


@router.post("/destinations", status_code=201)
def create_destination(body: DestinationBody, request: Request):
    _guard(backup.test_destination, body.path)
    dest = _store(request).add_destination(body.name.strip(), body.path.strip().strip('"'), body.enabled)
    audit.record(request, "backup.destination.add", f"{dest['name']} -> {dest['path']}")
    return dest


@router.put("/destinations/{dest_id}")
def update_destination(dest_id: int, body: DestinationBody, request: Request):
    _guard(backup.test_destination, body.path)
    _guard(_store(request).update_destination, dest_id, body.name.strip(), body.path.strip().strip('"'), body.enabled)
    audit.record(request, "backup.destination.edit", f"#{dest_id} {body.name.strip()} -> {body.path.strip()} "
                 f"({'enabled' if body.enabled else 'disabled'})")
    return {"ok": True}


@router.delete("/destinations/{dest_id}")
def delete_destination(dest_id: int, request: Request):
    _guard(_store(request).delete_destination, dest_id)
    audit.record(request, "backup.destination.delete", f"#{dest_id}")
    return {"ok": True}


@router.post("/destinations/{dest_id}/test")
def test_destination(dest_id: int, request: Request):
    dest = _guard(_store(request).destination, dest_id)
    try:
        return {"success": True, "message": backup.test_destination(dest["path"])}
    except backup.BackupError as exc:
        return {"success": False, "message": str(exc)}


# ---- jobs -------------------------------------------------------------------------------------

@router.get("/jobs")
def list_jobs(request: Request):
    return {"jobs": _store(request).jobs(), "busy": _busy(request)}


@router.get("/jobs/{job_id}")
def get_job(job_id: int, request: Request):
    return _guard(_store(request).job, job_id)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, request: Request):
    """Removes the history record only; the archive file stays at its destination."""
    _store(request).delete_job(job_id)
    audit.record(request, "backup.job.delete", f"#{job_id} (record only)")
    return {"ok": True}


@router.get("/jobs/{job_id}/files")
def job_files(job_id: int, request: Request):
    store = _store(request)
    job = _guard(store.job, job_id)
    dest = _guard(store.destination, job["destination_id"])
    return backup.list_archives(dest["path"])


@router.delete("/jobs/{job_id}/files/{filename}")
def delete_job_file(job_id: int, filename: str, request: Request):
    store = _store(request)
    job = _guard(store.job, job_id)
    dest = _guard(store.destination, job["destination_id"])
    path = _guard(backup.archive_path, dest, filename)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    path.unlink()
    audit.record(request, "backup.file.delete", str(path), "WARN")
    return {"ok": True}


# ---- backup / restore --------------------------------------------------------------------------

@router.post("/run", status_code=202)
async def run_backup(body: BackupBody, request: Request, cfg: ServerConfig = Depends(get_config),
                     settings: Settings = Depends(get_settings)):
    if _busy(request):
        raise HTTPException(status_code=409, detail="Another backup or restore is still running.")
    include = {"configs": body.include_configs, "databases": body.include_databases, "binaries": body.include_binaries}
    if not any(include.values()):
        raise HTTPException(status_code=422, detail="Choose at least one thing to back up.")
    store = _store(request)
    dest = _guard(store.destination, body.destination_id)
    if not dest["enabled"]:
        raise HTTPException(status_code=409, detail="That destination is disabled.")
    job_id = store.new_job(type="backup", destination_id=dest["id"], destination_name=dest["name"],
                           include=include, notes=body.notes.strip(), file=None, size=0)

    def work(log):
        name, size = backup.run_backup(cfg, settings.mysql_path, dest, include, body.notes.strip(), log)
        return {"file": name, "size": size}

    _start_job(request, job_id, work)
    audit.record(request, "backup.run", f"job #{job_id} to {dest['name']}: "
                 f"{', '.join(k for k, v in include.items() if v)}{' - ' + body.notes.strip() if body.notes.strip() else ''}")
    return {"job_id": job_id}


@router.post("/restore", status_code=202)
async def restore(body: RestoreBody, request: Request, cfg: ServerConfig = Depends(get_config),
                  settings: Settings = Depends(get_settings), manager: ServerManager = Depends(get_manager)):
    if _busy(request):
        raise HTTPException(status_code=409, detail="Another backup or restore is still running.")
    running = [manager.services[k].label for k in ("world", "auth") if manager.services[k].is_up()]
    if running:
        raise HTTPException(status_code=409, detail=f"Stop {' and '.join(running)} before restoring.")
    store = _store(request)
    source = _guard(store.job, body.job_id)
    if source.get("type") != "backup" or source["status"] != "completed" or not source.get("file"):
        raise HTTPException(status_code=409, detail="Only completed backups can be restored.")
    dest = _guard(store.destination, source["destination_id"])
    archive: Path = _guard(backup.archive_path, dest, source["file"])
    if not archive.is_file():
        raise HTTPException(status_code=404, detail=f"{source['file']} is no longer in {dest['path']}.")
    options = {"configs": body.restore_configs, "databases": body.restore_databases, "binaries": body.restore_binaries}
    if not any(options.values()):
        raise HTTPException(status_code=422, detail="Choose at least one thing to restore.")
    job_id = store.new_job(type="restore", source_job_id=source["id"], destination_id=dest["id"],
                           destination_name=dest["name"], include=options, notes="", file=source["file"], size=0)
    _start_job(request, job_id, lambda log: backup.run_restore(cfg, settings.mysql_path, archive, options, log))
    audit.record(request, "backup.restore", f"job #{job_id} from {source['file']}: "
                 f"{', '.join(k for k, v in options.items() if v)}", "WARN")
    return {"job_id": job_id}
