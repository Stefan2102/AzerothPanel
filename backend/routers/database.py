from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .. import security
from ..acconf import DbInfo, ServerConfig
from ..deps import get_config
from ..services import audit, db
from ..services.sqlguard import QueryRejected, check_readonly

router = APIRouter(prefix="/api/db", tags=["database"], dependencies=[Depends(security.require_session)])


class QueryBody(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)


def _db(cfg: ServerConfig, key: str) -> DbInfo:
    info = cfg.databases.get(key)
    if info is None:
        raise HTTPException(status_code=404, detail="Unknown database.")
    return info


async def _tables(info: DbInfo) -> list[dict]:
    return await db.query(
        info,
        "SELECT TABLE_NAME AS name, TABLE_ROWS AS row_estimate, DATA_LENGTH + INDEX_LENGTH AS size "
        "FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME", (info.database,))


@router.get("")
def databases(cfg: ServerConfig = Depends(get_config)):
    return [{"key": k, **v.public()} for k, v in cfg.databases.items()]


@router.get("/{key}/tables")
async def tables(key: str, cfg: ServerConfig = Depends(get_config)):
    return await _tables(_db(cfg, key))


@router.get("/{key}/tables/{table}")
async def table_rows(key: str, table: str, page: int = Query(0, ge=0), size: int = Query(100, ge=1, le=500),
                     cfg: ServerConfig = Depends(get_config)):
    info = _db(cfg, key)
    # The table name is only ever used after matching it against the live table list.
    if table not in {t["name"] for t in await _tables(info)}:
        raise HTTPException(status_code=404, detail="Unknown table.")
    columns = await db.query(
        info,
        "SELECT COLUMN_NAME AS name, COLUMN_TYPE AS type, COLUMN_KEY AS `key`, IS_NULLABLE AS nullable, "
        "COLUMN_DEFAULT AS `default`, COLUMN_COMMENT AS comment FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION", (info.database, table))
    result = await db.run_readonly(
        info, f"SELECT * FROM {db.quote_ident(table)} LIMIT {size} OFFSET {page * size}", max_rows=size)
    total = await db.scalar(info, f"SELECT COUNT(*) FROM {db.quote_ident(table)}")
    return {"columns": columns, "rows": result["rows"], "total": int(total or 0), "page": page, "size": size}


@router.post("/{key}/query")
async def run_query(key: str, body: QueryBody, request: Request, cfg: ServerConfig = Depends(get_config)):
    info = _db(cfg, key)
    try:
        sql = check_readonly(body.sql)
    except QueryRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record(request, "db.query", f"{info.database}: {sql}")
    return await db.run_readonly(info, sql)
