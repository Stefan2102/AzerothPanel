"""Client data for the worldserver (DataDir): status, download of the pre-extracted release, and
extraction from a local WoW 3.3.5a client with the server's own extractor tools.

Folders in DataDir: dbc, maps, Cameras (map_extractor), vmaps (vmap4_extractor + vmap4_assembler),
mmaps (mmaps_generator). New data is always produced in a work folder next to DataDir and only
swapped in (folder by folder, old one removed afterwards) once everything succeeded, with the
worldserver stopped. See docs/data.md.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import zipfile
from collections import deque
from pathlib import Path
from typing import Callable

from ..paths import DATA_DIR
from . import pe
from .jobs import JobError, JobStore, LogFn, ProcessRunner

TYPES = ("dbc", "maps", "vmaps", "mmaps")            # tiles on the page; Cameras travels with dbc
REQUIRED = ("dbc", "maps", "vmaps")
RELEASES = "https://github.com/wowgaming/client-data/releases"
LATEST_API = "https://api.github.com/repos/wowgaming/client-data/releases/latest"
VERSION_FILE = "data-version"                        # same file and format as AzerothCore's own installer
CLIENT_BUILD = "3.3.5.12340"
TOOLS = ("map_extractor.exe", "vmap4_extractor.exe", "vmap4_assembler.exe", "mmaps_generator.exe")
MAP_EXTRACT_FLAGS = {"maps": 1, "dbc": 2 | 4}         # map_extractor -e: MAP(1) / DBC(2) / Camera(4)
CHUNK = 1024 * 1024


def new_store() -> JobStore:
    return JobStore(DATA_DIR / "client-data.json", max_jobs=50, max_log_lines=3000, log_dir=DATA_DIR / "client-data-logs")


# ---- status ------------------------------------------------------------------------------------------

def _count(folder: Path) -> int:
    try:
        return sum(1 for _ in folder.rglob("*") if _.is_file()) if folder.is_dir() else 0
    except OSError:
        return 0


def installed_version(data_dir: Path) -> str | None:
    f = data_dir / VERSION_FILE
    if not f.is_file():
        return None
    m = re.search(r"INSTALLED_VERSION=(\S+)", f.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def pinned_version(source: Path | None) -> str | None:
    """The client-data release the AzerothCore source asks for (apps/installer/includes/functions.sh)."""
    if not source:
        return None
    f = source / "apps" / "installer" / "includes" / "functions.sh"
    if not f.is_file():
        return None
    text = f.read_text(encoding="utf-8", errors="replace")
    block = text[text.find("inst_download_client_data"):] if "inst_download_client_data" in text else ""
    m = re.search(r"VERSION=(v[\w.]+)", block)
    return m.group(1) if m else None


def status(data_dir: Path) -> dict:
    tiles = []
    for t in TYPES:
        files = _count(data_dir / t)
        tiles.append({"key": t, "present": files > 0, "files": files, "required": t in REQUIRED})
    return {"data_dir": str(data_dir), "tiles": tiles, "installed_version": installed_version(data_dir),
            "ready": all(x["present"] for x in tiles if x["required"])}


def tools_present(server_dir: Path) -> dict[str, bool]:
    return {t: (server_dir / t).is_file() for t in TOOLS}


def check_client(path: Path) -> tuple[str | None, list[str]]:
    """(client build, problems). A 3.3.5a client has Wow.exe 3.3.5.12340 and Data\\*.MPQ."""
    problems = []
    exe = path / "Wow.exe"
    build = None
    if not exe.is_file():
        problems.append(f"No Wow.exe in {path}.")
    else:
        build = pe.version_info(exe)["version"]
        if build != f"{CLIENT_BUILD}":
            problems.append(f"Wow.exe is version {build or 'unknown'}, the server needs {CLIENT_BUILD} (3.3.5a).")
    if not any((path / "Data").glob("*.MPQ")) and not any((path / "Data").glob("*.mpq")):
        problems.append(f"No Data\\*.MPQ files in {path}.")
    return build, problems


# ---- swapping data in --------------------------------------------------------------------------------

def _work_dir(data_dir: Path, kind: str) -> Path:
    work = data_dir.parent / f".client-data-{kind}"
    _remove_work(work)              # leftover of an interrupted run (its junctions are unlinked, not followed)
    work.mkdir(parents=True)
    return work


def _move(src: Path, dst: Path, attempts: int = 20, delay: float = 0.5) -> None:
    """Rename a folder. Windows refuses while any process has a file inside it open; antivirus and
    search indexing do that briefly to freshly written files, so a refused rename is retried for ~10 s."""
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def swap_in(data_dir: Path, work: Path, folders: list[str], log: LogFn) -> None:
    """Replace data_dir/<folder> with work/<folder> for each folder; the old ones are deleted only
    after all folders were swapped. On any error every folder is put back as it was."""
    data_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved: list[tuple[Path, Path | None]] = []        # (live folder now holding new data, its old data)
    try:
        for name in folders:
            new, live = work / name, data_dir / name
            old = data_dir / f".{name}.old-{stamp}" if live.exists() else None
            if old:
                _move(live, old)
            try:
                _move(new, live)
            except OSError:
                if old:
                    _move(old, live)                     # this folder's own data back first
                raise
            moved.append((live, old))
            log(f"  ✓ {name}")
    except OSError as exc:
        for live, old in reversed(moved):
            shutil.rmtree(live, ignore_errors=True)
            if old:
                _move(old, live)
        raise JobError(f"Couldn't replace the data folders ({exc}). Nothing was changed; is a file in use?") from exc
    for _, old in moved:
        if old:
            shutil.rmtree(old, ignore_errors=True)


def _junction(link: Path, target: Path) -> None:
    """Directory junction (no admin rights needed); used read-only, removed with _remove_work."""
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def _remove_work(work: Path) -> None:
    """Remove a work folder; junctions inside it are unlinked, never followed."""
    for entry in work.iterdir() if work.exists() else ():
        if entry.is_junction():
            entry.unlink()
    shutil.rmtree(work, ignore_errors=True)


# ---- jobs ---------------------------------------------------------------------------------------------

class _Job:
    def __init__(self, data_dir: Path, log: LogFn, progress: Callable[[dict], None],
                 world_running: Callable[[], bool]) -> None:
        self.data_dir, self.log, self._progress, self.world_running = data_dir, log, progress, world_running
        self.runner = ProcessRunner()
        self.state = {"step": None, "progress": 0}

    def cancel(self) -> None:
        self.runner.cancel()

    def _set(self, **fields) -> None:
        self.state.update(fields)
        self._progress(dict(self.state))

    def _before_swap(self) -> None:
        self.runner.check()
        if self.world_running():
            raise JobError("Worldserver is running, so its data can't be replaced. Stop it and start this again.")


class DownloadJob(_Job):
    """Download data.zip of a wowgaming/client-data release and install it (all folders)."""

    def __init__(self, version: str, *args) -> None:
        super().__init__(*args)
        self.version = version
        self.zip = self.data_dir.parent / f".client-data-{version}.zip"

    def _download(self) -> None:
        url = f"{RELEASES}/download/{self.version}/data.zip"
        have = self.zip.stat().st_size if self.zip.is_file() else 0
        req = urllib.request.Request(url, headers={"User-Agent": "AzerothPanel", **({"Range": f"bytes={have}-"} if have else {})})
        self.log(f"  {url}")
        try:
            resp = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and have:              # already complete
                self.log("  Already downloaded.")
                return
            raise JobError(f"Download failed: HTTP {exc.code} for {url}") from exc
        except OSError as exc:
            raise JobError(f"Download failed: {exc}") from exc
        with resp:
            resumed = resp.status == 206
            if have and not resumed:
                have = 0                               # server ignored the range: start over
            total = have + int(resp.headers.get("Content-Length") or 0)
            if total:
                free = shutil.disk_usage(self.data_dir.parent).free
                need = (total - have) + total * 3     # zip + unpacked data (~2.7x the zip)
                if free < need:
                    raise JobError(f"Not enough free space: {free / 1e9:.1f} GB free, about {need / 1e9:.1f} GB needed.")
            self.log(f"  {'Resuming at ' + str(have // CHUNK) + ' MB of ' if resumed else 'Size: '}{total // CHUNK} MB")
            done, last = have, 0.0
            samples: deque[tuple[float, int]] = deque([(time.monotonic(), have)])   # speed over the last ~5 s
            with self.zip.open("ab" if resumed else "wb") as f:
                while chunk := resp.read(CHUNK):
                    self.runner.check()
                    f.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if total and now - last > 1:
                        last = now
                        samples.append((now, done))
                        while now - samples[0][0] > 5 and len(samples) > 2:
                            samples.popleft()
                        speed = int((done - samples[0][1]) / max(now - samples[0][0], 0.001))
                        self._set(progress=int(done * 70 / total), downloaded=done, total=total, speed=speed)
            if total and done < total:
                raise JobError("The download was interrupted. Start it again to resume.")

    def _extract(self, work: Path) -> list[str]:
        with zipfile.ZipFile(self.zip) as zf:
            members = zf.infolist()
            total = sum(m.file_size for m in members) or 1
            done, last = 0, 0.0
            for m in members:
                self.runner.check()
                target = (work / m.filename).resolve()
                if work.resolve() not in target.parents and target != work.resolve():
                    raise JobError(f"Unsafe path in the archive: {m.filename}")
                zf.extract(m, work)
                done += m.file_size
                if time.monotonic() - last > 1:
                    last = time.monotonic()
                    self._set(progress=70 + int(done * 28 / total))
        return sorted(p.name for p in work.iterdir() if p.is_dir())

    def run_sync(self) -> dict:
        self._set(step="download", progress=0)
        self.log(f"[step] Downloading client data {self.version}")
        self._download()
        self._set(step="extract", progress=70)
        self.log("[step] Unpacking")
        work = _work_dir(self.data_dir, "download")
        try:
            folders = self._extract(work)
            missing = [t for t in TYPES if t not in folders]
            if missing:
                raise JobError(f"The archive has no {', '.join(missing)} folder. Nothing was changed.")
            self._before_swap()
            self._set(step="install", progress=98)
            self.log(f"[step] Installing into {self.data_dir}")
            swap_in(self.data_dir, work, folders, self.log)
            (self.data_dir / VERSION_FILE).write_text(f"INSTALLED_VERSION={self.version}\n", encoding="utf-8")
        finally:
            _remove_work(work)
        self.zip.unlink(missing_ok=True)
        self._set(step="done", progress=100)
        self.log(f"[done] Client data {self.version} installed.")
        return {"version": self.version}


class ExtractJob(_Job):
    """Extract the chosen data types from a local 3.3.5a client with the server's extractor tools."""

    def __init__(self, client: Path, server_dir: Path, types: list[str], *args) -> None:
        super().__init__(*args)
        self.client, self.server, self.types = client, server_dir, types

    def _tool(self, name: str, args: list[str], cwd: Path) -> None:
        exe = self.server / name
        self.log(f"> {name} {' '.join(args)}")
        maps_done = re.compile(r"\((\d+)/(\d+)\)")    # map_extractor: "Extract <map> (i/N)"
        map_part = re.compile(r"^Processing\.*(\d+)%")   # map_extractor, per map: "Processing.......45%" + "\r"
        mmaps_done = re.compile(r"^(\d+)% \[Map")        # mmaps_generator: "12% [Map 0000] Building tile ..."
        current = [0, 0]                                 # map_extractor: map i of n being converted

        def parse(text: str) -> None:
            step = self.state["step"]
            if step == "dbc_maps" and (m := maps_done.search(text)):
                current[:] = int(m.group(1)), int(m.group(2))
                i, n = current
                self._within((i - 1) / n if n else 0, f"{i}/{n} maps")
            elif step == "dbc_maps" and current[1] and (m := map_part.match(text)):
                i, n = current
                self._within((i - 1 + int(m.group(1)) / 100) / n, f"{i}/{n} maps")
            elif step == "mmaps" and (m := mmaps_done.match(text)):
                self._within(int(m.group(1)) / 100, f"{m.group(1)}% of mmaps")

        def on_line(line: str) -> None:
            self.log(line)
            parse(line)

        # Progress meters ended by a lone "\r" update the bar instead of piling up in the log.
        code = self.runner.run([str(exe), *args], cwd, on_line, on_progress=parse)
        if code != 0:
            raise JobError(f"{name} failed (exit code {code}). The log says why.")

    def _within(self, fraction: float, detail: str) -> None:
        """Progress inside the current step (steps share the bar equally)."""
        self._set(detail=detail, progress=int((self._index + min(fraction, 1.0)) * 100 / self._steps))

    def run_sync(self) -> dict:
        work = _work_dir(self.data_dir, "extract")
        # The tools run inside the work folder and get short relative paths: map_extractor keeps -i/-o
        # in 128-character buffers and silently cuts longer paths (src/tools/map_extractor/System.cpp).
        _junction(work / "client", self.client)
        steps = [s for s in ("dbc_maps", "vmaps", "mmaps") if
                 (s == "dbc_maps" and ({"dbc", "maps"} & set(self.types))) or s in self.types]
        self._steps = len(steps)
        try:
            for i, step in enumerate(steps):
                self._index = i
                self._set(step=step, progress=int(i * 100 / len(steps)), detail=None)
                if step == "dbc_maps":
                    flags = sum(MAP_EXTRACT_FLAGS[t] for t in ("dbc", "maps") if t in self.types)
                    self.log("[step] Extracting " + " and ".join(t for t in ("dbc", "maps") if t in self.types)
                             + (" (with Cameras)" if "dbc" in self.types else ""))
                    self._tool("map_extractor.exe", ["-i", "client", "-o", ".", "-e", str(flags)], work)
                elif step == "vmaps":
                    self.log("[step] Extracting vmaps (\"No such file\" / \"Couldn't open RootWmo\" lines are normal)")
                    self._tool("vmap4_extractor.exe", ["-s", "-d", "client/Data"], work)
                    (work / "vmaps").mkdir(exist_ok=True)
                    self._tool("vmap4_assembler.exe", ["Buildings", "vmaps"], work)
                    shutil.rmtree(work / "Buildings", ignore_errors=True)
                else:
                    self.log("[step] Generating mmaps (this takes a long time)")
                    # mmaps_generator reads maps + vmaps from its data folder: freshly extracted ones,
                    # otherwise the installed ones (linked in read-only, never modified).
                    for name in ("maps", "vmaps"):
                        if not (work / name).exists():
                            live = self.data_dir / name
                            if not any(live.glob("*")):
                                raise JobError(f"MMaps need {name}, and there are none yet. Extract {name} too.")
                            _junction(work / name, live)
                    (work / "mmaps").mkdir(exist_ok=True)
                    self._tool("mmaps_generator.exe", ["--config", str(self.server / "mmaps-config.yaml")], work)
            produced = [p.name for p in work.iterdir() if p.is_dir() and not p.is_junction()
                        and p.name in ("dbc", "maps", "Cameras", "vmaps", "mmaps")]
            self._before_swap()
            self._set(step="install", progress=99, detail=None)
            self.log(f"[step] Installing into {self.data_dir}")
            swap_in(self.data_dir, work, sorted(produced), self.log)
            # The data no longer is a downloaded release; record where it came from instead.
            build = (pe.version_info(self.client / "Wow.exe")["version"] or "").rsplit(".", 1)[-1] or "unknown"
            (self.data_dir / VERSION_FILE).write_text(f"INSTALLED_VERSION=client-{build}\n", encoding="utf-8")
        finally:
            _remove_work(work)
        self._set(step="done", progress=100)
        self.log(f"[done] Extracted {', '.join(self.types)}.")
        return {}


def latest_release() -> str | None:
    try:
        req = urllib.request.Request(LATEST_API, headers={"User-Agent": "AzerothPanel", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("tag_name")
    except (OSError, ValueError):
        return None


async def run(job: _Job) -> dict:
    started = time.monotonic()
    result = await asyncio.to_thread(job.run_sync)
    return {**result, "duration": round(time.monotonic() - started)}
