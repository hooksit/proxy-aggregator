import asyncio
import time
import tempfile
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
import httpx

from app.core.parser import ProxyConfig
from app.core.singbox import build_singbox_outbound, build_singbox_config, find_free_port, get_singbox_executable
from app.core.speedtest import measure_speed_via_proxy
from app.config import settings
from app.database import get_db_connection, get_setting

async def fast_tcp_check(host: str, port: int, timeout: float = 1.5) -> bool:
    """Quickly check if the host:port is reachable via TCP."""
    try:
        conn = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(conn, timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

async def test_single_proxy(
    cfg: ProxyConfig,
    enable_speedtest: bool = False
) -> Tuple[bool, int, float, float, Optional[str]]:
    """
    Tests a proxy configuration.
    Returns: (is_alive, ping_ms, download_mbps, upload_mbps, error_message)
    """
    singbox_bin = get_singbox_executable()
    
    # 1. Fast pre-check for TCP protocols
    if cfg.protocol in ["vless", "vmess", "shadowsocks", "trojan"]:
        is_port_open = await fast_tcp_check(cfg.server, cfg.port, timeout=2.0)
        if not is_port_open:
            return False, -1, 0.0, 0.0, "Connection refused or timed out on port"

    # 2. If sing-box is not available, return TCP check result as fallback
    if not singbox_bin:
        t0 = time.perf_counter()
        ok = await fast_tcp_check(cfg.server, cfg.port, timeout=settings.TEST_TIMEOUT_SECONDS)
        ping = int((time.perf_counter() - t0) * 1000) if ok else -1
        return ok, ping, 0.0, 0.0, None if ok else "TCP connect failed"

    # 3. Deep check using sing-box
    in_port = find_free_port()
    outbound = build_singbox_outbound(cfg)
    sb_config = build_singbox_config(outbound, in_port)
    
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(sb_config, f)
        config_path = f.name

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            singbox_bin, "run", "-c", config_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        
        # Give sing-box 150ms to bind to the port
        await asyncio.sleep(0.15)
        
        proxy_url = f"socks5://127.0.0.1:{in_port}"
        t0 = time.perf_counter()
        
        async with httpx.AsyncClient(proxy=proxy_url, timeout=settings.TEST_TIMEOUT_SECONDS, verify=False) as client:
            resp = await client.get(settings.PING_TEST_URL)
            if resp.status_code in [200, 204]:
                ping_ms = int((time.perf_counter() - t0) * 1000)
                
                # Run speedtest if enabled
                down_mbps, up_mbps = 0.0, 0.0
                if enable_speedtest:
                    down_mbps, up_mbps = await measure_speed_via_proxy(
                        in_port,
                        max_bytes=settings.SPEEDTEST_MAX_BYTES,
                        timeout_seconds=12.0
                    )
                
                return True, ping_ms, down_mbps, up_mbps, None
            else:
                return False, -1, 0.0, 0.0, f"HTTP status {resp.status_code}"

    except Exception as e:
        return False, -1, 0.0, 0.0, str(e)
    finally:
        if proc:
            try:
                proc.terminate()
                await proc.wait()
            except Exception:
                pass
        if os.path.exists(config_path):
            try:
                os.remove(config_path)
            except Exception:
                pass

check_progress = {
    "is_running": False,
    "current": 0,
    "total": 0,
    "alive": 0,
    "dead": 0,
    "mode": "пинг",
    "percent": 0
}

async def run_full_check_cycle() -> Dict[str, Any]:
    """
    Runs health check for all active and pending configurations in the database.
    Prunes dead configurations if fail_count exceeds threshold.
    """
    global check_progress
    start_time = time.perf_counter()
    speedtest_val = await get_setting("speedtest_enabled", "0")
    enable_speedtest = speedtest_val == "1"
    
    max_retries = int(await get_setting("max_retries_before_purge", "3"))

    async with get_db_connection() as db:
        cursor = await db.execute("SELECT * FROM configs")
        rows = await cursor.fetchall()
        
    if not rows:
        return {"total": 0, "alive": 0, "dead": 0, "purged": 0}

    check_progress["is_running"] = True
    check_progress["total"] = len(rows)
    check_progress["current"] = 0
    check_progress["alive"] = 0
    check_progress["dead"] = 0
    check_progress["mode"] = "замер скорости (50МБ)" if enable_speedtest else "проверка пинга"
    check_progress["percent"] = 0

    sem = asyncio.Semaphore(settings.CONCURRENT_CHECKS_LIMIT)
    
    results = {
        "total": len(rows),
        "alive": 0,
        "dead": 0,
        "purged": 0
    }

    async def check_item(row):
        async with sem:
            from app.core.parser import parse_single_link
            cfg = parse_single_link(row["raw_link"])
            if not cfg:
                res = (row["id"], False, -1, 0.0, 0.0, "Invalid link")
            else:
                is_alive, ping, down_mbps, up_mbps, err = await test_single_proxy(
                    cfg,
                    enable_speedtest=enable_speedtest
                )
                res = (row["id"], is_alive, ping, down_mbps, up_mbps, err)
            
            check_progress["current"] += 1
            if res[1]:
                check_progress["alive"] += 1
            else:
                check_progress["dead"] += 1
            check_progress["percent"] = int((check_progress["current"] / max(1, check_progress["total"])) * 100)
            return res

    try:
        tasks = [check_item(r) for r in rows]
        check_results = await asyncio.gather(*tasks)
    finally:
        check_progress["is_running"] = False

    now_iso = datetime.utcnow().isoformat()


    async with get_db_connection() as db:
        for cid, is_alive, ping, down_mbps, up_mbps, err in check_results:
            if is_alive:
                results["alive"] += 1
                await db.execute("""
                    UPDATE configs
                    SET is_active = 1,
                        ping_ms = ?,
                        download_mbps = CASE WHEN ? > 0 THEN ? ELSE download_mbps END,
                        upload_mbps = CASE WHEN ? > 0 THEN ? ELSE upload_mbps END,
                        fail_count = 0,
                        last_checked_at = ?,
                        last_error = NULL
                    WHERE id = ?
                """, (ping, down_mbps, down_mbps, up_mbps, up_mbps, now_iso, cid))
            else:
                results["dead"] += 1
                # Increment fail count
                cursor = await db.execute("SELECT fail_count FROM configs WHERE id = ?", (cid,))
                r = await cursor.fetchone()
                current_fails = (r["fail_count"] if r else 0) + 1
                
                if current_fails >= max_retries:
                    # Purge permanently
                    await db.execute("DELETE FROM configs WHERE id = ?", (cid,))
                    results["purged"] += 1
                else:
                    await db.execute("""
                        UPDATE configs
                        SET is_active = 0,
                            ping_ms = -1,
                            fail_count = ?,
                            last_checked_at = ?,
                            last_error = ?
                        WHERE id = ?
                    """, (current_fails, now_iso, err, cid))

        # Record check run in settings and metrics_log
        await db.execute(
            "UPDATE system_settings SET value = ? WHERE key = 'last_check_time'",
            (now_iso,)
        )
        duration = round(time.perf_counter() - start_time, 2)
        await db.execute("""
            INSERT INTO metrics_log (action, total_active, total_dead, purged_count, duration_seconds, details)
            VALUES ('check', ?, ?, ?, ?, ?)
        """, (results["alive"], results["dead"], results["purged"], duration, json.dumps(results)))
        
        await db.commit()

    return results
