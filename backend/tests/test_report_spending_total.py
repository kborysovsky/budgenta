from datetime import date, datetime, timezone
import pytest
from backend.tests.test_budget import db, account
from backend.core.schemas import NewEntry, ReportPreferences, Transfer, BalanceCorrection
from backend.services import budget, reporting, management

NOW = datetime(2024, 2, 1, 12, tzinfo=timezone.utc)


def quote(currency):
    return dict(usd_rate={'USD':'1', 'EUR':'2', 'ARS':'.001'}[currency], stale=False,
                source='Test', as_of='2024-01-31', display_rate=currency)


def spend(db, wallet, amount, day, uid=1):
    return budget.add_entry(db, uid, NewEntry(account_id=wallet, kind='expense', amount=amount, date=day))


@pytest.mark.parametrize('frequency,total,start', [('daily','20.00','2024-01-31'),('weekly','26.00','2024-01-25'),('monthly','34.00','2024-01-01')])
@pytest.mark.parametrize('details', [True, False])
def test_spending_immediately_after_balance_in_usd_with_correct_period(db,frequency,total,start,details):
    cash=account(db,opening='1000');eur=account(db,currency='EUR',opening='1000')
    spend(db,cash,'10',date(2024,1,31));spend(db,eur,'5',date(2024,1,31))
    spend(db,eur,'3',date(2024,1,25));spend(db,eur,'4',date(2024,1,24))
    spend(db,cash,'100',date(2023,12,31));spend(db,cash,'100',date(2024,2,1))
    prefs=ReportPreferences(main_currency='EUR');config=getattr(prefs,frequency)
    config.include_categories=details;config.include_rates=details
    reporting.save_preferences(db,1,prefs)
    calls=[]
    def quotes(currency): calls.append(currency);return quote(currency)
    lines=reporting.report_message(db,1,frequency,now=NOW,quote_fn=quotes).splitlines()
    assert lines[1].startswith('Estimated balance:') and 'EUR' in lines[1]
    assert lines[2]==f'Total spending: {total} USD (estimated) · {start} to 2024-01-31'
    assert all(calls.count(currency)==1 for currency in set(calls))


def test_spending_honors_filters_and_only_live_expenses(db):
    cash=account(db,opening='1000');other=account(db);saved=account(db,kind='savings');eur=account(db,currency='EUR');foreign=account(db,user=2)
    day=date(2024,1,31)
    spend(db,cash,'10',day);mistake=spend(db,cash,'50',day);budget.delete_transaction(db,1,mistake)
    for wallet in (other,saved,eur):spend(db,wallet,'20',day)
    spend(db,foreign,'30',day,uid=2)
    budget.transfer(db,1,Transfer(source_id=cash,destination_id=other,amount='20',date=day))
    budget.add_entry(db,1,NewEntry(account_id=cash,kind='income',amount='100',date=day))
    management.correct_balance(db,1,cash,BalanceCorrection(balance='1000',date=day))
    prefs=ReportPreferences();prefs.monthly.include_categories=False;prefs.monthly.include_rates=False
    prefs.monthly.include_savings=False;prefs.monthly.excluded_currencies=['EUR']
    prefs.monthly.account_ids=[a['group_id'] for a in budget.accounts(db,1) if a['id']!=other]
    reporting.save_preferences(db,1,prefs)
    assert reporting.report_message(db,1,'monthly',now=NOW,quote_fn=quote).splitlines()[2].startswith('Total spending: 10.00 USD')
    prefs.monthly.account_ids=[];reporting.save_preferences(db,1,prefs)
    assert reporting.report_message(db,1,'monthly',now=NOW,quote_fn=quote).splitlines()[2].startswith('Total spending: 0.00 USD')


def test_spending_missing_or_stale_rate_even_when_spent_account_is_empty(db):
    eur=account(db,currency='EUR',opening='10');spend(db,eur,'10',date(2024,1,31))
    prefs=ReportPreferences();prefs.daily.include_categories=False;prefs.daily.include_rates=False
    reporting.save_preferences(db,1,prefs)
    missing=reporting.report_message(db,1,'daily',now=NOW,quote_fn=lambda c: None if c=='EUR' else quote(c)).splitlines()
    assert missing[2]=='Total spending unavailable in USD · 2024-01-31 to 2024-01-31. Missing rates: EUR.'
    stale=reporting.report_message(db,1,'daily',now=NOW,quote_fn=lambda c:{**quote(c),'stale':True}).splitlines()
    assert stale[2].startswith('Total spending: 20.00 USD')
    assert stale[3]=='Spending uses cached exchange rates; estimate may be out of date.'


@pytest.mark.parametrize('language,expected',[('ru','Всего расходов:'),('uk','Усього витрат:'),('es','Gasto total:')])
def test_spending_translations(db,language,expected):
    reporting.save_language(db,1,language)
    assert reporting.report_message(db,1,'monthly',now=NOW,quote_fn=quote).splitlines()[2].startswith(expected+' 0.00 USD')


@pytest.mark.parametrize('details', [True, False])
def test_current_state_spending_month_to_date_and_filters(db, details):
    now=datetime(2024,2,1,1,tzinfo=timezone.utc)  # Still January 31 in Buenos Aires.
    cash=account(db,opening='1000');eur=account(db,currency='EUR',opening='1000')
    saved=account(db,kind='savings',opening='1000');foreign=account(db,user=2,opening='1000')
    spend(db,cash,'10',date(2024,1,1));spend(db,eur,'5',date(2024,1,31))
    spend(db,cash,'99',date(2023,12,31));spend(db,cash,'99',date(2024,2,1))
    spend(db,saved,'200',date(2024,1,31));spend(db,foreign,'300',date(2024,1,31),uid=2)
    mistaken=spend(db,cash,'50',date(2024,1,31));budget.delete_transaction(db,1,mistaken)
    prefs=ReportPreferences(main_currency='EUR');config=prefs.current_state
    config.include_monthly_summary=details;config.include_categories=details;config.include_rates=details
    config.include_savings=False
    reporting.save_preferences(db,1,prefs)
    lines=reporting.current_state(db,1,now=now,quote_fn=quote).splitlines()
    assert lines[1].startswith('Estimated balance:') and 'EUR' in lines[1]
    assert lines[2]=='Total spending: 20.00 USD (estimated) · 2024-01-01 to 2024-01-31'
    assert ('This month so far' in lines)==details
    prefs.current_state.excluded_currencies=['EUR'];reporting.save_preferences(db,1,prefs)
    assert 'Total spending: 10.00 USD' in reporting.current_state(db,1,now=now,quote_fn=quote)
    prefs.current_state.account_ids=[];reporting.save_preferences(db,1,prefs)
    assert 'Total spending: 0.00 USD' in reporting.current_state(db,1,now=now,quote_fn=quote)


def test_current_state_missing_and_stale_spending_rates(db):
    wallet=account(db,currency='EUR',opening='10')
    spend(db,wallet,'10',date(2024,1,31))  # Zero remaining balance still needs an expense quote.
    now=datetime(2024,1,31,18,tzinfo=timezone.utc)
    message=reporting.current_state(db,1,now=now,quote_fn=lambda c: None if c=='EUR' else quote(c))
    assert 'Total spending unavailable in USD' in message and 'Missing rates: EUR.' in message
    message=reporting.current_state(db,1,now=now,quote_fn=lambda c: {**quote(c),'stale':True})
    assert 'Total spending: 20.00 USD' in message and 'Spending uses cached exchange rates' in message


def test_monthly_api_and_exports_total_independent_of_category_details(db):
    from backend.services import monthly_export
    cash=account(db,opening='1000');eur=account(db,currency='EUR',opening='1000')
    spend(db,cash,'10',date(2024,1,31));spend(db,eur,'5',date(2024,1,31))
    prefs=ReportPreferences();prefs.monthly.include_categories=False;prefs.monthly.include_rates=False
    reporting.save_preferences(db,1,prefs)
    report=reporting.monthly_report(db,1,'2024-01',quote_fn=quote)
    assert not report['category_totals'] and report['spending_valuation']['total_usd']=='20.00'
    tables=monthly_export.monthly_tables(db,1,'2024-01',quote_fn=quote)
    info=next(t for t in tables if t['name']=='Report information')
    assert dict(info['rows'])['Total spending (USD, estimated)']==20
    assert not any(t['name']=='Spending by category' for t in tables)
    missing=monthly_export.monthly_tables(db,1,'2024-01',quote_fn=lambda c: None if c=='EUR' else quote(c))
    info=dict(next(t['rows'] for t in missing if t['name']=='Report information'))
    assert info['Total spending (USD, estimated)'] is None and info['Missing exchange rates']=='EUR'
