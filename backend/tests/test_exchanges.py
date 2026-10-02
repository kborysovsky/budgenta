"""Cross-currency ledger operations and both public entry points."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.tests.test_budget import db, account, DAY
from backend.bot import dialogue
from backend.core.calendar import today
from backend.core.schemas import Exchange, NewEntry, NewGoal
from backend.persistence.models import Account, AccountGroup, Entry, User, BotState, MonthClose
from backend.services import budget, exchanges


def exchange_data(source, target, **kwargs):
    return Exchange(source_id=source, destination_id=target, amount='10', rate='1500', date=DAY, **kwargs)


def test_crypto_to_cash_paired_reversal_and_reports(db):
    source = account(db, currency='USDT', kind='crypto')
    target = account(db, currency='ARS', opening='0')
    data = exchange_data(source, target)
    count = len(db.scalars(select(Entry)).all())
    preview = exchanges.preview(db, 1, data)
    assert preview['received'] == '15000.00'
    assert len(db.scalars(select(Entry)).all()) == count
    result = exchanges.exchange(db, 1, data)
    assert budget.balance(db, source) == 90
    assert budget.balance(db, target) == 15000
    pair = db.scalars(select(Entry).where(Entry.operation_id == result['operation_id'])).all()
    assert len(pair) == 2 and all(e.kind == 'exchange' for e in pair)
    assert all('1 USDT = 1500 ARS' in e.note for e in pair)
    report = budget.monthly(db, 1, '2024-01')
    assert all(Decimal(t['income']) == Decimal(t['expenses']) == 0 for t in report['totals'])
    budget.delete_transaction(db, 1, pair[1].id)
    budget.delete_transaction(db, 1, pair[0].id)  # Both deletion directions are idempotent.
    assert budget.balance(db, source) == 100 and budget.balance(db, target) == 0


@pytest.mark.parametrize('currency,kind,rate,received', [
    ('USD', 'cash', '1.2345', '12.35'),
    ('BTC', 'crypto', '0.000000015', '0.00000015'),
    ('ETH', 'crypto', '0.0000123456', '0.00012346'),
    ('TRX', 'crypto', '0.12345675', '1.234568'),
    ('UAH', 'cash', '41.5555', '415.56'),
])
def test_destination_precision(db, currency, kind, rate, received):
    source = account(db, currency='USDT', kind='crypto')
    target = account(db, currency=currency, kind=kind, opening='0')
    data = Exchange(source_id=source, destination_id=target, amount='10', rate=rate, date=DAY)
    assert exchanges.exchange(db, 1, data)['received'] == received
    assert budget.balance(db, target) == Decimal(received)


def test_reversal_requires_undoing_spending_and_tracks_goal(db):
    source = account(db, currency='EUR')
    savings = account(db, kind='savings', opening='0')
    budget.create_goal(db, 1, NewGoal(name='Trip', currency='USD', target='100', savings_account_ids=[savings]))
    result = exchanges.exchange(db, 1, Exchange(source_id=source, destination_id=savings, amount='10', rate='1.1', date=DAY))
    assert Decimal(budget.goals(db, 1)[0]['saved']) == 11
    spent = budget.add_entry(db, 1, NewEntry(account_id=savings, kind='expense', amount='1', date=DAY))
    leg = db.scalar(select(Entry).where(Entry.operation_id == result['operation_id']))
    with pytest.raises(budget.BudgetError, match='dependent'):
        budget.delete_transaction(db, 1, leg.id)
    assert budget.balance(db, source) == 90 and budget.balance(db, savings) == 10
    budget.delete_transaction(db, 1, spent)
    budget.delete_transaction(db, 1, leg.id)
    assert Decimal(budget.goals(db, 1)[0]['saved']) == 0


@pytest.mark.parametrize('failure', ['foreign_source', 'foreign_target', 'same_currency', 'same_wallet', 'funds', 'precision', 'archived', 'future', 'closed', 'zero_received', 'overflow'])
def test_invalid_exchange_never_writes_a_leg(db, failure):
    source = account(db)
    target = account(db, currency='ARS', opening='0')
    data = dict(source_id=source, destination_id=target, amount='10', rate='1500', date=DAY)
    if failure == 'foreign_source': data['source_id'] = account(db, user=2)
    if failure == 'foreign_target': data['destination_id'] = account(db, currency='ARS', user=2)
    if failure == 'same_currency': data['destination_id'] = account(db)
    if failure == 'same_wallet': data['destination_id'] = source
    if failure == 'funds': data['amount'] = '101'
    if failure == 'precision': data['amount'] = '0.001'
    if failure == 'archived': db.get(AccountGroup, db.get(Account, target).group_id).archived = True; db.commit()
    if failure == 'future': data['date'] = today() + timedelta(days=1)
    if failure == 'closed': db.add(MonthClose(user_id=1, month='2024-01')); db.commit()
    if failure == 'zero_received': data['rate'] = '0.00001'
    if failure == 'overflow': data['rate'] = '999999999999999999'
    before = len(db.scalars(select(Entry)).all())
    with pytest.raises(budget.BudgetError): exchanges.exchange(db, 1, Exchange(**data))
    assert len(db.scalars(select(Entry)).all()) == before
    assert budget.balance(db, source) == 100 and budget.balance(db, target) == 0


@pytest.mark.parametrize('rate', ['0', '-1', 'NaN', 'Infinity', '0.0000000000000000001'])
def test_invalid_rate_rejected_by_schema(rate):
    with pytest.raises(ValidationError):
        Exchange(source_id=1, destination_id=2, amount='1', rate=rate)


@pytest.mark.parametrize('action', ['transfer', 'exchange'])
def test_bot_confirm_back_home_and_destination_validation(db, action):
    source = account(db, currency='USDT', kind='crypto')
    target = account(db, currency='ARS' if action == 'exchange' else 'USDT', kind='cash' if action == 'exchange' else 'savings', opening='0')
    other = account(db, currency='ARS', user=2)
    user = db.get(User, 1)
    dialogue.handle(db, user, '/' + action)
    result = dialogue.handle(db, user, f'#{source}')
    assert f'#{target}' in str(result['reply_markup']) and f'#{source} ' not in str(result['reply_markup'])
    for bad in (source, other):
        result = dialogue.handle(db, user, f'#{bad}')
        assert 'Could not save' in result['text']
        assert json.loads(db.get(BotState, 1).payload)['step'] == 1
    dialogue.handle(db, user, f'#{target}')
    dialogue.handle(db, user, '10')
    if action == 'exchange':
        result = dialogue.handle(db, user, '0')
        assert 'positive' in result['text']
        dialogue.handle(db, user, '1500')
    result = dialogue.handle(db, user, DAY.isoformat())
    assert f'Review {action}' in result['text']
    assert '15000.00 ARS' in result['text'] if action == 'exchange' else '+10 USDT' in result['text']
    assert budget.balance(db, source) == 100
    dialogue.handle(db, user, dialogue.BACK)
    assert 'date' not in json.loads(db.get(BotState, 1).payload)['data']
    dialogue.handle(db, user, DAY.isoformat())
    assert 'Saved.' in dialogue.handle(db, user, 'Confirm')['text']
    dialogue.handle(db, user, 'Confirm')
    assert budget.balance(db, source) == 90
    assert budget.balance(db, target) == (15000 if action == 'exchange' else 10)
    dialogue.handle(db, user, '/' + action)
    dialogue.handle(db, user, f'#{source}')
    dialogue.handle(db, user, dialogue.BACK)
    assert json.loads(db.get(BotState, 1).payload)['data'] == {}
    dialogue.handle(db, user, dialogue.HOME)
    assert json.loads(db.get(BotState, 1).payload) == {}


def test_bot_exchange_duplicate_update_is_atomic(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from backend.persistence.database import Base
    from backend.bot import worker
    from backend.services.users import find_or_create_user
    engine = create_engine('sqlite:///' + str(tmp_path / 'exchange.db'))
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        user = find_or_create_user(session, 111, 'Test')
        source = account(session)
        target = account(session, currency='ARS', opening='0')
    monkeypatch.setattr(worker, 'engine', engine)
    for i, message in enumerate(['/exchange', f'#{source}', f'#{target}', '10', '1500', DAY.isoformat(), 'Confirm'], 1):
        update = {'update_id': i, 'message': {'chat': {'id': 111, 'type': 'private'}, 'from': {'id': 111, 'first_name': 'Test'}, 'text': message}}
        worker.process_update(update)
        worker.process_update(update)
    with Session(engine) as session:
        assert budget.balance(session, source) == 90
        assert budget.balance(session, target) == 15000
        assert len(session.scalars(select(Entry)).all()) == 4


@pytest.mark.parametrize('sent,received,currency,kind', [
    ('3', '10.00', 'ARS', 'cash'),
    ('100', '0.00000001', 'BTC', 'crypto'),
    ('999999999999999999', '0.00000001', 'ETH', 'crypto'),
    ('0.01', '999999999999999999.99', 'ARS', 'cash'),
])
def test_received_amount_is_authoritative_even_with_rounded_or_extreme_rate(db, sent, received, currency, kind):
    source = account(db, opening=sent)
    target = account(db, currency=currency, kind=kind, opening='0')
    data = Exchange(source_id=source, destination_id=target, amount=sent, received=received, date=DAY)
    preview = exchanges.preview(db, 1, data)
    assert preview['rate_calculated'] is True and Decimal(preview['rate']) > 0
    if sent == '3':
        assert preview['rate'] == '3.33333333333333333' and preview['rate_approximate'] is True
    result = exchanges.exchange(db, 1, data)
    assert result['received'] == preview['received']
    assert budget.balance(db, source) == 0
    assert budget.balance(db, target) == Decimal(received)
    leg = db.scalar(select(Entry).where(Entry.operation_id == result['operation_id']))
    assert 'calculated from' in leg.note
    budget.delete_transaction(db, 1, leg.id)
    assert budget.balance(db, source) == Decimal(sent) and budget.balance(db, target) == 0


@pytest.mark.parametrize('extra', [{}, {'rate': '2', 'received': '10'}, {'received': '0'}, {'received': '-1'}, {'received': 'NaN'}, {'received': 'Infinity'}])
def test_exchange_requires_exactly_one_valid_input(extra):
    with pytest.raises(ValidationError):
        Exchange(source_id=1, destination_id=2, amount='3', **extra)


def test_received_precision_error_does_not_write(db):
    source = account(db)
    target = account(db, currency='ARS', opening='0')
    with pytest.raises(budget.BudgetError, match='decimal places'):
        exchanges.exchange(db, 1, Exchange(source_id=source, destination_id=target, amount='3', received='10.001', date=DAY))
    assert budget.balance(db, source) == 100 and budget.balance(db, target) == 0


def test_bot_received_amount_switch_back_and_confirmation(db):
    source = account(db)
    target = account(db, currency='ARS', opening='0')
    user = db.get(User, 1)
    for message in ['/exchange', f'#{source}', f'#{target}', '3']:
        response = dialogue.handle(db, user, message)
    assert 'Enter received amount' in str(response['reply_markup'])
    response = dialogue.handle(db, user, 'Enter received amount')
    assert 'Final amount received in ARS' in response['text']
    assert 'decimal places' in dialogue.handle(db, user, '10.001')['text']
    for message in ['10', DAY.isoformat()]: response = dialogue.handle(db, user, message)
    assert '+10.00 ARS' in response['text'] and 'Calculated rate' in response['text'] and '≈' in response['text']
    dialogue.handle(db, user, dialogue.BACK)
    assert json.loads(db.get(BotState, 1).payload)['data']['received'] == '10'
    dialogue.handle(db, user, dialogue.BACK)
    assert 'received' not in json.loads(db.get(BotState, 1).payload)['data']
    dialogue.handle(db, user, 'Enter rate')
    dialogue.handle(db, user, '2')
    dialogue.handle(db, user, dialogue.BACK)
    dialogue.handle(db, user, 'Enter received amount')
    for message in ['10', DAY.isoformat(), 'Confirm']: response = dialogue.handle(db, user, message)
    assert 'Saved.' in response['text']
    assert budget.balance(db, source) == 97 and budget.balance(db, target) == 10
    dialogue.handle(db, user, 'Confirm')
    assert budget.balance(db, target) == 10
