# Database setup (Setup page)

Prepares a portable MySQL (the 8.4 ZIP extracted anywhere, e.g. `install\database`) for AzerothCore. Code:
`backend/services/mysql_setup.py`, `backend/routers/database_setup.py`, `frontend/src/components/DatabaseSetup.tsx`.

**Which MySQL:** the folder chosen on Setup → Requirements → MySQL → **Change** (`settings.mysql_dir`, read through
`settings.mysql_home`; `mysql_path` once it has `bin\mysqld.exe`). Never detected; intended place
`<AzerothCore folder>\install\database`, but any place and folder names work. With the portable ZIP, the MySQL you
compile against and the one that runs are the same folder. The card checks again when the browser window gets
focus (e.g. after extracting the ZIP in Explorer) and when Requirements changes MySQL.

- **Choosing** (`PUT /api/build/paths {key: "mysql"}` → `mysql_setup.find_mysql_home`): the picked folder itself
  when it has `bin\mysqld.exe`, its parent when `bin` was picked, else the only MySQL up to 2 levels below it
  (skipping `data` folders), e.g. `install` → `install\database\mysql-8.4.11-winx64`. None or several → error.
- **Refused** while the panel runs MySQL (it would keep running from the old folder) or while a database setup,
  SQL import, backup/restore or build runs.
- Follows automatically: compiling (CMake `MYSQL_INCLUDE_DIR` / `MYSQL_LIBRARY` on every configure), deploy's DLL
  search, worldserver's `MySQLExecutable` default, Database setup, backups, SQL import, start/stop. `my.ini` uses
  relative paths (`basedir=./`, `datadir=./data`), so a MySQL folder can be moved as a whole and chosen again.
  After switching to another MySQL version, compile and deploy again (libmysql.dll must match, ACE00046).

## Fields (fresh MySQL)
| Field | Default | Used for |
|---|---|---|
| IP address | `127.0.0.1` | `bind-address` / `mysqlx-bind-address` in my.ini and the host in the server configs |
| Port | 3306 (or the existing my.ini's) | my.ini and configs |

IP and port are always editable before the first setup; an existing my.ini only pre-fills them (e.g. when just
the `data` folder was deleted). A refetch doesn't overwrite what you typed.
| Account name | empty (required) | the account that is created; letters, digits and `_` |
| Password | empty (required) | its password; `;` and `"` are not allowed (AzerothCore separates values with `;`) |

- **Loopback** (`127.0.0.1` / `localhost`): the account is `<name>@'localhost'` and only this PC can reach MySQL.
- **Any other address** (e.g. the PC's LAN address): MySQL listens only on that address and the account is
  `<name>@'%'`. The servers then connect through that address, which MySQL doesn't count as localhost. Other
  machines on that network can reach MySQL, so use a strong password.

## What it does (fresh MySQL, `data\` not initialised)
1. **`my.ini`** (always written; an existing one is replaced, with the IP and port from the fields):
   ```ini
   [mysqld]
   basedir=./
   datadir=./data
   port=<port>
   bind-address=<IP address>
   mysqlx-bind-address=<IP address>
   sql-mode=""
   character-set-server=utf8mb4
   collation-server=utf8mb4_unicode_ci
   max_allowed_packet=128M
   [client]
   port=<port>
   ```
   MySQL's X protocol (port 33060) listens on all addresses unless `mysqlx-bind-address` is set;
   `bind-address` alone doesn't cover it.
2. **`mysqld --initialize-insecure --console`** creates `data\` with `root@localhost` and no password.
3. **A temporary `mysqld --console --bind-address=127.0.0.1`** is started and the job waits for its port. It is
   loopback only, because `root@localhost` may only log in from this PC. A port already in use is refused.
4. **As root, through PyMySQL with escaped parameters:**
   - `CREATE USER IF NOT EXISTS <user>@<'localhost' or '%'> IDENTIFIED BY <password>`
   - `GRANT ALL PRIVILEGES ON *.* TO <user>@<same> WITH GRANT OPTION`
   - `CREATE DATABASE IF NOT EXISTS <db> DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`, the same
     charset as AzerothCore's `data/sql/create/create_mysql.sql`
5. **Check, then remove root:**
   - Log in as the new account and check `SHOW GRANTS` has a grant `ON *.* … WITH GRANT OPTION`. MySQL 8
     lists the privileges by name; it doesn't print "ALL PRIVILEGES".
   - Only then every `root` account (`SELECT … FROM mysql.user WHERE user='root'`) is dropped and privileges are
     flushed. This always happens. A failed check keeps root.
6. **Clean shutdown:** `mysqladmin shutdown` as the new account, through a temporary option file. A console
   Ctrl-C (`ctrl_event.py`) is the fallback. The panel never kills it.
7. Server Control starts and stops this MySQL by itself (it is the fixed one in the AzerothCore folder).
8. **Remembered connection:** host, port, account and password are saved as `settings.db_connection` in
   `data\settings.json`, like the SOAP password.
   - The password is never sent to the browser or stored in the job record.
   - Database setup does **not** write the server configs (only Config Files edits `.conf` values). The
     connection appears pre-filled on Config Files → "Paths for this setup"; Save & apply there puts it into
     every `*DatabaseInfo` line ([config-values.md](config-values.md)). The job summary says so.
   - Changing it on Config Files only changes the configs, not the MySQL account.

**Tables:** the panel creates none. AzerothCore creates them on the first authserver/worldserver start
(`Updates.AutoSetup = 1` imports `data/sql/base`, then the updates). Verified: an authserver against a fresh
setup created 22 tables in `acore_auth` and applied 23 update files.

## Which databases (no fixed list)
- **Core:** from `LoginDatabaseInfo`, `WorldDatabaseInfo` and `CharacterDatabaseInfo`. They are read from the
  server's `worldserver.conf`, otherwise its `.dist`, otherwise the source's `worldserver.conf.dist`.
- **Modules:** every other `*DatabaseInfo` key in `<source>\modules\*\conf\*.conf.dist` and in the server's
  `configs\modules\*.conf(.dist)`.
  - mod-playerbots declares `PlayerbotsDatabaseInfo = "…;acore_playerbots"`, so `acore_playerbots` is
    created only when it is installed.
  - Any other module with its own database works the same way.

## Already set up (`data\mysql` exists)
- Only "Add missing databases": `CREATE DATABASE IF NOT EXISTS` for the list above.
- It logs in with the remembered account (`settings.db_connection`), or else the one in the server's
  `LoginDatabaseInfo`, so it also works before any config exists. It uses a MySQL that is already running, or
  starts and stops a temporary one.
- No user, root, my.ini or config changes. Existing databases and tables are not touched.

## Rules
- **Input checks:** the IP must be an IPv4 address (`localhost` becomes 127.0.0.1). The account name and
  password must not be empty and follow the rules in the Fields table.
- **When something fails** after initialising, the job stops the temporary server cleanly and says that
  `data\` can be deleted to start over (it holds no AzerothCore data yet).
- **Jobs:** `data\db-setup.json`, logs in `data\db-setup-logs`.
- **Endpoints:** `GET /api/db-setup`,
  `POST /api/db-setup/run {host, port, user, password}`, and the shared
  `/jobs…` routes.
