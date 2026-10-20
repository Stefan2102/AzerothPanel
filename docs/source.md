# Source code (Setup page)

Gets the AzerothCore source with git and makes it the panel's source folder (Compilation builds it). Code:
`backend/services/clone.py`, `backend/routers/source_setup.py`, `frontend/src/components/SourceSetup.tsx`.

## Choices
| Preset | Repository | Branch | Also |
|---|---|---|---|
| AzerothCore (official) | `https://github.com/azerothcore/azerothcore-wotlk.git` | `master` | |
| AzerothCore + Playerbots | `https://github.com/mod-playerbots/azerothcore-wotlk.git` | `Playerbot` (its default) | clones `mod-playerbots` (`master`) into `modules\` |
| Custom | any `https://` git URL | any branch | |

- **Branch list:** the refresh button lists the repository's branches with `git ls-remote --symref <url> HEAD refs/heads/*`,
  without downloading the repository, and selects its default branch. A branch that doesn't exist is flagged.
- **Folder:** always `<AzerothCore folder>\source`. It must be new or empty, so nothing is ever overwritten; to clone
  again, delete or rename it first. The card says why Clone is disabled (no AzerothCore folder yet, source
  already there, a job running).

## Job
- **Command:** `git clone --progress --branch <b> <url> <folder>` (full history), then the preset's modules. It runs
  with `GIT_TERMINAL_PROMPT=0`, so it never waits for a password.
- **Live progress:** git writes progress lines ending in a lone `\r` ("Receiving objects: 45% (…)").
  `ProcessRunner.run(on_progress=…)` passes those as live updates instead of log lines (any `\r` before `\n` still
  ends a normal line; Windows text output writes `\r\r\n`). The page shows a bar and the header shows the percentage.
  Under the bar is git's whole line incl. size and speed ("9% (21956/225075), 21.33 MiB | 301.00 KiB/s"): the
  percentage counts objects, so it can stand still for minutes while large files arrive.
- **Reload:** the page picks up a running clone from `/api/status` (`source.id`) and follows it again. The job
  stores `url`, `branch` and `modules`, so its output doesn't depend on what the form currently shows.
- **Failure or Cancel:** the folder is deleted, since it held only this clone's partial copy. It was new or empty
  before.
- **Success:** Compilation, Modules and Database setup use the new source right away (it's the fixed source
  folder). With the playerbots preset, Database setup then lists `acore_playerbots` by itself.
- **Exclusions:** refused while a build, pull or module job runs, and those are refused while a clone runs.
- **Storage:** `data\clone.json`, `data\clone-logs\<id>.log`.
- **Endpoints:** `GET /api/source/presets`, `GET /api/source/branches?url=`,
  `POST /api/source/clone {preset, url, branch}`, and the shared `/jobs…` routes.

Updating an existing source is on Compilation (Pull Latest Source); module updates are on Modules.
