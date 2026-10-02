"""Public-hosting protections and adversarial multi-user HTTP requests."""
import asyncio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from backend.core.config import validate_config
from backend.core.rate_limit import RateLimiter
from backend.persistence.database import Base, get_db
from backend.persistence.models import LoginChallenge
from backend.web.main import app
from backend.web import security


@pytest.fixture
def client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine, expire_on_commit=False) as session:
            yield session
    app.dependency_overrides[get_db] = db
    with TestClient(app) as client:
        yield client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def test_login_flood_is_limited_before_creating_challenges(client, monkeypatch):
    client, engine = client
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'test-token')
    monkeypatch.setenv('TELEGRAM_BOT_USERNAME', 'test_bot')
    for _ in range(security.LOGIN_LIMIT):
        assert client.post('/api/auth/bot/start', headers={'Origin': 'http://localhost:8000'}).status_code == 200
    response = client.post('/api/auth/bot/start', headers={'Origin': 'http://localhost:8000', 'X-Forwarded-For': '1.2.3.4'})
    assert response.status_code == 429
    assert response.headers['Retry-After'] == '60'
    assert response.headers['Cache-Control'] == 'no-store'
    with Session(engine) as db:
        assert len(db.scalars(select(LoginChallenge)).all()) == security.LOGIN_LIMIT


def test_headers_auth_and_body_limits(client, monkeypatch):
    client, _ = client
    for path in ['/api/me', '/api/config', '/']:
        response = client.get(path)
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert "script-src 'self'" in response.headers['Content-Security-Policy']
        assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert client.get('/api/accounts').status_code == 401
    assert client.get('/api/accounts', headers={'Cookie': 'budgenta_session=forged'}).status_code == 401
    assert client.post('/api/accounts', json={}).status_code == 403
    assert client.post('/api/accounts', headers={'Origin': 'https://attacker.invalid'}, json={}).status_code == 403
    response = client.post('/api/auth/telegram', headers={'Origin': 'http://localhost:8000'}, content=b'x' * (security.MAX_BODY_BYTES + 1))
    assert response.status_code == 413
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert client.get('/openapi.json').status_code == 404
    monkeypatch.setattr(security, 'API_LIMIT', 1)
    security.limiter.clear()
    assert client.get('/api/config').status_code == 200
    assert client.get('/api/config').status_code == 429


def test_actual_chunked_body_limit():
    called = []
    sent = []
    async def downstream(scope, receive, send):
        called.append(True)
    middleware = security.SecurityMiddleware(downstream)
    chunks = iter([{'type': 'http.request', 'body': b'x' * security.MAX_BODY_BYTES, 'more_body': True},
                   {'type': 'http.request', 'body': b'x', 'more_body': False}])
    async def receive():
        return next(chunks)
    async def send(message):
        sent.append(message)
    scope = {'type': 'http', 'method': 'POST', 'path': '/api/accounts', 'client': ('test', 1),
             'headers': [(b'origin', b'http://localhost:8000')]}
    asyncio.run(middleware(scope, receive, send))
    assert not called
    assert sent[0]['status'] == 413


@pytest.mark.parametrize('origin,secure', [('http://budget.example.com', 'false'),
    ('https://budget.example.com', 'false'), ('https://budget.example.com/', 'true'),
    ('https://user:password@budget.example.com', 'true'), ('https://budget.example.com?x=1', 'true')])
def test_insecure_public_configuration_rejected(monkeypatch, origin, secure):
    monkeypatch.setenv('APP_ORIGIN', origin)
    monkeypatch.setenv('COOKIE_SECURE', secure)
    with pytest.raises(RuntimeError):
        validate_config()


def test_public_host_and_secure_session(client, monkeypatch, telegram_login):
    client, _ = client
    telegram_login(client)
    monkeypatch.setenv('APP_ORIGIN', 'https://budget.example.com')
    monkeypatch.setenv('COOKIE_SECURE', 'true')
    monkeypatch.setenv('TELEGRAM_BOT_USERNAME', 'test_bot')
    validate_config()
    assert client.get('/api/config', headers={'Host': 'attacker.invalid'}).status_code == 400
    response = client.get('/api/me', headers={'Host': 'budget.example.com'})
    assert response.status_code == 200
    assert response.headers['Strict-Transport-Security'] == 'max-age=31536000'
    from backend.web.auth import set_session, COOKIE
    from starlette.responses import Response
    from types import SimpleNamespace
    response = Response()
    set_session(response, SimpleNamespace(id=1))
    assert all(flag in response.headers['set-cookie'] for flag in ('HttpOnly', 'Secure', 'SameSite=lax'))


def test_rate_limiter_expires_and_bounds_memory(monkeypatch):
    from backend.core import rate_limit
    monkeypatch.setattr(rate_limit, 'monotonic', lambda: 0)
    limiter = RateLimiter(max_keys=2)
    assert limiter.allow('a', 1)
    assert not limiter.allow('a', 1)
    assert limiter.allow('b', 1)
    assert not limiter.allow('c', 1)
    monkeypatch.setattr(rate_limit, 'monotonic', lambda: 61)
    assert limiter.allow('c', 1)
    assert limiter.allow('a', 1)
    assert len(limiter.buckets) == 2


def test_bot_flood_and_mismatched_sender_do_not_create_users(client, monkeypatch):
    from backend.bot import worker
    from backend.persistence.models import User
    _, engine = client
    monkeypatch.setattr(worker, 'engine', engine)
    for _ in range(30):
        assert worker.bot_limiter.allow(111, 30)
    def update(identifier, sender, chat):
        return {'update_id': identifier, 'message': {'text': '/start', 'from': {'id': sender}, 'chat': {'id': chat, 'type': 'private'}}}
    assert worker.process_update(update(1, 111, 111)) is None
    assert worker.process_update(update(2, 222, 111)) is None
    with Session(engine) as db:
        assert db.scalars(select(User)).all() == []


def test_telegram_network_error_does_not_expose_token():
    import httpx
    from backend.bot.worker import telegram, TelegramError
    class FailedClient:
        async def post(self, method, json):
            raise httpx.ConnectError('https://api.telegram.org/botFAKE_PRIVATE_TOKEN/' + method)
    with pytest.raises(TelegramError) as exc:
        asyncio.run(telegram(FailedClient(), 'setMyCommands', {}))
    import traceback
    output = ''.join(traceback.format_exception(exc.value))
    assert 'FAKE_PRIVATE_TOKEN' not in output


def test_cross_user_mutations_and_reports_are_isolated(client, telegram_login):
    client, _ = client
    headers = {'Origin': 'http://localhost:8000'}
    def post(path, body):
        response = client.post('/api' + path, headers=headers, json=body)
        assert response.status_code in (200, 201), response.text
        return response.json()
    telegram_login(client, 111)
    a = post('/accounts', {'name': 'Alice secret', 'kind': 'cash', 'currency': 'USD', 'opening_balance': '100'})['id']
    saved = post('/accounts', {'name': 'Alice reserve', 'kind': 'savings', 'currency': 'USD', 'opening_balance': '20'})['id']
    entry = post('/entries', {'account_id': a, 'kind': 'expense', 'amount': '1', 'category': 'Private'})['id']
    group = client.get('/api/accounts').json()[0]['group_id']
    debt = post('/debts', {'name': 'Alice loan', 'currency': 'USD', 'amount': '10'})['id']
    goal = post('/goals', {'name': 'Alice goal', 'currency': 'USD', 'target': '100', 'savings_account_ids': [saved]})['id']
    rule = post('/savings/rules', {'source_id': a, 'destination_id': saved, 'mode': 'fixed', 'amount': '5'})['id']
    telegram_login(client, 222)
    b = post('/accounts', {'name': 'Bob', 'kind': 'cash', 'currency': 'USD', 'opening_balance': '50'})['id']
    attacks = [
        ('/entries', {'account_id': a, 'kind': 'expense', 'amount': '1'}),
        (f'/entries/{entry}/delete', {}),
        (f'/accounts/{a}/balance', {'balance': '999'}),
        (f'/account-groups/{group}/edit', {'name': 'Stolen', 'kind': 'cash'}),
        (f'/account-groups/{group}/archive', {'archived': True}),
        ('/transfers', {'source_id': a, 'destination_id': b, 'amount': '1'}),
        ('/transfers', {'source_id': b, 'destination_id': a, 'amount': '1'}),
        ('/exchanges', {'source_id': a, 'destination_id': b, 'amount': '1', 'rate': '1'}),
        (f'/debts/{debt}/payments', {'account_id': b, 'amount': '1'}),
        (f'/debts/{debt}/archive', {'archived': True}),
        (f'/goals/{goal}/progress', {'saved': '999'}),
        ('/goals', {'name': 'Steal reserve', 'currency': 'USD', 'target': '100', 'savings_account_ids': [saved]}),
        (f'/savings/rules/{rule}', {'enabled': False}),
        ('/savings/move', {'source_id': b, 'destination_id': saved, 'amount': '1'}),
        ('/preferences/current-state', {'account_ids': [group]}),
    ]
    for path, body in attacks:
        response = client.post('/api' + path, headers=headers, json=body)
        assert response.status_code == 400, (path, response.text)
    for path in ['/accounts', '/account-groups', '/debts', '/goals', '/savings/rules', '/categories', '/report-preview/current-state']:
        response = client.get('/api' + path)
        assert response.status_code == 200
        assert 'Alice' not in response.text and 'Private' not in response.text
    telegram_login(client, 111)
    assert client.get('/api/accounts').json()[0]['balance'] == '99.000000'
    assert client.get('/api/debts').json()[0]['remaining'] == '10'
