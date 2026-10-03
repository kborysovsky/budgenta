"""Budgets read the encrypted ledger, convert currencies, and queue advisory alerts."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from pydantic import ValidationError
from sqlalchemy import select, text, create_engine, inspect
from sqlalchemy.orm import Session
from backend.tests.test_budget import db, account, DAY
from backend.core.schemas import BudgetLimitInput, BudgetLimitSettings, NewEntry, Transfer, ReportPreferences, CategoryChange
from backend.core.encryption import encrypt, identity_key
from backend.persistence.models import BudgetLimit, BudgetAlertState, Notification, User, Entry
from backend.persistence.migrations import migrate, VERSION, KEY_CHECK_PREFIX
from backend.services import budget, budget_limits as limits, reporting, categories, scheduler

NOW = datetime(2024, 1, 16, 18, tzinfo=timezone.utc)
RATES = {'USD': '1', 'EUR': '1.25', 'ARS': '.001', 'UAH': '.025', 'USDT': '1', 'TRX': '.3', 'BTC': '60000', 'ETH': '3000'}


def quote(currency):
    return dict(usd_rate=RATES[currency], stale=False, as_of='2024-01-16', source='Test quotes', display_rate=f'1 {currency} = {RATES[currency]} USD', url='https://example.invalid')


@pytest.fixture(autouse=True)
def fixed_month(monkeypatch):
    original = limits.current_month
    monkeypatch.setattr(limits, 'current_month', lambda db, user_id, now=None: original(db, user_id, now or NOW))


def enable(db, uid=1, **kwargs):
    return limits.save_settings(db, uid, BudgetLimitSettings(enabled=True, **kwargs))


def create(db, category='Grocery', amount='100', currency='USD', uid=1, **kwargs):
    return limits.save(db, uid, BudgetLimitInput(category=category, amount=amount, currency=currency, **kwargs))


def spend(db, wallet, amount, category='Grocery', uid=1, day=DAY):
    return budget.add_entry(db, uid, NewEntry(account_id=wallet, kind='expense', amount=amount, category=category, date=day))


def tick(db, now=NOW, quote_fn=quote):
    budget.lock_user(db, 1)
    limits.check_alerts(db, 1, now, quote_fn=quote_fn)
    db.commit()


def alerts(db):
    return db.scalars(select(Notification).where(Notification.budget_id.is_not(None)).order_by(Notification.id)).all()


def delivered(db):
    for row in alerts(db): row.sent = True
    db.commit()


def test_optional_defaults_do_not_change_expense_workflow(db):
    wallet = account(db, opening='1000')
    create(db, amount='1')
    spend(db, wallet, '125')
    tick(db)
    assert not alerts(db)
    result = limits.overview(db, 1, '2024-01', quote_fn=quote)
    assert not result['settings']['enabled'] and result['budgets'][0]['stats'] is None
    assert budget.balance(db, wallet) == 875
    enable(db)
    stats = limits.snapshot(db, 1, '2024-01', quote_fn=quote)['budgets'][0]['stats']
    assert stats['percentage'] == '12500.00' and Decimal(stats['remaining']) == -124


def test_shared_limit_multi_currency_exclusions_and_ownership(db):
    enable(db)
    usd, ars, eur, trx = (account(db, currency=c, kind='crypto' if c == 'TRX' else 'cash', opening='100000') for c in ['USD', 'ARS', 'EUR', 'TRX'])
    other = account(db, user=2, opening='1000')
    for wallet, amount in [(usd, '40'), (ars, '50000'), (eur, '8'), (trx, '100')]: spend(db, wallet, amount)
    spend(db, other, '500', uid=2)
    create(db, currency='EUR', expense_currencies=['USD', 'ARS', 'EUR'])
    result = limits.snapshot(db, 1, '2024-01', quote_fn=quote)
    row = result['budgets'][0]
    assert Decimal(row['stats']['spent']) == 80 and Decimal(row['stats']['remaining']) == 20
    assert row['stats']['percentage'] == '80.00'
    assert {v['currency'] for v in row['native_spending']} == {'USD', 'ARS', 'EUR'}
    assert len(result['totals']) == 1 and Decimal(result['totals'][0]['spent']) == 80
    assert limits.snapshot(db, 2, '2024-01', quote_fn=quote)['budgets'] == []


def test_only_live_expenses_count_and_deletion_recalculates(db):
    enable(db)
    first, target = account(db, opening='1000'), account(db, opening='0')
    create(db)
    spend(db, first, '20', category=' Grocery ')
    mistaken = spend(db, first, '105', category='grocery')
    spend(db, first, '10', category='Rent')
    spend(db, first, '10', day=date(2023, 12, 31))
    budget.add_entry(db, 1, NewEntry(account_id=first, kind='income', amount='50', category='Grocery', date=DAY))
    budget.transfer(db, 1, Transfer(source_id=first, destination_id=target, amount='20', date=DAY))
    row = limits.snapshot(db, 1, '2024-01', quote_fn=quote)['budgets'][0]
    assert row['stats']['percentage'] == '125.00' and row['stats']['exceeded']
    budget.delete_transaction(db, 1, mistaken)
    categories.change(db, 1, CategoryChange(kind='expense', name='Grocery'))
    row = limits.snapshot(db, 1, '2024-01', quote_fn=quote)['budgets'][0]
    assert Decimal(row['stats']['spent']) == 20
    assert not row['stats']['exceeded']


def test_thresholds_once_at_exact_boundaries_and_reset(db):
    enable(db)
    wallet = account(db, opening='1000'); rule = create(db)
    for index, (amount, threshold) in enumerate([('75', 25), ('10', 15), ('5', 10), ('5', 5), ('5', 0)], 1):
        spend(db, wallet, amount)
        tick(db); tick(db)
        assert len(alerts(db)) == index
        assert json.loads(alerts(db)[-1].budget_context)['crossed'] == [threshold]
        delivered(db)
    assert 'fully used' in alerts(db)[-1].payload
    spend(db, wallet, '25'); tick(db)
    assert len(alerts(db)) == 5
    limits.reset_alerts(db, 1, rule['id'], now=NOW)
    tick(db)
    assert len(alerts(db)) == 6 and 'exceeded' in alerts(db)[-1].payload and '125.00%' in alerts(db)[-1].payload
    assert Decimal(limits.snapshot(db, 1, '2024-01')['budgets'][0]['stats']['remaining']) == -25


def test_jumps_coalesce_and_alerts_and_state_are_atomic(db):
    enable(db)
    wallet = account(db, opening='1000'); create(db)
    spend(db, wallet, '125')
    limits.check_alerts(db, 1, NOW, quote_fn=quote)
    db.rollback()
    assert not alerts(db) and not db.scalars(select(BudgetAlertState)).all()
    tick(db); tick(db)
    assert len(alerts(db)) == 1
    assert json.loads(alerts(db)[0].budget_context)['crossed'] == list(limits.THRESHOLDS)
    assert 'exceeded' in alerts(db)[0].payload


def test_disable_reenable_no_duplicates_and_cancel_queued_notifications(db):
    enable(db)
    wallet = account(db, opening='1000'); rule = create(db)
    spend(db, wallet, '90'); tick(db)
    assert len(alerts(db)) == 1
    limits.save_settings(db, 1, BudgetLimitSettings(enabled=False))
    assert all(row.sent for row in alerts(db))
    enable(db); tick(db)
    assert len(alerts(db)) == 2 and not alerts(db)[-1].sent
    delivered(db)
    limits.save(db, 1, BudgetLimitInput(category='Grocery', amount='100', currency='USD', enabled=False), rule['id'])
    tick(db)
    limits.save(db, 1, BudgetLimitInput(category='Grocery', amount='100', currency='USD', enabled=True), rule['id'])
    tick(db)
    assert len(alerts(db)) == 2
    limits.save_settings(db, 1, BudgetLimitSettings(enabled=True, notifications_enabled=False))
    spend(db, wallet, '20'); tick(db)
    assert len(alerts(db)) == 2


def test_deleting_expense_does_not_rearm_but_limit_change_does(db):
    enable(db)
    wallet = account(db, opening='1000'); rule = create(db)
    mistaken = spend(db, wallet, '90'); tick(db); delivered(db)
    budget.delete_transaction(db, 1, mistaken)
    spend(db, wallet, '90'); tick(db)
    assert len(alerts(db)) == 1
    limits.save(db, 1, BudgetLimitInput(category='Grocery', amount='200', currency='USD'), rule['id'])
    tick(db)
    assert len(alerts(db)) == 1
    spend(db, wallet, '60'); tick(db)
    assert len(alerts(db)) == 2 and '25.00% remaining' in alerts(db)[-1].payload
    delivered(db)
    # Saving an unchanged form or changing a limit that leaves a reached threshold
    # relevant does not repeat it; lowering through a new threshold does alert.
    limits.save(db, 1, BudgetLimitInput(category='Grocery', amount='195', currency='USD'), rule['id']); tick(db)
    assert len(alerts(db)) == 2
    limits.save(db, 1, BudgetLimitInput(category='Grocery', amount='100', currency='USD'), rule['id']); tick(db)
    assert len(alerts(db)) == 3 and 'exceeded' in alerts(db)[-1].payload


def test_fresh_rates_required_for_alerts_and_exact_unrounded_threshold(db):
    enable(db)
    wallet = account(db, currency='ARS', opening='1000000'); create(db)
    spend(db, wallet, '74999')
    tick(db)
    assert not alerts(db)  # 74.999% displays as 75.00%, but has not crossed yet.
    spend(db, wallet, '1')
    missing = lambda c: None if c == 'ARS' else quote(c)
    result = limits.snapshot(db, 1, '2024-01', quote_fn=missing)
    assert result['budgets'][0]['stats']['spent'] is None and result['totals'][0]['spent'] is None
    tick(db, quote_fn=missing); assert not alerts(db)
    stale = lambda c: {**quote(c), 'stale': c == 'ARS'}
    tick(db, quote_fn=stale); assert not alerts(db)
    assert limits.snapshot(db, 1, '2024-01', quote_fn=stale)['budgets'][0]['stats']['stale']
    tick(db); assert len(alerts(db)) == 1


def test_month_rollover_uses_user_timezone_and_cancels_old_queue(db):
    enable(db)
    wallet = account(db, opening='1000'); create(db)
    spend(db, wallet, '90'); tick(db)
    pending = alerts(db)[0]
    boundary = datetime(2024, 2, 1, 2, 59, tzinfo=timezone.utc)
    assert limits.current_month(db, 1, boundary) == '2024-01'
    assert limits.notification_active(db, pending, boundary)
    february = datetime(2024, 2, 1, 3, 0, tzinfo=timezone.utc)
    assert limits.current_month(db, 1, february) == '2024-02'
    assert not limits.notification_active(db, pending, february)
    spend(db, wallet, '75', day=date(2024, 2, 1)); tick(db, now=february)
    assert len(alerts(db)) == 2 and '2024-02' in alerts(db)[-1].payload


def test_ownership_duplicates_removal_and_encryption(db):
    enable(db); rule = create(db, category='Private category')
    with pytest.raises(budget.BudgetError, match='already has'):
        create(db, category=' private CATEGORY ')
    db.rollback()
    for fn in [lambda: limits.remove(db, 2, rule['id']), lambda: limits.reset_alerts(db, 2, rule['id']),
               lambda: limits.save(db, 2, BudgetLimitInput(category='Private category', amount='50', currency='USD'), rule['id'])]:
        with pytest.raises(budget.BudgetError, match='not found'): fn()
        db.rollback()
    create(db, category='Private category', uid=2)
    tick(db)
    row = db.execute(text('SELECT category, amount, currency, expense_currencies, enabled FROM budget_limits LIMIT 1')).one()
    assert all(value.startswith('enc:v1:') for value in row)
    assert 'Private category' not in str(row)
    state = db.execute(text('SELECT payload FROM budget_alert_states LIMIT 1')).scalar_one()
    assert state.startswith('enc:v1:')
    limits.remove(db, 1, rule['id'])
    assert not limits.definitions(db, 1)
    assert create(db, category='Private category')['id'] != rule['id']


@pytest.mark.parametrize('change', [{'amount': '0'}, {'amount': '-1'}, {'currency': 'JPY'}, {'expense_currencies': []}, {'expense_currencies': ['USD', 'USD']}, {'category': '   '}])
def test_schema_validation(change):
    with pytest.raises(ValidationError): BudgetLimitInput(**({'category': 'Grocery', 'amount': '100', 'currency': 'USD'} | change))


def test_precision_reports_filters_and_localized_alerts(db):
    enable(db)
    wallet = account(db, opening='1000'); ars = account(db, currency='ARS', opening='100000')
    with pytest.raises(budget.BudgetError, match='decimal places'): create(db, amount='0.001')
    db.rollback()
    create(db)
    spend(db, wallet, '50'); spend(db, ars, '25000')
    baseline = reporting.current_state(db, 1, now=NOW, quote_fn=quote)
    assert 'Budget Limits' not in baseline
    prefs = reporting.get_preferences(db, 1)
    for section in ['daily', 'weekly', 'monthly', 'current_state', 'dashboard']: prefs[section]['include_budgets'] = True
    reporting.save_preferences(db, 1, ReportPreferences(**prefs))
    assert '75.00% used' in reporting.current_state(db, 1, now=NOW, quote_fn=quote)
    assert 'Budget Limits · 2024-01' in reporting.report_message(db, 1, 'daily', now=NOW, quote_fn=quote)
    assert 'Budget Limits · 2024-01' in reporting.report_message(db, 1, 'monthly', now=datetime(2024, 2, 1, 18, tzinfo=timezone.utc), quote_fn=quote)
    prefs['monthly']['excluded_currencies'] = ['ARS']
    reporting.save_preferences(db, 1, ReportPreferences(**prefs))
    assert Decimal(reporting.monthly_report(db, 1, '2024-01', quote_fn=quote)['budgets']['budgets'][0]['stats']['spent']) == 50
    prefs['monthly']['account_ids'] = []
    reporting.save_preferences(db, 1, ReportPreferences(**prefs))
    assert Decimal(reporting.monthly_report(db, 1, '2024-01', quote_fn=quote)['budgets']['budgets'][0]['stats']['spent']) == 0
    reporting.save_language(db, 1, 'ru'); tick(db)
    assert 'Продукты' in alerts(db)[0].payload and 'осталось 25.00%' in alerts(db)[0].payload
    # Feature and report controls survive unrelated old preference clients.
    old = {'timezone': prefs['timezone']}
    reporting.save_preferences(db, 1, ReportPreferences(**old))
    assert reporting.get_preferences(db, 1)['budget_limits']['enabled']
    assert reporting.get_preferences(db, 1)['monthly']['include_budgets']


def test_v7_migration_preserves_encrypted_rows_and_pending_notifications():
    engine = create_engine('sqlite://')
    migrate(engine)
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE notifications'))
        conn.execute(text('CREATE TABLE notifications (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), job_key VARCHAR(64) NOT NULL UNIQUE, payload TEXT NOT NULL, sent BOOLEAN NOT NULL)'))
        conn.execute(text('DROP TABLE budget_alert_states'))
        conn.execute(text('DROP TABLE budget_limits'))
        conn.execute(text('DELETE FROM schema_versions'))
        conn.execute(text('INSERT INTO schema_versions VALUES (7, :check)'), {'check': encrypt(KEY_CHECK_PREFIX + identity_key(0))})
        conn.execute(text('INSERT INTO users (id, telegram_id, telegram_key, name) VALUES (1, :telegram, :key, :name)'), {'telegram': encrypt('123'), 'key': identity_key(123), 'name': encrypt('Original owner')})
        conn.execute(text('INSERT INTO notifications (user_id, job_key, payload, sent) VALUES (1, :key, :payload, false)'), {'key': identity_key('existing'), 'payload': encrypt('Existing report')})
        before = conn.execute(text('SELECT telegram_id, telegram_key, name FROM users')).one()
        notification = conn.execute(text('SELECT job_key, payload, sent FROM notifications')).one()
    migrate(engine); migrate(engine)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT telegram_id, telegram_key, name FROM users')).one() == before
        assert conn.execute(text('SELECT job_key, payload, sent FROM notifications')).one() == notification
        assert conn.scalar(text('SELECT max(version) FROM schema_versions')) == VERSION
        assert {'budget_limits', 'budget_alert_states'} <= set(inspect(conn).get_table_names())


def test_raising_limit_rearms_immediately_before_next_scheduler_tick(db):
    enable(db)
    wallet = account(db, opening='1000'); rule = create(db)
    spend(db, wallet, '90'); tick(db); delivered(db)
    limits.save(db, 1, BudgetLimitInput(category='Grocery', amount='200', currency='USD'), rule['id'])
    spend(db, wallet, '60')  # No intervening tick after editing the limit.
    tick(db)
    assert len(alerts(db)) == 2 and '25.00% remaining' in alerts(db)[-1].payload


def test_pending_alert_replaced_after_change_and_disabled_limits_omitted(db):
    enable(db)
    wallet = account(db, opening='1000'); rule = create(db)
    spend(db, wallet, '90'); tick(db)
    old = alerts(db)[0]
    limits.save(db, 1, BudgetLimitInput(category='Grocery', amount='50', currency='USD'), rule['id'])
    assert not limits.notification_active(db, old, NOW)
    tick(db)
    assert len(alerts(db)) == 2 and '180.00%' in alerts(db)[-1].payload
    create(db, category='Rent', amount='900', enabled=False)
    result = limits.snapshot(db, 1, '2024-01', include_disabled=True)
    assert len(result['budgets']) == 2 and Decimal(result['totals'][0]['limit']) == 50
    assert len(limits.snapshot(db, 1, '2024-01')['budgets']) == 1


def test_crypto_precision_missing_target_rate_and_currency_totals(db):
    enable(db)
    wallet = account(db, currency='BTC', kind='crypto', opening='1')
    create(db, amount='0.00000004', currency='BTC')
    spend(db, wallet, '0.00000003')
    tick(db)
    assert '0.00000001 BTC left from 0.00000004 BTC' in alerts(db)[0].payload
    create(db, category='Rent', amount='100', currency='EUR')
    usd = account(db)
    spend(db, usd, '20', category='Rent')
    result = limits.snapshot(db, 1, '2024-01', quote_fn=lambda c: None if c == 'EUR' else quote(c))
    assert result['budgets'][1]['stats']['missing'] == ['EUR']
    assert {row['currency'] for row in result['totals']} == {'BTC', 'EUR'}
    assert result['totals'][1]['spent'] is None


def test_debt_payments_and_archived_account_history_count(db):
    from backend.services import management
    from backend.core.schemas import NewDebt, DebtPayment
    from backend.persistence.models import Account
    enable(db)
    wallet = account(db, opening='100')
    create(db, category='Debts')
    debt = budget.create_debt(db, 1, NewDebt(name='Loan', currency='USD', amount='100'))
    transaction = budget.repay_debt(db, 1, debt, DebtPayment(account_id=wallet, amount='100', date=DAY))
    management.archive_account(db, 1, db.get(Account, wallet).group_id, True)
    assert Decimal(limits.snapshot(db, 1, '2024-01')['budgets'][0]['stats']['spent']) == 100
    budget.delete_transaction(db, 1, transaction)
    assert Decimal(limits.snapshot(db, 1, '2024-01')['budgets'][0]['stats']['spent']) == 0


def test_scheduler_and_delivery_use_existing_outbox_without_new_bot_command(db, monkeypatch):
    import asyncio
    from contextlib import contextmanager
    from backend.bot import worker
    from backend.services import rates
    enable(db)
    wallet = account(db, opening='1000'); create(db)
    spend(db, wallet, '90')
    prefs = reporting.get_preferences(db, 1)
    for name in ('daily', 'weekly', 'monthly'): prefs[name]['enabled'] = False
    reporting.save_preferences(db, 1, ReportPreferences(**prefs))
    monkeypatch.setattr(rates, 'quote', quote)
    scheduler.run_user_jobs(db, 1, NOW); scheduler.run_user_jobs(db, 1, NOW)
    assert len(alerts(db)) == 1
    @contextmanager
    def session(): yield db
    monkeypatch.setattr(worker, 'Session', session)
    messages = []
    async def telegram(client, method, payload): messages.append((method, payload))
    monkeypatch.setattr(worker, 'telegram', telegram)
    asyncio.run(worker.deliver_notifications(None))
    asyncio.run(worker.deliver_notifications(None))
    assert len(messages) == 1 and messages[0][0] == 'sendMessage'
    assert '10.00% remaining' in messages[0][1]['text']
    spend(db, wallet, '5'); scheduler.run_user_jobs(db, 1, NOW)
    limits.save_settings(db, 1, BudgetLimitSettings(enabled=False))
    asyncio.run(worker.deliver_notifications(None))
    assert len(messages) == 1


def test_budget_http_auth_validation_ownership_and_management(telegram_login):
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import StaticPool
    from backend.web.main import app
    from backend.persistence.database import Base, get_db
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def session():
        with Session(engine, expire_on_commit=False) as db: yield db
    app.dependency_overrides[get_db] = session
    headers = {'Origin': 'http://localhost:8000'}
    payload = dict(category='Grocery', amount='100', currency='USD', expense_currencies=['USD', 'ARS'])
    try:
        with TestClient(app) as client:
            assert client.get('/api/budget-limits').status_code == 401
            assert client.post('/api/budget-limits', headers=headers, json=payload).status_code == 401
            telegram_login(client)
            assert client.post('/api/budget-limits', headers={'Origin': 'https://attacker.invalid'}, json=payload).status_code == 403
            assert client.get('/api/budget-limits?month=invalid').status_code == 400
            assert client.post('/api/budget-limits', headers=headers, json={**payload, 'expense_currencies': []}).status_code == 422
            result = client.post('/api/budget-limits', headers=headers, json=payload)
            assert result.status_code == 201, result.text
            identifier = result.json()['id']
            assert client.post('/api/budget-limits/settings', headers=headers, json={'enabled': True}).status_code == 200
            result = client.get('/api/budget-limits?month=2024-01').json()
            assert result['settings']['enabled'] and result['budgets'][0]['stats']['percentage'] == '0.00'
            assert client.post(f'/api/budget-limits/{identifier}/edit', headers=headers, json={**payload, 'amount': '200'}).json()['amount'] == '200'
            telegram_login(client, telegram_id=222)
            assert client.get('/api/budget-limits').json()['budgets'] == []
            for action, body in [('edit', payload), ('delete', {}), ('reset-alerts', {})]:
                result = client.post(f'/api/budget-limits/{identifier}/{action}', headers=headers, json=body)
                assert result.status_code == 400 and result.json()['detail'] == 'Budget limit not found.'
            telegram_login(client)
            assert client.post(f'/api/budget-limits/{identifier}/reset-alerts', headers=headers, json={}).json()['month'] == '2024-01'
            assert client.post(f'/api/budget-limits/{identifier}/delete', headers=headers, json={}).status_code == 200
            assert client.get('/api/budget-limits').json()['budgets'] == []
    finally:
        app.dependency_overrides.clear()
