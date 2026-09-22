import base64
from typing import Optional
from fastapi import APIRouter, Query, Response
from app.database import get_db_connection

router = APIRouter(prefix="/sub", tags=["subscription"])

@router.get("/raw")
async def get_raw_subscription(
    protocol: Optional[str] = Query(None, description="Comma-separated protocols e.g. vless,hy2,vmess"),
    max_ping: Optional[int] = Query(None, description="Maximum allowed ping in ms"),
    sort: str = Query("ping", description="ping or speed"),
    limit: int = Query(100, le=1000)
):
    query_parts = ["SELECT raw_link FROM configs WHERE is_active = 1 AND ping_ms > 0"]
    params = []

    if protocol:
        protocols = [p.strip().lower() for p in protocol.split(",") if p.strip()]
        placeholders = ",".join("?" for _ in protocols)
        query_parts.append(f"AND protocol IN ({placeholders})")
        params.extend(protocols)

    if max_ping:
        query_parts.append("AND ping_ms <= ?")
        params.append(max_ping)

    if sort == "speed":
        query_parts.append("ORDER BY download_mbps DESC, ping_ms ASC")
    else:
        query_parts.append("ORDER BY ping_ms ASC")

    query_parts.append("LIMIT ?")
    params.append(limit)

    async with get_db_connection() as db:
        cur = await db.execute(" ".join(query_parts), tuple(params))
        rows = await cur.fetchall()


    content = "\n".join(r["raw_link"] for r in rows)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Subscription-Userinfo": f"upload=0; download=0; total={len(rows)}",
            "Profile-Update-Interval": "1"
        }
    )

@router.get("/base64")
async def get_base64_subscription(
    protocol: Optional[str] = Query(None),
    max_ping: Optional[int] = Query(None),
    sort: str = Query("ping"),
    limit: int = Query(100, le=1000)
):
    # Fetch raw
    resp = await get_raw_subscription(protocol=protocol, max_ping=max_ping, sort=sort, limit=limit)
    encoded = base64.b64encode(resp.body).decode("utf-8")
    
    return Response(
        content=encoded,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": "inline; filename=\"subscription.txt\"",
            "Profile-Update-Interval": "1"
        }
    )
