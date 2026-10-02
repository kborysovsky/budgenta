import hashlib
import hmac
import os
import time
from fastapi import Depends, HTTPException, Request
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from backend.persistence.database import get_db
from backend.persistence.models import User

COOKIE = "budget_session"

def serializer():
    secret = os.getenv("SESSION_SECRET", "")
    if len(secret) < 32 or secret.startswith("replace-with"):
        raise RuntimeError("Set SESSION_SECRET to a random value of at least 32 characters.")
    return URLSafeTimedSerializer(secret, salt="budget-session-v1")

def verify_telegram(data, token, now=None):
    values = {k: str(v) for k, v in data.items() if k != "hash"}
    allowed = {"id", "first_name", "last_name", "username", "photo_url", "auth_date"}
    if set(values) - allowed:
        raise ValueError("Invalid Telegram fields.")
    check = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
    expected = hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(data.get("hash", ""))):
        raise ValueError("Invalid Telegram signature.")
    age = (time.time() if now is None else now) - int(values["auth_date"])
    if age < -30 or age > 300:
        raise ValueError("Telegram login expired. Please sign in again.")
    return int(values["id"])

def get_user(request: Request, db=Depends(get_db)):
    try:
        user_id = serializer().loads(request.cookies.get(COOKIE, ""), max_age=7 * 86400)
        user = db.get(User, int(user_id))
        if not user:
            raise ValueError()
        if user.telegram_id <= 0:
            raise ValueError()
        return user
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        raise HTTPException(401, "Sign in to continue.")


def set_session(response, user):
    response.set_cookie(COOKIE, serializer().dumps(user.id), httponly=True, secure=os.getenv("COOKIE_SECURE") == "true", samesite="lax", max_age=7 * 86400)
