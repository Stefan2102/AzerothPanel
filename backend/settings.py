r"""Panel settings stored in data/settings.json.

Only things the AzerothCore configs cannot tell us live here: the AzerothCore folder
and how the panel itself behaves. Database credentials, ports and log locations are
always read from worldserver.conf / authserver.conf.

Source, build and server have their fixed place inside the one folder you choose (LAYOUT):
    <root>\source             git checkout that Compilation builds
    <root>\build              CMake build folder
    <root>\install\server     worldserver, authserver, configs, data, logs (deploy target)
The portable MySQL (the extracted ZIP) can be anywhere; the user chooses it (mysql_dir), e.g. <root>\install\database.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .paths import SETTINGS_FILE, ensure_dirs


LAYOUT = {"source": "source", "build": "build", "server": "install/server"}


@dataclass
class Settings:
    root_dir: str = ""            # the AzerothCore folder; everything else has a fixed place in it (LAYOUT)
    host: str = "127.0.0.1"
    port: int = 8090
    session_hours: int = 12
    world_shutdown_delay: int = 10  # seconds of in-game countdown on a safe world stop
    soap_username: str = ""         # game account (GM level 3) for worldserver SOAP
    soap_password: str = ""         # kept in data/settings.json; SOAP needs it in clear text
    remote_enabled: bool = False    # extra HTTPS listener on all interfaces (other devices)
    remote_port: int = 8443
    tls_cert: str = ""              # own certificate + key; empty = self-signed in data/tls
    tls_key: str = ""
    # Build tools (installed system-wide). Empty = use what was detected; a value is the user's
    # override, kept until "Reset to detected".
    cmake_exe: str = ""
    vs_instance: str = ""           # Visual Studio installation folder
    boost_dir: str = ""
    openssl_dir: str = ""
    mysql_dir: str = ""             # portable MySQL folder (has bin\mysqld.exe), chosen on Setup -> Requirements
    build_options: dict = field(default_factory=dict)   # last used Compilation options
    client_dir: str = ""            # WoW 3.3.5a client folder last used for Data Extraction
    # Values the panel writes into the server configs (services/config_values.py):
    # MySQL connection {host, port, user, password}, set by Database setup or on Config Files, and the
    # path values (DataDir, LogsDir, MySQLExecutable) changed on Config Files (missing key = default).
    db_connection: dict = field(default_factory=dict)
    config_paths: dict = field(default_factory=dict)

    def _part(self, key: str) -> Path:
        return Path(self.root_dir) / LAYOUT[key]

    @property
    def source_path(self) -> Path | None:
        return self._part("source") if self.root_dir else None

    @property
    def build_path(self) -> Path | None:
        return self._part("build") if self.root_dir else None

    @property
    def server_dir(self) -> str:
        r"""<root>\install\server, or "" while no AzerothCore folder is chosen."""
        return str(self._part("server")) if self.root_dir else ""

    @property
    def server_path(self) -> Path:
        r"""<root>\install\server. Only meaningful when root_dir is set (see `configured`)."""
        return self._part("server")

    @property
    def mysql_home(self) -> Path | None:
        r"""The chosen MySQL folder (it may have been moved or deleted since), None until one is chosen."""
        return Path(self.mysql_dir) if self.mysql_dir else None

    @property
    def mysql_path(self) -> Path | None:
        r"""The MySQL the panel starts and stops: mysql_home while it has bin\mysqld.exe, else None
        (MySQL then isn't managed by the panel, e.g. a Windows service)."""
        home = self.mysql_home
        return home if home and (home / "bin" / "mysqld.exe").is_file() else None

    @property
    def configured(self) -> bool:
        """Deployed: the server folder has worldserver.exe (the server pages need it)."""
        return bool(self.root_dir) and (self.server_path / "worldserver.exe").is_file()

    def paths(self) -> dict[str, str]:
        return {k: str(self._part(k)) for k in LAYOUT} if self.root_dir else {}


def load_settings() -> Settings:
    if not SETTINGS_FILE.is_file():
        return Settings()
    raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    if not raw.get("root_dir") and raw.get("server_dir"):
        raw["root_dir"] = _root_from_server(Path(raw["server_dir"]))
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save_settings(settings: Settings) -> None:
    ensure_dirs()
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, SETTINGS_FILE)


def _root_from_server(server: Path) -> str:
    r"""Settings from before the fixed layout stored the server folder; <root>\install\server gives the root."""
    if server.name.lower() == "server" and server.parent.name.lower() == "install":
        return str(server.parent.parent)
    return ""
