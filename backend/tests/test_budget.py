import hashlib
import hmac
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.persistence.database import Base
from backend.persistence.models import User
from backend.core.schemas import NewAccount, NewEntry, Transfer
from backend.services import budget as service
from backend.web.auth import verify_telegram

@pytest.fixture
def db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all([User(id=1, telegram_id=123, name='Owner'), User(id=2, telegram_id=456, name='Other')])
        session.commit()
        yield session

DAY = date(2024, 1, 15)

def account(db, currency='USD', kind='cash', opening='100', user=1):
    return service.create_account(db, user, NewAccount(name='Wallet', kind=kind, currency=currency, opening_balance=opening, date=DAY))

def entry(db, account_id, amount, kind='income', day=DAY):
    return service.add_entry(db, 1, NewEntry(account_id=account_id, kind=kind, amount=amount, date=day))

def test_exact_balance_and_savings_exclude_opening_and_transfers(db):
    first, second = account(db), account(db, opening='0')
    entry(db, first, '0.10'); entry(db, first, '0.20'); entry(db, first, '0.10', 'expense')
    service.transfer(db, 1, Transfer(source_id=first, destination_id=second, amount='50', date=DAY))
    assert service.balance(db, first) == Decimal('50.20')
    assert service.balance(db, second) == Decimal('50')
    report = service.monthly(db, 1, '2024-01')['totals'][0]
    assert Decimal(report['income']) == Decimal('0.30')
    assert Decimal(report['expenses']) == Decimal('0.10')
    assert Decimal(report['surplus']) == Decimal('0.20')

def test_ownership_and_no_leak(db):
    mine = account(db)
    with pytest.raises(service.BudgetError, match='not found'):
        service.owned_account(db, 2, mine)
    assert service.accounts(db, 2) == []
    assert service.monthly(db, 2, '2024-01')['transactions'] == []

def test_currency_precision_and_allowed_types(db):
    with pytest.raises(service.BudgetError, match='not supported'):
        account(db, currency='BTC')
    db.rollback()
    usd = account(db)
    with pytest.raises(service.BudgetError, match='decimal places'):
        entry(db, usd, '0.001')
    db.rollback()
    trx = account(db, currency='TRX', kind='crypto')
    entry(db, trx, '0.000001')
    assert service.balance(db, trx) == Decimal('100.000001')

def test_transfer_failure_does_not_write_half(db):
    first = account(db)
    second = account(db, currency='ARS')
    with pytest.raises(service.BudgetError, match='same currency'):
        service.transfer(db, 1, Transfer(source_id=first, destination_id=second, amount='5', date=DAY))
    assert service.balance(db, first) == Decimal('100')
    assert service.balance(db, second) == Decimal('100')

def test_cash_overdraft_rejected_card_debt_allowed(db):
    cash, card = account(db), account(db, kind='card')
    with pytest.raises(service.BudgetError, match='Not enough'):
        entry(db, cash, '101', 'expense')
    db.rollback()
    entry(db, card, '101', 'expense')
    assert service.balance(db, card) == Decimal('-1')

def test_closing_locks_history_and_preserves_deficit(db):
    wallet = account(db)
    entry(db, wallet, '10', 'expense')
    service.close_month(db, 1, '2024-01')
    assert Decimal(service.savings(db, 1)[0]['totals'][0]['surplus']) == Decimal('-10')
    with pytest.raises(service.BudgetError, match='closed'):
        entry(db, wallet, '5')
    db.rollback()
    with pytest.raises(service.BudgetError, match='chronological'):
        service.close_month(db, 1, '2024-01')
    db.rollback()
    with pytest.raises(service.BudgetError, match='last day'):
        service.close_month(db, 1, date.today().strftime('%Y-%m'))

@pytest.mark.parametrize('month', ['bad', '2024-13', '2024-00', '2024-1', '0000-01'])
def test_invalid_month(month):
    with pytest.raises(service.BudgetError):
        service.month_bounds(month)

def test_telegram_signature_expiry_and_tampering():
    token = 'test-token-only'
    data = {'id': 123, 'first_name': 'Owner', 'auth_date': 1000}
    check = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
    data['hash'] = hmac.new(hashlib.sha256(token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    assert verify_telegram(data, token, now=1001) == 123
    with pytest.raises(ValueError, match='expired'):
        verify_telegram(data, token, now=1400)
    with pytest.raises(ValueError, match='signature'):
        verify_telegram({**data, 'id': 999}, token, now=1001)
