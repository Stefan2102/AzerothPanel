# Build & Deploy

Sidebar group **Build & Deploy**. Phase 1 has two pages:
- **Setup** shows the Requirements and Database setup.
- **Compilation** builds and deploys.

Modules, Data Extraction and the installation wizard follow later; the plan is at the end of this file.
The panel never downloads or installs dependencies. You install them yourself; the panel finds them, checks
them and uses exactly the ones it shows.

## Requirements (Setup page)
`backend/services/requirements.py` holds the guide for each item: link, notes on what to pick while
installing, and what it's needed for. Links are buttons only: **Download** (`link`, tooltip `link_label`) plus
optional extra buttons (`more_links`, e.g. VS Build Tools); the notes carry no links. `backend/services/toolchain.py` detects the items.

| Item | Detected from | Version read from |
|---|---|---|
| Git | PATH, Program Files\Git | `git --version` |
| Visual Studio | `vswhere -products * -requires …VC.Tools.x86.x64` | `cl.exe` banner of the default toolset (`VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt`) |
| CMake | existing build cache (`CMAKE_COMMAND`), PATH, Program Files\CMake | `cmake -E capabilities` (also lists the generators) |
| Boost | cache `Boost_DIR`, env `BOOST_ROOT`/`Boost_ROOT`, `C:\local\boost_*` | `boost\version.hpp`; libraries must be in `lib64-msvc-*\cmake\Boost-*` |
| OpenSSL | cache `OPENSSL_INCLUDE_DIR`, env `OPENSSL_ROOT_DIR`, Program Files\OpenSSL-Win64, `C:\OpenSSL-Win64` | `include\openssl\opensslv.h`; needs `lib\VC\x64\MD\libcrypto.lib` + `bin\libcrypto-*.dll` (the "Light" installer has neither) |
| VC++ runtime | registry `HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64` | `Version`; must be ≥ the compiler toolset |
| MySQL | only the folder chosen with Change (`settings.mysql_dir`, anywhere; see [database.md](database.md)) | `include\mysql_version.h`; needs `lib\libmysql.lib` + `lib\libmysql.dll` |

- **Where paths come from, in order:**
  1. Your override ("your choice"), saved in `data\settings.json` until **Reset to detected**.
  2. The build folder's `CMakeCache.txt` ("from your existing build"), but only while that path is still
     installed: for Visual Studio it must still be an installation vswhere lists, for the others it must exist.
     A tool replaced since the last build (e.g. VS 2022 → VS 2026, Boost 1.91 → 1.92) falls through to
     detection, and the next configure clears the old cache (no mixed versions).
  3. Standard locations ("detected").

  This applies to the build tools only. Source, build folder and install folder have fixed places in the
  AzerothCore folder (`settings.LAYOUT`, see [usage.md](usage.md)) and can't be changed one by one. MySQL is never
  detected: it is the folder chosen with Change (no Reset).
- **Minimum versions** are parsed from the selected source, not hardcoded:

  | Dependency | File | Setting |
  |---|---|---|
  | CMake | `CMakeLists.txt` | `cmake_minimum_required` |
  | MSVC | `src/cmake/compiler/msvc/settings.cmake` | `MSVC_EXPECTED_VERSION` |
  | OpenSSL | `deps/openssl/CMakeLists.txt` | `OPENSSL_EXPECTED_VERSION` |
  | MySQL | `src/cmake/macros/FindMySQL.cmake` | `MYSQL_MINIMUM_VERSION` |
  | Boost | `deps/boost/CMakeLists.txt` | `BOOST_REQUIRED_VERSION` in the `if (WIN32)` branch |

  If a value can't be read, the status is "unknown"; it is never guessed.
- **Wiki recommendations are advice only and never block a build:** OpenSSL 3.x, MySQL 8.4 LTS (warns on
  9.x/26.x), no CMake RC, no VS Preview.
- **Visual Studio generator:** taken from CMake's own generator list (`Visual Studio <major> <year>`), matched by
  the installation's major version (17 → "Visual Studio 17 2022", 18 → "Visual Studio 18 2026"). The year from
  vswhere isn't used: its `productLineVersion` is "2022" for VS 2022 but "18" for VS 2026. An old CMake with a
  new VS shows "Update CMake".
- **Visual Studio path (Change):** any folder in or above the installation works (`…\18`, `…\18\Community`,
  `…\Community\Common7\IDE`); it's resolved to the installation folder, also for an already saved value
  (`toolchain.vs_installation_for`).

## Compilation page
- **Source bar** (top): AzerothCore's branch, commit, subject, date and local changes; the modules in
  `<source>\modules` as chips (revision on hover, a dot for local changes, red for a junction/symlink whose
  target is gone, which blocks the build because CMake would fail on it); **Pull Latest Source**.
  The folders themselves are fixed (`source`, `build`, `install\server` in the AzerothCore folder) and shown
  on Setup / Settings, not here. Before the first deploy the install folder may be missing or empty; building
  only needs the AzerothCore folder to be chosen.
- **Build Configuration** below it, full width.
- **Options:**
  - Build type: RelWithDebInfo (default), Release or Debug.
  - Always: `APPS_BUILD=all` (worldserver + authserver) and `WITH_WARNINGS=ON`. With it, MSVC also reports
    the warnings AzerothCore otherwise suppresses (C4996, C4985, C4244, C4267, C4619, C4512; see
    `src/cmake/compiler/msvc/settings.cmake`), so the log and the warning count get much bigger.
  - `TOOLS_BUILD` (extractors: none/all/db-only/maps-only), `SCRIPTS` and `MODULES`. Choices and
    defaults are parsed from `conf/dist/config.cmake`.
    - `static` builds the scripts or modules into worldserver.exe (the normal choice).
    - `dynamic` builds them as separate DLLs loaded at start.
    - `minimal-*` keeps only the Commands and Spells scripts.
    - `none` leaves them out.
  - Parallel jobs: `os.cpu_count()` of the PC the panel runs on (logical threads, e.g. 16 on an 8-core CPU with
    SMT), so each PC gets its own number; the page shows it in the hint (`cpu_threads` in `GET /api/build/toolchain`).
    Once a build ran, the used value is remembered like the other options. There is no "0 = auto": the value is
    always passed to `--parallel`.
  - Clean build, deploy when done.
  - The first values come from the existing build cache. The last used options are saved in
    `settings.build_options`.
- **Pull Latest Source** (button in the source bar, its own job of type "pull"):
  - Runs `git pull --ff-only` in the source folder with `GIT_TERMINAL_PROMPT=0`, so it never waits for a
    password.
  - Lists the new commits (`git log --oneline old..new`), or says "Already up to date".
  - Local changes in the way, or a diverged branch, make it fail and change nothing; git's own message is
    in the log.
  - Modules are not pulled here; that's for the Modules page.
- **Build steps** (`backend/services/build.py`, one job at a time, history in `data\build.json`, full logs in
  `data\build-logs\<id>.log`):
  1. **Configure:**
     - Command: `cmake -S src -B build -G "<VS generator>" -A x64 -DCMAKE_GENERATOR_INSTANCE=…
       -DCMAKE_INSTALL_PREFIX=<server folder> -DBoost_DIR=… -DOPENSSL_ROOT_DIR=… -DMYSQL_INCLUDE_DIR=…
       -DMYSQL_LIBRARY=… -DAPPS_BUILD=all -DWITH_WARNINGS=ON -DTOOLS_BUILD/SCRIPTS/MODULES=…`.
     - The child environment drops `BOOST_ROOT`, `BOOSTROOT`, `BOOST_INCLUDEDIR`, `BOOST_LIBRARYDIR`,
       `OPENSSL_ROOT_DIR` and `MYSQL_ROOT_DIR`. `deps/boost/CMakeLists.txt` reads `$ENV{Boost_ROOT}`, so a
       stray variable would otherwise override the chosen Boost. `VSLANG=1033` makes compiler messages
       English so errors and warnings can be counted.
     - If the source, generator, VS instance, Boost, OpenSSL or MySQL paths differ from the existing cache,
       `CMakeCache.txt` and `CMakeFiles` are deleted first (no mixed versions). "Clean build" deletes the
       whole build folder, but only if it contains a `CMakeCache.txt`.
  2. **Build:**
     - Command: `cmake --build build --config <cfg> --parallel <n> -- /nodeReuse:false /nologo /v:minimal`.
     - Progress of a fresh build (no cache before, clean, or toolchain changed) is compiled source files
       (cl prints each file name). An incremental build counts finished projects (`x.vcxproj -> file`
       lines). The totals come from the non-Utility `.vcxproj` files and their `<ClCompile>` items,
       leaving out CMake's own compiler checks under `CMakeFiles` (CompilerIdC, CompilerIdCXX), which are never built.
     - The files total counts every source file, but MSBuild skips up-to-date ones (e.g. what a failed earlier
       build already compiled), so an incremental build ends below it. The job's `fresh` flag tells the page:
       incremental runs show "N files compiled (only what changed)", and a finished build with fewer files than
       the total shows "N files compiled · M already up to date" instead of a stuck-looking "N / total".
     - Building works while the servers run; the output goes to `build\bin\<cfg>`.
  3. **Deploy** (optional, or the **Deploy only** button):
     - Needs worldserver and authserver stopped, because their exes can't be replaced while they run.
       If they run when a build finishes, the build logs "Not deployed". Stop them and click Deploy only.
     - `cmake --install` copies the exes, `configs\*.conf.dist` and `configs\modules\*.conf.dist`.
     - **Runtime DLLs:** `backend/services/pe.py` reads the import tables of every exe in the server folder
       and follows them recursively. Each non-Windows DLL is taken from the chosen OpenSSL (`bin`, root),
       MySQL (`lib`, `bin`) or Boost lib folder, never from System32. It is copied when it differs. A DLL
       found only in System32 that is not from Microsoft is an error, because it would load a stray copy.
     - `legacy.dll` comes from OpenSSL (`bin` or `lib\ossl-modules`) when the source asserts it
       (`OpenSSLCrypto.cpp`).
     - `libmysql.dll` must have the MySQL headers' version, otherwise AzerothCore stops with ACE00046.
     - PDBs, when the build type makes them (RelWithDebInfo, Debug), come from `build\bin\<cfg>`.
       They make crash dumps readable.
     - **Configs** (`build.sync_configs`). Before `cmake --install`, deploy records a hash of every
       `configs\**\*.conf.dist`. After it, each installed template is handled like this:
       - **No `.conf` yet:** created from its `.dist`.
       - **The `.dist` changed in this update** (core or module update): the `.conf` is **replaced** by the
         new template (no .bak copy). Your other settings (SOAP.Enabled,
         GameType, ...) come back as the template's defaults; you chose this behaviour.
       - **The `.dist` is unchanged:** the `.conf` is left alone. A deploy without a source or module update
         therefore never touches configs.

       Deploy never edits a value in a `.conf`: created or replaced configs are plain copies of their templates
       (AzerothCore's defaults). The job lists them (field `configs`); the log and the page then just say
       "Before starting the servers, go to Config Files" (no warning; see [config-values.md](config-values.md)).

       Code: `build.sync_configs`.
     - The job warns when the VC++ runtime is missing or older than the compiler.
- **Cancel** kills the whole process tree (cmake, MSBuild, cl, link), which is safe for a compile.
  MSBuild runs with `/nodeReuse:false`, so no worker nodes stay behind holding files. When the panel
  stops, a running build is cancelled.

## API
| Endpoint | Purpose |
|---|---|
| `GET /api/build/toolchain` | Workspace, items, `ready` / `deploy_ready` + problems, default options, `built` configs |
| `PUT /api/build/paths` `{key, path}` | Override for `cmake`, `vs`, `boost` or `openssl`; an empty path resets it (source, build and MySQL are fixed) |
| `POST /api/build/run` | Start a build (options as above) → `{job_id}` |
| `POST /api/build/deploy` `{config}` | Deploy only |
| `POST /api/build/pull` | Update the source (git pull --ff-only) |
| `GET /api/build/jobs` | Recent jobs (the page itself only shows the running or just-started job) |
| `GET /api/build/jobs/{id}?after=n` | A job, with only log lines numbered above `n` (`log_first`, `log_total`) |
| `GET /api/build/jobs/{id}/log` | Download the full log |
| `POST /api/build/jobs/{id}/cancel` | Cancel |

`/api/status` has `build: {id, type, step, progress}` while a job runs; the header shows it.

## Later phases (planned)
- **Modules:** GitHub topic catalogue (`azerothcore-module`, …), and install, update or remove in
  `<source>\modules` with git. A "rebuild needed" banner follows any change. Module SQL is left to
  AzerothCore's own updater.
- **Data Extraction:**
  - Status of `dbc`, `maps`, `vmaps`, `mmaps` and `Cameras` in `DataDir`.
  - Download the latest `wowgaming/client-data` release, or extract from a 3.3.5a client with the built
    tools: `map_extractor`, then `vmap4_extractor -s` + `vmap4_assembler Buildings vmaps`, then
    `mmaps_generator`.
- **Installation wizard:**
  - Clone the official repo or the playerbots fork.
  - Initialize the portable MySQL from the zip and create the user and databases.
  - Build, deploy, create the configs and extract the data.
