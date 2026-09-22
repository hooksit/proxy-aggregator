from fastapi import Request, HTTPException, status, Depends
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from typing import Optional
from app.config import settings
from app.database import get_db_connection, verify_password

serializer = URLSafeTimedSerializer(settings.SECRET_KEY)
SESSION_COOKIE_NAME = "vpn_aggregator_session"
MAX_SESSION_AGE = 86400 * 7  # 7 days

def create_session_token(username: str) -> str:
    return serializer.dumps({"username": username})

def verify_session_token(token: str) -> Optional[str]:
    try:
        data = serializer.loads(token, max_age=MAX_SESSION_AGE)
        return data.get("username")
    except (BadSignature, SignatureExpired):
        return None

async def authenticate_user(username: str, password: str) -> bool:
    async with get_db_connection() as db:
        cursor = await db.execute("SELECT password_hash FROM users WHERE username = ?", (username,))

        row = await cursor.fetchone()
        if not row:
            return False
        return verify_password(password, row["password_hash"])

async def get_current_user_optional(request: Request) -> Optional[str]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        # Check authorization header as Bearer token alternative
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            return None
    return verify_session_token(token)

async def require_auth(request: Request) -> str:
    from app.database import has_any_users
    if not await has_any_users():
        if request.url.path.startswith("/api/"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Требуется первоначальная настройка администратора на /setup"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/setup"}
            )

    username = await get_current_user_optional(request)
    if not username:
        if request.url.path.startswith("/api/"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/login"}
            )
    return username
