"""Sidebar shortcuts: programs the user launches from the panel (WoW client, Ollama, any tool).

A launch is the same as a double-click in Explorer (ShellExecute through os.startfile). The program
gets its own process and console, shares nothing with the panel and is never watched, stopped or
restarted by it, so shutting the panel down leaves it running.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from ..settings import Settings

ALLOWED_EXT = (".exe", ".bat", ".cmd", ".lnk")
MAX_ITEMS = 20
MAX_NAME = 40
MAX_ARGS = 300


def _clean_path(value: str) -> str:
    return str(value or "").strip().strip('"')


def validate(items: list[dict]) -> list[dict]:
    """Checked, normalised shortcuts in the given order. Raises ValueError with a message for the user."""
    if len(items) > MAX_ITEMS:
        raise ValueError(f"At most {MAX_ITEMS} shortcuts.")
    out: list[dict] = []
    ids: set[str] = set()
    for item in items:
        name = str(item.get("name") or "").strip()
        label = name or "A shortcut"
        if not name or len(name) > MAX_NAME:
            raise ValueError(f"Shortcut names need 1-{MAX_NAME} characters.")
        path = Path(_clean_path(item.get("path")))
        if not path.is_absolute() or not path.drive:
            raise ValueError(f"{label}: use a full file path, e.g. D:\\Games\\WoW\\Wow.exe.")
        if path.is_dir():
            raise ValueError(f"{label}: {path} is a folder; choose the program file in it.")
        if path.suffix.lower() not in ALLOWED_EXT:
            raise ValueError(f"{label}: only {', '.join(ALLOWED_EXT)} files can be launched.")
        if not path.is_file():
            raise ValueError(f"{label}: {path} does not exist.")
        args = str(item.get("args") or "").strip()
        if len(args) > MAX_ARGS or "\n" in args or "\r" in args:
            raise ValueError(f"{label}: arguments must be one line of at most {MAX_ARGS} characters.")
        sid = str(item.get("id") or "")
        if not sid.isalnum() or len(sid) > 16 or sid in ids:
            sid = uuid.uuid4().hex[:8]
        ids.add(sid)
        out.append({"id": sid, "name": name, "path": str(path), "args": args})
    return out


def find(settings: Settings, sid: str) -> dict | None:
    return next((s for s in settings.shortcuts if s.get("id") == sid), None)


def launch(item: dict) -> None:
    """Start a stored shortcut like a double-click, in the file's own folder. Raises ValueError / OSError."""
    path = Path(item["path"])
    if not path.is_file():
        raise ValueError(f"{path} does not exist any more.")
    os.startfile(str(path), arguments=item.get("args") or "", cwd=str(path.parent))


def suggestions(settings: Settings) -> list[dict]:
    """Ready-made entries for programs on this PC that aren't added yet. A path may be a folder
    (the WoW client folder without a Wow.exe, e.g. a patched client): the user picks the file in it."""
    found = []
    if settings.client_dir and Path(settings.client_dir).is_dir():
        wow = Path(settings.client_dir) / "Wow.exe"
        found.append({"name": "World of Warcraft", "path": str(wow if wow.is_file() else Path(settings.client_dir))})
    if local := os.environ.get("LOCALAPPDATA"):
        ollama = Path(local) / "Programs" / "Ollama" / "ollama.exe"
        if ollama.is_file():
            found.append({"name": "Ollama", "path": str(ollama), "args": "serve"})
    added_paths = [os.path.normcase(s.get("path", "")) for s in settings.shortcuts]
    added_names = {s.get("name", "").lower() for s in settings.shortcuts}
    return [{"args": "", **s} for s in found
            if s["name"].lower() not in added_names
            and not any(p == os.path.normcase(s["path"]) or p.startswith(os.path.normcase(s["path"]) + os.sep)
                        for p in added_paths)]
