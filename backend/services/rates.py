"""Public exchange quotes. No account values or user information leave the app."""
from backend.core.i18n import tr
import os
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from functools import cache
from concurrent.futures import ThreadPoolExecutor
import httpx

_CACHE = {}
TTL = 300
MAX_FALLBACK_AGE = 86400

def positive(value):
    result = Decimal(str(value))
    if not result.is_finite() or result <= 0:
        raise ValueError('Invalid rate')
    return result

def fetch_quote(currency):
    with httpx.Client(timeout=8) as client:
        if currency == 'ARS':
            r = client.get('https://dolarapi.com/v1/dolares/blue')
            r.raise_for_status(); data = r.json()
            rate = positive(data['venta'])
            return {'usd_rate': str(Decimal(1)/rate), 'display_rate': f'1 USD = {rate} ARS (blue venta)', 'as_of': data['fechaActualizacion'], 'source': 'DolarApi', 'url': 'https://dolarapi.com/docs/argentina/operations/get-dolar-blue'}
        if currency == 'EUR':
            r = client.get('https://api.frankfurter.dev/v1/latest', params={'base':'EUR','symbols':'USD'})
            r.raise_for_status(); data = r.json()
            rate = positive(data['rates']['USD'])
            return {'usd_rate': str(rate), 'display_rate': f'1 EUR = {rate} USD', 'as_of': data['date'], 'source': 'Frankfurter', 'url': 'https://frankfurter.dev/v1/'}
        if currency == 'UAH':
            r = client.get('https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange', params={'valcode':'USD', 'date':datetime.now(timezone.utc).strftime('%Y%m%d'), 'json':''})
            r.raise_for_status()
            data = next(row for row in r.json() if row['cc'] == 'USD')
            rate = positive(data['rate'])
            timestamp = datetime.strptime(data['exchangedate'], '%d.%m.%Y').date().isoformat()
            return {'usd_rate': str(Decimal(1)/rate), 'display_rate': f'1 USD = {rate} UAH (official)', 'as_of': timestamp, 'source': 'National Bank of Ukraine', 'url': 'https://bank.gov.ua/en/markets/exchangerates'}
        coin = {'USDT': 'tether', 'TRX': 'tron', 'BTC': 'bitcoin', 'ETH': 'ethereum'}[currency]
        headers = {'x-cg-demo-api-key': os.getenv('COINGECKO_API_KEY')} if os.getenv('COINGECKO_API_KEY') else {}
        r = client.get('https://api.coingecko.com/api/v3/simple/price', params={'ids':coin, 'vs_currencies':'usd', 'include_last_updated_at':'true'}, headers=headers)
        r.raise_for_status(); data = r.json()[coin]
        rate = positive(data['usd'])
        timestamp = datetime.fromtimestamp(data['last_updated_at'], timezone.utc).isoformat()
        return {'usd_rate': str(rate), 'display_rate': f'1 {currency} = {rate} USD', 'as_of': timestamp, 'source': 'CoinGecko', 'url': 'https://www.coingecko.com/'}

def quote(currency):
    if currency == 'USD':
        return {'usd_rate':'1','source':'USD','as_of':None,'stale':False,'display_rate':'1 USD = 1 USD'}
    if currency == 'TRX':
        stored = stored_trx()
        if stored is not None: return stored
    cached = _CACHE.get(currency)
    if cached and time.time()-cached[0] < TTL:
        return {**cached[1], 'stale':False}
    try:
        result = fetch_quote(currency)
        # Weekends/holidays are valid quote dates; reject implausibly old feeds.
        timestamp = datetime.fromisoformat(result['as_of'].replace('Z','+00:00'))
        timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp
        age = (datetime.now(timezone.utc)-timestamp).total_seconds()
        if age < -3600 or age > (7*86400 if currency in ('ARS','EUR','UAH') else 3600):
            raise ValueError('Quote is too old')
        _CACHE[currency] = (time.time(), result)
        return {**result, 'stale':False}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation, StopIteration):
        if cached and time.time()-cached[0] < MAX_FALLBACK_AGE:
            return {**cached[1], 'stale':True}
        return None

def valuation(accounts, quote_fn=None):
    quote_fn = quote_fn or quote
    currencies = sorted({a['currency'] for a in accounts if Decimal(a['balance']) != 0})
    with ThreadPoolExecutor(max_workers=5) as pool:
        quotes = dict(zip(currencies, pool.map(quote_fn, currencies)))
    total = Decimal(0); missing = []; used = []; rows = []
    for currency in currencies:
        value = quotes[currency]
        if value is None:
            missing.append(currency)
        else:
            used.append({'currency':currency, **value})
    for account in accounts:
        amount = Decimal(account['balance'])
        rate = quotes.get(account['currency'])
        converted = amount*Decimal(rate['usd_rate']) if rate else (Decimal(0) if amount==0 else None)
        if converted is not None:
            total += converted
        rows.append({**account, 'usd_value': str(converted.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) if converted is not None else None})
    return {'total_usd': str(total.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)), 'complete':not missing, 'missing':missing, 'stale':any(q['stale'] for q in used), 'quotes':used, 'accounts':rows, 'fetched_at':datetime.now(timezone.utc).isoformat()}

def report_amount(value):
    """Round display only; stored balances and USD valuation retain precision."""
    amount = Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return format(abs(amount) if amount == 0 else amount, '.2f')


def balance_valuation(accounts, currency='USD', quote_fn=None):
    """Value the total in the chosen unit without rounding the USD intermediate.

    Keep USD values for the existing account ordering. Same-currency money needs
    no external rate; a missing target rate must never produce a fake zero total.
    """
    quote_fn = cache(quote_fn or quote)
    result = valuation(accounts, quote_fn)
    if currency == 'USD':
        return {**result, 'currency': currency, 'total': result['total_usd'], 'unavailable': False}
    foreign = any(Decimal(a['balance']) != 0 and a['currency'] != currency for a in accounts)
    target = quote_fn(currency) if foreign else None
    quotes = {q['currency']: q for q in result['quotes']}
    if target:
        quotes[currency] = {'currency': currency, **target}
    missing = [c for c in result['missing'] if c != currency]
    unavailable = foreign and target is None
    if unavailable:
        missing.append(currency)
    with localcontext() as context:
        context.prec = 60
        total = Decimal(0)
        for account in accounts:
            amount = Decimal(account['balance'])
            if account['currency'] == currency:
                total += amount
            elif amount and target and account['currency'] in quotes:
                total += amount * Decimal(quotes[account['currency']]['usd_rate']) / Decimal(target['usd_rate'])
        precision = 8 if currency in ('BTC', 'ETH') else 6 if currency in ('USDT', 'TRX') else 2
        total = total.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
    return {**result, 'currency': currency, 'total': None if unavailable else format(abs(total) if total == 0 else total, f'.{precision}f'),
            'complete': not missing, 'unavailable': unavailable, 'missing': missing,
            'quotes': list(quotes.values()), 'stale': any(q['stale'] for q in quotes.values())}


def balance_heading(result):
    currency = result.get('currency', 'USD')
    if result.get('unavailable'):
        return tr('Estimated balance in {currency}: unavailable (exchange rate missing)', currency=currency)
    heading = tr('Estimated balance') if result['complete'] else tr('Partial balance (rates missing)')
    return f"{heading}: {result.get('total', result['total_usd'])} {currency}"


def message(result, *, include_rates=True):
    lines = [balance_heading(result), tr('Account balances; separate debt records are not deducted.')]
    lines += [f"{a['name']}: {report_amount(a['balance'])} {a['currency']}" for a in result['accounts']]
    if include_rates:
        lines += [f"{display_quote(q)} · {tr(q['source'])} · {q['as_of']}" for q in result['quotes'] if q['currency']!='USD']
    if result['missing']:
        lines.append((tr('Rates unavailable: ') if result.get('unavailable') else tr('Excluded, rate unavailable: '))+', '.join(result['missing']))
    if result['stale']:
        lines.append(tr('Warning: cached rates used because a provider is unavailable.'))
    return '\n'.join(lines)


def refresh_trx(db, now=None, zones=None, fetch_fn=None):
    """Persist a shared quote; scheduled successes survive web/worker restarts."""
    import json
    from zoneinfo import ZoneInfo
    from backend.persistence.models import MarketQuote
    from backend.core.calendar import timezone_name
    now = now or datetime.now(timezone.utc)
    record = db.get(MarketQuote, 'TRX')
    payload = json.loads(record.payload) if record else {'days': {}}
    due = {zone: now.astimezone(ZoneInfo(zone)).date().isoformat() for zone in zones or {timezone_name()}
           if now.astimezone(ZoneInfo(zone)).hour >= 10 and payload.get('days', {}).get(zone) != now.astimezone(ZoneInfo(zone)).date().isoformat()}
    if record and not due:
        return
    # Also limit provider retries during an outage, including across restarts.
    if record and record.fetched_at.replace(tzinfo=timezone.utc) > now - timedelta(minutes=5):
        return
    try:
        value = (fetch_fn or fetch_quote)('TRX')
        stamp = datetime.fromisoformat(value['as_of'].replace('Z','+00:00'))
        age = (now-stamp).total_seconds()
        if age < -3600 or age > 3600: raise ValueError('Quote is too old')
        positive(value['usd_rate'])
    except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation, StopIteration):
        # Failed fetch is recorded without replacing the last good quote.
        value = None
    if not record:
        record = MarketQuote(currency='TRX', checked_day='')
        db.add(record)
    if value:
        payload['quote'] = value
        payload['success_at'] = now.isoformat()
        payload['days'] = {**payload.get('days',{}), **due}
    record.payload = json.dumps(payload)
    record.fetched_at = now
    record.checked_day = now.date().isoformat()
    db.commit()


def stored_trx():
    import json
    from backend.persistence.database import Session
    from backend.persistence.models import MarketQuote
    from sqlalchemy.exc import SQLAlchemyError
    try:
        with Session() as db:
            row = db.get(MarketQuote, 'TRX')
            if not row: return None
            payload = json.loads(row.payload)
        if not payload.get('quote'): return None
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(payload['success_at'])).total_seconds()
        if age > 3*86400: return None
        return {**payload['quote'], 'stale': age > 26*3600}
    except (SQLAlchemyError, ValueError, KeyError):
        return None


def grouped_by_usd(result):
    """Rank whole multi-currency accounts; incomplete valuations come last."""
    groups = {}
    quotes = {q['currency']: Decimal(q['usd_rate']) for q in result['quotes']}
    for account in result['accounts']:
        identifier = account.get('group_id') or account['id']
        group = groups.setdefault(identifier, {'id':identifier,'name':account['name'],'balances':[], 'usd':Decimal(0),'complete':True})
        group['balances'].append(account)
        amount = Decimal(account['balance'])
        rate = quotes.get(account['currency'])
        if amount == 0: continue
        if rate is None: group['complete'] = False
        else: group['usd'] += amount * rate
    return sorted(groups.values(), key=lambda g: (not g['complete'], -g['usd'] if g['complete'] else Decimal(0), g['name'].casefold(), g['id']))


def current_balance_message(result, *, include_rates=True):
    lines = [balance_heading(result), tr('Accounts · highest USD balance first')]
    groups = grouped_by_usd(result)
    for group in groups:
        lines.append(f"{group['name']}:")
        lines.append('  '+' · '.join(f"{report_amount(a['balance'])} {a['currency']}" for a in group['balances']))
    if not groups: lines.append(tr('No accounts included.'))
    if include_rates:
        details = [f"{display_quote(q)} · {tr(q['source'])} · {q['as_of']}" for q in result['quotes'] if q['currency']!='USD']
        if details: lines += [tr('Exchange rates')]+details
    if result['missing']: lines.append(tr('Rates unavailable: ')+', '.join(result['missing'])+(tr('. The converted total cannot be calculated.') if result.get('unavailable') else tr('. Unpriced accounts are listed last and excluded from the converted total where no rate is available.')))
    if result['stale']: lines.append(tr('Cached exchange rates used; estimate may be out of date.'))
    return '\n'.join(lines)


def display_quote(quote):
    value = quote['display_rate']
    for suffix in (' (official)', ' (blue venta)'):
        if value.endswith(suffix):
            return value[:-len(suffix)] + tr(suffix)
    return value
