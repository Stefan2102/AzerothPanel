"""Folder browser for path fields (the browser can't open the PC's own folder dialog).

Lists the user's main folders (Desktop, Documents ...), drives, folders and optionally files of the PC the panel runs on. Signed-in admins only;
it reads names only, never file contents. Creating a folder is the one change it can make.
"""
import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import security
from ..services import audit

router = APIRouter(prefix="/api/fs", tags=["fs"], dependencies=[Depends(security.require_session)])
MAX_ENTRIES = 2000
# Windows known folders, so a Desktop moved to OneDrive or another drive is still found.
KNOWN_FOLDERS = (
    ("Home", "home", "5E6C858F-0E22-4760-9AFE-EA3317B67173"),
    ("Desktop", "desktop", "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"),
    ("Documents", "documents", "FDD39AD0-238F-46AF-ADB4-6C85480369C7"),
    ("Downloads", "downloads", "374DE290-123F-4565-9164-39C4925E467B"),
)


class NewFolder(BaseModel):
    parent: str = Field(min_length=2, max_length=400)
    name: str = Field(min_length=1, max_length=120)


def _drives() -> list[dict]:
    return [{"name": d.rstrip("\\"), "path": d, "dir": True, "kind": "drive"} for d in os.listdrives()]


def _known_folder(guid: str) -> str | None:
    fid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(guid).bytes_le)
    out = wintypes.LPWSTR()
    try:
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(out)) != 0:
            return None
        return out.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def _places() -> list[dict]:
    """The signed-in Windows user's home, Desktop, Documents and Downloads folders that exist."""
    places = []
    for name, kind, guid in KNOWN_FOLDERS:
        path = _known_folder(guid)
        if path and os.path.isdir(path):
            places.append({"name": name, "path": path, "dir": True, "kind": kind})
    return places


@router.get("/list")
def list_folder(path: str = "", files: bool = False, ext: str = ""):
    """Folders (and with files=true, files with one of the extensions in `ext`, e.g. ".exe") of `path`.
    An empty path lists the drives."""
    places, drives = _places(), _drives()
    if not path.strip():
        return {"path": "", "parent": None, "entries": places + drives, "drives": drives, "places": places}
    folder = Path(path.strip().strip('"'))
    if not folder.is_absolute() or not folder.is_dir():
        raise HTTPException(status_code=404, detail=f"{folder} is not a folder.")
    exts = {e.strip().lower() for e in ext.split(",") if e.strip()}
    entries = []
    try:
        for entry in os.scandir(folder):
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if entry.name.startswith(("$", ".")) and is_dir:
                continue                      # $Recycle.Bin, .git ...: never what you're looking for
            if is_dir or (files and (not exts or os.path.splitext(entry.name)[1].lower() in exts)):
                entries.append({"name": entry.name, "path": entry.path, "dir": is_dir})
            if len(entries) >= MAX_ENTRIES:
                break
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=f"No access to {folder}.") from exc
    entries.sort(key=lambda e: (not e["dir"], e["name"].lower()))
    parent = folder.parent if folder.parent != folder else None
    return {"path": str(folder), "parent": str(parent) if parent else "", "entries": entries, "drives": drives, "places": places}


@router.post("/mkdir")
def make_folder(body: NewFolder, request: Request):
    name = body.name.strip()
    if name in (".", "..") or any(c in name for c in '<>:"/\\|?*'):
        raise HTTPException(status_code=422, detail="That is not a valid folder name.")
    parent = Path(body.parent.strip().strip('"'))
    if not parent.is_absolute() or not parent.is_dir():
        raise HTTPException(status_code=404, detail=f"{parent} is not a folder.")
    target = parent / name
    try:
        target.mkdir()
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=f"{target} already exists.") from exc
    except OSError as exc:
        raise HTTPException(status_code=403, detail=f"Couldn't create {target}: {exc.strerror}") from exc
    audit.record(request, "fs.mkdir", str(target))
    return {"path": str(target)}
