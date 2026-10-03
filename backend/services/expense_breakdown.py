"""Category shares of all filtered expenses, valued in a common currency."""
from backend.core.i18n import tr, category_label
from collections import defaultdict
from decimal import Decimal, localcontext
from backend.core.money import expense_percentage
from backend.services import rates


def summarize(amounts, quote_fn=None):
    """Amounts are keyed by (currency, category); keep original money for display."""
    totals = defaultdict(Decimal)
    for (currency, _), amount in amounts.items():
        totals[currency] += amount
    valuation = rates.valuation([{'currency': c, 'balance': str(v)} for c, v in sorted(totals.items())], quote_fn=quote_fn)
    quotes = {row['currency']: Decimal(row['usd_rate']) for row in valuation['quotes']}
    complete = valuation['complete']
    grouped = {}
    rows = []
    # Calculate shares before rounding USD amounts, including tiny crypto expenses.
    with localcontext() as context:
        context.prec = 60
        total_usd = sum((amount * quotes[c] for c, amount in totals.items() if c in quotes), Decimal(0))
        for (currency, category), amount in sorted(amounts.items(), key=lambda row: (row[0][0], -row[1], row[0][1].casefold())):
            usd = amount * quotes[currency] if currency in quotes else Decimal(0)
            rows.append(dict(currency=currency, category=category, amount=str(amount),
                             percentage=expense_percentage(usd, total_usd) if complete else None))
            group = grouped.setdefault(category, {'category': category, 'amounts': [], 'usd': Decimal(0)})
            group['amounts'].append({'currency': currency, 'amount': str(amount)})
            group['usd'] += usd
        groups = sorted(grouped.values(), key=lambda row: (-row['usd'] if complete else Decimal(0), row['category'].casefold()))
        summary = [dict(category=row['category'], amounts=row['amounts'],
                        percentage=expense_percentage(row['usd'], total_usd) if complete else None) for row in groups]
    return {'categories': rows, 'category_totals': summary, 'expense_valuation': valuation}


def lines(report):
    if not report.get('category_totals'):
        return []
    result = [tr('Expenses by category (% of total expenses across currencies)')]
    for row in report['category_totals']:
        amounts = ' + '.join(f"{rates.report_amount(a['amount'])} {a['currency']}" for a in row['amounts'])
        share = f"{row['percentage']}%" if row['percentage'] is not None else tr('percentage unavailable')
        result.append(f"{category_label(row['category'], 'expense')}: {amounts} · {share}")
    valuation = report['expense_valuation']
    if not valuation['complete']:
        result.append(tr('Percentages unavailable: missing expense exchange rates for ') + ', '.join(valuation['missing']) + '.')
    else:
        result.append(tr('Shares use total expenses converted to USD at current rates.'))
    if valuation['stale']:
        result.append(tr('Expense percentages use cached exchange rates; estimates may be out of date.'))
    return result
