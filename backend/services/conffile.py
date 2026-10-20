"""Small edits to AzerothCore .conf files: set the value of keys that are already in the file.

Only existing `Key = ...` lines are changed (comments, order and everything else stay), so a key that
a config doesn't have (e.g. DataDir in authserver.conf) is never added.
"""
from __future__ import annotations

import re
from pathlib import Path


def set_values(path: Path, values: dict[str, str]) -> list[str]:
    """Set `Key = "value"` for each key present in the file. Returns the keys that changed."""
    text = path.read_text(encoding="utf-8", errors="replace")
    changed = []
    for key, value in values.items():
        line = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*)(.*)$', re.M)
        quoted = f'"{value}"'
        m = line.search(text)
        if m and m.group(2).strip() != quoted:
            text = text[:m.start(2)] + quoted + text[m.end(2):]
            changed.append(key)
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def set_raw(path: Path, values: dict[str, str]) -> list[str]:
    """Like set_values, but keeps each line's own style: quoted stays quoted, a bare number stays bare."""
    text = path.read_text(encoding="utf-8", errors="replace")
    changed = []
    for key, value in values.items():
        m = re.compile(rf'^(\s*{re.escape(key)}\s*=\s*)(.*?)\s*$', re.M).search(text)
        if not m:
            continue
        old = m.group(2)
        new = f'"{value}"' if old.startswith('"') else value
        if old != new:
            text = text[:m.start(2)] + new + text[m.end(2):]
            changed.append(key)
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed
