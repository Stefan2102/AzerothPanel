"""Get the AzerothCore source: git clone of the official repository, the playerbots fork, or any URL.

The playerbots fork needs the mod-playerbots module, so that preset clones it into modules/ too.
After a successful clone the folder becomes the panel's source folder (Compilation uses it).
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable

from ..paths import DATA_DIR
from .jobs import JobError, JobStore, LogFn, ProcessRunner, git_progress
from .modules import remove_tree

PRESETS = [
    {"key": "official", "label": "AzerothCore (official)", "url": "https://github.com/azerothcore/azerothcore-wotlk.git",
     "branch": "master", "modules": []},
    {"key": "playerbots", "label": "AzerothCore + Playerbots", "url": "https://github.com/mod-playerbots/azerothcore-wotlk.git",
     "branch": "Playerbot", "modules": [{"name": "mod-playerbots", "url": "https://github.com/mod-playerbots/mod-playerbots.git", "branch": "master"}]},
]
_URL = re.compile(r"^https://[^\s/]+/\S+$")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,100}$")
_ENV = {"GIT_TERMINAL_PROMPT": "0"}      # never wait for a password prompt


def new_store() -> JobStore:
    return JobStore(DATA_DIR / "clone.json", max_jobs=30, max_log_lines=2000, log_dir=DATA_DIR / "clone-logs")


def check_url(url: str) -> str:
    url = url.strip()
    if not _URL.match(url):
        raise JobError("Use an https git URL, e.g. https://github.com/azerothcore/azerothcore-wotlk.git")
    return url


def check_branch(branch: str) -> str:
    branch = branch.strip()
    if not _BRANCH.match(branch) or branch.startswith(("-", "/")) or ".." in branch:
        raise JobError("That is not a valid branch name.")
    return branch


def check_target(folder: str) -> Path:
    path = Path(folder.strip().strip('"'))
    if not path.is_absolute():
        raise JobError("Use a full folder path, e.g. D:\\AzerothCore\\source.")
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise JobError(f"{path} already has files. To clone again, delete or rename that folder first.")
    return path


def remote_branches(git: str, url: str) -> dict:
    """{"default": name|None, "branches": [...]} without downloading the repository (git ls-remote)."""
    try:
        proc = subprocess.run([git, "ls-remote", "--symref", url, "HEAD", "refs/heads/*"], capture_output=True, timeout=45,
                              env={**os.environ, **_ENV}, creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise JobError("The repository didn't answer within 45 seconds.") from exc
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip().splitlines()
        raise JobError(f"Couldn't read that repository: {msg[-1] if msg else 'unknown error'}")
    out = proc.stdout.decode(errors="replace")
    m = re.search(r"^ref: refs/heads/(\S+)\s+HEAD", out, re.M)
    branches = sorted(set(re.findall(r"\trefs/heads/(\S+)$", out, re.M)), key=str.lower)
    return {"default": m.group(1) if m else None, "branches": branches}


class CloneJob:
    def __init__(self, git: Path, url: str, branch: str, target: Path, modules: list[dict],
                 log: LogFn, progress: Callable[[dict], None]) -> None:
        self.git, self.url, self.branch, self.target, self.modules = git, url, branch, target, modules
        self.log, self._progress = log, progress
        self.runner = ProcessRunner()
        self.state = {"step": None, "progress": 0, "detail": None}

    def cancel(self) -> None:
        self.runner.cancel()

    def _set(self, **fields) -> None:
        self.state.update(fields)
        self._progress(dict(self.state))

    def _clone(self, url: str, branch: str, target: Path, step: str) -> None:
        args = ["clone", "--progress", "--branch", branch, url, str(target)]
        self.log("> git " + " ".join(args))
        last = [0.0]

        def on_progress(text: str) -> None:
            p = git_progress(text)
            if p and time.monotonic() - last[0] > 0.5:
                last[0] = time.monotonic()
                self._set(detail=p[2], progress=p[1] if step == "source" else self.state["progress"])

        code = self.runner.run([str(self.git), *args], None, lambda line: self.log("  " + line),
                               {**os.environ, **_ENV}, on_progress=on_progress)
        if code != 0:
            raise JobError(f"git clone failed (exit code {code}). The log says why.")

    def run_sync(self) -> dict:
        started = time.monotonic()
        try:
            self._set(step="source", progress=0)
            self.log(f"[step] Cloning {self.url} ({self.branch}) into {self.target}")
            self._clone(self.url, self.branch, self.target, "source")
            for mod in self.modules:
                self._set(step="modules", progress=95, detail=None)
                self.log(f"[step] Installing {mod['name']} (needed by this repository)")
                self._clone(mod["url"], mod["branch"], self.target / "modules" / mod["name"], "modules")
        except BaseException:
            # The folder was new or empty before (check_target), so everything in it is this clone's partial copy.
            if self.target.exists():
                remove_tree(self.target)
                self.log(f"  Removed the partial copy in {self.target}.")
            raise
        self._set(step="done", progress=100, detail=None)
        self.log(f"[done] Source ready in {self.target}. It is now the source folder on the Compilation page.")
        return {"duration": round(time.monotonic() - started)}
