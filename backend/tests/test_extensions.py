import json
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from fastapi import Response, HTTPException
from backend.persistence.database import Base
from backend.persistence.models import User, Account, Entry, Debt, Goal, LoginChallenge
from backend.core.encryption import decrypt, encrypt, identity_key, PREFIX
from backend.persistence.migrations import migrate
from backend.services import budget as service
from backend.services import rates
from backend.web import login_flow
from backend.bot import dialogue as bot_dialogue
from backend.core.schemas import NewAccount, NewDebt, DebtPayment, NewGoal, GoalProgress

@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([User(id=1,telegram_id=111,name='Alice'),User(id=2,telegram_id=222,name='Bob')]); db.commit()
        yield db


def test_raw_financial_fields_are_encrypted(db):
    account=service.create_account(db,1,NewAccount(name='Secret wallet',kind='cash',currency='USD',opening_balance='123.45'))
    debt=service.create_debt(db,1,NewDebt(name='Secret creditor',currency='USD',amount='10',note='Private note'))
    raw=db.execute(text('SELECT name, currency, kind FROM accounts WHERE id=:id'),{'id':account}).one()
    assert all(v.startswith(PREFIX) for v in raw)
    raw=db.execute(text('SELECT amount, date, category FROM entries WHERE account_id=:id'),{'id':account}).one()
    assert all(v.startswith(PREFIX) for v in raw)
    raw=db.execute(text('SELECT name, telegram_id FROM users WHERE id=1')).one()
    assert all(v.startswith(PREFIX) for v in raw)
    assert service.accounts(db,1)[0]['name']=='Secret wallet'
    assert db.get(Debt,debt).note=='Private note'
    assert encrypt('same') != encrypt('same')


def test_wrong_key_fails_closed(monkeypatch):
    value=encrypt('sensitive')
    monkeypatch.setenv('DATA_ENCRYPTION_KEYS',Fernet.generate_key().decode())
    with pytest.raises(InvalidToken): decrypt(value)
    with pytest.raises(RuntimeError): decrypt('plaintext')


def test_debt_repayment_is_expense_and_isolated(db):
    account=service.create_account(db,1,NewAccount(name='Cash',kind='cash',currency='USD',opening_balance='100'))
    debt=service.create_debt(db,1,NewDebt(name='Loan',currency='USD',amount='60'))
    with pytest.raises(service.BudgetError,match='not found'):
        service.repay_debt(db,2,debt,DebtPayment(account_id=account,amount='1'))
    db.rollback()
    service.repay_debt(db,1,debt,DebtPayment(account_id=account,amount='20'))
    assert service.balance(db,account)==Decimal('80')
    assert service.debts(db,1)[0]['remaining']=='40'
    report=service.monthly(db,1,date.today().strftime('%Y-%m'))
    assert report['transactions'][0]['category']=='Debts'
    with pytest.raises(service.BudgetError,match='exceeds'):
        service.repay_debt(db,1,debt,DebtPayment(account_id=account,amount='41'))
    db.rollback()
    assert service.balance(db,account)==Decimal('80')
    assert service.debts(db,2)==[]


def test_goal_progress_no_fake_income_and_ownership(db):
    goal=service.create_goal(db,1,NewGoal(name='Trip',currency='USD',target='500',saved='10'))
    service.update_goal(db,1,goal,GoalProgress(saved='120'))
    assert service.goals(db,1)[0]['saved']=='120'
    assert service.accounts(db,1)==[]
    with pytest.raises(service.BudgetError): service.update_goal(db,2,goal,GoalProgress(saved='1'))
    assert service.goals(db,2)==[]


def test_conversion_divides_blue_venta_and_multiplies_eur():
    values={'USD':'1','ARS':'0.001','EUR':'1.2','USDT':'0.999','TRX':'0.25'}
    accounts=[{'id':i,'name':c,'currency':c,'balance':v} for i,(c,v) in enumerate([('USD','10'),('ARS','2000'),('EUR','5'),('USDT','1'),('TRX','4')])]
    result=rates.valuation(accounts,lambda c:{'usd_rate':values[c],'stale':False})
    assert result['total_usd']=='20.00'
    assert result['complete']
    partial=rates.valuation(accounts,lambda c:None if c=='ARS' else {'usd_rate':values[c],'stale':False})
    assert not partial['complete'] and partial['missing']==['ARS']
    assert partial['total_usd']=='18.00'


def test_rate_failure_uses_flagged_cache_then_excludes(monkeypatch):
    import time
    monkeypatch.setattr(rates,'_CACHE',{'EUR':(time.time()-600,{'usd_rate':'1.1'})})
    def unavailable(currency): raise ValueError('offline')
    monkeypatch.setattr(rates,'fetch_quote',unavailable)
    assert rates.quote('EUR')['stale']
    monkeypatch.setattr(rates,'_CACHE',{})
    assert rates.quote('EUR') is None


def test_login_challenge_is_browser_bound_and_one_use(db, monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_USERNAME','example_bot')
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN','test-only')
    response=Response()
    info=login_flow.start(db,response)
    cookie=response.headers['set-cookie'].split(';')[0].split('=',1)[1]
    request=SimpleNamespace(cookies={login_flow.COOKIE:cookie})
    identifier=cookie.split('.')[0]
    assert info['url'].endswith('login_'+identifier)
    assert login_flow.status(db,request)['approved'] is False
    with pytest.raises(HTTPException): login_flow.complete(db,request,Response())
    db.rollback()
    assert login_flow.approve(db,identifier,1)
    assert not login_flow.approve(db,identifier,2)
    assert login_flow.status(db,request)['name']=='Alice'
    wrong=SimpleNamespace(cookies={login_flow.COOKIE:identifier+'.wrong'})
    with pytest.raises(HTTPException): login_flow.status(db,wrong)
    db.rollback()
    assert login_flow.complete(db,request,Response())['name']=='Alice'
    with pytest.raises(HTTPException): login_flow.complete(db,request,Response())


def test_expired_challenge_rejected(db):
    db.add(LoginChallenge(id='expired',browser_key='key',expires_at=login_flow.now()-timedelta(minutes=1))); db.commit()
    assert not login_flow.approve(db,'expired',1)




def test_legacy_plaintext_migration_preserves_values_and_is_idempotent():
    engine=create_engine('sqlite://')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id BIGINT NOT NULL UNIQUE, name VARCHAR(120) NOT NULL)'))
        c.execute(text("INSERT INTO users VALUES (1, 765432, 'Original user')"))
        c.execute(text('CREATE TABLE accounts (id INTEGER PRIMARY KEY, user_id INTEGER, name VARCHAR(80), kind VARCHAR(16), currency VARCHAR(8))'))
        c.execute(text("INSERT INTO accounts VALUES (1,1,'Old cash','cash','USD')"))
        c.execute(text('CREATE TABLE entries (id INTEGER PRIMARY KEY, account_id INTEGER, kind VARCHAR(16), amount NUMERIC(24,6), date DATE, category VARCHAR(60), note VARCHAR(300))'))
        c.execute(text("INSERT INTO entries VALUES (1,1,'opening',123.45,'2024-01-01','Opening balance','Keep this')"))
    migrate(engine); migrate(engine)
    with Session(engine) as db:
        assert service.accounts(db,1)[0]['balance']=='123.450000'
        assert db.scalar(select(User).where(User.telegram_key==identity_key(765432))).name=='Original user'
        assert db.execute(text('SELECT note FROM entries')).scalar().startswith(PREFIX)








def test_wrong_identity_hash_key_blocks_migration_startup(monkeypatch):
    engine=create_engine('sqlite://')
    migrate(engine)
    monkeypatch.setenv('IDENTITY_HASH_KEY','different-secret-key-that-must-not-be-accepted')
    with pytest.raises(RuntimeError): migrate(engine)
