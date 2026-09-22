import time
import httpx
from typing import Tuple

async def measure_speed_via_proxy(
    proxy_port: int,
    max_bytes: int = 50 * 1024 * 1024,
    timeout_seconds: float = 12.0
) -> Tuple[float, float]:
    """
    Measures download and upload throughput in Mbps through the local proxy.
    Returns (download_mbps, upload_mbps).
    Uses Cloudflare Speed CDN endpoint with a strict timeout to avoid hangs.
    """
    proxy_url = f"socks5://127.0.0.1:{proxy_port}"
    download_mbps = 0.0
    upload_mbps = 0.0
    
    down_url = f"https://speed.cloudflare.com/__down?bytes={max_bytes}"
    up_url = "https://speed.cloudflare.com/__up"
    
    async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout_seconds, verify=False) as client:
        # 1. Download Test
        try:
            start_time = time.perf_counter()
            total_bytes = 0
            
            async with client.stream("GET", down_url) as response:
                if response.status_code == 200:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        total_bytes += len(chunk)
                        # Cap at max_bytes
                        if total_bytes >= max_bytes:
                            break
                            
            duration = time.perf_counter() - start_time
            if duration > 0.1 and total_bytes > 0:
                download_mbps = round((total_bytes * 8) / (duration * 1_000_000), 2)
        except Exception:
            # If download failed or timed out partially
            pass

        # 2. Upload Test (stream up to 50MB)
        try:
            # Generate a 1MB dummy chunk and stream it up to 50 times
            chunk_size = 512 * 1024  # 512 KB
            dummy_chunk = b"0" * chunk_size
            num_chunks = max_bytes // chunk_size

            async def dummy_generator():
                for _ in range(num_chunks):
                    yield dummy_chunk

            start_time = time.perf_counter()
            headers = {"Content-Type": "application/octet-stream"}
            response = await client.post(up_url, content=dummy_generator(), headers=headers)
            
            duration = time.perf_counter() - start_time
            if response.status_code in [200, 204] and duration > 0.1:
                upload_mbps = round((max_bytes * 8) / (duration * 1_000_000), 2)
        except Exception:
            # Upload failed
            pass

    return download_mbps, upload_mbps
