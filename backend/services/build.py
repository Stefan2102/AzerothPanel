"""Compile AzerothCore with CMake + MSBuild and deploy the result into the server folder.

Steps of a build job (each logged as "[step] ..."):
  configure  cmake with every dependency path passed explicitly
  build      cmake --build (MSBuild); progress = finished projects / projects in the solution
  deploy     cmake --install, runtime DLLs, legacy.dll, PDBs, missing .conf files (optional)
Deploy needs worldserver and authserver stopped (their exes can't be replaced while they run).
Updating the source (git pull) is a separate job, PullJob. See docs/build.md.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..paths import BUILD_LOG_DIR, BUILD_STATE_FILE
from ..settings import Settings
from . import pe, source as source_info, toolchain
from .jobs import JobError, JobStore, LogFn, ProcessRunner

CONFIGS = ("RelWithDebInfo", "Release", "Debug")
# Always built: both servers (APPS_BUILD) and all compiler warnings (WITH_WARNINGS).
FIXED_OPTIONS = {"APPS_BUILD": "all", "WITH_WARNINGS": "ON"}
CHOICES = ("TOOLS_BUILD", "SCRIPTS", "MODULES")       # CMake options offered on the Compilation page
# Environment variables that would let CMake pick a different Boost/OpenSSL/MySQL than the chosen one.
_STRAY_ENV = {"BOOST_ROOT", "BOOSTROOT", "BOOST_INCLUDEDIR", "BOOST_LIBRARYDIR", "OPENSSL_ROOT_DIR", "MYSQL_ROOT_DIR"}
# Cache entries that may not change between configures of one build folder.
_CACHE_KEYS = ("CMAKE_HOME_DIRECTORY", "CMAKE_GENERATOR", "CMAKE_GENERATOR_INSTANCE", "Boost_DIR",
               "OPENSSL_INCLUDE_DIR", "MYSQL_INCLUDE_DIR", "MYSQL_LIBRARY")
_VC_RUNTIME = re.compile(r"^(msvcp|vcruntime|concrt|vccorlib|vcomp)\d", re.I)
_PROJECT_DONE = re.compile(r"\.vcxproj -> ")
_SOURCE_DONE = re.compile(r"^\s*[\w.+-]+\.(?:cpp|cxx|cc|c)\s*$", re.I)   # cl prints each file it compiles
_ERROR = re.compile(r": (?:fatal )?error [A-Z]+\d+|^CMake Error|: error MSB\d+", re.I)
_WARNING = re.compile(r": warning [A-Z]+\d+|^CMake Warning", re.I)
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def new_store() -> JobStore:
    """Build/deploy history (data/build.json) with full logs in data/build-logs."""
    return JobStore(BUILD_STATE_FILE, max_jobs=50, max_log_lines=3000, log_dir=BUILD_LOG_DIR)


@dataclass
class Plan:
    """Everything a build needs, resolved from detection + overrides."""
    source: Path
    build: Path
    install: Path
    cmake: Path
    git: Path | None             # for the module snapshot of a build
    generator: str
    vs_instance: Path
    vs_toolset: str | None
    boost_config: Path
    openssl: Path
    mysql: Path
    mysql_version: str
    legacy_dll: Path | None


def default_options(settings: Settings, ws_cache: dict, source: Path | None) -> dict:
    """Saved options, else the existing build's values, else the source's defaults."""
    choices = toolchain.build_options(source) if source and source.is_dir() else {}
    opts = {"config": "RelWithDebInfo", "jobs": os.cpu_count() or 4, "clean": False, "deploy": True}
    for name in CHOICES:
        opts[name] = ws_cache.get(name) or (choices.get(name) or {}).get("default")
    # Remember the last choices, except a clean build: that one is never pre-ticked.
    opts.update({k: v for k, v in settings.build_options.items() if k in opts and k != "clean"})
    return opts


def resolve(settings: Settings, deploy_only: bool = False, found: dict | None = None) -> tuple[Plan | None, list[str], dict]:
    """Build plan from the current detection, or the reasons why nothing can be built (or deployed) yet."""
    found = found or toolchain.detect_all(settings)
    ws, items = found["workspace"], {i.key: i for i in found["items"]}
    problems = []
    if not settings.root_dir:
        problems.append("Choose your AzerothCore folder on the Setup page first.")
    elif not ws["source_valid"]:
        problems.append(f"No AzerothCore source in {ws['source']} yet. Clone it on the Setup page.")
    for key in ("vs", "cmake", "boost", "openssl", "mysql"):
        item = items[key]
        if item.status != "ok":
            label = item.public()["label"]
            problems.append(f"{label}: {item.message or item.status}")
    if ws["source_valid"] and not deploy_only:      # a module only matters when compiling
        for m in source_info.modules(Path(ws["source"]), None):
            if m["broken"]:
                problems.append(f"Module '{m['name']}' links to {m['link']}, which no longer exists. "
                                "Restore that folder or remove the link.")
    if problems:
        return None, problems, found
    plan = Plan(
        source=Path(ws["source"]), build=Path(ws["build"]), install=settings.server_path,
        cmake=Path(items["cmake"].path), git=Path(items["git"].path) if items["git"].status == "ok" else None,
        generator=items["vs"].details["generator"], vs_instance=Path(items["vs"].path),
        vs_toolset=items["vs"].details.get("toolset"),
        boost_config=Path(items["boost"].details["config_dir"]), openssl=Path(items["openssl"].path),
        mysql=Path(items["mysql"].path), mysql_version=items["mysql"].version or "",
        legacy_dll=Path(items["openssl"].details["legacy"]) if items["openssl"].details.get("legacy") else None,
    )
    return plan, [], found


def dist_hashes(install: Path) -> dict[str, str]:
    """{path: sha256} of the config templates (.conf.dist) in the server's configs folder."""
    folder = install / "configs"
    if not folder.is_dir():
        return {}
    return {os.path.normcase(str(f)): hashlib.sha256(f.read_bytes()).hexdigest() for f in folder.rglob("*.conf.dist")}


def sync_configs(plan: "Plan", installed: list[Path], before: dict[str, str], log: LogFn) -> list[str]:
    """Configs after cmake --install copied the templates (files only; deploy never edits a value):
    - no .conf yet: create it as a copy of its .dist;
    - its .dist changed in this update: replace the .conf with the new .dist;
    - otherwise: leave it alone.
    Returns the created or replaced configs. They have AzerothCore's defaults until Config Files ->
    Setup -> Save & apply puts the panel's values in (services/config_values.py)."""
    fresh = []
    for dist in (f for f in installed if f.name.endswith(".conf.dist") and f.is_file()):
        conf = dist.with_name(dist.name[: -len(".dist")])
        name = conf.relative_to(plan.install / "configs").as_posix()
        if not conf.exists():
            log(f"  New config {name}.")
        else:
            was = before.get(os.path.normcase(str(dist)))
            if was is None or was == hashlib.sha256(dist.read_bytes()).hexdigest():
                continue                                    # template unchanged by this update
            log(f"  Replaced {name} with the updated one.")
        shutil.copy2(dist, conf)
        fresh.append(name)
    if fresh:
        log("  Before starting the servers, go to Config Files.")
    return fresh


def requires_legacy_provider(source: Path) -> bool:
    """AzerothCore asserts that OpenSSL's legacy.dll sits next to the exe (OpenSSLCrypto.cpp)."""
    folder = source / "src" / "common" / "Cryptography"
    return any("legacy.dll" in p.read_text(encoding="utf-8", errors="replace") for p in folder.glob("*.cpp"))


def count_work(build: Path) -> tuple[int, int]:
    """(projects that produce a binary, source files they compile). MSBuild prints "x.vcxproj -> file"
    for each finished project and cl prints each source file name, so both can be counted."""
    projects = sources = 0
    for p in build.rglob("*.vcxproj"):
        if "CMakeFiles" in p.relative_to(build).parts:
            continue        # CMake's own compiler checks (CompilerIdC, CompilerIdCXX), never part of the build
        text = p.read_text(encoding="utf-8", errors="replace")
        if "<ConfigurationType>Utility</ConfigurationType>" not in text:
            projects += 1
            sources += text.count("<ClCompile Include=")
    return projects, sources


def _posix(p: Path) -> str:
    return p.as_posix()


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k.upper() not in _STRAY_ENV}
    env["VSLANG"] = "1033"     # English compiler/MSBuild messages, so errors and warnings can be counted
    return env


# ---- runtime DLLs ----------------------------------------------------------------------------------------

def runtime_search_dirs(openssl: Path | None, mysql: Path | None, boost_config: Path | None) -> list[Path]:
    """Where the server's third-party DLLs may come from, in priority order (never System32)."""
    dirs = toolchain.openssl_runtime_dirs(openssl) if openssl else []
    if mysql:
        dirs += [mysql / "lib", mysql / "bin"]
    if boost_config:
        dirs.append(boost_config.parents[1])
    return [d for d in dirs if d.is_dir()]


def _same_file(a: Path, b: Path) -> bool:
    if not b.is_file() or a.stat().st_size != b.stat().st_size:
        return False
    digest = lambda p: hashlib.sha256(p.read_bytes()).digest()  # noqa: E731
    return digest(a) == digest(b)


def runtime_report(install: Path, search: list[Path], extra: list[Path] = ()) -> dict:
    """Walk the imports of every exe in `install` (and `extra` files) and decide where each DLL comes from.

    Returns {"copy": [{name, source, installed: same|different|missing, needed_by}], "own": [...], "system": [...], "vc_runtime": [...],
             "problems": [{name, needed_by, reason}]}.
    """
    report: dict = {"copy": [], "own": [], "system": [], "vc_runtime": [], "problems": []}
    queue = sorted(install.glob("*.exe")) + list(extra)
    needed_by: dict[str, set[str]] = {}
    seen: set[str] = set()
    while queue:
        binary = queue.pop(0)
        try:
            names = pe.imports(binary)
        except (OSError, pe.PeError) as exc:
            report["problems"].append({"name": binary.name, "needed_by": [], "reason": f"Can't read: {exc}"})
            continue
        for name in names:
            key = name.lower()
            needed_by.setdefault(key, set()).add(binary.name)
            if key in seen:
                continue
            seen.add(key)
            if key.startswith(("api-ms-", "ext-ms-")):
                report["system"].append(name)
                continue
            if _VC_RUNTIME.match(key):
                report["vc_runtime"].append(name)
                continue
            src = next((d / name for d in search if (d / name).is_file()), None)
            if src:
                target = install / src.name
                state = "same" if _same_file(src, target) else "different" if target.is_file() else "missing"
                report["copy"].append({"name": src.name, "source": str(src), "installed": state})
                queue.append(src)
            elif (install / name).is_file():
                report["own"].append(name)
                queue.append(install / name)
            elif (SYSTEM32 / name).is_file():
                company = pe.version_info(SYSTEM32 / name)["company"] or ""
                if company.startswith("Microsoft"):
                    report["system"].append(name)
                else:
                    report["problems"].append({"name": name, "reason": f"Only found in {SYSTEM32} ({company or 'unknown vendor'}), "
                                               "not in the selected OpenSSL/MySQL folders. It would load a stray copy."})
            else:
                report["problems"].append({"name": name, "reason": "Not found in the selected OpenSSL/MySQL folders."})
    for group in ("copy", "problems"):
        for entry in report[group]:
            entry["needed_by"] = sorted(needed_by.get(entry["name"].lower(), ()))
    return report


def deploy_runtime(plan: Plan, log: LogFn) -> None:
    """Copy the third-party DLLs the server binaries need next to them; fail on anything unresolved."""
    search = runtime_search_dirs(plan.openssl, plan.mysql, plan.boost_config)
    extra: list[Path] = []
    if requires_legacy_provider(plan.source):
        if plan.legacy_dll is None:
            raise JobError(f"The core needs OpenSSL's legacy.dll, but {plan.openssl} has none.")
        extra.append(plan.legacy_dll)
    report = runtime_report(plan.install, search, extra)
    files = report["copy"] + ([{"name": "legacy.dll", "source": str(plan.legacy_dll)}] if extra else [])
    for entry in files:
        src, dst = Path(entry["source"]), plan.install / entry["name"]
        if entry.get("installed") == "same" or _same_file(src, dst):
            log(f"  = {entry['name']} (up to date)")
        else:
            shutil.copy2(src, dst)
            log(f"  + {entry['name']}  <- {src.parent}")
    for p in report["problems"]:
        log(f"[ERROR] {p['name']} (needed by {', '.join(p['needed_by']) or '?'}): {p['reason']}")
    if report["problems"]:
        raise JobError("Some DLLs the server needs could not be found. See the log.")
    lib = plan.install / "libmysql.dll"
    if lib.is_file():
        found = pe.version_info(lib)["version"] or ""
        if toolchain.version_tuple(found)[:3] != toolchain.version_tuple(plan.mysql_version)[:3]:
            raise JobError(f"libmysql.dll is {found}, but the server was compiled with MySQL {plan.mysql_version} "
                           "headers (AzerothCore error ACE00046).")
        log(f"  libmysql.dll {found} matches the MySQL headers {plan.mysql_version}.")


# ---- the job ------------------------------------------------------------------------------------------------

class BuildJob:
    """One build/deploy run. `progress` receives {step, progress, projects_/files_ done/total, warnings, errors}."""

    def __init__(self, plan: Plan, options: dict, steps: list[str], log: LogFn,
                 progress: Callable[[dict], None], running_servers: Callable[[], list[str]]) -> None:
        self.plan, self.opts, self.steps = plan, options, steps
        self.log, self._progress = log, progress
        self.running_servers = running_servers
        self.runner = ProcessRunner()
        self.state = {"step": None, "progress": 0, "projects_done": 0, "projects_total": 0, "files_done": 0,
                      "files_total": 0, "warnings": 0, "errors": 0}
        self._warnings: set[str] = set()
        self._errors: set[str] = set()
        self._fresh = False          # nothing compiled yet in this build folder (set by configure)
        self._dists_before: dict[str, str] = {}
        self._configs: list[str] = []    # configs deploy created or replaced (they need Config Files)

    def cancel(self) -> None:
        self.runner.cancel()

    def _set(self, **fields) -> None:
        self.state.update(fields)
        self._progress(dict(self.state))

    async def _exec(self, args: list[str], cwd: Path | None = None, track: bool = False) -> int:
        self.log(f"> {' '.join(_quote(a) for a in args)}")

        def on_line(line: str) -> None:
            self.log(line)
            if not track:
                return
            if _ERROR.search(line):
                self._errors.add(line.strip())
            elif _WARNING.search(line):
                self._warnings.add(line.strip())
            if _PROJECT_DONE.search(line):
                self._advance("projects")
            elif _SOURCE_DONE.match(line):
                self._advance("files")
            if len(self._errors) != self.state["errors"] or len(self._warnings) != self.state["warnings"]:
                self._set(errors=len(self._errors), warnings=len(self._warnings))

        return await asyncio.to_thread(self.runner.run, args, cwd, on_line, _env())

    def _advance(self, kind: str) -> None:
        """Count a finished project or source file. A fresh build is measured by files (two projects hold
        most of them), an incremental one by projects (only a few files compile)."""
        done = self.state[f"{kind}_done"] + 1
        self.state[f"{kind}_done"] = done
        self.state[f"{kind}_total"] = max(self.state[f"{kind}_total"], done)
        measure = "files" if self._fresh else "projects"
        fraction = self.state[f"{measure}_done"] / max(self.state[f"{measure}_total"], 1)
        self._set(progress=min(99, int(fraction * 100)))

    async def run(self) -> dict:
        started = time.monotonic()
        result: dict = {"deployed": False}
        if "configure" in self.steps:
            await self._configure()
        if "build" in self.steps:
            await self._build()
            # What this build compiled, so the Modules page can tell whether a rebuild is needed.
            result["modules"] = await asyncio.to_thread(module_snapshot, self.plan.source, self.plan.git)
        if "deploy" in self.steps:
            result["deployed"] = await self._deploy()
            result["configs"] = self._configs
        self._set(step="done", progress=100)
        result["duration"] = round(time.monotonic() - started)
        result.update(warnings=len(self._warnings), errors=len(self._errors))
        self.log(f"[done] Finished in {_duration(result['duration'])}"
                 + (f" · {len(self._warnings)} warnings" if "build" in self.steps else ""))
        return result

    async def _configure(self) -> None:
        plan = self.plan
        self._set(step="configure")
        self.log("[step] Configuring with CMake")
        cache = plan.build / "CMakeCache.txt"
        self._fresh = bool(self.opts.get("clean")) or not cache.is_file()
        if self.opts.get("clean") and plan.build.exists():
            if not cache.is_file():
                raise JobError(f"{plan.build} has no CMakeCache.txt, so it isn't wiped for a clean build. "
                               "Choose an empty folder or an existing build folder.")
            self.log(f"  Clean build: deleting {plan.build}")
            await asyncio.to_thread(shutil.rmtree, plan.build)
        elif cache.is_file():
            old = toolchain.read_cache(cache)
            new = {"CMAKE_HOME_DIRECTORY": plan.source, "CMAKE_GENERATOR": plan.generator,
                   "CMAKE_GENERATOR_INSTANCE": plan.vs_instance, "Boost_DIR": plan.boost_config,
                   "OPENSSL_INCLUDE_DIR": plan.openssl / "include", "MYSQL_INCLUDE_DIR": plan.mysql / "include",
                   "MYSQL_LIBRARY": plan.mysql / "lib" / "libmysql.lib"}
            changed = [k for k in _CACHE_KEYS if old.get(k) and not toolchain.same_path(old[k], new[k])]
            if changed:
                self.log(f"  Toolchain changed ({', '.join(changed)}): starting with a fresh CMake cache.")
                self._fresh = True       # new include paths and flags: nearly everything recompiles
                cache.unlink()
                await asyncio.to_thread(shutil.rmtree, plan.build / "CMakeFiles", True)
        plan.build.mkdir(parents=True, exist_ok=True)
        o = self.opts
        args = [str(plan.cmake), "-S", str(plan.source), "-B", str(plan.build), "-G", plan.generator, "-A", "x64",
                f"-DCMAKE_GENERATOR_INSTANCE={_posix(plan.vs_instance)}",
                f"-DCMAKE_INSTALL_PREFIX={_posix(plan.install)}",
                f"-DBoost_DIR={_posix(plan.boost_config)}",
                f"-DOPENSSL_ROOT_DIR={_posix(plan.openssl)}",
                f"-DMYSQL_INCLUDE_DIR={_posix(plan.mysql / 'include')}",
                f"-DMYSQL_LIBRARY={_posix(plan.mysql / 'lib' / 'libmysql.lib')}"]
        args += [f"-D{name}={value}" for name, value in FIXED_OPTIONS.items()]
        args += [f"-D{name}={o[name]}" for name in CHOICES if o.get(name)]
        if await self._exec(args) != 0:
            raise JobError("CMake configure failed. The first \"CMake Error\" lines in the log say why.")
        projects, files = await asyncio.to_thread(count_work, plan.build)
        self._set(projects_total=projects, files_total=files)

    async def _build(self) -> None:
        plan = self.plan
        # fresh: every file compiles. Otherwise MSBuild skips up-to-date files, so files_total is only an upper bound.
        self._set(step="build", progress=0, projects_done=0, files_done=0, fresh=self._fresh)
        self.log(f"[step] Compiling ({self.opts['config']}, {self.opts['jobs']} parallel jobs)")
        if not self.state["projects_total"]:
            projects, files = await asyncio.to_thread(count_work, plan.build)
            self._set(projects_total=projects, files_total=files)
        args = [str(plan.cmake), "--build", str(plan.build), "--config", self.opts["config"],
                "--parallel", str(self.opts["jobs"]), "--", "/nodeReuse:false", "/nologo", "/v:minimal"]
        if await self._exec(args, track=True) != 0:
            raise JobError(f"Compiling failed with {len(self._errors)} error(s). The lines marked as errors in the log say why.")

    async def _deploy(self) -> bool:
        plan = self.plan
        self._set(step="deploy")
        self.log(f"[step] Deploying to {plan.install}")
        running = self.running_servers()
        if running:
            self.log(f"[WARN] Not deployed: {' and '.join(running)} still running. Stop the servers and click Deploy only.")
            return False
        # Remember the config templates as they are now, to see which ones this update changes.
        self._dists_before = await asyncio.to_thread(dist_hashes, plan.install)
        if await self._exec([str(plan.cmake), "--install", str(plan.build), "--config", self.opts["config"]]) != 0:
            raise JobError("cmake --install failed.")
        await asyncio.to_thread(self._finish_deploy)
        return True

    def _finish_deploy(self) -> None:
        plan, log = self.plan, self.log
        log("  Runtime DLLs:")
        deploy_runtime(plan, log)
        installed = _installed_files(plan.build)
        # Debug symbols (RelWithDebInfo/Debug builds) make crash dumps readable.
        bin_dir = plan.build / "bin" / self.opts["config"]
        for exe in (p for p in installed if p.suffix.lower() == ".exe"):
            pdb = bin_dir / f"{exe.stem}.pdb"
            if pdb.is_file():
                shutil.copy2(pdb, plan.install / pdb.name)
                log(f"  + {pdb.name}")
        self._configs = sync_configs(plan, installed, self._dists_before, log)
        self._set(configs=self._configs)
        vc = toolchain.vc_runtime_version()
        if vc is None:
            log("[WARN] The Visual C++ x64 runtime is not installed; the servers won't start. See Requirements.")
        elif plan.vs_toolset and toolchain.version_tuple(vc)[:2] < toolchain.version_tuple(plan.vs_toolset)[:2]:
            log(f"[WARN] The Visual C++ runtime {vc} is older than the compiler's {plan.vs_toolset}. Update it (see Requirements).")


class PullJob:
    """Update the core source: `git pull --ff-only`, then list the commits it brought in."""

    def __init__(self, git: Path, source: Path, log: LogFn, progress: Callable[[dict], None]) -> None:
        self.git, self.source, self.log, self._progress = git, source, log, progress
        self.runner = ProcessRunner()

    def cancel(self) -> None:
        self.runner.cancel()

    def _head(self) -> str | None:
        return source_info.git(str(self.git), self.source, "rev-parse", "HEAD")

    async def run(self) -> dict:
        started = time.monotonic()
        self._progress({"step": "pull", "progress": 0})
        self.log(f"[step] Pulling the latest source into {self.source}")
        before = await asyncio.to_thread(self._head)
        args = [str(self.git), "-C", str(self.source), "pull", "--ff-only"]
        self.log(f"> {' '.join(_quote(a) for a in args)}")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}      # never wait for a password prompt
        if await asyncio.to_thread(self.runner.run, args, None, self.log, env) != 0:
            raise JobError("git pull failed (local changes in the way, or the branch has diverged). Nothing was changed.")
        after = await asyncio.to_thread(self._head)
        commits: list[str] = []
        if before and after and before != after:
            out = await asyncio.to_thread(source_info.git, str(self.git), self.source, "log", "--oneline", f"{before}..{after}")
            commits = (out or "").splitlines()
            self.log(f"  {len(commits)} new commit(s):")
            for line in commits[:200]:
                self.log(f"  {line}")
        self._progress({"step": "done", "progress": 100})
        self.log(f"[done] {'Already up to date.' if not commits else f'{len(commits)} new commit(s). Build to use them.'}")
        return {"duration": round(time.monotonic() - started), "commits": len(commits)}


def module_snapshot(source: Path, git: Path | None) -> dict[str, str | None]:
    """{module folder: HEAD commit} of <source>/modules (None for a folder without git)."""
    return {m["name"]: m.get("commit") for m in source_info.modules(source, str(git) if git else None) if not m["broken"]}


def running_servers(manager) -> list[str]:
    """Labels of the servers whose files a deploy would replace and that are running now."""
    return [manager.services[k].label for k in ("world", "auth") if manager.services[k].is_up()]


def _installed_files(build: Path) -> list[Path]:
    manifest = build / "install_manifest.txt"
    if not manifest.is_file():
        return []
    return [Path(line) for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


def _duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m} min {s} s" if m else f"{s} s"
