import os
os.environ['SESSION_SECRET'] = 'test-secret-that-is-longer-than-thirty-two-characters'
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['APP_ORIGIN'] = 'http://localhost:8000'
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from backend.web.main import app
from backend.persistence.database import Base, get_db


def test_auth_origin_and_account_roundtrip(telegram_login):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine, expire_on_commit=False) as session:
            yield session
    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app) as client:
            assert client.get('/api/accounts').status_code == 401
            assert client.post('/api/auth/telegram', headers={'Origin': 'https://attacker.invalid'}, json={}).status_code == 403
            headers = {'Origin': 'http://localhost:8000'}
            telegram_login(client)
            result = client.post('/api/accounts', headers=headers, json={'name': 'My cash', 'kind': 'cash', 'currency': 'USD', 'opening_balance': '10.10'})
            assert result.status_code == 201, result.text
            assert client.get('/api/accounts').json()[0]['balance'] == '10.100000'
            assert client.post('/api/entries', headers=headers, json={'account_id': result.json()['id'], 'kind': 'expense', 'amount': '0.01'}).status_code == 201
            assert client.get('/api/accounts').json()[0]['balance'] == '10.090000'
            assert client.get('/api/months/not-a-month').status_code == 400
            assert client.post('/api/auth/logout', headers=headers, json={}).status_code == 200
            assert client.get('/api/accounts').status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_multi_currency_and_preferences_http_roundtrip(telegram_login):
    from backend.web import main
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine, expire_on_commit=False) as session:
            yield session
    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app) as client:
            headers={'Origin':'http://localhost:8000'}
            telegram_login(client)
            response=client.post('/api/account-groups',headers=headers,json={'name':'Cash','kind':'cash','balances':[{'currency':'USD','opening_balance':'100'},{'currency':'ARS','opening_balance':'200'}]})
            assert response.status_code==201,response.text
            groups=client.get('/api/account-groups').json()
            assert len(groups)==1 and len(groups[0]['balances'])==2
            savings=client.post('/api/account-groups',headers=headers,json={'name':'Reserve','kind':'savings','balances':[{'currency':'USD','opening_balance':'50'}]})
            prefs=client.get('/api/preferences').json()
            assert prefs['daily']['time']=='09:15'
            prefs['dashboard']['include_savings']=False
            prefs['daily']['account_ids']=[response.json()['id']]
            assert client.post('/api/preferences',headers=headers,json=prefs).status_code==200
            assert client.get('/api/preferences').json()['dashboard']['include_savings'] is False
            prefs['weekly']['time']='99:01'
            assert client.post('/api/preferences',headers=headers,json=prefs).status_code==422
            assert client.get('/api/report-preview/invalid').status_code==404
            assert client.post('/api/account-groups/merge',headers=headers,json={'source_id':response.json()['id'],'destination_id':savings.json()['id']}).status_code==400
    finally:
        app.dependency_overrides.clear()


def test_web_management_goal_links_and_debt_payment(telegram_login):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine,expire_on_commit=False) as session: yield session
    app.dependency_overrides[get_db]=db
    try:
        with TestClient(app) as client:
            headers={'Origin':'http://localhost:8000'}
            def post(path,data):
                result=client.post('/api'+path,headers=headers,json=data)
                assert result.status_code in (200,201),result.text
                return result.json()
            telegram_login(client)
            cash=post('/accounts',{'name':'Cash','kind':'cash','currency':'USD','opening_balance':'100'})['id']
            saved=post('/accounts',{'name':'Reserve','kind':'savings','currency':'USD','opening_balance':'20'})['id']
            identifier=post('/goals',{'name':'Trip','currency':'USD','target':'200','savings_account_ids':[saved]})['id']
            assert client.get('/api/goals').json()[0]['saved']=='20'
            post('/accounts/'+str(saved)+'/balance',{'balance':'30'})
            assert client.get('/api/goals').json()[0]['saved']=='30'
            debt=post('/debts',{'name':'Loan','currency':'USD','amount':'50'})['id']
            post(f'/debts/{debt}/payments',{'account_id':cash,'amount':'10'})
            assert client.get('/api/debts').json()[0]['remaining']=='40'
            post(f'/debts/{debt}/edit',{'name':'Loan updated','currency':'USD','amount':'60'})
            assert client.get('/api/debts').json()[0]['remaining']=='50'
            post(f'/goals/{identifier}/archive',{'archived':True})
            assert client.get('/api/goals').json()==[]
            assert client.get('/api/goals?include_archived=true').json()[0]['saved']=='30'
            post(f'/goals/{identifier}/archive',{'archived':False})
            assert client.get('/api/goals').json()[0]['savings_account_ids']==[]
    finally: app.dependency_overrides.clear()


def test_current_state_and_account_layout_settings_http(telegram_login):
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine,expire_on_commit=False) as session:yield session
    app.dependency_overrides[get_db]=db
    try:
        with TestClient(app) as client:
            headers={'Origin':'http://localhost:8000'}
            def post(path,data):
                result=client.post('/api'+path,headers=headers,json=data)
                assert result.status_code in (200,201),result.text
                return result.json()
            telegram_login(client)
            one=post('/account-groups',{'name':'One','kind':'debit','balances':[{'currency':'USD','opening_balance':'10'}]})['id']
            two=post('/account-groups',{'name':'Two','kind':'cash','balances':[{'currency':'USD','opening_balance':'20'}]})['id']
            post('/preferences/accounts-page',{'order':[two,one],'show_credit':False})
            assert [a['id'] for a in client.get('/api/account-groups').json()]==[two,one]
            post('/preferences/current-state',{'include_rates':False,'include_debts':False,'include_goals':False,'include_savings':False,'excluded_currencies':['TRX']})
            preview=client.get('/api/report-preview/current-state')
            assert preview.status_code==200,preview.text
            assert preview.json()['text'].index('Two:\n  20.00 USD')<preview.json()['text'].index('One:\n  10.00 USD')
            assert 'Debts (' not in preview.json()['text']
            prefs=client.get('/api/preferences').json()
            assert not prefs['accounts_page']['show_credit'] and not prefs['current_state']['include_debts']
            assert prefs['monthly']['enabled']
            assert prefs['current_state']['excluded_currencies']==['TRX']
            assert client.post('/api/preferences/current-state',headers=headers,json={'excluded_currencies':['INVALID']}).status_code==422
    finally:app.dependency_overrides.clear()


def test_local_login_removed_and_old_local_sessions_rejected(monkeypatch, telegram_login):
    from backend.persistence.models import User
    from backend.web.auth import COOKIE, serializer
    monkeypatch.setenv('DEV_LOGIN','true')  # An old server setting cannot re-enable it.
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine,expire_on_commit=False) as session:yield session
    app.dependency_overrides[get_db]=db
    try:
        with Session(engine) as session:
            session.add(User(id=1,telegram_id=-1,name='Former local workspace'));session.commit()
        with TestClient(app) as client:
            assert '/api/auth/dev' not in app.openapi()['paths']
            assert client.get('/openapi.json').status_code == 404
            assert client.post('/api/auth/dev',headers={'Origin':'http://localhost:8000'},json={}).status_code in (404,405)
            assert 'dev_login' not in client.get('/api/config').json()
            client.cookies.set(COOKIE,serializer().dumps(1))
            assert client.get('/api/me').status_code==401
            assert client.get('/api/accounts').status_code==401
            client.cookies.clear()
            telegram_login(client)
            assert client.get('/api/me').json()['name']=='Test user'
    finally:app.dependency_overrides.clear()


def test_browser_telegram_approval_creates_session_without_dev_login(monkeypatch):
    from backend.services import login
    from backend.services.users import find_or_create_user
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-only-token')
    monkeypatch.setenv('TELEGRAM_BOT_USERNAME','test_budgenta_bot')
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine,expire_on_commit=False) as session:yield session
    app.dependency_overrides[get_db]=db
    headers={'Origin':'http://localhost:8000'}
    try:
        with TestClient(app) as client:
            result=client.post('/api/auth/bot/start',headers=headers,json={})
            assert result.status_code==200
            identifier=result.json()['url'].split('login_',1)[1]
            assert client.get('/api/auth/bot/status').json()['approved'] is False
            assert client.post('/api/auth/bot/complete',headers=headers,json={}).status_code==409
            with Session(engine,expire_on_commit=False) as session:
                user=find_or_create_user(session,222,'Telegram person')
                assert login.approve(session,identifier,user.id)
            assert client.get('/api/auth/bot/status').json()=={'approved':True,'name':'Telegram person'}
            assert client.post('/api/auth/bot/complete',headers=headers,json={}).status_code==200
            assert client.get('/api/me').json()=={'name':'Telegram person'}
            assert client.post('/api/auth/bot/complete',headers=headers,json={}).status_code==401
    finally:app.dependency_overrides.clear()


def test_exchange_preview_save_delete_and_ownership(telegram_login):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine, expire_on_commit=False) as session:
            yield session
    app.dependency_overrides[get_db] = db
    headers = {'Origin': 'http://localhost:8000'}
    try:
        with TestClient(app) as client:
            data = {'source_id': 1, 'destination_id': 2, 'amount': '10', 'rate': '1500'}
            assert client.post('/api/exchanges', headers=headers, json=data).status_code == 401
            assert client.post('/api/exchanges/preview', headers=headers, json=data).status_code == 401
            telegram_login(client)
            for name, kind, currency, balance in [('Wallet', 'crypto', 'USDT', '100'), ('Cash', 'cash', 'ARS', '0')]:
                result = client.post('/api/accounts', headers=headers, json={'name': name, 'kind': kind, 'currency': currency, 'opening_balance': balance})
                assert result.status_code == 201
                data['source_id' if currency == 'USDT' else 'destination_id'] = result.json()['id']
            preview = client.post('/api/exchanges/preview', headers=headers, json=data)
            assert preview.status_code == 200 and preview.json()['received'] == '15000.00'
            assert client.get('/api/accounts').json()[0]['balance'] == '100.000000'
            assert client.post('/api/exchanges', headers=headers, json={**data, 'rate': 'NaN'}).status_code == 422
            assert client.post('/api/exchanges', headers={'Origin': 'https://attacker.invalid'}, json=data).status_code == 403
            result = client.post('/api/exchanges', headers=headers, json=data)
            assert result.status_code == 201 and result.json()['received'] == preview.json()['received']
            assert client.get('/api/accounts').json()[0]['balance'] == '90.000000'
            from backend.core.calendar import today
            rows = client.get('/api/months/' + today().strftime('%Y-%m')).json()['transactions']
            leg = next(t['id'] for t in rows if t['kind'] == 'exchange')
            telegram_login(client, 222)
            assert client.post('/api/exchanges/preview', headers=headers, json=data).status_code == 400
            assert client.post('/api/exchanges', headers=headers, json=data).status_code == 400
            assert client.post(f'/api/entries/{leg}/delete', headers=headers, json={}).status_code == 400
            telegram_login(client)
            assert client.post(f'/api/entries/{leg}/delete', headers=headers, json={}).status_code == 200
            balances = client.get('/api/accounts').json()
            assert balances[0]['balance'] == '100.000000' and balances[1]['balance'] == '0.000000'
    finally:
        app.dependency_overrides.clear()


def test_custom_categories_http_privacy_and_persistence(telegram_login):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine, expire_on_commit=False) as session:
            yield session
    app.dependency_overrides[get_db] = db
    headers = {'Origin': 'http://localhost:8000'}
    try:
        with TestClient(app) as client:
            assert client.get('/api/categories').status_code == 401
            telegram_login(client)
            wallet = client.post('/api/accounts', headers=headers, json={'name': 'Cash', 'kind': 'cash', 'currency': 'USD', 'opening_balance': '100'}).json()['id']
            for kind, category, save in [('expense', 'Watches', True), ('income', 'Money from parents', True), ('expense', 'One-off purpose', False)]:
                result = client.post('/api/entries', headers=headers, json={'account_id': wallet, 'kind': kind, 'amount': '10', 'category': category, 'save_category': save})
                assert result.status_code == 201, result.text
            assert client.post('/api/entries', headers=headers, json={'account_id': wallet, 'kind': 'expense', 'amount': '1', 'category': '   ', 'save_category': True}).status_code == 422
            result = client.get('/api/categories').json()
            assert 'Watches' in result['expense'] and 'Money from parents' in result['income']
            assert 'One-off purpose' not in result['expense'] and 'Watches' not in result['income']
            telegram_login(client, 222)
            assert 'Watches' not in client.get('/api/categories').json()['expense']
            telegram_login(client)
            assert 'Watches' in client.get('/api/categories').json()['expense']
            assert 'Watches' not in str(client.get('/api/config').json())
    finally:
        app.dependency_overrides.clear()


def test_exchange_received_amount_http_roundtrip(telegram_login):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db():
        with Session(engine, expire_on_commit=False) as session:
            yield session
    app.dependency_overrides[get_db] = db
    headers = {'Origin': 'http://localhost:8000'}
    try:
        with TestClient(app) as client:
            telegram_login(client)
            ids = []
            for currency in ['USD', 'ARS']:
                response = client.post('/api/accounts', headers=headers, json={'name': currency, 'kind': 'cash', 'currency': currency, 'opening_balance': '3' if currency == 'USD' else '0'})
                ids.append(response.json()['id'])
            data = {'source_id': ids[0], 'destination_id': ids[1], 'amount': '3', 'received': '10'}
            preview = client.post('/api/exchanges/preview', headers=headers, json=data)
            assert preview.status_code == 200 and preview.json()['rate_approximate']
            assert preview.json()['received'] == '10.00'
            assert client.post('/api/exchanges', headers=headers, json={**data, 'rate': '2'}).status_code == 422
            assert client.post('/api/exchanges', headers=headers, json={**data, 'received': '10.001'}).status_code == 400
            saved = client.post('/api/exchanges', headers=headers, json=data)
            assert saved.status_code == 201 and saved.json()['rate'] == preview.json()['rate']
            assert [a['balance'] for a in client.get('/api/accounts').json()] == ['0.000000', '10.000000']
    finally:
        app.dependency_overrides.clear()
