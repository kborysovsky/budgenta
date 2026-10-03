"""Owner-scoped monthly downloads. Export values, never executable spreadsheet formulas."""
import csv
import io
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_HALF_UP
from functools import cache
from sqlalchemy import select
from backend.core.i18n import tr, localized, category_label
from backend.core.money import flow_totals
from backend.persistence.models import Entry, Account
from backend.services import budget, reporting, rates, expense_breakdown, budget_limits

ACTIVITY = ('income', 'expense', 'transfer', 'exchange')
KIND_LABELS = {'income': 'Income', 'expense': 'Expense', 'transfer': 'Transfer', 'exchange': 'Exchange'}


def safe_csv_cell(value):
    if isinstance(value, (Decimal, int)):
        return format(value, 'f') if isinstance(value, Decimal) else str(value)
    text = '' if value is None else str(value)
    # Quoting alone does not prevent spreadsheet formula execution. Inspect past
    # leading whitespace/control characters; preserve the original text after '.
    candidate = re.sub(r'^[\s\x00-\x1f\ufeff]+', '', text)
    if candidate.startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
        return "'" + text
    return text


def csv_bytes(tables):
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\r\n')
    for table in tables:
        writer.writerow([safe_csv_cell(table['name'])])
        writer.writerow([safe_csv_cell(value) for value in table['headers']])
        writer.writerows([safe_csv_cell(value) for value in row] for row in table['rows'])
        writer.writerow([])
    # Excel recognizes UTF-8 Cyrillic and accented Spanish without import setup.
    return output.getvalue().encode('utf-8-sig')


def table(name, headers, rows, **extra):
    return dict(name=tr(name), headers=[tr(h) for h in headers], rows=rows, **extra)


def budget_status(stats):
    if not stats['complete']:
        return tr('Estimate temporarily unavailable') + ': ' + ', '.join(stats['missing'])
    label = tr('Over budget') if stats['exceeded'] else tr('Fully used') if Decimal(stats['remaining']) == 0 else tr('Within budget')
    return label + ('; ' + tr('Cached exchange rates used; estimate may be out of date.') if stats['stale'] else '')


def flow_rows(rows, prefix=()):
    with localcontext() as context:
        context.prec = 60
        return [list(prefix) + [r['currency']] + [Decimal(r[key]) for key in ('income', 'expenses', 'surplus', 'transfers_out', 'transfers_in')]
                for r in flow_totals(rows)]


@localized
def monthly_tables(db, user_id, month, *, quote_fn=None):
    start, end = budget.month_bounds(month)
    prefs = reporting.get_preferences(db, user_id)
    config, main = prefs['monthly'], prefs['main_currency']
    rows = db.execute(select(Entry, Account).join(Account, Entry.account_id == Account.id)
                      .where(Account.user_id == user_id, Entry.deleted == False)).all()
    rows = sorted(((e, a) for e, a in rows if start <= e.date <= end and e.kind in ACTIVITY
                   and reporting.matches({'kind': a.kind, 'group_id': a.group_id, 'currency': a.currency}, config)),
                  key=lambda row: (row[0].date, row[0].id))
    quote_fn = cache(quote_fn or rates.quote)
    flows, daily, accounts, categories = [], defaultdict(list), defaultdict(list), defaultdict(Decimal)
    with localcontext() as context:
        context.prec = 60
        for entry, account in rows:
            flow = (account.currency, entry.kind, entry.amount)
            flows.append(flow); daily[entry.date].append(flow)
            accounts[(account.id, account.name)].append(flow)
            if entry.kind == 'expense': categories[(account.currency, entry.category)] -= entry.amount
        breakdown = expense_breakdown.summarize(categories if config['include_categories'] else {}, quote_fn=quote_fn)
        target = quote_fn(main) if config['include_categories'] and any(c != main for c, _ in categories) else None
        quotes = {q['currency']: q for q in breakdown['expense_valuation']['quotes']}
        if target and config['include_categories']: quotes[main] = {'currency': main, **target}
        def converted(amounts):
            result = Decimal(0)
            for item in amounts:
                amount, currency = Decimal(item['amount']), item['currency']
                if currency == main: result += amount
                elif currency in quotes and target:
                    result += amount * Decimal(quotes[currency]['usd_rate']) / Decimal(target['usd_rate'])
                else: return None
            precision = 8 if main in ('BTC', 'ETH') else 6 if main in ('USDT', 'TRX') else 2
            return result.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
        category_rows = []
        for row in breakdown['category_totals']:
            category_rows.append([category_label(row['category'], 'expense'),
                                  ' + '.join(f"{a['amount']} {a['currency']}" for a in row['amounts']),
                                  converted(row['amounts']), Decimal(row['percentage']) if row['percentage'] is not None else None])
    metadata = [
        [tr('Month'), month], [tr('Generated at (UTC)'), datetime.now(timezone.utc).isoformat(timespec='seconds')],
        [tr('Timezone'), prefs['timezone']], [tr('Main currency'), main], [tr('Transaction rows'), len(rows)],
        [tr('Expense transactions'), sum(e.kind == 'expense' for e, _ in rows)],
        [tr('Included accounts'), tr('All accounts (including future accounts)') if config['account_ids'] is None else ', '.join(sorted({a.name for _, a in rows})) or tr('None')],
        [tr('Excluded currencies'), ', '.join(config['excluded_currencies']) or tr('None')],
        [tr('Include savings'), tr('Yes') if config['include_savings'] else tr('No')],
        [tr('Notes'), tr('Manual balance corrections, opening balances, and deleted transactions are excluded.')],
        [tr('Notes'), tr('Transfers and exchanges appear as signed account movements linked by operation ID. They do not count as income or expenses.')],
        [tr('Notes'), tr('Estimates use current exchange rates, not historical transaction rates. Missing estimates are left blank.')],
        [tr('Notes'), tr('Excel preserves values exceeding 15 significant digits as text; CSV retains exact decimal values.')],
        [tr('Notes'), tr('Text beginning with spreadsheet formula characters is escaped for safe CSV opening.')],
    ]
    if breakdown['expense_valuation']['stale'] or (target and target['stale']):
        metadata.append([tr('Warning'), tr('Cached exchange rates used; estimate may be out of date.')])
    missing = breakdown['expense_valuation']['missing'] + ([main] if config['include_categories'] and categories and any(c != main for c, _ in categories) and target is None else [])
    if missing: metadata.append([tr('Missing exchange rates'), ', '.join(sorted(set(missing)))])
    headers = ['Currency', 'Income', 'Expenses', 'Income less expenses', 'Transferred out', 'Received from transfers']
    tables = [table('Report information', ['Field', 'Value'], metadata),
              table('Monthly totals', headers, flow_rows(flows))]
    if config['include_categories']:
        tables.append(table('Spending by category', ['Category', 'Original amounts', tr('Estimated spending') + f' ({main})', 'Share of total expenses (%)'], category_rows, chart='category', currency=main))
    tables += [table('Daily activity', ['Date'] + headers, [row for day, values in sorted(daily.items()) for row in flow_rows(values, (day.isoformat(),))]),
               table('Account activity', ['Account ID', 'Account'] + headers, [row for (identifier, name), values in sorted(accounts.items()) for row in flow_rows(values, (identifier, name))])]
    if config['include_budgets']:
        snapshot = budget_limits.snapshot(db, user_id, month, config=config, quote_fn=quote_fn)
        if snapshot['settings']['enabled']:
            for row in snapshot['budgets']:
                for q in row['stats']['quotes']: quotes[q['currency']] = q
            tables.append(table('Budget Limits', ['Category', 'Currency', 'Budget', 'Spent', 'Remaining', 'Usage (%)', 'Status'],
                [[category_label(b['category'], 'expense'), b['currency'], Decimal(b['amount']),
                  Decimal(b['stats']['spent']) if b['stats']['spent'] is not None else None,
                  Decimal(b['stats']['remaining']) if b['stats']['remaining'] is not None else None,
                  Decimal(b['stats']['percentage']) if b['stats']['percentage'] is not None else None,
                  budget_status(b['stats'])]
                 for b in snapshot['budgets']]))
    if config['include_rates']:
        tables.append(table('Exchange rates', ['Currency', 'USD per unit', 'As of', 'Source', 'Status'],
                     [[c, Decimal(q['usd_rate']), q['as_of'], tr(q['source']), tr('Cached') if q['stale'] else tr('Current')] for c, q in sorted(quotes.items())]))
    tables.append(table('Transactions', ['Date', 'Type', 'Account', 'Currency', 'Signed amount', 'Category', 'Note', 'Transaction ID', 'Operation ID', 'Account ID', 'Debt ID'],
        [[e.date.isoformat(), tr(KIND_LABELS[e.kind]), a.name, a.currency, e.amount,
          category_label(e.category, e.kind) if e.kind in ('income', 'expense') else tr(KIND_LABELS[e.kind]),
          e.note, e.id, e.operation_id, a.id, e.debt_id] for e, a in rows]))
    return tables


def xlsx_bytes(tables):
    import xlsxwriter
    output = io.BytesIO()
    with xlsxwriter.Workbook(output, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False}) as workbook:
        workbook.set_properties({'title': 'Budgenta monthly report', 'author': 'Budgenta'})
        heading = workbook.add_format({'bold': True, 'bg_color': '#214F40', 'font_color': 'white', 'text_wrap': True, 'valign': 'vcenter'})
        money = workbook.add_format({'num_format': '#,##0.00######', 'valign': 'top'})
        wrapped = workbook.add_format({'text_wrap': True, 'valign': 'top'})
        for index, item in enumerate(tables, 1):
            if len(item['rows']) > 1048575:
                raise budget.BudgetError('This report is too large for Excel. Download CSV instead.')
            # Prefix ensures localized/truncated sheet names remain unique.
            name = f"{index} {item['name']}"[:31]
            sheet = workbook.add_worksheet(name)
            sheet.hide_gridlines(2); sheet.freeze_panes(1, 0)
            sheet.set_column(0, len(item['headers']) - 1, 22)
            sheet.set_column(0, 0, 25)
            if len(item['headers']) == 2: sheet.set_column(1, 1, 90, wrapped)
            sheet.set_row(0, 32)
            for column, label in enumerate(item['headers']): sheet.write_string(0, column, label, heading)
            for row_number, row in enumerate(item['rows'], 1):
                for column, value in enumerate(row):
                    if value is None: continue
                    if isinstance(value, (Decimal, int)):
                        digits = format(value, 'f').lstrip('-').replace('.', '').lstrip('0').rstrip('0')
                        # Excel numbers have 15 significant digits. Preserve larger
                        # exact amounts as text instead of silently rounding them.
                        if len(digits) <= 15: sheet.write_number(row_number, column, value, money if isinstance(value, Decimal) else None)
                        else: sheet.write_string(row_number, column, format(value, 'f'), wrapped)
                    else: sheet.write_string(row_number, column, str(value), wrapped)
            if item['rows']: sheet.autofilter(0, 0, len(item['rows']), len(item['headers']) - 1)
            if item.get('chart') == 'category' and item['rows'] and all(r[3] is not None for r in item['rows']):
                chart = workbook.add_chart({'type': 'bar'})
                chart.add_series({'name': item['headers'][3], 'categories': [name, 1, 0, len(item['rows']), 0],
                                  'values': [name, 1, 3, len(item['rows']), 3],
                                  'fill': {'color': '#52734D'}, 'border': {'none': True},
                                  'data_labels': {'value': True, 'num_format': '0.00"%"'}})
                chart.set_title({'name': item['name']})
                chart.set_x_axis({'name': item['headers'][3], 'min': 0, 'max': 100})
                chart.set_y_axis({'reverse': True}); chart.set_legend({'none': True})
                chart.set_size({'width': 720, 'height': max(360, min(1600, len(item['rows']) * 32 + 100))})
                sheet.insert_chart('G2', chart)
    return output.getvalue()
