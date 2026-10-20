"""Log sources (worldserver, authserver, GM commands, DB errors): resolution, paging and live follow.

Which file a source lives in is read from the AzerothCore logging config, not hardcoded:
  Logger.<name>=<level>,<appender> <appender>...
  Appender.<name>=<type>,<level>,<flags>,<file>[,<mode>]   (type 2 = file)
A file name may contain "%s", which AzerothCore replaces with a timestamp.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..acconf import ServerConfig, read_conf
from ..paths import AUDIT_FILE

BLOCK = 64 * 1024
APPENDER_FILE = "2"


@dataclass(frozen=True)
class LogSource:
    key: str
    label: str
    service: str        # "world" or "auth": whose config defines the logger
    logger: str
    hint: str           # shown when the logger has no file appender


SOURCES = (
    LogSource("worldserver", "Worldserver", "world", "root", "Logger.root in worldserver.conf has no file appender."),
    LogSource("authserver", "Authserver", "auth", "root", "Logger.root in authserver.conf has no file appender."),
    LogSource("gm", "GM Commands", "world", "commands.gm",
              "GM command logging is off. Enable Appender.GM and Logger.commands.gm in worldserver.conf, then restart the worldserver."),
    LogSource("db_errors", "DB Errors", "world", "sql.sql", "Logger.sql.sql in worldserver.conf has no file appender."),
    # Not an AzerothCore log: the panel's own action log (services/audit.py).
    LogSource("panel", "Panel Actions", "panel", "", "No panel actions recorded yet."),
)
_BY_KEY = {s.key: s for s in SOURCES}


def _logger_file(conf: dict[str, str], logger: str) -> str | None:
    """File name of the first file appender a logger writes to (None if it has none)."""
    value = conf.get(f"Logger.{logger}")
    if not value or "," not in value:
        return None
    for name in value.split(",", 1)[1].split():
        parts = [p.strip().strip('"') for p in conf.get(f"Appender.{name}", "").split(",")]
        if len(parts) >= 4 and parts[0] == APPENDER_FILE and parts[3]:
            return parts[3]
    return None


def _locate(source: LogSource, cfg: ServerConfig) -> tuple[Path | None, str | None]:
    """Return (path, reason). path is None when the source is not configured or has no file yet."""
    if source.service == "panel":
        return (AUDIT_FILE, None) if AUDIT_FILE.is_file() else (None, source.hint)
    conf = read_conf(cfg.world_conf if source.service == "world" else cfg.auth_conf)
    name = _logger_file(conf, source.logger)
    if name is None:
        return None, source.hint
    folder = cfg.logs_dir if source.service == "world" else cfg.auth_logs_dir
    if "%s" in name:   # timestamped file: newest match
        matches = sorted(folder.glob(name.replace("%s", "*")), key=lambda p: p.stat().st_mtime)
        if not matches:
            return None, f"No {name} file yet. It appears once the server writes to it."
        return matches[-1], None
    path = folder / name
    return (path, None) if path.is_file() else (None, f"{name} does not exist yet. It appears once the server writes to it.")


def list_sources(cfg: ServerConfig) -> list[dict]:
    out = []
    for s in SOURCES:
        path, reason = _locate(s, cfg)
        out.append({
            "key": s.key, "label": s.label, "available": path is not None, "reason": reason,
            "file": path.name if path else None, "size": path.stat().st_size if path else 0,
        })
    return out


def resolve_source(cfg: ServerConfig, key: str) -> Path:
    """Map a source key to its file; the client never supplies a path."""
    source = _BY_KEY.get(key)
    if source is None:
        raise FileNotFoundError(key)
    path, _ = _locate(source, cfg)
    if path is None:
        raise FileNotFoundError(key)
    return path


def read_page(path: Path, before: int | None, max_lines: int) -> dict:
    """Return up to max_lines complete lines that end at byte offset `before` (default: end of file)."""
    with path.open("rb") as f:
        size = f.seek(0, os.SEEK_END)
        end = size if before is None else max(0, min(before, size))
        pos = end
        data = b""
        while pos > 0 and data.count(b"\n") <= max_lines:
            step = min(BLOCK, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
        lines = data.split(b"\n")
        if pos > 0:                      # first piece is a partial line; it belongs to the next page
            pos += len(lines[0]) + 1
            lines = lines[1:]
        if lines and lines[-1] == b"":
            lines = lines[:-1]
        if len(lines) > max_lines:
            drop = lines[:-max_lines]
            pos += sum(len(x) + 1 for x in drop)
            lines = lines[-max_lines:]
    return {
        "lines": [ln.decode("utf-8", errors="replace").rstrip("\r") for ln in lines],
        "start": pos,
        "end": end,
        "size": size,
    }


class Follower:
    """Incremental reader used by the live-tail websocket."""

    def __init__(self, path: Path, offset: int):
        self.path = path
        self.offset = offset
        self._partial = b""

    def poll(self) -> tuple[bool, list[str]]:
        """Returns (truncated, new_lines). Truncation happens when the server restarts
        and reopens its log with mode 'w'."""
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return False, []
        truncated = size < self.offset
        if truncated:
            self.offset, self._partial = 0, b""
        if size == self.offset:
            return truncated, []
        with self.path.open("rb") as f:
            f.seek(self.offset)
            chunk = f.read(min(size - self.offset, 4 * 1024 * 1024))
        self.offset += len(chunk)
        data = self._partial + chunk
        parts = data.split(b"\n")
        self._partial = parts.pop()
        return truncated, [p.decode("utf-8", errors="replace").rstrip("\r") for p in parts]

    @property
    def resume_offset(self) -> int:
        """Where a reconnecting client continues: the start of the unfinished line, which hasn't been sent yet."""
        return self.offset - len(self._partial)
