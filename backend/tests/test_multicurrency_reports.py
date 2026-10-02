import json
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text, event
from sqlalchemy.orm import Session
from backend.persistence.database import Base
from backend.persistence.models import User, Account, AccountGroup, Entry, SavingsRule, Notification, Preferences, MarketQuote
from backend.services import budget as service
from backend.services import reporting
from backend.services import scheduler
from backend.services import rates
from backend.bot import dialogue as bot_dialogue
from backend.core.schemas import NewAccountGroup, AddCurrency, MergeAccounts, NewEntry, Transfer, NewDebt, DebtPayment, NewSavingsRule, ReportPreferences
from backend.core.encryption import PREFIX

DAY = date(2024,1,1)

@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _): connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([User(id=1,telegram_id=111,name='Alice'), User(id=2,telegram_id=222,name='Bob')]); db.commit()
        yield db


def group(db, name='Cash', kind='cash', balances=None, uid=1):
    identifier = service.create_account_group(db,uid,NewAccountGroup(name=name,kind=kind,balances=balances or [{'currency':'USD','opening_balance':'100'}],date=DAY))
    return next(g for g in service.account_groups(db,uid) if g['id']==identifier)


def test_multicurrency_creation_and_currency_validation(db):
    cash = group(db,balances=[{'currency':'USD','opening_balance':'10'},{'currency':'ARS','opening_balance':'2000'}])
    assert [b['balance'] for b in cash['balances']]==['10.000000','2000.000000']
    with pytest.raises(service.BudgetError): service.add_currency(db,1,cash['id'],AddCurrency(currency='USD'))
    db.rollback()
    with pytest.raises(service.BudgetError): service.add_currency(db,1,cash['id'],AddCurrency(currency='TRX'))
    db.rollback()
    with pytest.raises(service.BudgetError): service.add_currency(db,2,cash['id'],AddCurrency(currency='ARS'))
    db.rollback()
    with pytest.raises(service.BudgetError): group(db,balances=[{'currency':'USD'},{'currency':'USD'}])
    db.rollback()
    assert len(service.account_groups(db,1))==1


def test_merging_preserves_balances_history_rules_and_debt_reversal(db):
    one=group(db,'Cash USD'); two=group(db,'Cash',balances=[{'currency':'USD','opening_balance':'20'},{'currency':'ARS','opening_balance':'500'}]); reserve=group(db,'Reserve','savings')
    source=one['balances'][0]['id']; target=two['balances'][0]['id']
    debt=service.create_debt(db,1,NewDebt(name='Loan',currency='USD',amount='50'))
    repayment=service.repay_debt(db,1,debt,DebtPayment(account_id=source,amount='10',date=DAY))
    rule=service.create_savings_rule(db,1,NewSavingsRule(source_id=source,destination_id=reserve['balances'][0]['id'],mode='fixed',amount='5',day=10))
    prefs=ReportPreferences();prefs.daily.account_ids=[one['id']];reporting.save_preferences(db,1,prefs)
    operation=service.transfer(db,1,Transfer(source_id=source,destination_id=target,amount='5',date=DAY))
    service.merge_accounts(db,1,MergeAccounts(source_id=one['id'],destination_id=two['id']))
    assert db.get(Account,source) is None
    assert db.get(SavingsRule,rule).source_id==target
    assert service.balance(db,target)==110
    assert reporting.get_preferences(db,1)['daily']['account_ids']==[two['id']]
    service.delete_transaction(db,1,repayment)
    assert service.balance(db,target)==120 and service.debts(db,1)[0]['remaining']=='50'
    transfer_id=db.scalar(select(Entry.id).where(Entry.operation_id==operation))
    service.delete_transaction(db,1,transfer_id)
    assert service.balance(db,target)==120  # both former sides now in the same wallet
    assert len(service.account_groups(db,1))==2


def test_merge_moves_other_currency_and_rejects_cross_owner_or_type(db):
    one=group(db,'Pesos',balances=[{'currency':'ARS','opening_balance':'250'}]);two=group(db)
    foreign=group(db,uid=2);savings=group(db,'Reserve','savings')
    for target in (foreign['id'], savings['id'], one['id']):
        with pytest.raises(service.BudgetError): service.merge_accounts(db,1,MergeAccounts(source_id=one['id'],destination_id=target))
        db.rollback()
    wallet=one['balances'][0]['id']
    service.merge_accounts(db,1,MergeAccounts(source_id=one['id'],destination_id=two['id']))
    assert db.get(Account,wallet).name=='Cash' and db.get(Account,wallet).group_id==two['id']
    assert service.balance(db,wallet)==250


def test_account_selection_savings_categories_and_dashboard(db):
    cash=group(db);savings=group(db,'Reserve','savings');other=group(db,'Other')
    for g,amount in [(cash,'10'),(savings,'20'),(other,'30')]:
        service.add_entry(db,1,NewEntry(account_id=g['balances'][0]['id'],kind='expense',amount=amount,date=DAY,category='Grocery'))
    prefs=ReportPreferences();prefs.monthly.account_ids=[cash['id'],savings['id']];prefs.monthly.include_savings=False;prefs.dashboard=prefs.monthly.model_copy()
    reporting.save_preferences(db,1,prefs)
    report=reporting.monthly_report(db,1,'2024-01')
    assert report['totals'][0]['expenses']=='10' and report['categories'][0]['amount']=='10'
    assert reporting.dashboard(db,1,'2024-01')['totals'][0]['expenses']=='10'
    prefs.monthly.include_categories=False;prefs.monthly.include_savings=True
    reporting.save_preferences(db,1,prefs)
    report=reporting.monthly_report(db,1,'2024-01')
    assert report['totals'][0]['expenses']=='30' and report['categories']==[]
    prefs.monthly.account_ids=[];reporting.save_preferences(db,1,prefs)
    assert reporting.monthly_report(db,1,'2024-01')['totals']==[]


def test_preferences_encrypted_and_validated(db):
    foreign=group(db,uid=2)
    prefs=ReportPreferences();prefs.daily.account_ids=[foreign['id']]
    with pytest.raises(service.BudgetError): reporting.save_preferences(db,1,prefs)
    db.rollback()
    for invalid in ({'timezone':'Bad/Zone'}, {'daily':{'time':'25:00'}}, {'weekly':{'weekday':7}}):
        with pytest.raises(ValidationError): ReportPreferences(**invalid)
    reporting.save_preferences(db,1,ReportPreferences())
    assert db.execute(text('SELECT payload FROM preferences')).scalar().startswith(PREFIX)


def test_daily_default_local_time_and_deduplication(db):
    group(db)
    assert list(reporting.due_reports(db,1,datetime(2024,2,2,12,14,tzinfo=timezone.utc)))==[('monthly','2024-02-01')]
    # Save an explicitly disabled monthly schedule, so only daily is due.
    prefs=ReportPreferences();prefs.monthly.enabled=False;reporting.save_preferences(db,1,prefs)
    before=datetime(2024,2,2,12,14,tzinfo=timezone.utc)
    scheduler.run_user_jobs(db,1,before)
    assert db.scalars(select(Notification)).all()==[]
    for minute in (15,16,17): scheduler.run_user_jobs(db,1,before.replace(minute=minute))
    rows=db.scalars(select(Notification)).all()
    assert len(rows)==1 and '09:15' in rows[0].payload and '100.00 USD' in rows[0].payload
    assert '2024-02-01 to 2024-02-01' in rows[0].payload


def test_weekly_monthly_custom_days_and_timezone_dst(db):
    prefs=ReportPreferences(timezone='America/New_York');prefs.daily.enabled=False;prefs.weekly.enabled=True;prefs.weekly.weekday=6;prefs.weekly.time='09:15';prefs.monthly.month_day=31
    reporting.save_preferences(db,1,prefs)
    assert list(reporting.due_reports(db,1,datetime(2024,3,10,13,14,tzinfo=timezone.utc)))==[]
    assert list(reporting.due_reports(db,1,datetime(2024,3,10,13,15,tzinfo=timezone.utc)))==[('weekly','2024-03-10')]
    assert list(reporting.due_reports(db,1,datetime(2024,2,29,14,tzinfo=timezone.utc)))==[('monthly','2024-02-29')]
    assert list(reporting.due_reports(db,1,datetime(2024,3,11,14,tzinfo=timezone.utc)))==[]


def test_reports_daily_yesterday_weekly_seven_days_monthly_previous_month(db):
    cash=group(db)
    for day in (date(2024,1,24),date(2024,1,25),date(2024,1,31),date(2024,2,1)):
        service.add_entry(db,1,NewEntry(account_id=cash['balances'][0]['id'],kind='expense',amount='5',date=day,category='Delivery'))
    now=datetime(2024,2,1,12,15,tzinfo=timezone.utc)
    prefs=ReportPreferences();prefs.daily.include_categories=True;reporting.save_preferences(db,1,prefs)
    assert 'Delivery: 5.00 USD' in reporting.report_message(db,1,'daily',now)
    assert 'Delivery: 10.00 USD' in reporting.report_message(db,1,'weekly',now)
    assert 'Delivery: 15.00 USD' in reporting.report_message(db,1,'monthly',now)


def test_trx_refresh_at_ten_persistent_once_per_local_day_and_retry(db):
    calls=[]
    now=datetime(2024,2,1,12,59,tzinfo=timezone.utc)
    def fetch(currency):
        calls.append(currency)
        return {'usd_rate':'0.25','as_of':now.isoformat(),'source':'Test','display_rate':'1 TRX = 0.25 USD'}
    rates.refresh_trx(db,now=now,fetch_fn=fetch)
    assert len(calls)==1  # initial quote
    now=now+timedelta(minutes=1)
    rates.refresh_trx(db,now=now,fetch_fn=fetch)
    assert len(calls)==1  # recent quote, wait for minimum provider interval
    now=now+timedelta(minutes=5)
    rates.refresh_trx(db,now=now,fetch_fn=fetch)
    assert len(calls)==2
    for _ in range(3): rates.refresh_trx(db,now=now+timedelta(hours=1),fetch_fn=fetch)
    assert len(calls)==2
    row=db.get(MarketQuote,'TRX');assert json.loads(row.payload)['days']['America/Argentina/Buenos_Aires']=='2024-02-01'
    now=now+timedelta(days=1)
    def fail(c): calls.append(c);raise ValueError('offline')
    rates.refresh_trx(db,now=now,fetch_fn=fail)
    rates.refresh_trx(db,now=now+timedelta(minutes=1),fetch_fn=fail)
    assert len(calls)==3 and json.loads(row.payload)['quote']['usd_rate']=='0.25'
    rates.refresh_trx(db,now=now+timedelta(minutes=6),fetch_fn=fetch)
    assert len(calls)==4




def test_v3_migration_keeps_encrypted_account_and_entry_ids():
    from backend.persistence.migrations import migrate
    from backend.core.encryption import encrypt, identity_key
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE schema_versions (version INTEGER PRIMARY KEY, key_check TEXT NOT NULL)'))
        conn.execute(text('INSERT INTO schema_versions VALUES (3, :check)'),{'check':encrypt('pocket-encryption-check:'+identity_key(0))})
        conn.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id TEXT, telegram_key VARCHAR(64), name TEXT)'))
        conn.execute(text('INSERT INTO users VALUES (1,:tid,:key,:name)'),{'tid':encrypt('111'),'key':identity_key(111),'name':encrypt('Alice')})
        conn.execute(text('CREATE TABLE accounts (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, kind TEXT, currency TEXT)'))
        conn.execute(text('INSERT INTO accounts VALUES (7,1,:name,:kind,:currency)'),{'name':encrypt('Old cash'),'kind':encrypt('cash'),'currency':encrypt('ARS')})
    migrate(engine);migrate(engine)
    with Session(engine) as db:
        account=db.get(Account,7)
        assert account.name=='Old cash' and account.currency=='ARS'
        assert db.get(AccountGroup,account.group_id).name=='Old cash'
        assert len(service.account_groups(db,1))==1
        assert db.execute(text('SELECT name FROM account_groups')).scalar().startswith(PREFIX)


def test_monthly_notifications_use_users_local_month(db):
    prefs=ReportPreferences(timezone='Asia/Tokyo');prefs.daily.enabled=False;prefs.monthly.time='00:15'
    reporting.save_preferences(db,1,prefs)
    now=datetime(2024,1,31,15,15,tzinfo=timezone.utc)  # Feb 1 in Tokyo; Jan 31 Buenos Aires
    scheduler.run_user_jobs(db,1,now)
    scheduler.run_user_jobs(db,1,now+timedelta(hours=16))
    rows=db.scalars(select(Notification)).all()
    assert len(rows)==1 and '2024-01-01 to 2024-01-31' in rows[0].payload


