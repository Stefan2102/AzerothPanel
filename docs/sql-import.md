# Import SQL (Database page)

Runs an `.sql` file against one database. Code: `backend/services/sql_import.py`, `backend/routers/sql_import.py`,
`frontend/src/components/SqlImport.tsx`.

- **Dialog** (Database → Import SQL): the database (auth / characters / world / playerbots, from the server configs'
  `*DatabaseInfo`), the file (picked with the panel's file browser, `.sql` only, up to 4 GB), and two options, both off
  by default:
  - **Back up this database first:** `mysqldump --single-transaction --routines --triggers --events --hex-blob
    --databases <db>` to `backups\before-import-<db>-<time>.sql`. Importing that file the same way undoes the import
    (it recreates the tables as they were). If the dump fails, nothing is imported.
  - **Continue after errors:** `mysql --force`; otherwise the import stops at the first error. Statements before
    it stay (autocommit; DDL can't be rolled back anyway).
  - While worldserver runs, importing into world or characters shows a warning: the server keeps much of that
    data in memory, so changes may not show or be overwritten until a restart.
- **How:** MySQL's own client (`bin\mysql.exe` of the chosen MySQL folder, `--default-character-set=utf8mb4`), so everything
  AzerothCore's SQL files use works (`DELIMITER` blocks, many statements, large dumps). The panel feeds the file to
  its stdin in 1 MB chunks: that gives the progress (MB read) and lets **Cancel** stop it (kills mysql.exe; what was
  already imported stays). The login is in a temporary option file in `data\` (`mysql-*.cnf`), never on the command
  line; it's deleted afterwards, and leftovers from a killed panel are deleted at the next start.
- **Status:** a card under the page header with the steps (Backup, Import), progress and the result only, no
  console. Success: "Imported into <db>" (+ backup file). Stopped at an error: MySQL's error with the line number.
  With **Continue after errors**: the number skipped and the first 5 of them (`SHOWN_ERRORS`, job field
  `first_errors`); everything MySQL printed is in the downloadable **Log**. A toast also announces the end. The header
  shows "Importing SQL — importing 45%". One import at a time. Audit entry `db.import` (WARN).
- **Storage:** `data\sql-import.json`, `data\sql-import-logs\<id>.log`.
- **Endpoints:** `POST /api/sql-import/run {database, file, force, backup}` and the shared `/api/sql-import/jobs…` routes.
- **Tested** against a throwaway MySQL 8.4 (scratch data folder): DELIMITER procedure, stop at the first error,
  `--force` with the error counted, backup + undo by importing it, cancel at 28 % (no mysql.exe left), 7 MB / 400k rows
  in 4 s, file checks.
