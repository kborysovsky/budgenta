"""Durable monthly savings and report jobs, driven by the Telegram worker."""
from backend.core.i18n import tr, localized
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.persistence.models import User, SavingsRule, SavingsRun, ReportSettings, Notification
from backend.core.encryption import identity_key
from backend.core.calendar import today, next_month, scheduled_date, timezone_name
from backend.services import budget as service
from backend.services import reporting
from backend.core.schemas import Transfer


def settings(db, user_id, current_day=None):
    current_day = current_day or today()
    value = db.get(ReportSettings, user_id)
    if not value:
        value = ReportSettings(user_id=user_id, next_report=current_day.replace(day=1) if current_day.day == 1 else next_month(current_day), enabled=1)
        db.add(value)
        db.flush()
    return value


def report_settings(db, user_id):
    service.lock_user(db, user_id)
    value = settings(db, user_id)
    db.commit()
    return {'enabled': bool(value.enabled), 'next_report': value.next_report.isoformat(), 'timezone': timezone_name(), 'time': '09:00'}


def set_reports(db, user_id, enabled):
    service.lock_user(db, user_id)
    value = settings(db, user_id)
    value.enabled = int(enabled)
    preferences = reporting.get_preferences(db, user_id)
    preferences['monthly']['enabled'] = enabled
    reporting.store_preferences(db, user_id, preferences)
    if enabled and value.next_report < today().replace(day=1):
        value.next_report = today().replace(day=1) if today().day == 1 else next_month(today())
    db.commit()


def notify(db, user_id, key, message):
    job_key = identity_key('notification:'+key)
    if not db.scalar(select(Notification.id).where(Notification.job_key == job_key)):
        db.add(Notification(user_id=user_id, job_key=job_key, payload=message))


@localized
def run_user_jobs(db, user_id, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(timezone_name()))
    current_day = now.date()
    service.lock_user(db, user_id)
    rules = db.scalars(select(SavingsRule).where(SavingsRule.user_id == user_id).order_by(SavingsRule.id)).all()
    for rule in rules:
        if not rule.active or rule.archived:
            continue
        # Fixed-date jobs run at 09:00; month-end jobs at 23:59.
        threshold = (23, 59) if rule.day == 0 else (9, 0)
        due = rule.next_run
        if due > current_day or (due == current_day and (now.hour, now.minute) < threshold):
            continue
        key = identity_key(f'savings:{rule.id}:{due:%Y-%m}')
        if db.scalar(select(SavingsRun.id).where(SavingsRun.run_key == key)):
            rule.next_run = scheduled_date(next_month(due), rule.day)
            continue
        operation = None
        source = service.owned_account(db, user_id, rule.source_id)
        target = service.owned_account(db, user_id, rule.destination_id)
        amount = rule.amount if rule.mode == 'fixed' else max(Decimal(0), service.balance(db, source.id))
        if due < current_day.replace(day=1) and not (rule.day == 0 and current_day == due + timedelta(days=1)):
            # Do not unexpectedly drain several missed months after a long outage.
            result = tr('Skipped: the scheduled month passed while the worker was offline.')
        elif amount <= 0:
            result = tr('Skipped: no positive balance left to save.')
        else:
            try:
                operation = service.transfer(db, user_id, Transfer(source_id=source.id, destination_id=target.id, amount=amount, date=current_day), commit=False)
                result = tr('Saved {amount} {currency} from {source} to {target}.', amount=amount, currency=source.currency, source=source.name, target=target.name)
            except service.BudgetError as exc:
                result = tr('Skipped: ')+tr(str(exc))
        db.add(SavingsRun(rule_id=rule.id, run_key=key, scheduled_date=due, result=result, operation_id=operation))
        notify(db, user_id, key, f"{tr('Monthly savings')} · {due.isoformat()}\n{result}")
        # Advance only this occurrence; missed months are each marked skipped on
        # later ticks, so new monthly balances are never swept retroactively.
        rule.next_run = scheduled_date(next_month(due), rule.day)
    preference = settings(db, user_id, current_day)
    for frequency, occurrence in reporting.due_reports(db, user_id, now):
        month = (datetime.fromisoformat(occurrence).date().replace(day=1)-timedelta(days=1)).strftime('%Y-%m')
        key = f'report:{user_id}:{month}' if frequency == 'monthly' else f'report:{user_id}:{frequency}:{occurrence}'
        if not db.scalar(select(Notification.id).where(Notification.job_key == identity_key('notification:'+key))):
            notify(db, user_id, key, reporting.report_message(db, user_id, frequency, now))
        if frequency == 'monthly':
            preference.next_report = next_month(current_day)
    db.commit()


def tick(engine, now=None):
    from sqlalchemy.orm import Session
    with Session(engine) as db:
        ids = db.scalars(select(User.id)).all()
    # Shared persistent TRX quote: one refresh at/after 10:00 in each user's
    # configured timezone, plus an initial quote for a new installation.
    from backend.services import rates
    with Session(engine) as db:
        zones = {reporting.get_preferences(db, uid)['timezone'] for uid in ids}
        rates.refresh_trx(db, now=now, zones=zones or {timezone_name()})
    for user_id in ids:
        with Session(engine, expire_on_commit=False) as db:
            run_user_jobs(db, user_id, now)
