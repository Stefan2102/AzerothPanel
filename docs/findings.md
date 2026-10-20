# AzerothCore facts the panel relies on

Paths are relative to the AzerothCore source tree.

## Worldserver console (`src/server/apps/worldserver/CommandLine/CliRunnable.cpp`)
- Prompt is `"AC> "`, printed again after every command finishes → used to detect the end of a
  command's output (`ServerManager.run_command`).
- Real console: `ReadConsoleW`; redirected stdin: `std::getline`, EOF → `World::StopNow`.
- Requires `Console.Enable = 1` (default) in worldserver.conf.
- On shutdown `ShutdownCLIThread` cancels the pending console read (`CancelSynchronousIo`) — verified
  that the process exits cleanly under ConPTY.
- Commands are typed without the leading dot (the panel strips it).

## Signals (`apps/worldserver/Main.cpp`, `apps/authserver/Main.cpp`)
- Both register SIGINT, SIGTERM and (Windows) SIGBREAK → graceful stop (`World::StopNow` / io stop).
- World shutdown path saves players: `sWorldSessionMgr->KickAll()` + `UpdateSessions(1)`.
- Ready line: `"<rev> (worldserver-daemon) ready..."`, printed right after the world port opens.

## GM commands used (`src/server/scripts/Commands`)
| Panel action | Command | Notes |
|---|---|---|
| kick | `kick <name> [reason]` | |
| ban / unban | `ban account|character <name> <duration> <reason>` / `unban ...` | Duration goes through `TimeStringToSecs`: a bare number = 0 s = **permanent**; `-1` also permanent. The panel requires units (30m, 12h, 7d) or -1. Reason is mandatory. |
| mute / unmute | `mute <name> <time> [reason]` | `TimeStringToSecs` again → the panel sends `<minutes>m`. |
| GM level | `account set gmlevel <account> <0-3> -1` | -1 = all realms |
| level | `character level <name> <level>` | works offline |
| revive | `revive <name>` | |
| mail / gold | `send mail <name> "subject" "text"`, `send money <name> "subject" "text" <copper>` | QuotedString args: `"` removed from user text |
| announce / notify | `announce <text>`, `notify <text>` | |
| stop | `server shutdown <seconds>` | |

## Database schema bits (`data/sql/base`)
- `auth.account` (username, last_ip, last_login, online, mutetime, totaltime …), `account_access`
  (id, gmlevel, RealmID; -1 = all realms), `account_banned` (active, bandate, unbandate; bandate ==
  unbandate = permanent), `characters.characters` (online, zone, map, money, totaltime),
  `characters.character_banned`.
- Stock `acore` user: `ALL PRIVILEGES` on the three schemas only (`data/sql/create/create_mysql.sql`).

## mod-playerbots (4th database)
- The module keeps its own database and reads `PlayerbotsDatabaseInfo` from its module config
  `configs/modules/playerbots.conf` (default `"127.0.0.1;3306;acore;acore;acore_playerbots"`, from
  `conf/playerbots.conf.dist` in mod-playerbots). Module configs: `.conf.dist` defaults, `.conf` overrides.
- The panel treats Playerbots as installed when that config is deployed and adds `playerbots` to its
  database list (`ServerConfig.databases`), so the Database page, Backup & Restore, Test connections and
  Settings pick it up automatically. Random bots are normal characters and count as players.
- The reference panel instead checks for `modules/mod-playerbots` in the source tree and has separate
  `AC_PLAYERBOTS_DB_*` settings; it shows a Playerbots tab in its Database Manager only.

## DBC
- `AreaTableEntryfmt = "niiiixxxxxissssssssssssssssxiiiiixxx"` (`src/server/shared/DataStores/DBCfmt.h`):
  ID field 0, localized names fields 11–26. Read from `<DataDir>/dbc/AreaTable.dbc` (2307 areas on 3.3.5a).

## Install layout seen on this machine
`install\database\` (mysqld + my.ini, port 3307) and `install\server\` (exe files, `configs\`,
`configs\modules\`, `logs\`, `data\`). The panel does not assume this layout; it searches for the
executables (Settings → Detect).

## Building on Windows (verified on this machine)
- Visual Studio: the AzerothCore wiki (windows-requirements) asks for "MS Visual Studio (Community) ≥ 17 (2022)".
  visualstudio.microsoft.com/downloads only offers the newest version (2026 = 18), and the "older downloads" page
  needs a Visual Studio subscription for 2022. Microsoft's fixed installer links for the current 2022 release are
  `https://aka.ms/vs/17/release/vs_community.exe` and `.../vs_buildtools.exe` (checked 2026-10-17: both resolve to
  download.visualstudio.microsoft.com). The Requirements row's Download button is the Community one, a second button (`more_links`) Build Tools; a newer VS gets an info
  note (it meets the minimum; Boost msvc-14.5 instead of 14.3).
- `cmake --install` puts the exes in the prefix root and `.conf.dist` files in `configs\` and `configs\modules\`
  (`src/server/apps/CMakeLists.txt`, `src/cmake/macros/ConfigInstall.cmake`). It copies **no OpenSSL / MySQL DLLs**
  (the panel's deploy does). The only DLL AzerothCore's CMake handles is `libsidecar.dll` (POST_BUILD copy into the
  build tree, `install(FILES)` next to worldserver; checked on master 2026-10-17).
- Boost is linked statically on Windows (`deps/boost/CMakeLists.txt`: `Boost_USE_STATIC_LIBS ON`), so no Boost
  DLLs are needed. That file also reads `$ENV{Boost_ROOT}`, so a stray environment variable can override the Boost
  you pass. The panel removes it from the build's environment.
- `OpenSSLCrypto.cpp` asserts that `legacy.dll` sits next to the exe, and loads the OpenSSL legacy provider from there.
- `DatabaseWorkerPool.cpp`: the runtime `libmysql.dll` must have exactly the version of the headers it was compiled
  with (ACE00046), and must be at least 8.0 (ACE00043).
- `libmysql.dll` (8.4.x) imports `libssl-3-x64.dll` and `libcrypto-3-x64.dll`. The MySQL zip ships them in `bin`.
  When the server folder lacks them, Windows may load stray copies from System32. The DLL walk reports that.
- With an OpenSSL 4.x build the server imports `libcrypto-4-x64.dll` while libmysql still needs the `-3` DLLs, so
  both majors end up next to the server. File names differ per major, so they don't conflict.
- A module folder can be a junction. If its target is gone, CMake fails, so preflight reports it.
- MSBuild (`/v:minimal`) prints `name.vcxproj -> output` per finished project and cl prints each compiled file
  name. A full build is about 1175 compile units, 600 of them in `scripts` and 326 in `game`.

## Client data (verified on this machine)
- The core pins the client-data release in `apps/installer/includes/functions.sh` (`inst_download_client_data`,
  `VERSION=v20.0` at commit 93927ec9). `data.zip` v20.0 is 1,196,168,257 bytes, has top-level `Cameras`, `dbc`,
  `maps`, `mmaps`, `vmaps` (22,284 entries, 3.23 GB unpacked). GitHub serves it with `Accept-Ranges: bytes`.
- `map_extractor` options: `-i` input, `-o` output, `-e` MAP(1)/DBC(2)/Camera(4), `-f` int heights. Both paths live in
  `char[128]` and are cut silently (`src/tools/map_extractor/System.cpp`), e.g. "Could not create directory …scratchp/dbc/".
- `vmap4_extractor`: `-s` small (default) / `-l` large, `-d <client>/Data`; writes `./Buildings`; `output_path[128]`.
  `vmap4_assembler Buildings vmaps`. `mmaps_generator`: `--config`, `--threads`, map id; reads `<dataDir>/maps` and
  `<dataDir>/vmaps` (`dataDir` from `mmaps-config.yaml`, default `./`).
- `Wow.exe` 3.3.5a has file version 3.3.5.12340 in its version resource.

## MySQL setup (verified on this machine, MySQL 8.4.8)
- AzerothCore's `data/sql/create/create_mysql.sql` creates the schemas with `UTF8MB4 / utf8mb4_unicode_ci` and grants the
  `acore` user rights on those three only. The panel's setup instead grants `ALL ON *.* WITH GRANT OPTION` (your choice)
  so module databases and `mysqladmin shutdown` work with the same account.
- `mysqld --initialize-insecure --console` reads `my.ini` from the base folder (cwd = MySQL folder) and creates `data\`
  with `root@localhost` without password (log: "root@localhost is created with an empty password").
- MySQL 8 `SHOW GRANTS` for a global ALL grant lists every privilege by name (`GRANT SELECT, INSERT, … ON *.* … WITH
  GRANT OPTION`), not "ALL PRIVILEGES".
- The X Plugin listens on `::`:33060 unless `mysqlx-bind-address` is set.
- Fresh databases + an authserver start: AutoSetup created 22 tables in acore_auth and applied 23 update files.

## Config templates vs. a portable setup
- `worldserver.conf.dist`: `DataDir = "."`, `LogsDir = ""`, `SourceDirectory = ""`, `MySQLExecutable = ""`. `authserver.conf.dist`
  and `dbimport.conf.dist` have LogsDir / SourceDirectory / MySQLExecutable but no DataDir.
- An empty MySQLExecutable means the compiled-in path or PATH (`DBUpdater.cpp`: "Didn't find any executable MySQL binary at …
  or in path, correct the path in the *.conf (MySQLExecutable)"). A panel build doesn't bake one in, and a portable MySQL isn't
  on PATH, so new configs get the MySQL folder's bin\mysql.exe.
