"""A child process running inside a Windows pseudo console (ConPTY).

Why ConPTY instead of plain pipes: with redirected stdout the MSVC runtime
fully buffers output (authserver printed nothing until it exited), and
Ctrl-C can only be delivered to a process that owns a console. Inside a
pseudo console the servers behave exactly as in a normal console window:
live line-by-line output with colours, a real interactive prompt, and
writing "\\x03" to the input raises a normal Ctrl-C (graceful shutdown).
See docs/process-control.md.
"""
from __future__ import annotations

import asyncio
import ctypes
import threading
import time
from pathlib import Path
from typing import Callable

import psutil
from winpty import PTY, Backend, WinptyError


def enable_ctrl_c_for_children() -> None:
    """Clear this process's "ignore Ctrl-C" flag.

    Child processes inherit that flag. If the panel was launched with
    CREATE_NEW_PROCESS_GROUP (or by any tool that disables Ctrl-C), authserver and
    mysqld would silently ignore the Ctrl-C that stops them safely. Verified on
    2026-10-11: a panel launched that way could not stop authserver or MySQL.
    """
    ctypes.WinDLL("kernel32").SetConsoleCtrlHandler(None, False)


class ConPtyProcess:
    def __init__(self, exe: Path, args: str | None, cwd: Path, cols: int, rows: int,
                 loop: asyncio.AbstractEventLoop, on_output: Callable[[str], None]):
        self._exe = exe
        self._args = args
        self._cwd = cwd
        self._loop = loop
        self._on_output = on_output
        self._pty = PTY(cols, rows, backend=Backend.ConPTY)
        self._reader: threading.Thread | None = None
        self._tree: dict[int, psutil.Process] = {}
        self.pid: int = 0

    def start(self) -> None:
        # pywinpty builds the command line as "<appname> <cmdline>", so cmdline holds only the arguments.
        if not self._pty.spawn(str(self._exe), self._args, str(self._cwd)):
            raise RuntimeError(f"Could not start {self._exe.name}")
        self.pid = self._pty.pid
        try:
            self._tree[self.pid] = psutil.Process(self.pid)
        except psutil.NoSuchProcess:
            pass
        self._reader = threading.Thread(target=self._read_loop, name=f"pty-{self._exe.stem}", daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        while True:
            try:
                data = self._pty.read(blocking=True)
            except WinptyError:
                # Raised once the root process is gone. A child (mysqld's server
                # process) may still be writing its shutdown messages; keep trying
                # until the whole tree has exited.
                if self.alive():
                    time.sleep(0.2)
                    continue
                return
            if data:
                self._loop.call_soon_threadsafe(self._on_output, data)
            elif self._pty.iseof():
                return

    # ---- process tree -------------------------------------------------------
    # mysqld 8.4 on Windows runs as a monitor process plus a server child, and the
    # monitor exits before the server finishes its shutdown. "Exited" therefore
    # means the whole tree is gone, never just the first PID.

    def refresh_tree(self) -> None:
        for proc in list(self._tree.values()):
            try:
                for child in proc.children(recursive=True):
                    self._tree.setdefault(child.pid, child)
            except psutil.NoSuchProcess:
                continue

    def processes(self) -> list[psutil.Process]:
        alive = []
        for pid, proc in list(self._tree.items()):
            try:
                if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                    alive.append(proc)
                    continue
            except psutil.NoSuchProcess:
                pass
            self._tree.pop(pid, None)
        return alive

    def alive(self) -> bool:
        return bool(self.processes())

    def exit_code(self) -> int | None:
        try:
            return self._pty.get_exitstatus()
        except WinptyError:
            return None

    # ---- I/O ------------------------------------------------------------------

    def write(self, text: str) -> None:
        self._pty.write(text)

    def close(self) -> None:
        """Release the pseudo console. Call only after the process tree has exited,
        because closing a pseudo console terminates everything still attached to it."""
        try:
            self._pty.cancel_io()
        except (WinptyError, AttributeError):
            pass
        if self._reader:
            self._reader.join(timeout=2)
        del self._pty
