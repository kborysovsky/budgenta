"""Telegram approval of one-use login challenges, without HTTP dependencies."""
from datetime import datetime, timezone
from sqlalchemy import select
from backend.persistence.models import LoginChallenge

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def approve(db, identifier, user_id):
    challenge = db.scalar(select(LoginChallenge).where(LoginChallenge.id==identifier).with_for_update())
    if not challenge or challenge.consumed or challenge.expires_at <= now() or challenge.user_id is not None:
        return False
    challenge.user_id = user_id
    db.commit()
    return True
