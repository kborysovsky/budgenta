"""Explicit UI translations; financial records always retain their original values."""
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

LANGUAGES = {'en': 'English', 'ru': 'Русский', 'uk': 'Українська', 'es': 'Español'}
_language = ContextVar('budgenta_language', default='en')
_root = Path(__file__).resolve().parents[2] / 'locales'
CATALOGS = {code: json.loads((_root / f'{code}.json').read_text()) for code in LANGUAGES if code != 'en'}


def tr(message, **values):
    translated = CATALOGS.get(_language.get(), {}).get(message, message)
    return translated.format(**values) if values else translated


@contextmanager
def language_scope(language):
    token = _language.set(language if language in LANGUAGES else 'en')
    try:
        yield
    finally:
        _language.reset(token)


def localized(function):
    """Scope each user's bot/report work, also when invoked directly by jobs."""
    @wraps(function)
    def wrapped(db, user_id, *args, **kwargs):
        from backend.services.reporting import get_preferences
        uid = getattr(user_id, 'id', user_id)
        with language_scope(get_preferences(db, uid)['language']):
            return function(db, user_id, *args, **kwargs)
    return wrapped


def category_label(name, kind=None):
    from backend.services.categories import EXPENSE_CATEGORIES, INCOME_CATEGORIES
    defaults = EXPENSE_CATEGORIES if kind == 'expense' else INCOME_CATEGORIES if kind == 'income' else EXPENSE_CATEGORIES + INCOME_CATEGORIES
    return tr(name) if name in defaults else name


def error_message(message):
    precision = re.fullmatch(r'(USD|EUR|ARS|UAH|USDT|TRX|BTC|ETH) allows at most (\d+) decimal places\.', message)
    if precision:
        return tr('{currency} allows at most {places} decimal places.', currency=precision[1], places=precision[2])
    if message.startswith(('invalid literal for int', 'Invalid isoformat string')):
        return tr('Check the amount, date, and required fields.')
    return tr(message)
