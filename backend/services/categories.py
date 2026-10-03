"""Private, encrypted reusable categories, separate from transaction history."""
from sqlalchemy import select
from backend.persistence.models import SavedCategory

EXPENSE_CATEGORIES = ['Grocery', 'Outside Food', 'Self Care', 'Rent', 'Health', 'Clothes', 'Emergency', 'Debts', 'Leisure', 'Delivery', 'Home', 'Transport', 'Subscriptions']
INCOME_CATEGORIES = ['Salary', 'Freelance', 'Other']


def choices(db, user_id):
    from backend.services.reporting import get_preferences
    hidden = get_preferences(db, user_id)['hidden_categories']
    result = {'expense': list(EXPENSE_CATEGORIES), 'income': list(INCOME_CATEGORIES)}
    rows = db.scalars(select(SavedCategory).where(SavedCategory.user_id == user_id).order_by(SavedCategory.id)).all()
    for row in rows:
        if row.name.casefold() not in {name.casefold() for name in result[row.kind]}:
            result[row.kind].append(row.name)
    return {kind: [name for name in names if name.casefold() not in {v.casefold() for v in hidden[kind]}] for kind, names in result.items()}


def manage(db, user_id):
    active = choices(db, user_id)
    return {kind: [{'name': name, 'removed': name not in active[kind]} for name in dict.fromkeys([*defaults, *active[kind]])]
            for kind, defaults in [('expense', EXPENSE_CATEGORIES), ('income', INCOME_CATEGORIES)]}


def change(db, user_id, data):
    from backend.services import budget, reporting
    budget.lock_user(db, user_id)
    name = ' '.join(data.name.split())
    prefs = reporting.get_preferences(db, user_id)
    defaults = EXPENSE_CATEGORIES if data.kind == 'expense' else INCOME_CATEGORIES
    builtin = next((v for v in defaults if v.casefold() == name.casefold()), None)
    rows = db.scalars(select(SavedCategory).where(SavedCategory.user_id == user_id)).all()
    matches = [r for r in rows if r.kind == data.kind and r.name.casefold() == name.casefold()]
    if not builtin and not matches:
        raise budget.BudgetError('Category not found.')
    if builtin:
        hidden = [v for v in prefs['hidden_categories'][data.kind] if v.casefold() != builtin.casefold()]
        if data.removed:
            hidden.append(builtin)
        prefs['hidden_categories'][data.kind] = hidden
        reporting.store_preferences(db, user_id, prefs)
    if data.removed:
        for row in matches:
            db.delete(row)
    db.commit()
    return manage(db, user_id)


def resolve(db, user_id, kind, name, *, save=False):
    """Called inside the owner's financial write lock; never commits on its own."""
    name = ' '.join(name.split())
    existing = next((value for value in choices(db, user_id)[kind] if value.casefold() == name.casefold()), None)
    if existing:
        return existing
    if save:
        from backend.services import reporting
        prefs = reporting.get_preferences(db, user_id)
        hidden = prefs['hidden_categories'][kind]
        restored = next((v for v in hidden if v.casefold() == name.casefold()), None)
        if restored:
            prefs['hidden_categories'][kind] = [v for v in hidden if v != restored]
            reporting.store_preferences(db, user_id, prefs)
            return restored
        db.add(SavedCategory(user_id=user_id, kind=kind, name=name))
    return name
