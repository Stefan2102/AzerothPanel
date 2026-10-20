"""Send a console Ctrl-C / Ctrl-Break to a process the panel did not start.

Usage: python -I ctrl_event.py <pid> <c|break>

A console control event can only be raised from inside the target's console,
so this runs as its own short-lived process: it leaves its own (hidden)
console, attaches to the target's console, raises the event and exits.
The panel itself must never do this, because it would lose its own console.
"""
import ctypes
import sys
import time
from ctypes import wintypes

CTRL_C_EVENT, CTRL_BREAK_EVENT = 0, 1


def main() -> int:
    pid, kind = int(sys.argv[1]), sys.argv[2]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    k32.FreeConsole()
    if not k32.AttachConsole(pid):
        return 10
    ignore_all = handler_type(lambda _event: True)  # keep this helper alive while the event is delivered
    k32.SetConsoleCtrlHandler(ignore_all, True)
    ok = k32.GenerateConsoleCtrlEvent(CTRL_C_EVENT if kind == "c" else CTRL_BREAK_EVENT, 0)
    time.sleep(0.5)
    k32.FreeConsole()
    return 0 if ok else 11


if __name__ == "__main__":
    sys.exit(main())
