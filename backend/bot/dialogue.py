"""Telegram transaction forms; financial rules live in the shared services."""
import json
import os
from datetime import date
from decimal import Decimal
from pydantic import ValidationError
from backend.services import budget as service
from backend.services import reporting, exchanges, categories
from backend.core.calendar import today
from backend.persistence.models import BotState
from backend.core.schemas import NewEntry, Transfer, Exchange

HOME = '⌂ Home'
BACK = '← Back'
MENU = [['↑ Expense', '↓ Income'], ['↔ Transfer', '⇄ Exchange'], ['Current state'], ['Open website']]
FIELDS = {
    'income': ['account_id', 'amount', 'category', 'note', 'date'],
    'expense': ['account_id', 'amount', 'category', 'note', 'date'],
    'transfer': ['source_id', 'destination_id', 'amount', 'date'],
    'exchange': ['source_id', 'destination_id', 'amount', 'rate', 'date'],
}
LABELS = {'account_id': 'Pay from / receive into', 'source_id': 'From account',
          'destination_id': 'To account', 'amount': 'Amount', 'rate': 'Custom exchange rate',
          'received': 'Amount received', 'category': 'Category', 'note': 'Note (optional)', 'date': 'Date (YYYY-MM-DD)'}
ACTIONS = {'↑ Expense': 'expense', '↓ Income': 'income', '↔ Transfer': 'transfer', '⇄ Exchange': 'exchange',
           **{'/' + action: action for action in FIELDS}}


def fields_for(state):
    fields = FIELDS[state['action']]
    if state['action'] == 'exchange' and state.get('exchange_input') == 'received':
        return ['received' if field == 'rate' else field for field in fields]
    return fields


def reply(text, buttons=None, inline=None):
    result = {'text': text, 'reply_markup': {'keyboard': buttons or MENU, 'resize_keyboard': True, 'is_persistent': True}}
    if inline:
        result['reply_markup'] = {'inline_keyboard': inline}
    return result


def set_state(db, user_id, state):
    record = db.get(BotState, user_id)
    if not record:
        record = BotState(user_id=user_id, payload='{}')
        db.add(record)
    record.payload = json.dumps(state)
    db.commit()


def destinations(db, uid, state):
    source = service.owned_account(db, uid, state['data']['source_id'])
    return [a for a in service.accounts(db, uid) if a['id'] != source.id and
            ((a['currency'] == source.currency) == (state['action'] == 'transfer'))]


def choices(db, uid, state, field):
    if field in ('account_id', 'source_id', 'destination_id'):
        accounts = destinations(db, uid, state) if field == 'destination_id' else service.accounts(db, uid)
        return [f"#{a['id']} {a['name'][:35]} · {a['currency']}" for a in accounts]
    if field == 'category':
        return categories.choices(db, uid)[state['action']]
    if field == 'note': return ['Skip']
    if field == 'date': return ['Today']
    if field == 'rate': return ['Enter received amount']
    if field == 'received': return ['Enter rate']
    if field == 'amount' and state['action'] in ('expense', 'transfer', 'exchange'):
        return ['All']
    return []


def prompt(db, uid, state):
    fields, data, action = fields_for(state), state['data'], state['action']
    if state.get('category_choice_pending'):
        return reply(f"Keep “{data['category']}” in your {action} categories for future use?",
                     [['Save category', 'Use once'], [BACK, HOME], ['Cancel']])
    if state['step'] == len(fields):
        if action in ('transfer', 'exchange'):
            source = service.owned_account(db, uid, data['source_id'])
            target = service.owned_account(db, uid, data['destination_id'])
            received = data['amount']
            rate_line = ''
            if action == 'exchange':
                result = exchanges.preview(db, uid, Exchange(**data))
                received = result['received']
                rate_line = f"\n{'Calculated rate: ' if result['rate_calculated'] else ''}1 {source.currency} {'≈' if result['rate_approximate'] else '='} {result['rate']} {target.currency}"
                if result['rate_approximate']:
                    rate_line += '\nDisplayed rate rounded; received amount stays exact.'
            text = (f"Review {action}:\nFrom {source.name}: −{data['amount']} {source.currency}"
                    f"\nTo {target.name}: +{received} {target.currency}{rate_line}\n{data['date']}"
                    '\nBoth balances update together; this is not income or an expense.')
        else:
            account = service.owned_account(db, uid, data['account_id'])
            text = (f"Review {action}:\n{account.name} · {data['amount']} {account.currency}"
                    f"\n{data['category']} · {data['date']}\n{data['note'] or 'No note'}")
            if data.get('save_category'):
                text += '\nSave this category for future use.'
        return reply(text, [['Confirm', 'Cancel'], [BACK, HOME]])
    field = fields[state['step']]
    options = choices(db, uid, state, field)
    text = LABELS[field] + ':'
    if field == 'category':
        text += '\nChoose a category or type your own purpose.'
    if field in ('account_id', 'source_id', 'destination_id') and not options:
        text += '\nNo compatible accounts. Add a currency/account on the website, or go Back.'
    if field == 'amount' and action in ('transfer', 'exchange'):
        source = service.owned_account(db, uid, data['source_id'])
        text = f'Amount to send in {source.currency}:'
    if field == 'amount' and action in ('expense', 'transfer', 'exchange'):
        text += '\nAll uses the available balance of this account and currency.'
    if field == 'rate':
        source = service.owned_account(db, uid, data['source_id'])
        target = service.owned_account(db, uid, data['destination_id'])
        text = (f'Custom rate: how many {target.currency} for 1 {source.currency}?'
                '\nType your rate, or choose Enter received amount to calculate the rate automatically.')
    if field == 'received':
        target = service.owned_account(db, uid, data['destination_id'])
        text = f'Final amount received in {target.currency}:\nThe rate will be calculated automatically; this exact amount will be saved.'
    return reply(text, [[choice] for choice in options] + [[BACK, HOME], ['Cancel']])


def parse(db, uid, state, text):
    field = fields_for(state)[state['step']]
    data = state['data']
    if field in ('account_id', 'source_id', 'destination_id'):
        identifier = int(text.split()[0].lstrip('#'))
        service.owned_account(db, uid, identifier)
        if field == 'destination_id' and identifier not in {a['id'] for a in destinations(db, uid, state)}:
            raise ValueError('Choose a different account with ' + ('the same currency.' if state['action'] == 'transfer' else 'a different currency.'))
        return identifier
    if field in ('amount', 'rate', 'received'):
        if text.strip().casefold() == 'all' and field == 'amount' and state['action'] in ('expense', 'transfer', 'exchange'):
            identifier = data.get('account_id', data.get('source_id'))
            service.owned_account(db, uid, identifier)
            amount = service.balance(db, identifier)
            if amount <= 0:
                raise ValueError('There is no positive balance available in this account and currency.')
        else:
            amount = Decimal(text)
        if not amount.is_finite() or amount <= 0:
            raise ValueError('Enter a positive number.')
        if field in ('rate', 'received'):
            Exchange(**data, **{field: amount})
            if field == 'received':
                target = service.owned_account(db, uid, data['destination_id'])
                service.validate_amount(target.currency, amount)
        else:
            identifier = data.get('account_id', data.get('source_id'))
            account = service.owned_account(db, uid, identifier)
            # Enforce the same magnitude limits as the HTTP input before advancing.
            NewEntry(account_id=identifier, kind='income', amount=amount)
            service.validate_amount(account.currency, amount)
            if state['action'] in ('transfer', 'exchange') and service.balance(db, identifier) < amount:
                raise ValueError('Not enough funds in this account.')
        return format(amount, 'f')
    if field == 'date':
        day = today() if text == 'Today' else date.fromisoformat(text)
        service.check_date(db, uid, day)
        return day.isoformat()
    if field == 'note' and text == 'Skip': return ''
    if field == 'category':
        return NewEntry(account_id=data['account_id'], kind=state['action'], amount=data['amount'], category=text).category
    limit = 60 if field == 'category' else 300
    if not text.strip() or len(text) > limit:
        raise ValueError(f'Enter 1–{limit} characters.')
    return text.strip()


def handle(db, user, text):
    uid = user.id
    record = db.get(BotState, uid)
    state = json.loads(record.payload) if record else {}
    if state.get('action') not in FIELDS:
        state = {}
        if record:
            set_state(db, uid, {})
    if text in (HOME, '/home', '/start', '/help', '/menu'):
        set_state(db, uid, {})
        return reply('Budgenta · Your budget agent. Add income or expenses, transfer or exchange money, or check your current state. Manage accounts, savings, debts, goals, and report schedules on the website.')
    try:
        if text in (BACK, '/back', 'Cancel', '/cancel'):
            if state and text in (BACK, '/back') and state['step'] > 0:
                state['step'] -= 1
                state.pop('category_choice_pending', None)
                keep = fields_for(state)[:state['step']]
                if 'category' in keep:
                    keep = [*keep, 'save_category']
                state['data'] = {k: v for k, v in state['data'].items() if k in keep}
                set_state(db, uid, state)
                return prompt(db, uid, state)
            set_state(db, uid, {})
            return reply('Choose an action.')
        if not state:
            if text in ('Current state', '/balance', '/report'):
                set_state(db, uid, {})
                return reply(reporting.current_state(db, uid))
            if text in ('Open website', '/web'):
                return reply('Manage your budget and report schedules on the website:\n' + os.getenv('APP_ORIGIN', 'http://localhost:8000'))
            if text in ACTIONS:
                state = {'action': ACTIONS[text], 'step': 0, 'data': {}}
                set_state(db, uid, state)
                return prompt(db, uid, state)
            return reply('Use the buttons below to add a transaction or read a report. Management is available on the website.')
        fields = fields_for(state)
        if state['action'] == 'exchange' and state['step'] == 3 and text in ('Enter rate', 'Enter received amount'):
            state['exchange_input'] = 'rate' if text == 'Enter rate' else 'received'
            state['data'].pop('rate', None)
            state['data'].pop('received', None)
            set_state(db, uid, state)
            return prompt(db, uid, state)
        if state.get('category_choice_pending'):
            if text not in ('Save category', 'Use once'):
                return prompt(db, uid, state)
            state['data']['save_category'] = text == 'Save category'
            state.pop('category_choice_pending')
            set_state(db, uid, state)
            return prompt(db, uid, state)
        if state['step'] == len(fields):
            if text != 'Confirm': return prompt(db, uid, state)
            if state['action'] == 'exchange':
                exchanges.exchange(db, uid, Exchange(**state['data']))
            elif state['action'] == 'transfer':
                service.transfer(db, uid, Transfer(**state['data']))
            else:
                service.add_entry(db, uid, NewEntry(kind=state['action'], **state['data']))
            set_state(db, uid, {})
            return reply('Saved. Your balances and website are up to date.')
        field = fields[state['step']]
        # Build the next prompt before persisting, so an invalid review stays editable.
        value = parse(db, uid, state, text)
        candidate = {**state, 'step': state['step'] + 1, 'data': {**state['data'], field: value}}
        if field == 'category' and value.casefold() not in {name.casefold() for name in categories.choices(db, uid)[state['action']]}:
            candidate['category_choice_pending'] = True
        response = prompt(db, uid, candidate)
        set_state(db, uid, candidate)
        return response
    except (ValueError, ArithmeticError, ValidationError, IndexError) as exc:
        detail = '; '.join(e['msg'] for e in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
        try:
            response = prompt(db, uid, state) if state else reply('Choose an action.')
        except (ValueError, ArithmeticError, IndexError):
            # Keep Back/Home available even if an account changed during confirmation.
            if state.get('action') in ('transfer', 'exchange'):
                response = reply('Use Back to correct the transaction, or Home to start again.', [[BACK, HOME], ['Cancel']])
            else:
                set_state(db, uid, {})
                response = reply('Start a new transaction to choose an active account.')
        response['text'] = 'Could not save: ' + detail + '\n\n' + response['text']
        return response
