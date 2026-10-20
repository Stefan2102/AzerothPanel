"""Database -> Import SQL: run an .sql file (picked with the panel's file browser) against one database."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..acconf import ServerConfig
from ..deps import get_config, get_manager
from ..services import audit, jobs, sql_import
from ..services.server_manager import ServerManager
from ..settings import Settings
from .job_routes import add_job_routes

router = APIRouter(prefix="/api/sql-import", tags=["database"], dependencies=[Depends(security.require_session)])


class ImportBody(BaseModel):
    database: str = Field(min_length=1, max_length=40)     # key: auth | characters | world | playerbots
    file: str = Field(min_length=3, max_length=500)
    force: bool = False                                      # continue after errors (mysql --force)
    backup: bool = False                                     # dump the database first


def slot(request: Request) -> jobs.JobSlot:
    return request.app.state.sqlimport_slot


add_job_routes(router, slot, "sql-import")


@router.post("/run", status_code=202)
async def run(body: ImportBody, request: Request, cfg: ServerConfig = Depends(get_config),
              manager: ServerManager = Depends(get_manager)):
    if slot(request).busy():
        raise HTTPException(status_code=409, detail="An import is already running.")
    info = cfg.databases.get(body.database)
    if info is None:
        raise HTTPException(status_code=404, detail="Unknown database.")
    try:
        file = await asyncio.to_thread(sql_import.check_file, body.file)
    except jobs.JobError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    settings: Settings = request.app.state.settings
    store = slot(request).store
    job_id = store.new_job(type="import", database=info.database, file=str(file), force=body.force, backup=body.backup,
                           world_running=manager.services["world"].is_up(), step=None, progress=0, detail=None)
    job = sql_import.ImportJob(info, settings.mysql_path, file, body.force, body.backup,
                               lambda line: store.log(job_id, line), lambda state: store.update_job(job_id, save=False, **state))

    async def work(_log):
        return await asyncio.to_thread(job.run_sync)

    slot(request).start(job_id, job, work)
    audit.record(request, "db.import", f"job #{job_id}: {file} -> {info.database}"
                 f"{', backup first' if body.backup else ''}{', continue after errors' if body.force else ''}", "WARN")
    return {"job_id": job_id}
