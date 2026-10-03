"""Optional category budgets. Ledger reads and durable alerts; never block an expense."""
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_HALF_UP
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.core.encryption import identity_key
from backend.core.i18n import tr, category_label, localized
from backend.core.money import expense_percentage
from backend.persistence.models import BudgetLimit, BudgetAlertState, Entry, Account, Notification
from backend.services import budget, categories, reporting, rates

THRESHOLDS = (25, 15, 10, 5, 0)


def category_key(name):
    return ' '.join(name.split()).casefold()


def reached_thresholds(row):
    # Use unrounded values, including for tiny crypto limits and FX estimates.
    with localcontext() as context:
        context.prec = 80
        return [threshold for threshold in THRESHOLDS
                if Decimal(row['stats']['remaining']) * 100 <= Decimal(row['amount']) * threshold]


def current_month(db, user_id, now=None):
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo(reporting.get_preferences(db, user_id)['timezone'])).strftime('%Y-%m')


def owned(db, user_id, identifier):
    record = db.scalar(select(BudgetLimit).where(BudgetLimit.id == identifier, BudgetLimit.user_id == user_id, BudgetLimit.deleted == False))
    if not record:
        raise budget.BudgetError('Budget limit not found.')
    return record


def definitions(db, user_id):
    return db.scalars(select(BudgetLimit).where(BudgetLimit.user_id == user_id, BudgetLimit.deleted == False).order_by(BudgetLimit.id)).all()


def serialize(record):
    return dict(id=record.id, category=record.category, amount=str(record.amount), currency=record.currency,
                enabled=bool(record.enabled), expense_currencies=json.loads(record.expense_currencies))


def _state(db, identifier, month, create=False):
    key = identity_key(f'budget-month:{identifier}:{month}')
    record = db.scalar(select(BudgetAlertState).where(BudgetAlertState.state_key == key))
    if record is None and create:
        record = BudgetAlertState(budget_id=identifier, state_key=key,
                                 payload=json.dumps(dict(month=month, seen=[], cycle=str(uuid4()))))
        db.add(record)
        db.flush()
    return record


def cancel_pending(db, user_id, identifier=None):
    query = select(Notification).where(Notification.user_id == user_id, Notification.budget_id.is_not(None), Notification.sent == False)
    if identifier is not None:
        query = query.where(Notification.budget_id == identifier)
    for notification in db.scalars(query).all():
        context = json.loads(notification.budget_context)
        state = _state(db, notification.budget_id, context['month'])
        if state:
            payload = json.loads(state.payload)
            payload['seen'] = [threshold for threshold in payload['seen'] if threshold not in context['crossed']]
            # Old outbox keys must not prevent a fresh alert after re-enabling.
            payload['cycle'] = str(uuid4())
            state.payload = json.dumps(payload)
        notification.sent = True


def save_settings(db, user_id, data):
    budget.lock_user(db, user_id)
    prefs = reporting.get_preferences(db, user_id)
    prefs['budget_limits'] = data.model_dump()
    reporting.store_preferences(db, user_id, prefs)
    if not data.enabled or not data.notifications_enabled:
        cancel_pending(db, user_id)
    db.commit()
    return prefs['budget_limits']


def save(db, user_id, data, identifier=None):
    budget.lock_user(db, user_id)
    budget.validate_amount(data.currency, data.amount)
    name = categories.resolve(db, user_id, 'expense', data.category)
    key = identity_key(f'budget-category:{user_id}:{category_key(name)}')
    duplicate = db.scalar(select(BudgetLimit).where(BudgetLimit.category_key == key))
    if duplicate and duplicate.id != identifier:
        raise budget.BudgetError('This category already has a budget. Edit its existing limit.')
    record = owned(db, user_id, identifier) if identifier is not None else BudgetLimit(user_id=user_id)
    changed = identifier is not None and (record.category_key != key or record.amount != data.amount or record.currency != data.currency
                                        or set(json.loads(record.expense_currencies) or []) != set(data.expense_currencies or []))
    category_changed = identifier is not None and record.category_key != key
    if identifier is not None and (changed or not data.enabled):
        cancel_pending(db, user_id, identifier)
    record.category_key, record.category = key, name
    record.amount, record.currency = data.amount, data.currency
    record.enabled, record.expense_currencies = int(data.enabled), json.dumps(data.expense_currencies)
    db.add(record)
    db.flush()
    if changed:
        # Re-arm only on an actual configuration change, never just a ledger deletion
        # or an FX fluctuation. Evaluate at save time so a new expense before the
        # next scheduler tick cannot hide a threshold that became relevant again.
        state = _state(db, record.id, current_month(db, user_id))
        if state:
            payload = json.loads(state.payload)
            payload.update(cycle=str(uuid4()), rearm_pending=True)
            if category_changed:
                payload['seen'] = []
            result = snapshot(db, user_id, current_month(db, user_id), include_disabled=True)
            row = next((row for row in result['budgets'] if row['id'] == record.id), None)
            if row and row['stats'] and row['stats']['complete'] and not row['stats']['stale']:
                reached = reached_thresholds(row)
                payload['seen'] = [threshold for threshold in payload['seen'] if threshold in reached]
                payload.pop('rearm_pending', None)
            state.payload = json.dumps(payload)
    db.commit()
    return serialize(record)


def remove(db, user_id, identifier):
    budget.lock_user(db, user_id)
    record = owned(db, user_id, identifier)
    cancel_pending(db, user_id, identifier)
    record.deleted, record.enabled = True, 0
    # Preserve alert history while freeing the category for a new budget.
    record.category_key = identity_key(f'deleted-budget:{record.id}:{uuid4()}')
    db.commit()


def reset_alerts(db, user_id, identifier, now=None):
    budget.lock_user(db, user_id)
    owned(db, user_id, identifier)
    cancel_pending(db, user_id, identifier)
    month = current_month(db, user_id, now)
    state = _state(db, identifier, month, create=True)
    state.payload = json.dumps(dict(month=month, seen=[], cycle=str(uuid4())))
    db.commit()
    return {'month': month}


def snapshot(db, user_id, month, *, config=None, quote_fn=None, include_disabled=False):
    start, end = budget.month_bounds(month)
    settings = reporting.get_preferences(db, user_id)['budget_limits']
    records = definitions(db, user_id)
    if not include_disabled:
        records = [record for record in records if record.enabled]
    rows = [serialize(record) for record in records]
    if not settings['enabled']:
        return dict(month=month, settings=settings, budgets=[dict(row, stats=None) for row in rows] if include_disabled else [], totals=[])
    if config:
        rows = [row for row in rows if row['currency'] not in config.get('excluded_currencies', [])]
    # Dates, kinds, category names and currencies are encrypted, so filter after
    # the SQL ownership boundary. Archived accounts still contribute their history.
    expenses = defaultdict(lambda: defaultdict(Decimal))
    ledger = db.execute(select(Entry, Account).join(Account, Entry.account_id == Account.id)
                        .where(Account.user_id == user_id, Entry.deleted == False)).all() if rows else []
    with localcontext() as context:
        context.prec = 60
        for entry, account in ledger:
            if entry.kind != 'expense' or not start <= entry.date <= end:
                continue
            if config and not reporting.matches({'kind': account.kind, 'group_id': account.group_id, 'currency': account.currency}, config):
                continue
            expenses[category_key(entry.category)][account.currency] -= entry.amount
        needed = set()
        for row in rows:
            native = {currency: amount for currency, amount in expenses[category_key(row['category'])].items()
                      if amount and (row['expense_currencies'] is None or currency in row['expense_currencies'])}
            row['native_spending'] = [{'currency': c, 'amount': str(a)} for c, a in sorted(native.items())]
            if any(currency != row['currency'] for currency in native):
                needed.update(native)
                needed.add(row['currency'])
        # Fetch each public quote once, concurrently, regardless of category count.
        valuation = rates.valuation([dict(currency=c, balance='1') for c in sorted(needed)], quote_fn=quote_fn)
        quotes = {q['currency']: q for q in valuation['quotes']}
        totals = {}
        for row in rows:
            used, missing, spent = set(), set(), Decimal(0)
            for native in row['native_spending']:
                source, target, amount = native['currency'], row['currency'], Decimal(native['amount'])
                if source == target:
                    spent += amount
                else:
                    used.update((source, target))
                    missing.update(c for c in (source, target) if c not in quotes)
                    if source in quotes and target in quotes:
                        spent += amount * Decimal(quotes[source]['usd_rate']) / Decimal(quotes[target]['usd_rate'])
            limit = Decimal(row['amount'])
            row['stats'] = dict(spent=None if missing else str(spent), remaining=None if missing else str(limit-spent),
                                percentage=None if missing else expense_percentage(spent, limit), exceeded=False if missing else spent > limit,
                                complete=not missing, stale=any(quotes[c]['stale'] for c in used if c in quotes),
                                missing=sorted(missing), quotes=[quotes[c] for c in sorted(used) if c in quotes])
            if row['enabled']:
                total = totals.setdefault(row['currency'], dict(limit=Decimal(0), spent=Decimal(0), complete=True, stale=False))
                total['limit'] += limit
                total['spent'] += spent
                total['complete'] &= not missing
                total['stale'] |= row['stats']['stale']
        summary = [dict(currency=c, limit=str(v['limit']), spent=str(v['spent']) if v['complete'] else None,
                        remaining=str(v['limit']-v['spent']) if v['complete'] else None, complete=v['complete'], stale=v['stale'])
                   for c, v in sorted(totals.items())]
    return dict(month=month, settings=settings, budgets=rows, totals=summary)


def overview(db, user_id, month=None, quote_fn=None):
    current = current_month(db, user_id)
    return {**snapshot(db, user_id, month or current, quote_fn=quote_fn, include_disabled=True), 'current_month': current}


def amount_text(value, currency):
    precision = 8 if currency in ('BTC', 'ETH') else 6 if currency in ('USDT', 'TRX') else 2
    with localcontext() as context:
        context.prec = 60
        rounded = Decimal(value).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
        return f'{abs(rounded) if rounded == 0 else rounded:.{precision}f} {currency}'


def lines(result):
    if not result['settings']['enabled'] or not result['budgets']:
        return []
    output = [tr('Budget Limits · {month}', month=result['month'])]
    for row in result['budgets']:
        stats, currency = row['stats'], row['currency']
        output.append(category_label(row['category'], 'expense'))
        if not stats['complete']:
            output.append(tr('Budget usage unavailable: missing rates for {currencies}.', currencies=', '.join(stats['missing'])))
            continue
        output.append(f"{amount_text(stats['spent'], currency)} / {amount_text(row['amount'], currency)}")
        fill = min(20, max(0, int(Decimal(stats['percentage']) / 5)))
        output.append('█' * fill + '░' * (20-fill) + ' ' + tr('{percentage}% used', percentage=stats['percentage']))
        output.append(tr('Remaining: {amount}', amount=amount_text(stats['remaining'], currency)))
        if stats['exceeded']:
            output.append(tr('Over budget'))
        if stats['stale']:
            output.append(tr('Cached exchange rates used; estimate may be out of date.'))
    output.append(tr('Budget usage follows this report’s account and currency filters.'))
    return output


def notification_text(row, month, threshold):
    stats, currency = row['stats'], row['currency']
    values = dict(category=category_label(row['category'], 'expense'), amount=amount_text(stats['remaining'], currency), limit=amount_text(row['amount'], currency))
    if threshold == 0:
        text = tr('{category} budget: fully used — {percentage}% used; remaining {amount} from {limit}.', percentage=stats['percentage'], **values)
        if stats['exceeded']:
            text = tr('{category} budget: exceeded — {percentage}% used; remaining {amount} from {limit}.', percentage=stats['percentage'], **values)
    else:
        # A jump can land between thresholds; use the actual remaining percentage.
        remaining = expense_percentage(Decimal(stats['remaining']), Decimal(row['amount']))
        text = tr('{category} budget: {percentage}% remaining — {amount} left from {limit}.', percentage=remaining, **values)
    return text + '\n' + tr('Budget Limits · {month}', month=month)


@localized
def check_alerts(db, user_id, now=None, quote_fn=None):
    """Called under the owner's scheduler lock; outbox and seen state commit together."""
    budget.lock_user(db, user_id)
    settings = reporting.get_preferences(db, user_id)['budget_limits']
    if not settings['enabled'] or not settings['notifications_enabled']:
        return
    from backend.services.scheduler import notify
    month = current_month(db, user_id, now)
    result = snapshot(db, user_id, month, quote_fn=quote_fn)
    for row in result['budgets']:
        stats = row['stats']
        if not stats['complete'] or stats['stale']:
            continue
        record = _state(db, row['id'], month, create=True)
        state = json.loads(record.payload)
        # Compare exact values; a rounded 75.00% must not fire a threshold early.
        reached = reached_thresholds(row)
        if state.pop('rearm_pending', False):
            state['seen'] = [threshold for threshold in state['seen'] if threshold in reached]
        crossed = [threshold for threshold in reached if threshold not in state['seen']]
        if crossed:
            threshold = min(crossed)
            notify(db, user_id, f"budget:{row['id']}:{month}:{state['cycle']}:{threshold}", notification_text(row, month, threshold),
                   budget_id=row['id'], budget_context=json.dumps(dict(month=month, crossed=crossed)))
            state['seen'] = sorted(set(state['seen']) | set(crossed))
        record.payload = json.dumps(state)


def notification_active(db, notification, now=None):
    """Recheck cancellations after the transport loaded its queue, before delivery."""
    if notification.sent:
        return False
    if notification.budget_id is None:
        return True
    settings = reporting.get_preferences(db, notification.user_id)['budget_limits']
    record = db.get(BudgetLimit, notification.budget_id)
    return bool(settings['enabled'] and settings['notifications_enabled'] and record and not record.deleted and record.enabled
                and json.loads(notification.budget_context)['month'] == current_month(db, notification.user_id, now))
