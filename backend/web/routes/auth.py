"""Auth HTTP endpoints."""
from fastapi import APIRouter
import os
from fastapi import Depends, HTTPException, Request, Response
from backend.services.users import find_or_create_user
from backend.web.auth import get_user, set_session, verify_telegram, COOKIE
from backend.persistence.database import get_db
from backend.web import login_flow

router = APIRouter(tags=["auth"])

@router.post("/api/auth/telegram")
def login(data: dict, response: Response, db=Depends(get_db)):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise HTTPException(503, "Telegram login is not configured.")
    try:
        telegram_id = verify_telegram(data, token)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(401, "Invalid or expired Telegram login.")
    if telegram_id <= 0:
        raise HTTPException(403, "This Telegram account is not allowed.")
    user = find_or_create_user(db, telegram_id, str(data.get("first_name", "You")))
    set_session(response, user)
    return {"name": user.name}


@router.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/api/me")
def me(user=Depends(get_user)):
    return {"name": user.name}


@router.post('/api/auth/bot/start')
def bot_login_start(response: Response, db=Depends(get_db)):
    return login_flow.start(db, response)


@router.get('/api/auth/bot/status')
def bot_login_status(request: Request, db=Depends(get_db)):
    return login_flow.status(db, request)


@router.post('/api/auth/bot/complete')
def bot_login_complete(request: Request, response: Response, db=Depends(get_db)):
    return login_flow.complete(db, request, response)

