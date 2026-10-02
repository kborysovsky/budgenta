"""Record currency exchanges at an explicitly agreed rate, without fetching prices."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from uuid import uuid4

from backend.core.schemas import Exchange
from backend.persistence.models import Entry
from backend.services import budget


def preview(db, user_id, data: Exchange):
    budget.check_date(db, user_id, data.date)
    source = budget.owned_account(db, user_id, data.source_id)
    destination = budget.owned_account(db, user_id, data.destination_id)
    if source.currency == destination.currency:
        raise budget.BudgetError('Choose different currencies for an exchange. Use Transfer for the same currency.')
    budget.validate_amount(source.currency, data.amount)
    if budget.balance(db, source.id) < data.amount:
        raise budget.BudgetError('Not enough funds to exchange.')
    places = 8 if destination.currency in ('BTC', 'ETH') else 6 if destination.currency in ('USDT', 'TRX') else 2
    rate = data.rate
    if data.received is not None:
        budget.validate_amount(destination.currency, data.received)
        # The actual received amount is authoritative; never recalculate it from
        # a displayed rate, which may be a repeating decimal or very small.
        with localcontext() as context:
            context.prec = 18
            rate = data.received / data.amount
    with localcontext() as context:
        context.prec = 80
        received = (data.received if data.received is not None else data.amount * rate).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP)
        approximate_rate = data.received is not None and rate * data.amount != received
    if received <= 0:
        raise budget.BudgetError('The received amount rounds to zero. Increase the amount or rate.')
    if received >= Decimal('1e18'):
        raise budget.BudgetError('The received amount is too large.')
    return dict(source_id=source.id, destination_id=destination.id,
                source=source.name, destination=destination.name,
                source_currency=source.currency, destination_currency=destination.currency,
                amount=format(data.amount, 'f'), rate=format(rate, 'f'),
                rate_calculated=data.received is not None, rate_approximate=approximate_rate,
                received=format(received, 'f'), date=data.date.isoformat())


def exchange(db, user_id, data: Exchange, *, commit=True):
    budget.lock_user(db, user_id)
    result = preview(db, user_id, data)
    operation_id = str(uuid4())
    note = (f"{result['source']} → {result['destination']}; "
            f"1 {result['source_currency']} {'≈' if result['rate_approximate'] else '='} {result['rate']} {result['destination_currency']}")
    if result['rate_calculated']:
        note += f" (calculated from {result['received']} {result['destination_currency']} received)"
    for account_id, amount in [(data.source_id, -data.amount), (data.destination_id, Decimal(result['received']))]:
        db.add(Entry(account_id=account_id, operation_id=operation_id, kind='exchange',
                     amount=amount, date=data.date, category='Exchange', note=note))
    db.flush()
    if commit:
        db.commit()
    return {**result, 'operation_id': operation_id}
