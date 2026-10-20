"""Config Files -> "Paths for this setup": the values the panel keeps in the server configs."""
import asyncio
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..services import audit, config_values, mysql_setup
from ..settings import Settings, save_settings

router = APIRouter(prefix="/api/config-values", tags=["configs"], dependencies=[Depends(security.require_session)])


class DbBody(BaseModel):
    host: str = Field(min_length=1, max_length=64)
    port: int = Field(ge=1, le=65535)
    user: str = Field(min_length=1, max_length=32)
    password: str | None = Field(default=None, max_length=64)     # None = keep the saved one


class ValuesBody(BaseModel):
    paths: dict[str, str]
    db: DbBody | None = None


def _check_paths(paths: dict[str, str]) -> dict[str, str]:
    if set(paths) != set(config_values.PATH_KEYS):
        raise HTTPException(status_code=422, detail=f"Expected exactly {', '.join(config_values.PATH_KEYS)}.")
    out = {}
    for key, value in paths.items():
        value = value.strip()
        if any(c in value for c in '"\r\n'):
            raise HTTPException(status_code=422, detail=f'{key} can\'t contain " or line breaks.')
        out[key] = value
    return out


def _check_db(body: DbBody, current: dict) -> dict:
    host, user = body.host.strip(), body.user.strip()
    password = current.get("password", "") if body.password is None else body.password
    if any(c in host for c in ';" '):
        raise HTTPException(status_code=422, detail="Enter an IP address or host name.")
    if not mysql_setup._USER.match(user):
        raise HTTPException(status_code=422, detail="Account name: letters, digits and _ only.")
    if not password:
        raise HTTPException(status_code=422, detail="Enter the account's password.")
    if any(c in password for c in ';"\r\n'):
        raise HTTPException(status_code=422, detail='The password can\'t contain ; or " (AzerothCore configs separate values with ;).')
    return {"host": host, "port": body.port, "user": user, "password": password}


@router.get("")
async def get_values(request: Request):
    return await asyncio.to_thread(config_values.status, request.app.state.settings)


@router.get("/password")
def reveal_password(request: Request):
    """The database password, only when asked for (eye button); every reveal is in the audit log."""
    settings: Settings = request.app.state.settings
    conn = settings.db_connection or config_values.connection_from_configs(settings)
    audit.record(request, "config.values.reveal", "database password shown")
    return {"password": conn.get("password", "")}


@router.put("")
async def save_and_apply(body: ValuesBody, request: Request):
    """Save the values, then write them into every existing config."""
    if request.app.state.build_slot.busy():
        raise HTTPException(status_code=409, detail="A build or deploy is running; apply after it.")
    current: Settings = request.app.state.settings
    paths = _check_paths(body.paths)
    defaults = config_values.default_paths(current)
    changes: dict = {"config_paths": {k: v for k, v in paths.items() if v != defaults[k]}}   # defaults follow the folder
    if body.db is not None:
        # an empty password keeps the saved one, or the one already in the configs
        changes["db_connection"] = _check_db(body.db, current.db_connection or config_values.connection_from_configs(current))
    new = replace(current, **changes)
    save_settings(new)
    request.app.state.settings = new
    applied = await asyncio.to_thread(config_values.apply_all, new)
    audit.record(request, "config.values",
                 f"paths {paths}; database {'set' if body.db else 'unchanged'}; "
                 f"applied to {', '.join(a['file'] for a in applied) or 'no file (all up to date)'}")
    return {"applied": applied, "status": await asyncio.to_thread(config_values.status, new)}
