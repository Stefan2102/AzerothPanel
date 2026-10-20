"""Reader for AzerothCore .conf files (worldserver.conf, authserver.conf, module configs).

The panel never duplicates values that already live in these files; it reads
them on demand (cached by file modification time).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_cache: dict[Path, tuple[float, dict[str, str]]] = {}


def parse_conf(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "[")) or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        values[key.strip()] = value
    return values


def read_conf(path: Path) -> dict[str, str]:
    """Parse a .conf file; falls back to the .conf.dist template if the .conf is missing."""
    if not path.is_file():
        dist = path.with_name(path.name + ".dist")
        if not dist.is_file():
            return {}
        path = dist
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    values = parse_conf(path.read_text(encoding="utf-8", errors="replace"))
    _cache[path] = (mtime, values)
    return values


@dataclass(frozen=True)
class DbInfo:
    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def parse(cls, value: str) -> "DbInfo":
        parts = value.split(";")
        if len(parts) < 5:
            raise ValueError(f"Malformed database info: {value!r}")
        host, port, user, password, database = parts[:5]
        if host == ".":
            raise ValueError("Named-pipe MySQL connections ('.') are not supported by the panel; use 127.0.0.1.")
        return cls(host, int(port), user, password, database)

    def public(self) -> dict:
        return {"host": self.host, "port": self.port, "user": self.user, "database": self.database}


@dataclass(frozen=True)
class ServerConfig:
    server_dir: Path
    world_conf: Path
    auth_conf: Path
    login_db: DbInfo
    world_db: DbInfo
    char_db: DbInfo
    realm_id: int
    world_port: int
    auth_port: int
    logs_dir: Path
    auth_logs_dir: Path
    data_dir: Path
    soap_enabled: bool
    soap_host: str
    soap_port: int
    playerbots_db: DbInfo | None = None   # set when mod-playerbots is installed

    @property
    def configs_dir(self) -> Path:
        return self.world_conf.parent

    @property
    def databases(self) -> dict[str, DbInfo]:
        dbs = {"auth": self.login_db, "characters": self.char_db, "world": self.world_db}
        if self.playerbots_db is not None:
            dbs["playerbots"] = self.playerbots_db
        return dbs


def _resolve(server_dir: Path, value: str, default: str) -> Path:
    p = Path(value or default)
    return p if p.is_absolute() else (server_dir / p).resolve()


def read_module_conf(configs_dir: Path, name: str) -> dict[str, str]:
    """A module config as worldserver sees it: <name>.dist defaults overridden by <name>.
    Empty when the module's config is not deployed (module not installed)."""
    conf = configs_dir / "modules" / name
    dist = conf.with_name(conf.name + ".dist")
    values: dict[str, str] = {}
    for path in (dist, conf):
        if path.is_file():
            values.update(read_conf(path))
    return values


def _playerbots_db(configs_dir: Path) -> DbInfo | None:
    # mod-playerbots keeps its own database: PlayerbotsDatabaseInfo in playerbots.conf.
    info = read_module_conf(configs_dir, "playerbots.conf").get("PlayerbotsDatabaseInfo")
    return DbInfo.parse(info) if info else None


def load_server_config(server_dir: Path) -> ServerConfig:
    world_conf = server_dir / "configs" / "worldserver.conf"
    auth_conf = server_dir / "configs" / "authserver.conf"
    w = read_conf(world_conf)
    a = read_conf(auth_conf)
    if not w:
        raise ValueError(f"Cannot read {world_conf}")
    return ServerConfig(
        server_dir=server_dir,
        world_conf=world_conf,
        auth_conf=auth_conf,
        login_db=DbInfo.parse(w.get("LoginDatabaseInfo", "")),
        world_db=DbInfo.parse(w.get("WorldDatabaseInfo", "")),
        char_db=DbInfo.parse(w.get("CharacterDatabaseInfo", "")),
        realm_id=int(w.get("RealmID", "1") or 1),
        world_port=int(w.get("WorldServerPort", "8085") or 8085),
        auth_port=int(a.get("RealmServerPort", "3724") or 3724),
        logs_dir=_resolve(server_dir, w.get("LogsDir", ""), "."),
        auth_logs_dir=_resolve(server_dir, a.get("LogsDir", ""), "."),
        data_dir=_resolve(server_dir, w.get("DataDir", ""), "."),
        soap_enabled=w.get("SOAP.Enabled", "0") == "1",
        soap_host=w.get("SOAP.IP", "127.0.0.1"),
        soap_port=int(w.get("SOAP.Port", "7878") or 7878),
        playerbots_db=_playerbots_db(world_conf.parent),
    )
