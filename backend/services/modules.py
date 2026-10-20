"""Modules: the AzerothCore catalogue and the modules installed in <source>/modules.

Catalogue: the file the official catalogue page (azerothcore.org/catalogue.html) is built from,
data/catalogue.json, regenerated daily from the GitHub topics azerothcore-module / -tools / -lua / -sql.
Using it means no GitHub API rate limit and no token. It is cached in data/ for an hour.

Installed modules are git checkouts; install = git clone, update = git pull --ff-only, remove =
delete the folder (a junction is only unlinked). After any change the core must be rebuilt;
module SQL is applied by AzerothCore's own DB updater when worldserver starts.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

from ..paths import DATA_DIR
from . import source as source_info
from .jobs import JobError, JobStore, LogFn, ProcessRunner, git_progress

CATALOGUE_URL = "https://www.azerothcore.org/data/catalogue.json"
CACHE_FILE = DATA_DIR / "catalogue-cache.json"
CACHE_SECONDS = 3600
CATEGORIES = {"modules": "azerothcore-module", "tools": "azerothcore-tools",
              "lua": "azerothcore-lua", "sql": "azerothcore-sql"}
_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_GITHUB = re.compile(r"github\.com[/:]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", re.I)
_lock = threading.Lock()


def new_store() -> JobStore:
    return JobStore(DATA_DIR / "modules.json", max_jobs=100, max_log_lines=2000, log_dir=DATA_DIR / "modules-logs")


# ---- catalogue -----------------------------------------------------------------------------------------

def _item(raw: dict) -> dict:
    owner = raw.get("owner") or {}
    return {
        "id": raw.get("id"), "name": raw.get("name"), "full_name": raw.get("full_name"),
        "description": raw.get("description") or "", "stars": raw.get("stargazers_count") or 0,
        "forks": raw.get("forks_count") or 0, "created": raw.get("created_at"),
        "pushed": raw.get("pushed_at") or raw.get("updated_at"), "url": raw.get("html_url"),
        "owner": owner.get("login"), "avatar": owner.get("avatar_url"), "branch": raw.get("default_branch"),
        "topics": raw.get("topics") or [],
    }


def catalogue(refresh: bool = False) -> dict:
    """{"fetched": ts, "categories": {key: [items]}}; served from the cache unless it is old or refresh=True."""
    with _lock:
        if not refresh and CACHE_FILE.is_file() and time.time() - CACHE_FILE.stat().st_mtime < CACHE_SECONDS:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        try:
            req = urllib.request.Request(CATALOGUE_URL, headers={"User-Agent": "AzerothPanel"})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = json.loads(r.read())
        except (OSError, ValueError) as exc:
            if CACHE_FILE.is_file():          # offline: keep showing the last copy
                data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                data["stale"] = str(exc)
                return data
            raise JobError(f"Couldn't load the AzerothCore catalogue ({exc}).") from exc
        org = next(iter((raw.get("organizations") or {}).values()), {})
        data = {"fetched": time.time(),
                "categories": {key: [_item(i) for i in org.get(topic, [])] for key, topic in CATEGORIES.items()}}
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, CACHE_FILE)
        return data


def repo_key(url: str | None) -> str | None:
    """'owner/repo' (lower case) from a GitHub URL, to match installed modules with catalogue entries."""
    m = _GITHUB.search(url or "")
    return f"{m.group(1)}/{m.group(2)}".lower() if m else None


# ---- installed --------------------------------------------------------------------------------------------

def installed(source: Path, git: str | None) -> list[dict]:
    out = source_info.modules(source, git)
    for m in out:
        m["repo"] = repo_key(m.get("remote"))
    return out


def name_from_url(url: str) -> str:
    """Folder name for a module cloned from an https git URL (its last path part, without .git)."""
    if not re.match(r"^https://[^\s/]+/\S+$", url):
        raise JobError("Use an https git URL, e.g. https://github.com/owner/mod-name.git")
    name = url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    if not _NAME.match(name) or name.startswith("."):
        raise JobError("Couldn't take a folder name from that URL.")
    return name


def module_dir(source: Path, name: str) -> Path:
    if not _NAME.match(name) or name.startswith("."):
        raise JobError("Invalid module name.")
    return source / "modules" / name


def remove_tree(path: Path) -> None:
    """Delete a folder; git object files are read-only on Windows, so clear that flag first."""
    def onexc(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onexc=onexc)


# ---- jobs ----------------------------------------------------------------------------------------------

class ModuleJob:
    """install / update / update-all / remove; `changed` tells whether a rebuild is needed."""

    def __init__(self, kind: str, git: Path | None, source: Path, log: LogFn,
                 progress: Callable[[dict], None], name: str | None = None, url: str | None = None) -> None:
        self.kind, self.git, self.source, self.name, self.url = kind, git, source, name, url
        self.log, self._progress = log, progress
        self.runner = ProcessRunner()

    def cancel(self) -> None:
        self.runner.cancel()

    def _git(self, *args: str, cwd: Path | None = None, progress: bool = False) -> int:
        """Run git. With progress, git's --progress meter (clone, pull) is shown as the job's progress."""
        if self.git is None:
            raise JobError("Git was not found. See Setup -> Requirements.")
        cmd = [str(self.git), *args]
        self.log("> git " + " ".join(args))
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}          # never wait for a password prompt
        last = [0.0]

        def on_progress(text: str) -> None:
            p = git_progress(text)
            if p and time.monotonic() - last[0] > 0.5:
                last[0] = time.monotonic()
                self._progress({"step": self.kind, "progress": p[1], "detail": p[2]})

        return self.runner.run(cmd, cwd, self.log, env, on_progress=on_progress if progress else None)

    def _head(self, folder: Path) -> str | None:
        return source_info.git(str(self.git), folder, "rev-parse", "HEAD") if self.git else None

    def _install(self) -> bool:
        target = module_dir(self.source, self.name or "")
        if target.exists() or target.is_junction():
            raise JobError(f"modules\\{target.name} already exists.")
        self.log(f"[step] Installing {self.name} from {self.url}")
        try:
            code = self._git("clone", "--progress", "--recursive", self.url or "", str(target), progress=True)
        except BaseException:                       # cancelled: don't leave a half-cloned module behind
            self._remove_partial(target)
            raise
        if code != 0:
            self._remove_partial(target)
            raise JobError("git clone failed. The log says why.")
        if not (target / "src").is_dir():
            self.log("[WARN] This repository has no src folder; it may not be an AzerothCore module.")
        return True

    def _remove_partial(self, target: Path) -> None:
        """Remove what an unfinished clone left; it was new (install refuses an existing folder)."""
        if not target.exists():
            return
        for _ in range(10):                         # git's killed processes may still hold files for a moment
            try:
                remove_tree(target)
                self.log(f"  Removed the unfinished modules\\{target.name}.")
                return
            except OSError:
                time.sleep(0.5)
        self.log(f"[WARN] Couldn't remove the unfinished modules\\{target.name}; delete that folder before installing again.")

    def _update_one(self, folder: Path) -> bool:
        before = self._head(folder)
        if self._git("-C", str(folder), "pull", "--progress", "--ff-only", progress=self.kind == "update") != 0:
            raise JobError(f"git pull failed for {folder.name} (local changes or a diverged branch). Nothing was changed.")
        self._git("-C", str(folder), "submodule", "update", "--init", "--recursive")
        after = self._head(folder)
        if before != after:
            out = source_info.git(str(self.git), folder, "log", "--oneline", f"{before}..{after}") or ""
            lines = out.splitlines()
            self.log(f"  {len(lines)} new commit(s):")
            for line in lines[:100]:
                self.log(f"  {line}")
            return True
        self.log("  Already up to date.")
        return False

    def _remove(self) -> bool:
        target = module_dir(self.source, self.name or "")
        self.log(f"[step] Removing modules\\{target.name}")
        if target.is_junction() or target.is_symlink():
            target.unlink() if target.is_symlink() else os.rmdir(target)     # only the link, never its target
            self.log("  Removed the link (its target folder was not touched).")
        elif target.is_dir():
            remove_tree(target)
        else:
            raise JobError(f"modules\\{target.name} does not exist.")
        self.log("  Its settings in the server's configs\\modules folder stay; after a rebuild worldserver no longer reads them.")
        return True

    def run_sync(self) -> dict:
        started = time.monotonic()
        failed: list[str] = []
        self._progress({"step": self.kind, "progress": 0})
        if self.kind == "install":
            changed = self._install()
        elif self.kind == "remove":
            changed = self._remove()
        elif self.kind == "update":
            self.log(f"[step] Updating {self.name}")
            changed = self._update_one(module_dir(self.source, self.name or ""))
        else:                                                         # update-all
            changed = False
            folders = [m for m in installed(self.source, None) if not m["broken"] and m["git"]]
            for i, m in enumerate(folders):
                self.log(f"[step] Updating {m['name']}")
                try:
                    changed = self._update_one(self.source / "modules" / m["name"]) or changed
                except JobError as exc:
                    self.runner.check()
                    failed.append(m["name"])
                    self.log(f"[ERROR] {exc}")
                self._progress({"step": self.kind, "progress": int((i + 1) * 100 / len(folders))})
        self._progress({"step": "done", "progress": 100})
        if failed:
            self.log(f"[WARN] Not updated: {', '.join(failed)} (see above). The others were updated.")
        self.log("[done] " + ("Rebuild the server on the Compilation page to use the change." if changed else "Nothing changed."))
        return {"changed": changed, "failed": failed, "duration": round(time.monotonic() - started)}


def compiled_modules(build_dir: Path | None) -> set[str] | None:
    """Modules the build folder was last configured with: CMake generates one Add<module>Scripts()
    call per module into modules/gen_scriptloader/<static|dynamic>/ModulesLoader.cpp ('-' becomes '_')."""
    if not build_dir:
        return None
    loaders = list((build_dir / "modules" / "gen_scriptloader").glob("*/ModulesLoader.cpp"))
    if not loaders:
        return None
    names: set[str] = set()
    for f in loaders:
        names |= set(re.findall(r"^\s*void\s+Add(\w+)Scripts\(\);", f.read_text(encoding="utf-8", errors="replace"), re.M))
    return names


def rebuild_needed(current: list[dict], build_store: JobStore, build_dir: Path | None) -> bool:
    """Do the modules in the source differ from what the last build compiled?

    Builds made by the panel record each module's folder and commit, so an update counts too.
    For a build folder configured outside the panel, the module names from its generated
    ModulesLoader.cpp are compared. Installing and removing the same module needs no rebuild."""
    now = {m["name"]: m.get("commit") for m in current if not m["broken"]}
    builds = [j for j in build_store.jobs() if j["status"] == "completed" and j.get("type") == "build" and "modules" in j]
    if builds:
        return now != max(builds, key=lambda j: j["finished"])["modules"]
    compiled = compiled_modules(build_dir)
    if compiled is None:
        return False                     # never built: nothing to compare with
    return {n.replace("-", "_") for n in now} != compiled
