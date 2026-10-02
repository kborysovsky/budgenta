"""Identity lookup shared by HTTP and Telegram."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from backend.core.encryption import identity_key
from backend.persistence.models import User

def find_or_create_user(db, telegram_id, name):
    key = identity_key(telegram_id)
    user = db.scalar(select(User).where(User.telegram_key == key))
    if not user:
        try:
            with db.begin_nested():
                user = User(telegram_id=telegram_id, name=name[:120])
                db.add(user)
                db.flush()
            db.commit()
        except IntegrityError:
            user = db.scalar(select(User).where(User.telegram_key == key))
            if not user:
                raise
    return user
