"""Lifecycle of the three AzerothCore services: MySQL, authserver, worldserver.

Rules (see docs/process-control.md):
* Start order MySQL -> auth -> world; stop order world -> auth -> MySQL.
* Every stop is graceful: worldserver gets `server shutdown <delay>` (players
  are saved), authserver and MySQL get a console Ctrl-C. Nothing is ever
  killed unless the user explicitly confirms "Force kill".
* MySQL refuses to stop while auth/world are still connected to it.
* Processes started outside the panel are detected ("external") and can be
  stopped gracefully through a console control event.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import psutil

from ..acconf import ServerConfig, load_server_config
from ..settings import Settings
from .console_screen import ConsoleScreen
from .conpty import ConPtyProcess

ORDER = ("mysql", "auth", "world")
LABELS = {"mysql": "MySQL", "auth": "Authserver", "world": "Worldserver"}
READY_TIMEOUT = {"mysql": 180, "auth": 90, "world": 900}
STOP_TIMEOUT = {"mysql": 300, "auth": 60, "world": 300}   # world: plus the countdown
EXTERNAL_SIGNAL = {"mysql": "c", "auth": "break", "world": "break"}
# Pseudo console size. It only decides where ConPTY hard-wraps long lines; the browser
# shows the interpreted lines in any size (see console_screen.py).
PTY_COLS, PTY_ROWS = 240, 50
CONSOLE_LINES = 10_000          # scrolled-off lines kept per service (current run)
SAMPLE_INTERVAL = 2.0
CTRL_HELPER = Path(__file__).with_name("ctrl_event.py")

_CURSOR_POS = re.compile(r"\x1b\[\d*(?:;\d*)?[Hf]")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")


def strip_ansi(text: str) -> str:
    text = _CURSOR_POS.sub("\n", text)
    text = _ANSI.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "")


def _root(procs: list[psutil.Process]) -> psutil.Process | None:
    """The process whose parent is outside the set (mysqld: the monitor process)."""
    pids = {p.pid for p in procs}
    for p in procs:
        try:
            if p.ppid() not in pids:
                return p
        except psutil.Error:
            continue
    return procs[0] if procs else None


class ServiceError(Exception):
    """A lifecycle request that cannot be carried out (shown to the user as-is)."""


async def port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return True


@dataclass
class Service:
    key: str
    label: str
    state: str = "stopped"              # stopped | starting | running | stopping | external
    proc: ConPtyProcess | None = None
    external: list[psutil.Process] = field(default_factory=list)
    started_at: float | None = None
    message: str | None = None
    last_exit: dict | None = None
    console: ConsoleScreen | None = None
    run_id: int = 0                      # increments per start; browsers clear on change
    watchers: set[asyncio.Event] = field(default_factory=set)
    text_listeners: set[Callable[[str], None]] = field(default_factory=set)
    samples: deque[dict] = field(default_factory=lambda: deque(maxlen=90))
    cpu_procs: dict[int, psutil.Process] = field(default_factory=dict)
    command_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ---- console output fan-out ------------------------------------------------

    def feed(self, data: str) -> None:
        if self.console is not None:
            self.console.feed(data)
        for event in self.watchers:
            event.set()
        if self.text_listeners:
            text = strip_ansi(data)
            for listener in list(self.text_listeners):
                listener(text)

    def banner(self, text: str) -> None:
        self.feed(f"\r\n\x1b[95m── {text} ──\x1b[0m\r\n")

    def reset_console(self) -> None:
        self.console = ConsoleScreen(PTY_COLS, PTY_ROWS, CONSOLE_LINES)
        self.run_id += 1
        for event in self.watchers:
            event.set()

    # ---- process view ------------------------------------------------------------

    def processes(self) -> list[psutil.Process]:
        if self.proc:
            return self.proc.processes()
        alive = []
        for p in self.external:
            try:
                if p.is_running():
                    alive.append(p)
            except psutil.NoSuchProcess:
                pass
        return alive

    def is_up(self) -> bool:
        return bool(self.processes())


class ServerManager:
    def __init__(self, get_settings: Callable[[], Settings]):
        self._get_settings = get_settings
        self.services = {k: Service(k, LABELS[k]) for k in ORDER}
        self.job: dict | None = None
        self.last_job: dict | None = None
        self._job_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None
        self._last_external_scan = 0.0
        self._last_sample = 0.0
        self._cpu_count = psutil.cpu_count() or 1
        # Why a service may not start right now (another job is replacing its files or database), or None.
        # Set by the app, which knows the build / data / backup jobs.
        self.start_guard: Callable[[str], str | None] = lambda key: None

    # ---- configuration -------------------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self._get_settings()

    def config(self) -> ServerConfig:
        return load_server_config(self.settings.server_path)

    def managed(self, key: str) -> bool:
        """MySQL is only managed when the settings point at a mysqld install."""
        return key != "mysql" or self.settings.mysql_path is not None

    def _exe(self, key: str) -> tuple[Path, Path, str | None]:
        s = self.settings
        if key == "mysql":
            assert s.mysql_path is not None
            return s.mysql_path / "bin" / "mysqld.exe", s.mysql_path, "--console"
        name = "authserver.exe" if key == "auth" else "worldserver.exe"
        return s.server_path / name, s.server_path, None

    def _endpoint(self, key: str, cfg: ServerConfig) -> tuple[str, int]:
        if key == "mysql":
            return cfg.login_db.host, cfg.login_db.port
        return "127.0.0.1", cfg.auth_port if key == "auth" else cfg.world_port

    # ---- background monitor --------------------------------------------------------

    def start_monitor(self) -> None:
        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="service-monitor")

    async def _monitor_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the monitor must survive anything a single tick throws
                print(f"[monitor] {exc!r}", file=sys.stderr)
            await asyncio.sleep(1.0)

    async def _tick(self) -> None:
        if not self.settings.configured:
            return
        cfg = self.config()
        now = time.monotonic()
        for svc in self.services.values():
            if svc.proc:
                svc.proc.refresh_tree()
                if not svc.proc.alive():
                    await self._finalize_exit(svc)
                elif svc.state == "starting" and await port_open(*self._endpoint(svc.key, cfg)):
                    svc.state = "running"
        if now - self._last_external_scan > 3.0:
            self._last_external_scan = now
            await self._scan_external()
        if now - self._last_sample > SAMPLE_INTERVAL:
            self._last_sample = now
            self._sample_metrics()

    async def _finalize_exit(self, svc: Service) -> None:
        proc = svc.proc
        assert proc is not None
        code = proc.exit_code()
        unexpected = svc.state != "stopping"
        svc.proc = None
        await asyncio.to_thread(proc.close)
        svc.last_exit = {"code": code, "at": time.time(), "unexpected": unexpected}
        svc.state = "stopped"
        svc.started_at = None
        if unexpected:
            svc.message = f"{svc.label} exited unexpectedly (exit code {code}). Check its console and logs."
            svc.banner(f"{svc.label} exited unexpectedly with code {code}")
        else:
            # mysqld's monitor reports 0xC000013A (Ctrl-C exit) after a clean shutdown; that is expected.
            svc.banner(f"{svc.label} stopped")

    async def _scan_external(self) -> None:
        wanted: dict[str, str] = {}
        for key in ORDER:
            svc = self.services[key]
            if svc.proc is None and self.managed(key):
                wanted[os.path.normcase(str(self._exe(key)[0]))] = key
        if not wanted:
            return

        def scan() -> dict[str, list[psutil.Process]]:
            found: dict[str, list[psutil.Process]] = {}
            for p in psutil.process_iter(["exe"]):
                exe = p.info.get("exe")
                if exe and (key := wanted.get(os.path.normcase(exe))):
                    found.setdefault(key, []).append(p)
            return found

        found = await asyncio.to_thread(scan)
        for key in wanted.values():
            svc = self.services[key]
            if svc.proc is not None:      # started by us while scanning
                continue
            procs = found.get(key, [])
            svc.external = procs
            if procs and svc.state in ("stopped", "external"):
                svc.state = "external"
                svc.started_at = min(p.create_time() for p in procs)
            elif not procs and svc.state in ("external", "stopping"):
                svc.state = "stopped"
                svc.started_at = None

    def _sample_metrics(self) -> None:
        for svc in self.services.values():
            procs = svc.processes()
            cpu = mem = 0.0
            seen = set()
            for p in procs:
                tracked = svc.cpu_procs.setdefault(p.pid, p)
                seen.add(p.pid)
                try:
                    cpu += tracked.cpu_percent(None)
                    mem += tracked.memory_info().rss
                except psutil.Error:
                    pass
            for pid in set(svc.cpu_procs) - seen:
                svc.cpu_procs.pop(pid, None)
            if procs:
                svc.samples.append({"t": time.time(), "cpu": round(cpu / self._cpu_count, 1), "mem": int(mem)})
            else:
                svc.samples.clear()

    # ---- jobs (one lifecycle operation at a time) ---------------------------------

    def run_job(self, name: str, coro_factory: Callable[[], "asyncio.Future"]) -> None:
        if self._job_task and not self._job_task.done():
            raise ServiceError(f"Busy: {self.job['name'] if self.job else 'another operation'} is still running.")
        self.job = {"name": name, "step": None, "started": time.time()}

        async def runner() -> None:
            ok, error = True, None
            try:
                await coro_factory()
            except ServiceError as exc:
                ok, error = False, str(exc)
            except Exception as exc:
                ok, error = False, f"Unexpected error: {exc!r}"
            self.last_job = {"name": name, "ok": ok, "error": error, "finished": time.time()}
            self.job = None

        self._job_task = asyncio.create_task(runner(), name=f"job-{name}")

    def _step(self, text: str) -> None:
        if self.job:
            self.job["step"] = text

    # ---- start ----------------------------------------------------------------------

    async def start(self, key: str) -> None:
        svc = self.services[key]
        if not self.managed(key):
            raise ServiceError("MySQL is not managed by the panel (no MySQL folder chosen on Setup -> Requirements).")
        if svc.state != "stopped" or svc.is_up():
            raise ServiceError(f"{svc.label} is already {svc.state}.")
        if reason := self.start_guard(key):
            raise ServiceError(reason)
        cfg = self.config()
        host, port = self._endpoint(key, cfg)
        if await port_open(host, port):
            raise ServiceError(f"Port {port} is already in use by another program, so {svc.label} cannot start.")
        if key != "mysql" and not await port_open(cfg.login_db.host, cfg.login_db.port):
            raise ServiceError(f"MySQL is not reachable on {cfg.login_db.host}:{cfg.login_db.port}. Start MySQL first.")
        exe, cwd, args = self._exe(key)
        if not exe.is_file():
            raise ServiceError(f"{exe} does not exist.")

        self._step(f"Starting {svc.label}")
        svc.message = None
        svc.reset_console()   # each run starts with an empty console view
        proc = ConPtyProcess(exe, args, cwd, PTY_COLS, PTY_ROWS, asyncio.get_running_loop(), svc.feed)
        try:
            proc.start()
        except Exception as exc:
            raise ServiceError(f"Could not start {svc.label}: {exc}") from exc
        svc.proc = proc
        svc.external = []
        svc.state = "starting"
        svc.started_at = time.time()

        self._step(f"Waiting for {svc.label} to listen on port {port}")
        deadline = time.monotonic() + READY_TIMEOUT[key]
        while svc.state == "starting":
            if time.monotonic() > deadline:
                raise ServiceError(f"{svc.label} is still not listening on port {port} after "
                                   f"{READY_TIMEOUT[key]} s. It keeps running; check its console.")
            await asyncio.sleep(0.25)
        if svc.state != "running":
            code = svc.last_exit["code"] if svc.last_exit else None
            raise ServiceError(f"{svc.label} exited during startup (exit code {code}). Check its console.")

    # ---- stop -----------------------------------------------------------------------

    async def stop(self, key: str, delay: int | None = None) -> None:
        svc = self.services[key]
        if not svc.is_up():
            raise ServiceError(f"{svc.label} is not running.")
        if key == "mysql":
            users = [self.services[k].label for k in ("auth", "world") if self.services[k].is_up()]
            if users:
                raise ServiceError(f"Stop {' and '.join(users)} first; they are connected to MySQL.")

        previous = svc.state
        svc.state = "stopping"
        svc.message = None
        timeout = STOP_TIMEOUT[key]
        if svc.proc:
            if key == "world":
                countdown = self.settings.world_shutdown_delay if delay is None else max(0, int(delay))
                timeout += countdown
                self._step(f"Worldserver shutdown countdown: {countdown} s (saving players)")
                svc.proc.write(f"server shutdown {countdown}\r")
            else:
                self._step(f"Sending Ctrl-C to {svc.label}")
                svc.proc.write("\x03")
        else:
            self._step(f"Asking external {svc.label} to shut down")
            await self._signal_external(svc)

        deadline = time.monotonic() + timeout
        while svc.is_up():
            if time.monotonic() > deadline:
                svc.state = previous if svc.proc is None else "stopping"
                raise ServiceError(f"{svc.label} is still shutting down after {timeout} s. "
                                   "Give it more time, or use Force kill as a last resort.")
            await asyncio.sleep(0.25)
        # Let the monitor finalise our own process (exit code, pseudo console cleanup).
        while svc.proc is not None:
            await asyncio.sleep(0.1)
        svc.state = "stopped"
        svc.external = []
        svc.started_at = None

    async def _signal_external(self, svc: Service) -> None:
        # Attach to the root of the tree (mysqld monitor); all members share its console.
        root = _root(svc.processes())
        if root is None:
            return
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-I", str(CTRL_HELPER), str(root.pid), EXTERNAL_SIGNAL[svc.key]],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise ServiceError(f"Could not signal {svc.label} (helper exit {result.returncode}).")

    async def restart(self, key: str, delay: int | None = None) -> None:
        await self.stop(key, delay)
        await self.start(key)

    async def start_all(self) -> None:
        for key in ORDER:
            svc = self.services[key]
            if not self.managed(key) or svc.is_up():
                continue
            if key == "mysql":
                cfg = self.config()
                if await port_open(cfg.login_db.host, cfg.login_db.port):
                    continue  # MySQL already provided by something else (e.g. a Windows service)
            await self.start(key)

    async def stop_all(self, delay: int | None = None, owned_only: bool = False) -> None:
        for key in reversed(ORDER):
            svc = self.services[key]
            if not svc.is_up() or (owned_only and svc.proc is None):
                continue
            await self.stop(key, delay)

    def force_kill(self, key: str) -> None:
        svc = self.services[key]
        procs = svc.processes()
        if not procs:
            raise ServiceError(f"{svc.label} is not running.")
        for p in procs:
            try:
                p.kill()
            except psutil.NoSuchProcess:
                pass
        svc.message = f"{svc.label} was force-killed."

    # ---- GM commands ------------------------------------------------------------------
    # The browser console is read-only. The only input a server ever receives is a
    # validated command line from run_command (or the stop sequences above).

    async def run_command(self, command: str, timeout: float = 10.0) -> str:
        """Run a GM command on the worldserver console and return its reply text."""
        svc = self.services["world"]
        if svc.proc is None or svc.state != "running":
            if svc.state == "external":
                raise ServiceError("Worldserver was started outside the panel, so its console is not "
                                   "available. Set up SOAP in Settings, or start it from the panel.")
            raise ServiceError("Worldserver is not running.")
        command = command.strip().lstrip(".").replace("\r", " ").replace("\n", " ")
        if not command:
            raise ServiceError("Empty command.")
        async with svc.command_lock:
            collected: list[str] = []
            done = asyncio.Event()

            def listener(text: str) -> None:
                collected.append(text)
                # The console prints "AC> " when the command has finished.
                if "AC>" in "".join(collected).split(command, 1)[-1]:
                    done.set()

            svc.text_listeners.add(listener)
            try:
                svc.proc.write(command + "\r")
                try:
                    await asyncio.wait_for(done.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
            finally:
                svc.text_listeners.discard(listener)
        text = "".join(collected)
        if command in text:
            text = text.split(command, 1)[1]
        lines = [ln.rstrip() for ln in text.split("\n")]
        return "\n".join(ln for ln in lines if ln.strip() and ln.strip() != "AC>").strip()

    # ---- status ----------------------------------------------------------------------

    def snapshot(self) -> dict:
        try:
            cfg = self.config() if self.settings.configured else None
        except ValueError:
            cfg = None
        out = {}
        for key, svc in self.services.items():
            last = svc.samples[-1] if svc.samples else None
            root = None if svc.proc else _root(svc.processes())
            out[key] = {
                "key": key,
                "label": svc.label,
                "managed": self.managed(key),
                "state": svc.state,
                "owned": svc.proc is not None,
                "pid": svc.proc.pid if svc.proc else (root.pid if root else None),
                "started_at": svc.started_at,
                "port": self._endpoint(key, cfg)[1] if cfg else None,
                "cpu": last["cpu"] if last else None,
                "memory": last["mem"] if last else None,
                "history": list(svc.samples),
                "message": svc.message,
                "last_exit": svc.last_exit,
            }
        return {"services": out, "job": self.job, "last_job": self.last_job}

    # ---- panel shutdown ---------------------------------------------------------------

    async def shutdown(self) -> None:
        """Called when the panel exits: safely stop everything the panel started.
        Processes started outside the panel are left alone."""
        if self._job_task and not self._job_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._job_task), 900)
            except asyncio.TimeoutError:
                pass
        if any(s.proc for s in self.services.values()):
            # If the panel owns MySQL, anything connected to it must stop first,
            # even if it was started outside the panel; otherwise only our own.
            owned_only = self.services["mysql"].proc is None
            try:
                await self.stop_all(owned_only=owned_only)
            except ServiceError as exc:
                print(f"[shutdown] {exc}", file=sys.stderr)
        if self._monitor_task:
            self._monitor_task.cancel()
