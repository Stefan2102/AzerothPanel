r"""Database -> Import SQL: run an .sql file against one database with MySQL's own client (mysql.exe).

mysql.exe handles everything AzerothCore's SQL files use (DELIMITER blocks, many statements, large dumps).
The panel feeds the file to its stdin in chunks, which gives the progress and lets Cancel stop it; the login
goes in a temporary option file, never on the command line. Optionally the target database is dumped first
(mysqldump) to backups\before-import-<db>-<time>.sql, which can be imported the same way to undo.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from ..acconf import DbInfo
from ..paths import BACKUP_DIR, DATA_DIR
from .backup import find_mysql_tool, option_file
from .jobs import Cancelled, JobError, JobStore, LogFn, decode_line, kill_tree

CHUNK = 1024 * 1024
MAX_SIZE = 4 * 1024 ** 3          # 4 GB; larger files are better imported by hand
SHOWN_ERRORS = 5                  # skipped errors kept on the job for the result message (all are in the log)


def new_store() -> JobStore:
    return JobStore(DATA_DIR / "sql-import.json", max_jobs=100, max_log_lines=3000, log_dir=DATA_DIR / "sql-import-logs")


def check_file(path: str) -> Path:
    file = Path(path.strip().strip('"'))
    if not file.is_absolute() or not file.is_file():
        raise JobError("Choose an existing .sql file.")
    if file.suffix.lower() != ".sql":
        raise JobError("Only .sql files can be imported.")
    if file.stat().st_size > MAX_SIZE:
        raise JobError("That file is larger than 4 GB; import it with mysql.exe directly.")
    return file


class ImportJob:
    def __init__(self, info: DbInfo, mysql_dir: Path | None, file: Path, force: bool, backup: bool,
                 log: LogFn, progress: Callable[[dict], None]) -> None:
        self.info, self.mysql_dir, self.file, self.force, self.backup = info, mysql_dir, file, force, backup
        self.log, self._progress = log, progress
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.cancelled = False

    def cancel(self) -> None:
        with self._lock:
            self.cancelled = True
            proc = self._proc
        if proc and proc.poll() is None:
            kill_tree(proc.pid)

    def _check(self) -> None:
        if self.cancelled:
            raise Cancelled("Cancelled by the user.")

    def _start(self, args: list[str], **kw) -> subprocess.Popen:
        with self._lock:
            self._check()
            self._proc = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW, **kw)
            return self._proc

    def _tool(self, name: str) -> Path:
        exe = find_mysql_tool(self.mysql_dir, name)
        if exe is None:
            raise JobError(f"{name}.exe not found (choose the MySQL folder on Setup -> Requirements).")
        return exe

    def _dump(self) -> Path:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        target = BACKUP_DIR / f"before-import-{self.info.database}-{time.strftime('%Y%m%d-%H%M%S')}.sql"
        self._progress({"step": "backup", "progress": 0, "detail": f"Backing up {self.info.database}…"})
        self.log(f"[step] Backing up {self.info.database} to {target}")
        opt = option_file(self.info, DATA_DIR)
        try:
            with target.open("wb") as out:
                proc = self._start([str(self._tool("mysqldump")), f"--defaults-extra-file={opt}", "--single-transaction",
                                    "--routines", "--triggers", "--events", "--no-tablespaces", "--hex-blob",
                                    "--default-character-set=utf8mb4", "--databases", self.info.database],
                                   stdout=out, stderr=subprocess.PIPE)
                _, err = proc.communicate()
            self._check()
            if proc.returncode != 0:
                raise JobError(f"The backup failed, nothing was imported: {err.decode(errors='replace').strip()}")
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            opt.unlink(missing_ok=True)
        self.log(f"  ✓ {target.stat().st_size // 1024} KB. To undo the import, import this file the same way.")
        return target

    def _import(self) -> list[str]:
        """Feed the file to mysql.exe; returns the SQL errors it reported (skipped with --force)."""
        size = self.file.stat().st_size or 1
        self.log(f"[step] Importing {self.file.name} ({size // 1024} KB) into {self.info.database}"
                 + (" (continuing after errors)" if self.force else ""))
        errors: list[str] = []
        opt = option_file(self.info, DATA_DIR)
        try:
            proc = self._start([str(self._tool("mysql")), f"--defaults-extra-file={opt}", "--default-character-set=utf8mb4",
                                *(["--force"] if self.force else []), self.info.database],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

            def read() -> None:                       # MySQL's messages (errors carry "at line N")
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = decode_line(raw)
                    if line.startswith("ERROR"):
                        errors.append(line)
                    self.log(f"  {line}")

            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            done, last = 0, 0.0
            assert proc.stdin is not None
            try:
                with self.file.open("rb") as f:
                    while chunk := f.read(CHUNK):
                        self._check()
                        proc.stdin.write(chunk)
                        done += len(chunk)
                        if time.monotonic() - last > 0.5:
                            last = time.monotonic()
                            self._progress({"step": "import", "progress": min(99, int(done * 100 / size)),
                                            "detail": f"{done / CHUNK:.1f} / {size / CHUNK:.1f} MB"})
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass                                  # mysql.exe stopped (first error, or cancelled)
            code = proc.wait()
            reader.join(10)
        finally:
            opt.unlink(missing_ok=True)
        self._check()
        if code != 0 and not self.force:
            raise JobError(f"MySQL stopped at the first error: {errors[-1] if errors else f'exit code {code}'}. "
                           "Everything before it was already imported.")
        return errors

    def run_sync(self) -> dict:
        started = time.monotonic()
        backup = self._dump() if self.backup else None
        errors = self._import()
        self._progress({"step": "done", "progress": 100, "detail": None})
        self.log(f"[done] Imported {self.file.name} into {self.info.database}"
                 + (f" with {len(errors)} error(s) skipped (see above)." if errors else "."))
        return {"errors": len(errors), "first_errors": errors[:SHOWN_ERRORS], "backup_file": backup.name if backup else None, "duration": round(time.monotonic() - started)}
