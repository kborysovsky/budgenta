"""Read-only integration check. Never prints tokens or raw API errors."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/'.env')
import os
import httpx
from backend.services import rates

def main():
    token=os.getenv('TELEGRAM_BOT_TOKEN','')
    if token:
        try:
            with httpx.Client(timeout=10) as client:
                data=client.get(f'https://api.telegram.org/bot{token}/getMe').json()
                if data.get('ok'):
                    username=data['result']['username']
                    print('Telegram connection OK; configured username matches:', username==os.getenv('TELEGRAM_BOT_USERNAME','').lstrip('@'))
                else: print('Telegram rejected the configured token.')
                webhook=client.get(f'https://api.telegram.org/bot{token}/getWebhookInfo').json()
                print('Telegram webhook present:',bool(webhook.get('result',{}).get('url')))
        except httpx.HTTPError:
            print('Telegram network request failed. No credentials logged.')
    for currency in ['ARS','EUR','UAH','USDT','TRX','BTC','ETH']:
        value=rates.quote(currency)
        print(currency+': '+(f"{value['display_rate']} | {value['source']} | {value['as_of']}" if value else 'rate unavailable'))

if __name__=='__main__': main()
