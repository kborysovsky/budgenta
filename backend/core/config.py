"""Fail closed when a public deployment has unsafe authentication settings."""
import os
import re
from urllib.parse import urlsplit

LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}


def public_origin():
    return urlsplit(os.getenv('APP_ORIGIN', 'http://localhost:8000'))


def validate_config():
    origin = public_origin()
    try:
        port = origin.port
    except ValueError:
        raise RuntimeError('APP_ORIGIN must contain a valid port.') from None
    if (origin.scheme not in ('http', 'https') or not origin.hostname
            or origin.username or origin.password or origin.query or origin.fragment
            or origin.path or (port is not None and port < 1)):
        raise RuntimeError('APP_ORIGIN must be an origin such as https://budget.example.com, with no path or trailing slash.')
    if origin.hostname not in LOCAL_HOSTS:
        if origin.scheme != 'https' or os.getenv('COOKIE_SECURE') != 'true':
            raise RuntimeError('Public hosting requires HTTPS APP_ORIGIN and COOKIE_SECURE=true.')
        if not os.getenv('TELEGRAM_BOT_TOKEN') or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', os.getenv('TELEGRAM_BOT_USERNAME', '').lstrip('@')):
            raise RuntimeError('Public hosting requires a Telegram bot token and username.')
