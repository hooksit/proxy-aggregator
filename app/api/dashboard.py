import asyncio
from fastapi import APIRouter, Depends
from app.auth import require_auth
from app.database import get_db_connection, get_setting
from app.scheduler import get_scheduler_status, safe_parse_job, safe_check_job

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

@router.get("/stats")
async def get_dashboard_stats(user: str = Depends(require_auth)):
    async with get_db_connection() as db:
        # Total counts

        cur = await db.execute("SELECT COUNT(*) as cnt FROM configs")
        total_configs = (await cur.fetchone())["cnt"]
        
        cur = await db.execute("SELECT COUNT(*) as cnt FROM configs WHERE is_active = 1")
        active_configs = (await cur.fetchone())["cnt"]
        
        cur = await db.execute("SELECT COUNT(*) as cnt FROM configs WHERE is_active = 0")
        dead_configs = (await cur.fetchone())["cnt"]
        
        # Protocol breakdown
        cur = await db.execute("SELECT protocol, COUNT(*) as cnt FROM configs WHERE is_active = 1 GROUP BY protocol")
        protocol_counts = {r["protocol"]: r["cnt"] for r in await cur.fetchall()}
        
        # Sources count
        cur = await db.execute("SELECT COUNT(*) as cnt FROM sources WHERE enabled = 1")
        active_sources = (await cur.fetchone())["cnt"]

        # Purged metrics in the last 24h
        cur = await db.execute("""
            SELECT SUM(purged_count) as total_purged, SUM(added_count) as total_added
            FROM metrics_log 
            WHERE created_at >= datetime('now', '-1 day')
        """)
        m_row = await cur.fetchone()
        purged_last_24h = m_row["total_purged"] or 0
        added_last_24h = m_row["total_added"] or 0

        # Recent metrics log
        cur = await db.execute("SELECT * FROM metrics_log ORDER BY id DESC LIMIT 5")
        recent_logs = [dict(r) for r in await cur.fetchall()]

    last_parse = await get_setting("last_parse_time", "")
    last_check = await get_setting("last_check_time", "")
    speedtest_enabled = (await get_setting("speedtest_enabled", "0")) == "1"

    scheduler_status = get_scheduler_status()

    return {
        "user": user,
        "counts": {
            "total": total_configs,
            "active": active_configs,
            "dead": dead_configs,
            "active_sources": active_sources,
            "added_last_24h": added_last_24h,
            "purged_last_24h": purged_last_24h,
            "protocols": protocol_counts
        },
        "timestamps": {
            "last_parse": last_parse,
            "last_check": last_check,
            "next_parse": scheduler_status["parse_next_run"],
            "next_check": scheduler_status["check_next_run"],
        },
        "flags": {
            "speedtest_enabled": speedtest_enabled,
            "is_parsing_now": scheduler_status["is_parsing_now"],
            "is_checking_now": scheduler_status["is_checking_now"]
        },
        "recent_logs": recent_logs
    }

@router.post("/trigger-parse")
async def trigger_parse(user: str = Depends(require_auth)):
    asyncio.create_task(safe_parse_job())
    return {"status": "ok", "message": "Сбор конфигураций запущен в фоне"}

@router.post("/trigger-check")
async def trigger_check(user: str = Depends(require_auth)):
    asyncio.create_task(safe_check_job())
    return {"status": "ok", "message": "Проверка конфигураций запущена в фоне"}
