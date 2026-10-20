# Modules

Sidebar: Build & Deploy -> **Modules**. Code: `backend/services/modules.py`, `backend/routers/modules.py`,
`frontend/src/pages/Modules.tsx`.

## Catalogue
- **Source:** `https://www.azerothcore.org/data/catalogue.json`, the file the official catalogue page
  (azerothcore.org/catalogue.html) is built from.
  - It is regenerated daily from the GitHub topics `azerothcore-module`, `azerothcore-tools`,
    `azerothcore-lua` and `azerothcore-sql`.
  - It has about 500 modules, 90 tools, 90 Lua and 40 SQL entries, each with stars, forks, created/pushed
    dates, owner and avatar, and the default branch.
  - So there are no GitHub API calls, no rate limit and no token, unlike the reference panel's
    10 searches/minute.
- **Caching:** `data\catalogue-cache.json`, kept for 1 hour. **Refresh** reloads it. When offline, the last
  copy is shown with a note.
- **Page:** like azerothcore.org:
  - Tabs: All Modules, Tools, Lua scripts, SQL.
  - Search over name and description.
  - Sort: Most stars, Recently updated (pushed), Recently added (created).
  - 30 per page. Cards like the reference panel.
- **Install** exists only for modules (they go into `<source>\modules`). Tools, Lua and SQL entries open
  on GitHub.
- **"installed" badge:** an installed module's git remote matches the repo (`owner/repo`), or the folder
  name matches.

## Installed
- **List:** the folders in `<source>\modules`: git remote, branch@commit, local changes, link or broken
  link (`services/source.py`).
- **Update:** `git pull --ff-only`, then `git submodule update --init --recursive`. It lists the new
  commits. With local changes or a diverged branch it stops and changes nothing.
- **Update All Modules:** updates each git module. Failures are listed and the others still update.
- **Remove:** asks for confirmation (warns about local changes), then deletes the folder.
  - Git's read-only object files are made writable first.
  - A junction or symlink is only unlinked; its target is never touched.
  - The module's `.conf` / `.conf.dist` in `install\server\configs\modules` stay (deploy never deletes files).
    After the rebuild worldserver ignores them: it loads only the module configs on the list compiled in
    (`CONFIG_FILE_LIST` from `modules/CMakeLists.txt`, `ConfigMgr::LoadModulesConfigs`). Kept for a reinstall.
- **Install from Git URL:** any `https://…` git URL, for modules that aren't in the catalogue (e.g.
  mod-solo-lfg has no catalogue topic). The folder name is the URL's last part without `.git`.

## Rules
- No output box: the page follows the job it started and reports the result as a toast (with the error if it
  failed), then refreshes the lists. The full log stays in `data\modules-logs`.
- While a job runs, a card above the tabs shows it ("Installing mod-x"), git's progress line with size and speed
  (`clone --progress`, `pull --progress`; `jobs.git_progress`, shared with the source clone), a bar, and **Cancel**.
  The header shows "Installing module — downloading 64%". A cancelled or failed install removes the unfinished
  module folder (retrying for a few seconds while git's killed processes let go of files).
- All git commands run with `GIT_TERMINAL_PROMPT=0` (never waiting for a password).
- One module job at a time.
- Module jobs are refused while a build or source update runs, and builds and pulls are refused while a
  module job runs, since both touch the source tree.
- **Rebuild needed:** the modules in `<source>\modules` differ from what the last build compiled.
  - Builds made by the panel record each module's folder and commit (job field `modules`), so updates count
    too.
  - For a build folder configured outside the panel, the module names come from its generated
    `modules\gen_scriptloader\<static|dynamic>\ModulesLoader.cpp` (one `Add<module>Scripts()` per module,
    `-` becomes `_`).
  - Installing and then removing the same module needs no rebuild. The page shows a banner linking to
    Compilation.
- **After a change:** rebuild and deploy.
  - Deploy installs the module's `.conf.dist` and creates the `.conf` if missing.
  - The module's SQL (`modules/<mod>/data/sql`) is applied by AzerothCore's DB updater when worldserver
    starts.
- **Storage:** jobs in `data\modules.json`, logs in `data\modules-logs\<id>.log`.
- **Endpoints:** `GET /api/modules/catalogue[?refresh=true]`, `GET /api/modules/installed`,
  `POST /api/modules/install {full_name}`, `POST /api/modules/install-url {url}`,
  `POST /api/modules/{name}/update`, `POST /api/modules/update-all`, `DELETE /api/modules/{name}`, and the
  shared `/jobs…` routes.
