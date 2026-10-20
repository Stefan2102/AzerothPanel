# Shortcuts (sidebar)

Programs the user starts from the panel, e.g. the WoW client or Ollama. Code: `backend/services/shortcuts.py`,
`backend/routers/shortcuts.py`, `frontend/src/pages/Shortcuts.tsx`, the Shortcuts group in
`frontend/src/components/Layout.tsx`.

## Stored
`settings.shortcuts` in `data\settings.json`, in sidebar order: `{id, name, path, args}`. The arrows on the Manage page change the order; Save keeps it.

| Field | Rule |
|---|---|
| name | 1-40 characters |
| path | full path to an existing `.exe`, `.bat`, `.cmd` or `.lnk` file (a folder is refused) |
| args | optional, one line, max 300 characters (e.g. `serve` for `ollama.exe`) |

At most 20. Everything is checked again on every save.

## Launch
- `os.startfile(path, arguments, cwd=<the file's folder>)` = ShellExecute, the same as a double-click in Explorer. Console programs
  (a `.bat`, `ollama.exe serve`) get their own console window; `.lnk` files use their own target and settings.
- The program is **not** a panel service: no ConPTY, no shared console (so no Ctrl-C side effects, see
  process-control.md), no status, never stopped or restarted. Shutting the panel down leaves it running.
- The launch request names the shortcut by id only; the path always comes from the saved settings.
- Remote access: a launch from another device starts the program on the PC the panel runs on.
- Saves and launches are written to the audit log (`shortcuts.update`, `shortcuts.launch`).

## Suggestions (Add buttons on the Shortcuts page)
Built at runtime from this PC only (the client folder chosen on Data Extraction and the user's own
`%LOCALAPPDATA%`); no paths are stored in the code. Shown while not added yet (same name, or a saved path inside the suggested one):
- **World of Warcraft**: `<client folder>\Wow.exe` from Data Extraction (`settings.client_dir`). When the
  client has no `Wow.exe` (patched clients, e.g. `Wow_patched.exe`), the entry gets the client folder and
  Browse opens there to pick the right exe; it can't be saved until a file is picked.
- **Ollama**: `%LOCALAPPDATA%\Programs\Ollama\ollama.exe` with `serve` (the Ollama server in its own console
  window; closing that window stops it). It fails with "address already in use" when Ollama's tray app already
  runs a server on port 11434.

## Endpoints
`GET /api/shortcuts` → `{items, suggestions}`, `PUT /api/shortcuts {items}` (validate + save),
`POST /api/shortcuts/{id}/launch`.
