import time
import httpx
from typing import Tuple

async def measure_speed_via_proxy(
    proxy_port: int,
    max_bytes: int = 50 * 1024 * 1024,
    timeout_seconds: float = 8.0
) -> Tuple[float, float]:
    """
    Measures download and upload throughput in Mbps through the local proxy.
    Capped at 50MB, but dynamically measures speed within a 4-5 second window
    so slow nodes don't timeout with 0 Mbps.
    """
    proxy_url = f"socks5://127.0.0.1:{proxy_port}"
    download_mbps = 0.0
    upload_mbps = 0.0
    
    down_url = f"https://speed.cloudflare.com/__down?bytes={max_bytes}"
    up_url = "https://speed.cloudflare.com/__up"
    
    # 1. Download Test
    start_time = time.perf_counter()
    total_bytes = 0
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout_seconds, verify=False) as client:
            async with client.stream("GET", down_url) as response:
                if response.status_code == 200:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        total_bytes += len(chunk)
                        dur = time.perf_counter() - start_time
                        if total_bytes >= max_bytes or dur >= 4.0:
                            break
    except Exception:
        pass

    duration_down = time.perf_counter() - start_time
    if duration_down > 0.2 and total_bytes > 50000:
        download_mbps = round((total_bytes * 8) / (duration_down * 1_000_000), 2)

    # 2. Upload Test (stream chunks up to 4 seconds or max_bytes)
    t_up_start = time.perf_counter()
    up_bytes = 0
    try:
        chunk_size = 65536  # 64 KB
        dummy_chunk = b"0" * chunk_size

        async def dummy_generator():
            nonlocal up_bytes
            while up_bytes < max_bytes:
                if (time.perf_counter() - t_up_start) >= 3.5:
                    break
                up_bytes += len(dummy_chunk)
                yield dummy_chunk

        async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout_seconds, verify=False) as client:
            headers = {"Content-Type": "application/octet-stream"}
            await client.post(up_url, content=dummy_generator(), headers=headers)
    except Exception:
        pass

    duration_up = time.perf_counter() - t_up_start
    if duration_up > 0.2 and up_bytes > 50000:
        upload_mbps = round((up_bytes * 8) / (duration_up * 1_000_000), 2)

    return download_mbps, upload_mbps
