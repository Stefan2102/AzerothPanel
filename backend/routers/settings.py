from dataclasses import asdict, replace
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..acconf import load_server_config
from ..deps import get_manager
from ..services import audit, db, soap, tls
from ..services.backup import find_mysqldump
from ..services.server_manager import ServerManager, port_open
from ..settings import LAYOUT, Settings, save_settings

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(security.require_session)])


class RootBody(BaseModel):
    root_dir: str = Field(min_length=3, max_length=300)


class SettingsBody(BaseModel):
    session_hours: int = Field(ge=1, le=24 * 30)
    world_shutdown_delay: int = Field(ge=0, le=3600)


class RemoteBody(BaseModel):
    enabled: bool
    port: int = Field(ge=1, le=65535)
    tls_cert: str = ""
    tls_key: str = ""


class SoapBody(BaseModel):
    username: str = Field(default="", max_length=32)
    password: str | None = Field(default=None, max_length=64)   # None = keep the saved one


def _summary(settings: Settings) -> dict:
    public = asdict(settings)
    public["soap_password_set"] = bool(public.pop("soap_password"))   # never sent to the browser
    db = public.pop("db_connection")                                   # same for the database password
    public["db_connection"] = {k: v for k, v in db.items() if k != "password"} if db else None
    out: dict = {"settings": public, "layout": LAYOUT, "paths": settings.paths(), "configured": settings.configured,
                 "config": None, "error": None}
    if settings.configured:
        try:
            cfg = load_server_config(settings.server_path)
            out["config"] = {
                "world_conf": str(cfg.world_conf), "auth_conf": str(cfg.auth_conf),
                "databases": {k: v.public() for k, v in cfg.databases.items()},
                "realm_id": cfg.realm_id, "world_port": cfg.world_port, "auth_port": cfg.auth_port,
                "logs_dir": str(cfg.logs_dir), "data_dir": str(cfg.data_dir),
                "soap_enabled": cfg.soap_enabled, "soap_host": cfg.soap_host, "soap_port": cfg.soap_port,
                "mysqldump": str(find_mysqldump(settings.mysql_path) or ""),
            }
        except ValueError as exc:
            out["error"] = str(exc)
    return out


@router.get("")
def get(request: Request):
    return _summary(request.app.state.settings)


_JOB_SLOTS = ("build_slot", "data_slot", "modules_slot", "dbsetup_slot", "source_slot", "sqlimport_slot")


@router.put("/root")
def update_root(body: RootBody, request: Request, manager: ServerManager = Depends(get_manager)):
    """The AzerothCore folder. Source, build and server have fixed places inside it (settings.LAYOUT);
    it may be new or empty (Setup fills it), so nothing inside has to exist yet."""
    root = Path(body.root_dir.strip().strip('"'))
    if not root.is_absolute() or not root.drive:
        raise HTTPException(status_code=422, detail="Use a full folder path, e.g. D:\\AzerothCore.")
    if root.exists() and not root.is_dir():
        raise HTTPException(status_code=422, detail=f"{root} is a file, not a folder.")
    current: Settings = request.app.state.settings
    if str(root) != current.root_dir:
        if any(s.proc for s in manager.services.values()):
            raise HTTPException(status_code=409, detail="Stop the servers started by the panel before changing the folder.")
        backup_task = getattr(request.app.state, "backup_task", None)
        if any(getattr(request.app.state, name).busy() for name in _JOB_SLOTS) or (backup_task and not backup_task.done()):
            raise HTTPException(status_code=409, detail="Wait until the running build, clone, module, data, database, "
                                                        "SQL import, backup or restore job has finished.")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't create {root}: {exc.strerror}") from exc
    new = replace(current, root_dir=str(root))
    if new.configured:
        try:
            load_server_config(new.server_path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Cannot read worldserver.conf: {exc}") from exc
    save_settings(new)
    request.app.state.settings = new
    audit.record(request, "settings.root", str(root))
    return _summary(new)


@router.put("")
def update(body: SettingsBody, request: Request):
    new = replace(request.app.state.settings, session_hours=body.session_hours, world_shutdown_delay=body.world_shutdown_delay)
    save_settings(new)
    request.app.state.settings = new
    audit.record(request, "settings.update", f"session {new.session_hours} h, world countdown {new.world_shutdown_delay} s")
    return _summary(new)


@router.post("/test")
async def test(request: Request):
    settings: Settings = request.app.state.settings
    if not settings.configured:
        raise HTTPException(status_code=409, detail="Set the AzerothCore folder first.")
    cfg = load_server_config(settings.server_path)
    results = []
    reachable = await port_open(cfg.login_db.host, cfg.login_db.port)
    results.append({"name": f"MySQL port {cfg.login_db.host}:{cfg.login_db.port}", "ok": reachable,
                    "detail": "reachable" if reachable else "not reachable (is MySQL running?)"})
    if reachable:
        for key, info in cfg.databases.items():
            try:
                version = await db.scalar(info, "SELECT VERSION()")
                results.append({"name": f"{key} database ({info.database})", "ok": True, "detail": f"MySQL {version}"})
            except db.DbError as exc:
                results.append({"name": f"{key} database ({info.database})", "ok": False, "detail": str(exc)})
    for label, path in (("worldserver.exe", settings.server_path / "worldserver.exe"),
                        ("authserver.exe", settings.server_path / "authserver.exe"),
                        ("AreaTable.dbc (zone names)", cfg.data_dir / "dbc" / "AreaTable.dbc")):
        results.append({"name": label, "ok": path.is_file(), "detail": str(path)})
    if settings.mysql_path:
        p = settings.mysql_path / "bin" / "mysqld.exe"
        results.append({"name": "mysqld.exe", "ok": p.is_file(), "detail": str(p)})
    return results


@router.put("/soap")
def update_soap(body: SoapBody, request: Request):
    current: Settings = request.app.state.settings
    username = body.username.strip()
    password = current.soap_password if body.password is None else body.password
    new = replace(current, soap_username=username, soap_password=password if username else "")
    save_settings(new)
    request.app.state.settings = new
    audit.record(request, "settings.soap", f"account '{username or '-'}'{', password changed' if body.password else ''}")
    return _summary(new)


@router.post("/soap/test")
async def test_soap(request: Request):
    settings: Settings = request.app.state.settings
    if not settings.configured:
        raise HTTPException(status_code=409, detail="Set the AzerothCore folder first.")
    cfg = load_server_config(settings.server_path)
    if not cfg.soap_enabled:
        return {"ok": False, "message": "SOAP.Enabled is 0 in worldserver.conf."}
    if not (settings.soap_username and settings.soap_password):
        return {"ok": False, "message": "Enter and save the SOAP account first."}
    try:
        ok, output = await soap.execute(cfg.soap_host, cfg.soap_port, settings.soap_username,
                                        settings.soap_password, "server info")
    except soap.SoapError as exc:
        return {"ok": False, "message": str(exc)}
    first = output.splitlines()[0] if output else "(no output)"
    return {"ok": ok, "message": f"Connected: {first}" if ok else output}


# ---- remote access (HTTPS listener for other devices) ------------------------------------

def _remote_key(s: Settings) -> tuple:
    return (s.remote_enabled, s.remote_port, s.tls_cert, s.tls_key)


def _remote(request: Request) -> dict:
    settings: Settings = request.app.state.settings
    own = bool(settings.tls_cert or settings.tls_key)
    cert_path = Path(settings.tls_cert) if own else tls.SELF_CERT
    cert, cert_error = None, None
    if cert_path.is_file():
        try:
            cert = tls.describe(cert_path)
        except ValueError as exc:
            cert_error = f"Can't read the certificate: {exc}"
    elif own:
        cert_error = "Certificate file not found."
    dns, ips = tls.host_names()
    hosts = [h for h in dns if h != "localhost" and h == h.lower()] + [i for i in ips if i != "127.0.0.1"]
    return {
        "enabled": settings.remote_enabled, "port": settings.remote_port,
        "tls_cert": settings.tls_cert, "tls_key": settings.tls_key, "own_cert": own,
        "cert": cert, "cert_error": cert_error,
        "default_password": security.default_password_in_use(),
        "active_port": getattr(request.app.state, "remote_active", None),
        "restart_required": _remote_key(settings) != getattr(request.app.state, "remote_at_start", _remote_key(settings)),
        "urls": [f"https://{h}:{settings.remote_port}" for h in hosts],
    }


@router.get("/remote")
def get_remote(request: Request):
    return _remote(request)


@router.put("/remote")
def update_remote(body: RemoteBody, request: Request):
    current: Settings = request.app.state.settings
    cert_path, key_path = body.tls_cert.strip().strip('"'), body.tls_key.strip().strip('"')
    if body.port == current.port:
        raise HTTPException(status_code=422, detail=f"Port {body.port} is the local panel port; choose another one.")
    if bool(cert_path) != bool(key_path):
        raise HTTPException(status_code=422, detail="Give both the certificate and the key file, or neither (self-signed).")
    new = replace(current, remote_enabled=body.enabled, remote_port=body.port, tls_cert=cert_path, tls_key=key_path)
    if body.enabled:
        if security.default_password_in_use():
            raise HTTPException(status_code=409, detail="Change the default admin password before allowing remote access.")
        try:
            cert, key = tls.paths(new)      # creates the self-signed pair when needed
            tls.validate(cert, key)
        except tls.TlsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    save_settings(new)
    request.app.state.settings = new
    audit.record(request, "settings.remote",
                 f"{'enabled' if new.remote_enabled else 'disabled'}, port {new.remote_port}, "
                 f"{'own certificate' if cert_path else 'self-signed certificate'}")
    return _remote(request)


@router.post("/remote/regenerate")
def regenerate_certificate(request: Request):
    settings: Settings = request.app.state.settings
    if settings.tls_cert or settings.tls_key:
        raise HTTPException(status_code=409, detail="An own certificate is configured; nothing to regenerate.")
    tls.generate_self_signed()
    audit.record(request, "settings.remote", "self-signed certificate regenerated")
    return _remote(request)
