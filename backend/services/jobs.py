"""Persistent history of long-running jobs (backups, builds) and the helpers to run them.

A store keeps its jobs in one JSON file. Each job keeps the tail of its log in that file;
stores created with a log folder also write the complete log to <log_dir>/<id>.log
(build logs are far too large for the JSON file). `log_total` counts every line ever
logged, so a client can ask for only the lines after the ones it already has.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable, TextIO

import psutil

LogFn = Callable[[str], None]


class JobError(Exception):
    """A request that cannot be carried out (shown to the user as-is)."""


class Cancelled(Exception):
    """The user cancelled the job."""


class JobStore:
    """Jobs persisted to one JSON file (thread-safe). Subclasses may keep more keys in the same file."""

    def __init__(self, state_file: Path, defaults: dict | None = None, max_jobs: int = 200,
                 max_log_lines: int = 1000, log_dir: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._file = state_file
        self._max_jobs = max_jobs
        self._max_log = max_log_lines
        self._log_dir = log_dir
        self._handles: dict[int, TextIO] = {}
        state_file.parent.mkdir(parents=True, exist_ok=True)
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)
        if state_file.is_file():
            self._state = json.loads(state_file.read_text(encoding="utf-8"))
        else:
            self._state = {**(defaults or {}), "jobs": [], "next_job_id": 1}
        # A job still "running" here was interrupted by a panel stop.
        for job in self._state["jobs"]:
            if job["status"] == "running":
                job.update(status="failed", error="The panel stopped while this job was running.", finished=time.time())
        self._save()

    def _save(self) -> None:
        tmp = self._file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=1), encoding="utf-8")
        os.replace(tmp, self._file)

    def _find(self, job_id: int) -> dict | None:
        return next((j for j in self._state["jobs"] if j["id"] == job_id), None)

    def jobs(self) -> list[dict]:
        with self._lock:
            return [{k: v for k, v in j.items() if k != "log"} for j in reversed(self._state["jobs"])]

    def job(self, job_id: int, after: int | None = None) -> dict:
        """One job with its log tail. With `after`, only lines numbered above it (0-based count)."""
        with self._lock:
            j = self._find(job_id)
            if j is None:
                raise JobError("Unknown job.")
            out = json.loads(json.dumps(j))
        total = out.setdefault("log_total", len(out["log"]))
        first = total - len(out["log"])          # number of the first line still in the tail
        if after is not None:
            out["log"] = out["log"][max(0, after - first):]
            first = max(first, after)
        out["log_first"] = first
        return out

    def new_job(self, **fields) -> int:
        with self._lock:
            job_id = self._state["next_job_id"]
            self._state["next_job_id"] += 1
            self._state["jobs"].append({"id": job_id, "status": "running", "started": time.time(), "finished": None,
                                        "error": None, "log": [], "log_total": 0, **fields})
            removed = self._state["jobs"][:-self._max_jobs]
            self._state["jobs"] = self._state["jobs"][-self._max_jobs:]
            self._save()
        if self._log_dir:
            # Line-buffered, so a download while the job runs has everything up to now.
            self._handles[job_id] = (self._log_dir / f"{job_id}.log").open("w", encoding="utf-8", newline="\n", buffering=1)
            for old in removed:
                self.log_path(old["id"]).unlink(missing_ok=True)
        return job_id

    def update_job(self, job_id: int, save: bool = True, **fields) -> None:
        with self._lock:
            j = self._find(job_id)
            if j is not None:
                j.update(fields)
            if save:
                self._save()

    def log(self, job_id: int, line: str) -> None:
        with self._lock:
            j = self._find(job_id)
            if j is None:
                return
            j["log_total"] = j.get("log_total", len(j["log"])) + 1   # records from before log_total existed
            j["log"].append(line)
            if len(j["log"]) > self._max_log:
                del j["log"][: len(j["log"]) - self._max_log]
            handle = self._handles.get(job_id)
            if handle:
                handle.write(line + "\n")

    def finish(self, job_id: int, error: str | None = None, status: str | None = None, **fields) -> None:
        handle = self._handles.pop(job_id, None)
        if handle:
            handle.close()
        self.update_job(job_id, status=status or ("failed" if error else "completed"), error=error,
                        finished=time.time(), **fields)

    def delete_job(self, job_id: int) -> None:
        with self._lock:
            self._state["jobs"] = [j for j in self._state["jobs"] if j["id"] != job_id]
            self._save()
        if self._log_dir:
            self.log_path(job_id).unlink(missing_ok=True)

    def log_path(self, job_id: int) -> Path:
        if not self._log_dir:
            raise JobError("This job type keeps no log file.")
        return self._log_dir / f"{job_id}.log"


def start(store: JobStore, job_id: int, work: Callable[[LogFn], Awaitable[dict | None]]) -> asyncio.Task:
    """Run `work(log)` as a background task; its result fields are stored on the job."""
    async def runner() -> None:
        try:
            result = await work(lambda line: store.log(job_id, line))
        except asyncio.CancelledError:
            store.log(job_id, "[ERROR] Cancelled.")
            store.finish(job_id, error="Cancelled.", status="cancelled")
            raise
        except Exception as exc:  # reported to the user in the job record
            store.log(job_id, f"[ERROR] {exc}")
            store.finish(job_id, error=str(exc), status="cancelled" if isinstance(exc, Cancelled) else None)
        else:
            store.finish(job_id, **(result or {}))

    return asyncio.create_task(runner(), name=f"job-{job_id}")


# ---- child processes --------------------------------------------------------------------------

_LINE_END = re.compile(rb"\r*\n|\r+(?=[^\r\n])")    # a line end (any \r before \n) | a progress update (lone \r)
_OEM = f"cp{ctypes.windll.kernel32.GetOEMCP()}"
_GIT_PROGRESS = re.compile(r"^(Receiving objects|Resolving deltas|Updating files):\s+(\d+)%")
_GIT_DONE = re.compile(r",\s*done\.?$")


def git_progress(text: str) -> tuple[str, int, str] | None:
    """A git --progress line as (stage, percent, detail). The detail keeps git's size and speed
    ("Receiving objects: 9% (21956/225075), 21.33 MiB | 301.00 KiB/s"): the percentage counts objects,
    so it can sit still for minutes while large files arrive. None for other lines."""
    m = _GIT_PROGRESS.match(text)
    if not m:
        return None
    return m.group(1), int(m.group(2)), re.sub(r"\s+", " ", _GIT_DONE.sub("", text.strip()))


def decode_line(raw: bytes) -> str:
    """Console tools write UTF-8 or the OEM code page depending on the tool; accept both."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode(_OEM, errors="replace")
    return text.rstrip("\r\n")


def kill_tree(pid: int) -> None:
    try:
        root = psutil.Process(pid)
        procs = root.children(recursive=True) + [root]
    except psutil.NoSuchProcess:
        return
    for p in procs:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=10)


class ProcessRunner:
    """Runs one child process at a time for a job, with cancel support (kills the whole tree)."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            proc = self._proc
        if proc and proc.poll() is None:
            kill_tree(proc.pid)

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled("Cancelled by the user.")

    def run(self, args: list[str], cwd: Path | None, on_line: LogFn, env: dict | None = None,
            on_progress: LogFn | None = None) -> int:
        """Blocking: run to completion, streaming merged stdout/stderr lines. Returns the exit code.

        With on_progress, text ended by a carriage return (progress meters such as git's
        "Receiving objects:  45%") goes there live instead of being logged as lines."""
        self.check()
        with self._lock:
            self._proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            proc = self._proc
        try:
            assert proc.stdout is not None
            if on_progress is None:
                for raw in proc.stdout:
                    on_line(decode_line(raw))
            else:
                buf = b""
                while chunk := proc.stdout.read1(4096):
                    buf += chunk
                    # "\r\n" ends a line; a lone "\r" ends a progress update that overwrites the previous one.
                    while (m := _LINE_END.search(buf)) is not None:
                        piece, buf = buf[:m.start()], buf[m.end():]
                        if m.group() == b"\r":
                            on_progress(decode_line(piece))
                        elif piece:
                            on_line(decode_line(piece))
                if buf:
                    on_line(decode_line(buf))
            code = proc.wait()
        finally:
            with self._lock:
                self._proc = None
        self.check()
        return code


class JobSlot:
    """A job store plus the one job that may run in it at a time (build, client data, ...)."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.task: asyncio.Task | None = None
        self.job = None              # object with cancel(); the running job's worker

    def busy(self) -> bool:
        return self.task is not None and not self.task.done()

    def start(self, job_id: int, job, work: Callable[[LogFn], Awaitable[dict | None]]) -> None:
        self.job = job
        self.task = start(self.store, job_id, work)

    def running(self) -> dict | None:
        """The running job's record (without its log), for /api/status."""
        if not self.busy():
            return None
        return next((j for j in self.store.jobs() if j["status"] == "running"), None)

    def cancel(self, job_id: int) -> bool:
        current = self.running()
        if current is None or current["id"] != job_id or self.job is None:
            return False
        self.job.cancel()
        return True

    async def shutdown(self, timeout: float = 60) -> None:
        """Panel is exiting: cancel the running job and wait until it has been recorded."""
        if self.busy() and self.job is not None:
            self.job.cancel()
            try:
                await asyncio.wait_for(self.task, timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
