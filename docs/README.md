# AzerothPanel docs

A local, Windows-only web dashboard for an AzerothCore 3.3.5a server: start/stop with safe
shutdowns, live consoles, players, logs, database, backups, config editing, and compiling + deploying
AzerothCore from source. Overview and quick start: [README](../README.md) in the repo root.

| File | What it covers |
|---|---|
| [usage.md](usage.md) | Build, start, stop, first run, day-to-day use |
| [architecture.md](architecture.md) | Components, data flow, API map, where things live |
| [source.md](source.md) | Source code: clone the official repo, the playerbots fork or any URL/branch |
| [database.md](database.md) | Database setup: my.ini, initialise MySQL, account + databases (incl. module databases), configs |
| [modules.md](modules.md) | Modules: catalogue (azerothcore.org), install / update / remove in the source tree |
| [data.md](data.md) | Data Extraction: client data status, download of the pinned release, extraction from a 3.3.5a client |
| [build.md](build.md) | Build & Deploy: requirements detection, compiling, deploying (DLLs, configs) |
| [sql-import.md](sql-import.md) | Database page → Import SQL: run an .sql file against one database (optional backup first) |
| [config-values.md](config-values.md) | Config Files tabs: Setup (paths, database connection) and Quick settings (common worldserver values) |
| [process-control.md](process-control.md) | How servers are started/stopped safely (verified findings) |
| [findings.md](findings.md) | AzerothCore / MySQL facts the panel relies on, with sources |

Quick start: run `install.bat` once, then `start.bat`. Stop everything safely with `stop.bat`
or **Shut down panel** in the sidebar.
