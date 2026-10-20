"""State of the AzerothCore source tree: git revision and the modules folder (read-only)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def git(git_exe: str, repo: Path, *args: str, timeout: float = 15) -> str | None:
    """Output of a read-only git command, or None if it failed."""
    try:
        proc = subprocess.run([git_exe, "-C", str(repo), *args], capture_output=True, timeout=timeout,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout.decode("utf-8", errors="replace").strip() if proc.returncode == 0 else None


def revision(git_exe: str | None, repo: Path) -> dict:
    if not git_exe or not (repo / ".git").exists():
        return {"git": False}
    branch = git(git_exe, repo, "rev-parse", "--abbrev-ref", "HEAD")
    last = git(git_exe, repo, "log", "-1", "--format=%h%x00%cI%x00%s")
    commit, date, subject = (last.split("\0", 2) if last else (None, None, None))
    changes = git(git_exe, repo, "status", "--porcelain", "--untracked-files=no")
    return {
        "git": True, "branch": branch, "commit": commit, "date": date, "subject": subject,
        "remote": git(git_exe, repo, "config", "--get", "remote.origin.url"),
        "dirty": bool(changes) if changes is not None else None,
    }


def modules(source: Path, git_exe: str | None) -> list[dict]:
    """Folders in <source>/modules. A junction or symlink whose target is gone is reported as broken."""
    folder = source / "modules"
    out = []
    if not folder.is_dir():
        return out
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        link = entry.is_junction() or entry.is_symlink()
        if not (entry.is_dir() or link) or entry.name.startswith("."):
            continue
        item = {"name": entry.name, "link": None, "broken": False, "git": False}
        if link:
            item["link"] = os.readlink(entry).removeprefix("\\\\?\\")
            item["broken"] = not entry.exists()
        if not item["broken"]:
            item.update(revision(git_exe, entry))
        out.append(item)
    return out
