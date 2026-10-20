# AzerothPanel

A local, Windows-only web dashboard for an [AzerothCore](https://www.azerothcore.org/) 3.3.5a server.
No Docker: it runs the servers directly on your PC.

Hugely inspired by [Old-Man-Warcraft/AzerothPanel](https://github.com/Old-Man-Warcraft/AzerothPanel),
but coded from scratch.

## Features
- **Monitor:** dashboard, live read-only consoles of worldserver and authserver, logs.
- **Manage:** start / stop / restart with safe shutdowns (players are saved), players, database browser with
  read-only SQL, backup & restore.
- **Build & Deploy:**
  - **Setup:** requirements check with install notes, clone AzerothCore (official, playerbots fork or any
    repository and branch), portable MySQL setup.
  - **Compilation:** update the source, compile, deploy.
  - **Data Extraction:** download client data or extract it from your own 3.3.5a client.
  - **Modules:** catalogue from azerothcore.org; install, update and remove.
- **Configure:** the config values for this setup (paths, database connection), a config file editor, settings.

## Folder layout
Inside the AzerothCore folder you choose on Setup:

| Folder | Holds |
|---|---|
| `source` | AzerothCore source code (cloned on Setup) |
| `build` | compiler output |
| `install\server` | worldserver, authserver, configs, data, logs |

The portable MySQL can be anywhere (intended: `install\database`); choose its folder on Setup → Requirements.

## Quick start
Requirements: Windows 10/11, Python 3.11+ and Node.js 20+ in `PATH` (only needed to build the panel).

1. `install.bat`: installs the panel's packages and builds it (again after updating the panel).
2. `start.bat`: starts the panel and opens it in your browser. Sign in with **admin / admin**; you are then
   asked to choose your own password.
3. Follow **Setup**, then **Compilation**, **Data Extraction** and **Config Files**.

`stop.bat` stops the servers the panel started (safely), then the panel. `clean.bat` removes build output
and keeps your settings and backups.

## Documentation
See [docs/](docs/README.md): usage, architecture and how each part works.
