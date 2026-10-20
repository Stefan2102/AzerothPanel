"""Config editor for worldserver.conf, authserver.conf and configs/modules/*.conf.

Saving refuses to overwrite a file that changed on disk since it was loaded (hash check).
"""
import hashlib
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..acconf import ServerConfig
from ..deps import get_config, get_manager
from ..services import audit
from ..services.server_manager import ServerManager

router = APIRouter(prefix="/api/configs", tags=["configs"], dependencies=[Depends(security.require_session)])


class SaveBody(BaseModel):
    content: str = Field(max_length=5_000_000)
    base_hash: str


def _files(cfg: ServerConfig) -> dict[str, tuple[Path, str]]:
    """id -> (path, service that reads it)."""
    files = {"worldserver.conf": (cfg.world_conf, "world"), "authserver.conf": (cfg.auth_conf, "auth")}
    modules = cfg.configs_dir / "modules"
    if modules.is_dir():
        for p in sorted(modules.glob("*.conf")):
            files[f"modules/{p.name}"] = (p, "world")
    return {k: v for k, v in files.items() if v[0].is_file()}


def _lookup(cfg: ServerConfig, file_id: str) -> tuple[Path, str]:
    entry = _files(cfg).get(file_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Config file not found.")
    return entry


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _restart_required(path: Path, service: str, manager: ServerManager) -> bool:
    started = manager.services[service].started_at
    return started is not None and path.stat().st_mtime > started


@router.get("")
def list_configs(cfg: ServerConfig = Depends(get_config), manager: ServerManager = Depends(get_manager)):
    return [
        {"id": fid, "group": "modules" if fid.startswith("modules/") else "core", "service": svc,
         "size": path.stat().st_size, "modified": path.stat().st_mtime,
         "restart_required": _restart_required(path, svc, manager)}
        for fid, (path, svc) in _files(cfg).items()
    ]


@router.get("/{file_id:path}")
def read_config(file_id: str, cfg: ServerConfig = Depends(get_config), manager: ServerManager = Depends(get_manager)):
    path, svc = _lookup(cfg, file_id)
    data = path.read_bytes()
    return {"id": file_id, "content": data.decode("utf-8", errors="replace"), "hash": _hash(data),
            "service": svc, "restart_required": _restart_required(path, svc, manager)}


@router.put("/{file_id:path}")
def save_config(file_id: str, body: SaveBody, request: Request, cfg: ServerConfig = Depends(get_config),
                manager: ServerManager = Depends(get_manager)):
    path, svc = _lookup(cfg, file_id)
    current = path.read_bytes()
    if _hash(current) != body.base_hash:
        raise HTTPException(status_code=409, detail="The file changed on disk since you opened it. Reload it first.")
    # Keep the file's existing line endings (AzerothCore ships CRLF on Windows).
    new_text = body.content.replace("\r\n", "\n")
    if b"\r\n" in current:
        new_text = new_text.replace("\n", "\r\n")
    data = new_text.encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    audit.record(request, "config.save", file_id)
    return {"hash": _hash(data), "restart_required": _restart_required(path, svc, manager)}
