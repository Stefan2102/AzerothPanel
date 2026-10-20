# Architecture

One local process: FastAPI (Python) serves the API, two WebSockets and the built React app on a
single port (default `127.0.0.1:8090`, `data\settings.json`). No Docker, no external services.

```
browser (React + Tailwind, CodeMirror)
   │  HTTP /api/*   WS /ws/console/{key}, /ws/logs/{source}
   ▼
FastAPI  ── ServerManager ── ConPtyProcess ×3 ──► mysqld / authserver / worldserver
   │            (state machine, jobs, metrics)        (each in its own pseudo console)
   ├── PyMySQL (credentials from worldserver.conf)
   ├── log files (LogsDir), configs\*.conf, AreaTable.dbc
   └── mysqldump.exe (backups)
```

## Backend (`backend`)
| Module | Responsibility |
|---|---|
| `__main__.py` | `run` (foreground), `start` (spawn hidden + open browser), `stop` (control token → safe shutdown, waits for the PID) |
| `app.py` | App factory, lifespan (monitor start / safe shutdown), error mapping, static frontend |
| `settings.py` | `data\settings.json`: the AzerothCore folder (`root_dir`; source, build and server have fixed places in it, `LAYOUT`), the MySQL folder (`mysql_dir`, anywhere, chosen on Requirements), port, session hours, world countdown, build-tool overrides |
| `acconf.py` | Parses AzerothCore `.conf` (cached by mtime): DB infos, ports, realm, LogsDir, DataDir, SOAP |
| `services/audit.py` | Action log `data\audit.log` (who, IP, action) shown as Logs -> Panel Actions; rotates at 5 MB |
| `services/tls.py` | Certificates for the remote listener: self-signed in `data\tls` (EC P-256, this PC's names/IPs) or own files |
| `security.py` | scrypt password hash, HMAC-signed session cookie, same-origin checks, local control token |
| `services/conpty.py` | One child in a ConPTY (pywinpty): reader thread → asyncio, process-tree tracking, write; keeps Ctrl-C enabled for children |
| `services/console_screen.py` | pyte terminal emulation of the ConPTY stream → finished lines + current screen for the read-only console |
| `services/server_manager.py` | Lifecycle rules, ordered start/stop, jobs, external-process detection, CPU/RAM sampling, GM command runner |
| `services/ctrl_event.py` | Helper process: Ctrl-C/Ctrl-Break into the console of a process the panel did not start |
| `services/soap.py` | Client for worldserver SOAP (stdlib HTTP + basic auth): result / command fault / 401 / 403 / unreachable |
| `services/commands.py` | GM command routing: SOAP first (if enabled + account set), worldserver console as fallback |
| `services/players.py` | Character/account queries, GM command builders with input validation |
| `services/db.py`, `sqlguard.py` | DB access, read-only runner (guard + `READ ONLY` transaction) |
| `services/logs.py` | Log sources (worldserver, authserver, GM commands, DB errors) resolved from `Logger.*`/`Appender.*` in the .conf files; backwards paging; incremental follower (handles truncation on server restart) |
| `services/backup.py` | Backup & Restore: destinations + job history (`data\backup.json`), zip archives (configs / mysqldump / binaries), restore with path-traversal checks; MySQL tools get credentials via a temporary option file (never on a command line) |
| `services/dbc.py` | Zone names from the server's `AreaTable.dbc` |
| `services/jobs.py` | Shared job history (JSON file, log tail, optional full log file), background runner, child-process runner with cancel (kills the tree) |
| `services/toolchain.py` | Detection of VS / CMake / Git / Boost / OpenSSL / MySQL / VC++ runtime and of the workspace (source, build folder, existing CMake cache) |
| `services/requirements.py` | Install guide per dependency (links, what to select) and minimum versions parsed from the source |
| `services/source.py` | Git revision of the source and of each module; broken module links |
| `services/build.py` | Build plan, configure/compile/deploy job, runtime DLL resolution, safe stop/start around a deploy |
| `services/clone.py` | Source code: presets, remote branch list, clone job with live progress, cleanup on failure |
| `services/mysql_setup.py` | Database setup: my.ini, mysqld --initialize-insecure, account + databases (core + module *DatabaseInfo), root removal after a check, config rewrite |
| `services/modules.py` | Module catalogue (azerothcore.org catalogue.json, cached), installed modules, install/update/remove jobs, rebuild-needed check |
| `services/client_data.py` | Client data (DataDir): status, pinned release, download + unpack + swap, extraction with the server's tools |
| `services/pe.py` | PE import table reader and file version resources (which DLLs a binary loads) |
| `routers/fs.py` | Folder browser for path fields: quick places (Windows known folders Home / Desktop / Documents / Downloads via `SHGetKnownFolderPath`, so OneDrive-redirected ones work) and every drive (`os.listdrives()`), folders, optional files by extension, New folder (signed-in only, names only) |
| `routers/*` | Thin HTTP/WS layers per feature |

Everything that can be read from AzerothCore's own configs is read, never duplicated.

## API map
- `GET /api/health` (no auth), `POST /api/control/shutdown` (control token)
- `/api/auth/state|login|logout|password`
- `GET /api/status` (polled every 2 s: service states, metrics history, job, player counts)
- `POST /api/server/{mysql|auth|world}/{start|stop|restart|kill}`, `/api/server/start-all|stop-all`, `/api/server/command`, `/api/panel/shutdown`
- `/api/players/characters|accounts`, `POST /api/players/action`
- `/api/logs` (sources + availability), `/api/logs/{source}?before=&limit=`, `/api/logs/{source}/download`, WS `/ws/logs/{source}?offset=`
- `/api/db`, `/api/db/{key}/tables`, `/api/db/{key}/tables/{table}?page=&size=`, `POST /api/db/{key}/query`
  - Connection (host, port, user, password, database) comes from worldserver.conf's `*DatabaseInfo`
    lines (playerbots: its module config). An unreachable MySQL answers 503 with the reason; the
    Database page shows it in the table list instead of an endless spinner.
- `/api/backups/destinations` (CRUD + `/{id}/test`), `/api/backups/jobs` (+ `/{id}`, `/{id}/files`, `DELETE /{id}/files/{name}`), `POST /api/backups/run`, `POST /api/backups/restore`
- `/api/configs`, `/api/configs/{id}` (GET/PUT with `base_hash`); `/api/config-values` (GET, PUT = save & apply), `/api/quick-settings` (GET, PUT); see config-values.md
- `POST /api/sql-import/run` and `/api/sql-import/jobs…` (Database page → Import SQL; see sql-import.md)
- `/api/build/toolchain|paths|pull|run|deploy|jobs…` (see build.md)
- `/api/client-data`, `/api/client-data/download|extract|jobs…` (see data.md)
- `/api/db-setup`, `/api/db-setup/run|jobs…` (see database.md)
- `/api/source/presets|branches|clone|jobs…` (see source.md)
- `GET /api/fs/list?path=&files=&ext=`, `POST /api/fs/mkdir {parent, name}` (Browse buttons)
- `/api/modules/catalogue|installed|install|install-url|update-all|{name}/update`, `DELETE /api/modules/{name}` (see modules.md)
- `/api/settings` (GET; PUT = session hours and world countdown), `PUT /api/settings/root {root_dir}` (refused while
  servers the panel started or any job run; creates the folder), `/api/settings/test`, `PUT /api/settings/soap`, `POST /api/settings/soap/test`
- WS `/ws/console/{key}` (read-only): `init {run, lines, screen}` then `update {lines, screen}`

Lifecycle operations are **jobs**: the request returns 202, one job runs at a time, progress and the
result appear in `/api/status` (`job`, `last_job`) and as toasts.

## Frontend (`frontend`)
React 19 + TypeScript + Vite + Tailwind v4, TanStack Query (polling/caching), plain-text console view,
CodeMirror 6 (config + SQL editors, merge view for diffs), lucide icons. Hash routing.
Console/Database/Configs pages are lazy-loaded chunks. Dark theme only.
Design follows Old-Man-Warcraft/AzerothPanel (grouped sidebar, status cards, purple accent).

## Security model
- Two listeners: local `http://127.0.0.1:<port>` (always, owns the app lifespan) and, when enabled in Settings,
  remote `https://0.0.0.0:<remote_port>` (TLS only; `lifespan="off"`; a failed bind does not stop the panel).
- Default account admin/admin: a session signed in with it may only change the password (token flag `mc`);
  remote access can't be enabled until it is changed. Changing the password rotates the signing key, so all
  other sessions are signed out. Login lockout: 5 failures within 15 min lock that IP for 15 min.
- Session cookie gets `Secure` on HTTPS requests. Every state-changing action is written to the audit log.
- Binds to 127.0.0.1 only. Single admin account (username + scrypt hash; a fresh install creates `admin` / `admin`), session cookie `HttpOnly; SameSite=Strict`.
- Every state-changing request and every WebSocket must come from the panel's own origin.
- SQL runner is read-only by two independent layers. Config/log/backup files are looked up by name from
  server-side lists — client paths are never used.
- GM command arguments are validated (names without spaces/quotes, durations with units, quoted texts sanitised).

## Data on disk
- `data\` – settings.json, auth.json (username + hash), secret.key, control.token, panel.pid, panel.log
- `backups\azeroth-backup-<yyyymmdd-hhmmss>.zip` (default destination; other destinations are user folders)
- `data\backup.json` – backup destinations and job history
- `data\build.json` + `data\build-logs\<id>.log` – build/deploy history and full logs
- `data\client-data.json` + `data\client-data-logs\<id>.log` – client data download/extraction jobs
- `data\modules.json` + `data\modules-logs\<id>.log` – module jobs; `data\catalogue-cache.json` – catalogue (1 h)
