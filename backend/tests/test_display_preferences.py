import json
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from backend.persistence.database import Base
from backend.persistence.models import User, Account, Preferences
from backend.services import budget as service
from backend.services import reporting
from backend.services import rates
from backend.core.encryption import PREFIX
from backend.core.schemas import NewAccountGroup, NewAccount, NewEntry, NewDebt, NewGoal, ReportPreferences, CurrentStatePreferences, AccountsPagePreferences, MergeAccounts

@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as db:
        db.add_all([User(id=1,telegram_id=111,name='Alice'),User(id=2,telegram_id=222,name='Bob')]);db.commit()
        yield db


def group(db,name,kind='cash',balances=None,uid=1):
    return service.create_account_group(db,uid,NewAccountGroup(name=name,kind=kind,balances=balances or [{'currency':'USD','opening_balance':'10'}],date=date(2024,1,1)))


def quote(currency):
    values={'USD':'1','ARS':'0.001','EUR':'1.2','USDT':'1','TRX':'0.25'}
    return {'usd_rate':values[currency],'stale':False,'display_rate':f'QUOTE {currency}','source':'Test source','as_of':'2026-10-01'}


def test_current_state_groups_currencies_and_sorts_actual_usd_value(db):
    group(db,'Pesos',balances=[{'currency':'ARS','opening_balance':'20000'}])
    group(db,'Combined',balances=[{'currency':'USD','opening_balance':'15'},{'currency':'ARS','opening_balance':'10000'}])
    group(db,'Crypto','crypto',[{'currency':'USDT','opening_balance':'5'},{'currency':'TRX','opening_balance':'100'}])
    message=reporting.current_state(db,1,quote_fn=quote)
    assert message.index('Crypto:') < message.index('Combined:') < message.index('Pesos:')
    assert message.count('Combined:')==1
    assert 'Estimated balance: 75.00 USD' in message
    assert 'Combined: 25.00 USD' not in message
    assert '15.00 USD · 10000.00 ARS' in message
    assert 'Exchange rates' in message


def test_current_state_toggles_do_not_change_dashboard_or_scheduled_reports(db):
    cash=group(db,'Cash');group(db,'Reserve','savings')
    service.create_debt(db,1,NewDebt(name='Loan',currency='USD',amount='50'))
    service.create_goal(db,1,NewGoal(name='Holiday',currency='USD',target='100'))
    initial=reporting.get_preferences(db,1)
    value=CurrentStatePreferences(account_ids=[cash],include_rates=False,include_savings=False,include_debts=False,include_goals=False,include_monthly_summary=False)
    reporting.save_section(db,1,'current_state',value)
    message=reporting.current_state(db,1,quote_fn=quote)
    assert 'Cash:\n  10.00 USD' in message
    assert all(word not in message for word in ('Reserve:','Exchange rates','Debts (','Loan','Goals','Holiday','This month so far'))
    prefs=reporting.get_preferences(db,1)
    assert prefs['dashboard']==initial['dashboard'] and prefs['monthly']==initial['monthly']
    assert db.execute(text('SELECT payload FROM preferences')).scalar().startswith(PREFIX)
    reporting.save_section(db,1,'current_state',CurrentStatePreferences())
    restored=reporting.current_state(db,1,quote_fn=quote)
    assert 'Reserve:' in restored and 'Loan: 50.00 USD' in restored and 'Holiday:' in restored


def test_hiding_rate_details_keeps_conversion_and_missing_rate_warning(db):
    group(db,'Euros','debit',[{'currency':'EUR','opening_balance':'100'}]);group(db,'Cash')
    reporting.save_section(db,1,'current_state',CurrentStatePreferences(include_rates=False))
    message=reporting.current_state(db,1,quote_fn=quote)
    assert 'Euros:\n  100.00 EUR' in message and '130.00 USD' in message and 'QUOTE EUR' not in message
    message=reporting.current_state(db,1,quote_fn=lambda currency:None if currency=='EUR' else quote(currency))
    assert 'Partial balance' in message and 'Rates unavailable: EUR' in message
    assert message.index('Cash:\n  10.00 USD')<message.index('Euros:\n  100.00 EUR')


def test_manual_account_order_persists_and_new_accounts_append(db):
    one=group(db,'One');two=group(db,'Two');three=group(db,'Reserve','savings')
    reporting.save_section(db,1,'accounts_page',AccountsPagePreferences(order=[two,one,three],show_credit=False))
    assert [g['id'] for g in service.account_groups(db,1)]==[two,one,three]
    four=group(db,'New')
    assert [g['id'] for g in service.account_groups(db,1)]==[two,one,three,four]
    db.expire_all()
    assert not reporting.get_preferences(db,1)['accounts_page']['show_credit']
    assert reporting.get_preferences(db,1)['current_state']['include_debts']


def test_display_preferences_reject_foreign_accounts_and_empty_filter_is_empty(db):
    other=group(db,'Other',uid=2)
    for section,data in [('current_state',CurrentStatePreferences(account_ids=[other])),('accounts_page',AccountsPagePreferences(order=[other]))]:
        with pytest.raises(service.BudgetError): reporting.save_section(db,1,section,data)
        db.rollback()
    group(db,'Cash')
    reporting.save_section(db,1,'current_state',CurrentStatePreferences(account_ids=[]))
    assert 'No accounts included' in reporting.current_state(db,1,quote_fn=quote)
    assert service.accounts(db,1)


def test_legacy_preferences_inherit_dashboard_once_and_old_clients_keep_new_settings(db):
    cash=group(db,'Cash')
    legacy=ReportPreferences().model_dump();legacy.pop('current_state');legacy.pop('accounts_page')
    legacy['dashboard']={'include_savings':False,'account_ids':[cash]}
    db.add(Preferences(user_id=1,payload=json.dumps(legacy)));db.commit()
    prefs=reporting.get_preferences(db,1)
    assert prefs['current_state']['account_ids']==[cash] and not prefs['current_state']['include_savings']
    reporting.save_section(db,1,'current_state',CurrentStatePreferences(include_rates=False,include_debts=False))
    reporting.save_section(db,1,'accounts_page',AccountsPagePreferences(order=[cash],show_credit=False))
    reporting.save_preferences(db,1,ReportPreferences(**legacy))
    updated=reporting.get_preferences(db,1)
    assert not updated['current_state']['include_debts'] and not updated['accounts_page']['show_credit']


def test_merge_remaps_display_order_and_current_state_filter(db):
    a=group(db,'A');b=group(db,'B')
    reporting.save_section(db,1,'current_state',CurrentStatePreferences(account_ids=[a]))
    reporting.save_section(db,1,'accounts_page',AccountsPagePreferences(order=[a,b]))
    service.merge_accounts(db,1,MergeAccounts(source_id=a,destination_id=b))
    prefs=reporting.get_preferences(db,1)
    assert prefs['accounts_page']['order']==[b] and prefs['current_state']['account_ids']==[b]
    assert 'B:\n  20.00 USD' in reporting.current_state(db,1,quote_fn=quote)


def test_debit_cards_do_not_overdraw_but_existing_credit_cards_can(db):
    debit=service.create_account(db,1,NewAccount(name='Debit',kind='debit',currency='EUR',opening_balance='10'))
    credit=service.create_account(db,1,NewAccount(name='Credit',kind='card',currency='EUR',opening_balance='10'))
    with pytest.raises(service.BudgetError):service.add_entry(db,1,NewEntry(account_id=debit,kind='expense',amount='20'))
    db.rollback()
    service.add_entry(db,1,NewEntry(account_id=credit,kind='expense',amount='20'))
    assert service.balance(db,debit)==10 and service.balance(db,credit)==-10
