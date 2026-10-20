"""Backup & restore: destinations, backup jobs (zip archives) and restore.

Archive layout (azeroth-backup-YYYYMMDD-HHMMSS.zip):
  manifest.json                created, notes, what is included, database names
  configs/<relative path>      every *.conf below the server's configs folder
  databases/<name>.sql         mysqldump --databases (recreates its tables on import)
  binaries/<file>              top-level files of the server folder (exe, dll, pdb, ...)

Destinations are local folders for now; the record has a "type" so other kinds can be
added later. The built-in "Default Local Storage" is the repo's backups folder.
State (destinations + job history) lives in data/backup.json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from ..acconf import DbInfo, ServerConfig
from ..paths import BACKUP_DIR, DATA_DIR, ensure_dirs
from .jobs import JobError, JobStore

STATE_FILE = DATA_DIR / "backup.json"
DEFAULT_DEST_ID = 0
MAX_JOBS = 200
MAX_LOG_LINES = 1000
ARCHIVE_PREFIX = "azeroth-backup-"


class BackupError(JobError):
    """A request that cannot be carried out (shown to the user as-is)."""


# ---- tools ---------------------------------------------------------------------------

def find_mysql_tool(mysql_dir: Path | None, name: str) -> Path | None:
    if mysql_dir and (mysql_dir / "bin" / f"{name}.exe").is_file():
        return mysql_dir / "bin" / f"{name}.exe"
    found = shutil.which(name)
    return Path(found) if found else None


def find_mysqldump(mysql_dir: Path | None) -> Path | None:
    return find_mysql_tool(mysql_dir, "mysqldump")


def remove_stale_option_files() -> None:
    """Delete option files left by a panel that was killed while a MySQL tool ran (they hold a password)."""
    for f in DATA_DIR.glob("mysql-*.cnf"):
        f.unlink(missing_ok=True)


def option_file(info: DbInfo, folder: Path) -> Path:
    """Temporary [client] option file so the password never appears on a command line."""
    fd, path = tempfile.mkstemp(prefix="mysql-", suffix=".cnf", dir=folder)
    password = info.password.replace("\\", "\\\\").replace('"', '\\"')
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"[client]\nuser={info.user}\npassword=\"{password}\"\nhost={info.host}\nport={info.port}\n")
    return Path(path)


def dump_command(mysqldump: Path, database: str) -> list[str]:
    """mysqldump of one database that recreates it on import (the login goes in an option file)."""
    return [str(mysqldump), "--single-transaction", "--routines", "--triggers", "--events", "--no-tablespaces",
            "--hex-blob", "--default-character-set=utf8mb4", "--databases", database]


def _run_mysql_tool(args: list[str], info: DbInfo, stdin=None, stdout=None) -> None:
    opt = option_file(info, DATA_DIR)
    try:
        proc = subprocess.run([args[0], f"--defaults-extra-file={opt}", *args[1:]], stdin=stdin, stdout=stdout,
                              stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        opt.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise BackupError(proc.stderr.decode(errors="replace").strip() or f"{Path(args[0]).name} failed")


# ---- state ---------------------------------------------------------------------------

class BackupStore(JobStore):
    """Destinations and job history, persisted to data/backup.json (thread-safe)."""

    def __init__(self) -> None:
        ensure_dirs()
        super().__init__(STATE_FILE, defaults={"destinations": [], "next_dest_id": 1},
                         max_jobs=MAX_JOBS, max_log_lines=MAX_LOG_LINES)

    # destinations
    def destinations(self) -> list[dict]:
        default = {"id": DEFAULT_DEST_ID, "name": "Default Local Storage", "type": "local",
                   "path": str(BACKUP_DIR), "enabled": True, "builtin": True}
        with self._lock:
            return [default, *[{**d, "builtin": False} for d in self._state["destinations"]]]

    def destination(self, dest_id: int) -> dict:
        for d in self.destinations():
            if d["id"] == dest_id:
                return d
        raise BackupError("Unknown destination.")

    def add_destination(self, name: str, path: str, enabled: bool) -> dict:
        with self._lock:
            dest = {"id": self._state["next_dest_id"], "name": name, "type": "local", "path": path, "enabled": enabled}
            self._state["next_dest_id"] += 1
            self._state["destinations"].append(dest)
            self._save()
            return dest

    def update_destination(self, dest_id: int, name: str, path: str, enabled: bool) -> None:
        with self._lock:
            for d in self._state["destinations"]:
                if d["id"] == dest_id:
                    d.update(name=name, path=path, enabled=enabled)
                    self._save()
                    return
        raise BackupError("Unknown destination (the default one can't be edited).")

    def delete_destination(self, dest_id: int) -> None:
        with self._lock:
            before = len(self._state["destinations"])
            self._state["destinations"] = [d for d in self._state["destinations"] if d["id"] != dest_id]
            if len(self._state["destinations"]) == before:
                raise BackupError("Unknown destination (the default one can't be deleted).")
            self._save()


# ---- destination helpers ---------------------------------------------------------------

def test_destination(path: str) -> str:
    folder = Path(path)
    if not folder.is_absolute():
        raise BackupError("Use a full folder path, e.g. D:\\Backups\\AzerothCore.")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".write-test-{os.getpid()}"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        raise BackupError(f"Can't write to {folder}: {exc.strerror or exc}") from exc
    free = shutil.disk_usage(folder).free
    return f"Writable · {free / 1024**3:.1f} GB free"


def list_archives(path: str) -> list[dict]:
    folder = Path(path)
    if not folder.is_dir():
        return []
    files = []
    for p in sorted(folder.glob(f"{ARCHIVE_PREFIX}*.zip"), reverse=True):
        st = p.stat()
        files.append({"filename": p.name, "size": st.st_size, "modified": st.st_mtime})
    return files


def archive_path(dest: dict, filename: str) -> Path:
    if Path(filename).name != filename or not filename.startswith(ARCHIVE_PREFIX) or not filename.endswith(".zip"):
        raise BackupError("Invalid backup file name.")
    return Path(dest["path"]) / filename


# ---- backup ------------------------------------------------------------------------------

def run_backup(cfg: ServerConfig, mysql_dir: Path | None, dest: dict, include: dict, notes: str,
               log: Callable[[str], None]) -> tuple[str, int]:
    """Create the archive in the destination folder. Returns (file name, size)."""
    folder = Path(dest["path"])
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = f"{ARCHIVE_PREFIX}{stamp}.zip"
    final, partial = folder / name, folder / f"{name}.partial"
    work = Path(tempfile.mkdtemp(prefix="backup-", dir=folder))
    log(f"[INFO] Backup started: {name}")
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            manifest = {"created": time.time(), "notes": notes, "include": include, "app": "AzerothPanel",
                        "databases": {k: v.database for k, v in cfg.databases.items()}}
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            if include.get("configs"):
                log("[INFO] Collecting config files…")
                for p in sorted(cfg.configs_dir.rglob("*.conf")):
                    rel = p.relative_to(cfg.configs_dir).as_posix()
                    zf.write(p, f"configs/{rel}")
                    log(f"  + {rel}")

            if include.get("databases"):
                dump = find_mysqldump(mysql_dir)
                if dump is None:
                    raise BackupError("mysqldump.exe not found (choose the MySQL folder on Setup -> Requirements).")
                log("[INFO] Dumping databases…")
                for info in cfg.databases.values():
                    out = work / f"{info.database}.sql"
                    log(f"  Dumping {info.database}…")
                    with out.open("wb") as f:
                        _run_mysql_tool(dump_command(dump, info.database), info, stdout=f)
                    log(f"  ✓ {info.database}: {out.stat().st_size // 1024} KB, compressing…")
                    zf.write(out, f"databases/{out.name}")
                    out.unlink()

            if include.get("binaries"):
                log("[INFO] Archiving server binaries…")
                for p in sorted(cfg.server_dir.iterdir()):
                    if p.is_file():
                        zf.write(p, f"binaries/{p.name}")
                        log(f"  + {p.name}")

        os.replace(partial, final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    size = final.stat().st_size
    log(f"[INFO] Archive size: {size // 1024} KB")
    log(f"[INFO] Saved to {final}")
    return name, size


# ---- restore --------------------------------------------------------------------------------

def _safe_target(base: Path, rel: str) -> Path:
    """Resolve an archive member below base; refuse anything that escapes it."""
    parts = PurePosixPath(rel).parts
    if not parts or any(p in ("..", "") or ":" in p for p in parts):
        raise BackupError(f"Unsafe path in archive: {rel}")
    target = base.joinpath(*parts)
    if base.resolve() not in target.resolve().parents:
        raise BackupError(f"Unsafe path in archive: {rel}")
    return target


def run_restore(cfg: ServerConfig, mysql_dir: Path | None, archive: Path, options: dict,
                log: Callable[[str], None]) -> None:
    """Restore the chosen parts. The caller has verified that world and auth are stopped."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log(f"[INFO] Starting restore from: {archive.name}")
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()

        if options.get("configs"):
            members = [n for n in names if n.startswith("configs/") and not n.endswith("/")]
            log(f"[INFO] Restoring {len(members)} config files (current files kept as .{stamp}.bak)…")
            for n in members:
                target = _safe_target(cfg.configs_dir, n[len("configs/"):])
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.is_file():
                    shutil.copy2(target, target.with_name(f"{target.name}.{stamp}.bak"))
                target.write_bytes(zf.read(n))
                log(f"  ✓ {n[len('configs/'):]}")

        dumps = [n for n in names if n.startswith("databases/") and n.endswith(".sql")]
        if options.get("databases") and dumps:
            client = find_mysql_tool(mysql_dir, "mysql")
            if client is None:
                raise BackupError("mysql.exe not found (choose the MySQL folder on Setup -> Requirements).")
            by_name = {info.database: info for info in cfg.databases.values()}
            for n in dumps:
                db_name = PurePosixPath(n).stem
                info = by_name.get(db_name) or cfg.login_db
                log(f"  Importing {db_name}…")
                work = Path(tempfile.mkdtemp(prefix="restore-", dir=archive.parent))
                try:
                    sql = work / f"{db_name}.sql"
                    with zf.open(n) as src, sql.open("wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    with sql.open("rb") as f:
                        _run_mysql_tool([str(client), "--default-character-set=utf8mb4"], info, stdin=f)
                finally:
                    shutil.rmtree(work, ignore_errors=True)
                log(f"  ✓ {db_name}")

        if options.get("binaries"):
            members = [n for n in names if n.startswith("binaries/") and not n.endswith("/")]
            log(f"[INFO] Restoring {len(members)} server files…")
            for n in members:
                target = _safe_target(cfg.server_dir, n[len("binaries/"):])
                with zf.open(n) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                log(f"  ✓ {target.name}")
    log("[INFO] Restore finished.")
