"""Zone names from the server's own AreaTable.dbc (WDBC, client 3.3.5a).

Field layout follows AreaTableEntryfmt in AzerothCore's DBCfmt.h:
"niiiixxxxxissssssssssssssssxiiiiixxx" -> ID at 0, AreaName_lang[16] at 11..26.
"""
from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

_NAME_FIRST, _NAME_LAST = 11, 26


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict[int, str]:
    data = Path(path).read_bytes()
    magic, records, fields, record_size, string_size = struct.unpack_from("<4s4I", data, 0)
    if magic != b"WDBC" or fields <= _NAME_LAST:
        raise ValueError(f"{path} is not a 3.3.5a AreaTable.dbc")
    strings_at = 20 + records * record_size
    names: dict[int, str] = {}
    for i in range(records):
        base = 20 + i * record_size
        area_id = struct.unpack_from("<I", data, base)[0]
        for f in range(_NAME_FIRST, _NAME_LAST + 1):
            offset = struct.unpack_from("<I", data, base + f * 4)[0]
            if offset:
                end = data.index(b"\0", strings_at + offset)
                names[area_id] = data[strings_at + offset:end].decode("utf-8", errors="replace")
                break
    return names


def area_names(data_dir: Path) -> dict[int, str]:
    dbc = data_dir / "dbc" / "AreaTable.dbc"
    if not dbc.is_file():
        return {}
    return _load(str(dbc), dbc.stat().st_mtime)
