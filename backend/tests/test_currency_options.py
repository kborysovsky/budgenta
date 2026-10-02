from datetime import date, datetime, timezone
from decimal import Decimal
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.persistence.database import Base
from backend.persistence.models import User
from backend.services import budget as service
from backend.services import reporting
from backend.services import rates
from backend.core.schemas import NewAccountGroup, NewEntry, CurrentStatePreferences, NewDebt, NewGoal, Transfer

@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(User(id=1, telegram_id=111, name='Alice')); session.commit()
        yield session


def group(db, name, kind, balances):
    return service.create_account_group(db, 1, NewAccountGroup(name=name, kind=kind, balances=[{'currency':c, 'opening_balance':v} for c,v in balances.items()], date=date(2024,1,1)))


def quote(currency):
    values = {'USD':'1', 'TRX':'0.25', 'USDT':'1', 'BTC':'60000', 'ETH':'3000', 'UAH':'0.025', 'EUR':'1.2', 'ARS':'0.001'}
    return {'usd_rate':values[currency], 'stale':False, 'display_rate':currency, 'source':'Test', 'as_of':'2026-10-01'}


def test_currency_exclusion_filters_entire_current_state_and_preserves_ledger(db):
    group(db, 'Crypto', 'crypto', {'USDT':'2', 'TRX':'100'})
    group(db, 'Cash', 'cash', {'USD':'10'})
    group(db, 'Fees', 'crypto', {'TRX':'1'})
    trx = next(a for a in service.accounts(db,1) if a['currency']=='TRX')
    service.add_entry(db,1,NewEntry(account_id=trx['id'],kind='expense',amount='1'))
    service.create_debt(db,1,NewDebt(name='Fee debt',currency='TRX',amount='2'))
    service.create_goal(db,1,NewGoal(name='Fee goal',currency='TRX',target='10'))
    before = reporting.get_preferences(db,1)
    assert reporting.current_state(db,1,quote_fn=quote).index('Crypto:') < reporting.current_state(db,1,quote_fn=quote).index('Cash:')
    reporting.save_section(db,1,'current_state',CurrentStatePreferences(excluded_currencies=['TRX']))
    message = reporting.current_state(db,1,quote_fn=lambda c: quote(c) if c!='TRX' else pytest.fail('Excluded currency fetched'))
    assert 'Estimated balance: 12.00 USD' in message
    assert message.index('Cash:') < message.index('Crypto:')
    assert all(word not in message for word in ('TRX','Fees:','Fee debt','Fee goal'))
    assert 'No income, expenses, or transfers recorded this month.' in message
    assert service.balance(db,trx['id'])==99
    assert reporting.get_preferences(db,1)['monthly']==before['monthly']
    assert reporting.get_preferences(db,1)['dashboard']==before['dashboard']
    reporting.save_section(db,1,'current_state',CurrentStatePreferences(excluded_currencies=['USD','TRX','USDT']))
    assert 'No accounts included.' in reporting.current_state(db,1,quote_fn=quote)
    reporting.save_section(db,1,'current_state',CurrentStatePreferences())
    assert '99.00 TRX' in reporting.current_state(db,1,quote_fn=quote)


def test_cash_and_cards_share_fiat_currencies_and_savings_accepts_all(db):
    assert service.CURRENCIES['cash']==service.CURRENCIES['card']==service.CURRENCIES['debit']==['USD','EUR','ARS','UAH']
    for kind in ('cash','card','debit','savings'):
        group(db,kind,kind,{c:'1' for c in service.CURRENCIES[kind]})
    assert len(next(g for g in service.account_groups(db,1) if g['kind']=='savings')['balances'])==8
    for currency, invalid in [('UAH','1.001'),('TRX','0.0000001'),('BTC','0.000000001'),('ETH','0.000000001')]:
        with pytest.raises(service.BudgetError): service.validate_amount(currency,Decimal(invalid))


@pytest.mark.parametrize('currency',['BTC','ETH'])
def test_crypto_precision_survives_storage_api_transfer_and_report_rounding(db,currency):
    source=group(db,'Wallet','crypto',{currency:'0.12345678'})
    dest=group(db,'Reserve','savings',{currency:'0'})
    accounts=service.accounts(db,1);a=next(a for a in accounts if a['group_id']==source);b=next(a for a in accounts if a['group_id']==dest)
    assert a['balance']=='0.12345678'
    service.transfer(db,1,Transfer(source_id=a['id'],destination_id=b['id'],amount='0.00000001'))
    db.expire_all()
    assert service.balance(db,a['id'])==Decimal('0.12345677')
    assert service.balance(db,b['id'])==Decimal('0.00000001')
    result=rates.valuation(service.accounts(db,1),quote_fn=quote)
    expected=(Decimal('0.12345678')*Decimal(quote(currency)['usd_rate'])).quantize(Decimal('.01'))
    assert Decimal(result['total_usd'])==expected
    report=rates.current_balance_message(result,include_rates=False)
    assert f'Wallet:\n  0.12 {currency}' in report and f'Reserve:\n  0.00 {currency}' in report
    assert '0.12345677' not in report
    assert rates.report_amount('-0.001')=='0.00' and rates.report_amount('1.235')=='1.24'


@pytest.mark.parametrize('currency,coin',[('BTC','bitcoin'),('ETH','ethereum'),('UAH',None)])
def test_new_quote_providers_and_conversion_direction(monkeypatch,currency,coin):
    original=httpx.Client
    def handler(request):
        if currency=='UAH':
            assert request.url.host=='bank.gov.ua' and request.url.params['valcode']=='USD'
            assert request.url.params['date']==datetime.now(timezone.utc).strftime('%Y%m%d')
            return httpx.Response(200,json=[{'cc':'USD','rate':40,'exchangedate':'01.10.2026'}])
        assert request.url.params['ids']==coin and request.url.params['vs_currencies']=='usd'
        return httpx.Response(200,json={coin:{'usd':60000 if currency=='BTC' else 3000,'last_updated_at':1790856000}})
    monkeypatch.setattr(rates.httpx,'Client',lambda **kwargs: original(transport=httpx.MockTransport(handler),**kwargs))
    result=rates.fetch_quote(currency)
    assert Decimal(result['usd_rate'])==Decimal({'BTC':'60000','ETH':'3000','UAH':'0.025'}[currency])
    assert result['as_of']


@pytest.mark.parametrize('section', ['daily', 'weekly', 'monthly', 'dashboard'])
def test_currency_exclusions_apply_to_each_report_and_dashboard(db, section):
    from backend.core.schemas import ReportPreferences
    group(db, 'Mixed', 'cash', {'USD':'100', 'UAH':'400'})
    group(db, 'Only excluded', 'cash', {'UAH':'10'})
    for account in service.accounts(db,1):
        service.add_entry(db,1,NewEntry(account_id=account['id'],kind='expense',amount='1',date=date(2024,1,31),category='Excluded only' if account['currency']=='UAH' else 'Grocery'))
    original_transactions=service.monthly(db,1,'2024-01')['transactions']
    prefs=ReportPreferences()
    getattr(prefs,section).excluded_currencies=['UAH']
    reporting.save_preferences(db,1,prefs)
    db.expire_all()
    saved=reporting.get_preferences(db,1)
    assert saved[section]['excluded_currencies']==['UAH']
    assert all(saved[other]['excluded_currencies']==[] for other in ('daily','weekly','monthly','dashboard','current_state') if other!=section)
    selected=reporting.selected_accounts(db,1,saved[section])
    assert [a['currency'] for a in selected]==['USD']
    def only_usd(currency):
        assert currency=='USD', 'Excluded rate must not be fetched'
        return quote(currency)
    assert rates.valuation(selected,only_usd)['total_usd']=='99.00'
    if section=='dashboard':
        report=reporting.dashboard(db,1,'2024-01')
        assert [t['currency'] for t in report['transactions']]==['USD','USD']
    else:
        report=reporting.period_report(db,1,date(2024,1,1),date(2024,1,31),saved[section])
        assert all(row['currency']=='USD' for row in report['categories'])
        message=reporting.report_message(db,1,section,datetime(2024,2,1,12,tzinfo=timezone.utc),quote_fn=only_usd)
        assert 'UAH' not in message and 'Excluded only' not in message and '99.00 USD' in message
        if section=='monthly':
            assert reporting.monthly_report(db,1,'2024-01')['totals']==report['totals']
    assert report['totals']==[{'currency':'USD','income':'0','expenses':'1','surplus':'-1','transfers_out':'0','transfers_in':'0'}]
    # Selecting no currencies produces an empty view, without altering the ledger.
    getattr(prefs,section).excluded_currencies=['USD','UAH']
    reporting.save_preferences(db,1,prefs)
    assert reporting.selected_accounts(db,1,reporting.get_preferences(db,1)[section])==[]
    if section=='dashboard': assert reporting.dashboard(db,1,'2024-01')['transactions']==[]
    assert service.monthly(db,1,'2024-01')['transactions']==original_transactions


def test_legacy_currency_preferences_keep_current_state_and_default_other_tabs(db):
    import json
    from backend.persistence.models import Preferences
    from backend.core.schemas import ReportPreferences
    legacy=ReportPreferences().model_dump()
    for section in ('daily','weekly','monthly','dashboard'):legacy[section].pop('excluded_currencies')
    legacy['current_state']['excluded_currencies']=['TRX']
    db.add(Preferences(user_id=1,payload=json.dumps(legacy)));db.commit()
    prefs=reporting.get_preferences(db,1)
    assert prefs['current_state']['excluded_currencies']==['TRX']
    assert all(prefs[s]['excluded_currencies']==[] for s in ('daily','weekly','monthly','dashboard'))


@pytest.mark.parametrize('section', ['daily','weekly','monthly','dashboard'])
def test_exchange_rate_visibility_preserves_valuation_and_other_tabs(db, section):
    from backend.core.schemas import ReportPreferences
    group(db,'Euros','cash',{'EUR':'100'})
    prefs=ReportPreferences()
    getattr(prefs,section).include_rates=False
    reporting.save_preferences(db,1,prefs)
    db.expire_all()
    saved=reporting.get_preferences(db,1)
    assert saved[section]['include_rates'] is False
    assert all(saved[other]['include_rates'] for other in ('daily','weekly','monthly','dashboard','current_state') if other!=section)
    accounts=reporting.selected_accounts(db,1,saved[section])
    assert rates.valuation(accounts,quote)['total_usd']=='120.00'
    if section=='dashboard': return
    message=reporting.report_message(db,1,section,quote_fn=quote)
    assert '120.00 USD' in message and '100.00 EUR' in message and 'Test' not in message
    stale=reporting.report_message(db,1,section,quote_fn=lambda c:{**quote(c),'stale':True})
    assert 'cached rates' in stale
    missing=reporting.report_message(db,1,section,quote_fn=lambda c:None)
    assert 'Partial balance' in missing and 'rate unavailable: EUR' in missing
    getattr(prefs,section).include_rates=True
    reporting.save_preferences(db,1,prefs)
    assert 'EUR · Test' in reporting.report_message(db,1,section,quote_fn=quote)
