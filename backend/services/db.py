"""MySQL access with the credentials from worldserver.conf (PyMySQL, run in a worker thread)."""
from __future__ import annotations

import asyncio
import datetime as dt
import decimal
from typing import Any

import pymysql
import pymysql.cursors

from ..acconf import DbInfo


class DbError(Exception):
    pass


def connect(info: DbInfo) -> pymysql.connections.Connection:
    try:
        return pymysql.connect(
            host=info.host, port=info.port, user=info.user, password=info.password,
            database=info.database, charset="utf8mb4", connect_timeout=3, read_timeout=60,
            write_timeout=60, cursorclass=pymysql.cursors.DictCursor, autocommit=True,
        )
    except pymysql.MySQLError as exc:
        raise DbError(f"Cannot connect to {info.database} on {info.host}:{info.port}: {exc.args[-1]}") from exc


def jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return "0x" + bytes(value[:64]).hex() + ("…" if len(value) > 64 else "")
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    return value


def _run(info: DbInfo, sql: str, params: Any = None) -> list[dict]:
    conn = connect(info)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [{k: jsonable(v) for k, v in row.items()} for row in cur.fetchall()]
    except pymysql.MySQLError as exc:
        raise DbError(str(exc.args[-1])) from exc
    finally:
        conn.close()


async def query(info: DbInfo, sql: str, params: Any = None) -> list[dict]:
    return await asyncio.to_thread(_run, info, sql, params)


async def scalar(info: DbInfo, sql: str, params: Any = None) -> Any:
    rows = await query(info, sql, params)
    return next(iter(rows[0].values())) if rows else None


def quote_ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def _run_readonly(info: DbInfo, sql: str, max_rows: int, timeout_ms: int) -> dict:
    """Run a user query inside a READ ONLY transaction (the server rejects any write)."""
    conn = connect(info)
    try:
        with conn.cursor(pymysql.cursors.Cursor) as cur:
            cur.execute("SET SESSION max_execution_time = %s", (timeout_ms,))
            cur.execute("START TRANSACTION READ ONLY")
            started = dt.datetime.now()
            cur.execute(sql)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(max_rows + 1) if columns else []
            elapsed = (dt.datetime.now() - started).total_seconds() * 1000
            cur.execute("ROLLBACK")
        truncated = len(rows) > max_rows
        return {
            "columns": columns,
            "rows": [[jsonable(v) for v in row] for row in rows[:max_rows]],
            "truncated": truncated,
            "elapsed_ms": round(elapsed, 1),
        }
    except pymysql.MySQLError as exc:
        raise DbError(str(exc.args[-1])) from exc
    finally:
        conn.close()


async def run_readonly(info: DbInfo, sql: str, max_rows: int = 1000, timeout_ms: int = 15000) -> dict:
    return await asyncio.to_thread(_run_readonly, info, sql, max_rows, timeout_ms)
