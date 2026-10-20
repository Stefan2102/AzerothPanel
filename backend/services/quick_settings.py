"""Config Files -> Quick settings: common worldserver.conf values as a form.

The panel defines which keys appear and their control (toggle, choice, number). The rest comes from
AzerothCore's files: the current value from worldserver.conf, the default from worldserver.conf.dist,
and the description from the comment block above the key. Saving changes only the value of the key's
own line (conffile.set_raw); comments and the .dist template stay as they are.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..acconf import parse_conf
from . import conffile

ON_OFF = "toggle"

# (group, [(key, label, kind, options or (min, max))]). Options are AzerothCore's documented values.
GROUPS: list[tuple[str, list[tuple]]] = [
    ("Realm", [
        ("GameType", "Realm type", "select",
         [("0", "Normal"), ("1", "PvP"), ("4", "Normal"), ("6", "RP"), ("8", "RP-PvP"), ("16", "Free-for-all PvP")]),
        ("RealmZone", "Realm zone", "select",
         [("1", "Development"), ("2", "United States"), ("3", "Oceanic"), ("4", "Latin America"), ("6", "Korea"),
          ("8", "English"), ("9", "German"), ("10", "French"), ("11", "Spanish"), ("12", "Russian"),
          ("14", "Taiwan"), ("16", "China"), ("26", "Test Server"), ("28", "QA Server")]),
        ("PlayerLimit", "Player limit", "int", (0, 100000)),
    ]),
    ("Characters", [
        ("MaxPlayerLevel", "Max level", "int", (1, 255)),
        ("StartPlayerLevel", "Start level", "int", (1, 255)),
        ("StartHeroicPlayerLevel", "Death Knight start level", "int", (1, 255)),
        ("StartPlayerMoney", "Start money (copper)", "int", (0, 2147483647)),
        ("MaxPrimaryTradeSkill", "Primary professions", "int", (0, 11)),
        ("SkipCinematics", "Intro cinematic", "select",
         [("0", "Every new character"), ("1", "First of each race"), ("2", "Never")]),
        ("EnablePlayerSettings", "Character settings", ON_OFF, None),
        ("AllowTwoSide.Accounts", "Both factions on one account", ON_OFF, None),
    ]),
    ("Rates", [
        ("Rate.XP.Kill", "XP from kills", "rate", None),
        ("Rate.XP.Quest", "XP from quests", "rate", None),
        ("Rate.XP.Explore", "XP from exploring", "rate", None),
        ("Rate.Rest.InGame", "Rested XP", "rate", None),
        ("Rate.Reputation.Gain", "Reputation", "rate", None),
        ("Rate.Honor", "Honor", "rate", None),
        ("Rate.Talent", "Talent points", "rate", None),
        ("Rate.Drop.Money", "Money drops", "rate", None),
    ]),
    ("Item drops", [
        ("Rate.Drop.Item.Normal", "Common", "rate", None),
        ("Rate.Drop.Item.Uncommon", "Uncommon", "rate", None),
        ("Rate.Drop.Item.Rare", "Rare", "rate", None),
        ("Rate.Drop.Item.Epic", "Epic", "rate", None),
        ("Rate.Drop.Item.Legendary", "Legendary", "rate", None),
    ]),
    ("Cross-faction", [
        ("AllowTwoSide.Interaction.Chat", "Chat", ON_OFF, None),
        ("AllowTwoSide.Interaction.Group", "Groups", ON_OFF, None),
        ("AllowTwoSide.Interaction.Guild", "Guilds", ON_OFF, None),
        ("AllowTwoSide.Interaction.Auction", "Auction house", ON_OFF, None),
    ]),
    ("Instances", [
        ("Instance.IgnoreLevel", "Ignore level requirement", ON_OFF, None),
        ("Instance.IgnoreRaid", "Enter raids without a raid group", ON_OFF, None),
    ]),
    ("Performance & data", [
        ("MapUpdate.Threads", "Map update threads", "int", (1, 64)),
        ("DBC.EnforceItemAttributes", "Item stats from DBC files", ON_OFF, None),
    ]),
]
_KINDS = {key: (kind, extra) for _, items in GROUPS for key, _, kind, extra in items}
_FIELD = re.compile(r"^#\s+([A-Z][A-Za-z ]*):\s*(.*)$")


def describe(text: str, key: str) -> str:
    """The "Description:" of the comment block that documents key ("" if there is none)."""
    lines = text.splitlines()
    at = next((i for i, line in enumerate(lines) if re.match(rf"^\s*{re.escape(key)}\s*=", line)), None)
    if at is None:
        return ""
    i = at - 1
    while i >= 0 and not lines[i].startswith("#"):    # blank lines, and keys sharing one block (rates)
        i -= 1
    block: list[str] = []
    while i >= 0 and lines[i].startswith("#") and lines[i].strip() != "#":
        block.insert(0, lines[i])
        i -= 1
    if not any(re.fullmatch(rf"#\s+{re.escape(key)}\s*", line) for line in block):
        return ""                                       # that block documents another key
    out, inside = [], False
    for line in block:
        m = _FIELD.match(line)
        if m:
            inside = m.group(1) == "Description"
            if inside:
                out.append(m.group(2))
        elif inside:
            out.append(line.lstrip("#").strip())
    return " ".join(p for p in out if p)


def state(server: Path) -> dict:
    conf = server / "configs" / "worldserver.conf"
    if not conf.is_file():
        return {"file": str(conf), "found": False, "groups": []}
    text = conf.read_text(encoding="utf-8", errors="replace")
    values = parse_conf(text)
    dist = conf.with_name("worldserver.conf.dist")
    defaults = parse_conf(dist.read_text(encoding="utf-8", errors="replace")) if dist.is_file() else {}
    groups = []
    for title, items in GROUPS:
        rows = []
        for key, label, kind, extra in items:
            if key not in values:
                continue                                  # not in this AzerothCore version
            row = {"key": key, "label": label, "kind": kind, "value": values[key],
                   "default": defaults.get(key), "description": describe(text, key)}
            if kind == "select":
                row["options"] = [{"value": v, "label": lbl} for v, lbl in extra]
            elif kind == "int":
                row["min"], row["max"] = extra
            rows.append(row)
        if rows:
            groups.append({"title": title, "items": rows})
    return {"file": str(conf), "found": True, "groups": groups}


def check(key: str, value: str) -> str:
    """The value as it will be written, or ValueError with a message."""
    if key not in _KINDS:
        raise ValueError(f"{key} is not a quick setting.")
    kind, extra = _KINDS[key]
    value = value.strip()
    if kind == ON_OFF and value not in ("0", "1"):
        raise ValueError(f"{key} must be 0 or 1.")
    if kind == "select" and value not in {v for v, _ in extra}:
        raise ValueError(f"{key}: {value} is not one of its values.")
    if kind == "int":
        if not re.fullmatch(r"\d+", value) or not extra[0] <= int(value) <= extra[1]:
            raise ValueError(f"{key} must be a whole number from {extra[0]} to {extra[1]}.")
    if kind == "rate":
        if not re.fullmatch(r"\d+(\.\d+)?", value) or float(value) > 1000:
            raise ValueError(f"{key} must be a number from 0 to 1000 (e.g. 1 or 2.5).")
    return value


def save(server: Path, values: dict[str, str]) -> list[str]:
    conf = server / "configs" / "worldserver.conf"
    checked = {k: check(k, v) for k, v in values.items()}
    return conffile.set_raw(conf, checked)
