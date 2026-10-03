"""Telegram transaction forms; financial rules live in the shared services."""
from backend.core.i18n import tr, localized, language_scope, LANGUAGES, CATALOGS, category_label, error_message
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
MENU = [['↑ Expense', '↓ Income'], ['↔ Transfer', '⇄ Exchange'], ['Current state'], ['Open website'], ['Language']]
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


CONTROL_BUTTONS = {HOME, BACK, *ACTIONS, 'Current state', 'Open website', 'Language', 'Save category', 'Use once', 'Cancel', 'Confirm', 'Skip', 'Today', 'All', 'Enter rate', 'Enter received amount'}

def fields_for(state):
    fields = FIELDS[state['action']]
    if state['action'] == 'exchange' and state.get('exchange_input') == 'received':
        return ['received' if field == 'rate' else field for field in fields]
    return fields


def reply(text, buttons=None, inline=None, raw_rows=0):
    result = {'text': text, 'reply_markup': {'keyboard': [[tr(button) if index >= raw_rows and button in CONTROL_BUTTONS else button for button in row] for index, row in enumerate(buttons or MENU)], 'resize_keyboard': True, 'is_persistent': True}}
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
        return [category_label(name, state['action']) for name in categories.choices(db, uid)[state['action']]]
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
        return reply(tr('Keep “{category}” in your {action} categories for future use?', category=category_label(data['category'], action), action=tr(action)),
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
                rate_line = f"\n{tr('Calculated rate: ') if result['rate_calculated'] else ''}1 {source.currency} {'≈' if result['rate_approximate'] else '='} {result['rate']} {target.currency}"
                if result['rate_approximate']:
                    rate_line += '\n' + tr('Displayed rate rounded; received amount stays exact.')
            text = (tr('Review {action}:\nFrom {name}: −{amount} {currency}', action=tr(action), name=source.name, amount=data['amount'], currency=source.currency)
                    + '\n' + tr('To {name}: +{amount} {currency}', name=target.name, amount=received, currency=target.currency) + rate_line + '\n' + data['date']
                    + '\n' + tr('Both balances update together; this is not income or an expense.'))
        else:
            account = service.owned_account(db, uid, data['account_id'])
            text = (tr('Review {action}:', action=tr(action)) + f"\n{account.name} · {data['amount']} {account.currency}"
                    f"\n{category_label(data['category'], action)} · {data['date']}\n{data['note'] or tr('No note')}")
            if data.get('save_category'):
                text += '\n' + tr('Save this category for future use.')
        return reply(text, [['Confirm', 'Cancel'], [BACK, HOME]])
    field = fields[state['step']]
    options = choices(db, uid, state, field)
    text = tr(LABELS[field]) + ':'
    if field == 'category':
        text += '\n' + tr('Choose a category or type your own purpose.')
    if field in ('account_id', 'source_id', 'destination_id') and not options:
        text += '\n' + tr('No compatible accounts. Add a currency/account on the website, or go Back.')
    if field == 'amount' and action in ('transfer', 'exchange'):
        source = service.owned_account(db, uid, data['source_id'])
        text = tr('Amount to send in {currency}:', currency=source.currency)
    if field == 'amount' and action in ('expense', 'transfer', 'exchange'):
        text += '\n' + tr('All uses the available balance of this account and currency.')
    if field == 'rate':
        source = service.owned_account(db, uid, data['source_id'])
        target = service.owned_account(db, uid, data['destination_id'])
        text = (tr('Custom rate: how many {target} for 1 {source}?', target=target.currency, source=source.currency)
                + '\n' + tr('Type your rate, or choose Enter received amount to calculate the rate automatically.'))
    if field == 'received':
        target = service.owned_account(db, uid, data['destination_id'])
        text = tr('Final amount received in {currency}:\nThe rate will be calculated automatically; this exact amount will be saved.', currency=target.currency)
    return reply(text, [[choice] for choice in options] + [[BACK, HOME], ['Cancel']],
                 raw_rows=len(options) if field in ('category', 'account_id', 'source_id', 'destination_id') else 0)


def parse(db, uid, state, text):
    field = fields_for(state)[state['step']]
    data = state['data']
    if field in ('account_id', 'source_id', 'destination_id'):
        identifier = int(text.split()[0].lstrip('#'))
        service.owned_account(db, uid, identifier)
        if field == 'destination_id' and identifier not in {a['id'] for a in destinations(db, uid, state)}:
            raise ValueError(tr('Choose a different account with the same currency.' if state['action'] == 'transfer' else 'Choose a different account with a different currency.'))
        return identifier
    if field in ('amount', 'rate', 'received'):
        if text.strip().casefold() == 'all' and field == 'amount' and state['action'] in ('expense', 'transfer', 'exchange'):
            identifier = data.get('account_id', data.get('source_id'))
            service.owned_account(db, uid, identifier)
            amount = service.balance(db, identifier)
            if amount <= 0:
                raise ValueError('There is no positive balance available in this account and currency.')
        else:
            amount = Decimal(text.replace(',', '.'))
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
        raise ValueError(tr('Enter 1–{limit} characters.', limit=limit))
    return text.strip()


@localized
def handle(db, user, text):
    record = db.get(BotState, user.id)
    previous = json.loads(record.payload) if record else {}
    if text == '/language' or (previous.get('action') not in FIELDS and text in {'Language', *(c.get('Language') for c in CATALOGS.values())}):
        set_state(db, user.id, {'language_menu': True})
        return reply(tr('Choose your language.'), [[name] for name in LANGUAGES.values()] + [[HOME]])
    if previous.get('language_menu') and text in LANGUAGES.values():
        code = next(code for code, name in LANGUAGES.items() if name == text)
        reporting.save_language(db, user.id, code)
        set_state(db, user.id, {})
        with language_scope(code):
            return reply(tr('Language saved. Choose an action.'))
    # Only map control labels at steps where they are controls. User text stays literal.
    field = None
    if previous.get('action') in FIELDS and previous.get('step', 0) < len(fields_for(previous)):
        field = fields_for(previous)[previous['step']]
    controls = {HOME, BACK, 'Cancel'}
    if not previous or previous.get('language_menu'): controls |= CONTROL_BUTTONS
    if previous.get('category_choice_pending'): controls |= {'Save category', 'Use once'}
    elif previous.get('action') in FIELDS and previous.get('step') == len(fields_for(previous)): controls.add('Confirm')
    elif field == 'note': controls.add('Skip')
    elif field == 'date': controls.add('Today')
    elif field == 'amount': controls.add('All')
    elif field in ('rate', 'received'): controls |= {'Enter rate', 'Enter received amount'}
    text = next((button for button in controls if text in {button, *(c.get(button) for c in CATALOGS.values())}), text)
    if field == 'category' and text not in controls and not previous.get('category_choice_pending'):
        options = categories.choices(db, user.id)[previous['action']]
        # Prefer exact custom names over a translated default label.
        if text not in options:
            text = next((name for name in options if text in {category_label(name, previous['action']), *(c.get(name) for c in CATALOGS.values() if name in (categories.EXPENSE_CATEGORIES if previous['action'] == 'expense' else categories.INCOME_CATEGORIES))}), text)
    return _handle(db, user, text)


def _handle(db, user, text):
    uid = user.id
    record = db.get(BotState, uid)
    state = json.loads(record.payload) if record else {}
    if state.get('action') not in FIELDS:
        state = {}
        if record:
            set_state(db, uid, {})
    if text in (HOME, '/home', '/start', '/help', '/menu'):
        set_state(db, uid, {})
        return reply(tr('Budgenta · Your budget agent. Add income or expenses, transfer or exchange money, or check your current state. Manage accounts, savings, debts, goals, and report schedules on the website.'))
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
            return reply(tr('Choose an action.'))
        if not state:
            if text in ('Current state', '/balance', '/report'):
                set_state(db, uid, {})
                return reply(reporting.current_state(db, uid))
            if text in ('Open website', '/web'):
                return reply(tr('Manage your budget and report schedules on the website:') + '\n' + os.getenv('APP_ORIGIN', 'http://localhost:8000'))
            if text in ACTIONS:
                state = {'action': ACTIONS[text], 'step': 0, 'data': {}}
                set_state(db, uid, state)
                return prompt(db, uid, state)
            return reply(tr('Use the buttons below to add a transaction or read a report. Management is available on the website.'))
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
            return reply(tr('Saved. Your balances and website are up to date.'))
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
        detail = tr('Check the amount, date, and required fields.') if isinstance(exc, (ValidationError, ArithmeticError)) else str(exc)
        try:
            response = prompt(db, uid, state) if state else reply(tr('Choose an action.'))
        except (ValueError, ArithmeticError, IndexError):
            # Keep Back/Home available even if an account changed during confirmation.
            if state.get('action') in ('transfer', 'exchange'):
                response = reply(tr('Use Back to correct the transaction, or Home to start again.'), [[BACK, HOME], ['Cancel']])
            else:
                set_state(db, uid, {})
                response = reply(tr('Start a new transaction to choose an active account.'))
        response['text'] = tr('Could not save: ') + error_message(detail) + '\n\n' + response['text']
        return response
