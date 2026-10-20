"""Sidebar shortcuts: list, save and launch (services/shortcuts.py)."""
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import security
from ..services import audit, shortcuts
from ..settings import Settings, save_settings

router = APIRouter(prefix="/api/shortcuts", tags=["shortcuts"], dependencies=[Depends(security.require_session)])


class SaveBody(BaseModel):
    items: list[dict]


def _state(settings: Settings) -> dict:
    return {"items": settings.shortcuts, "suggestions": shortcuts.suggestions(settings)}


@router.get("")
def get_shortcuts(request: Request):
    return _state(request.app.state.settings)


@router.put("")
def save_shortcuts(body: SaveBody, request: Request):
    try:
        items = shortcuts.validate(body.items)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    new = replace(request.app.state.settings, shortcuts=items)
    save_settings(new)
    request.app.state.settings = new
    audit.record(request, "shortcuts.update", ", ".join(f"{s['name']} = {s['path']}" for s in items) or "none")
    return _state(new)


@router.post("/{sid}/launch")
def launch_shortcut(sid: str, request: Request):
    """Launches a saved shortcut; the request names it by id only, never by path."""
    item = shortcuts.find(request.app.state.settings, sid)
    if item is None:
        raise HTTPException(status_code=404, detail="That shortcut doesn't exist any more.")
    try:
        shortcuts.launch(item)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't start {item['name']}: {exc.strerror or exc}") from exc
    audit.record(request, "shortcuts.launch", f"{item['name']} ({item['path']})")
    return {"ok": True}
