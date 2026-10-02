"""One-use, browser-bound sign-in approved through a private Telegram chat."""
import hashlib
import hmac
import os
import secrets
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select, delete
from backend.persistence.models import LoginChallenge, User
from backend.web.auth import set_session

from backend.services.login import now, approve

COOKIE = 'pocket_login'


def start(db, response):
    username = os.getenv('TELEGRAM_BOT_USERNAME', '').lstrip('@')
    if not username or not os.getenv('TELEGRAM_BOT_TOKEN'):
        raise HTTPException(503, 'Telegram login is not configured.')
    identifier, browser_secret = secrets.token_hex(16), secrets.token_hex(32)
    db.execute(delete(LoginChallenge).where(LoginChallenge.expires_at < now()))
    db.add(LoginChallenge(id=identifier, browser_key=hashlib.sha256(browser_secret.encode()).hexdigest(), expires_at=now()+timedelta(minutes=5)))
    db.commit()
    response.set_cookie(COOKIE, identifier+'.'+browser_secret, max_age=300, httponly=True, secure=os.getenv('COOKIE_SECURE')=='true', samesite='lax')
    return {'url': f'https://t.me/{username}?start=login_{identifier}', 'code': identifier[:6].upper(), 'expires_in': 300}

def browser_challenge(db, request):
    try:
        identifier, secret = request.cookies.get(COOKIE, '').split('.')
    except ValueError:
        raise HTTPException(401, 'Start Telegram login in this browser first.')
    challenge = db.scalar(select(LoginChallenge).where(LoginChallenge.id==identifier).with_for_update())
    if not challenge or challenge.consumed or challenge.expires_at <= now():
        raise HTTPException(401, 'Login expired or already used. Please try again.')
    if not hmac.compare_digest(challenge.browser_key, hashlib.sha256(secret.encode()).hexdigest()):
        raise HTTPException(401, 'This login belongs to another browser.')
    return challenge

def status(db, request):
    challenge = browser_challenge(db, request)
    user = db.get(User, challenge.user_id) if challenge.user_id else None
    return {'approved': bool(user), 'name': user.name if user else None}


def complete(db, request, response):
    challenge = browser_challenge(db, request)
    if not challenge.user_id:
        raise HTTPException(409, 'Confirm the login in Telegram first.')
    user = db.get(User, challenge.user_id)
    challenge.consumed = True
    db.commit()
    set_session(response, user)
    response.delete_cookie(COOKIE)
    return {'name': user.name}
