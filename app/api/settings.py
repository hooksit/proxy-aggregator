from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional

from app.auth import require_auth
from app.database import get_db_connection, get_setting, set_setting
from app.scheduler import reschedule_parse_job, reschedule_check_job

router = APIRouter(prefix="/api/settings", tags=["settings"])

class UpdateSettingsRequest(BaseModel):
    parse_interval_hours: Optional[int] = None
    check_interval_minutes: Optional[int] = None
    speedtest_enabled: Optional[bool] = None
    max_retries_before_purge: Optional[int] = None

@router.get("")
async def get_all_settings(user: str = Depends(require_auth)):
    async with get_db_connection() as db:
        cur = await db.execute("SELECT key, value, description FROM system_settings")

        settings_dict = {r["key"]: r["value"] for r in await cur.fetchall()}

    return {
        "parse_interval_hours": int(settings_dict.get("parse_interval_hours", "12")),
        "check_interval_minutes": int(settings_dict.get("check_interval_minutes", "5")),
        "speedtest_enabled": settings_dict.get("speedtest_enabled", "0") == "1",
        "max_retries_before_purge": int(settings_dict.get("max_retries_before_purge", "3")),
        "last_parse_time": settings_dict.get("last_parse_time", ""),
        "last_check_time": settings_dict.get("last_check_time", "")
    }

@router.post("")
async def update_settings(req: UpdateSettingsRequest, user: str = Depends(require_auth)):
    if req.parse_interval_hours is not None:
        val = max(1, req.parse_interval_hours)
        await set_setting("parse_interval_hours", str(val))
        reschedule_parse_job(val)

    if req.check_interval_minutes is not None:
        val = max(1, req.check_interval_minutes)
        await set_setting("check_interval_minutes", str(val))
        reschedule_check_job(val)

    if req.speedtest_enabled is not None:
        val_str = "1" if req.speedtest_enabled else "0"
        await set_setting("speedtest_enabled", val_str)

    if req.max_retries_before_purge is not None:
        val = max(1, req.max_retries_before_purge)
        await set_setting("max_retries_before_purge", str(val))

    return {"status": "ok", "message": "Настройки успешно сохранены"}

@router.post("/speedtest-toggle")
async def toggle_speedtest(user: str = Depends(require_auth)):
    current = await get_setting("speedtest_enabled", "0")
    new_val = "0" if current == "1" else "1"
    await set_setting("speedtest_enabled", new_val)
    return {"status": "ok", "speedtest_enabled": new_val == "1"}

@router.post("/reset-traffic")
async def reset_traffic(user: str = Depends(require_auth)):
    await set_setting("total_traffic_down_bytes", "0")
    await set_setting("total_traffic_up_bytes", "0")
    return {"status": "ok", "message": "Счетчик трафика сброшен"}
