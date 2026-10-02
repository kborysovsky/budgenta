from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from backend.persistence.database import Base
from backend.persistence.models import User, Entry, Debt, SavingsRule, SavingsRun, Notification, ReportSettings, BotState
from backend.services import budget as service
from backend.services import scheduler
from backend.bot import dialogue as bot_dialogue
from backend.core.schemas import NewAccount, NewEntry, Transfer, NewDebt, DebtPayment, NewSavingsRule, SavingsMove

@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as db:
        db.add_all([User(id=1,telegram_id=1001,name='Alice'),User(id=2,telegram_id=1002,name='Bob')]);db.commit()
        yield db

DAY=date(2024,1,1)
def account(db,name='Cash',kind='cash',opening='1000',currency='USD'):
    return service.create_account(db,1,NewAccount(name=name,kind=kind,currency=currency,opening_balance=opening,date=DAY))

def entry(db,identifier,amount,kind='expense'):
    return service.add_entry(db,1,NewEntry(account_id=identifier,amount=amount,kind=kind,date=DAY,category='Grocery'))

def test_delete_debt_payment_restores_balance_debt_and_report_once(db):
    cash=account(db)
    debt=service.create_debt(db,1,NewDebt(name='Loan',currency='USD',amount='500'))
    identifier=service.repay_debt(db,1,debt,DebtPayment(account_id=cash,amount='100',date=DAY))
    assert service.balance(db,cash)==Decimal('900')
    service.close_month(db,1,'2024-01')
    service.delete_transaction(db,1,identifier)
    service.delete_transaction(db,1,identifier)
    assert service.balance(db,cash)==Decimal('1000')
    assert db.get(Debt,debt).paid==0
    assert service.expense_report(db,1,'2024-01')['categories']==[]
    assert db.get(Entry,identifier).deleted


def test_delete_transfer_from_either_side_and_ownership(db):
    cash=account(db); savings=account(db,'Savings','savings','0')
    operation=service.transfer(db,1,Transfer(source_id=cash,destination_id=savings,amount='100',date=DAY))
    rows=db.scalars(select(Entry).where(Entry.operation_id==operation).order_by(Entry.id)).all()
    with pytest.raises(service.BudgetError): service.delete_transaction(db,2,rows[0].id)
    db.rollback()
    service.delete_transaction(db,1,rows[1].id)
    assert service.balance(db,cash)==1000 and service.balance(db,savings)==0
    assert all(db.get(Entry,e.id).deleted for e in rows)


def test_cannot_undo_money_already_spent_but_can_undo_dependents(db):
    cash=account(db); savings=account(db,'Savings','savings','0')
    operation=service.transfer(db,1,Transfer(source_id=cash,destination_id=savings,amount='100',date=DAY))
    identifier=db.scalar(select(Entry.id).where(Entry.operation_id==operation))
    expense=entry(db,savings,'20')
    with pytest.raises(service.BudgetError,match='dependent'):
        service.delete_transaction(db,1,identifier)
    db.rollback()
    assert service.balance(db,cash)==900 and service.balance(db,savings)==80
    service.delete_transaction(db,1,expense)
    service.delete_transaction(db,1,identifier)
    assert service.balance(db,cash)==1000 and service.balance(db,savings)==0


def test_savings_deposit_withdraw_and_sweep_do_not_count_as_spending(db):
    cash=account(db); savings=account(db,'Reserve','savings','0')
    service.move_savings(db,1,SavingsMove(source_id=cash,destination_id=savings,amount='100',date=DAY))
    service.move_savings(db,1,SavingsMove(source_id=savings,destination_id=cash,amount='40',date=DAY))
    assert service.balance(db,cash)==940 and service.balance(db,savings)==60
    service.move_savings(db,1,SavingsMove(source_id=cash,destination_id=savings,mode='remainder',date=DAY))
    assert service.balance(db,cash)==0 and service.balance(db,savings)==1000
    assert Decimal(service.monthly(db,1,'2024-01')['totals'][0]['expenses'])==0


def test_monthly_fixed_rule_is_idempotent_and_delete_does_not_rerun(db,monkeypatch):
    monkeypatch.setattr(service,'today',lambda:date(2024,1,10))
    cash=account(db); savings=account(db,'Reserve','savings','0')
    rule=service.create_savings_rule(db,1,NewSavingsRule(source_id=cash,destination_id=savings,mode='fixed',amount='100',day=10))
    now=datetime(2024,1,10,12,0,tzinfo=timezone.utc)  # 09:00 Buenos Aires
    for _ in range(3): scheduler.run_user_jobs(db,1,now)
    assert service.balance(db,savings)==100
    assert len(db.scalars(select(SavingsRun)).all())==1
    run=db.scalar(select(SavingsRun))
    identifier=db.scalar(select(Entry.id).where(Entry.operation_id==run.operation_id))
    service.delete_transaction(db,1,identifier)
    scheduler.run_user_jobs(db,1,now)
    assert service.balance(db,savings)==0
    assert db.get(SavingsRule,rule).next_run==date(2024,2,10)
    assert 'reversed' in service.savings_rules(db,1)[0]['recent_runs'][0]['result']


def test_insufficient_funds_skip_and_short_month_day_clamp(db,monkeypatch):
    monkeypatch.setattr(service,'today',lambda:date(2024,2,1))
    cash=account(db,opening='50'); savings=account(db,'Reserve','savings','0')
    rule=service.create_savings_rule(db,1,NewSavingsRule(source_id=cash,destination_id=savings,mode='fixed',amount='100',day=31))
    assert db.get(SavingsRule,rule).next_run==date(2024,2,29)
    monkeypatch.setattr(service,'today',lambda:date(2024,2,29))
    scheduler.run_user_jobs(db,1,datetime(2024,2,29,12,tzinfo=timezone.utc))
    assert service.balance(db,cash)==50 and service.balance(db,savings)==0
    assert 'Skipped' in db.scalar(select(SavingsRun)).result
    assert db.get(SavingsRule,rule).next_run==date(2024,3,31)


def test_month_end_sweep_waits_until_2359_and_catches_up_next_day(db,monkeypatch):
    monkeypatch.setattr(service,'today',lambda:date(2024,1,1))
    cash=account(db); savings=account(db,'Reserve','savings','0')
    service.create_savings_rule(db,1,NewSavingsRule(source_id=cash,destination_id=savings,mode='remainder',day=0))
    monkeypatch.setattr(service,'today',lambda:date(2024,1,31))
    scheduler.run_user_jobs(db,1,datetime(2024,2,1,2,58,tzinfo=timezone.utc))
    assert service.balance(db,savings)==0
    monkeypatch.setattr(service,'today',lambda:date(2024,2,1))
    scheduler.run_user_jobs(db,1,datetime(2024,2,1,3,1,tzinfo=timezone.utc))
    assert service.balance(db,savings)==1000


def test_report_once_on_first_at_local_nine_and_expense_categories(db):
    cash=account(db)
    entry(db,cash,'25')
    # Pref persisted during the prior month.
    scheduler.settings(db,1,date(2024,1,15));db.commit()
    scheduler.run_user_jobs(db,1,datetime(2024,2,1,11,59,tzinfo=timezone.utc))
    assert len(db.scalars(select(Notification)).all())==0
    scheduler.run_user_jobs(db,1,datetime(2024,2,1,12,0,tzinfo=timezone.utc))
    scheduler.run_user_jobs(db,1,datetime(2024,2,1,12,1,tzinfo=timezone.utc))
    rows=db.scalars(select(Notification)).all()
    assert len(rows)==1
    assert '2024-01' in rows[0].payload and 'Grocery: 25.00 USD' in rows[0].payload
    assert db.get(ReportSettings,1).next_report==date(2024,3,1)


def test_paused_rules_and_disabled_reports_do_not_run(db,monkeypatch):
    monkeypatch.setattr(service,'today',lambda:date(2024,1,1))
    cash=account(db); savings=account(db,'Reserve','savings','0')
    rule=service.create_savings_rule(db,1,NewSavingsRule(source_id=cash,destination_id=savings,mode='fixed',amount='100',day=1))
    service.set_savings_rule(db,1,rule,False)
    scheduler.set_reports(db,1,False)
    scheduler.run_user_jobs(db,1,datetime(2024,1,1,12,tzinfo=timezone.utc))
    assert service.balance(db,savings)==0 and db.scalars(select(Notification)).all()==[]






def test_debts_category_is_not_treated_as_menu_navigation(db):
    cash=account(db)
    user=db.get(User,1)
    for message in ['↑ Expense',f'#{cash}','10','Debts','Skip','2024-01-01','Confirm']:
        response=bot_dialogue.handle(db,user,message)
    assert response['text'].startswith('Saved')
    assert service.balance(db,cash)==990


def test_legacy_links_backfill_and_reversal():
    from backend.persistence.migrations import backfill_links
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as db:
        db.add(User(id=1,telegram_id=100,name='Legacy'));db.commit()
        cash=account(db); reserve=account(db,'Reserve','savings','0')
        debt=Debt(user_id=1,name='Old loan',currency='USD',amount=Decimal(100),paid=Decimal(30));db.add(debt);db.flush()
        outgoing=Entry(account_id=cash,kind='transfer',amount=Decimal(-25),date=DAY,category='Transfer',note='Transfer with Reserve')
        incoming=Entry(account_id=reserve,kind='transfer',amount=Decimal(25),date=DAY,category='Transfer',note='Transfer with Cash')
        repayment=Entry(account_id=cash,kind='expense',amount=Decimal(-30),date=DAY,category='Debts',note='Repayment: Old loan')
        db.add_all([outgoing,incoming,repayment]);db.commit()
        ids=(outgoing.id,incoming.id,repayment.id,debt.id)
    with engine.begin() as conn: backfill_links(conn)
    with Session(engine) as db:
        out,inc,payment=(db.get(Entry,i) for i in ids[:3])
        assert out.operation_id==inc.operation_id
        assert payment.debt_id==ids[3]
        service.delete_transaction(db,1,payment.id)
        service.delete_transaction(db,1,inc.id)
        assert db.get(Debt,ids[3]).paid==0
        assert service.balance(db,cash)==1000 and service.balance(db,reserve)==0
