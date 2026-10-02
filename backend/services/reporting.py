"""Encrypted report preferences and shared filtered reporting for web and bot."""
import json
from functools import cache
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.services import budget as service
from backend.services import rates
from backend.services import expense_breakdown
from backend.core.calendar import timezone_name, scheduled_date
from backend.core.money import flow_totals, flow_lines
from backend.persistence.models import Preferences, ReportSettings, Entry, Account, AccountGroup
from backend.core.schemas import ReportPreferences, CurrentStatePreferences


def get_preferences(db, user_id):
    record = db.get(Preferences, user_id)
    if record:
        data = json.loads(record.payload)
        if 'current_state' not in data:
            data['current_state'] = CurrentStatePreferences(**data.get('dashboard', {})).model_dump()
        return ReportPreferences(**data).model_dump()
    preferences = ReportPreferences(timezone=timezone_name()).model_dump()
    legacy = db.get(ReportSettings, user_id)
    if legacy:
        preferences['monthly']['enabled'] = bool(legacy.enabled)
    return preferences


def store_preferences(db, user_id, value):
    record = db.get(Preferences, user_id)
    if not record:
        record = Preferences(user_id=user_id)
        db.add(record)
    record.payload = json.dumps(value)


def save_preferences(db, user_id, data):
    service.lock_user(db, user_id)
    value = data.model_dump()
    existing = get_preferences(db, user_id)
    if 'main_currency' not in data.model_fields_set:
        value['main_currency'] = existing['main_currency']
    for section in ('current_state', 'accounts_page'):
        if section not in data.model_fields_set and not getattr(data,section).model_fields_set:
            value[section] = existing[section]
    allowed = set(db.scalars(select(AccountGroup.id).where(AccountGroup.user_id == user_id)))
    for section in ('daily', 'weekly', 'monthly', 'dashboard', 'current_state'):
        selected = value[section]['account_ids']
        if selected is not None and not set(selected) <= allowed:
            raise service.BudgetError('Choose only your own accounts.')
        if selected is not None:
            value[section]['account_ids'] = list(dict.fromkeys(selected))
    if not set(value['accounts_page']['order']) <= allowed:
        raise service.BudgetError('Choose only your own accounts for the display order.')
    value['accounts_page']['order'] = list(dict.fromkeys(value['accounts_page']['order']))
    store_preferences(db, user_id, value)
    legacy = db.get(ReportSettings, user_id)
    if legacy:
        legacy.enabled = int(value['monthly']['enabled'])
    db.commit()
    return value


def matches(account, config):
    return (account.get('currency') not in config.get('excluded_currencies', [])) and (config['include_savings'] or account['kind'] != 'savings') and (config['account_ids'] is None or account['group_id'] in config['account_ids'])


def selected_accounts(db, user_id, config, *, include_archived=False):
    return [a for a in service.accounts(db, user_id, include_archived=include_archived) if matches(a, config)]


def estimated_balance(db, user_id, *, dashboard=False, quote_fn=None):
    quote_fn = cache(quote_fn or rates.quote)
    preferences = get_preferences(db, user_id)
    accounts = selected_accounts(db, user_id, preferences['dashboard']) if dashboard else service.accounts(db, user_id)
    result = rates.balance_valuation(accounts, preferences['main_currency'], quote_fn=quote_fn)
    if dashboard:
        config = preferences['dashboard']
        details = {q['currency']: q for q in result['quotes'] if q['currency'] != 'USD' and q['currency'] not in config['excluded_currencies']} if config['include_rates'] else {}
        unavailable = []
        # UAH is also a dashboard reference quote when no UAH wallet is held.
        # Its availability must not change a total that did not need this rate.
        if config['include_rates'] and 'UAH' not in config['excluded_currencies'] and 'UAH' not in details:
            uah = quote_fn('UAH')
            if uah:
                details['UAH'] = {'currency': 'UAH', **uah}
            else:
                unavailable.append('UAH')
        result.update(display_quotes=list(details.values()), unavailable_reference_rates=unavailable)
    return result


def dashboard(db, user_id, month):
    config = get_preferences(db, user_id)['dashboard']
    report = service.monthly(db, user_id, month)
    report['transactions'] = [t for t in report['transactions'] if matches({'kind':t['account_kind'], 'group_id':t['group_id'], 'currency':t['currency']}, config)]
    report['totals'] = flow_totals(((t['currency'], t['kind'], t['amount']) for t in report['transactions']), include_empty=True)
    return report


def period_report(db, user_id, start, end, config, *, quote_fn=None):
    selected = selected_accounts(db, user_id, config, include_archived=True)
    ids = {a['id'] for a in selected}
    rows = db.scalars(select(Entry).where(Entry.account_id.in_(ids), Entry.deleted == False)).all()
    currencies = {a['id']: a['currency'] for a in selected}
    flows = []
    categories = defaultdict(Decimal)
    for entry in rows:
        if not start <= entry.date <= end: continue
        currency = currencies[entry.account_id]
        flows.append((currency, entry.kind, entry.amount))
        if entry.kind == 'expense':
            categories[(currency, entry.category)] -= entry.amount
    return {'start':start.isoformat(), 'end':end.isoformat(), 'accounts':selected_accounts(db,user_id,config),
            'totals':flow_totals(flows),
            **expense_breakdown.summarize(categories if config.get('include_categories', False) else {}, quote_fn=quote_fn)}


def monthly_report(db, user_id, month, *, quote_fn=None):
    start, end = service.month_bounds(month)
    result = period_report(db, user_id, start, end, get_preferences(db,user_id)['monthly'], quote_fn=quote_fn)
    return {**result, 'month':month, 'closed':month in service.closed_months(db,user_id)}


def category_lines(report):
    return expense_breakdown.lines(report)


def report_message(db, user_id, frequency, now=None, quote_fn=None):
    quote_fn = cache(quote_fn or rates.quote)
    prefs = get_preferences(db, user_id)
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(prefs['timezone']))
    current = now.date()
    end = current - timedelta(days=1)
    start = end if frequency == 'daily' else current-timedelta(days=7)
    if frequency == 'monthly':
        end = current.replace(day=1)-timedelta(days=1)
        start = end.replace(day=1)
    config = prefs[frequency]
    report = period_report(db, user_id, start, end, config, quote_fn=quote_fn)
    valuation = rates.balance_valuation(report['accounts'], prefs['main_currency'], quote_fn=quote_fn)
    lines = [f"{frequency.title()} report · {now:%Y-%m-%d %H:%M} ({prefs['timezone']})", rates.message(valuation, include_rates=config['include_rates']), f"Activity · {start} to {end}"]
    lines += flow_lines(report['totals']) or ['No income, expenses, or transfers in this period.']
    if config['include_categories']:
        lines += category_lines(report)
    lines.append('Savings '+('included.' if config['include_savings'] else 'excluded.'))
    return '\n'.join(lines)


def due_reports(db, user_id, now):
    """One occurrence per local day/week/month; no backlog after downtime."""
    prefs = get_preferences(db,user_id)
    local = now.astimezone(ZoneInfo(prefs['timezone']))
    for frequency in ('daily','weekly','monthly'):
        setting = prefs[frequency]
        hour, minute = map(int, setting['time'].split(':'))
        if not setting['enabled']: continue
        legacy = db.get(ReportSettings, user_id)
        if frequency == 'monthly' and not db.get(Preferences, user_id) and legacy and legacy.next_report > local.date(): continue
        day = local.date()
        if frequency == 'weekly': day -= timedelta(days=(day.weekday()-setting['weekday']) % 7)
        if frequency == 'monthly': day = scheduled_date(day.replace(day=1), setting['month_day'])
        due = datetime.combine(day, datetime.min.time(), tzinfo=local.tzinfo).replace(hour=hour, minute=minute)
        if local < due: continue
        # Don't send an old daily or weekly report if this week's scheduled day
        # passed. Monthly reports may catch up within the current month.
        if frequency in ('daily','weekly') and day != local.date(): continue
        yield frequency, day.isoformat()


def save_section(db, user_id, section, data):
    service.lock_user(db,user_id)
    preferences = get_preferences(db,user_id)
    preferences[section] = data.model_dump()
    return save_preferences(db,user_id,ReportPreferences(**preferences))


def save_main_currency(db, user_id, currency):
    service.lock_user(db, user_id)
    preferences = get_preferences(db, user_id)
    preferences['main_currency'] = currency
    return save_preferences(db, user_id, ReportPreferences(**preferences))


def current_state(db, user_id, now=None, quote_fn=None):
    quote_fn = cache(quote_fn or rates.quote)
    prefs = get_preferences(db,user_id)
    config = prefs['current_state']
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(prefs['timezone']))
    accounts = selected_accounts(db,user_id,config)
    result = rates.balance_valuation(accounts,prefs['main_currency'],quote_fn=quote_fn)
    lines = [f"Current state · {now:%Y-%m-%d %H:%M} ({prefs['timezone']})",
             rates.current_balance_message(result, include_rates=config['include_rates']),
             'Savings '+('included in balance.' if config['include_savings'] else 'excluded from balance.')]
    if config['include_monthly_summary']:
        monthly = period_report(db,user_id,now.date().replace(day=1),now.date(),config,quote_fn=quote_fn)
        lines += ['This month so far'] + (flow_lines(monthly['totals']) or ['No income, expenses, or transfers recorded this month.'])
        if config['include_categories']: lines += category_lines(monthly)
    if config['include_debts']:
        debts = [d for d in service.debts(db,user_id) if d['currency'] not in config['excluded_currencies']]
        lines += ['Debts (separate from account balance)'] + ([f"{d['name']}: {rates.report_amount(d['remaining'])} {d['currency']} remaining" for d in debts if Decimal(d['remaining'])>0] or ['No outstanding debts.'])
    if config['include_goals']:
        goals = [g for g in service.goals(db,user_id) if g['currency'] not in config['excluded_currencies']]
        lines += ['Goals'] + ([f"{g['name']}: {rates.report_amount(g['saved'])} / {rates.report_amount(g['target'])} {g['currency']}" for g in goals] or ['No active goals.'])
    return '\n'.join(lines)
