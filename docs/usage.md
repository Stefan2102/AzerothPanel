# Using AzerothPanel

## Requirements
- Windows 10/11 (ConPTY is required)
- Python 3.11+ and Node.js 20+ in `PATH` (only needed to build)

## Scripts (repo root)
| Script | Does |
|---|---|
| `install.bat` | Creates `.venv`, installs `requirements.txt`, `npm ci` + production build of the frontend. Pauses on success/failure. Refuses to run while the panel is running. |
| `start.bat` | Starts the panel in the background (no console window) and opens `http://127.0.0.1:8090`. If it is already running it just opens the browser. |
| `stop.bat` | Safely stops every server the panel started (world → auth → MySQL), then the panel. Waits until done. |
| `clean.bat` | Removes `.venv`, `node_modules`, `dist`, `__pycache__`. Keeps `data` (settings, password) and `backups`. Refuses while the panel is running. |

## First run
1. `start.bat` → sign in with **admin / admin** (created automatically on first start); the panel then asks
   for a new password (min. 8 characters) before anything else. Delete `data\auth.json` and restart the panel
   to reset the account to admin / admin. Older installs keep their password; the username is `admin`.
2. Setup (or Settings) → **AzerothCore folder** → choose one folder → **Save**. A new or empty folder is fine
   (it is created). Source, build and server have a fixed place inside it:

   | Folder | Holds |
   |---|---|
   | `<folder>\source` | the AzerothCore git checkout (cloned on Setup, built by Compilation) |
   | `<folder>\build` | CMake build folder |
   | `<folder>\install\server` | worldserver, authserver, `configs\`, `data\`, `logs\` (deploy target) |

   The layout is `settings.LAYOUT`; settings from before it (separate server/source/build folders) are converted
   on load when the server folder was `<folder>\install\server`.
   **MySQL** (the portable ZIP, used for compiling and as the server) can be anywhere, with any folder names; the
   intended place is `<folder>\install\database`. Choose it on Setup → Requirements → MySQL → **Change**
   (`settings.mysql_dir`); nothing is detected. Until one is chosen (e.g. MySQL runs as a Windows service), the
   panel never starts or stops MySQL.
3. **Test connections** checks MySQL, the three databases, the executables and `AreaTable.dbc`.

## Daily use
- Dashboard / Server Control: **Start all** (MySQL → Auth → World, each waits for the previous port).
  **Safe stop all** reverses the order. Single services have Start / Stop / Restart.
  **Force kill** is a last resort behind a confirmation (may lose progress / trigger InnoDB recovery).
- Console: live, read-only output of each server (nothing is typed into the terminal itself). The
  Worldserver tab has a GM command line under the output (same route as the Server Control GM console;
  Up/Down recall earlier commands). Replies that go through the console appear in the output; SOAP
  replies don't reach the console, so they are listed above the command line. The announce bar sends
  server-wide announcements / notifications.
  The console shows the current run only; previous runs are in Logs.
- Database: table browser and a read-only SQL editor. Its starting query follows the selected database
  (characters → `characters`, world → `creature_template`, auth → `account`) until you edit it.
- Players: characters (online first) and accounts. Kick / ban / unban / mute / level / mail / gold /
  revive / GM level all run as GM commands on the worldserver console, so worldserver must be running
  from the panel.
- Logs: Worldserver, Authserver, GM Commands and DB Errors. Each file is found from the logger config
  (`Logger.root`, `Logger.commands.gm`, `Logger.sql.sql` -> their file `Appender`). GM command logging is off
  by default in AzerothCore; enable `Appender.GM` and `Logger.commands.gm` to fill that tab. Level filter
  (ALL/ERROR/WARN/INFO/DEBUG) uses the level word in a line; AzerothCore only writes it when the appender
  flags include 2, so with flags 0 most lines count as INFO (DB Errors lines count as ERROR). Search,
  Live/Disconnected, Clear (view only), Download, Auto-scroll, Load older lines.
- Database: table browser + SQL runner. Only single `SELECT/SHOW/DESCRIBE/EXPLAIN/WITH` statements, and
  they run inside a `READ ONLY` transaction (MySQL itself rejects writes), 15 s limit, 1000 rows. Rows are
  streamed and only the first 1001 are read, so a huge result never fills the panel's memory.
- Backup & Restore (three tabs, like the reference panel):
  - Destinations: local folders (PC, USB, mapped network drive). "Default Local Storage" is the repo's
    `backups` folder and can't be removed. Test checks the folder is writable and shows free space.
  - Create Backup: pick destination, include Config Files / Databases / Server Binaries, optional notes.
    Produces `azeroth-backup-YYYYMMDD-HHMMSS.zip` (manifest.json, configs/, databases/*.sql, binaries/).
    Live progress log; one backup/restore at a time.
  - Job History: status, size, destination, contents; expand to see/delete archive files; delete the record;
    Restore (only while Worldserver and Authserver are stopped; MySQL must run for databases). Config
    restores keep the current files as `<file>.<timestamp>.bak`.
- Config Files has three tabs:
  - **Setup:** DataDir, LogsDir, MySQLExecutable and the database connection for every config
    ([config-values.md](config-values.md)).
  - **Quick settings:** common worldserver.conf values as a form (realm, characters, rates, cross-faction,
    instances, performance) ([config-values.md](config-values.md#quick-settings)).
  - **Editor:** worldserver.conf, authserver.conf, `configs\modules\*.conf`. Ctrl+F opens a find/replace box
    (match case, whole word, regex; Enter / Shift+Enter, Escape; `components/FindWidget.tsx`, also in the SQL
    editor and the diff view). Save shows a diff first. A
    "restart to apply" badge appears when a file is newer than the running server.
  - No `.bak` copies are written for configs (user's choice).

## Build & Deploy
- Setup -> Source code: clone AzerothCore (official, playerbots fork with mod-playerbots, or any URL and branch) into
  `<folder>\source`. See [source.md](source.md).
- Setup -> Requirements: Git, Visual Studio 2022 (C++ workload), CMake, Boost, OpenSSL, VC++ runtime,
  MySQL 8.4. Each row shows the found version and path, the minimum your source needs, a Download link
  and what to pick while installing. For the build tools, **Change** sets another folder (kept until **Reset to
  detected**). MySQL's **Change** is the only way to set it (no detection, no reset); the folder you pick may be
  the MySQL folder itself, its `bin`, or a folder above it (see [database.md](database.md)).
- Compilation: **Pull Latest Source** updates the source (git pull; stops without changes if local edits are in
  the way). Below it: the source (git revision, modules), build folder and install folder (= server folder).
  Pick the options and **Start Build**. With **Deploy when done** the result is installed into the server
  folder, including the DLLs it needs (worldserver and authserver must be stopped). **Deploy only** installs
  the last compiled binaries. Details: [build.md](build.md).

- Data Extraction: status of dbc/maps/vmaps/mmaps in DataDir. **Download Data** fetches the release your
  source expects (resumes if interrupted); **Extract from Local Client** runs the server's extractor tools on a
  3.3.5a client. Worldserver must be stopped; data is replaced only after everything succeeded. See [data.md](data.md).

- Modules: browse the AzerothCore catalogue (search, sort, categories) and **Install** modules into the source's
  modules folder; Installed tab: Update / Update All / Remove, or install from a Git URL. Rebuild afterwards
  (a banner reminds you). See [modules.md](modules.md).

- Shortcuts (sidebar): start the game client, Ollama or any program with one click; **Manage** adds, edits
  and removes them. They start like a double-click and the panel never stops them. See [shortcuts.md](shortcuts.md).

- Every folder or file field has **Browse**: a folder browser of the PC the panel runs on (drives, folders, Up,
  New folder). It also works from another device when remote access is on. A web page can't open Windows' own
  folder dialog.

## SOAP (optional)
GM commands (Server Control GM console, Players actions, announcements) go over SOAP when it is set up,
otherwise through the worldserver console. SOAP gives exact replies and also works when worldserver was
started outside the panel. Setup:
1. Config Files -> worldserver.conf: `SOAP.Enabled = 1` (keep `SOAP.IP = "127.0.0.1"`), restart worldserver.
2. Settings -> SOAP: a game account with GM level 3 (Players -> Accounts -> GM level) and its password -> Save.
3. Test SOAP. The password is stored in `data\settings.json` (SOAP needs it in clear text) and is never
   sent back to the browser.

## Remote access (optional)
Settings -> Remote access: tick "Allow access from other devices", pick the HTTPS port (default 8443) and the
certificate (self-signed automatic, or your own cert + key files, e.g. Let's Encrypt via win-acme), Save, then
restart the panel (stop.bat, start.bat). Requirements and behaviour:
- Only possible after the default admin password is changed (the first login with admin/admin forces it).
- This PC keeps using `http://127.0.0.1:8090`; other devices use the https URLs shown in the card. Self-signed:
  the browser warns once - compare the SHA-256 fingerprint shown in Settings.
- Windows Firewall may ask to allow Python. From the internet: forward the port on the router, or better use
  a VPN (Tailscale/WireGuard).
- 5 wrong logins in 15 min lock that address for 15 min. Logs -> Panel Actions lists every action
  (logins, starts/stops, GM commands, player actions, config saves, SQL queries, backups/restores, settings).

## Closing
Closing the browser tab does nothing to the servers. The panel keeps running until `stop.bat` or
**Shut down panel**. Servers started outside the panel (e.g. the old `0x_start_*.bat` files) are shown as
"Online (external)"; the panel can stop them gracefully but has no console for them.
