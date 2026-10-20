"""Setup -> Database setup: initialise a portable MySQL and create the account and databases."""
import asyncio
import ipaddress
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..acconf import load_server_config
from ..services import audit, jobs, mysql_setup
from ..settings import Settings, save_settings
from .job_routes import add_job_routes

router = APIRouter(prefix="/api/db-setup", tags=["db-setup"], dependencies=[Depends(security.require_session)])


class SetupBody(BaseModel):
    host: str = Field(default="127.0.0.1", min_length=1, max_length=64)
    port: int = Field(default=3306, ge=1, le=65535)
    user: str = Field(default="", max_length=32)        # required for a fresh setup only
    password: str = Field(default="", max_length=64)


def slot(request: Request) -> jobs.JobSlot:
    return request.app.state.dbsetup_slot


add_job_routes(router, slot, "db-setup")


def _paths(settings: Settings) -> tuple[Path | None, Path | None]:
    """(server folder, source folder) for finding the databases to create."""
    return (settings.server_path if settings.configured else None), settings.source_path


@router.get("")
async def get_status(request: Request):
    settings: Settings = request.app.state.settings
    folder = settings.mysql_home          # chosen on Setup -> Requirements (anywhere)
    server, source = _paths(settings)
    state = await asyncio.to_thread(mysql_setup.status, folder, server, source)
    return {**state, "busy": slot(request).busy()}


@router.post("/run", status_code=202)
async def run(body: SetupBody, request: Request):
    if slot(request).busy():
        raise HTTPException(status_code=409, detail="A database setup is already running.")
    folder = request.app.state.settings.mysql_home
    if folder is None:
        raise HTTPException(status_code=409, detail="Choose the MySQL folder under Requirements first.")
    if not mysql_setup.is_mysql_home(folder):
        raise HTTPException(status_code=422, detail=f"No bin\\mysqld.exe in {folder}. Choose the MySQL folder under Requirements again.")
    fresh = not mysql_setup.initialised(folder)
    host = body.host.strip()
    if fresh:   # the account fields only matter when the account is created now
        try:
            host = "127.0.0.1" if host == "localhost" else str(ipaddress.IPv4Address(host))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Enter an IPv4 address, e.g. 127.0.0.1 (this PC only) or this PC's LAN address.") from exc
        if not mysql_setup._USER.match(body.user):
            raise HTTPException(status_code=422, detail="Enter an account name: letters, digits and _ only.")
        if not body.password:
            raise HTTPException(status_code=422, detail="Enter a password for the account.")
    if fresh and any(c in body.password for c in ';"\r\n'):
        raise HTTPException(status_code=422, detail='The password can\'t contain ; or " (AzerothCore configs separate values with ;).')
    settings: Settings = request.app.state.settings
    server, source = _paths(settings)
    databases = [d["name"] for d in await asyncio.to_thread(mysql_setup.planned_databases, server, source)]
    if not databases:
        raise HTTPException(status_code=409, detail="No databases found to create. Set the server or source folder first.")
    if slot(request).busy():
        raise HTTPException(status_code=409, detail="A database setup is already running.")

    options = body.model_dump() | {"host": host}
    if not fresh:
        # Already set up: only CREATE DATABASE IF NOT EXISTS, logged in with the account from Database setup
        # (remembered in settings) or else the one the servers use.
        if settings.db_connection:
            conn = settings.db_connection
        elif settings.configured:
            login = load_server_config(settings.server_path).login_db
            conn = {"host": login.host, "port": login.port, "user": login.user, "password": login.password}
        else:
            raise HTTPException(status_code=409, detail="This MySQL is already set up, but the panel doesn't know its account. Build and deploy the server first.")
        options |= conn
    store = slot(request).store
    job_id = store.new_job(type="setup", mysql_dir=str(folder), databases=databases, step=None, progress=0, duration=None)
    job = mysql_setup.SetupJob(folder, options, databases, lambda line: store.log(job_id, line),
                               lambda state: store.update_job(job_id, save=False, **state))
    app = request.app

    async def work(_log):
        result = await asyncio.to_thread(job.run_sync)
        if result.get("connection"):                    # Config Files puts it into the server configs
            new = replace(app.state.settings, db_connection=result.pop("connection"))
            save_settings(new)
            app.state.settings = new
        result.pop("connection", None)                  # never stored in the job record (it has the password)
        return result

    slot(request).start(job_id, job, work)
    audit.record(request, "db-setup.run", f"job #{job_id}: {folder}, user {options['user']}, databases {', '.join(databases)}"
                 f", host {options['host']}", "WARN")
    return {"job_id": job_id}
