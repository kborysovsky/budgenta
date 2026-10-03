"""Language isolation, canonical financial data, and per-user category removal."""
import json
from datetime import datetime, timezone
from string import Formatter
from decimal import Decimal
import pytest
from sqlalchemy import select, text
from backend.tests.test_budget import db, account, DAY
from backend.persistence.models import User, Entry, Preferences
from backend.core.i18n import CATALOGS, tr, language_scope
from backend.core.schemas import CategoryChange, NewEntry, ReportPreferences
from backend.services import budget, categories, reporting, scheduler
from backend.bot import dialogue


def test_catalog_parameters_are_complete():
    keys = set(CATALOGS['ru'])
    for language, catalog in CATALOGS.items():
        assert set(catalog) == keys
        for source, translated in catalog.items():
            assert translated, (language, source)
            fields = lambda value: {field for _, field, _, _ in Formatter().parse(value) if field is not None}
            assert fields(source) == fields(translated), (language, source)


@pytest.mark.parametrize('language', ['ru', 'uk', 'es'])
def test_bot_language_menu_transaction_and_reports(db, language):
    wallet = account(db)
    user = db.get(User, 1)
    result = dialogue.handle(db, user, '/language')
    assert ['Русский'] in result['reply_markup']['keyboard']
    dialogue.handle(db, user, dialogue.LANGUAGES[language])
    assert reporting.get_preferences(db, 1)['language'] == language
    catalog = CATALOGS[language]
    for message in [catalog['↑ Expense'], f'#{wallet}', '10,25']:
        result = dialogue.handle(db, user, message)
    assert [catalog['Grocery']] in result['reply_markup']['keyboard']
    for message in [catalog['Grocery'], 'literal note: Income / Продукты', DAY.isoformat()]:
        result = dialogue.handle(db, user, message)
    assert catalog['Review {action}:'].split('{')[0] in result['text']
    assert 'literal note: Income / Продукты' in result['text']
    dialogue.handle(db, user, catalog['Confirm'])
    entry = next(e for e in db.scalars(select(Entry)).all() if e.kind == 'expense')
    assert entry.category == 'Grocery'
    assert entry.note == 'literal note: Income / Продукты'
    assert budget.balance(db, wallet) == Decimal('89.75')
    now = datetime(2024, 1, 16, 18, tzinfo=timezone.utc)
    state = reporting.current_state(db, 1, now=now)
    report = reporting.report_message(db, 1, 'daily', now=now)
    assert catalog['Current state'] in state
    assert catalog['Daily report'] in report
    assert catalog['Grocery'] in state
    assert 'Wallet' in state  # Account name never translated.
    assert catalog['spent'] in state
    assert 'Current state' in reporting.current_state(db, 2, now=now)
    assert tr('Current state') == 'Current state'  # Scope never leaks to the next user.


def test_old_keyboard_after_web_language_change(db):
    wallet = account(db)
    user = db.get(User, 1)
    reporting.save_language(db, 1, 'ru')
    dialogue.handle(db, user, '↑ Расход')
    dialogue.handle(db, user, f'#{wallet}')
    reporting.save_language(db, 1, 'es')
    result = dialogue.handle(db, user, 'Всё')
    assert CATALOGS['es']['Category'] in result['text']
    result = dialogue.handle(db, user, 'Продукты')
    assert CATALOGS['es']['Note (optional)'] in result['text']
    dialogue.handle(db, user, '/home')
    assert budget.balance(db, wallet) == 100


def test_category_removal_preserves_history_isolation_and_settings(db):
    wallet = account(db)
    custom = budget.add_entry(db, 1, NewEntry(account_id=wallet, kind='expense', amount='5', category='Watches', save_category=True, date=DAY))
    original = budget.add_entry(db, 1, NewEntry(account_id=wallet, kind='expense', amount='5', category='Grocery', date=DAY))
    stale = ReportPreferences(**reporting.get_preferences(db, 1))
    categories.change(db, 1, CategoryChange(kind='expense', name='Watches'))
    categories.change(db, 1, CategoryChange(kind='expense', name='Grocery'))
    reporting.save_language(db, 1, 'ru')
    reporting.save_preferences(db, 1, stale)
    assert 'Grocery' not in categories.choices(db, 1)['expense']
    assert 'Watches' not in categories.choices(db, 1)['expense']
    assert 'Grocery' in categories.choices(db, 2)['expense']
    assert reporting.get_preferences(db, 1)['language'] == 'ru'
    assert db.get(Entry, custom).category == 'Watches'
    assert db.get(Entry, original).category == 'Grocery'
    assert budget.balance(db, wallet) == 90
    payload = db.execute(text('SELECT payload FROM preferences WHERE user_id=1')).scalar_one()
    assert payload.startswith('enc:v1:') and 'Grocery' not in payload
    categories.change(db, 1, CategoryChange(kind='expense', name='Grocery', removed=False))
    assert 'Grocery' in categories.choices(db, 1)['expense']
    assert len([r for r in categories.manage(db, 1)['expense'] if r['name'] == 'Grocery']) == 1
    with pytest.raises(budget.BudgetError):
        categories.change(db, 2, CategoryChange(kind='expense', name='Watches'))


def test_resaving_removed_default_is_atomic(db):
    wallet = account(db)
    categories.change(db, 1, CategoryChange(kind='expense', name='Grocery'))
    entry = NewEntry(account_id=wallet, kind='expense', amount='1', category='Grocery', save_category=True, date=DAY)
    budget.add_entry(db, 1, entry, commit=False)
    db.rollback()
    assert 'Grocery' not in categories.choices(db, 1)['expense']
    budget.add_entry(db, 1, entry)
    assert 'Grocery' in categories.choices(db, 1)['expense']


@pytest.mark.parametrize('purpose', ['Currency', 'Language', 'Grocery'])
def test_custom_purpose_is_not_translated(db, purpose):
    wallet = account(db)
    user = db.get(User, 1)
    reporting.save_language(db, 1, 'ru')
    for message in ['/income', f'#{wallet}', '1', purpose, 'Use once', 'Income', DAY.isoformat(), 'Confirm']:
        dialogue.handle(db, user, message)
    entry = next(e for e in db.scalars(select(Entry)).all() if e.kind == 'income')
    assert entry.category == purpose and entry.note == 'Income'


def test_language_scope_resets_after_error():
    with pytest.raises(RuntimeError):
        with language_scope('ru'):
            assert tr('Income') == 'Доход'
            raise RuntimeError()
    assert tr('Income') == 'Income'


@pytest.mark.parametrize('language', ['ru', 'uk', 'es'])
@pytest.mark.parametrize('action', ['transfer', 'exchange'])
def test_localized_movements_and_scheduled_reports(db, language, action):
    from backend.persistence.models import Notification
    source = account(db)
    target = account(db, currency='EUR' if action == 'exchange' else 'USD', opening='0')
    user = db.get(User, 1)
    reporting.save_language(db, 1, language)
    catalog = CATALOGS[language]
    button = '↔ Transfer' if action == 'transfer' else '⇄ Exchange'
    for message in [catalog[button], f'#{source}', f'#{target}', '5']:
        response = dialogue.handle(db, user, message)
    if action == 'exchange':
        dialogue.handle(db, user, catalog['Enter received amount'])
        dialogue.handle(db, user, '4')
    dialogue.handle(db, user, DAY.isoformat())
    response = dialogue.handle(db, user, catalog['Confirm'])
    assert response['text'] == catalog['Saved. Your balances and website are up to date.']
    assert budget.balance(db, source) == 95
    assert budget.balance(db, target) == (4 if action == 'exchange' else 5)
    # Scheduled daily report is rendered using the same encrypted preference.
    if action == 'transfer':
        scheduler.run_user_jobs(db, 1, datetime(2024, 1, 16, 18, tzinfo=timezone.utc))
        notifications = db.scalars(select(Notification)).all()
        assert any(catalog['Daily report'] in n.payload for n in notifications)
