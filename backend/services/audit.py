"""Panel action log: who did what, when, from which address (data/audit.log).

One line per action, readable in the Logs page ("Panel Actions" tab):
  2026-10-11 20:15:03 INFO  admin@192.168.1.20 server.stop Worldserver (countdown 10 s)
The level word (INFO / WARN / ERROR) is what the Logs level filter matches.
The file rotates to audit.log.1 at 5 MB.
"""
from __future__ import annotations

import os
import threading
import time

from fastapi import Request

from .. import security
from ..paths import AUDIT_FILE, ensure_dirs

MAX_BYTES = 5 * 1024 * 1024
_lock = threading.Lock()


def _clean(text: str) -> str:
    return " ".join(str(text).split())[:500]


def write(action: str, detail: str = "", level: str = "INFO", who: str = "-", ip: str = "-") -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {level:<5} {who}@{ip} {action}"
    if detail:
        line += " " + _clean(detail)
    with _lock:
        ensure_dirs()
        if AUDIT_FILE.is_file() and AUDIT_FILE.stat().st_size > MAX_BYTES:
            os.replace(AUDIT_FILE, AUDIT_FILE.with_name(AUDIT_FILE.name + ".1"))
        with AUDIT_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def record(request: Request, action: str, detail: str = "", level: str = "INFO", who: str | None = None) -> None:
    """Log an action done through the panel (by the signed-in admin unless `who` is given)."""
    ip = request.client.host if request.client else "-"
    if who is None:
        who = security.username() if security.session_valid(request.cookies.get(security.SESSION_COOKIE)) else "-"
    write(action, detail, level, _clean(who) or "-", ip)
