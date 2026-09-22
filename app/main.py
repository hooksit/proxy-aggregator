import os
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import init_db, get_db_connection
from app.auth import get_current_user_optional, require_auth
from app.scheduler import init_scheduler, safe_parse_job, safe_check_job

from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.configs import router as configs_router
from app.api.sources import router as sources_router
from app.api.settings import router as settings_router
from app.api.sub import router as sub_router

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    await init_scheduler()
    
    # Check if we have 0 configs on initial boot, trigger initial parse in background
    async def initial_bootstrap():
        await asyncio.sleep(2.0)
        async with get_db_connection() as db:
            cur = await db.execute("SELECT COUNT(*) as cnt FROM configs")

            count = (await cur.fetchone())["cnt"]
        if count == 0:
            print("[Bootstrap] DB is empty, triggering initial source parse & test...")
            await safe_parse_job()

    asyncio.create_task(initial_bootstrap())
    yield
    # Shutdown

app = FastAPI(
    title="VPN Config Vault",
    description="Parser, Checker & Manager for VLESS, VMess, SS, Hy2, Trojan",
    version="1.0.0",
    lifespan=lifespan
)

# Include Routers
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(configs_router)
app.include_router(sources_router)
app.include_router(settings_router)
app.include_router(sub_router)

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    from app.database import has_any_users
    if await has_any_users():
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="setup.html")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    from app.database import has_any_users
    if not await has_any_users():
        return RedirectResponse(url="/setup", status_code=status.HTTP_302_FOUND)
    user = await get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, user: str = Depends(require_auth)):
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"user": user})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
