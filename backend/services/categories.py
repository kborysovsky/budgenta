"""Private, encrypted reusable categories, separate from transaction history."""
from sqlalchemy import select
from backend.persistence.models import SavedCategory

EXPENSE_CATEGORIES = ['Grocery', 'Outside Food', 'Self Care', 'Rent', 'Health', 'Clothes', 'Emergency', 'Debts', 'Leisure', 'Delivery', 'Home', 'Transport', 'Subscriptions']
INCOME_CATEGORIES = ['Salary', 'Freelance', 'Other']


def choices(db, user_id):
    result = {'expense': list(EXPENSE_CATEGORIES), 'income': list(INCOME_CATEGORIES)}
    rows = db.scalars(select(SavedCategory).where(SavedCategory.user_id == user_id).order_by(SavedCategory.id)).all()
    for row in rows:
        if row.name.casefold() not in {name.casefold() for name in result[row.kind]}:
            result[row.kind].append(row.name)
    return result


def resolve(db, user_id, kind, name, *, save=False):
    """Called inside the owner's financial write lock; never commits on its own."""
    name = ' '.join(name.split())
    existing = next((value for value in choices(db, user_id)[kind] if value.casefold() == name.casefold()), None)
    if existing:
        return existing
    if save:
        db.add(SavedCategory(user_id=user_id, kind=kind, name=name))
    return name
