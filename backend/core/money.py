"""Decimal-only calculations shared by financial reports."""
from decimal import Decimal, ROUND_HALF_UP


def expense_percentage(amount, total):
    """Share of expenses measured in the same unit, rounded for display only."""
    if total <= 0:
        return '0.00'
    return str((amount * Decimal(100) / total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


FLOW_LABELS = (('expenses', 'spent'), ('income', 'income'),
               ('transfers_out', 'transferred out'), ('transfers_in', 'received from transfers'))


def flow_totals(rows, *, include_empty=False):
    """Sum signed ledger legs by currency; transfers never become income/expense.

    Rows are (currency, kind, amount) after ownership/date/account filters.
    Include empty preserves the legacy monthly ledger's opening-only currencies.
    """
    totals = {}
    for currency, kind, raw_amount in rows:
        if kind not in ('income', 'expense', 'transfer', 'exchange') and not include_empty:
            continue
        total = totals.setdefault(currency, {key: Decimal(0) for key, _ in FLOW_LABELS})
        amount = Decimal(raw_amount)
        if kind == 'income': total['income'] += amount
        elif kind == 'expense': total['expenses'] -= amount
        elif kind in ('transfer', 'exchange'):
            total['transfers_in' if amount > 0 else 'transfers_out'] += abs(amount)
    return [dict(currency=currency, **{key: str(value) for key, value in total.items()},
                 surplus=str(total['income'] - total['expenses'])) for currency, total in sorted(totals.items())]


def flow_lines(totals):
    """Readable original-currency statistics, omitting zero measures and rows."""
    lines = []
    for total in totals:
        parts = []
        for key, label in FLOW_LABELS:
            amount = Decimal(total.get(key, '0'))
            if amount == 0: continue
            rounded = amount.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            display = '<0.01' if rounded == 0 and amount > 0 else format(rounded, '.2f')
            parts.append(f'{label} {display}')
        if parts:
            lines.append(f"{total['currency']}: " + ' · '.join(parts))
    return lines
