import os
from cryptography.fernet import Fernet
# Set isolation before any test imports persistence; collection order must never
# select the workspace database or reuse a prior run's encrypted SQLite file.
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['SESSION_SECRET'] = 'test-secret-that-is-longer-than-thirty-two-characters'
os.environ['APP_ORIGIN'] = 'http://localhost:8000'
os.environ['DATA_ENCRYPTION_KEYS'] = Fernet.generate_key().decode()
os.environ['IDENTITY_HASH_KEY'] = 'test-identity-secret-not-used-outside-tests'


import hashlib
import hmac
import time
import pytest


@pytest.fixture(autouse=True)
def reset_request_limits():
    from backend.web.security import limiter
    from backend.bot.worker import bot_limiter
    limiter.clear()
    bot_limiter.clear()
    yield
    limiter.clear()
    bot_limiter.clear()


@pytest.fixture
def telegram_login(monkeypatch):
    """Exercise the signed Telegram endpoint using a test-only bot token."""
    token = 'test-only-telegram-token'
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', token)
    def sign_in(client, telegram_id=111):
        data = {'id': telegram_id, 'first_name': 'Test user', 'auth_date': int(time.time())}
        check = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
        data['hash'] = hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
        response = client.post('/api/auth/telegram', headers={'Origin': 'http://localhost:8000'}, json=data)
        assert response.status_code == 200, response.text
        return response.json()
    return sign_in
