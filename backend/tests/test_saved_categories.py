"""Reusable categories are private, optional, encrypted, and saved atomically."""
import json
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select, text, inspect
from backend.tests.test_budget import db, account, DAY
from backend.core.schemas import NewEntry
from backend.persistence.models import Entry, SavedCategory, BotState, User
from backend.persistence.migrations import migrate, VERSION
from backend.core.encryption import encrypt, identity_key
from backend.services import budget, categories
from backend.bot import dialogue


def add(db, wallet, name, *, kind='expense', save=False, amount='10'):
    return budget.add_entry(db, 1, NewEntry(account_id=wallet, kind=kind, amount=amount, category=name, save_category=save, date=DAY))


def test_once_saved_case_matching_and_separate_income(db):
    wallet = account(db)
    add(db, wallet, 'One-time errand')
    assert 'One-time errand' not in categories.choices(db, 1)['expense']
    identifier = add(db, wallet, '  Watches  ', save=True)
    add(db, wallet, 'wATCHES', save=True)
    add(db, wallet, ' grocery ', save=True)
    add(db, wallet, 'Money   from parents', kind='income', save=True)
    assert db.get(Entry, identifier).category == 'Watches'
    assert categories.choices(db, 1)['expense'].count('Watches') == 1
    assert 'Money from parents' in categories.choices(db, 1)['income']
    assert 'Money from parents' not in categories.choices(db, 1)['expense']
    assert 'Watches' not in categories.choices(db, 1)['income']
    assert 'Watches' not in categories.choices(db, 2)['expense']
    assert len(db.scalars(select(SavedCategory)).all()) == 2
    # A mistaken transaction can be reversed without losing the user's saved choice.
    budget.delete_transaction(db, 1, identifier)
    assert 'Watches' in categories.choices(db, 1)['expense']
    totals = budget.monthly(db, 1, '2024-01')['totals'][0]
    assert Decimal(totals['expenses']) == 30 and Decimal(totals['income']) == 10


def test_same_name_can_be_saved_for_both_kinds(db):
    wallet = account(db)
    add(db, wallet, 'Family', save=True)
    add(db, wallet, 'Family', kind='income', save=True)
    assert all('Family' in categories.choices(db, 1)[kind] for kind in ('income', 'expense'))


def test_failed_and_rolled_back_transaction_does_not_save_category(db):
    wallet = account(db, opening='0')
    with pytest.raises(budget.BudgetError):
        add(db, wallet, 'Unaffordable', save=True)
    assert 'Unaffordable' not in categories.choices(db, 1)['expense']
    other = account(db, user=2)
    with pytest.raises(budget.BudgetError):
        add(db, other, 'Foreign', save=True)
    assert not db.scalars(select(SavedCategory)).all()
    budget.add_entry(db, 1, NewEntry(account_id=wallet, kind='income', amount='10', category='Rolled back', save_category=True, date=DAY), commit=False)
    db.rollback()
    assert 'Rolled back' not in categories.choices(db, 1)['income']
    assert budget.balance(db, wallet) == 0


def test_saved_category_fields_encrypted_at_rest(db):
    wallet = account(db)
    add(db, wallet, 'Secret watches', save=True)
    rows = db.execute(text('SELECT kind, name FROM saved_categories')).all()
    assert rows and all(value.startswith('enc:v1:') for row in rows for value in row)
    assert 'Secret watches' not in str(rows)
    db.expire_all()
    assert 'Secret watches' in categories.choices(db, 1)['expense']


@pytest.mark.parametrize('value', ['   ', '\n\t', 'a' * 61])
def test_invalid_category(value):
    with pytest.raises(ValidationError):
        NewEntry(account_id=1, amount='1', kind='expense', category=value, save_category=True)


@pytest.mark.parametrize('save', [True, False])
def test_bot_custom_choice_confirm_and_reuse(db, save):
    wallet = account(db); user = db.get(User, 1)
    for message in ['/income', f'#{wallet}', '50', 'Money from parents']:
        response = dialogue.handle(db, user, message)
    assert 'Save category' in str(response['reply_markup'])
    assert not db.scalars(select(SavedCategory)).all()
    dialogue.handle(db, user, 'Save category' if save else 'Use once')
    for message in ['Skip', DAY.isoformat()]: response = dialogue.handle(db, user, message)
    assert ('Save this category' in response['text']) == save
    dialogue.handle(db, user, dialogue.BACK)
    assert json.loads(db.get(BotState, 1).payload)['data']['save_category'] == save
    for message in [DAY.isoformat(), 'Confirm']: response = dialogue.handle(db, user, message)
    assert 'Saved.' in response['text'] and budget.balance(db, wallet) == 150
    assert ('Money from parents' in categories.choices(db, 1)['income']) == save
    if save:
        for message in ['/income', f'#{wallet}', '1']: response = dialogue.handle(db, user, message)
        assert 'Money from parents' in str(response['reply_markup'])
        response = dialogue.handle(db, user, 'Money from parents')
        assert 'Note (optional)' in response['text']  # Existing categories need no extra question.


def test_bot_cancel_and_back_do_not_save_category(db):
    wallet = account(db); user = db.get(User, 1)
    for message in ['/expense', f'#{wallet}', '10', 'Watches']:
        dialogue.handle(db, user, message)
    dialogue.handle(db, user, dialogue.BACK)
    state = json.loads(db.get(BotState, 1).payload)
    assert 'category' not in state['data'] and not state.get('category_choice_pending')
    for message in ['Another purpose', 'Save category', 'Skip', DAY.isoformat(), 'Cancel']:
        dialogue.handle(db, user, message)
    assert categories.choices(db, 1)['expense'] == categories.EXPENSE_CATEGORIES
    assert budget.balance(db, wallet) == 100


def test_migrate_v5_creates_category_table_and_is_repeatable():
    engine = create_engine('sqlite://')
    migrate(engine)
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE saved_categories'))
        conn.execute(text('DELETE FROM schema_versions'))
        conn.execute(text('INSERT INTO schema_versions(version,key_check) VALUES (5,:check)'), {'check': encrypt('pocket-encryption-check:' + identity_key(0))})
    migrate(engine); migrate(engine)
    assert 'saved_categories' in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT max(version) FROM schema_versions')) == VERSION
