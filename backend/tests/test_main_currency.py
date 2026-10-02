from datetime import date, datetime, timezone
from decimal import Decimal
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from backend.core.schemas import ReportPreferences, NewAccountGroup
from backend.core.encryption import PREFIX
from backend.persistence.database import Base, get_db
from backend.persistence.models import User, Preferences
from backend.services import rates, reporting, budget
from backend.web.main import app


def quote(currency):
    values = {'USD': '1', 'EUR': '1.2', 'ARS': '0.001', 'UAH': '0.025',
              'USDT': '0.999', 'TRX': '0.25', 'BTC': '60000', 'ETH': '3000'}
    return {'usd_rate': values[currency], 'stale': False, 'display_rate': currency + ' reference',
            'source': 'Test', 'as_of': '2026-10-02'}


@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([User(id=1, telegram_id=111, name='Alice'), User(id=2, telegram_id=222, name='Bob')])
        session.commit()
        yield session


@pytest.mark.parametrize('currency,expected', [('USD','112.00'), ('EUR','93.33'), ('ARS','112000.00'), ('UAH','4480.00'), ('USDT','112.112112'), ('TRX','448.000000'), ('BTC','0.00186667'), ('ETH','0.03733333')])
def test_total_in_every_supported_main_currency(currency, expected):
    accounts = [{'currency':'USD','balance':'100'}, {'currency':'EUR','balance':'10'}]
    result = rates.balance_valuation(accounts, currency, quote)
    assert result['total'] == expected and result['currency'] == currency
    assert result['total_usd'] == '112.00' and result['complete']
    assert expected + ' ' + currency in rates.message({**result, 'accounts': []}, include_rates=False)


def test_conversion_does_not_round_usd_intermediate_and_handles_debt_balance():
    values = [{'currency':'USD','balance':'0.00004'}]
    result = rates.balance_valuation(values, 'UAH', lambda c: {**quote(c), 'usd_rate':'0.0001' if c=='UAH' else '1'})
    assert result['total_usd'] == '0.00' and result['total'] == '0.40'
    assert rates.balance_valuation([{'currency':'USD','balance':'-10'}], 'UAH', quote)['total'] == '-400.00'


def test_missing_target_is_unavailable_and_never_mislabeled_usd_or_zero():
    result = rates.balance_valuation([{'currency':'USD','balance':'100'}], 'UAH', lambda c: None if c=='UAH' else quote(c))
    assert result['total'] is None and result['unavailable'] and not result['complete']
    assert result['missing'] == ['UAH']
    message = rates.message({**result, 'accounts': []}, include_rates=False)
    assert 'Estimated balance in UAH: unavailable' in message
    assert '0.00 UAH' not in message and '100.00 UAH' not in message


def test_same_currency_and_empty_balances_do_not_require_target_rate():
    for accounts, expected in [([], '0.00'), ([{'currency':'UAH','balance':'150'}], '150.00')]:
        result = rates.balance_valuation(accounts, 'UAH', lambda c: None)
        assert result['total'] == expected and result['complete'] and not result['unavailable']
        assert not result['missing']


def test_missing_source_is_partial_and_target_staleness_is_visible():
    result = rates.balance_valuation([{'currency':'USD','balance':'100'}, {'currency':'EUR','balance':'10'}], 'UAH',
                                    lambda c: None if c=='EUR' else {**quote(c), 'stale':c=='UAH'})
    assert result['total'] == '4000.00' and not result['complete'] and not result['unavailable']
    assert result['missing'] == ['EUR'] and result['stale']
    assert 'Partial balance' in rates.balance_heading(result)


def test_main_currency_is_encrypted_independent_and_preserved_by_legacy_saves(db):
    assert reporting.get_preferences(db, 1)['main_currency'] == 'USD'
    before = reporting.get_preferences(db, 1)
    updated = reporting.save_main_currency(db, 1, 'UAH')
    assert updated['main_currency'] == 'UAH' and updated['daily'] == before['daily']
    assert reporting.get_preferences(db, 2)['main_currency'] == 'USD'
    assert db.execute(text('SELECT payload FROM preferences WHERE user_id=1')).scalar().startswith(PREFIX)
    reporting.save_preferences(db, 1, ReportPreferences(timezone='Europe/Kyiv'))
    assert reporting.get_preferences(db, 1)['main_currency'] == 'UAH'
    reporting.save_preferences(db, 1, ReportPreferences(main_currency='USD'))
    assert reporting.get_preferences(db, 1)['main_currency'] == 'USD'
    legacy = ReportPreferences().model_dump(); del legacy['main_currency']
    db.get(Preferences, 1).payload = json.dumps(legacy); db.commit()
    assert reporting.get_preferences(db, 1)['main_currency'] == 'USD'


@pytest.mark.parametrize('frequency', ['current_state','daily','weekly','monthly'])
def test_all_telegram_reports_share_main_currency_and_keep_native_accounts(db, frequency):
    budget.create_account_group(db, 1, NewAccountGroup(name='Cash', kind='cash', balances=[{'currency':'USD','opening_balance':'100'}],date=date(2024,1,1)))
    reporting.save_main_currency(db, 1, 'UAH')
    now = datetime(2024,2,1,15,tzinfo=timezone.utc)
    result = (reporting.current_state(db,1,now,quote_fn=quote) if frequency=='current_state'
              else reporting.report_message(db,1,frequency,now,quote_fn=quote))
    assert 'Estimated balance: 4000.00 UAH' in result and '100.00 USD' in result
    assert 'UAH reference' in result  # fetched even without a UAH wallet


def test_currency_endpoint_validates_ownership_filters_and_legacy_api(telegram_login, monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def session():
        with Session(engine, expire_on_commit=False) as db: yield db
    app.dependency_overrides[get_db] = session
    monkeypatch.setattr(rates,'quote',quote)
    try:
        with TestClient(app) as client:
            path='/api/preferences/main-currency'; headers={'Origin':'http://localhost:8000'}
            assert client.post(path,headers=headers,json={'currency':'UAH'}).status_code==401
            telegram_login(client)
            assert client.post(path,headers=headers,json={'currency':'INVALID'}).status_code==422
            assert client.post(path,headers={'Origin':'https://attacker.invalid'},json={'currency':'UAH'}).status_code==403
            for kind,amount in [('cash','100'),('savings','50')]:
                assert client.post('/api/accounts',headers=headers,json={'name':kind,'kind':kind,'currency':'USD','opening_balance':amount}).status_code==201
            preferences=client.get('/api/preferences').json(); preferences['dashboard']['include_savings']=False
            client.post('/api/preferences',headers=headers,json=preferences)
            usd = client.get('/api/balance?dashboard=true').json()
            assert usd['total']=='100.00' and any(q['currency']=='UAH' for q in usd['display_quotes'])
            preferences['dashboard']['excluded_currencies']=['UAH']
            client.post('/api/preferences',headers=headers,json=preferences)
            assert client.get('/api/balance?dashboard=true').json()['display_quotes']==[]
            preferences['dashboard']['excluded_currencies']=[]
            preferences['dashboard']['include_rates']=False
            client.post('/api/preferences',headers=headers,json=preferences)
            assert client.get('/api/balance?dashboard=true').json()['display_quotes']==[]
            preferences['dashboard']['include_rates']=True
            client.post('/api/preferences',headers=headers,json=preferences)
            monkeypatch.setattr(rates,'quote',lambda c: None if c=='UAH' else quote(c))
            missing_reference=client.get('/api/balance?dashboard=true').json()
            assert missing_reference['total']=='100.00' and missing_reference['complete']
            assert missing_reference['unavailable_reference_rates']==['UAH']
            monkeypatch.setattr(rates,'quote',quote)
            assert client.post(path,headers=headers,json={'currency':'UAH'}).json()['main_currency']=='UAH'
            total=client.get('/api/balance?dashboard=true').json()
            assert total['currency']=='UAH' and total['total']=='4000.00'
            assert client.get('/api/balance').json()['total']=='6000.00'
            assert client.get('/api/balance/usd?dashboard=true').json()['total_usd']=='100.00'
            client.post('/api/auth/logout',headers=headers,json={});telegram_login(client,telegram_id=222)
            assert client.get('/api/preferences').json()['main_currency']=='USD'
            assert client.get('/api/balance').json()['total']=='0.00'
    finally:
        app.dependency_overrides.clear()


def test_uah_is_refetched_automatically_after_cache_expiry(monkeypatch):
    calls=[]; clock=[1000]
    monkeypatch.setattr(rates,'_CACHE',{})
    monkeypatch.setattr(rates.time,'time',lambda:clock[0])
    def fetch(currency):
        calls.append(currency)
        return {**quote(currency),'as_of':datetime.now(timezone.utc).date().isoformat()}
    monkeypatch.setattr(rates,'fetch_quote',fetch)
    for _ in range(2): assert rates.quote('UAH')['usd_rate']=='0.025'
    assert calls==['UAH']
    clock[0]+=301
    assert rates.quote('UAH')['usd_rate']=='0.025' and calls==['UAH','UAH']
