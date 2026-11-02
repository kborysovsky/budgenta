"""Shared category limits preserve ownership, history, and alert semantics."""
import json
from datetime import date
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from backend.tests.test_budget_limits import db, fixed_month, account, enable, spend, tick, alerts, delivered, quote, NOW
from backend.core.schemas import BudgetLimitInput, ReportPreferences
from backend.core.encryption import decrypt
from backend.persistence.models import BudgetLimit, User
from backend.persistence.migrations import migrate
from backend.services import budget, budget_limits as limits, reporting, monthly_export


def save(db, names, uid=1, identifier=None, **changes):
    return limits.save(db, uid, BudgetLimitInput(categories=names, **({'amount': '100', 'currency': 'USD'} | changes)), identifier)


def test_combined_expenses_currency_filters_and_deletion(db):
    enable(db)
    usd, ars = account(db, opening='1000'), account(db, currency='ARS', opening='100000')
    foreign = account(db, user=2, opening='1000')
    row = save(db, ['Delivery', 'Outside Food'])
    spend(db, usd, '50', category='Delivery')
    mistaken = spend(db, ars, '75000', category='outside food')
    spend(db, usd, '10', category='Grocery')
    spend(db, usd, '20', category='Delivery', day=date(2023, 12, 31))
    spend(db, foreign, '500', category='Delivery', uid=2)
    result = limits.snapshot(db, 1, '2024-01', quote_fn=quote)
    assert result['budgets'][0]['categories'] == ['Delivery', 'Outside Food']
    assert result['budgets'][0]['stats']['percentage'] == '125.00'
    assert result['budgets'][0]['stats']['exceeded']
    assert Decimal(result['totals'][0]['remaining']) == -25
    filtered = limits.snapshot(db, 1, '2024-01', quote_fn=quote, config={'excluded_currencies': ['ARS'], 'include_savings': True, 'account_ids': None})
    assert Decimal(filtered['budgets'][0]['stats']['spent']) == 50
    budget.delete_transaction(db, 1, mistaken)
    assert Decimal(limits.snapshot(db, 1, '2024-01', quote_fn=quote)['budgets'][0]['stats']['spent']) == 50
    raw = db.execute(text('SELECT categories FROM budget_limits WHERE id=:id'), {'id': row['id']}).scalar_one()
    assert raw.startswith('enc:v1:') and json.loads(decrypt(raw)) == ['Delivery', 'Outside Food']


def test_group_membership_overlap_and_ownership(db):
    first = save(db, ['Delivery', 'Outside Food'], enabled=False)
    for names in [['delivery'], ['Outside Food', 'Transport']]:
        with pytest.raises(budget.BudgetError, match='already belongs'):
            save(db, names)
        db.rollback()
    save(db, ['Delivery', 'Outside Food'], uid=2)
    with pytest.raises(budget.BudgetError, match='not found'):
        save(db, ['Rent'], uid=2, identifier=first['id'])
    db.rollback()
    save(db, ['Delivery'], identifier=first['id'])
    other = save(db, ['Outside Food', 'Transport'])
    limits.remove(db, 1, other['id'])
    assert save(db, ['Delivery', 'Outside Food'], identifier=first['id'])['categories'] == ['Delivery', 'Outside Food']


@pytest.mark.parametrize('names', [[], ['Delivery', ' delivery '], [' '], ['x' * 61], [str(i) for i in range(51)]])
def test_reject_empty_duplicate_or_oversized_selection(names):
    with pytest.raises(ValidationError):
        BudgetLimitInput(categories=names, amount='100', currency='USD')


def test_combined_alerts_once_reorder_and_membership_change(db):
    enable(db)
    wallet = account(db, opening='1000')
    row = save(db, ['Delivery', 'Outside Food'])
    spend(db, wallet, '40', category='Delivery'); spend(db, wallet, '35', category='Outside Food')
    tick(db); tick(db)
    assert len(alerts(db)) == 1 and 'Delivery + Outside Food budget: 25.00% remaining' in alerts(db)[0].payload
    delivered(db)
    save(db, ['Outside Food', 'Delivery'], identifier=row['id'])
    tick(db)
    assert len(alerts(db)) == 1  # Ordering alone must not rearm a delivered alert.
    spend(db, wallet, '50', category='Outside Food'); tick(db)
    assert len(alerts(db)) == 2 and 'exceeded' in alerts(db)[-1].payload
    # Membership edits cancel a queued alert and recalculate without changing expenses.
    save(db, ['Delivery'], identifier=row['id'])
    assert all(a.sent for a in alerts(db))
    tick(db)
    assert len(alerts(db)) == 2
    spend(db, wallet, '35', category='Delivery'); tick(db)
    assert len(alerts(db)) == 3 and '25.00% remaining' in alerts(db)[-1].payload


def test_localized_reports_and_exports_include_group(db):
    enable(db); wallet = account(db, opening='1000')
    save(db, ['Delivery', 'Outside Food'])
    spend(db, wallet, '40', category='Delivery'); spend(db, wallet, '50', category='Outside Food')
    prefs = reporting.get_preferences(db, 1); prefs['monthly']['include_budgets'] = True
    reporting.save_preferences(db, 1, ReportPreferences(**prefs))
    result = limits.snapshot(db, 1, '2024-01', quote_fn=quote)
    assert 'Delivery + Outside Food' in limits.lines(result)
    rows = next(t['rows'] for t in monthly_export.monthly_tables(db, 1, '2024-01', quote_fn=quote) if t['name'] == 'Budget Limits')
    assert rows[0][0] == 'Delivery + Outside Food' and rows[0][3] == Decimal('90')
    reporting.save_language(db, 1, 'ru'); tick(db)
    text = alerts(db)[0].payload
    from backend.core.i18n import language_scope, category_label
    with language_scope('ru'):
        assert category_label('Delivery', 'expense') in text
        assert category_label('Outside Food', 'expense') in text


def test_v8_upgrade_preserves_existing_limit_ciphertext_and_membership():
    engine = create_engine('sqlite://')
    migrate(engine)
    with Session(engine) as session:
        session.add(User(id=1, telegram_id=123, name='Owner'))
        session.commit()
        row = limits.save(session, 1, BudgetLimitInput(category='Delivery', amount='100', currency='USD'))
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE budget_limits DROP COLUMN categories'))
        conn.execute(text('UPDATE schema_versions SET version=8 WHERE version=9'))
        before = conn.execute(text('SELECT * FROM budget_limits')).one()
    migrate(engine); migrate(engine)
    with engine.connect() as conn:
        after = conn.execute(text('SELECT * FROM budget_limits')).one()
        assert tuple(after[:-1]) == tuple(before) and after[-1] is None
        assert conn.scalar(text('SELECT max(version) FROM schema_versions')) == 9
    with Session(engine) as session:
        record = session.get(BudgetLimit, row['id'])
        assert limits.serialize(record)['categories'] == ['Delivery']
        assert limits.serialize(record)['amount'] == '100'
        assert limits.save(session, 1, BudgetLimitInput(categories=['Delivery', 'Outside Food'], amount='150', currency='USD'), row['id'])['categories'] == ['Delivery', 'Outside Food']
