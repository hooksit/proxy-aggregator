from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from pydantic import BaseModel
from app.auth import authenticate_user, create_session_token, SESSION_COOKIE_NAME, require_auth, get_current_user_optional
from app.database import get_db_connection, hash_password, has_any_users

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class SetupRequest(BaseModel):
    username: str
    password: str
    confirm_password: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

@router.get("/status")
async def auth_status(request: Request):
    is_setup = await has_any_users()
    current_user = await get_current_user_optional(request)
    return {
        "is_setup": is_setup,
        "authenticated": current_user is not None,
        "username": current_user
    }

@router.post("/setup")
async def setup_admin(req: SetupRequest, response: Response):
    if await has_any_users():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Панель уже настроена. Первоначальное создание администратора недоступно."
        )

    username = req.username.strip()
    if len(username) < 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Имя пользователя должно содержать не менее 3 символов"
        )

    if len(req.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пароль должен содержать не менее 6 символов"
        )

    if req.confirm_password is not None and req.password != req.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Введенные пароли не совпадают"
        )

    pw_hash = hash_password(req.password)
    async with get_db_connection() as db:
        await db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, pw_hash)
        )
        await db.commit()

    token = create_session_token(username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=86400 * 7,
        samesite="lax"
    )
    return {
        "status": "ok",
        "message": "Учетная запись администратора успешно создана",
        "username": username,
        "token": token
    }

@router.post("/login")
async def login(req: LoginRequest, response: Response):
    ok = await authenticate_user(req.username, req.password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверное имя пользователя или пароль"
        )
    
    token = create_session_token(req.username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=86400 * 7,
        samesite="lax"
    )
    return {"status": "ok", "token": token, "username": req.username}

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "ok"}

@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, username: str = Depends(require_auth)):
    ok = await authenticate_user(username, req.current_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Текущий пароль указан неверно"
        )
    
    if len(req.new_password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен содержать не менее 6 символов"
        )

    new_hash = hash_password(req.new_password)
    async with get_db_connection() as db:
        await db.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, username))
        await db.commit()


    return {"status": "ok", "message": "Пароль успешно изменен"}
