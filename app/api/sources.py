from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.auth import require_auth
from app.database import get_db_connection
from app.core.scraper import scrape_single_source

router = APIRouter(prefix="/api/sources", tags=["sources"])

class AddSourceRequest(BaseModel):
    name: str
    url: str
    source_type: Optional[str] = "sub"

@router.get("")
async def get_sources(user: str = Depends(require_auth)):
    async with get_db_connection() as db:
        cur = await db.execute("SELECT * FROM sources ORDER BY id DESC")
        sources = [dict(r) for r in await cur.fetchall()]
    return {"sources": sources}

@router.post("")
async def add_source(req: AddSourceRequest, user: str = Depends(require_auth)):
    url = req.url.strip()
    if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("t.me/"):
        raise HTTPException(status_code=400, detail="Ссылка должна начинаться с http://, https:// или t.me/")

    s_type = req.source_type
    if "t.me" in url:
        s_type = "telegram"
    elif "github.com" in url or "raw.githubusercontent.com" in url:
        s_type = "github"

    async with get_db_connection() as db:
        try:
            cur = await db.execute(
                "INSERT INTO sources (name, url, source_type) VALUES (?, ?, ?)",
                (req.name.strip(), url, s_type)
            )
            source_id = cur.lastrowid
            await db.commit()
        except Exception:
            raise HTTPException(status_code=400, detail="Источник с таким URL уже существует")

    # Scrape immediately
    res = await scrape_single_source(source_id, url)
    return {
        "status": "ok",
        "id": source_id,
        "message": f"Источник добавлен. Найдено конфигураций: {res['found']}, добавлено: {res['added']}"
    }

@router.delete("/{source_id}")
async def delete_source(source_id: int, user: str = Depends(require_auth)):
    async with get_db_connection() as db:
        await db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        await db.commit()
    return {"status": "ok"}

@router.post("/{source_id}/scrape")
async def scrape_source(source_id: int, user: str = Depends(require_auth)):
    async with get_db_connection() as db:

        cur = await db.execute("SELECT url FROM sources WHERE id = ?", (source_id,))
        row = await cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Источник не найден")
        url = row["url"]

    res = await scrape_single_source(source_id, url)
    return {
        "status": "ok",
        "found": res["found"],
        "added": res["added"],
        "error": res["error"]
    }
