import json
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from backend.persistence.database import Base
from backend.persistence.models import User, Account, AccountGroup, Goal, GoalSavings, Debt, Entry, SavingsRule, BotState
from backend.services import budget as service
from backend.services import management
from backend.services import reporting
from backend.services import scheduler
from backend.bot import dialogue as bot_dialogue
from backend.core.schemas import NewAccount, NewEntry, NewDebt, DebtPayment, NewGoal, GoalProgress, EditAccountGroup, BalanceCorrection, MergeAccounts, NewSavingsRule, Transfer

DAY=date(2024,1,1)

@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    @event.listens_for(engine,'connect')
    def foreign_keys(connection,_): connection.execute('PRAGMA foreign_keys=ON')
    Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as db:
        db.add_all([User(id=1,telegram_id=111,name='Alice'),User(id=2,telegram_id=222,name='Bob')]);db.commit()
        yield db


def wallet(db,kind='cash',amount='100',uid=1,currency='USD',name=None):
    return service.create_account(db,uid,NewAccount(name=name or kind,kind=kind,currency=currency,opening_balance=amount,date=DAY))


def goal(db,ids,name='Trip',uid=1):
    return service.create_goal(db,uid,NewGoal(name=name,currency='USD',target='500',savings_account_ids=ids))


def test_account_edit_correction_archive_history_and_restore(db):
    identifier=wallet(db);group=db.get(Account,identifier).group_id
    management.edit_account(db,1,group,EditAccountGroup(name='Travel cash',kind='cash'))
    assert db.get(Account,identifier).name=='Travel cash'
    with pytest.raises(service.BudgetError): management.archive_account(db,1,group,True)
    db.rollback()
    management.correct_balance(db,1,identifier,BalanceCorrection(balance='0',date=DAY,note='Fix opening balance'))
    correction=db.scalars(select(Entry).order_by(Entry.id.desc())).first()
    assert correction.kind=='adjustment' and correction.amount==-100
    assert service.monthly(db,1,'2024-01')['totals'][0]['expenses']=='0'
    management.archive_account(db,1,group,True)
    assert service.accounts(db,1)==[] and service.account_groups(db,1,include_archived=True)[0]['archived']
    with pytest.raises(service.BudgetError): service.add_entry(db,1,NewEntry(account_id=identifier,kind='income',amount='10',date=DAY))
    db.rollback()
    service.delete_transaction(db,1,correction.id)
    assert service.balance(db,identifier)==100 and not db.get(AccountGroup,group).archived


def test_archiving_preserves_historical_spending(db):
    identifier=wallet(db);group=db.get(Account,identifier).group_id
    service.add_entry(db,1,NewEntry(account_id=identifier,kind='expense',amount='100',date=DAY,category='Rent'))
    management.archive_account(db,1,group,True)
    report=reporting.monthly_report(db,1,'2024-01')
    assert report['totals'][0]['expenses']=='100'
    assert report['accounts']==[]
    management.archive_account(db,1,group,False)
    assert len(service.accounts(db,1))==1


def test_goal_follows_deposits_withdrawals_corrections_and_reversals(db):
    cash=wallet(db);saved=wallet(db,'savings','20');identifier=goal(db,[saved])
    assert service.goals(db,1)[0]['saved']=='20'
    operation=service.transfer(db,1,Transfer(source_id=cash,destination_id=saved,amount='30',date=DAY))
    assert service.goals(db,1)[0]['saved']=='50'
    service.transfer(db,1,Transfer(source_id=saved,destination_id=cash,amount='10',date=DAY))
    assert service.goals(db,1)[0]['saved']=='40'
    eid=db.scalar(select(Entry.id).where(Entry.operation_id==operation))
    service.delete_transaction(db,1,eid)
    assert service.goals(db,1)[0]['saved']=='10'
    management.correct_balance(db,1,saved,BalanceCorrection(balance='25',date=DAY))
    assert service.goals(db,1)[0]['saved']=='25'
    with pytest.raises(service.BudgetError): service.update_goal(db,1,identifier,GoalProgress(saved='500'))


def test_goal_links_ownership_currency_and_no_double_counting(db):
    saved=wallet(db,'savings');foreign=wallet(db,'savings',uid=2);ars=wallet(db,'savings',currency='ARS');cash=wallet(db)
    for invalid in (foreign,ars,cash):
        with pytest.raises(service.BudgetError): goal(db,[invalid])
        db.rollback()
    first=goal(db,[saved])
    with pytest.raises(service.BudgetError,match='another goal'): goal(db,[saved],'Second')
    db.rollback()
    assert len(service.goals(db,1))==1
    with pytest.raises(service.BudgetError): management.edit_goal(db,2,first,NewGoal(name='Other',currency='USD',target='10'))


def test_goal_edit_unlink_archive_and_restore(db):
    saved=wallet(db,'savings');identifier=goal(db,[saved])
    management.edit_goal(db,1,identifier,NewGoal(name='Holiday',currency='USD',target='200',saved='100',savings_account_ids=[]))
    assert service.goals(db,1)[0]['saved']=='100' and db.scalars(select(GoalSavings)).all()==[]
    management.edit_goal(db,1,identifier,NewGoal(name='Holiday',currency='USD',target='200',savings_account_ids=[saved]))
    management.archive_planning(db,1,Goal,identifier,True)
    assert service.goals(db,1)==[] and db.scalars(select(GoalSavings)).all()==[]
    management.archive_planning(db,1,Goal,identifier,False)
    assert service.goals(db,1)[0]['saved']=='100' and service.goals(db,1)[0]['savings_account_ids']==[]


def test_debt_edit_payment_and_archived_reversal(db):
    cash=wallet(db);identifier=service.create_debt(db,1,NewDebt(name='Loan',currency='USD',amount='50'))
    eid=service.repay_debt(db,1,identifier,DebtPayment(account_id=cash,amount='20',date=DAY))
    with pytest.raises(service.BudgetError): management.edit_debt(db,1,identifier,NewDebt(name='Loan',currency='USD',amount='10'))
    db.rollback()
    with pytest.raises(service.BudgetError): management.edit_debt(db,1,identifier,NewDebt(name='Loan',currency='EUR',amount='50'))
    db.rollback()
    management.edit_debt(db,1,identifier,NewDebt(name='Renamed loan',currency='USD',amount='60'))
    assert service.debts(db,1)[0]['remaining']=='40'
    management.archive_planning(db,1,Debt,identifier,True)
    with pytest.raises(service.BudgetError): service.repay_debt(db,1,identifier,DebtPayment(account_id=cash,amount='1',date=DAY))
    db.rollback()
    service.delete_transaction(db,1,eid)
    assert service.debts(db,1)[0]['remaining']=='60' and service.balance(db,cash)==100


def test_merging_linked_savings_preserves_goal_and_prevents_conflict(db):
    a=wallet(db,'savings','10');b=wallet(db,'savings','20');c=wallet(db,'savings','30')
    one=goal(db,[a,b]);two=goal(db,[c],'Second')
    group_a=db.get(Account,a).group_id;group_b=db.get(Account,b).group_id;group_c=db.get(Account,c).group_id
    with pytest.raises(service.BudgetError,match='different goals'): service.merge_accounts(db,1,MergeAccounts(source_id=group_a,destination_id=group_c))
    db.rollback()
    service.merge_accounts(db,1,MergeAccounts(source_id=group_a,destination_id=group_b))
    assert management.goal_saved(db,db.get(Goal,one))==30
    assert [l.account_id for l in management.goal_links(db,one)]==[b]


def test_account_type_and_archiving_respect_goal_and_rule_dependencies(db):
    cash=wallet(db);saved=wallet(db,'savings','0');identifier=goal(db,[saved]);group=db.get(Account,saved).group_id
    with pytest.raises(service.BudgetError,match='Unlink'): management.archive_account(db,1,group,True)
    db.rollback()
    with pytest.raises(service.BudgetError,match='Unlink'): management.edit_account(db,1,group,EditAccountGroup(name='Money',kind='cash'))
    db.rollback()
    management.archive_planning(db,1,Goal,identifier,True)
    rule=service.create_savings_rule(db,1,NewSavingsRule(source_id=cash,destination_id=saved,mode='fixed',amount='10'))
    management.archive_account(db,1,group,True)
    assert not db.get(SavingsRule,rule).active
    with pytest.raises(service.BudgetError): service.set_savings_rule(db,1,rule,True)
    db.rollback()
    management.archive_account(db,1,group,False)
    assert not db.get(SavingsRule,rule).active


def test_rule_edit_remove_restore_and_no_repeat_after_edit(db,monkeypatch):
    monkeypatch.setattr(service,'today',lambda:date(2024,1,10));monkeypatch.setattr(management,'today',lambda:date(2024,1,10))
    cash=wallet(db);saved=wallet(db,'savings','0')
    data=NewSavingsRule(source_id=cash,destination_id=saved,mode='fixed',amount='10',day=10)
    identifier=service.create_savings_rule(db,1,data)
    now=datetime(2024,1,10,12,tzinfo=timezone.utc)
    scheduler.run_user_jobs(db,1,now)
    assert service.balance(db,saved)==10
    data.amount=Decimal('20');management.edit_rule(db,1,identifier,data)
    scheduler.run_user_jobs(db,1,now)
    assert service.balance(db,saved)==10
    management.archive_rule(db,1,identifier,True)
    assert service.savings_rules(db,1)==[]
    management.archive_rule(db,1,identifier,False)
    assert not service.savings_rules(db,1)[0]['active']


def test_management_cross_owner_and_invalid_types(db):
    cash=wallet(db);group=db.get(Account,cash).group_id
    for fn in (lambda:management.edit_account(db,2,group,EditAccountGroup(name='Hack',kind='cash')),lambda:management.correct_balance(db,2,cash,BalanceCorrection(balance='0')),lambda:management.archive_account(db,2,group,True)):
        with pytest.raises(service.BudgetError): fn()
        db.rollback()
    with pytest.raises(service.BudgetError): management.edit_account(db,1,group,EditAccountGroup(name='Bad',kind='crypto'))
    db.rollback()
    with pytest.raises(service.BudgetError): management.correct_balance(db,1,cash,BalanceCorrection(balance='-1'))


def test_small_bot_income_expense_confirmation_back_and_home(db):
    cash=wallet(db);user=db.get(User,1)
    response=bot_dialogue.handle(db,user,'/home')
    assert response['reply_markup']['keyboard']==bot_dialogue.MENU
    for message in ['↑ Expense',f'#{cash}','10','Delivery','Skip','2024-01-01']:
        response=bot_dialogue.handle(db,user,message)
    assert 'Review expense' in response['text'] and service.balance(db,cash)==100
    bot_dialogue.handle(db,user,bot_dialogue.BACK)
    state=json.loads(db.get(BotState,1).payload)
    assert state['step']==4 and 'date' not in state['data']
    bot_dialogue.handle(db,user,'2024-01-01');bot_dialogue.handle(db,user,'Confirm')
    assert service.balance(db,cash)==90
    for message in ['↓ Income',f'#{cash}','15','Salary','Skip','2024-01-01','Confirm']: bot_dialogue.handle(db,user,message)
    assert service.balance(db,cash)==105
    bot_dialogue.handle(db,user,'↑ Expense');bot_dialogue.handle(db,user,bot_dialogue.HOME)
    assert json.loads(db.get(BotState,1).payload)=={}


def test_bot_rejects_old_management_and_discards_old_state(db):
    user=db.get(User,1)
    bot_dialogue.set_state(db,1,{'action':'debt','step':6,'data':{'name':'Old form','amount':'10','currency':'USD'}})
    for text in ('Confirm','＋ Account','Merge accounts','Daily settings','Repay debt'):
        response=bot_dialogue.handle(db,user,text)
        assert 'website' in response['text']
    assert service.accounts(db,1)==[] and service.debts(db,1)==[]
    assert json.loads(db.get(BotState,1).payload)=={}


def test_bot_current_state_only_and_scheduled_report_controls_stay_on_web(db):
    cash=wallet(db);saved=wallet(db,'savings','20');goal(db,[saved]);service.create_debt(db,1,NewDebt(name='Loan',currency='USD',amount='50'))
    user=db.get(User,1)
    before=service.balance(db,cash)
    response=bot_dialogue.handle(db,user,'Current state')
    assert 'Current state' in response['text'] and 'Loan: 50.00 USD' in response['text'] and 'Trip: 20.00 / 500.00 USD' in response['text']
    for text in ('Daily report','Weekly report','Monthly report'):
        response=bot_dialogue.handle(db,user,text)
        assert response['reply_markup']['keyboard']==bot_dialogue.MENU
        assert text not in response['text']
    assert bot_dialogue.MENU == [['↑ Expense','↓ Income'],['↔ Transfer','⇄ Exchange'],['Current state'],['Open website']]
    assert service.balance(db,cash)==before


def test_bot_duplicate_update_does_not_duplicate_expense(tmp_path,monkeypatch):
    from backend.bot import worker as bot
    from backend.services.users import find_or_create_user
    engine=create_engine('sqlite:///'+str(tmp_path/'bot.db'));Base.metadata.create_all(engine)
    with Session(engine,expire_on_commit=False) as db:
        user=find_or_create_user(db,111,'Alice');cash=wallet(db,uid=user.id)
    monkeypatch.setattr(bot,'engine',engine)
    for i,message in enumerate(['↑ Expense',f'#{cash}','10','Home','Skip','2024-01-01','Confirm'],1):
        update={'update_id':i,'message':{'chat':{'id':111,'type':'private'},'from':{'id':111,'first_name':'Alice'},'text':message}}
        bot.process_update(update);bot.process_update(update)
    with Session(engine) as db:
        assert service.balance(db,cash)==90
        assert len(db.scalars(select(Entry)).all())==2


def test_bot_handles_account_archived_mid_form(db):
    cash=wallet(db,amount='0');group=db.get(Account,cash).group_id;user=db.get(User,1)
    for message in ['↓ Income',f'#{cash}','10','Salary','Skip','2024-01-01']:bot_dialogue.handle(db,user,message)
    management.archive_account(db,1,group,True)
    response=bot_dialogue.handle(db,user,'Confirm')
    assert 'archived' in response['text'] and service.balance(db,cash)==0
    assert response['reply_markup']['keyboard']==bot_dialogue.MENU
