# Config Files: Setup and Quick settings tabs

The values the panel keeps in the server configs. Code: `backend/services/config_values.py`,
`backend/routers/config_values.py`, `frontend/src/components/ConfigValues.tsx` (Setup tab).

| Value | Default | Stored in |
|---|---|---|
| `DataDir` | `./data` (= `install\server\data`) | `settings.config_paths` (only values that differ from the default) |
| `LogsDir` | `./logs` (= `install\server\logs`) | same |
| `MySQLExecutable` | `bin\mysql.exe` of the chosen MySQL folder (Setup → Requirements) | same |
| `*DatabaseInfo` (IP, port, account, password) | none: set by Database setup or here | `settings.db_connection`, shared with Database setup |

- **Why:** AzerothCore's templates use DataDir `"."`, LogsDir `""` (both the server folder itself) and an empty
  MySQLExecutable ("search PATH"). A portable MySQL isn't on PATH, so the DB updater would stop with "Didn't
  find any executable MySQL binary".
- **Everything is editable.** Defaults follow the AzerothCore folder: a value equal to its default isn't stored,
  so it moves with the folder. "Default" puts the default back into the field.
- **Where they're written: only by Save & apply** (user's decision: nothing else edits `.conf` values).
  - Save & apply saves, then writes them into every existing `.conf` (core + `configs\modules`). No `.bak`
    copies are made (user's choice). It creates the DataDir and LogsDir folders (relative
    values are inside the server folder). Refused while a build/deploy runs.
  - Deploy only copies templates: a missing `.conf` becomes a copy of its `.dist`, and a `.conf` whose `.dist`
    changed in the update is replaced by it. Those configs have AzerothCore's defaults
    (DataDir `.`, `acore/acore`, empty MySQLExecutable). The deploy log and the Compilation page then say
    "Before starting the servers, go to Config Files" (a note, not a warning). Config Files shows "Differs in …".
  - Database setup only remembers the connection (`settings.db_connection`); it doesn't write configs either.
- **What is changed:** only the value of an existing `Key = ...` line (`conffile.set_values`,
  `mysql_setup.apply_connection`). Comment lines (`#   DataDir ...`), all other lines, line endings and the
  `.conf.dist` templates are never touched; a key a file doesn't have is not added. In `*DatabaseInfo` the
  database name (5th part) stays.
- **Existing installation:** without a saved connection the tab shows the one in the configs (first
  `*DatabaseInfo`, worldserver.conf first; `db.source = "configs"`, "Read from your configs"). Saving with an
  empty password field then keeps that password. The fields follow the latest status (folder chosen, deploy,
  window focus) until you edit one; after Save & apply they follow it again.
- **Password:** shown as `••••••••` when one exists; the eye button loads it (`GET /api/config-values/password`,
  audit entry `config.values.reveal`) so it can be read or edited. Showing it isn't a change; an empty field keeps the
  saved one. Every password field in the panel has the eye (`PasswordInput` in `components/ui.tsx`); only this one
  loads a saved value.
- **Status per value:** "Set in …" (every config that has the key has the value), "Differs in …" (hover shows
  the current values), "No config has this key". The database password is compared but never sent to the
  browser unless revealed (`password_set` only).
- **Endpoints:** `GET /api/config-values` (status), `PUT /api/config-values {paths, db|null}` (save & apply;
  returns `applied` = changed files and the new status).

## Quick settings
Config Files → Quick settings: common worldserver.conf values as a form. Code: `backend/services/quick_settings.py`,
`backend/routers/quick_settings.py`, `frontend/src/components/QuickSettings.tsx`.

- **Which keys and their control** (toggle, choice, whole number, rate ×) are defined by the panel in
  `quick_settings.GROUPS`: Realm (GameType, RealmZone, PlayerLimit), Characters (levels, start money, professions,
  intro cinematic, EnablePlayerSettings, AllowTwoSide.Accounts), Rates (XP, rest, reputation, honor, talents,
  money), Item drops (common … legendary), Cross-faction (AllowTwoSide.Interaction.*), Instances (IgnoreLevel, IgnoreRaid), Performance & data
  (MapUpdate.Threads, DBC.EnforceItemAttributes). Choice lists are AzerothCore's documented values. A key the
  file doesn't have (another AzerothCore version) is not shown. Adding a key is one line in `GROUPS`.
- **From AzerothCore's files:** current value from worldserver.conf, default from worldserver.conf.dist, and the
  description (info icon tooltip) from the comment block above the key. The block must name the key in its header,
  otherwise no description is shown. The template's comments are not parsed for options: their format differs
  between keys (shared blocks for rates, "1+" for PlayerLimit).
- **Saving** writes only the changed keys (`conffile.set_raw`): just the value, keeping quotes/bare numbers and the
  line's alignment. Values are checked first (choice in its list, whole numbers in range, rates 0–1000). The
  worldserver must be restarted to use them. After a deploy replaces worldserver.conf, the tab simply shows the
  new file's values.
- **Endpoints:** `GET /api/quick-settings`, `PUT /api/quick-settings {values: {key: value}}`.
