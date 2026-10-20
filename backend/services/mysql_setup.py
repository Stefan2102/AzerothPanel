"""Set up a fresh portable MySQL for AzerothCore: my.ini, initialise, account, databases.

Steps of a setup job (Setup page -> Database setup):
  1. write my.ini (port, utf8mb4, bind-address = the chosen host); an existing one is replaced
  2. mysqld --initialize-insecure  (root@localhost without password; refused if data\\ is initialised)
  3. start a temporary mysqld
  4. as root: CREATE USER IF NOT EXISTS, GRANT ALL ON *.* WITH GRANT OPTION, CREATE DATABASE IF NOT EXISTS
  5. log in as the new account; only then drop every root account + FLUSH PRIVILEGES
  6. stop the temporary mysqld cleanly (mysqladmin shutdown)
The server configs are not touched: the connection is remembered (settings.db_connection) and put into
the configs on Config Files -> "Paths for this setup" (services/config_values.py).
The temporary server always listens on 127.0.0.1 (root may only log in locally); the chosen host applies
from the first normal start. The account is <user>@'localhost' for a loopback host, otherwise <user>@'%'
(the servers then connect through that address, which MySQL does not count as localhost).
Which databases: the core ones from Login/World/CharacterDatabaseInfo, plus every *DatabaseInfo key
of the installed modules (mod-playerbots -> acore_playerbots). Tables are created by AzerothCore's own
updater (Updates.AutoSetup) on the first server start. See docs/database.md.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

import pymysql

from ..acconf import DbInfo, parse_conf
from ..paths import DATA_DIR
from .jobs import Cancelled, JobError, JobStore, LogFn, ProcessRunner

CORE_KEYS = ("LoginDatabaseInfo", "WorldDatabaseInfo", "CharacterDatabaseInfo")
_DB_KEY = re.compile(r"^(\w+DatabaseInfo)$")
_NAME = re.compile(r"^[A-Za-z0-9_$]{1,64}$")
_USER = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_INFO_LINE = re.compile(r'^(\s*)(\w+DatabaseInfo)(\s*=\s*)"([^"]*)"', re.M)
CTRL_HELPER = Path(__file__).with_name("ctrl_event.py")
MY_INI = """# Written by AzerothPanel (Setup -> Database setup)
[mysqld]
basedir=./
datadir=./data
port={port}
bind-address={host}
mysqlx-bind-address={host}
sql-mode=""
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
max_allowed_packet=128M

[client]
port={port}
"""


def new_store() -> JobStore:
    return JobStore(DATA_DIR / "db-setup.json", max_jobs=50, max_log_lines=2000, log_dir=DATA_DIR / "db-setup-logs")


# ---- what is there --------------------------------------------------------------------------------

def _read(path: Path) -> dict[str, str]:
    return parse_conf(path.read_text(encoding="utf-8", errors="replace")) if path.is_file() else {}


def ini_port(mysql_dir: Path) -> int | None:
    ini = mysql_dir / "my.ini"
    if not ini.is_file():
        return None
    m = re.search(r"^\s*port\s*=\s*(\d+)", ini.read_text(encoding="utf-8", errors="replace"), re.M)
    return int(m.group(1)) if m else None


def ini_host(mysql_dir: Path) -> str | None:
    ini = mysql_dir / "my.ini"
    if not ini.is_file():
        return None
    m = re.search(r"^\s*bind[-_]address\s*=\s*(\S+)", ini.read_text(encoding="utf-8", errors="replace"), re.M)
    return m.group(1) if m else None


def is_mysql_home(folder: Path) -> bool:
    return (folder / "bin" / "mysqld.exe").is_file()


def find_mysql_home(chosen: Path, depth: int = 2) -> Path:
    r"""The MySQL folder (the one with bin\mysqld.exe) for a folder the user picked: the folder itself, its parent
    when bin\ was picked, or the only one up to `depth` levels below it, whatever the folders are named
    (e.g. install\ -> install\database\mysql-8.4.11-winx64). Raises ValueError when there is none or several."""
    if is_mysql_home(chosen):
        return chosen
    if chosen.name.lower() == "bin" and is_mysql_home(chosen.parent):
        return chosen.parent
    found: list[Path] = []
    level = [chosen]
    for _ in range(depth):
        below: list[Path] = []
        for folder in level:
            try:
                with os.scandir(folder) as entries:
                    below += [Path(e.path) for e in entries if e.is_dir()
                              and not e.name.startswith(("$", ".")) and e.name.lower() != "data"]   # data: MySQL's own
            except OSError:
                continue
        level = []
        for folder in below:
            (found if is_mysql_home(folder) else level).append(folder)
    if not found:
        raise ValueError(f"No MySQL in {chosen}: no bin\\mysqld.exe in it or in the folders below it. "
                         "Choose the folder you extracted the MySQL ZIP into.")
    if len(found) > 1:
        raise ValueError(f"{chosen} has more than one MySQL ({', '.join(str(f) for f in found)}). Choose one of them.")
    return found[0]


def initialised(mysql_dir: Path) -> bool:
    return (mysql_dir / "data" / "mysql").is_dir()


def mysqld_version(mysql_dir: Path) -> str | None:
    exe = mysql_dir / "bin" / "mysqld.exe"
    if not exe.is_file():
        return None
    try:
        out = subprocess.run([str(exe), "--version"], capture_output=True, timeout=20,
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout.decode(errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Ver\s+(\d+\.\d+\.\d+)", out)
    return m.group(1) if m else None


def planned_databases(server_dir: Path | None, source: Path | None) -> list[dict]:
    """Databases to create: the core ones and every *DatabaseInfo of an installed module (no fixed list)."""
    out: dict[str, dict] = {}

    def add(value: str, reason: str) -> None:
        try:
            name = DbInfo.parse(value).database
        except ValueError:
            return
        if _NAME.match(name) and name not in out:
            out[name] = {"name": name, "reason": reason}

    core: dict[str, str] = {}
    if server_dir:
        core = _read(server_dir / "configs" / "worldserver.conf") or _read(server_dir / "configs" / "worldserver.conf.dist")
    if not core and source:
        core = _read(source / "src" / "server" / "apps" / "worldserver" / "worldserver.conf.dist")
    for key in CORE_KEYS:
        if core.get(key):
            add(core[key], "AzerothCore")

    module_confs: list[tuple[Path, str]] = []
    if source and (source / "modules").is_dir():
        for folder in sorted(p for p in (source / "modules").iterdir() if p.is_dir()):
            module_confs += [(f, folder.name) for f in sorted((folder / "conf").glob("*.conf.dist"))]
    if server_dir and (server_dir / "configs" / "modules").is_dir():
        for f in sorted((server_dir / "configs" / "modules").glob("*.conf*")):
            if f.suffix in (".conf", ".dist"):
                module_confs.append((f, f.name.split(".conf")[0]))
    for conf, module in module_confs:
        for key, value in _read(conf).items():
            if _DB_KEY.match(key) and key not in CORE_KEYS:
                add(value, f"module {module}")
    return list(out.values())


def status(mysql_dir: Path | None, server_dir: Path | None, source: Path | None) -> dict:
    ok = bool(mysql_dir and (mysql_dir / "bin" / "mysqld.exe").is_file())
    return {
        "mysql_dir": str(mysql_dir) if mysql_dir else "",
        "found": ok,
        "version": mysqld_version(mysql_dir) if ok else None,
        "my_ini": bool(mysql_dir and (mysql_dir / "my.ini").is_file()),
        "port": ini_port(mysql_dir) if mysql_dir else None,
        "host": ini_host(mysql_dir) if mysql_dir else None,
        "initialised": bool(mysql_dir and initialised(mysql_dir)),
        "databases": planned_databases(server_dir, source),
    }


# ---- server configs ---------------------------------------------------------------------------------

def apply_connection(path: Path, conn: dict) -> bool:
    """Point every *DatabaseInfo line of one config at conn (host, port, user, password); the database
    names stay. Returns whether the file changed. Used by Config Files (config_values)."""
    text = path.read_text(encoding="utf-8", errors="replace")

    def repl(m: re.Match) -> str:
        parts = m.group(4).split(";")
        database = parts[4] if len(parts) >= 5 else ""
        return f'{m.group(1)}{m.group(2)}{m.group(3)}"{conn["host"]};{conn["port"]};{conn["user"]};{conn["password"]};{database}"'

    new = _INFO_LINE.sub(repl, text)
    if new == text:
        return False
    path.write_text(new, encoding="utf-8")
    return True


# ---- the job --------------------------------------------------------------------------------------------

def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


class SetupJob:
    def __init__(self, mysql_dir: Path, options: dict, databases: list[str],
                 log: LogFn, progress: Callable[[dict], None]) -> None:
        self.dir, self.o, self.databases = mysql_dir, options, databases
        self.log, self._progress = log, progress
        self.runner = ProcessRunner()
        self.mysqld: subprocess.Popen | None = None      # only a server this job started itself
        self.port: int = options["port"]

    def cancel(self) -> None:
        self.runner.cancel()          # stops a running --initialize; the temporary server is shut down in run_sync

    def _step(self, name: str, progress: int, text: str) -> None:
        self.runner.check()
        self._progress({"step": name, "progress": progress})
        self.log(f"[step] {text}")

    # temporary server ----------------------------------------------------------------------------------
    def _start_server(self, port: int, reuse_running: bool) -> None:
        if _port_open(port):
            if reuse_running:
                self.log(f"  MySQL is already running on port {port}; using it.")
                return
            raise JobError(f"Port {port} is already in use (another MySQL running?). Stop it first.")
        exe = self.dir / "bin" / "mysqld.exe"
        self.log(f"> mysqld.exe --console  (temporary, port {port})")
        # Loopback only while setting up: root@localhost can only log in from this PC.
        self.mysqld = subprocess.Popen([str(exe), "--console", "--bind-address=127.0.0.1", "--mysqlx-bind-address=127.0.0.1"],
                                       cwd=self.dir, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW)

        def pump(proc: subprocess.Popen) -> None:
            for raw in proc.stdout:            # type: ignore[union-attr]
                self.log("  " + raw.decode("utf-8", errors="replace").rstrip())

        threading.Thread(target=pump, args=(self.mysqld,), daemon=True).start()
        deadline = time.monotonic() + 120
        while not _port_open(port):
            self.runner.check()
            if self.mysqld.poll() is not None:
                raise JobError(f"mysqld stopped during startup (exit code {self.mysqld.returncode}). See the log.")
            if time.monotonic() > deadline:
                raise JobError("mysqld did not open its port within 2 minutes.")
            time.sleep(0.5)

    def _stop_server(self, user: str, password: str) -> None:
        """Clean shutdown: mysqladmin shutdown; if that is refused, a console Ctrl-C (also clean)."""
        proc = self.mysqld
        if proc is None or proc.poll() is not None:
            return
        self.log("  Stopping the temporary mysqld")
        admin = self.dir / "bin" / "mysqladmin.exe"
        fd, opt = tempfile.mkstemp(prefix="mysql-", suffix=".cnf", dir=DATA_DIR)
        with open(fd, "w", encoding="utf-8") as f:
            pw = password.replace("\\", "\\\\").replace('"', '\\"')
            f.write(f'[client]\nuser={user}\npassword="{pw}"\nhost=127.0.0.1\nport={self.port}\n')
        try:
            done = subprocess.run([str(admin), f"--defaults-extra-file={opt}", "shutdown"], capture_output=True,
                                  timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        finally:
            Path(opt).unlink(missing_ok=True)
        if done.returncode != 0:
            subprocess.run([sys.executable, "-I", str(CTRL_HELPER), str(proc.pid), "c"],
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        try:
            proc.wait(timeout=300)
        except subprocess.TimeoutExpired as exc:
            raise JobError("The temporary mysqld did not stop within 5 minutes.") from exc
        self.mysqld = None

    def _connect(self, user: str, password: str):
        return pymysql.connect(host="127.0.0.1", port=self.port, user=user, password=password,
                               charset="utf8mb4", autocommit=True, connect_timeout=10)

    def _create_databases(self, cur) -> None:
        for name in self.databases:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            self.log(f"  ✓ database {name}")

    # main ----------------------------------------------------------------------------------------------
    def run_sync(self) -> dict:
        started = time.monotonic()
        user, password = self.o["user"], self.o["password"]
        fresh = not initialised(self.dir)
        admin = ("root", "")                    # who can log in while we work (switches to the new account)
        try:
            if fresh:
                # A fresh setup always writes my.ini with the chosen IP and port, replacing an existing one
                # (e.g. left behind when only the data folder was deleted).
                ini = self.dir / "my.ini"
                self._step("my_ini", 5, ("Replacing" if ini.is_file() else "Writing") + " my.ini")
                self.port = self.o["port"]
                ini.write_text(MY_INI.format(port=self.port, host=self.o["host"]), encoding="utf-8")
                self.log(f"  ✓ {ini} (port {self.port}, address {self.o['host']})")
                self._step("initialize", 10, "Initialising the data folder (mysqld --initialize-insecure)")
                code = self.runner.run([str(self.dir / "bin" / "mysqld.exe"), "--initialize-insecure", "--console"],
                                       self.dir, lambda line: self.log("  " + line))
                if code != 0 or not initialised(self.dir):
                    raise JobError(f"mysqld --initialize-insecure failed (exit code {code}). See the log.")
            else:
                self.port = ini_port(self.dir) or self.o["port"]
                admin = (user, password)
                self.log(f"  This MySQL is already set up; only missing databases are added (as {user}).")

            self._step("start", 40, "Starting a temporary MySQL")
            self._start_server(self.port, reuse_running=not fresh)

            self._step("account", 60, "Creating the account and databases" if fresh else "Adding missing databases")
            try:
                conn = self._connect(*admin)
            except pymysql.err.OperationalError as exc:
                raise JobError(f"Couldn't log in to MySQL as {admin[0]}: {exc.args[-1]}") from exc
            with conn, conn.cursor() as cur:
                if fresh:
                    account_host = "localhost" if is_loopback(self.o["host"]) else "%"
                    cur.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (user, account_host, password))
                    cur.execute("GRANT ALL PRIVILEGES ON *.* TO %s@%s WITH GRANT OPTION", (user, account_host))
                    self.log(f"  ✓ account {user}@{account_host} with all privileges")
                self._create_databases(cur)

            if fresh:
                # Prove the new account works before anything else changes.
                with self._connect(user, password) as conn, conn.cursor() as cur:
                    cur.execute("SHOW GRANTS")
                    # MySQL 8 lists the global privileges by name: "GRANT SELECT, ... ON *.* TO ... WITH GRANT OPTION".
                    grants = [r[0] for r in cur.fetchall()]
                    if not any(" ON *.* TO " in g and g.endswith("WITH GRANT OPTION") for g in grants):
                        raise JobError(f"The account {user} does not have the expected rights; root was kept.")
                    self.log(f"  ✓ logged in as {user}")
                    admin = (user, password)
                    cur.execute("SELECT user, host FROM mysql.user WHERE user = 'root'")
                    for root_user, root_host in cur.fetchall():
                        cur.execute("DROP USER %s@%s", (root_user, root_host))
                        self.log(f"  ✓ removed {root_user}@{root_host}")
                    cur.execute("FLUSH PRIVILEGES")

            self._step("stop", 80, "Stopping the temporary MySQL")
            self._stop_server(*admin)
        except BaseException:
            try:
                self._stop_server(*admin)
            except Exception as exc:  # noqa: BLE001 - report the original error, but say what happened
                self.log(f"[WARN] Couldn't stop the temporary mysqld cleanly: {exc}")
            if fresh and isinstance(sys.exc_info()[1], (JobError, Cancelled)):
                self.log(f"[WARN] To start over, delete {self.dir / 'data'} (it holds no AzerothCore data yet).")
            raise

        conn = {"host": self.o["host"], "port": self.port, "user": user, "password": password}
        self._progress({"step": "done", "progress": 100})
        if fresh:
            self.log("  The connection is remembered. Put it into the server configs on Config Files -> "
                     "Paths for this setup -> Save & apply.")
        self.log("[done] Database ready. Start MySQL on Server Control; the servers create the tables on their first start.")
        return {"port": self.port, "databases": self.databases, "duration": round(time.monotonic() - started),
                "connection": conn if fresh else None}
