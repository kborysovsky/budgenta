"""Budget use cases shared by HTTP and Telegram; no transport dependencies."""
import calendar
from collections import defaultdict
from datetime import date
from decimal import Decimal
from sqlalchemy import select
from uuid import uuid4
from backend.services import expense_breakdown
from backend.core.calendar import today
from backend.core.money import flow_totals, flow_lines
from backend.services import categories
from backend.services.categories import EXPENSE_CATEGORIES
from backend.persistence.models import Account, Entry, MonthClose, User, Debt, Goal, SavingsRule, SavingsRun, AccountGroup, GoalSavings

FIAT_CURRENCIES = ["USD", "EUR", "ARS", "UAH"]
CRYPTO_CURRENCIES = ["USDT", "TRX", "BTC", "ETH"]
CURRENCIES = {"cash": FIAT_CURRENCIES, "card": FIAT_CURRENCIES, "debit": FIAT_CURRENCIES, "paypal": ["USD", "EUR", "ARS"], "crypto": CRYPTO_CURRENCIES, "savings": FIAT_CURRENCIES + CRYPTO_CURRENCIES}

class BudgetError(ValueError):
    pass

def month_bounds(month):
    try:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        end = date(y, m, calendar.monthrange(y, m)[1])
        if start.strftime("%Y-%m") != month:
            raise ValueError()
        return start, end
    except (ValueError, TypeError):
        raise BudgetError("Use a valid month in YYYY-MM format.")

def lock_user(db, user_id):
    # Serialize all financial writes per owner, including closing a month.
    db.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()

def check_date(db, user_id, day):
    if day > today():
        raise BudgetError("Future transactions are not supported.")
    last = max(closed_months(db, user_id), default=None)
    if last and day.strftime("%Y-%m") <= last:
        raise BudgetError("This period is closed. Add an adjustment in an open month.")

def owned_account(db, user_id, account_id, *, allow_archived=False):
    account = db.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    if not account:
        raise BudgetError("Account not found.")
    if not allow_archived and account.group_id and db.get(AccountGroup,account.group_id).archived:
        raise BudgetError('Restore this archived account before using it.')
    return account

def validate_amount(currency, amount):
    places = 8 if currency in ("BTC", "ETH") else 6 if currency in ("TRX", "USDT") else 2
    if not amount.is_finite() or amount != amount.quantize(Decimal(10) ** -places):
        raise BudgetError(f"{currency} allows at most {places} decimal places.")

def closed_months(db, user_id):
    return db.scalars(select(MonthClose.month).where(MonthClose.user_id == user_id)).all()

def balance(db, account_id):
    return sum(db.scalars(select(Entry.amount).where(Entry.account_id == account_id, Entry.deleted == False)).all(), Decimal(0))

def accounts(db, user_id, *, include_archived=False):
    rows = db.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.id)).all()
    return [dict(id=a.id, group_id=a.group_id, name=a.name, kind=a.kind, currency=a.currency, balance=format(balance(db, a.id), '.8f' if a.currency in ('BTC', 'ETH') else '.6f')) for a in rows if include_archived or not a.group_id or not db.get(AccountGroup,a.group_id).archived]

def create_account(db, user_id, data):
    lock_user(db, user_id)
    check_date(db, user_id, data.date)
    if data.currency not in CURRENCIES[data.kind]:
        raise BudgetError("Currency is not supported for this account type.")
    if not data.name.strip():
        raise BudgetError("Give the account a name.")
    validate_amount(data.currency, data.opening_balance)
    group = AccountGroup(user_id=user_id, name=data.name.strip(), kind=data.kind)
    db.add(group)
    db.flush()
    account = Account(user_id=user_id, group_id=group.id, name=data.name.strip(), kind=data.kind, currency=data.currency)
    db.add(account)
    db.flush()
    db.add(Entry(account_id=account.id, kind="opening", operation_id=str(uuid4()), amount=data.opening_balance, date=data.date, category="Opening balance"))
    db.commit()
    return account.id

def add_entry(db, user_id, data, *, commit=True):
    lock_user(db, user_id)
    check_date(db, user_id, data.date)
    account = owned_account(db, user_id, data.account_id)
    validate_amount(account.currency, data.amount)
    # Negative card balances represent money owed; cash/wallets cannot overdraw.
    if data.kind == "expense" and account.kind != "card" and balance(db, account.id) < data.amount:
        raise BudgetError("Not enough funds in this account.")
    category = categories.resolve(db, user_id, data.kind, data.category, save=data.save_category)
    entry = Entry(account_id=account.id, operation_id=str(uuid4()), kind=data.kind, amount=data.amount if data.kind == "income" else -data.amount, date=data.date, category=category, note=data.note)
    db.add(entry)
    db.flush()
    if commit:
        db.commit()
    return entry.id

def transfer(db, user_id, data, *, commit=True):
    lock_user(db, user_id)
    check_date(db, user_id, data.date)
    source = owned_account(db, user_id, data.source_id)
    destination = owned_account(db, user_id, data.destination_id)
    if source.id == destination.id or source.currency != destination.currency:
        raise BudgetError("Choose two different accounts with the same currency.")
    validate_amount(source.currency, data.amount)
    if balance(db, source.id) < data.amount:
        raise BudgetError("Not enough funds to transfer.")
    operation_id = str(uuid4())
    for account, amount, other in [(source, -data.amount, destination), (destination, data.amount, source)]:
        db.add(Entry(account_id=account.id, operation_id=operation_id, kind="transfer", amount=amount, date=data.date, category="Transfer", note=f"Transfer with {other.name}"))
    db.flush()
    if commit:
        db.commit()
    return operation_id

def monthly(db, user_id, month):
    start, end = month_bounds(month)
    rows = db.execute(select(Entry, Account).join(Account).where(Account.user_id == user_id, Entry.deleted == False)).all()
    rows = sorted((row for row in rows if start <= row[0].date <= end), key=lambda row: (row[0].date, row[0].id), reverse=True)
    transactions = []
    for entry, account in rows:
        transactions.append(dict(id=entry.id, account_id=account.id, group_id=account.group_id, account_kind=account.kind, account=account.name, currency=account.currency, kind=entry.kind, amount=str(entry.amount), date=entry.date.isoformat(), category=entry.category, note=entry.note, debt_id=entry.debt_id, deletable=not bool(entry.reversal_issue), deletion_issue=entry.reversal_issue))
    result = flow_totals(((a.currency, e.kind, e.amount) for e, a in rows), include_empty=True)
    closed = month in closed_months(db, user_id)
    return dict(month=month, closed=closed, totals=result, transactions=transactions)

def close_month(db, user_id, month):
    lock_user(db, user_id)
    _, end = month_bounds(month)
    if end >= today():
        raise BudgetError("A month can be closed after its last day.")
    latest = max(closed_months(db, user_id), default=None)
    if latest and month <= latest:
        raise BudgetError("Close months in chronological order; this period is already locked.")
    db.add(MonthClose(user_id=user_id, month=month))
    db.commit()
    return monthly(db, user_id, month)

def savings(db, user_id):
    months = sorted(closed_months(db, user_id), reverse=True)
    return [dict(month=month, totals=monthly(db, user_id, month)["totals"]) for month in months]

def owned_record(db, model, user_id, record_id):
    record = db.scalar(select(model).where(model.id == record_id, model.user_id == user_id))
    if not record:
        raise BudgetError('Record not found.')
    return record

def debts(db, user_id, *, include_archived=False):
    rows = db.scalars(select(Debt).where(Debt.user_id == user_id).order_by(Debt.id.desc())).all()
    return [dict(id=d.id, archived=d.archived, name=d.name, currency=d.currency, amount=str(d.amount), paid=str(d.paid), remaining=str(d.amount-d.paid), due_date=d.due_date.isoformat() if d.due_date else None, note=d.note) for d in rows if include_archived or not d.archived]

def create_debt(db, user_id, data):
    lock_user(db, user_id)
    if not data.name.strip():
        raise BudgetError('Give the debt a name.')
    validate_amount(data.currency, data.amount)
    debt = Debt(user_id=user_id, **data.model_dump())
    db.add(debt)
    db.commit()
    return debt.id

def repay_debt(db, user_id, debt_id, data):
    from backend.core.schemas import NewEntry
    lock_user(db, user_id)
    debt = owned_record(db, Debt, user_id, debt_id)
    if debt.archived: raise BudgetError('Restore the debt before paying it.')
    account = owned_account(db, user_id, data.account_id)
    if account.currency != debt.currency:
        raise BudgetError('Repay from an account in the debt currency.')
    if data.amount > debt.amount-debt.paid:
        raise BudgetError('Payment exceeds the remaining debt.')
    entry_id = add_entry(db, user_id, NewEntry(account_id=account.id, kind='expense', amount=data.amount, date=data.date, category='Debts', note=f'Repayment: {debt.name}'), commit=False)
    db.get(Entry, entry_id).debt_id = debt.id
    debt.paid += data.amount
    db.commit()
    return entry_id

def goals(db, user_id, *, include_archived=False):
    from backend.services.management import goal_record
    rows = db.scalars(select(Goal).where(Goal.user_id == user_id).order_by(Goal.id.desc())).all()
    return [goal_record(db,g) for g in rows if include_archived or not g.archived]


def create_goal(db, user_id, data):
    lock_user(db, user_id)
    if not data.name.strip():
        raise BudgetError('Give the goal a name.')
    validate_amount(data.currency, data.target)
    validate_amount(data.currency, data.saved)
    from backend.services.management import validate_goal_links, replace_goal_links
    ids = validate_goal_links(db,user_id,data.currency,data.savings_account_ids)
    goal = Goal(user_id=user_id, **data.model_dump(exclude={'savings_account_ids'}))
    db.add(goal)
    db.flush()
    replace_goal_links(db,goal,ids)
    db.commit()
    return goal.id

def update_goal(db, user_id, goal_id, data):
    lock_user(db, user_id)
    goal = owned_record(db, Goal, user_id, goal_id)
    if goal.archived: raise BudgetError('Restore the goal before editing it.')
    if db.scalar(select(GoalSavings.id).where(GoalSavings.goal_id == goal.id)):
        raise BudgetError('This goal follows linked savings. Deposit or withdraw money to update its progress.')
    validate_amount(goal.currency, data.saved)
    goal.saved = data.saved
    db.commit()


def transaction(db, user_id, entry_id):
    entry = db.scalar(select(Entry).join(Account).where(Entry.id == entry_id, Account.user_id == user_id))
    if not entry:
        raise BudgetError('Transaction not found.')
    return entry

def delete_transaction(db, user_id, entry_id):
    """Undo an entire operation atomically; tombstones preserve scheduled-run identity."""
    lock_user(db, user_id)
    entry = transaction(db, user_id, entry_id)
    if entry.deleted:
        return  # repeat requests cannot reverse a debt twice
    if entry.reversal_issue:
        raise BudgetError(entry.reversal_issue)
    entries = db.scalars(select(Entry).join(Account).where(Account.user_id == user_id, Entry.operation_id == entry.operation_id, Entry.deleted == False)).all() if entry.operation_id else [entry]
    if any(e.reversal_issue for e in entries):
        raise BudgetError('This legacy operation needs its links repaired before deletion.')
    deltas = defaultdict(Decimal)
    for item in entries:
        deltas[item.account_id] += item.amount
    for account_id, amount in deltas.items():
        account = owned_account(db, user_id, account_id, allow_archived=True)
        if account.kind != 'card' and balance(db, account_id) - amount < 0:
            raise BudgetError('Deleting this would overdraw an account. Undo dependent spending or withdrawals first.')
    debt_changes = defaultdict(Decimal)
    for item in entries:
        if item.debt_id:
            debt_changes[item.debt_id] -= item.amount
    linked_debts = {}
    for debt_id, payment in debt_changes.items():
        debt = owned_record(db, Debt, user_id, debt_id)
        if payment <= 0 or debt.paid < payment:
            raise BudgetError('Debt repayment links are inconsistent; deletion was cancelled.')
        linked_debts[debt_id] = debt
    for debt_id, payment in debt_changes.items():
        linked_debts[debt_id].paid -= payment
        if linked_debts[debt_id].paid < linked_debts[debt_id].amount: linked_debts[debt_id].archived = False
    for item in entries:
        item.deleted = True
    db.flush()
    for account_id in deltas:
        wallet = owned_account(db,user_id,account_id,allow_archived=True)
        if wallet.group_id and balance(db,account_id) != 0:
            db.get(AccountGroup,wallet.group_id).archived = False
    db.commit()


def expense_report(db, user_id, month, *, quote_fn=None):
    report = monthly(db, user_id, month)
    amounts = defaultdict(Decimal)
    for entry in report['transactions']:
        if entry['kind'] == 'expense':
            amounts[(entry['currency'], entry['category'])] -= Decimal(entry['amount'])
    report.update(expense_breakdown.summarize(amounts, quote_fn=quote_fn))
    return report


def report_text(report):
    lines = [f"Expense report · {report['month']}"]
    lines += flow_lines(report['totals'])
    lines += expense_breakdown.lines(report)
    if not any(Decimal(t['expenses']) for t in report['totals']):
        lines.append('No expenses recorded in this month.')
    lines.append('Savings deposits and withdrawals are transfers, not expenses. Later corrections appear in the latest report.')
    return '\n'.join(lines)


def savings_rules(db, user_id, *, include_archived=False):
    rows = db.scalars(select(SavingsRule).where(SavingsRule.user_id == user_id).order_by(SavingsRule.id)).all()
    result = []
    for rule in rows:
        if rule.archived and not include_archived: continue
        source = owned_account(db, user_id, rule.source_id, allow_archived=True)
        target = owned_account(db, user_id, rule.destination_id, allow_archived=True)
        runs = db.scalars(select(SavingsRun).where(SavingsRun.rule_id == rule.id).order_by(SavingsRun.id.desc()).limit(3)).all()
        result.append(dict(id=rule.id, archived=rule.archived, source_id=source.id, destination_id=target.id, source=source.name, destination=target.name, currency=source.currency, mode=rule.mode, amount=str(rule.amount) if rule.amount is not None else None, day=rule.day, next_run=rule.next_run.isoformat(), active=bool(rule.active), recent_runs=[dict(date=r.scheduled_date.isoformat(), result=('Deleted; savings transfer reversed.' if r.operation_id and db.scalar(select(Entry.id).where(Entry.operation_id == r.operation_id, Entry.deleted == True)) else r.result)) for r in runs]))
    return result


def create_savings_rule(db, user_id, data):
    from backend.core.calendar import scheduled_date, next_month
    lock_user(db, user_id)
    source = owned_account(db, user_id, data.source_id)
    target = owned_account(db, user_id, data.destination_id)
    if target.kind != 'savings' or source.kind == 'savings' or source.currency != target.currency:
        raise BudgetError('Choose a spending account and a savings account in the same currency.')
    if data.amount is not None:
        validate_amount(source.currency, data.amount)
    due = scheduled_date(today().replace(day=1), data.day)
    if due < today():
        due = scheduled_date(next_month(due), data.day)
    rule = SavingsRule(user_id=user_id, next_run=due, **data.model_dump())
    db.add(rule)
    db.commit()
    return rule.id


def set_savings_rule(db, user_id, rule_id, enabled):
    from backend.core.calendar import scheduled_date, next_month
    lock_user(db, user_id)
    rule = owned_record(db, SavingsRule, user_id, rule_id)
    if rule.archived: raise BudgetError('Restore this rule before resuming it.')
    if enabled:
        from backend.services.management import validate_rule
        validate_rule(db,user_id,rule)
    rule.active = int(enabled)
    if enabled:
        # Resuming never backfills the months intentionally paused.
        while rule.next_run < today():
            rule.next_run = scheduled_date(next_month(rule.next_run), rule.day)
    db.commit()


def move_savings(db, user_id, data):
    from backend.core.schemas import Transfer
    lock_user(db, user_id)
    source = owned_account(db, user_id, data.source_id)
    target = owned_account(db, user_id, data.destination_id)
    if 'savings' not in (source.kind, target.kind):
        raise BudgetError('Choose a savings account to deposit into or withdraw from.')
    amount = balance(db, source.id) if data.mode == 'remainder' else data.amount
    if amount is None or amount <= 0:
        raise BudgetError('There is no positive balance to move.')
    return transfer(db, user_id, Transfer(source_id=source.id, destination_id=target.id, amount=amount, date=data.date))


def account_groups(db, user_id, *, include_archived=False):
    wallets = accounts(db, user_id, include_archived=include_archived)
    groups = db.scalars(select(AccountGroup).where(AccountGroup.user_id == user_id).order_by(AccountGroup.id)).all()
    from backend.services.reporting import get_preferences
    order = get_preferences(db,user_id)['accounts_page']['order']
    positions = {identifier: index for index,identifier in enumerate(order)}
    groups.sort(key=lambda g: (positions.get(g.id,len(order)),g.id))
    return [dict(id=g.id, archived=g.archived, name=g.name, kind=g.kind, balances=[a for a in wallets if a['group_id'] == g.id]) for g in groups if include_archived or not g.archived]


def create_account_group(db, user_id, data):
    lock_user(db, user_id)
    check_date(db, user_id, data.date)
    if not data.name.strip():
        raise BudgetError('Give the account a name.')
    currencies = [b.currency for b in data.balances]
    if len(currencies) != len(set(currencies)):
        raise BudgetError('Choose each currency only once.')
    for item in data.balances:
        if item.currency not in CURRENCIES[data.kind]:
            raise BudgetError('Currency is not supported for this account type.')
        validate_amount(item.currency, item.opening_balance)
    group = AccountGroup(user_id=user_id, name=data.name.strip(), kind=data.kind)
    db.add(group)
    db.flush()
    for item in data.balances:
        _add_currency(db, group, item, data.date)
    db.commit()
    return group.id


def _add_currency(db, group, data, day):
    wallet = Account(user_id=group.user_id, group_id=group.id, name=group.name, kind=group.kind, currency=data.currency)
    db.add(wallet)
    db.flush()
    db.add(Entry(account_id=wallet.id, kind='opening', operation_id=str(uuid4()), amount=data.opening_balance, date=day, category='Opening balance'))
    return wallet.id


def add_currency(db, user_id, group_id, data):
    lock_user(db, user_id)
    check_date(db, user_id, data.date)
    group = owned_record(db, AccountGroup, user_id, group_id)
    if group.archived: raise BudgetError('Restore this account before adding a currency.')
    if data.currency not in CURRENCIES[group.kind]:
        raise BudgetError('Currency is not supported for this account type.')
    wallets = db.scalars(select(Account).where(Account.group_id == group.id)).all()
    if any(w.currency == data.currency for w in wallets):
        raise BudgetError('This account already has that currency.')
    validate_amount(data.currency, data.opening_balance)
    identifier = _add_currency(db, group, data, data.date)
    db.commit()
    return identifier


def merge_accounts(db, user_id, data):
    from sqlalchemy import update
    from backend.services import reporting
    lock_user(db, user_id)
    source = owned_record(db, AccountGroup, user_id, data.source_id)
    target = owned_record(db, AccountGroup, user_id, data.destination_id)
    if source.archived or target.archived: raise BudgetError('Restore both accounts before merging them.')
    if source.id == target.id or source.kind != target.kind:
        raise BudgetError('Choose two different accounts of the same type.')
    targets = {a.currency: a for a in db.scalars(select(Account).where(Account.group_id == target.id))}
    source_wallets = db.scalars(select(Account).where(Account.group_id == source.id)).all()
    # Validate every currency before changing any relationship.
    for wallet in source_wallets:
        existing = targets.get(wallet.currency)
        if existing:
            left = db.scalar(select(GoalSavings).where(GoalSavings.account_id == wallet.id))
            right = db.scalar(select(GoalSavings).where(GoalSavings.account_id == existing.id))
            if left and right and left.goal_id != right.goal_id:
                raise BudgetError('These savings balances fund different goals. Unlink one goal before merging.')
    for wallet in source_wallets:
        existing = targets.get(wallet.currency)
        if existing:
            left = db.scalar(select(GoalSavings).where(GoalSavings.account_id == wallet.id))
            right = db.scalar(select(GoalSavings).where(GoalSavings.account_id == existing.id))
            if left:
                if right: db.delete(left)
                else: left.account_id = existing.id
            db.flush()
            db.execute(update(Entry).where(Entry.account_id == wallet.id).values(account_id=existing.id))
            db.execute(update(SavingsRule).where(SavingsRule.user_id == user_id, SavingsRule.source_id == wallet.id).values(source_id=existing.id))
            db.execute(update(SavingsRule).where(SavingsRule.user_id == user_id, SavingsRule.destination_id == wallet.id).values(destination_id=existing.id))
            db.delete(wallet)
        else:
            wallet.group_id = target.id
            wallet.name = target.name
            targets[wallet.currency] = wallet
    # Explicit report selections continue to include the merged account.
    preferences = reporting.get_preferences(db, user_id)
    for section in ('daily', 'weekly', 'monthly', 'dashboard', 'current_state'):
        ids = preferences[section]['account_ids']
        if ids is not None and source.id in ids:
            preferences[section]['account_ids'] = list(dict.fromkeys(target.id if i == source.id else i for i in ids))
    preferences['accounts_page']['order'] = list(dict.fromkeys(target.id if i == source.id else i for i in preferences['accounts_page']['order']))
    reporting.store_preferences(db, user_id, preferences)
    db.flush()
    db.delete(source)
    db.commit()
    return target.id
