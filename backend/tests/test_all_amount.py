"""All fills the exact source balance; confirmation still validates spending."""
import json
from decimal import Decimal
import pytest
from backend.tests.test_budget import db, account, DAY
from backend.bot import dialogue
from backend.core.schemas import NewEntry
from backend.persistence.models import BotState, User
from backend.services import budget


@pytest.mark.parametrize('action', ['expense', 'transfer', 'exchange'])
def test_bot_all_uses_exact_source_balance_and_waits_for_confirmation(db, action):
    source = account(db, currency='BTC', kind='crypto', opening='0.12345678')
    target = account(db, currency='USD' if action == 'exchange' else 'BTC', kind='cash' if action == 'exchange' else 'savings', opening='0')
    user = db.get(User, 1)
    messages = ['/' + action, f'#{source}']
    if action != 'expense': messages.append(f'#{target}')
    for message in messages: response = dialogue.handle(db, user, message)
    assert ['All'] in response['reply_markup']['keyboard']
    dialogue.handle(db, user, 'All')
    assert json.loads(db.get(BotState, 1).payload)['data']['amount'] == '0.12345678'
    if action == 'expense': remaining = ['Grocery', 'Skip', DAY.isoformat()]
    elif action == 'exchange': remaining = ['Enter received amount', '10', DAY.isoformat()]
    else: remaining = [DAY.isoformat()]
    for message in remaining: response = dialogue.handle(db, user, message)
    assert f'Review {action}' in response['text']
    assert budget.balance(db, source) == Decimal('0.12345678')
    assert 'Saved.' in dialogue.handle(db, user, 'Confirm')['text']
    assert budget.balance(db, source) == 0
    if action != 'expense': assert budget.balance(db, target) == (10 if action == 'exchange' else Decimal('0.12345678'))


@pytest.mark.parametrize('negative', [False, True])
def test_bot_all_rejects_zero_and_negative_balances(db, negative):
    source = account(db, kind='card', opening='0')
    if negative:
        budget.add_entry(db, 1, NewEntry(account_id=source, kind='expense', amount='5', date=DAY))
    user = db.get(User, 1)
    for message in ['/expense', f'#{source}', 'All']:
        response = dialogue.handle(db, user, message)
    assert 'no positive balance' in response['text']
    assert 'amount' not in json.loads(db.get(BotState, 1).payload)['data']
    assert budget.balance(db, source) == (-5 if negative else 0)


def test_bot_all_rechecks_source_after_back_and_insufficient_funds_on_confirm(db):
    first = account(db, opening='50')
    second = account(db, opening='10')
    user = db.get(User, 1)
    for message in ['/expense', f'#{first}', 'All', dialogue.BACK, dialogue.BACK, f'#{second}', 'All', 'Grocery', 'Skip', DAY.isoformat()]:
        response = dialogue.handle(db, user, message)
    assert '10 USD' in response['text']
    budget.add_entry(db, 1, NewEntry(account_id=second, kind='expense', amount='1', date=DAY))
    assert 'Not enough funds' in dialogue.handle(db, user, 'Confirm')['text']
    assert budget.balance(db, first) == 50 and budget.balance(db, second) == 9


def test_bot_income_and_exchange_rate_have_no_all_option(db):
    source = account(db)
    target = account(db, currency='ARS')
    user = db.get(User, 1)
    for message in ['/income', f'#{source}']: response = dialogue.handle(db, user, message)
    assert ['All'] not in response['reply_markup']['keyboard']
    dialogue.handle(db, user, dialogue.HOME)
    for message in ['/exchange', f'#{source}', f'#{target}', 'All']: response = dialogue.handle(db, user, message)
    assert ['All'] not in response['reply_markup']['keyboard']
    response = dialogue.handle(db, user, 'Enter received amount')
    assert ['All'] not in response['reply_markup']['keyboard']
