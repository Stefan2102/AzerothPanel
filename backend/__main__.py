"""Entry point.

  python -m backend start   start the panel in the background (if needed) and open the browser
  python -m backend stop    safely stop the servers the panel started, then the panel
  python -m backend run     run the panel in the foreground (used by `start`)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

import psutil

from .paths import ROOT_DIR, PANEL_LOG_FILE, PANEL_PID_FILE, ensure_dirs
from .security import new_control_token, read_control_token
from .settings import load_settings


def _url(path: str = "") -> str:
    s = load_settings()
    return f"http://{s.host}:{s.port}{path}"


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(_url("/api/health"), timeout=1) as r:
            return json.load(r).get("app") == "azerothpanel"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def run() -> int:
    import asyncio

    import uvicorn

    from .app import create_app
    from .services import audit, tls
    from .services.conpty import enable_ctrl_c_for_children

    enable_ctrl_c_for_children()
    ensure_dirs()
    settings = load_settings()
    app = create_app(settings, new_control_token())
    common = {"log_level": "warning", "timeout_graceful_shutdown": 5, "ws_ping_interval": 20}

    # Local listener (plain HTTP, this PC only). It owns the app lifespan:
    # monitor start, and the safe stop of all servers on exit.
    servers = [uvicorn.Server(uvicorn.Config(app, host=settings.host, port=settings.port, **common))]
    print(f"AzerothPanel listening on http://{settings.host}:{settings.port}", flush=True)

    # Remote listener (HTTPS on all interfaces), only when switched on in Settings.
    app.state.remote_active = None
    if settings.remote_enabled:
        try:
            cert, key = tls.paths(settings)
            tls.validate(cert, key)
            servers.append(uvicorn.Server(uvicorn.Config(
                app, host="0.0.0.0", port=settings.remote_port, lifespan="off",
                ssl_certfile=str(cert), ssl_keyfile=str(key), **common)))
            app.state.remote_active = settings.remote_port
            print(f"Remote access on https://0.0.0.0:{settings.remote_port}", flush=True)
        except tls.TlsError as exc:
            print(f"Remote access NOT started: {exc}", flush=True)
            audit.write("remote.error", f"remote access not started: {exc}", "ERROR", "panel")

    def request_exit() -> None:
        for s in servers:
            s.should_exit = True

    async def serve_remote(server: uvicorn.Server) -> None:
        # uvicorn exits via SystemExit when it can't bind; that must not stop the local panel.
        try:
            await server.serve()
        except SystemExit:
            app.state.remote_active = None
            msg = f"remote access stopped: port {settings.remote_port} could not be opened (in use?)"
            print(msg, flush=True)
            audit.write("remote.error", msg, "ERROR", "panel")

    async def serve() -> None:
        remote = asyncio.create_task(serve_remote(servers[1])) if len(servers) > 1 else None
        await servers[0].serve()            # the local listener decides the panel's lifetime
        request_exit()
        if remote:
            await remote

    app.state.request_exit = request_exit
    PANEL_PID_FILE.write_text(str(os.getpid()))
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass                                # Ctrl+C in a foreground run; servers were stopped already
    finally:
        PANEL_PID_FILE.unlink(missing_ok=True)
    print("AzerothPanel stopped.", flush=True)
    return 0


def start() -> int:
    if not _healthy():
        ensure_dirs()
        log = PANEL_LOG_FILE.open("ab")
        log.write(f"\n==== panel start {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n".encode())
        log.flush()
        proc = subprocess.Popen(
            [sys.executable, "-m", "backend", "run"], cwd=ROOT_DIR,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            # No CREATE_NEW_PROCESS_GROUP: it disables Ctrl-C for the panel and, by
            # inheritance, for every server it starts (their safe stop relies on Ctrl-C).
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for _ in range(100):
            if _healthy():
                break
            if proc.poll() is not None:
                print(f"The panel failed to start. See {PANEL_LOG_FILE}", file=sys.stderr)
                return 1
            time.sleep(0.2)
        else:
            print(f"The panel did not answer within 20 s. See {PANEL_LOG_FILE}", file=sys.stderr)
            return 1
    print(f"AzerothPanel is running at {_url()}")
    webbrowser.open(_url())
    return 0


def stop() -> int:
    if not _healthy():
        print("The panel is not running.")
        return 0
    token = read_control_token() or ""
    req = urllib.request.Request(_url("/api/control/shutdown"), method="POST", headers={"X-Control-Token": token})
    try:
        urllib.request.urlopen(req, timeout=5).close()
    except urllib.error.URLError as exc:
        print(f"Could not ask the panel to stop: {exc}", file=sys.stderr)
        return 1
    print("Stopping servers safely (worldserver -> authserver -> MySQL), then the panel...")
    # The HTTP port closes first; the process exits only after every server has shut down.
    try:
        pid = int(PANEL_PID_FILE.read_text())
        psutil.Process(pid).wait()
    except (OSError, ValueError, psutil.NoSuchProcess):
        pass
    print("Panel stopped.")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    commands = {"run": run, "start": start, "stop": stop}
    if command not in commands:
        print(__doc__)
        return 2
    return commands[command]()


if __name__ == "__main__":
    sys.exit(main())
