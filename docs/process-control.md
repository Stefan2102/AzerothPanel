# Process control (verified 2026-10-11 on AzerothCore rev 93927ec9477f, MySQL 8.4.8, Windows 11)

## Why ConPTY
Tested first with plain pipes: authserver printed **nothing until it exited** (MSVC runtime fully
buffers redirected stdout) and Ctrl-C cannot be delivered to a process without a console.
Inside a pseudo console (pywinpty, ConPTY backend) all three servers behave like in a normal
console: live coloured output, the worldserver prompt (`AC>`), and writing `\x03` to the input
raises a real Ctrl-C.

- pywinpty `spawn(appname, cmdline)` builds `"<appname> <cmdline>"`, so `cmdline` holds only the
  arguments (passing the full command made mysqld fail with "Too many arguments").

## Ctrl-C must not be disabled for the panel (bug found 2026-10-11)
The "ignore Ctrl-C" flag of a process is **inherited by its children**. `start.bat` used to launch
the panel with `CREATE_NEW_PROCESS_GROUP`, which sets that flag, so authserver and mysqld silently
ignored the Ctrl-C that stops them ("Authserver is still shutting down after 60 s"). Worldserver was
unaffected because it stops via a typed command.
Fix: no `CREATE_NEW_PROCESS_GROUP` in `backend start`, and `run` calls
`enable_ctrl_c_for_children()` (`SetConsoleCtrlHandler(NULL, FALSE)`) before starting anything, so it
works however the panel is launched. Verified by launching a test parent *with*
`CREATE_NEW_PROCESS_GROUP` + the fix: authserver "Halting process" after 1 s, mysqld "Shutdown complete".
Recovery when stuck in that state: Ctrl-Break cannot be disabled; `ctrl_event.py <pid> break` stopped
authserver cleanly. MySQL has no graceful Ctrl-Break handling, so it was stopped with `mysqladmin shutdown`
(this install's `acore` user has the SHUTDOWN privilege; the stock one does not).

## Console view (read-only)
ConPTY does not produce a plain text stream: it draws on a fixed screen with cursor positioning and
queries the terminal (`ESC[c`, `ESC[?1004h`). Replaying that raw stream into a browser terminal only
renders correctly with an identical grid, and the browser terminal's automatic replies were typed
into the worldserver prompt (`^[[?1;2cannounce yo!`).
Now the stream is interpreted **server-side** with pyte (`services/console_screen.py`, 240×50 screen):
lines that scroll off the top are final and kept (10 000 per run), the visible screen is sent as
well. Browsers receive coloured text lines over `/ws/console/{key}` and render them as normal text.
Nothing is ever read from the browser, so the console is read-only by construction; GM commands go
through `POST /api/server/command` (validated, one line + Enter).

## Stop methods (all graceful)
| Service | Method | Verified result |
|---|---|---|
| worldserver | `server shutdown <countdown>` typed into its console | "Server shutdown in N second(s)" → "Halting process..." → DB pools closed → exit code 0. Players are saved by the core (`KickAll` + session update in `Main.cpp`). |
| authserver | Ctrl-C (`\x03` into its console) | "Halting process..." → DB pool closed → exit code 0 |
| mysqld | Ctrl-C | "Normal shutdown" → "Shutdown complete" → next start has **no InnoDB crash recovery** (the "XA crash recovery" lines at every start are normal). |

MySQL 8.4 on Windows runs **two processes**: a monitor and the server child. On Ctrl-C the monitor
exits first with `0xC000013A` (STATUS_CONTROL_C_EXIT) while the server is still finishing its
shutdown. Therefore "stopped" = the whole process tree is gone, never just the first PID (refresh the
tree before checking).
The `MySQLShutdown<pid>` named event does not exist for a `--console` mysqld 8.4 (checked both PIDs).

## Processes started outside the panel
Detected by executable path every 3 s and shown as "Online (external)". Stop = a short helper process
(`services/ctrl_event.py`) that attaches to the target's console and raises Ctrl-C (MySQL) or
Ctrl-Break (auth/world; both register `SIGBREAK` in `Main.cpp`). Verified for MySQL (Ctrl-C) and
authserver (Ctrl-Break). No console or GM command access for external processes.

## Rules enforced by `ServerManager`
- Start order MySQL → auth → world; each waits until its port accepts connections.
- Refuses to start if the port is already taken, or auth/world while MySQL is unreachable.
- Refuses to start auth/world while a job replaces what they use: a deploy step, a restore, or (world only)
  a client data job (`start_guard`, set in `app.py`). Those jobs check only at their start that the servers
  are stopped, so this closes the gap while they run.
- Stop is disabled while a service is still starting: the start is the running lifecycle job, and worldserver
  can't take `server shutdown` before it has loaded. Force kill stays available.
- Refuses to stop MySQL while auth or world is up.
- One lifecycle job at a time; stop timeouts never escalate to a kill — the user decides (Force kill).
- Panel shutdown (stop.bat or the sidebar button) stops everything the panel started in safe order
  before exiting. If the panel owns MySQL, external auth/world are stopped too (they depend on it).
  Closing a pseudo console kills what is attached, so this must happen first.
- If the panel process is killed (e.g. Task Manager), Windows closes the pseudo consoles and the
  servers get a console-close event — avoid; use stop.bat.
