"""Apply Budgenta's Telegram profile once; never send messages or log credentials."""
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
NAME = 'Budgenta'
SHORT_DESCRIPTION = 'Budgenta · Your budget agent. Track spending, transfers, savings, and goals.'
DESCRIPTION = (
    'Your budget agent. Add income and expenses, transfer or exchange money, '
    'and check your current balances here. Receive your scheduled budget reports '
    'in this chat. Manage accounts, savings, debts, goals, and report settings '
    'on the Budgenta website.'
)


def main():
    load_dotenv(ROOT / '.env')
    token = os.getenv('TELEGRAM_BOT_TOKEN', '')
    username = os.getenv('TELEGRAM_BOT_USERNAME', '').lstrip('@')
    if not token or not username:
        raise SystemExit('Configure TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_USERNAME first.')
    avatar = ROOT / 'frontend/public/budgenta-avatar.jpg'
    if not avatar.is_file():
        raise SystemExit('Missing Budgenta avatar asset.')

    try:
        with httpx.Client(base_url=f'https://api.telegram.org/bot{token}/', timeout=30) as client:
            def call(method, **kwargs):
                response = client.post(method, **kwargs)
                data = response.json()
                if not response.is_success or not data.get('ok'):
                    raise SystemExit(f'Telegram rejected {method}; earlier updates may have succeeded.')
                return data['result']

            me = call('getMe')
            if me.get('username', '').lower() != username.lower():
                raise SystemExit('Configured username does not match this token. No changes made.')
            call('setMyName', json={'name': NAME})
            call('setMyShortDescription', json={'short_description': SHORT_DESCRIPTION})
            call('setMyDescription', json={'description': DESCRIPTION})
            with avatar.open('rb') as photo:
                call('setMyProfilePhoto',
                     data={'photo': '{"type":"static","photo":"attach://profile_photo"}'},
                     files={'profile_photo': ('budgenta-avatar.jpg', photo, 'image/jpeg')})
            expected = [
                ('getMyName', 'name', NAME),
                ('getMyShortDescription', 'short_description', SHORT_DESCRIPTION),
                ('getMyDescription', 'description', DESCRIPTION),
            ]
            for method, field, value in expected:
                if call(method).get(field) != value:
                    raise SystemExit(f'Telegram profile verification failed at {method}.')
            print('Budgenta bot name, descriptions, and profile photo updated successfully.')
            print('The existing Telegram username is unchanged.')
    except (httpx.HTTPError, ValueError):
        raise SystemExit('Telegram request failed; earlier updates may have succeeded. No credentials logged.') from None


if __name__ == '__main__':
    main()
