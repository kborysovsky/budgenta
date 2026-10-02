"""Authenticated field encryption. Keys live outside the database."""
import hashlib
import hmac
import os
from datetime import date
from decimal import Decimal
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

PREFIX = 'enc:v1:'

def cipher():
    keys = os.getenv('DATA_ENCRYPTION_KEYS', '').split(',')
    try:
        return MultiFernet([Fernet(key.strip().encode()) for key in keys if key.strip()])
    except (ValueError, TypeError):
        raise RuntimeError('Set DATA_ENCRYPTION_KEYS to a Fernet key before starting Budgenta.') from None

def encrypt(value):
    return PREFIX + cipher().encrypt(str(value).encode()).decode()

def decrypt(value):
    if not isinstance(value, str) or not value.startswith(PREFIX):
        raise RuntimeError('Unencrypted data found; run the database migration.')
    return cipher().decrypt(value[len(PREFIX):].encode()).decode()

def identity_key(telegram_id):
    key = os.getenv('IDENTITY_HASH_KEY', '')
    if len(key) < 32:
        raise RuntimeError('Set IDENTITY_HASH_KEY to a random secret of at least 32 characters.')
    return hmac.new(key.encode(), str(telegram_id).encode(), hashlib.sha256).hexdigest()

def identity_default(context):
    return identity_key(context.get_current_parameters()['telegram_id'])

class Encrypted(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, value_type='str'):
        self.value_type = value_type
        super().__init__()

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt(value.isoformat() if self.value_type == 'date' else value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        plain = decrypt(value)
        return {'decimal': Decimal, 'date': date.fromisoformat, 'int': int}.get(self.value_type, str)(plain)
