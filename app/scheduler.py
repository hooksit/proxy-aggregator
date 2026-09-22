import asyncio
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import get_setting
from app.core.scraper import run_full_parse_cycle
from app.core.tester import run_full_check_cycle

scheduler = AsyncIOScheduler()

PARSE_JOB_ID = "periodic_parse_job"
CHECK_JOB_ID = "periodic_check_job"

is_parsing_now = False
is_checking_now = False

async def safe_parse_job():
    global is_parsing_now
    if is_parsing_now:
        return
    is_parsing_now = True
    try:
        await run_full_parse_cycle()
        # Trigger an immediate check on newly parsed items
        await run_full_check_cycle()
    finally:
        is_parsing_now = False

async def safe_check_job():
    global is_checking_now
    if is_checking_now:
        return
    is_checking_now = True
    try:
        await run_full_check_cycle()
    finally:
        is_checking_now = False

async def init_scheduler():
    # Read intervals from database
    parse_hours = int(await get_setting("parse_interval_hours", "12"))
    check_minutes = int(await get_setting("check_interval_minutes", "5"))

    if not scheduler.get_job(PARSE_JOB_ID):
        scheduler.add_job(
            safe_parse_job,
            trigger=IntervalTrigger(hours=max(1, parse_hours)),
            id=PARSE_JOB_ID,
            name="Scrape all sources",
            replace_existing=True
        )

    if not scheduler.get_job(CHECK_JOB_ID):
        scheduler.add_job(
            safe_check_job,
            trigger=IntervalTrigger(minutes=max(1, check_minutes)),
            id=CHECK_JOB_ID,
            name="Check proxies health & ping",
            replace_existing=True
        )

    if not scheduler.running:
        scheduler.start()

def reschedule_parse_job(hours: int):
    hours = max(1, hours)
    if scheduler.get_job(PARSE_JOB_ID):
        scheduler.reschedule_job(PARSE_JOB_ID, trigger=IntervalTrigger(hours=hours))

def reschedule_check_job(minutes: int):
    minutes = max(1, minutes)
    if scheduler.get_job(CHECK_JOB_ID):
        scheduler.reschedule_job(CHECK_JOB_ID, trigger=IntervalTrigger(minutes=minutes))

def get_scheduler_status():
    parse_job = scheduler.get_job(PARSE_JOB_ID)
    check_job = scheduler.get_job(CHECK_JOB_ID)
    
    return {
        "is_running": scheduler.running,
        "is_parsing_now": is_parsing_now,
        "is_checking_now": is_checking_now,
        "parse_next_run": parse_job.next_run_time.isoformat() if parse_job and parse_job.next_run_time else None,
        "check_next_run": check_job.next_run_time.isoformat() if check_job and check_job.next_run_time else None,
    }
