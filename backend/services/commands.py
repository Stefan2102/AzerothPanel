"""GM command routing: SOAP first, worldserver console as fallback.

SOAP gives exact replies and also works when worldserver was started outside the
panel. The console is used when SOAP is not set up or nothing answers on its port.
SOAP refusing the request (wrong credentials, GM level too low) is reported, not
silently bypassed, so a broken setup is noticed.
"""
from __future__ import annotations

from ..acconf import ServerConfig
from ..settings import Settings
from . import soap
from .server_manager import ServerManager, ServiceError


def soap_configured(cfg: ServerConfig | None, settings: Settings) -> bool:
    return bool(cfg and cfg.soap_enabled and settings.soap_username and settings.soap_password)


def availability(manager: ServerManager, cfg: ServerConfig | None, settings: Settings) -> dict:
    """What the UI may offer right now."""
    world = manager.services["world"]
    via_soap = soap_configured(cfg, settings) and world.state in ("running", "external")
    via_console = world.state == "running" and world.proc is not None
    return {"available": via_soap or via_console, "soap": via_soap, "console": via_console}


async def run_gm_command(manager: ServerManager, settings: Settings, command: str) -> dict:
    command = command.strip().lstrip(".")
    if not command:
        raise ServiceError("Empty command.")
    cfg = manager.config()
    world = manager.services["world"]
    if soap_configured(cfg, settings) and world.state in ("running", "external"):
        try:
            ok, output = await soap.execute(cfg.soap_host, cfg.soap_port, settings.soap_username,
                                            settings.soap_password, command)
            return {"output": output, "ok": ok, "via": "soap"}
        except soap.SoapUnavailable:
            if world.proc is None:
                raise ServiceError("Worldserver SOAP is not reachable and the console is not available "
                                   "(worldserver was started outside the panel).")
        except soap.SoapError as exc:
            raise ServiceError(str(exc)) from exc
    output = await manager.run_command(command)
    return {"output": output, "ok": True, "via": "console"}
