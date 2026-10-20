"""Read-only views of accounts and characters, plus GM command builders.

Reads go straight to the databases. Every change (kick, ban, mute, ...) is a GM
command on the worldserver console, so the core applies it with its own rules
(online players, caches, logging) instead of the panel editing tables behind its back.
"""
from __future__ import annotations

import re
import time

from ..acconf import ServerConfig
from . import db
from .dbc import area_names

RACES = {1: "Human", 2: "Orc", 3: "Dwarf", 4: "Night Elf", 5: "Undead", 6: "Tauren", 7: "Gnome",
         8: "Troll", 10: "Blood Elf", 11: "Draenei"}
CLASSES = {1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest", 6: "Death Knight",
           7: "Shaman", 8: "Mage", 9: "Warlock", 11: "Druid"}

_CHAR_COLUMNS = ("guid, account, name, race, class, gender, level, money, zone, map, online, "
                 "totaltime, logout_time")


async def counts(cfg: ServerConfig) -> dict:
    row = (await db.query(cfg.char_db, "SELECT SUM(online = 1) AS online, COUNT(*) AS characters FROM characters"))[0]
    accounts = await db.scalar(cfg.login_db, "SELECT COUNT(*) FROM account")
    return {"online": int(row["online"] or 0), "characters": int(row["characters"] or 0), "accounts": int(accounts or 0)}


def _ban_active(row: dict, now: int) -> bool:
    return bool(row) and (row["bandate"] == row["unbandate"] or row["unbandate"] > now)


async def _decorate_characters(cfg: ServerConfig, rows: list[dict]) -> list[dict]:
    if not rows:
        return rows
    zones = area_names(cfg.data_dir)
    account_ids = sorted({r["account"] for r in rows})
    guids = [r["guid"] for r in rows]
    accounts = {a["id"]: a["username"] for a in await db.query(
        cfg.login_db, "SELECT id, username FROM account WHERE id IN %s", (account_ids,))}
    now = int(time.time())
    bans = {b["guid"]: b for b in await db.query(
        cfg.char_db,
        "SELECT guid, bandate, unbandate, banreason FROM character_banned WHERE active = 1 AND guid IN %s",
        (guids,))}
    for r in rows:
        r["account_name"] = accounts.get(r["account"])
        r["race_name"] = RACES.get(r["race"], f"Race {r['race']}")
        r["class_name"] = CLASSES.get(r["class"], f"Class {r['class']}")
        r["zone_name"] = zones.get(r["zone"], f"Zone {r['zone']}")
        ban = bans.get(r["guid"])
        r["banned"] = _ban_active(ban, now) if ban else False
        r["ban_reason"] = ban["banreason"] if r["banned"] else None
    return rows


async def characters(cfg: ServerConfig, search: str, online_only: bool, limit: int, offset: int) -> dict:
    where, params = [], []
    if search:
        where.append("name LIKE %s")
        params.append(f"%{search}%")
    if online_only:
        where.append("online = 1")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = await db.scalar(cfg.char_db, f"SELECT COUNT(*) FROM characters {clause}", params)
    rows = await db.query(
        cfg.char_db,
        f"SELECT {_CHAR_COLUMNS} FROM characters {clause} ORDER BY online DESC, name LIMIT %s OFFSET %s",
        [*params, limit, offset])
    return {"total": int(total or 0), "items": await _decorate_characters(cfg, rows)}


async def accounts(cfg: ServerConfig, search: str, limit: int, offset: int) -> dict:
    clause, params = ("WHERE username LIKE %s", [f"%{search}%"]) if search else ("", [])
    total = await db.scalar(cfg.login_db, f"SELECT COUNT(*) FROM account {clause}", params)
    rows = await db.query(
        cfg.login_db,
        "SELECT id, username, email, joindate, last_ip, last_login, online, expansion, locked, "
        f"mutetime, mutereason, totaltime FROM account {clause} ORDER BY id LIMIT %s OFFSET %s",
        [*params, limit, offset])
    if rows:
        ids = [r["id"] for r in rows]
        gm = {a["id"]: a["gmlevel"] for a in await db.query(
            cfg.login_db,
            "SELECT id, MAX(gmlevel) AS gmlevel FROM account_access "
            "WHERE id IN %s AND (RealmID = -1 OR RealmID = %s) GROUP BY id", (ids, cfg.realm_id))}
        now = int(time.time())
        bans: dict[int, dict] = {}
        for b in await db.query(cfg.login_db,
                                "SELECT id, bandate, unbandate, banreason FROM account_banned "
                                "WHERE active = 1 AND id IN %s", (ids,)):
            if _ban_active(b, now):
                bans[b["id"]] = b
        chars = {c["account"]: c["n"] for c in await db.query(
            cfg.char_db, "SELECT account, COUNT(*) AS n FROM characters WHERE account IN %s GROUP BY account", (ids,))}
        for r in rows:
            r["gmlevel"] = int(gm.get(r["id"], 0))
            r["banned"] = r["id"] in bans
            r["ban_reason"] = bans[r["id"]]["banreason"] if r["banned"] else None
            r["ban_until"] = (None if not r["banned"] or bans[r["id"]]["bandate"] == bans[r["id"]]["unbandate"]
                              else bans[r["id"]]["unbandate"])
            r["muted"] = r["mutetime"] > now
            r["characters"] = int(chars.get(r["id"], 0))
    return {"total": int(total or 0), "items": rows}


# ---- GM command builders ----------------------------------------------------------

_NAME = re.compile(r"^[^\s\"'\\]{1,32}$")
_DURATION = re.compile(r"^(-1|(\d+[dhms])+)$")


class InvalidAction(ValueError):
    pass


def _name(value: str, what: str) -> str:
    value = (value or "").strip()
    if not _NAME.match(value):
        raise InvalidAction(f"Invalid {what} name.")
    return value


def _text(value: str, limit: int = 255) -> str:
    return " ".join((value or "").replace('"', "'").split())[:limit]


def build_command(action: str, p: dict) -> str:
    if action == "kick":
        return f"kick {_name(p.get('name'), 'character')} {_text(p.get('reason', ''))}".strip()
    if action == "ban":
        kind = p.get("type")
        if kind not in ("account", "character"):
            raise InvalidAction("Ban type must be account or character.")
        duration = str(p.get("duration", "")).strip()
        # AzerothCore treats a bare number as 0 seconds = permanent, so a unit is required.
        if not _DURATION.match(duration):
            raise InvalidAction("Duration must look like 30m, 12h, 7d or -1 for permanent.")
        reason = _text(p.get("reason", "")) or "No reason given"
        return f"ban {kind} {_name(p.get('target'), kind)} {duration} {reason}"
    if action == "unban":
        kind = p.get("type")
        if kind not in ("account", "character"):
            raise InvalidAction("Unban type must be account or character.")
        return f"unban {kind} {_name(p.get('target'), kind)}"
    if action == "mute":
        minutes = int(p.get("minutes", 0))
        if minutes <= 0:
            raise InvalidAction("Mute time must be at least 1 minute.")
        # Explicit unit: the core parses the time with TimeStringToSecs ("10m" = 600 s).
        return f"mute {_name(p.get('name'), 'character')} {minutes}m {_text(p.get('reason', ''))}".strip()
    if action == "unmute":
        return f"unmute {_name(p.get('name'), 'character')}"
    if action == "gmlevel":
        level = int(p.get("level", -1))
        if level not in (0, 1, 2, 3):
            raise InvalidAction("GM level must be 0-3.")
        return f"account set gmlevel {_name(p.get('account'), 'account')} {level} -1"
    if action == "level":
        level = int(p.get("level", 0))
        if not 1 <= level <= 255:
            raise InvalidAction("Level must be 1-255.")
        return f"character level {_name(p.get('name'), 'character')} {level}"
    if action == "revive":
        return f"revive {_name(p.get('name'), 'character')}"
    if action == "mail":
        subject, text = _text(p.get("subject", ""), 128), _text(p.get("text", ""), 1000)
        if not subject:
            raise InvalidAction("Subject is required.")
        return f'send mail {_name(p.get("name"), "character")} "{subject}" "{text}"'
    if action == "money":
        copper = int(p.get("copper", 0))
        if copper <= 0:
            raise InvalidAction("Amount must be positive.")
        subject, text = _text(p.get("subject", "") or "Gift", 128), _text(p.get("text", ""), 1000)
        return f'send money {_name(p.get("name"), "character")} "{subject}" "{text}" {copper}'
    if action in ("announce", "notify"):
        message = _text(p.get("message", ""), 255)
        if not message:
            raise InvalidAction("Message is empty.")
        return f"{action} {message}"
    raise InvalidAction(f"Unknown action: {action}")
