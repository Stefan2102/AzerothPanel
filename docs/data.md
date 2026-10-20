# Data Extraction (client data)

Sidebar: Build & Deploy -> **Data Extraction**. Worldserver reads `dbc`, `maps`, `vmaps`, `mmaps` and
`Cameras` from `DataDir` (worldserver.conf, relative to the server folder). Code:
`backend/services/client_data.py`, `backend/routers/client_data.py`, `frontend/src/pages/DataExtraction.tsx`.

## Status card
- **Tiles:** one each for DBC, Maps, VMaps and MMaps, showing file counts. DBC, Maps and VMaps are
  required; MMaps are optional (creature pathfinding).
- **Ready:** shown when the required three are present.
- **Installed release:** read from `DataDir\data-version` (`INSTALLED_VERSION=v20.0`). This is the same
  file AzerothCore's own installer writes.
- **Expected release:** parsed from the source, `apps/installer/includes/functions.sh`
  (`inst_download_client_data` -> `VERSION=v20.0`). The core pins the release whose map, vmap and mmap
  format it reads, so a mismatch is shown as a warning.

## Download Pre-Extracted Data (recommended)
1. Release: the one the source pins, or the latest GitHub release when no source is set
   (`api.github.com/repos/wowgaming/client-data/releases/latest`).
2. Download `https://github.com/wowgaming/client-data/releases/download/<v>/data.zip` (v20.0: 1,196,168,257 bytes)
   to `<server>\.client-data-<v>.zip`:
   - Resumable: an interrupted download continues with an HTTP Range request.
   - Progress shows MB done / total, the speed (averaged over the last ~5 s, job field `speed`) and the time left.
   - When the release the source expects is already installed and complete, the button reads "Download Again" and
     asks first (it would replace the data with the same files).
   - Free-space check: the zip plus 3x its size.
3. Unpack into `<server>\.client-data-download`. Every member's path is checked, and zipfile verifies each
   CRC.
4. Swap in (worldserver must be stopped):
   - Each folder (`Cameras`, `dbc`, `maps`, `mmaps`, `vmaps`) is moved into place, and the old one is
     deleted only after all of them have moved.
   - On an error every folder, including the one that failed, is put back.
   - Windows refuses to rename a folder while a file in it is open (antivirus and indexing do this briefly
     to new files), so each rename is retried for about 10 s before it counts as a failure.
5. Write `data-version`, then delete the zip.

## Extract from Local Client
- **Client check:** `Wow.exe` must have file version `3.3.5.12340`, read from its version resource, and
  `Data\*.MPQ` must exist. Other clients are refused, for example Legion is 7.3.5.26972.
- **Tools** come from the server folder and are deployed when compiled with Tools = all:
  `map_extractor`, `vmap4_extractor`, `vmap4_assembler`, `mmaps_generator`.
- **Steps**, all run in the work folder `<server>\.client-data-extract`:

  | Step | Command | Notes |
  |---|---|---|
  | DBC & Maps | `map_extractor -i client -o . -e <flags>` | Flags: MAP 1, DBC 2, Camera 4; Cameras come with DBC |
  | VMaps | `vmap4_extractor -s -d client/Data`, then `vmap4_assembler Buildings vmaps` | Buildings is removed afterwards. "No such file" / "Couldn't open RootWmo" lines are normal. |
  | MMaps | `mmaps_generator --config <server>\mmaps-config.yaml` | Its `dataDir: "./"` is the work folder. Maps/vmaps that weren't extracted in this run are linked in read-only from DataDir. This can take hours. |

- **Progress:** map_extractor prints `Extract <map> (i/N)` per map, then `Processing....<n>%` ended by a lone
  `\r` (a meter that overwrites itself). The tools run with `ProcessRunner.run(..., on_progress=...)`: `\r` text
  only moves the bar ("i/N maps", within the map by its %), lines ended by `\n` go to the log. Without that the
  meters piled up into one huge log line per map.
- **Short paths:**
  - `client` is a directory junction to the client folder. map_extractor keeps `-i` and `-o` in
    128-character buffers and silently cuts longer paths (`src/tools/map_extractor/System.cpp`,
    `MAX_PATH_LENGTH 128`), so tools get short relative paths only.
  - Junctions are unlinked, never followed, when the work folder is removed, so the client is never
    modified.
- **Install:** only the produced folders are swapped in, the same way as for a download. Data types you
  didn't select stay as they are.
- **Version file:** `data-version` then says `INSTALLED_VERSION=client-12340`. The page shows "Extracted from a client"
  and compares release versions only for downloaded data.

## Jobs
- **Storage:** `data\client-data.json` and `data\client-data-logs\<id>.log`. It's one job at a time,
  separate from builds (`JobSlot`).
- **Endpoints:** `GET /api/client-data` (status), `POST /api/client-data/download`,
  `POST /api/client-data/extract {client_dir, types}`, and the shared `/jobs`, `/jobs/{id}?after=`,
  `/jobs/{id}/log`, `/jobs/{id}/cancel`.
- **Refused while:**
  - worldserver runs (data folders get replaced; checked again right before the swap);
  - a build runs (extract only, since the tools may be replaced);
  - another data job runs.

  Deploying is refused while a data job runs.
- **Cancel** kills the extractor tool, or stops the download between chunks. The partial zip stays for
  resuming; the work folder is removed.
- **Header and toast:** the header shows the running job and its percentage (`/api/status` -> `data`),
  and a toast announces when it ends.
