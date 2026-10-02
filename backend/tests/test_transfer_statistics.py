"""Per-currency incoming/outgoing movements, independent of income and expenses."""
from datetime import datetime, timezone, date
from decimal import Decimal
import pytest
from sqlalchemy import select
from backend.tests.test_budget import db, account, DAY
from backend.persistence.models import Entry, Account
from backend.core.schemas import NewEntry, Exchange, Transfer, ReportPreferences
from backend.core.money import flow_lines
from backend.services import budget, reporting, exchanges


def quote(currency):
    return {'usd_rate': '0.001' if currency == 'ARS' else '1', 'stale': False,
            'source': 'Fixture', 'display_rate': currency, 'as_of': '2024-01-31'}


def setup_flows(db, day=DAY):
    crypto = account(db, currency='USDT', kind='crypto', opening='0')
    cash = account(db, opening='0')
    ars = account(db, currency='ARS', opening='0')
    saved = account(db, kind='savings', opening='0')
    budget.add_entry(db, 1, NewEntry(account_id=crypto, kind='income', amount='2950', date=day))
    usd_exchange = exchanges.exchange(db, 1, Exchange(source_id=crypto, destination_id=cash, amount='1200', received='1200', date=day))
    ars_exchange = exchanges.exchange(db, 1, Exchange(source_id=crypto, destination_id=ars, amount='1000', received='1500000', date=day))
    budget.add_entry(db, 1, NewEntry(account_id=cash, kind='expense', amount='1180', category='Rent', date=day))
    budget.add_entry(db, 1, NewEntry(account_id=ars, kind='expense', amount='1000000', category='Grocery', date=day))
    budget.transfer(db, 1, Transfer(source_id=cash, destination_id=saved, amount='10', date=day))
    return crypto, cash, ars, saved, usd_exchange, ars_exchange


def test_statistics_exchange_and_same_currency_transfer_do_not_inflate_spending(db):
    setup_flows(db)
    prefs=ReportPreferences();prefs.monthly.include_categories=False;prefs.monthly.include_savings=True
    reporting.save_preferences(db,1,prefs)
    report=reporting.monthly_report(db,1,'2024-01')
    totals={row['currency']:row for row in report['totals']}
    assert totals['USDT']==dict(currency='USDT',income='2950',expenses='0',transfers_out='2200',transfers_in='0',surplus='2950')
    assert Decimal(totals['USD']['transfers_in'])==1210  # exchange + savings deposit
    assert Decimal(totals['USD']['transfers_out'])==10
    assert Decimal(totals['USD']['income'])==0 and Decimal(totals['USD']['expenses'])==1180
    assert Decimal(totals['ARS']['transfers_in'])==1500000
    assert Decimal(totals['ARS']['expenses'])==1000000
    assert budget.monthly(db,1,'2024-01')['totals']==report['totals']
    prefs.dashboard.include_savings=True;reporting.save_preferences(db,1,prefs)
    assert reporting.dashboard(db,1,'2024-01')['totals']==report['totals']
    assert Decimal(totals['USD']['surplus'])==-1180  # historical savings surplus keeps its meaning


def test_filters_apply_to_each_transfer_leg_and_reversal_removes_both(db):
    crypto, cash, ars, saved, _, _ = setup_flows(db)
    prefs=ReportPreferences();prefs.monthly.include_categories=False;prefs.monthly.include_savings=False
    prefs.monthly.account_ids=[db.get(Account,cash).group_id]
    reporting.save_preferences(db,1,prefs)
    row=reporting.monthly_report(db,1,'2024-01')['totals'][0]
    assert row['currency']=='USD' and Decimal(row['transfers_in'])==1200 and Decimal(row['transfers_out'])==10
    prefs.monthly.excluded_currencies=['USD'];reporting.save_preferences(db,1,prefs)
    assert reporting.monthly_report(db,1,'2024-01')['totals']==[]
    # A new exchange can be reversed without dependent spending.
    result=exchanges.exchange(db,1,Exchange(source_id=crypto,destination_id=ars,amount='1',received='1500',date=DAY))
    prefs.monthly.account_ids=None;prefs.monthly.excluded_currencies=[];reporting.save_preferences(db,1,prefs)
    before=reporting.monthly_report(db,1,'2024-01')['totals']
    leg=db.scalar(select(Entry).where(Entry.operation_id==result['operation_id']))
    budget.delete_transaction(db,1,leg.id)
    after={r['currency']:r for r in reporting.monthly_report(db,1,'2024-01')['totals']}
    assert Decimal(after['ARS']['transfers_in'])==1500000
    assert Decimal(after['USDT']['transfers_out'])==2200
    assert before!=list(after.values())


@pytest.mark.parametrize('frequency',['current_state','daily','weekly','monthly'])
def test_all_bot_report_types_include_movements_and_hide_zero_values(db,frequency):
    day=date(2024,1,31)
    setup_flows(db,day)
    prefs=ReportPreferences();config=getattr(prefs,frequency)
    config.include_categories=False;config.include_savings=False;config.include_rates=False
    reporting.save_preferences(db,1,prefs)
    if frequency=='current_state':
        message=reporting.current_state(db,1,datetime(2024,1,31,15,tzinfo=timezone.utc),quote_fn=quote)
    else:
        message=reporting.report_message(db,1,frequency,datetime(2024,2,1,15,tzinfo=timezone.utc),quote_fn=quote)
    assert 'ARS: spent 1000000.00 · received from transfers 1500000.00' in message
    assert 'USD: spent 1180.00 · transferred out 10.00 · received from transfers 1200.00' in message
    assert 'USDT: income 2950.00 · transferred out 2200.00' in message
    assert all(value not in message for value in ['spent 0.00','income 0.00','transferred out 0.00','received from transfers 0.00'])


def test_transfer_only_activity_not_reported_as_empty(db):
    source=account(db);target=account(db,opening='0')
    budget.transfer(db,1,Transfer(source_id=source,destination_id=target,amount='25',date=DAY))
    prefs=ReportPreferences();prefs.monthly.include_categories=True;reporting.save_preferences(db,1,prefs)
    report=reporting.monthly_report(db,1,'2024-01',quote_fn=quote)
    assert report['categories']==[] and report['category_totals']==[]
    assert flow_lines(report['totals'])==['USD: transferred out 25.00 · received from transfers 25.00']
    message=reporting.report_message(db,1,'monthly',datetime(2024,2,1,15,tzinfo=timezone.utc),quote_fn=quote)
    assert 'No income' not in message


def test_zero_openings_and_tiny_movements(db):
    account(db)
    assert flow_lines(budget.monthly(db,1,'2024-01')['totals'])==[]
    assert flow_lines([{'currency':'BTC','income':'0','expenses':'0','transfers_out':'0.00000001','transfers_in':'0'}])==['BTC: transferred out <0.01']
