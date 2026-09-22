import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import require_auth
from app.database import get_db_connection, get_setting
from app.core.scraper import add_manual_configs
from app.core.parser import parse_single_link
from app.core.tester import test_single_proxy

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

router = APIRouter(prefix="/api/configs", tags=["configs"])

class ManualAddRequest(BaseModel):
    content: str
    save_as_source: Optional[bool] = False


@router.get("")
async def get_configs(
    status: str = Query("active", description="active, dead, all"),
    protocol: str = Query("all", description="vless, vmess, shadowsocks, hysteria2, trojan, all"),
    sort_by: str = Query("ping", description="ping, speed, traffic, date"),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user: str = Depends(require_auth)
):
    query_parts = ["SELECT * FROM configs WHERE 1=1"]
    params = []

    if status == "active":
        query_parts.append("AND is_active = 1")
    elif status == "dead":
        query_parts.append("AND is_active = 0")

    if protocol != "all":
        query_parts.append("AND protocol = ?")
        params.append(protocol.lower())

    if search:
        query_parts.append("AND (name LIKE ? OR server LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if sort_by == "speed":
        query_parts.append("ORDER BY download_mbps DESC, ping_ms ASC")
    elif sort_by == "traffic":
        query_parts.append("ORDER BY (traffic_down_bytes + traffic_up_bytes) DESC, ping_ms ASC")
    elif sort_by == "date":
        query_parts.append("ORDER BY id DESC")
    else:
        # Default: ping ASC (putting positive pings first)
        query_parts.append("ORDER BY CASE WHEN ping_ms > 0 THEN ping_ms ELSE 999999 END ASC, id DESC")

    query_parts.append("LIMIT ? OFFSET ?")
    params.extend([limit, offset])

    async with get_db_connection() as db:
        cur = await db.execute(" ".join(query_parts), tuple(params))
        items = [dict(r) for r in await cur.fetchall()]

        # Get total matching count
        count_query = "SELECT COUNT(*) as cnt FROM configs WHERE 1=1"
        count_params = []
        if status == "active":
            count_query += " AND is_active = 1"
        elif status == "dead":
            count_query += " AND is_active = 0"
        if protocol != "all":
            count_query += " AND protocol = ?"
            count_params.append(protocol.lower())
        if search:
            count_query += " AND (name LIKE ? OR server LIKE ?)"
            count_params.extend([f"%{search}%", f"%{search}%"])

        cur_count = await db.execute(count_query, tuple(count_params))
        total = (await cur_count.fetchone())["cnt"]

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@router.post("/manual")
async def add_manual(req: ManualAddRequest, user: str = Depends(require_auth)):
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="Текст пуст")
    
    result = await add_manual_configs(req.content, save_as_source=req.save_as_source or False)
    msg = f"Распознано: {result['total_parsed']}, добавлено новых: {result['new_added']}"
    if result.get("sources_saved"):
        msg += f" (сохранено в источники: {result['sources_saved']})"
        
    return {
        "status": "ok",
        "message": msg
    }


@router.delete("/dead")
async def clear_dead_configs(user: str = Depends(require_auth)):
    async with get_db_connection() as db:
        cur = await db.execute("DELETE FROM configs WHERE is_active = 0")
        deleted = cur.rowcount
        await db.commit()
    return {"status": "ok", "deleted": deleted}

@router.delete("/{config_id}")
async def delete_config(config_id: int, user: str = Depends(require_auth)):
    async with get_db_connection() as db:
        await db.execute("DELETE FROM configs WHERE id = ?", (config_id,))
        await db.commit()
    return {"status": "ok"}

@router.post("/{config_id}/check")
async def check_single_config(config_id: int, user: str = Depends(require_auth)):
    async with get_db_connection() as db:
        cur = await db.execute("SELECT * FROM configs WHERE id = ?", (config_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Конфигурация не найдена")

    cfg = parse_single_link(row["raw_link"])
    if not cfg:
        raise HTTPException(status_code=400, detail="Ошибка разбора ссылки")

    speedtest_val = await get_setting("speedtest_enabled", "0")
    enable_speedtest = speedtest_val == "1"

    is_alive, ping, down, up, down_b, up_b, err = await test_single_proxy(cfg, enable_speedtest=enable_speedtest)

    now_iso = datetime.now(MOSCOW_TZ).isoformat()
    async with get_db_connection() as db:
        if is_alive:
            await db.execute("""
                UPDATE configs 
                SET is_active = 1, ping_ms = ?, download_mbps = ?, upload_mbps = ?, 
                    traffic_down_bytes = CASE WHEN ? > 0 THEN ? ELSE traffic_down_bytes END,
                    traffic_up_bytes = CASE WHEN ? > 0 THEN ? ELSE traffic_up_bytes END,
                    fail_count = 0, last_checked_at = ?, last_error = NULL
                WHERE id = ?
            """, (ping, down, up, down_b, down_b, up_b, up_b, now_iso, config_id))
        else:
            await db.execute("""
                UPDATE configs 
                SET is_active = 0, ping_ms = -1, 
                    traffic_down_bytes = CASE WHEN ? > 0 THEN ? ELSE traffic_down_bytes END,
                    traffic_up_bytes = CASE WHEN ? > 0 THEN ? ELSE traffic_up_bytes END,
                    fail_count = fail_count + 1, 
                    last_checked_at = ?, last_error = ?
                WHERE id = ?
            """, (down_b, down_b, up_b, up_b, now_iso, err, config_id))

        # Update cumulative traffic settings
        cur_down_val = await get_setting("total_traffic_down_bytes", "0")
        cur_up_val = await get_setting("total_traffic_up_bytes", "0")
        new_down = (int(cur_down_val) if cur_down_val.isdigit() else 0) + down_b
        new_up = (int(cur_up_val) if cur_up_val.isdigit() else 0) + up_b
        await db.execute("INSERT INTO system_settings (key, value) VALUES ('total_traffic_down_bytes', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(new_down),))
        await db.execute("INSERT INTO system_settings (key, value) VALUES ('total_traffic_up_bytes', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(new_up),))

        # Insert single check into metrics_log if traffic > 0
        if down_b > 0 or up_b > 0:
            await db.execute("""
                INSERT INTO metrics_log (action, total_active, total_dead, duration_seconds, traffic_down_bytes, traffic_up_bytes, details)
                VALUES ('single_check', ?, ?, 0.0, ?, ?, ?)
            """, (1 if is_alive else 0, 0 if is_alive else 1, down_b, up_b, f'{{"config_id": {config_id}}}'))

        await db.commit()

    return {
        "status": "ok",
        "is_alive": is_alive,
        "ping_ms": ping,
        "download_mbps": down,
        "upload_mbps": up,
        "traffic_down_bytes": down_b,
        "traffic_up_bytes": up_b,
        "error": err
    }
