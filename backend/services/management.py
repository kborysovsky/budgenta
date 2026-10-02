"""Account and planning lifecycle operations; ledger history remains reversible."""
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select, delete, or_
from backend.services import budget as service
from backend.persistence.models import Account, AccountGroup, Entry, Debt, Goal, GoalSavings, SavingsRule
from backend.core.calendar import today, scheduled_date, next_month


def active(record):
    if record.archived:
        raise service.BudgetError('Restore this archived record before editing it.')
    return record


def edit_account(db, uid, identifier, data):
    service.lock_user(db, uid)
    group = active(service.owned_record(db, AccountGroup, uid, identifier))
    name = data.name.strip()
    if not name: raise service.BudgetError('Give the account a name.')
    wallets = db.scalars(select(Account).where(Account.group_id == group.id)).all()
    ids = [a.id for a in wallets]
    if any(a.currency not in service.CURRENCIES[data.kind] for a in wallets):
        raise service.BudgetError('The selected type does not support all currencies in this account.')
    if data.kind != 'card' and any(service.balance(db,a.id) < 0 for a in wallets):
        raise service.BudgetError('Clear the negative balance before changing the account type.')
    if data.kind != group.kind:
        if db.scalar(select(GoalSavings.id).where(GoalSavings.account_id.in_(ids))):
            raise service.BudgetError('Unlink this savings account from its goals before changing its type.')
        rules = db.scalars(select(SavingsRule).where(SavingsRule.user_id == uid, SavingsRule.archived == False, or_(SavingsRule.source_id.in_(ids), SavingsRule.destination_id.in_(ids)))).all()
        if rules and ('savings' in (group.kind, data.kind)):
            raise service.BudgetError('Remove the connected savings rules before changing this account type.')
    group.name = name; group.kind = data.kind
    for wallet in wallets: wallet.name = name; wallet.kind = data.kind
    db.commit()


def archive_account(db, uid, identifier, archived):
    service.lock_user(db, uid)
    group = service.owned_record(db, AccountGroup, uid, identifier)
    if archived:
        ids = db.scalars(select(Account.id).where(Account.group_id == group.id)).all()
        if any(service.balance(db,i) != 0 for i in ids):
            raise service.BudgetError('Move or correct every currency balance to zero before archiving this account.')
        if db.scalar(select(GoalSavings.id).where(GoalSavings.account_id.in_(ids))):
            raise service.BudgetError('Unlink this savings account from its goals before archiving it.')
        for rule in db.scalars(select(SavingsRule).where(SavingsRule.user_id == uid, or_(SavingsRule.source_id.in_(ids), SavingsRule.destination_id.in_(ids)))):
            rule.active = 0
    group.archived = archived
    db.commit()


def correct_balance(db, uid, wallet_id, data):
    service.lock_user(db, uid)
    wallet = service.owned_account(db, uid, wallet_id)
    service.check_date(db, uid, data.date)
    service.validate_amount(wallet.currency, data.balance)
    if wallet.kind != 'card' and data.balance < 0:
        raise service.BudgetError('Only a card can have a negative balance.')
    difference = data.balance - service.balance(db, wallet.id)
    if difference:
        db.add(Entry(account_id=wallet.id, kind='adjustment', amount=difference, date=data.date,
                     category='Balance correction', note=data.note, operation_id=str(uuid4())))
    db.commit()


def edit_debt(db, uid, identifier, data):
    service.lock_user(db, uid)
    debt = active(service.owned_record(db, Debt, uid, identifier))
    if not data.name.strip(): raise service.BudgetError('Give the debt a name.')
    service.validate_amount(data.currency, data.amount)
    if data.amount < debt.paid:
        raise service.BudgetError('The debt amount cannot be less than the amount already repaid.')
    if debt.currency != data.currency and debt.paid:
        raise service.BudgetError('Undo repayments before changing the debt currency.')
    for key, value in data.model_dump().items(): setattr(debt,key,value)
    debt.name = debt.name.strip()
    db.commit()


def goal_links(db, goal_id):
    return db.scalars(select(GoalSavings).where(GoalSavings.goal_id == goal_id)).all()


def goal_saved(db, goal):
    links = goal_links(db, goal.id)
    return sum((service.balance(db,link.account_id) for link in links), Decimal(0)) if links else goal.saved


def goal_record(db, goal):
    links = goal_links(db,goal.id)
    wallets = [db.get(Account,link.account_id) for link in links]
    return dict(id=goal.id, name=goal.name, currency=goal.currency, target=str(goal.target),
                saved=str(goal_saved(db,goal)), archived=goal.archived,
                savings_account_ids=[a.id for a in wallets],
                linked_savings=[dict(id=a.id, name=a.name, currency=a.currency, balance=str(service.balance(db,a.id))) for a in wallets],
                due_date=goal.due_date.isoformat() if goal.due_date else None, note=goal.note)


def validate_goal_links(db, uid, currency, wallet_ids, goal_id=None):
    ids = list(dict.fromkeys(wallet_ids))
    for identifier in ids:
        wallet = service.owned_account(db,uid,identifier)
        if wallet.kind != 'savings' or wallet.currency != currency:
            raise service.BudgetError('Link active savings balances in the same currency as the goal.')
        existing = db.scalar(select(GoalSavings).where(GoalSavings.account_id == identifier))
        if existing and existing.goal_id != goal_id:
            raise service.BudgetError('This savings balance is already attached to another goal. Unlink it there first.')
    return ids


def replace_goal_links(db, goal, ids):
    db.execute(delete(GoalSavings).where(GoalSavings.goal_id == goal.id))
    db.flush()
    for identifier in ids: db.add(GoalSavings(goal_id=goal.id, account_id=identifier))


def edit_goal(db, uid, identifier, data):
    service.lock_user(db, uid)
    goal = active(service.owned_record(db,Goal,uid,identifier))
    if not data.name.strip(): raise service.BudgetError('Give the goal a name.')
    service.validate_amount(data.currency,data.target)
    service.validate_amount(data.currency,data.saved)
    ids = validate_goal_links(db,uid,data.currency,data.savings_account_ids,goal.id)
    for key,value in data.model_dump(exclude={'savings_account_ids'}).items(): setattr(goal,key,value)
    goal.name = goal.name.strip()
    replace_goal_links(db,goal,ids)
    db.commit()


def archive_planning(db, uid, model, identifier, archived):
    service.lock_user(db,uid)
    record = service.owned_record(db,model,uid,identifier)
    if model is Goal and archived and not record.archived:
        record.saved = goal_saved(db,record)
        replace_goal_links(db,record,[])
    record.archived = archived
    db.commit()


def validate_rule(db, uid, data):
    source = service.owned_account(db,uid,data.source_id)
    target = service.owned_account(db,uid,data.destination_id)
    if source.kind == 'savings' or target.kind != 'savings' or source.currency != target.currency:
        raise service.BudgetError('Choose a spending account and a savings account in the same currency.')
    if data.amount is not None: service.validate_amount(source.currency,data.amount)


def edit_rule(db, uid, identifier, data):
    service.lock_user(db,uid)
    rule = active(service.owned_record(db,SavingsRule,uid,identifier))
    validate_rule(db,uid,data)
    for key,value in data.model_dump().items(): setattr(rule,key,value)
    due = scheduled_date(today().replace(day=1), data.day)
    if due < today(): due = scheduled_date(next_month(due),data.day)
    rule.next_run = due
    db.commit()


def archive_rule(db, uid, identifier, archived):
    service.lock_user(db,uid)
    rule = service.owned_record(db,SavingsRule,uid,identifier)
    rule.archived = archived
    rule.active = 0
    db.commit()
