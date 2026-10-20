"""Minimal reader for Windows PE files: imported DLL names and version resources.

Used to find out which DLLs the server binaries really load, so deployment can copy exactly
those (whatever OpenSSL/MySQL version they come from) instead of relying on a fixed list.
"""
from __future__ import annotations

import ctypes
import struct
from ctypes import wintypes
from pathlib import Path

IMPORT_DIR, DELAY_IMPORT_DIR = 1, 13


class PeError(Exception):
    pass


def imports(path: Path) -> list[str]:
    """Names of the DLLs a PE file imports (normal and delay-load), as written in the file."""
    data = path.read_bytes()
    try:
        if data[:2] != b"MZ":
            raise PeError("not a PE file")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise PeError("not a PE file")
        sections_count = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        dirs = opt + (112 if magic == 0x20B else 96)       # PE32+ / PE32
        dir_count = struct.unpack_from("<I", data, dirs - 4)[0]
        sections = []
        for i in range(sections_count):
            off = opt + opt_size + i * 40
            vsize, vaddr, raw_size, raw_ptr = struct.unpack_from("<IIII", data, off + 8)
            sections.append((vaddr, max(vsize, raw_size), raw_ptr))

        def offset(rva: int) -> int:
            for vaddr, size, raw_ptr in sections:
                if vaddr <= rva < vaddr + size:
                    return rva - vaddr + raw_ptr
            raise PeError(f"RVA {rva:#x} outside all sections")

        def name_at(rva: int) -> str:
            start = offset(rva)
            return data[start:data.index(b"\0", start)].decode("ascii", errors="replace")

        names: list[str] = []
        for index, entry_size, name_field in ((IMPORT_DIR, 20, 12), (DELAY_IMPORT_DIR, 32, 4)):
            if index >= dir_count:
                continue
            rva, size = struct.unpack_from("<II", data, dirs + index * 8)
            if not rva or not size:
                continue
            pos = offset(rva)
            while True:
                entry = data[pos:pos + entry_size]
                if len(entry) < entry_size or not any(entry):
                    break
                name_rva = struct.unpack_from("<I", entry, name_field)[0]
                if name_rva:
                    names.append(name_at(name_rva))
                pos += entry_size
        return names
    except (struct.error, ValueError) as exc:
        raise PeError(f"unreadable PE file ({exc})") from exc


# ---- version resource (via version.dll) -------------------------------------------------------

_version = ctypes.WinDLL("version")
_version.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
_version.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
_version.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.POINTER(wintypes.UINT)]


def version_info(path: Path) -> dict:
    """{"version": "8.4.8.0" | None, "company": str | None, "product": str | None}."""
    out: dict = {"version": None, "company": None, "product": None}
    size = _version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return out
    buf = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(str(path), 0, size, buf):
        return out
    ptr, length = ctypes.c_void_p(), wintypes.UINT()
    if _version.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(length)) and length.value >= 52:
        ms, ls = struct.unpack_from("<II", ctypes.string_at(ptr.value, 52), 8)
        out["version"] = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    if _version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(length)) and length.value >= 4:
        lang, codepage = struct.unpack("<HH", ctypes.string_at(ptr.value, 4))
        for key, field in (("company", "CompanyName"), ("product", "ProductName")):
            query = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{field}"
            if _version.VerQueryValueW(buf, query, ctypes.byref(ptr), ctypes.byref(length)) and length.value:
                out[key] = ctypes.wstring_at(ptr.value, length.value).rstrip("\0").strip() or None
    return out
