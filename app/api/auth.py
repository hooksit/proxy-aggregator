from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from pydantic import BaseModel
from app.auth import authenticate_user, create_session_token, SESSION_COOKIE_NAME, require_auth
from app.database import get_db_connection, hash_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

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
