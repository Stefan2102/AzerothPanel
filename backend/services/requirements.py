"""Install guide for the build dependencies, and the version rules that apply to them.

The panel never installs anything: the Requirements card shows what was found, what the selected
AzerothCore source needs, where to download each item and what to select while installing it.
Guide texts follow the AzerothCore wiki (windows-requirements, windows-core-installation); update
them here when the wiki changes. Hard minimums come from the source (parse_minimums), the wiki's
recommendations are only shown as advice.
"""
from __future__ import annotations

import re
from pathlib import Path

GUIDE: dict[str, dict] = {
    "git": {
        "label": "Git",
        "link": "https://git-scm.com/download/win",
        "link_label": "git-scm.com",
        "needed_for": "Pulling the source and modules",
        "path_kind": None,
        "notes": [
            "Download the standalone 64-bit installer.",
            "On the PATH page choose \"Git from the command line and also from 3rd-party software\".",
            "Restart the panel afterwards so it sees the new PATH.",
        ],
    },
    "vs": {
        "label": "Visual Studio 2022 (C++ compiler)",
        # Microsoft's fixed link to the current VS 2022 (version 17) Community installer. visualstudio.microsoft.com
        # only offers the newest version; its "older downloads" page needs a Visual Studio subscription.
        "link": "https://aka.ms/vs/17/release/vs_community.exe",
        "link_label": "vs_community.exe (2022)",
        "more_links": [{"label": "Build Tools", "link": "https://aka.ms/vs/17/release/vs_buildtools.exe",
                        "title": "Build Tools for Visual Studio 2022: only the compiler, no IDE"}],
        "needed_for": "Compiling",
        "path_kind": "instance",
        "notes": [
            "Visual Studio 2022 Community (free), the version AzerothCore requires. Don't use a Preview version.",
            "Only want the compiler, no IDE? Build Tools for Visual Studio 2022 work too (Build Tools button).",
            "In the installer select the workload \"Desktop development with C++\".",
            "If several versions are installed, pick the one to build with here.",
        ],
    },
    "cmake": {
        "label": "CMake",
        "link": "https://cmake.org/download/",
        "link_label": "cmake.org",
        "needed_for": "Compiling",
        "path_kind": "file",
        "notes": [
            "Download the latest release \"Windows x64 Installer\" (windows-x86_64.msi). Never a release candidate (rc).",
            "Let the installer add CMake to the system PATH.",
        ],
    },
    "boost": {
        "label": "Boost",
        "link": "https://www.boost.org/releases/latest/",
        "link_label": "boost.org (latest release)",
        "needed_for": "Compiling",
        "path_kind": "folder",
        "notes": [
            "Under the release's binaries download the 64-bit installer for Visual Studio 2022: "
            "boost_<version>-msvc-14.3-64.exe.",
            "Install to the default folder (C:\\local\\boost_<version>) or anywhere you like.",
            "Setting BOOST_ROOT is not needed here: the panel passes the folder to CMake itself.",
        ],
    },
    "openssl": {
        "label": "OpenSSL",
        "link": "https://slproweb.com/products/Win32OpenSSL.html",
        "link_label": "slproweb.com",
        "needed_for": "Compiling and running",
        "path_kind": "folder",
        "notes": [
            "Pick a \"Win64 OpenSSL\" entry that is NOT \"Light\" (the Light one has no files for compiling).",
            "When asked where to copy the OpenSSL DLLs, choose \"The OpenSSL binaries (/bin) directory\", "
            "not the Windows system directory.",
            "If the installer asks for the Visual C++ runtime, install that first (row below).",
            "Deploying copies the needed DLLs (libcrypto, libssl, legacy.dll) next to the server for you.",
        ],
    },
    "vcredist": {
        "label": "Visual C++ Redistributable (x64)",
        "link": "https://aka.ms/vc14/vc_redist.x64.exe",
        "link_label": "vc_redist.x64.exe",
        "needed_for": "Running the servers",
        "path_kind": None,
        "notes": [
            "Needed by the server binaries and by the OpenSSL installer.",
            "It's usually already installed together with Visual Studio. Install it again when it's older than your compiler.",
        ],
    },
    "mysql": {
        "label": "MySQL 8.4 LTS",
        "link": "https://dev.mysql.com/downloads/file/?id=556213",
        "link_label": "mysql-8.4.11-winx64.zip",
        "needed_for": "Compiling and the database server",
        "path_kind": "folder",      # the user's choice, anywhere (settings.mysql_dir); never detected
        "notes": [
            "Take the ZIP Archive (portable), at the bottom click \"No thanks, just start my download\".",
            "Extract it anywhere, e.g. install\\database in your AzerothCore folder; the folder names don't matter. "
            "Then click Change and choose that folder (or one above it). The same folder is used for compiling "
            "and as the database server.",
            "Don't use MySQL 9.x or 26.x; AzerothCore doesn't support them.",
            "libmysql.dll next to the server must be the same version as the one you compiled with. "
            "After changing MySQL, compile and deploy again.",
        ],
    },
}

# Where the selected AzerothCore source states its minimum versions ("3.16...3.22" -> 3.16).
_MINIMUMS = {
    "cmake": ("CMakeLists.txt", r"cmake_minimum_required\s*\(\s*VERSION\s+(\d+(?:\.\d+)*)"),
    "vs": ("src/cmake/compiler/msvc/settings.cmake", r"set\s*\(\s*MSVC_EXPECTED_VERSION\s+(\d+(?:\.\d+)*)"),
    "openssl": ("deps/openssl/CMakeLists.txt", r"set\s*\(\s*OPENSSL_EXPECTED_VERSION\s+(\d+(?:\.\d+)*)"),
    "mysql": ("src/cmake/macros/FindMySQL.cmake", r"set\s*\(\s*MYSQL_MINIMUM_VERSION\s+\"?(\d+(?:\.\d+)*)"),
}
_BOOST_FILE = "deps/boost/CMakeLists.txt"


def parse_minimums(source: Path) -> dict[str, str]:
    """Minimum versions as written in the source; a key is missing when it can't be read."""
    out: dict[str, str] = {}
    for key, (rel, pattern) in _MINIMUMS.items():
        path = source / rel
        if path.is_file():
            m = re.search(pattern, path.read_text(encoding="utf-8", errors="replace"))
            if m:
                out[key] = m.group(1)
    boost = source / _BOOST_FILE
    if boost.is_file():
        text = boost.read_text(encoding="utf-8", errors="replace")
        # Windows has its own (higher) minimum in an `if (WIN32)` branch; otherwise there is one value.
        m = re.search(r"if\s*\(\s*WIN32\s*\)(?:(?!\belse\b|\bendif\b).)*?set\s*\(\s*BOOST_REQUIRED_VERSION\s+(\d+(?:\.\d+)*)",
                      text, re.S)
        values = set(re.findall(r"set\s*\(\s*BOOST_REQUIRED_VERSION\s+(\d+(?:\.\d+)*)", text))
        if m:
            out["boost"] = m.group(1)
        elif len(values) == 1:
            out["boost"] = values.pop()
    return out


# ---- advice (AzerothCore wiki recommendations; never blocks a build) ------------------------------------

def _major_minor(version: str | None) -> tuple[int, int]:
    nums = [int(x) for x in re.findall(r"\d+", version or "")] + [0, 0]
    return nums[0], nums[1]


def openssl_advice(version: str | None) -> list[dict]:
    major, _ = _major_minor(version)
    if major < 3:
        return [{"tone": "warn", "text": "Use OpenSSL 3.x or newer."}]
    if major > 3:
        return [{"tone": "info", "text": "Recommended is OpenSSL 3.x; this newer version also meets your source's minimum."}]
    return []


def mysql_advice(version: str | None) -> list[dict]:
    major, minor = _major_minor(version)
    if major != 8:
        return [{"tone": "warn", "text": "MySQL 9.x and 26.x are not supported. Use MySQL 8.4 LTS."}]
    if minor != 4:
        return [{"tone": "info", "text": "Recommended is MySQL 8.4 LTS."}]
    return []


def cmake_advice(version: str | None) -> list[dict]:
    if version and "rc" in version.lower():
        return [{"tone": "warn", "text": "This is a release candidate. Use a final release."}]
    return []


def vs_advice(instance: dict) -> list[dict]:
    if instance.get("prerelease"):
        return [{"tone": "warn", "text": "This is a Preview version of Visual Studio. Use a regular release."}]
    if _major_minor(instance.get("version"))[0] > 17:
        return [{"tone": "info", "text": "AzerothCore's guide uses Visual Studio 2022. This newer version also meets its "
                                         "minimum (17); with it, take the Boost installer for msvc-14.5 instead of 14.3."}]
    return []
