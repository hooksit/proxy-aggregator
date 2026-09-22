import time
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, List
import json

from app.core.parser import fetch_source_content, extract_configs_from_text, parse_single_link
from app.database import get_db_connection

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

async def scrape_single_source(source_id: int, url: str) -> Dict[str, Any]:
    stats = {"found": 0, "added": 0, "status": "ok", "error": None}
    try:
        content = await fetch_source_content(url)
        configs = extract_configs_from_text(content)
        stats["found"] = len(configs)
        
        now_iso = datetime.now(MOSCOW_TZ).isoformat()
        async with get_db_connection() as db:
            added = 0
            for cfg in configs:
                cursor = await db.execute("""
                    INSERT OR IGNORE INTO configs 
                    (hash, protocol, server, port, name, raw_link, is_active, source_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """, (
                    cfg.hash, cfg.protocol, cfg.server, cfg.port, 
                    cfg.name, cfg.raw_link, source_id, now_iso
                ))
                if cursor.rowcount > 0:
                    added += 1
            
            stats["added"] = added
            await db.execute("""
                UPDATE sources 
                SET last_scraped_at = ?,
                    last_status = 'success',
                    configs_found = ?
                WHERE id = ?
            """, (now_iso, len(configs), source_id))
            await db.commit()

    except Exception as e:
        stats["status"] = "error"
        stats["error"] = str(e)
        now_iso = datetime.now(MOSCOW_TZ).isoformat()
        async with get_db_connection() as db:
            await db.execute("""
                UPDATE sources 
                SET last_scraped_at = ?,
                    last_status = ?
                WHERE id = ?
            """, (now_iso, f"error: {str(e)[:60]}", source_id))
            await db.commit()
            
    return stats

async def run_full_parse_cycle() -> Dict[str, Any]:
    start_time = time.perf_counter()
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT id, name, url FROM sources WHERE enabled = 1")
        sources = await cursor.fetchall()
        
    summary = {
        "sources_scraped": len(sources),
        "total_found": 0,
        "new_added": 0,
        "errors": 0
    }
    
    for s in sources:
        res = await scrape_single_source(s["id"], s["url"])
        summary["total_found"] += res["found"]
        summary["new_added"] += res["added"]
        if res["status"] != "ok":
            summary["errors"] += 1

    now_iso = datetime.now(MOSCOW_TZ).isoformat()
    duration = round(time.perf_counter() - start_time, 2)

    async with get_db_connection() as db:
        await db.execute(
            "UPDATE system_settings SET value = ? WHERE key = 'last_parse_time'",
            (now_iso,)
        )
        await db.execute("""
            INSERT INTO metrics_log (action, added_count, duration_seconds, details)
            VALUES ('parse', ?, ?, ?)
        """, (summary["new_added"], duration, json.dumps(summary)))
        await db.commit()

    return summary

async def add_manual_configs(raw_text: str, save_as_source: bool = False) -> Dict[str, Any]:
    """
    Parse and add configurations. 
    Supports:
    1. Direct proxy links (vless://, vmess://, etc.)
    2. Base64 subscriptions
    3. URLs to subscriptions or channels (http://, https://, t.me/...) with auto-fetch!
    """
    configs = []
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    sources_saved = 0
    non_url_text = []

    for line in lines:
        if line.startswith("http://") or line.startswith("https://") or line.startswith("t.me/"):
            try:
                # Fetch remote content
                content = await fetch_source_content(line)
                fetched = extract_configs_from_text(content)
                configs.extend(fetched)

                # Optionally save URL to persistent sources for 12h auto-scrape
                if save_as_source:
                    async with get_db_connection() as db:
                        try:
                            s_name = f"Подписка {line[:30]}..."
                            s_type = "telegram" if "t.me" in line else "sub"
                            await db.execute(
                                "INSERT OR IGNORE INTO sources (name, url, source_type) VALUES (?, ?, ?)",
                                (s_name, line, s_type)
                            )
                            await db.commit()
                            sources_saved += 1
                        except Exception:
                            pass
            except Exception as e:
                pass
        else:
            non_url_text.append(line)

    if non_url_text:
        combined = "\n".join(non_url_text)
        direct_configs = extract_configs_from_text(combined)
        if not direct_configs:
            for l in non_url_text:
                c = parse_single_link(l)
                if c:
                    direct_configs.append(c)
        configs.extend(direct_configs)

    # De-duplicate configs in this batch
    unique_configs = {}
    for c in configs:
        unique_configs[c.hash] = c

    added = 0
    now_iso = datetime.utcnow().isoformat()
    async with get_db_connection() as db:
        for cfg in unique_configs.values():
            cursor = await db.execute("""
                INSERT OR IGNORE INTO configs 
                (hash, protocol, server, port, name, raw_link, is_active, source_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, NULL, ?)
            """, (
                cfg.hash, cfg.protocol, cfg.server, cfg.port, 
                cfg.name, cfg.raw_link, now_iso
            ))
            if cursor.rowcount > 0:
                added += 1
        await db.commit()

    return {
        "total_parsed": len(unique_configs),
        "new_added": added,
        "sources_saved": sources_saved
    }

