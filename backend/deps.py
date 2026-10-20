"""Shared FastAPI dependencies."""
from __future__ import annotations

from fastapi import HTTPException, Request

from .acconf import ServerConfig, load_server_config
from .services.server_manager import ServerManager
from .settings import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_manager(request: Request) -> ServerManager:
    return request.app.state.manager


def get_config(request: Request) -> ServerConfig:
    settings: Settings = request.app.state.settings
    if not settings.configured:
        raise HTTPException(status_code=409, detail="AzerothCore isn't set up yet: choose the AzerothCore folder and build and deploy it (Setup, Compilation).")
    try:
        return load_server_config(settings.server_path)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
