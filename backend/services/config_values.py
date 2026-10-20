r"""Values the panel keeps in the server configs (Config Files -> "Paths for this setup").

- Paths: DataDir, LogsDir and MySQLExecutable. Defaults: the data and logs folders in install\server and
  mysql.exe of the chosen MySQL folder (settings.mysql_dir); every value can be changed and is saved in
  settings.config_paths.
- Database connection: host, port, account and password in every *DatabaseInfo line (the database
  names stay). Stored once in settings.db_connection, shared with Database setup.

They are written when deploy creates or replaces a config, and by "Save & apply" into the existing
ones. Only the value of an existing `Key = ...` line changes: comments, other lines and the .dist
templates are never touched, and a key a file doesn't have is not added.
"""
from __future__ import annotations

from pathlib import Path

from ..acconf import parse_conf
from ..settings import Settings
from . import conffile, mysql_setup

PATH_KEYS = ("DataDir", "LogsDir", "MySQLExecutable")


def default_paths(settings: Settings) -> dict[str, str]:
    """AzerothCore's templates use DataDir "." and LogsDir "" (the server folder itself) and an empty
    MySQLExecutable ("search PATH"); a portable MySQL isn't on PATH, so worldserver would stop with
    "Didn't find any executable MySQL binary"."""
    mysql = settings.mysql_home
    return {"DataDir": "./data", "LogsDir": "./logs",
            "MySQLExecutable": str(mysql / "bin" / "mysql.exe") if mysql else ""}


def paths(settings: Settings) -> dict[str, str]:
    """The path values in use: what was saved, else the defaults."""
    return {k: settings.config_paths.get(k, v) for k, v in default_paths(settings).items()}


def config_files(server: Path) -> list[Path]:
    """The server's .conf files (never the .dist templates)."""
    folder = server / "configs"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.conf")) + sorted((folder / "modules").glob("*.conf"))


def _conn_parts(value: str) -> list[str]:
    return (value.split(";") + [""] * 5)[:5]


def connection_from_configs(settings: Settings) -> dict:
    """{host, port, user, password} of the first *DatabaseInfo line in the configs (worldserver.conf first),
    for an existing installation whose connection the panel hasn't saved yet. {} if there is none."""
    if not settings.root_dir:
        return {}
    files = config_files(settings.server_path)
    files.sort(key=lambda f: f.name != "worldserver.conf")
    for f in files:
        for key, value in parse_conf(f.read_text(encoding="utf-8", errors="replace")).items():
            if key.endswith("DatabaseInfo"):
                host, port, user, password, _ = _conn_parts(value)
                if host and user and port.isdigit():
                    return {"host": host, "port": int(port), "user": user, "password": password}
    return {}


def status(settings: Settings) -> dict:
    """What the configs contain compared with the values above (passwords are never sent out).
    Without a saved connection, the one in the configs is shown (db.source = "configs")."""
    server = settings.server_path if settings.root_dir else None
    files = config_files(server) if server else []
    want = paths(settings)
    conn = settings.db_connection or connection_from_configs(settings)
    source = "saved" if settings.db_connection else ("configs" if conn else None)
    rows = {k: [] for k in PATH_KEYS}
    db_rows = []
    for f in files:
        values = parse_conf(f.read_text(encoding="utf-8", errors="replace"))
        name = f.relative_to(server / "configs").as_posix()
        for key in PATH_KEYS:
            if key in values:
                rows[key].append({"file": name, "current": values[key],
                                  "state": "applied" if values[key] == want[key] else "differs"})
        for key, value in values.items():
            if key.endswith("DatabaseInfo"):
                host, port, user, password, database = _conn_parts(value)
                same = bool(conn) and [host, port, user, password] == [conn["host"], str(conn["port"]), conn["user"], conn["password"]]
                db_rows.append({"file": name, "key": key, "current": f"{user}@{host}:{port}/{database}",
                                "state": "applied" if same else "differs"})
    return {
        "configs_found": bool(files),
        "server": str(server) if server else None,
        "paths": {k: {"value": want[k], "default": default_paths(settings)[k], "files": rows[k]} for k in PATH_KEYS},
        "db": {"host": conn.get("host", ""), "port": conn.get("port"), "user": conn.get("user", ""),
               "password_set": bool(conn.get("password")), "source": source, "files": db_rows},
    }


def apply_to(conf: Path, settings: Settings) -> list[str]:
    """Write the values into one config (only keys it has). Returns what changed, for the log."""
    changed = conffile.set_values(conf, paths(settings))
    if settings.db_connection and mysql_setup.apply_connection(conf, settings.db_connection):
        changed.append("database connection")
    return changed


def make_folders(settings: Settings) -> None:
    """Create the DataDir and LogsDir folders (relative values are inside the server folder, as
    worldserver and authserver resolve them from there)."""
    if not settings.root_dir:
        return
    for key in ("DataDir", "LogsDir"):
        value = paths(settings)[key].strip()
        if value:
            folder = Path(value)
            (folder if folder.is_absolute() else settings.server_path / folder).mkdir(parents=True, exist_ok=True)


def apply_all(settings: Settings) -> list[dict]:
    """Write the values into every existing config. Returns the changed files and what changed."""
    if not settings.root_dir:
        return []
    files = config_files(settings.server_path)
    if files:
        make_folders(settings)
    done = []
    for conf in files:
        changed = apply_to(conf, settings)
        if changed:
            done.append({"file": conf.relative_to(settings.server_path / "configs").as_posix(), "changed": changed})
    return done
