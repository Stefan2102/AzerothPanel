"""FastAPI application: API routers, websockets and the built frontend on one port."""
from __future__ import annotations

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import security
from .paths import FRONTEND_DIST
from .routers import auth, backups, build, client_data as client_data_router, config_values, configs, console, quick_settings, sql_import as sql_import_router, database, database_setup, fs, logs, modules as modules_router, players, server, settings, shortcuts, source_setup
from .services import audit
from .services import build as build_service, client_data, clone, modules, mysql_setup, sql_import
from .services.jobs import JobSlot
from .services.backup import BackupStore, remove_stale_option_files
from .services.db import DbError
from .services.server_manager import ServerManager, ServiceError
from .settings import Settings


def create_app(initial_settings: Settings, control_token: str) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.manager.start_monitor()
        yield
        # Panel is exiting: cancel a running build / data job, then stop the servers it started, in safe order.
        await app.state.build_slot.shutdown()
        await app.state.data_slot.shutdown()
        await app.state.modules_slot.shutdown()
        await app.state.dbsetup_slot.shutdown()
        await app.state.source_slot.shutdown()
        await app.state.sqlimport_slot.shutdown()
        await app.state.manager.shutdown()

    security.ensure_default_account()   # fresh install: admin / admin
    app = FastAPI(title="AzerothPanel", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = initial_settings
    app.state.manager = ServerManager(lambda: app.state.settings)
    app.state.backup_store = BackupStore()
    remove_stale_option_files()             # nothing can be running yet, so any left over is stale
    # Remote listener state: set by __main__ when it starts the HTTPS listener.
    app.state.remote_active = None
    app.state.remote_at_start = (initial_settings.remote_enabled, initial_settings.remote_port,
                                 initial_settings.tls_cert, initial_settings.tls_key)
    app.state.backup_task = None
    app.state.build_slot = JobSlot(build_service.new_store())
    app.state.data_slot = JobSlot(client_data.new_store())
    app.state.modules_slot = JobSlot(modules.new_store())
    app.state.dbsetup_slot = JobSlot(mysql_setup.new_store())
    app.state.source_slot = JobSlot(clone.new_store())
    app.state.sqlimport_slot = JobSlot(sql_import.new_store())
    app.state.request_exit = lambda: None   # replaced by __main__ once uvicorn is created

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, exc: ServiceError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(DbError)
    async def db_error(_: Request, exc: DbError):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/api/health")
    def health():
        return {"ok": True, "app": "azerothpanel"}

    @app.post("/api/control/shutdown", status_code=202)
    def control_shutdown(x_control_token: str = Header(default="")):
        """Used by `python -m backend stop` (stop.bat); authenticated by a token file only
        readable by the local user."""
        if not hmac.compare_digest(x_control_token, control_token):
            raise HTTPException(status_code=403, detail="Bad control token.")
        audit.write("panel.shutdown", "via stop.bat", who="local", ip="127.0.0.1")
        app.state.request_exit()
        return {"ok": True}

    for module in (auth, server, console, players, logs, database, backups, build, client_data_router, modules_router, database_setup, source_setup, fs, config_values, quick_settings, sql_import_router, configs, settings, shortcuts):
        app.include_router(module.router)

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
    else:
        @app.get("/")
        def no_frontend():
            return JSONResponse(status_code=503, content={"detail": "Frontend not built. Run install.bat."})

    return app
