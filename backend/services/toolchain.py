"""Detection of the build toolchain and of the AzerothCore workspace (read-only).

Source and build folder have fixed places in the AzerothCore folder (settings.LAYOUT); MySQL is the folder
the user chose (settings.mysql_dir), never detected.
For the build tools, each path comes from, in order:
  1. the user's override in settings (kept until "Reset to detected"),
  2. the build folder's CMakeCache.txt (what the last build used),
  3. standard install locations / PATH / environment variables.
Versions are read from the installed files themselves; minimum versions are parsed from the
selected AzerothCore source, never hardcoded here.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import winreg
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from ..settings import Settings
from . import requirements

PROGRAM_FILES = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
PROGRAM_FILES_X86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
VSWHERE = PROGRAM_FILES_X86 / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
VC_TOOLS = "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"


def version_tuple(text: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text or ""))


def _run(args: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def same_path(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


# ---- CMakeCache.txt -------------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _read_cache(path: str, _mtime_key: float) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line[0] in "#/":
            continue
        key, sep, value = line.partition("=")
        if sep:
            out[key.split(":", 1)[0]] = value
    return out


def read_cache(path: Path) -> dict[str, str]:
    return _read_cache(str(path), _mtime(path))


# ---- items ------------------------------------------------------------------------------------------

@dataclass
class Item:
    key: str
    path: str | None = None
    origin: str | None = None          # override (the user's choice) | build | detected
    version: str | None = None
    required: str | None = None        # minimum from the source
    status: str = "missing"            # ok | too_old | missing | invalid | unknown
    message: str | None = None
    advice: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def public(self) -> dict:
        guide = requirements.GUIDE[self.key]
        return {"key": self.key, "label": guide["label"], "link": guide["link"], "link_label": guide["link_label"],
                "more_links": guide.get("more_links", []),
                "notes": guide["notes"], "needed_for": guide["needed_for"], "path_kind": guide["path_kind"],
                "path": self.path, "origin": self.origin, "version": self.version, "required": self.required,
                "status": self.status, "message": self.message, "advice": self.advice,
                "candidates": self.candidates, "details": self.details}


def _rate(item: Item) -> None:
    """Compare a found version with the source's minimum."""
    if item.status in ("missing", "invalid"):
        return
    if item.version is None:
        item.status, item.message = "unknown", item.message or "Could not read the version."
    elif item.required and version_tuple(item.version) < version_tuple(item.required):
        item.status, item.message = "too_old", f"Version {item.version} is older than the required {item.required}."
    else:
        item.status = "ok"


def _pick(item: Item, override: str, from_build: str | None, found: list[Path],
          installed: Callable[[Path], bool] = Path.exists) -> Path | None:
    """Choose the path for an item and fill in its origin and candidate list.
    The last build's path counts only while it's still `installed` (a tool can be uninstalled or replaced
    since, e.g. VS 2022 -> VS 2026); otherwise detection decides and the next configure clears the cache."""
    if from_build and not installed(Path(from_build)):
        from_build = None
    seen: list[str] = []
    for p in ([Path(from_build)] if from_build else []) + found:
        if not any(same_path(p, s) for s in seen):
            seen.append(str(p))
    item.candidates = [{"path": p} for p in seen]
    if override:
        item.origin = "override"
        return Path(override)
    if from_build:
        item.origin = "build"
        return Path(from_build)
    if found:
        item.origin = "detected"
        return found[0]
    return None


# ---- Boost --------------------------------------------------------------------------------------------

def _boost_version(root: Path) -> str | None:
    header = root / "boost" / "version.hpp"
    if not header.is_file():
        return None
    m = re.search(r"#define\s+BOOST_VERSION\s+(\d+)", header.read_text(encoding="utf-8", errors="replace"))
    if not m:
        return None
    v = int(m.group(1))
    return f"{v // 100000}.{v // 100 % 1000}.{v % 100}"


def _boost_config_dir(root: Path) -> Path | None:
    """<root>/lib64-msvc-<toolset>/cmake/Boost-<version>: the prebuilt 64-bit libraries, newest toolset."""
    configs = sorted(root.glob("lib64-msvc-*/cmake/Boost-*/BoostConfig.cmake"),
                     key=lambda p: version_tuple(p.parts[-4]), reverse=True)
    return configs[0].parent if configs else None


def _boost_root_from_config(config_dir: str) -> str | None:
    for parent in Path(config_dir).parents:
        if (parent / "boost" / "version.hpp").is_file():
            return str(parent)
    return None


def _boost_candidates() -> list[Path]:
    found: list[Path] = []
    for var in ("BOOST_ROOT", "Boost_ROOT"):
        if os.environ.get(var):
            found.append(Path(os.environ[var]))
    local = Path(os.environ.get("SystemDrive", "C:") + "\\") / "local"
    if local.is_dir():
        found.extend(sorted(local.glob("boost_*"), key=lambda p: version_tuple(p.name), reverse=True))
    return [p for p in found if (p / "boost" / "version.hpp").is_file()]


def detect_boost(settings: Settings, cache: dict, req: dict) -> Item:
    item = Item("boost", required=req.get("boost"))
    from_build = _boost_root_from_config(cache["Boost_DIR"]) if cache.get("Boost_DIR") else None
    root = _pick(item, settings.boost_dir, from_build, _boost_candidates())
    for c in item.candidates:
        c["version"] = _boost_version(Path(c["path"]))
    if root is None:
        item.message = "Boost was not found."
        return item
    item.path = str(root)
    item.version = _boost_version(root)
    if item.version is None:
        item.status, item.message = "invalid", "No boost\\version.hpp in this folder."
        return item
    config = _boost_config_dir(root)
    if config is None:
        item.status = "invalid"
        item.message = "No 64-bit prebuilt libraries (lib64-msvc-*) in this folder. Install the msvc-14.x-64 package."
        return item
    item.details = {"config_dir": str(config), "libraries": config.parents[1].name}
    item.status = "found"
    _rate(item)
    env_roots = [os.environ[v] for v in ("BOOST_ROOT", "Boost_ROOT") if os.environ.get(v)]
    if any(not same_path(r, root) for r in env_roots):
        item.advice.append({"tone": "info", "text": f"BOOST_ROOT points to {env_roots[0]}. The panel ignores it "
                                                    "and builds with the folder shown here."})
    return item


# ---- OpenSSL ------------------------------------------------------------------------------------------

def _openssl_version(root: Path) -> str | None:
    header = root / "include" / "openssl" / "opensslv.h"
    if not header.is_file():
        return None
    text = header.read_text(encoding="utf-8", errors="replace")
    parts = [re.search(rf"#\s*define\s+OPENSSL_VERSION_{k}\s+(\d+)", text) for k in ("MAJOR", "MINOR", "PATCH")]
    if all(parts):
        return ".".join(m.group(1) for m in parts)  # type: ignore[union-attr]
    m = re.search(r'OPENSSL_VERSION_TEXT\s+"OpenSSL\s+([\w.]+)', text)   # 1.x headers
    return m.group(1) if m else None


def _openssl_candidates() -> list[Path]:
    found = [PROGRAM_FILES / "OpenSSL-Win64", Path(os.environ.get("SystemDrive", "C:") + "\\") / "OpenSSL-Win64"]
    if os.environ.get("OPENSSL_ROOT_DIR"):
        found.insert(0, Path(os.environ["OPENSSL_ROOT_DIR"]))
    return [p for p in found if (p / "include" / "openssl" / "opensslv.h").is_file()]


def openssl_runtime_dirs(root: Path) -> list[Path]:
    return [d for d in (root / "bin", root) if d.is_dir()]


def find_legacy_provider(root: Path) -> Path | None:
    for p in (root / "bin" / "legacy.dll", root / "lib" / "ossl-modules" / "legacy.dll"):
        if p.is_file():
            return p
    return None


def detect_openssl(settings: Settings, cache: dict, req: dict) -> Item:
    item = Item("openssl", required=req.get("openssl"))
    include = cache.get("OPENSSL_INCLUDE_DIR")
    from_build = str(Path(include).parent) if include and include.endswith("include") else None
    root = _pick(item, settings.openssl_dir, from_build, _openssl_candidates())
    for c in item.candidates:
        c["version"] = _openssl_version(Path(c["path"]))
    if root is None:
        item.message = "OpenSSL was not found."
        return item
    item.path = str(root)
    item.version = _openssl_version(root)
    if item.version is None:
        item.status = "invalid"
        item.message = ("No include\\openssl in this folder, so it can't be used for compiling "
                        "(the \"Light\" installer has none). Install the full Win64 OpenSSL.")
        return item
    libs = [p for p in (root / "lib" / "VC" / "x64" / "MD" / "libcrypto.lib", root / "lib" / "libcrypto.lib") if p.is_file()]
    dlls = [p.name for d in openssl_runtime_dirs(root) for p in d.glob("libcrypto-*.dll")]
    if not libs:
        item.status, item.message = "invalid", "No libcrypto.lib (64-bit, /MD) in this folder."
        return item
    if not dlls:
        item.status = "invalid"
        item.message = "No libcrypto-*.dll in this folder's bin. Reinstall and copy the DLLs to the OpenSSL bin directory."
        return item
    legacy = find_legacy_provider(root)
    item.details = {"lib": str(libs[0]), "dll": sorted(set(dlls))[0], "legacy": str(legacy) if legacy else None}
    item.status = "found"
    _rate(item)
    item.advice.extend(requirements.openssl_advice(item.version))
    return item


# ---- MySQL (headers + client library for building) ---------------------------------------------------

def _mysql_version(root: Path) -> str | None:
    header = root / "include" / "mysql_version.h"
    if not header.is_file():
        return None
    m = re.search(r'#define\s+MYSQL_SERVER_VERSION\s+"([\d.]+)', header.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def detect_mysql(settings: Settings, cache: dict, req: dict) -> Item:
    """MySQL is the folder the user chose (the extracted ZIP, anywhere), never detected. The same folder is
    compiled against (include\\, lib\\) and runs as the database server."""
    item = Item("mysql", required=req.get("mysql"))
    root = settings.mysql_home
    if root is None:
        item.status = "missing"
        item.message = "Extract the MySQL ZIP anywhere (e.g. install\\database in your AzerothCore folder), then choose it with Change."
        return item
    item.path, item.origin = str(root), "override"
    item.version = _mysql_version(root)
    if item.version is None:
        item.status = "missing" if not root.exists() else "invalid"
        item.message = (f"{root} no longer exists. Choose the MySQL folder again with Change." if not root.exists()
                        else f"{root} has no include\\mysql_version.h. Choose the folder of the extracted MySQL ZIP.")
        return item
    lib, dll = root / "lib" / "libmysql.lib", root / "lib" / "libmysql.dll"
    if not lib.is_file() or not dll.is_file():
        item.status, item.message = "invalid", "lib\\libmysql.lib or lib\\libmysql.dll is missing in this folder."
        return item
    item.details = {"include": str(root / "include"), "lib": str(lib), "dll": str(dll)}
    item.status = "found"
    _rate(item)
    item.advice.extend(requirements.mysql_advice(item.version))
    return item


# ---- CMake ---------------------------------------------------------------------------------------------

@lru_cache(maxsize=8)
def _cmake_capabilities(exe: str, _mtime_key: float) -> dict | None:
    try:
        proc = _run([exe, "-E", "capabilities"])
        return json.loads(proc.stdout) if proc.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def cmake_capabilities(exe: Path) -> dict | None:
    return _cmake_capabilities(str(exe), _mtime(exe))


def detect_cmake(settings: Settings, cache: dict, req: dict) -> Item:
    item = Item("cmake", required=req.get("cmake"))
    found = [Path(p) for p in (shutil.which("cmake"), str(PROGRAM_FILES / "CMake" / "bin" / "cmake.exe")) if p and Path(p).is_file()]
    exe = _pick(item, settings.cmake_exe, cache.get("CMAKE_COMMAND"), found)
    if exe is None:
        item.message = "CMake was not found."
        return item
    item.path = str(exe)
    caps = cmake_capabilities(exe) if exe.is_file() else None
    if caps is None:
        item.status, item.message = "invalid", "This is not a working cmake.exe."
        return item
    item.version = caps.get("version", {}).get("string")
    item.details = {"generators": [g["name"] for g in caps.get("generators", [])]}
    item.status = "found"
    _rate(item)
    item.advice.extend(requirements.cmake_advice(item.version))
    return item


# ---- Visual Studio ---------------------------------------------------------------------------------------

@lru_cache(maxsize=2)
def _vswhere(_mtime_key: float) -> list[dict]:
    try:
        proc = _run([str(VSWHERE), "-all", "-products", "*", "-requires", VC_TOOLS, "-format", "json", "-utf8"])
        return json.loads(proc.stdout.decode("utf-8")) if proc.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


@lru_cache(maxsize=8)
def _cl_version(cl: str, _mtime_key: float) -> str | None:
    try:
        banner = _run([cl]).stderr.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"Version\s+(\d+\.\d+\.\d+)", banner)
    return m.group(1) if m else None


def vs_instances() -> list[dict]:
    out = []
    for inst in _vswhere(_mtime(VSWHERE)):
        path = Path(inst["installationPath"])
        default = path / "VC" / "Auxiliary" / "Build" / "Microsoft.VCToolsVersion.default.txt"
        toolset = default.read_text(encoding="utf-8").strip() if default.is_file() else None
        cl = path / "VC" / "Tools" / "MSVC" / toolset / "bin" / "Hostx64" / "x64" / "cl.exe" if toolset else None
        out.append({
            "path": str(path),
            "name": inst.get("displayName") or inst.get("productId"),
            "version": inst.get("installationVersion"),
            "prerelease": bool(inst.get("isPrerelease")),
            "toolset": toolset,
            "compiler": _cl_version(str(cl), _mtime(cl)) if cl and cl.is_file() else None,
        })
    out.sort(key=lambda i: version_tuple(i["version"]), reverse=True)
    return out


def generator_for(instance: dict, cmake: Item) -> str | None:
    """The CMake generator for a VS instance, as listed by `cmake -E capabilities`: "Visual Studio <major> <year>".
    Matched by the major version only; vswhere's productLineVersion is the year up to VS 2022 but "18" for VS 2026."""
    prefix = f"Visual Studio {version_tuple(instance['version'])[0]} "
    return next((g for g in cmake.details.get("generators", []) if g.startswith(prefix)), None)


def vs_installation_for(path: Path, instances: list[dict]) -> dict | None:
    """The installation a folder belongs to: the folder itself, one inside it (e.g. Common7\\IDE) or the
    only installation below it (e.g. ...\\Microsoft Visual Studio\\18 -> ...\\18\\Community)."""
    inside = [i for i in instances if same_path(i["path"], path) or Path(i["path"]) in path.parents]
    below = [i for i in instances if path in Path(i["path"]).parents]
    match = inside or (below if len(below) == 1 else [])
    return match[0] if match else None


def detect_vs(settings: Settings, cache: dict, req: dict, cmake: Item) -> Item:
    item = Item("vs", required=req.get("vs"))
    instances = vs_instances()
    override = settings.vs_instance
    if override:        # a saved folder in or above the installation means that installation
        inst = vs_installation_for(Path(override), instances)
        override = inst["path"] if inst else override
    root = _pick(item, override, cache.get("CMAKE_GENERATOR_INSTANCE"), [Path(i["path"]) for i in instances],
                 installed=lambda p: vs_installation_for(p, instances) is not None)
    for c in item.candidates:
        info = next((i for i in instances if same_path(i["path"], c["path"])), None)
        c["version"] = f"{info['name']} {info['version']}" if info else None
    if root is None:
        item.message = "No Visual Studio with the C++ build tools was found."
        return item
    item.path = str(root)
    inst = next((i for i in instances if same_path(i["path"], root)), None)
    if inst is None:
        item.status = "invalid"
        item.message = "No Visual Studio with the \"Desktop development with C++\" workload at this path."
        return item
    item.version = inst["compiler"]
    item.details = {"name": inst["name"], "product_version": inst["version"],
                    "toolset": inst["toolset"], "generator": generator_for(inst, cmake) if cmake.status == "ok" else None}
    item.status = "found"
    _rate(item)
    if item.status == "ok" and cmake.status == "ok" and item.details["generator"] is None:
        item.status = "invalid"
        item.message = f"CMake {cmake.version} has no generator for {inst['name']}. Update CMake."
    item.advice.extend(requirements.vs_advice(inst))
    return item


# ---- Git / VC++ runtime -------------------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _git_version(exe: str, _mtime_key: float) -> str | None:
    try:
        m = re.search(r"(\d+\.\d+\.\d+)", _run([exe, "--version"]).stdout.decode(errors="replace"))
    except (OSError, subprocess.SubprocessError):
        return None
    return m.group(1) if m else None


def detect_git() -> Item:
    item = Item("git")
    found = [Path(p) for p in (shutil.which("git"), str(PROGRAM_FILES / "Git" / "cmd" / "git.exe")) if p and Path(p).is_file()]
    exe = _pick(item, "", None, found)
    item.candidates = []
    if exe is None:
        item.message = "Git was not found on PATH."
        return item
    item.path = str(exe)
    item.version = _git_version(str(exe), _mtime(exe))
    item.status = "found"
    _rate(item)
    return item


def vc_runtime_version() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                            0, winreg.KEY_READ | winreg.KEY_WOW64_32KEY) as key:
            if winreg.QueryValueEx(key, "Installed")[0] != 1:
                return None
            return str(winreg.QueryValueEx(key, "Version")[0]).lstrip("v")
    except OSError:
        return None


def detect_vcredist(vs: Item) -> Item:
    item = Item("vcredist")
    item.version = vc_runtime_version()
    if item.version is None:
        item.message = "The Visual C++ x64 runtime is not installed."
        return item
    item.origin = "detected"
    # Binaries built with a toolset need at least that toolset's runtime.
    toolset = vs.details.get("toolset")
    item.required = ".".join(toolset.split(".")[:2]) if toolset else None
    item.status = "found"
    _rate(item)
    return item


# ---- source ------------------------------------------------------------------------------------------------

def is_source(path: Path) -> bool:
    return (path / "CMakeLists.txt").is_file() and (path / "src" / "server" / "apps").is_dir()


def source_requirements(source: Path | None) -> dict:
    return requirements.parse_minimums(source) if source and is_source(source) else {}


def build_options(source: Path) -> dict:
    """Choices for SCRIPTS / MODULES / APPS_BUILD / TOOLS_BUILD and their defaults, from conf/dist/config.cmake."""
    conf = source / "conf" / "dist" / "config.cmake"
    if not conf.is_file():
        return {}
    text = conf.read_text(encoding="utf-8", errors="replace")
    lists = {m.group(1): m.group(2).split() for m in re.finditer(r"set\(\s*(\w+_AVAILABLE_OPTIONS)\s+([^)]*)\)", text)}
    out = {}
    for m in re.finditer(r"set_property\(\s*CACHE\s+(\w+)\s+PROPERTY\s+STRINGS\s+\$\{(\w+)\}\s*\)", text):
        name, var = m.groups()
        default = re.search(rf'set\(\s*{name}\s+"([^"]*)"\s+CACHE', text)
        if var in lists:
            out[name] = {"choices": lists[var], "default": default.group(1) if default else None}
    return out


# ---- everything ---------------------------------------------------------------------------------------------

def workspace(settings: Settings) -> dict:
    """Source, build and install folder (fixed places in the AzerothCore folder) and the build's CMake
    cache (empty when it was never configured). All None until the AzerothCore folder is chosen."""
    source, build = settings.source_path, settings.build_path
    cache_file = build / "CMakeCache.txt" if build else None
    return {
        "source": str(source) if source else None,
        "source_valid": bool(source and is_source(source)),
        "build": str(build) if build else None,
        "install": settings.server_dir or None,
        "cache": read_cache(cache_file) if cache_file and cache_file.is_file() else {},
    }


def detect_all(settings: Settings) -> dict:
    ws = workspace(settings)
    cache = ws.pop("cache")
    req = source_requirements(Path(ws["source"]) if ws["source"] else None)
    cmake = detect_cmake(settings, cache, req)
    vs = detect_vs(settings, cache, req, cmake)
    items = [detect_git(), vs, cmake, detect_boost(settings, cache, req), detect_openssl(settings, cache, req),
             detect_vcredist(vs), detect_mysql(settings, cache, req)]
    return {"workspace": ws, "items": items, "cache": cache}
